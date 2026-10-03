"""电力系统元件与算例数据模型。

所有元件字段都直接以"标幺值 + MW/MVar"的工程口径存放，便于教学讲解与
前端表格直接编辑；`Case` 是整个仿真内核唯一的数据入口。
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

BUS_TYPES = ("SLACK", "PV", "PQ")


def _as_float(value: Any, default: float = 0.0) -> float:
    """把前端/JSON 传进来的值安全转换为 float。"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    """把前端/JSON 传进来的值安全转换为 int。"""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = True) -> bool:
    """把 0/1、"true"/"false"、True/False 统一成 bool。"""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "投运", "投入"}


@dataclass
class Bus:
    """母线（节点）。"""

    id: int
    name: str = ""
    type: str = "PQ"
    vm: float = 1.0
    va: float = 0.0
    pd: float = 0.0
    qd: float = 0.0
    gs: float = 0.0
    bs: float = 0.0
    vmax: float = 1.10
    vmin: float = 0.90
    x: float = 0.0
    y: float = 0.0
    area: str = ""

    def __post_init__(self) -> None:
        self.id = _as_int(self.id)
        self.type = str(self.type).strip().upper() or "PQ"
        if self.type not in BUS_TYPES:
            self.type = "PQ"
        self.name = str(self.name or f"母线{self.id}")
        for attr in ("vm", "va", "pd", "qd", "gs", "bs", "vmax", "vmin", "x", "y"):
            setattr(self, attr, _as_float(getattr(self, attr)))

    @property
    def is_generator_bus(self) -> bool:
        """是否为发电机并网点（平衡节点或 PV 节点）。"""
        return self.type in ("SLACK", "PV")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Bus":
        return cls(**{f.name: data.get(f.name, f.default) for f in fields(cls)})


@dataclass
class Gen:
    """同步发电机。"""

    id: int
    bus: int
    name: str = ""
    pg: float = 0.0
    qg: float = 0.0
    vg: float = 1.0
    qmax: float = 300.0
    qmin: float = -300.0
    pmax: float = 500.0
    pmin: float = 0.0
    h: float = 5.0
    d: float = 0.0
    xd: float = 1.0
    xd_prime: float = 0.30
    status: int = 1

    def __post_init__(self) -> None:
        self.id = _as_int(self.id)
        self.bus = _as_int(self.bus)
        self.name = str(self.name or f"G{self.id}")
        for attr in ("pg", "qg", "vg", "qmax", "qmin", "pmax", "pmin", "h", "d", "xd", "xd_prime"):
            setattr(self, attr, _as_float(getattr(self, attr)))
        self.status = 1 if _as_bool(self.status) else 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Gen":
        return cls(**{f.name: data.get(f.name, f.default) for f in fields(cls)})


@dataclass
class Branch:
    """输电线路或变压器支路（统一 π 型等效）。"""

    id: int
    fbus: int
    tbus: int
    name: str = ""
    r: float = 0.0
    x: float = 0.05
    b: float = 0.0
    tap: float = 1.0
    shift: float = 0.0
    rate: float = 100.0
    status: int = 1
    length: float = 0.0

    def __post_init__(self) -> None:
        self.id = _as_int(self.id)
        self.fbus = _as_int(self.fbus)
        self.tbus = _as_int(self.tbus)
        self.name = str(self.name or f"L{self.fbus}-{self.tbus}")
        for attr in ("r", "x", "b", "tap", "shift", "rate", "length"):
            setattr(self, attr, _as_float(getattr(self, attr)))
        if abs(self.tap) < 1e-9:
            self.tap = 1.0
        self.status = 1 if _as_bool(self.status) else 0

    @property
    def is_transformer(self) -> bool:
        """变比不为 1 或存在相移时按变压器处理。"""
        return abs(self.tap - 1.0) > 1e-9 or abs(self.shift) > 1e-9

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["is_transformer"] = self.is_transformer
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Branch":
        return cls(**{f.name: data.get(f.name, f.default) for f in fields(cls)})


@dataclass
class Case:
    """一个完整的电力系统算例。"""

    id: str = "custom"
    name: str = "自定义算例"
    desc: str = ""
    base_mva: float = 100.0
    base_kv: float = 110.0
    freq: float = 50.0
    level: str = "教学"
    tags: List[str] = field(default_factory=list)
    buses: List[Bus] = field(default_factory=list)
    gens: List[Gen] = field(default_factory=list)
    branches: List[Branch] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.base_mva = _as_float(self.base_mva, 100.0) or 100.0
        self.base_kv = _as_float(self.base_kv, 110.0) or 110.0
        self.freq = _as_float(self.freq, 50.0) or 50.0
        self.tags = list(self.tags or [])

    # ---------- 查询辅助 ----------

    def bus_ids(self) -> List[int]:
        """按录入顺序返回母线编号。"""
        return [bus.id for bus in self.buses]

    def index_of(self, bus_id: int) -> int:
        """返回母线编号在母线数组中的序号。"""
        for index, bus in enumerate(self.buses):
            if bus.id == bus_id:
                return index
        raise KeyError(f"算例中不存在母线 {bus_id}")

    def bus(self, bus_id: int) -> Bus:
        """按编号取母线对象。"""
        return self.buses[self.index_of(bus_id)]

    def slack_bus(self) -> Bus:
        """返回平衡节点，缺失时退化为第一台发电机所在母线。"""
        for bus in self.buses:
            if bus.type == "SLACK":
                return bus
        if self.gens:
            return self.bus(self.gens[0].bus)
        return self.buses[0]

    def active_branches(self) -> List[Branch]:
        """返回处于投运状态的支路。"""
        return [branch for branch in self.branches if branch.status]

    def active_gens(self) -> List[Gen]:
        """返回处于投运状态的发电机。"""
        return [gen for gen in self.gens if gen.status]

    def gen_power_at(self, bus_id: int) -> tuple:
        """汇总某母线上所有发电机的有功与无功出力（MW/MVar）。"""
        pg = sum(gen.pg for gen in self.active_gens() if gen.bus == bus_id)
        qg = sum(gen.qg for gen in self.active_gens() if gen.bus == bus_id)
        return pg, qg

    def total_load(self) -> tuple:
        """返回全网有功、无功负荷总量（MW/MVar）。"""
        return (
            sum(bus.pd for bus in self.buses),
            sum(bus.qd for bus in self.buses),
        )

    def total_gen(self) -> tuple:
        """返回全网发电机有功、无功出力设定总量（MW/MVar）。"""
        return (
            sum(gen.pg for gen in self.active_gens()),
            sum(gen.qg for gen in self.active_gens()),
        )

    # ---------- 校验与序列化 ----------

    def validate(self) -> List[str]:
        """返回问题清单，空列表代表算例自洽。"""
        problems: List[str] = []
        if not self.buses:
            problems.append("算例没有任何母线")
            return problems
        if self.base_mva <= 0:
            problems.append("功率基准值必须为正数")

        ids = self.bus_ids()
        if len(set(ids)) != len(ids):
            problems.append("存在重复的母线编号")

        known = set(ids)
        slack_count = sum(1 for bus in self.buses if bus.type == "SLACK")
        if slack_count == 0:
            problems.append("缺少平衡节点（SLACK），潮流计算无法启动")
        elif slack_count > 1:
            problems.append(f"存在 {slack_count} 个平衡节点，应且仅应有一个")

        for branch in self.branches:
            if branch.fbus not in known:
                problems.append(f"支路 {branch.name} 的首端母线 {branch.fbus} 不存在")
            if branch.tbus not in known:
                problems.append(f"支路 {branch.name} 的末端母线 {branch.tbus} 不存在")
            if branch.fbus == branch.tbus:
                problems.append(f"支路 {branch.name} 的首末端为同一母线")
            if abs(branch.x) < 1e-9 and abs(branch.r) < 1e-9 and branch.status:
                problems.append(f"支路 {branch.name} 阻抗为零，无法建立网络方程")

        for gen in self.gens:
            if gen.bus not in known:
                problems.append(f"发电机 {gen.name} 接入的母线 {gen.bus} 不存在")
            if gen.h <= 0:
                problems.append(f"发电机 {gen.name} 的惯性时间常数必须为正")

        for bus in self.buses:
            if bus.type in ("SLACK", "PV") and not any(
                gen.bus == bus.id and gen.status for gen in self.gens
            ):
                problems.append(f"母线 {bus.id} 为 {bus.type} 类型但没有投运的发电机")

        return problems

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "base_mva": self.base_mva,
            "base_kv": self.base_kv,
            "freq": self.freq,
            "level": self.level,
            "tags": list(self.tags),
            "buses": [bus.to_dict() for bus in self.buses],
            "gens": [gen.to_dict() for gen in self.gens],
            "branches": [branch.to_dict() for branch in self.branches],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Case":
        """由 JSON 结构构造算例，容忍字段缺失。"""
        data = data or {}
        return cls(
            id=str(data.get("id", "custom")),
            name=str(data.get("name", "自定义算例")),
            desc=str(data.get("desc", "")),
            base_mva=_as_float(data.get("base_mva"), 100.0),
            base_kv=_as_float(data.get("base_kv"), 110.0),
            freq=_as_float(data.get("freq"), 50.0),
            level=str(data.get("level", "教学")),
            tags=list(data.get("tags") or []),
            buses=[Bus.from_dict(item) for item in data.get("buses", [])],
            gens=[Gen.from_dict(item) for item in data.get("gens", [])],
            branches=[Branch.from_dict(item) for item in data.get("branches", [])],
        )

    def clone(self) -> "Case":
        """深拷贝，避免调用方改坏内置算例。"""
        return copy.deepcopy(self)

    def summary(self) -> Dict[str, Any]:
        """算例概览，供前端卡片与报告使用。"""
        pd, qd = self.total_load()
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "level": self.level,
            "tags": list(self.tags),
            "base_mva": self.base_mva,
            "base_kv": self.base_kv,
            "bus_count": len(self.buses),
            "branch_count": len(self.branches),
            "gen_count": len(self.gens),
            "load_p_mw": round(pd, 4),
            "load_q_mvar": round(qd, 4),
            "slack_bus": self.slack_bus().id,
        }
