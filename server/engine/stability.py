"""暂态稳定时域仿真（经典二阶模型）。

流程：潮流求初值 → 负荷等值为恒定阻抗 → 接入发电机暂态电抗后用 Kron
降阶得到发电机内节点导纳矩阵 → 对转子摇摆方程做四阶龙格-库塔积分，
并支持二分搜索极限切除时间（CCT）。
"""

from __future__ import annotations

import cmath
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .linalg import invert, matmul
from .models import Case
from .powerflow import build_ybus, bus_index, solve_power_flow

FAULT_SHUNT = 1e4  # 故障点等效并联导纳（标幺值），模拟金属性接地
DEFAULT_T_END = 3.0
DEFAULT_DT = 0.01


class _Machine:
    """参与摇摆方程的发电机内电势模型。"""

    __slots__ = ("gen_id", "bus", "h", "d", "e_mag", "delta", "pm", "name")

    def __init__(self, gen_id: int, bus: int, name: str, h: float, d: float,
                 e_mag: float, delta: float, pm: float) -> None:
        self.gen_id = gen_id
        self.bus = bus
        self.name = name
        self.h = h
        self.d = d
        self.e_mag = e_mag
        self.delta = delta
        self.pm = pm


def _load_admittance(case: Case, v: Sequence[complex]) -> Dict[int, complex]:
    """把恒功率负荷折算成恒定并联导纳（标幺值）。"""
    shunts: Dict[int, complex] = {}
    for i, bus in enumerate(case.buses):
        if abs(bus.pd) < 1e-9 and abs(bus.qd) < 1e-9:
            continue
        vm = abs(v[i])
        if vm < 1e-6:
            continue
        s_load = complex(bus.pd, bus.qd) / case.base_mva
        shunts[bus.id] = shunts.get(bus.id, 0j) + (s_load / (vm ** 2)).conjugate()
    return shunts


def _reduce_to_generators(
    case: Case,
    ybus_network: Sequence[Sequence[complex]],
    gen_buses: Sequence[int],
    gen_reactances: Sequence[float],
) -> List[List[complex]]:
    """把网络收缩到发电机内电势节点（Kron 降阶）。"""
    index = bus_index(case)
    n = len(case.buses)
    m = len(gen_buses)
    size = n + m
    y = [[0j for _ in range(size)] for _ in range(size)]
    for i in range(n):
        for j in range(n):
            y[i][j] = ybus_network[i][j]

    for g, (bus_id, xd) in enumerate(zip(gen_buses, gen_reactances)):
        i = index[bus_id]
        internal = n + g
        y_admittance = 1.0 / complex(0.0, xd)
        y[i][i] += y_admittance
        y[i][internal] -= y_admittance
        y[internal][i] -= y_admittance
        y[internal][internal] += y_admittance

    y_nn = [row[:n] for row in y[:n]]
    y_ng = [row[n:] for row in y[:n]]
    y_gn = [row[:n] for row in y[n:]]
    y_gg = [row[n:] for row in y[n:]]

    inv_nn = invert(y_nn)
    return [
        [y_gg[i][j] - _dot3(y_gn[i], inv_nn, _column(y_ng, j)) for j in range(m)]
        for i in range(m)
    ]


def _dot3(left: Sequence[complex], middle: Sequence[Sequence[complex]], right: Sequence[complex]) -> complex:
    """计算 left · middle · right（行向量-矩阵-列向量）。"""
    total = 0j
    for a, row in zip(left, middle):
        if a == 0:
            continue
        total += a * sum(mij * rj for mij, rj in zip(row, right))
    return total


def _column(matrix: Sequence[Sequence[complex]], col: int) -> List[complex]:
    """取矩阵的一列。"""
    return [row[col] for row in matrix]


def _electrical_power(y_red: Sequence[Sequence[complex]], machines: Sequence[_Machine]) -> List[float]:
    """由内电势相角计算各机电磁功率（标幺值）。"""
    m = len(machines)
    pe = [0.0] * m
    for i in range(m):
        ei = machines[i].e_mag
        total = 0.0
        for j in range(m):
            y_ij = y_red[i][j]
            angle = machines[i].delta - machines[j].delta
            total += machines[j].e_mag * (
                y_ij.real * math.cos(angle) + y_ij.imag * math.sin(angle)
            )
        pe[i] = ei * total
    return pe


