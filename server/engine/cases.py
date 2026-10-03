"""内置算例库。

参数取自电力系统分析教材与 MATPOWER 公开标准算例（功率基准 100 MVA），
用于潮流、短路与暂态稳定的教学演示与数值回归测试。
"""

from __future__ import annotations

from typing import Dict, List

from .models import Branch, Bus, Case, Gen


def _wscc9() -> Case:
    """WSCC 三机九节点系统：暂态稳定与潮流教学的经典算例。"""
    buses = [
        Bus(id=1, name="G1 平衡母线", type="SLACK", vm=1.04, va=0.0, pd=0.0, qd=0.0, x=12, y=18),
        Bus(id=2, name="G2 母线", type="PV", vm=1.025, pd=0.0, qd=0.0, x=12, y=88),
        Bus(id=3, name="G3 母线", type="PV", vm=1.025, pd=0.0, qd=0.0, x=88, y=62),
        Bus(id=4, name="枢纽站 4", type="PQ", vm=1.026, pd=0.0, qd=0.0, x=32, y=20),
        Bus(id=5, name="负荷母线 5", type="PQ", vm=0.996, pd=90.0, qd=30.0, x=55, y=10),
        Bus(id=6, name="负荷母线 6", type="PQ", vm=1.013, pd=100.0, qd=35.0, x=64, y=36),
        Bus(id=7, name="联络母线 7", type="PQ", vm=1.026, pd=0.0, qd=0.0, x=48, y=60),
        Bus(id=8, name="负荷母线 8", type="PQ", vm=1.016, pd=100.0, qd=35.0, x=30, y=74),
        Bus(id=9, name="联络母线 9", type="PQ", vm=1.032, pd=0.0, qd=0.0, x=14, y=52),
    ]
    gens = [
        Gen(id=1, bus=1, name="G1 汽轮机", pg=0.0, qg=0.0, vg=1.04, h=23.64,
            xd=0.1460, xd_prime=0.0608, pmax=400.0, qmax=300.0, qmin=-300.0),
        Gen(id=2, bus=2, name="G2 汽轮机", pg=163.0, qg=0.0, vg=1.025, h=6.40,
            xd=0.8958, xd_prime=0.1198, pmax=300.0, qmax=300.0, qmin=-300.0),
        Gen(id=3, bus=3, name="G3 汽轮机", pg=85.0, qg=0.0, vg=1.025, h=3.01,
            xd=1.3125, xd_prime=0.1813, pmax=250.0, qmax=300.0, qmin=-300.0),
    ]
    raw = [
        (1, 1, 4, 0.0, 0.0576, 0.0, 1.0, 250.0),
        (2, 4, 5, 0.0170, 0.0920, 0.158, 1.0, 250.0),
        (3, 5, 6, 0.0390, 0.1700, 0.358, 1.0, 250.0),
        (4, 3, 6, 0.0, 0.0586, 0.0, 1.0, 250.0),
        (5, 6, 7, 0.0119, 0.1008, 0.209, 1.0, 250.0),
        (6, 7, 8, 0.0085, 0.0720, 0.149, 1.0, 250.0),
        (7, 8, 2, 0.0, 0.0625, 0.0, 1.0, 250.0),
        (8, 8, 9, 0.0320, 0.1610, 0.306, 1.0, 250.0),
        (9, 9, 4, 0.0100, 0.0850, 0.176, 1.0, 250.0),
    ]
    branches = [_line(*item) for item in raw]
    return Case(
        id="wscc9",
        name="三机九节点系统（WSCC 9）",
        desc="经典暂态稳定算例，含三台同步机、九条母线，适合演示潮流分布与功角摇摆。",
        base_mva=100.0,
        base_kv=230.0,
        level="进阶",
        tags=["潮流", "暂态稳定", "标准算例"],
        buses=buses,
        gens=gens,
        branches=branches,
    )


