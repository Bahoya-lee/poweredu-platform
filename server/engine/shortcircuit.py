"""三相短路电流计算（节点阻抗矩阵法）。

以潮流计算结果作为故障前运行状态，把发电机次暂态电抗作为并联支路接入
网络，得到节点阻抗矩阵 Zbus 后按 I_f = V_pre / (Z_kk + Z_f) 求短路电流，
并给出全网母线电压跌落分布。
"""

from __future__ import annotations

import cmath
import math
from typing import Dict, List, Optional

from .linalg import invert
from .models import Case
from .powerflow import build_ybus, bus_index, solve_power_flow


def _gen_shunts(case: Case) -> Dict[int, complex]:
    """发电机次暂态电抗对应的并联导纳（标幺值）。"""
    shunts: Dict[int, complex] = {}
    for gen in case.active_gens():
        xd = gen.xd_prime if abs(gen.xd_prime) > 1e-6 else gen.xd
        if abs(xd) < 1e-6:
            continue
        shunts[gen.bus] = shunts.get(gen.bus, 0j) + 1.0 / complex(0.0, xd)
    return shunts


def solve_short_circuit(
    case: Case,
    fault_bus: Optional[int] = None,
    fault_impedance: float = 0.0,
) -> Dict[str, object]:
    """计算指定母线的三相短路电流及全网电压分布。

    Parameters
    ----------
    fault_bus:
        故障母线编号，缺省取负荷最重或编号最小的 PQ 母线。
    fault_impedance:
        故障点附加阻抗（标幺值），0 表示金属性短路。
    """
    problems = case.validate()
    if problems:
        return {"error": "；".join(problems), "per_bus": [], "bus_voltages": []}

    power_flow = solve_power_flow(case)
    if not power_flow.get("converged"):
        return {
            "error": power_flow.get("error", "潮流计算未收敛，无法确定故障前运行状态"),
            "per_bus": [],
            "bus_voltages": [],
        }

    index = bus_index(case)
    buses = case.buses
    n = len(buses)

    if fault_bus is None:
        candidates = [bus for bus in buses if bus.type == "PQ"] or buses
        fault_bus = max(candidates, key=lambda bus: bus.pd).id
    if fault_bus not in index:
        return {"error": f"算例中不存在母线 {fault_bus}", "per_bus": [], "bus_voltages": []}

    ybus = build_ybus(case, extra_shunts=_gen_shunts(case))
    try:
        zbus = invert(ybus)
    except ValueError as exc:
        return {"error": f"节点阻抗矩阵不可逆：{exc}", "per_bus": [], "bus_voltages": []}

    v_pre: List[complex] = [
        cmath.rect(item["vm"], math.radians(item["va"])) for item in power_flow["buses"]
    ]

    k = index[fault_bus]
    z_kk = zbus[k][k] + fault_impedance
    if abs(z_kk) < 1e-12:
        return {"error": "故障点自阻抗过小，无法计算短路电流", "per_bus": [], "bus_voltages": []}

    i_f = v_pre[k] / z_kk
    i_base_ka = case.base_mva / (math.sqrt(3.0) * case.base_kv)
    current_ka = abs(i_f) * i_base_ka
    short_circuit_mva = abs(i_f) * case.base_mva

    voltage_after = []
    for i, bus in enumerate(buses):
        v_after = v_pre[i] - zbus[i][k] * i_f
        voltage_after.append(
            {
                "bus": bus.id,
                "name": bus.name,
                "vm": abs(v_after),
                "vm_pre": abs(v_pre[i]),
                "va": math.degrees(cmath.phase(v_after)),
                "x": bus.x,
                "y": bus.y,
                "type": bus.type,
            }
        )

    per_bus = []
    for i, bus in enumerate(buses):
        z_self = abs(zbus[i][i])
        current = abs(v_pre[i]) / z_self if z_self > 1e-12 else 0.0
        per_bus.append(
            {
                "bus": bus.id,
                "name": bus.name,
                "zbus_mag": z_self,
                "current_pu": current,
                "current_ka": current * i_base_ka,
                "vm_pre": abs(v_pre[i]),
            }
        )

    return {
        "fault_bus": fault_bus,
        "fault_bus_name": buses[k].name,
        "fault_impedance": fault_impedance,
        "fault_current_pu": abs(i_f),
        "fault_current_ka": current_ka,
        "short_circuit_mva": short_circuit_mva,
        "prefault_vm": abs(v_pre[k]),
        "current_base_ka": i_base_ka,
        "zbus_self": abs(zbus[k][k]),
        "bus_voltages": voltage_after,
        "per_bus": per_bus,
        "min_vm": min(item["vm"] for item in voltage_after),
    }