def _rk4_step(y_red, machines, state, dt, freq):
    """四阶龙格-库塔推进一步。"""
    def derivative(vec):
        for machine, delta, omega in zip(machines, vec[:len(machines)], vec[len(machines):]):
            machine.delta = delta
        pe = _electrical_power(y_red, machines)
        d_delta = [2.0 * math.pi * freq * (omega - 1.0) for omega in vec[len(machines):]]
        d_omega = [
            (machine.pm - pe[i] - machine.d * (vec[len(machines) + i] - 1.0)) / (2.0 * machine.h)
            for i, machine in enumerate(machines)
        ]
        return d_delta + d_omega

    m = len(machines)
    k1 = derivative(state)
    k2 = derivative([state[i] + 0.5 * dt * k1[i] for i in range(2 * m)])
    k3 = derivative([state[i] + 0.5 * dt * k2[i] for i in range(2 * m)])
    k4 = derivative([state[i] + dt * k3[i] for i in range(2 * m)])
    for i in range(2 * m):
        state[i] += dt / 6.0 * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i])
    for machine, delta in zip(machines, state[:m]):
        machine.delta = delta
    return state


def _max_relative_angle(machines: Sequence[_Machine]) -> float:
    """最大两机相对功角差（度）。"""
    if len(machines) < 2:
        return 0.0
    deltas = [machine.delta for machine in machines]
    return math.degrees(max(deltas) - min(deltas))


def resolve_branch_ids(case: Case, spec) -> List[int]:
    """把切除线路的多种写法解析为支路编号列表。

    支持三种写法：
    - 支路编号：``5``
    - 母线对：``(6, 7)``，自动匹配首末端（正反序均可）
    - 上述两者的列表：``[5, (6, 7)]``
    """
    if spec is None:
        return []
    if isinstance(spec, (int, float)):
        return [int(spec)]
    if isinstance(spec, dict):
        if "branch_id" in spec:
            return [int(spec["branch_id"])]
        if "from" in spec and "to" in spec:
            return resolve_branch_ids(case, (spec["from"], spec["to"]))
        return []
    if isinstance(spec, (tuple, list)):
        if len(spec) == 2 and all(isinstance(item, (int, float)) for item in spec):
            from_bus, to_bus = int(spec[0]), int(spec[1])
            matched = [
                branch.id
                for branch in case.branches
                if {branch.fbus, branch.tbus} == {from_bus, to_bus}
            ]
            return matched
        ids: List[int] = []
        for item in spec:
            ids.extend(resolve_branch_ids(case, item))
        return ids
    return []