def _ieee14() -> Case:
    """IEEE 14 节点系统：潮流与短路电流教学标准算例。"""
    bus_rows = [
        (1, "G1 平衡母线", "SLACK", 1.060, 0.0, 0.0, 0.0, 12, 18),
        (2, "G2 母线", "PV", 1.045, 21.7, 12.7, 0.0, 30, 30),
        (3, "G3 母线", "PV", 1.010, 94.2, 19.0, 0.0, 26, 52),
        (4, "枢纽母线 4", "PQ", 1.019, 47.8, -3.9, 0.0, 50, 28),
        (5, "负荷母线 5", "PQ", 1.020, 7.6, 1.6, 0.0, 30, 10),
        (6, "G6 母线", "PV", 1.070, 11.2, 7.5, 0.0, 78, 24),
        (7, "联络母线 7", "PQ", 1.062, 0.0, 0.0, 0.0, 62, 46),
        (8, "G8 母线", "PV", 1.090, 0.0, 0.0, 0.0, 84, 46),
        (9, "联络母线 9", "PQ", 1.056, 29.5, 16.6, 19.0, 56, 64),
        (10, "负荷母线 10", "PQ", 1.051, 9.0, 5.8, 0.0, 68, 78),
        (11, "负荷母线 11", "PQ", 1.057, 3.5, 1.8, 0.0, 86, 68),
        (12, "负荷母线 12", "PQ", 1.055, 6.1, 1.6, 0.0, 92, 30),
        (13, "负荷母线 13", "PQ", 1.050, 13.5, 5.8, 0.0, 95, 52),
        (14, "负荷母线 14", "PQ", 1.036, 14.9, 5.0, 0.0, 76, 90),
    ]
    buses = [
        Bus(id=row[0], name=row[1], type=row[2], vm=row[3], pd=row[4], qd=row[5], bs=row[6], x=row[7], y=row[8])
        for row in bus_rows
    ]
    gens = [
        Gen(id=1, bus=1, name="G1", pg=232.4, vg=1.06, h=6.5, xd=0.30, xd_prime=0.06,
            pmax=400.0, qmax=200.0, qmin=-200.0),
        Gen(id=2, bus=2, name="G2", pg=40.0, vg=1.045, h=5.0, xd=0.35, xd_prime=0.10,
            pmax=200.0, qmax=100.0, qmin=-100.0),
        Gen(id=3, bus=3, name="G3 调相机", pg=0.0, vg=1.01, h=4.0, xd=0.40, xd_prime=0.12,
            pmax=100.0, qmax=80.0, qmin=-80.0),
        Gen(id=4, bus=6, name="G6 调相机", pg=0.0, vg=1.07, h=4.0, xd=0.40, xd_prime=0.12,
            pmax=100.0, qmax=80.0, qmin=-80.0),
        Gen(id=5, bus=8, name="G8 调相机", pg=0.0, vg=1.09, h=4.0, xd=0.40, xd_prime=0.12,
            pmax=100.0, qmax=80.0, qmin=-80.0),
    ]
    raw = [
        (1, 1, 2, 0.01938, 0.05917, 0.0528, 1.0, 130.0),
        (2, 1, 5, 0.05403, 0.22304, 0.0492, 1.0, 130.0),
        (3, 2, 3, 0.04699, 0.19797, 0.0438, 1.0, 130.0),
        (4, 2, 4, 0.05811, 0.17632, 0.0340, 1.0, 130.0),
        (5, 2, 5, 0.05695, 0.17388, 0.0346, 1.0, 130.0),
        (6, 3, 4, 0.06701, 0.17103, 0.0128, 1.0, 130.0),
        (7, 4, 5, 0.01335, 0.04211, 0.0, 1.0, 130.0),
        (8, 4, 7, 0.0, 0.20912, 0.0, 0.978, 130.0),
        (9, 4, 9, 0.0, 0.55618, 0.0, 0.969, 130.0),
        (10, 5, 6, 0.0, 0.25202, 0.0, 0.932, 130.0),
        (11, 6, 11, 0.09498, 0.19890, 0.0, 1.0, 130.0),
        (12, 6, 12, 0.12291, 0.25581, 0.0, 1.0, 130.0),
        (13, 6, 13, 0.06615, 0.13027, 0.0, 1.0, 130.0),
        (14, 7, 8, 0.0, 0.17615, 0.0, 1.0, 130.0),
        (15, 7, 9, 0.0, 0.11001, 0.0, 1.0, 130.0),
        (16, 9, 10, 0.03181, 0.08450, 0.0, 1.0, 130.0),
        (17, 9, 14, 0.12711, 0.27038, 0.0, 1.0, 130.0),
        (18, 10, 11, 0.08205, 0.19207, 0.0, 1.0, 130.0),
        (19, 12, 13, 0.22092, 0.19988, 0.0, 1.0, 130.0),
        (20, 13, 14, 0.17093, 0.34802, 0.0, 1.0, 130.0),
    ]
    branches = [_line(*item) for item in raw]
    return Case(
        id="ieee14",
        name="IEEE 14 节点系统",
        desc="国际通用测试系统，含 5 台发电机与 3 台带变比的变压器，适合作潮流与短路对比实验。",
        base_mva=100.0,
        base_kv=110.0,
        level="进阶",
        tags=["潮流", "短路", "标准算例"],
        buses=buses,
        gens=gens,
        branches=branches,
    )


