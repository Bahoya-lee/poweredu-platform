"""牛顿-拉夫逊法潮流计算（国产自主内核）。

采用极坐标形式的功率不平衡量方程，雅可比矩阵按解析公式装配，
用列主元高斯消元求解修正量。支持 PV/PQ/平衡节点、变压器非标准变比、
线路充电电容与母线并联补偿，并可选执行 PV 母线无功越限转 PQ。
"""

from __future__ import annotations

import cmath
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .linalg import solve as linalg_solve
from .models import Branch, Case

DEFAULT_TOL = 1e-8
DEFAULT_MAX_ITER = 30


def bus_index(case: Case) -> Dict[int, int]:
    """母线编号 -> 数组下标。"""
    return {bus.id: index for index, bus in enumerate(case.buses)}


def build_ybus(
    case: Case,
    skip_branch_ids: Optional[Iterable[int]] = None,
    extra_shunts: Optional[Dict[int, complex]] = None,
    include_load_shunts: Optional[Dict[int, complex]] = None,
) -> List[List[complex]]:
    """组装节点导纳矩阵 Ybus（复数方阵）。

    Parameters
    ----------
    skip_branch_ids:
        需要从网络中切除的支路编号集合（暂态稳定仿真用）。
    extra_shunts:
        母线编号 -> 追加的并联导纳（标幺值），例如发电机次暂态电抗。
    include_load_shunts:
        母线编号 -> 负荷等效并联导纳（标幺值），把恒功率负荷近似为恒定阻抗。
    """
    n = len(case.buses)
    index = bus_index(case)
    ybus = [[0j for _ in range(n)] for _ in range(n)]
    skip = set(skip_branch_ids or ())

    for branch in case.branches:
        if not branch.status or branch.id in skip:
            continue
        i = index[branch.fbus]
        j = index[branch.tbus]
        series = 1.0 / complex(branch.r, branch.x)
        tap = branch.tap * cmath.exp(1j * math.radians(branch.shift))
        tap_sq = branch.tap ** 2
        y_ff = (series + 1j * branch.b / 2.0) / tap_sq
        y_ft = -series / tap.conjugate()
        y_tf = -series / tap
        y_tt = series + 1j * branch.b / 2.0
        ybus[i][i] += y_ff
        ybus[i][j] += y_ft
        ybus[j][i] += y_tf
        ybus[j][j] += y_tt

    for bus in case.buses:
        if bus.gs or bus.bs:
            ybus[index[bus.id]][index[bus.id]] += complex(bus.gs, bus.bs) / case.base_mva

    for bus_id, shunt in (extra_shunts or {}).items():
        ybus[index[bus_id]][index[bus_id]] += shunt

    for bus_id, shunt in (include_load_shunts or {}).items():
        ybus[index[bus_id]][index[bus_id]] += shunt

    return ybus


def _calc_injection(ybus: Sequence[Sequence[complex]], v: Sequence[complex]) -> Tuple[List[float], List[float]]:
    """由节点电压求各母线注入功率（标幺值）。"""
    p: List[float] = []
    q: List[float] = []
    for i, vi in enumerate(v):
        current = sum(ybus[i][j] * v[j] for j in range(len(v)))
        s = vi * current.conjugate()
        p.append(s.real)
        q.append(s.imag)
    return p, q