def simulate_transient_stability(
    case: Case,
    fault_bus: int,
    trip_branch: Optional[Iterable[int]] = None,
    clearing_time: float = 0.15,
    t_end: float = DEFAULT_T_END,
    dt: float = DEFAULT_DT,
    fault_shunt: float = FAULT_SHUNT,
) -> Dict[str, object]:
    """按时域仿真判断给定切除时间下系统是否保持暂态稳定。"""
    problems = case.validate()
    if problems:
        return {"error": "；".join(problems), "stable": False, "curves": {"t": [], "machines": []}}

    power_flow = solve_power_flow(case)
    if not power_flow.get("converged"):
        return {
            "error": power_flow.get("error", "潮流未收敛，无法启动暂态仿真"),
            "stable": False,
            "curves": {"t": [], "machines": []},
        }

    index = bus_index(case)
    if fault_bus not in index:
        return {"error": f"算例中不存在母线 {fault_bus}", "stable": False,
                "curves": {"t": [], "machines": []}}

    gen_case = case.clone()
    gens = gen_case.active_gens()
    if len(gens) < 2:
        return {"error": "暂态稳定仿真至少需要两台投运发电机", "stable": False,
                "curves": {"t": [], "machines": []}}

    v_pre = [cmath.rect(item["vm"], math.radians(item["va"])) for item in power_flow["buses"]]
    load_shunts = _load_admittance(gen_case, v_pre)

    machines: List[_Machine] = []
    for gen in gens:
        i = index[gen.bus]
        vm = v_pre[i]
        pg, qg = gen_case.gen_power_at(gen.bus)
        s_gen = complex(pg, qg) / gen_case.base_mva
        current = (s_gen / vm).conjugate() if abs(vm) > 1e-9 else 0j
        e_phase = vm + complex(0.0, gen.xd_prime) * current
        machines.append(
            _Machine(
                gen_id=gen.id,
                bus=gen.bus,
                name=gen.name,
                h=max(gen.h, 1e-3),
                d=max(gen.d, 0.0),
                e_mag=abs(e_phase),
                delta=cmath.phase(e_phase),
                pm=0.0,
            )
        )

    gen_buses = [machine.bus for machine in machines]
    gen_reactances = [gen.xd_prime if abs(gen.xd_prime) > 1e-6 else gen.xd for gen in gens]
    trip_ids = resolve_branch_ids(gen_case, trip_branch)
    if trip_branch and not trip_ids:
        return {
            "error": f"未找到需要切除的支路：{trip_branch}",
            "stable": False,
            "curves": {"t": [], "machines": []},
        }

    def network(branch_ids: Optional[Iterable[int]] = None, fault_shunt_value: float = 0.0):
        extra = dict(load_shunts)
        if fault_shunt_value:
            extra[fault_bus] = extra.get(fault_bus, 0j) + fault_shunt_value
        ybus = build_ybus(gen_case, skip_branch_ids=branch_ids, extra_shunts=extra)
        return _reduce_to_generators(gen_case, ybus, gen_buses, gen_reactances)

    try:
        y_pre = network()
        y_fault = network(fault_shunt_value=complex(0.0, -fault_shunt))
        y_post = network(branch_ids=trip_ids)
    except ValueError as exc:
        return {"error": f"网络降阶失败：{exc}", "stable": False, "curves": {"t": [], "machines": []}}

    pe0 = _electrical_power(y_pre, machines)
    for machine, pe in zip(machines, pe0):
        machine.pm = pe

    state: List[float] = [machine.delta for machine in machines] + [1.0] * len(machines)
    freq = gen_case.freq
    steps = max(int(round(t_end / dt)), 1)
    times: List[float] = [0.0]
    deltas: List[List[float]] = [[math.degrees(machine.delta) for machine in machines]]
    omegas: List[List[float]] = [[1.0] * len(machines)]
    angle_diff: List[float] = [_max_relative_angle(machines)]

    for step in range(1, steps + 1):
        t = step * dt
        y_now = y_fault if t <= clearing_time else y_post
        state = _rk4_step(y_now, machines, state, dt, freq)
        times.append(t)
        deltas.append([math.degrees(machine.delta) for machine in machines])
        omegas.append(list(state[len(machines):]))
        angle_diff.append(_max_relative_angle(machines))
        if angle_diff[-1] > 3600.0:
            break

    tail_start = max(len(angle_diff) - max(5, len(angle_diff) // 10), 0)
    growing = angle_diff[-1] >= angle_diff[tail_start]
    stable = angle_diff[-1] < 360.0 and not (angle_diff[-1] > 180.0 and growing)

    machines_out = []
    for i, machine in enumerate(machines):
        machines_out.append(
            {
                "gen_id": machine.gen_id,
                "name": machine.name,
                "bus": machine.bus,
                "e_mag": machine.e_mag,
                "pm": machine.pm * gen_case.base_mva,
                "delta_deg": [row[i] for row in deltas],
                "omega_pu": [row[i] for row in omegas],
            }
        )

    return {
        "stable": stable,
        "clearing_time": clearing_time,
        "fault_bus": fault_bus,
        "trip_branch": trip_ids,
        "t_end": times[-1],
        "dt": dt,
        "max_angle_diff_deg": angle_diff[-1],
        "max_angle_diff_series": angle_diff,
        "prefault_angle_diff_deg": angle_diff[0],
        "curves": {"t": times, "machines": machines_out},
        "machines": machines_out,
    }


def find_critical_clearing_time(
    case: Case,
    fault_bus: int,
    trip_branch: Optional[Iterable[int]] = None,
    lo: float = 0.02,
    hi: float = 1.0,
    tol: float = 0.005,
    t_end: float = DEFAULT_T_END,
    dt: float = DEFAULT_DT,
) -> Dict[str, object]:
    """二分搜索极限切除时间（CCT）。"""
    def is_stable(tc: float) -> bool:
        result = simulate_transient_stability(case, fault_bus, trip_branch, tc, t_end=t_end, dt=dt)
        return bool(result.get("stable"))

    lower_stable = is_stable(lo)
    upper_stable = is_stable(hi)
    if not lower_stable:
        return {"cct": lo, "stable_at": False, "unstable_at": True,
                "message": f"切除时间 {lo:.3f} s 时系统已失稳，建议进一步减小初始切除时间"}
    if upper_stable:
        return {"cct": hi, "stable_at": True, "unstable_at": False,
                "message": f"切除时间 {hi:.3f} s 仍保持稳定，极限切除时间大于该值"}

    low, high = lo, hi
    while high - low > tol:
        mid = 0.5 * (low + high)
        if is_stable(mid):
            low = mid
        else:
            high = mid
    return {
        "cct": low,
        "stable_at": low,
        "unstable_at": high,
        "message": f"极限切除时间约为 {low:.3f} s（误差小于 {tol:.3f} s）",
    }