def _two_machine() -> Case:
    """单机-无穷大母线教学算例，用于短路电流解析解对照。"""
    buses = [
        Bus(id=1, name="发电机母线", type="SLACK", vm=1.00, pd=0.0, qd=0.0, x=18, y=50),
        Bus(id=2, name="负荷母线", type="PQ", vm=1.00, pd=20.0, qd=8.0, x=60, y=50),
        Bus(id=3, name="馈线末端", type="PQ", vm=1.00, pd=10.0, qd=4.0, x=88, y=50),
    ]
    gens = [
        Gen(id=1, bus=1, name="G1 发电机", pg=30.0, vg=1.00, h=5.0, xd=1.0, xd_prime=0.20,
            pmax=100.0, qmax=60.0, qmin=-60.0),
    ]
    raw = [
        (1, 1, 2, 0.0100, 0.1000, 0.0, 1.0, 100.0),
        (2, 2, 3, 0.0200, 0.1200, 0.0, 1.0, 100.0),
    ]
    branches = [_line(*item) for item in raw]
    return Case(
        id="two_machine",
        name="单机-无穷大母线系统",
        desc="最简教学算例：一台发电机经变压器与线路供电，短路电流可手算校核。",
        base_mva=100.0,
        base_kv=10.5,
        level="入门",
        tags=["潮流", "短路", "入门"],
        buses=buses,
        gens=gens,
        branches=branches,
    )


def _radial5() -> Case:
    """10 kV 辐射状配电馈线，用于配电网教学演示。"""
    buses = [
        Bus(id=1, name="变电站母线", type="SLACK", vm=1.00, pd=0.0, qd=0.0, x=10, y=50),
        Bus(id=2, name="分段开关 2", type="PQ", vm=1.00, pd=0.30, qd=0.12, x=30, y=50),
        Bus(id=3, name="分段开关 3", type="PQ", vm=1.00, pd=0.35, qd=0.14, x=50, y=50),
        Bus(id=4, name="配变 4", type="PQ", vm=1.00, pd=0.40, qd=0.16, x=70, y=50),
        Bus(id=5, name="线路末端 5", type="PQ", vm=1.00, pd=0.25, qd=0.10, x=90, y=50),
    ]
    gens = [
        Gen(id=1, bus=1, name="主变", pg=1.3, vg=1.00, h=6.0, xd=0.8, xd_prime=0.15,
            pmax=5.0, qmax=3.0, qmin=-3.0),
    ]
    raw = [
        (1, 1, 2, 0.0800, 0.0700, 0.0, 1.0, 5.0),
        (2, 2, 3, 0.0800, 0.0700, 0.0, 1.0, 5.0),
        (3, 3, 4, 0.1200, 0.1050, 0.0, 1.0, 5.0),
        (4, 4, 5, 0.1000, 0.0875, 0.0, 1.0, 5.0),
    ]
    branches = [_line(*item) for item in raw]
    return Case(
        id="radial5",
        name="10 kV 辐射状配电馈线",
        desc="面向电气专业入门课：单电源辐射网，演示电压降落与线损随距离的变化。",
        base_mva=10.0,
        base_kv=10.0,
        level="入门",
        tags=["配电网", "电压降落", "入门"],
        buses=buses,
        gens=gens,
        branches=branches,
    )


def _line(
    branch_id: int,
    fbus: int,
    tbus: int,
    r: float,
    x: float,
    b: float,
    tap: float,
    rate: float,
) -> Branch:
    """按表格式参数生成支路对象。"""
    kind = "变压器" if abs(tap - 1.0) > 1e-9 else "线路"
    return Branch(
        id=branch_id,
        fbus=fbus,
        tbus=tbus,
        name=f"{kind}{fbus}-{tbus}",
        r=r,
        x=x,
        b=b,
        tap=tap,
        rate=rate,
    )


_BUILDERS = {
    "wscc9": _wscc9,
    "ieee14": _ieee14,
    "two_machine": _two_machine,
    "radial5": _radial5,
}

_CACHE: Dict[str, Case] = {}


def _build(case_id: str) -> Case:
    """构造并缓存算例。"""
    if case_id not in _CACHE:
        _CACHE[case_id] = _BUILDERS[case_id]()
    return _CACHE[case_id]


def get_case(case_id: str) -> Case:
    """按编号取算例的深拷贝；未知编号抛 KeyError。"""
    if case_id not in _BUILDERS:
        raise KeyError(f"未知算例：{case_id}")
    return _build(case_id).clone()


def register_case(case_id: str, case: Case) -> None:
    """注册自定义算例（进程内有效，教学演示用）。"""
    case.id = case_id
    _CACHE[case_id] = case.clone()
    _BUILDERS[case_id] = lambda: _CACHE[case_id].clone()


def list_cases() -> List[Dict[str, object]]:
    """列出全部可用算例概览。"""
    return [_build(case_id).summary() for case_id in _BUILDERS]


def case_ids() -> List[str]:
    """返回全部算例编号。"""
    return list(_BUILDERS.keys())


def all_cases() -> List[Case]:
    """返回全部内置算例的副本（测试与批量校验用）。"""
    return [get_case(case_id) for case_id in case_ids()]