def solve_power_flow(
    case: Case,
    tol: float = DEFAULT_TOL,
    max_iter: int = DEFAULT_MAX_ITER,
    enforce_q_limits: bool = False,
    flat_start: bool = False,
) -> Dict[str, object]:
    """求解潮流，返回母线电压、支路潮流与收敛信息。"""
    problems = case.validate()
    if problems:
        return {
            "converged": False,
            "iterations": 0,
            "history": [],
            "buses": [],
            "branches": [],
            "generators": [],
            "summary": {},
            "error": "；".join(problems),
        }

    index = bus_index(case)
    n = len(case.buses)
    ybus = build_ybus(case)
    base = case.base_mva

    # 初始电压：默认沿用算例中保存的运行点，必要时改为平启动
    v: List[complex] = []
    for bus in case.buses:
        vm = 1.0 if (flat_start and bus.type == "PQ") else (bus.vm or 1.0)
        va = 0.0 if flat_start else math.radians(bus.va)
        v.append(cmath.rect(vm, va))

    pq = [i for i, bus in enumerate(case.buses) if bus.type == "PQ"]
    pv = [i for i, bus in enumerate(case.buses) if bus.type == "PV"]
    slack = [i for i, bus in enumerate(case.buses) if bus.type == "SLACK"]
    angle_idx = [i for i, bus in enumerate(case.buses) if bus.type != "SLACK"]

    p_spec = [0.0] * n
    q_spec = [0.0] * n
    for i, bus in enumerate(case.buses):
        pg, qg = case.gen_power_at(bus.id)
        p_spec[i] = (pg - bus.pd) / base
        q_spec[i] = (qg - bus.qd) / base

    history: List[Dict[str, float]] = []
    converged = False
    iteration = 0
    mismatch_norm = float("inf")
    angle_only: List[int] = list(angle_idx)
    pq_list: List[int] = list(pq)

    for iteration in range(1, max_iter + 1):
        p_calc, q_calc = _calc_injection(ybus, v)
        mismatch = [p_spec[i] - p_calc[i] for i in angle_only]
        mismatch += [q_spec[i] - q_calc[i] for i in pq_list]
        mismatch_norm = max((abs(x) for x in mismatch), default=0.0)
        history.append({"iter": iteration, "mismatch": mismatch_norm})
        if mismatch_norm < tol:
            converged = True
            break

        vm = [abs(x) for x in v]
        va = [cmath.phase(x) for x in v]
        g = [[ybus[i][j].real for j in range(n)] for i in range(n)]
        b = [[ybus[i][j].imag for j in range(n)] for i in range(n)]

        n_ang = len(angle_only)
        n_pq = len(pq_list)
        jac = [[0.0] * (n_ang + n_pq) for _ in range(n_ang + n_pq)]

        for row, i in enumerate(angle_only):
            for col, j in enumerate(angle_only):
                if i == j:
                    jac[row][col] = -q_calc[i] - b[i][i] * vm[i] ** 2
                else:
                    theta = va[i] - va[j]
                    jac[row][col] = vm[i] * vm[j] * (
                        g[i][j] * math.sin(theta) - b[i][j] * math.cos(theta)
                    )
            for col, j in enumerate(pq_list):
                if i == j:
                    jac[row][n_ang + col] = p_calc[i] / vm[i] + g[i][i] * vm[i]
                else:
                    theta = va[i] - va[j]
                    jac[row][n_ang + col] = vm[i] * (
                        g[i][j] * math.cos(theta) + b[i][j] * math.sin(theta)
                    )

        for row, i in enumerate(pq_list):
            base_row = n_ang + row
            for col, j in enumerate(angle_only):
                if i == j:
                    jac[base_row][col] = p_calc[i] - g[i][i] * vm[i] ** 2
                else:
                    theta = va[i] - va[j]
                    jac[base_row][col] = -vm[i] * vm[j] * (
                        g[i][j] * math.cos(theta) + b[i][j] * math.sin(theta)
                    )
            for col, j in enumerate(pq_list):
                if i == j:
                    jac[base_row][n_ang + col] = q_calc[i] / vm[i] - b[i][i] * vm[i]
                else:
                    theta = va[i] - va[j]
                    jac[base_row][n_ang + col] = vm[i] * (
                        g[i][j] * math.sin(theta) - b[i][j] * math.cos(theta)
                    )

        try:
            dx = linalg_solve(jac, mismatch)
        except ValueError as exc:
            return {
                "converged": False,
                "iterations": iteration,
                "history": history,
                "buses": [],
                "branches": [],
                "generators": [],
                "summary": {},
                "error": f"潮流雅可比矩阵求解失败：{exc}",
            }

        for offset, i in enumerate(angle_only):
            va[i] += dx[offset]
        for offset, i in enumerate(pq_list):
            vm[i] += dx[n_ang + offset]
            if vm[i] <= 0.0:
                vm[i] = 0.5
        v = [cmath.rect(vm[i], va[i]) for i in range(n)]

    p_calc, q_calc = _calc_injection(ybus, v)

    # 若开启无功限值校验，越限的 PV 母线降为 PQ 后重算
    if enforce_q_limits:
        converted = _convert_violating_pv(case, v, ybus, index, base, pv, q_calc)
        if converted:
            retry_case = case.clone()
            for bus_id, q_limited, vm_now in converted:
                bus = retry_case.bus(bus_id)
                bus.type = "PQ"
                bus.qd += -q_limited
                bus.vm = vm_now
            retry = solve_power_flow(retry_case, tol=tol, max_iter=max_iter, enforce_q_limits=False)
            retry["q_limit_converted"] = [bus_id for bus_id, _, _ in converted]
            retry["history"] = history + retry.get("history", [])
            return retry

    buses_out = []
    for i, bus in enumerate(case.buses):
        buses_out.append(
            {
                "id": bus.id,
                "name": bus.name,
                "type": bus.type,
                "vm": vm_of(v[i]),
                "va": math.degrees(cmath.phase(v[i])),
                "p": p_calc[i] * base,
                "q": q_calc[i] * base,
                "pd": bus.pd,
                "qd": bus.qd,
                "vmax": bus.vmax,
                "vmin": bus.vmin,
                "x": bus.x,
                "y": bus.y,
            }
        )

    branches_out = []
    for branch in case.branches:
        if not branch.status:
            continue
        branches_out.append(_branch_flow(case, branch, v, index, base))

    gens_out = []
    for gen in case.gens:
        i = index[gen.bus]
        if not gen.status or case.buses[i].type == "PQ":
            gens_out.append(
                {
                    "id": gen.id,
                    "name": gen.name,
                    "bus": gen.bus,
                    "pg": gen.pg,
                    "qg": gen.qg,
                    "vg": case.buses[i].vm,
                    "pmax": gen.pmax,
                    "pmin": gen.pmin,
                    "qmax": gen.qmax,
                    "qmin": gen.qmin,
                }
            )
            continue
        qg = q_calc[i] * base + case.buses[i].qd
        gens_out.append(
            {
                "id": gen.id,
                "name": gen.name,
                "bus": gen.bus,
                "pg": gen.pg,
                "qg": qg,
                "vg": case.buses[i].vm,
                "pmax": gen.pmax,
                "pmin": gen.pmin,
                "qmax": gen.qmax,
                "qmin": gen.qmin,
            }
        )

    total_load_p, total_load_q = case.total_load()
    slack_p = p_calc[index[case.slack_bus().id]] * base + case.slack_bus().pd
    slack_q = q_calc[index[case.slack_bus().id]] * base + case.slack_bus().qd
    loss_p = sum(b["loss_p"] for b in branches_out)
    loss_q = sum(b["loss_q"] for b in branches_out)

    return {
        "converged": converged,
        "iterations": iteration,
        "history": history,
        "buses": buses_out,
        "branches": branches_out,
        "generators": gens_out,
        "summary": {
            "base_mva": base,
            "total_load_p": total_load_p,
            "total_load_q": total_load_q,
            "slack_p": slack_p,
            "slack_q": slack_q,
            "total_gen_p": total_load_p + loss_p,
            "loss_p": loss_p,
            "loss_q": loss_q,
            "mismatch": mismatch_norm,
            "max_vm": max(b["vm"] for b in buses_out),
            "min_vm": min(b["vm"] for b in buses_out),
            "max_loading": max((b["loading"] for b in branches_out), default=0.0),
        },
    }


def vm_of(value: complex) -> float:
    """复电压幅值。"""
    return abs(value)


def _branch_flow(case: Case, branch: Branch, v: Sequence[complex], index: Dict[int, int], base: float) -> Dict[str, object]:
    """计算单条支路两端功率、损耗与负载率。"""
    i = index[branch.fbus]
    j = index[branch.tbus]
    series = 1.0 / complex(branch.r, branch.x)
    tap = branch.tap * cmath.exp(1j * math.radians(branch.shift))
    tap_sq = branch.tap ** 2
    y_ff = (series + 1j * branch.b / 2.0) / tap_sq
    y_ft = -series / tap.conjugate()
    y_tf = -series / tap
    y_tt = series + 1j * branch.b / 2.0

    i_from = y_ff * v[i] + y_ft * v[j]
    i_to = y_tf * v[i] + y_tt * v[j]
    s_from = v[i] * i_from.conjugate() * base
    s_to = v[j] * i_to.conjugate() * base
    loss = s_from + s_to
    flow_mag = max(abs(s_from), abs(s_to))
    loading = 100.0 * flow_mag / branch.rate if branch.rate > 1e-9 else 0.0
    return {
        "id": branch.id,
        "name": branch.name,
        "from": branch.fbus,
        "to": branch.tbus,
        "p_from": s_from.real,
        "q_from": s_from.imag,
        "p_to": s_to.real,
        "q_to": s_to.imag,
        "loss_p": loss.real,
        "loss_q": loss.imag,
        "loading": loading,
        "rate": branch.rate,
        "is_transformer": branch.is_transformer,
        "tap": branch.tap,
    }


def _convert_violating_pv(
    case: Case,
    v: Sequence[complex],
    ybus: Sequence[Sequence[complex]],
    index: Dict[int, int],
    base: float,
    pv: Sequence[int],
    q_calc: Sequence[float],
) -> List[Tuple[int, float, float]]:
    """找出无功越限的 PV 母线，返回 (母线编号, 限值, 当前电压)。"""
    violations: List[Tuple[int, float, float]] = []
    for i in pv:
        bus = case.buses[i]
        total_q = 0.0
        qmax = 0.0
        qmin = 0.0
        for gen in case.active_gens():
            if gen.bus != bus.id:
                continue
            total_q += gen.qg
            qmax += gen.qmax
            qmin += gen.qmin
        qg = q_calc[i] * base + bus.qd
        if qg > qmax + 1e-6:
            violations.append((bus.id, qmax, abs(v[i])))
        elif qg < qmin - 1e-6:
            violations.append((bus.id, qmin, abs(v[i])))
    return violations
