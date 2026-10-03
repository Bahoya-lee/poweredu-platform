"""AI 助教：自然语言改算例、运行结果诊断、实验报告草稿。

设计原则：**离线可用**。默认使用本地规则引擎完成意图解析与结果诊断，
配置了 OPENAI_API_KEY / DEEPSEEK_API_KEY 时才调用大模型润色与答疑，
网络异常自动降级，保证内网机房也能正常上课。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from .engine.models import Case

MW_UNITS = ("兆瓦", "mw", "MW", "千瓦", "kw", "kW")
MVAR_UNITS = ("兆乏", "mvar", "MVar", "千乏", "kvar")


def _to_mw(value: float, unit: str) -> float:
    """把 kW/kvar 等单位统一折算为 MW/MVar。"""
    return value / 1000.0 if unit.lower() in ("千瓦", "kw", "千乏", "kvar") else value


def _find_bus(text: str, case: Case, keyword: str = "母线") -> Optional[int]:
    """从文本中提取母线编号，支持"5号母线""母线5""节点5"。"""
    patterns = [
        rf"(\d+)\s*号\s*{keyword}",
        rf"{keyword}\s*(\d+)",
        rf"(\d+)\s*号\s*(?:节点|母线|bus)",
        r"节点\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if value in case.bus_ids():
                return value
    return None


def _find_gen(text: str, case: Case) -> Optional[int]:
    """从文本中提取发电机序号（按发电机编号或所在母线）。"""
    match = re.search(r"(\d+)\s*号?\s*(?:发电机|机组|机|G)", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = int(match.group(1))
    if any(gen.id == value for gen in case.gens):
        return value
    if any(gen.bus == value for gen in case.gens):
        for gen in case.gens:
            if gen.bus == value:
                return gen.id
    return None


def _number(text: str, units: Tuple[str, ...]) -> Optional[Tuple[float, str]]:
    """提取"数值 + 单位"组合。"""
    unit_pattern = "|".join(units)
    match = re.search(rf"(-?\d+(?:\.\d+)?)\s*({unit_pattern})", text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1)), match.group(2)


def _bus_pair(text: str, case: Case) -> Optional[Tuple[int, int]]:
    """提取"6-7 线路"这类母线对。"""
    match = re.search(r"(\d+)\s*[-—~到至]\s*(\d+)", text)
    if not match:
        return None
    pair = (int(match.group(1)), int(match.group(2)))
    if all(item in case.bus_ids() for item in pair):
        return pair
    return None


def _op(kind: str, target: str, detail: str, **extra: Any) -> Dict[str, Any]:
    """构造一条可展示的操作记录。"""
    item = {"op": kind, "target": target, "detail": detail}
    item.update(extra)
    return item


Handler = Callable[[Case, Dict[str, Any]], List[Dict[str, Any]]]


def _handle_set_load(case: Case, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """设置母线有功/无功负荷。"""
    ops: List[Dict[str, Any]] = []
    text = ctx["text"]
    bus_id = ctx["bus"]
    if bus_id is None:
        for bus in case.buses:
            bus.pd = round(bus.pd * ctx["ratio"], 2) if ctx.get("ratio") else bus.pd
            bus.qd = round(bus.qd * ctx["ratio"], 2) if ctx.get("ratio") else bus.qd
        return [_op("scale_load", "全网", f"全网负荷按 {ctx['ratio']:.3f} 倍缩放")]

    bus = case.bus(bus_id)
    p_value = _number(text, MW_UNITS)
    q_value = _number(text, MVAR_UNITS)
    old_p, old_q = bus.pd, bus.qd
    if p_value:
        bus.pd = round(_to_mw(*p_value), 4)
    if q_value:
        bus.qd = round(_to_mw(*q_value), 4)
    if not p_value and not q_value and ctx.get("ratio"):
        bus.pd = round(bus.pd * ctx["ratio"], 4)
        bus.qd = round(bus.qd * ctx["ratio"], 4)
    ops.append(_op(
        "set_load",
        f"母线 {bus_id}",
        f"有功负荷 {old_p:g} → {bus.pd:g} MW；无功负荷 {old_q:g} → {bus.qd:g} MVar",
        bus=bus_id,
    ))
    return ops


def _handle_set_gen(case: Case, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """设置发电机有功出力或机端电压。"""
    ops: List[Dict[str, Any]] = []
    text = ctx["text"]
    gen_id = ctx["gen"]
    if gen_id is None:
        return ops
    gen = next(item for item in case.gens if item.id == gen_id)
    voltage = re.search(r"电压\s*(?:为|设为|调到|设置为)?\s*(1\.\d+|\d\.\d+)", text)
    if voltage:
        old = gen.vg
        gen.vg = float(voltage.group(1))
        bus = case.bus(gen.bus)
        if bus.type in ("SLACK", "PV"):
            bus.vm = gen.vg
        ops.append(_op("set_gen_voltage", f"发电机 {gen_id}",
                       f"机端电压设定值 {old:g} → {gen.vg:g} p.u.", gen=gen_id))
    power = _number(text, MW_UNITS)
    if power:
        old = gen.pg
        gen.pg = round(_to_mw(*power), 4)
        ops.append(_op("set_gen_power", f"发电机 {gen_id}",
                       f"有功出力 {old:g} → {gen.pg:g} MW", gen=gen_id, bus=gen.bus))
    return ops


def _handle_set_bus_voltage(case: Case, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """设置 PV/平衡母线的电压设定值。"""
    bus_id = ctx["bus"]
    if bus_id is None:
        return []
    match = re.search(r"(1\.\d+|\d\.\d+)", ctx["text"])
    if not match:
        return []
    bus = case.bus(bus_id)
    old = bus.vm
    bus.vm = float(match.group(1))
    for gen in case.gens:
        if gen.bus == bus_id:
            gen.vg = bus.vm
    if bus.type == "PQ":
        bus.type = "PV" if any(gen.bus == bus_id for gen in case.gens) else bus.type
    return [_op("set_bus_voltage", f"母线 {bus_id}",
                f"电压设定值 {old:g} → {bus.vm:g} p.u.", bus=bus_id)]


def _handle_toggle_branch(case: Case, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """投入或切除线路。"""
    ops: List[Dict[str, Any]] = []
    pair = ctx["branch_pair"]
    if pair is None:
        return ops
    text = ctx["text"]
    want_open = any(word in text for word in ("断开", "切除", "退出", "停运", "跳开"))
    want_close = any(word in text for word in ("投入", "合上", "恢复", "复役", "闭合"))
    if not (want_open or want_close):
        want_open = True
    for branch in case.branches:
        if {branch.fbus, branch.tbus} == set(pair):
            branch.status = 0 if want_open else 1
            ops.append(_op(
                "toggle_branch",
                f"支路 {branch.fbus}-{branch.tbus}",
                "已切除" if want_open else "已投入",
                branch_id=branch.id,
                status=branch.status,
            ))
    return ops


def _handle_tap(case: Case, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """调整变压器变比。"""
    pair = ctx["branch_pair"]
    match = re.search(r"变比\s*(?:为|设为|改为|调到|设置为)?\s*(\d\.\d+)", ctx["text"])
    if pair is None or not match:
        return []
    ops = []
    for branch in case.branches:
        if {branch.fbus, branch.tbus} == set(pair):
            old = branch.tap
            branch.tap = float(match.group(1))
            ops.append(_op("set_tap", f"变压器 {branch.fbus}-{branch.tbus}",
                           f"变比 {old:g} → {branch.tap:g}", branch_id=branch.id))
    return ops


RULES: List[Tuple[str, re.Pattern, Handler, Dict[str, Any]]] = [
    (
        "变比",
        re.compile(r"变比"),
        _handle_tap,
        {"needs_pair": True},
    ),
    (
        "线路投切",
        re.compile(r"(断开|切除|退出|停运|跳开|投入|合上|恢复|复役|闭合)"),
        _handle_toggle_branch,
        {"needs_pair": True},
    ),
    (
        "全网负荷比例",
        re.compile(r"(全网|所有|各)\s*(母线)?\s*(负荷|负载)"),
        _handle_set_load,
        {"needs_ratio": True},
    ),
    (
        "母线电压",
        re.compile(r"(电压)"),
        _handle_set_bus_voltage,
        {"needs_bus": True},
    ),
    (
        "发电机出力",
        re.compile(r"(发电机|机组|\d+\s*号机|\d+\s*号\s*机|机端)"),
        _handle_set_gen,
        {"needs_gen": True},
    ),
    (
        "母线负荷",
        re.compile(r"(负荷|负载|用电)"),
        _handle_set_load,
        {"needs_bus": True},
    ),
]


def _extract_ratio(text: str) -> Optional[float]:
    """解析"增加 10%""降低 5%"为缩放系数。"""
    match = re.search(r"(增加|提高|上升|上升为|上调|降低|减少|下降|下调)\s*(\d+(?:\.\d+)?)\s*%", text)
    if not match:
        return None
    ratio = 1.0 + float(match.group(2)) / 100.0
    if match.group(1) in ("降低", "减少", "下降", "下调"):
        ratio = 1.0 / ratio
    return ratio


def apply_instruction(case: Case, text: str) -> Dict[str, Any]:
    """按自然语言指令修改算例，返回操作清单与新算例。"""
    text = (text or "").strip()
    if not text:
        return {"ops": [], "case": case, "reply": "请描述你想做的修改，例如“把 5 号母线负荷增加到 120 兆瓦”。",
                "applied": False}

    working = case.clone()
    base_bus = _find_bus(text, working)
    base_gen = _find_gen(text, working)
    pair = _bus_pair(text, working)
    ratio = _extract_ratio(text)

    all_ops: List[Dict[str, Any]] = []
    for _name, pattern, handler, options in RULES:
        if not pattern.search(text):
            continue
        ctx = {
            "text": text,
            "bus": base_bus,
            "gen": base_gen,
            "branch_pair": pair,
            "ratio": ratio,
        }
        if options.get("needs_bus") and ctx["bus"] is None and not (
            options.get("needs_ratio") and ratio
        ):
            continue
        if options.get("needs_gen") and ctx["gen"] is None:
            continue
        if options.get("needs_pair") and ctx["branch_pair"] is None:
            continue
        if options.get("needs_ratio") and not ratio:
            continue
        ops = handler(working, ctx)
        if ops:
            all_ops.extend(ops)
            break

    if not all_ops:
        return {
            "ops": [],
            "case": case,
            "reply": (
                "没有识别到可执行的修改。可以试试这些说法：\n"
                "· 把 5 号母线负荷增加到 120 兆瓦\n"
                "· 2 号发电机出力调到 200 兆瓦\n"
                "· 断开 6-7 线路\n"
                "· 把 4-7 变压器变比改为 1.02\n"
                "· 全网负荷降低 10%"
            ),
            "applied": False,
        }

    lines = [f"已按你的要求修改「{working.name}」，共 {len(all_ops)} 项操作："]
    for index, item in enumerate(all_ops, start=1):
        lines.append(f"{index}. {item['target']}：{item['detail']}")
    lines.append("修改后的算例可以点击“运行仿真”立即求解。")
    return {"ops": all_ops, "case": working, "reply": "\n".join(lines), "applied": True}


def diagnose(case: Case, result: Dict[str, Any]) -> Dict[str, Any]:
    """对潮流结果做工程化体检，输出教学式结论。"""
    if not result or not result.get("buses"):
        return {"level": "risk", "findings": [{"title": "无有效结果", "detail": "请先运行潮流计算。", "level": "risk"}],
                "text": "尚未获得潮流结果，请先运行仿真。"}
    if not result.get("converged"):
        return {
            "level": "risk",
            "findings": [{"title": "潮流不收敛", "detail": result.get("error", "请检查网络连通性与参数合理性。"), "level": "risk"}],
            "text": "潮流计算未收敛，通常说明存在孤岛、参数异常或运行点超出可行域。",
        }

    findings: List[Dict[str, Any]] = []
    buses = result["buses"]
    branches = result["branches"]
    summary = result["summary"]

    low_voltage = [bus for bus in buses if bus["vm"] < bus.get("vmin", 0.9) - 1e-9]
    high_voltage = [bus for bus in buses if bus["vm"] > bus.get("vmax", 1.1) + 1e-9]
    if low_voltage:
        worst = min(low_voltage, key=lambda bus: bus["vm"])
        findings.append({
            "title": f"电压越下限（{len(low_voltage)} 个母线）",
            "detail": (
                f"最低为母线 {worst['id']}：{worst['vm']:.4f} p.u.，低于下限 "
                f"{worst.get('vmin', 0.9):.2f}。说明该区域无功功率不足，"
                "可考虑投并联电容器、抬高发电机机端电压或减小该区负荷。"
            ),
            "level": "warn",
        })
    if high_voltage:
        worst = max(high_voltage, key=lambda bus: bus["vm"])
        findings.append({
            "title": f"电压越上限（{len(high_voltage)} 个母线）",
            "detail": (
                f"最高为母线 {worst['id']}：{worst['vm']:.4f} p.u.，高于上限 "
                f"{worst.get('vmax', 1.1):.2f}。轻载长线路容易出现过电压，"
                "可投入并联电抗器或降低机端电压。"
            ),
            "level": "warn",
        })

    overload = [branch for branch in branches if branch["loading"] > 100.0]
    if overload:
        worst = max(overload, key=lambda branch: branch["loading"])
        findings.append({
            "title": f"线路过载（{len(overload)} 条）",
            "detail": (
                f"最严重为支路 {worst['from']}-{worst['to']}，负载率 {worst['loading']:.1f}%，"
                f"输送功率 {max(abs(worst['p_from']), abs(worst['p_to'])):.1f} MW，"
                f"额定 {worst['rate']:.0f} MVA。建议转移负荷或增设并列线路。"
            ),
            "level": "warn" if worst["loading"] < 130 else "risk",
        })

    angle_pairs = [
        (branch, abs(next(bus["va"] for bus in buses if bus["id"] == branch["from"])
                     - next(bus["va"] for bus in buses if bus["id"] == branch["to"])))
        for branch in branches
    ]
    if angle_pairs:
        worst_branch, worst_angle = max(angle_pairs, key=lambda item: item[1])
        if worst_angle > 20.0:
            findings.append({
                "title": "支路两端相角差偏大",
                "detail": (
                    f"支路 {worst_branch['from']}-{worst_branch['to']} 相角差 {worst_angle:.2f}°，"
                    "接近静态稳定极限的征兆，应关注该通道的输电能力。"
                ),
                "level": "warn" if worst_angle < 30 else "risk",
            })

    for gen in result.get("generators", []):
        if gen["qg"] > gen["qmax"] + 1e-6:
            findings.append({
                "title": f"发电机 {gen['id']} 无功越上限",
                "detail": f"实际 {gen['qg']:.1f} MVar 超过上限 {gen['qmax']:.0f} MVar，"
                          "潮流计算中应转为 PQ 节点处理。",
                "level": "warn",
            })

    loss_ratio = summary["loss_p"] / max(summary["total_load_p"], 1e-9) * 100.0
    findings.append({
        "title": "网损与平衡机出力",
        "detail": (
            f"有功网损 {summary['loss_p']:.2f} MW，占负荷 {loss_ratio:.2f}%；"
            f"平衡机出力 {summary['slack_p']:.2f} MW、{summary['slack_q']:.2f} MVar，"
            f"全网最高电压 {summary['max_vm']:.4f} p.u.，最低 {summary['min_vm']:.4f} p.u.。"
        ),
        "level": "ok",
    })

    level = "ok"
    if any(item["level"] == "risk" for item in findings):
        level = "risk"
    elif any(item["level"] == "warn" for item in findings):
        level = "warn"

    header = {"ok": "潮流结果正常，运行点处于合理范围。",
              "warn": "潮流收敛，但存在需要关注的问题。",
              "risk": "潮流结果存在风险点，建议调整运行方式。"}[level]
    text = header + "\n" + "\n".join(
        f"· {item['title']}：{item['detail']}" for item in findings
    )
    return {"level": level, "findings": findings, "text": text}


def draft_report(
    case: Case,
    power_flow: Optional[Dict[str, Any]] = None,
    short_circuit: Optional[Dict[str, Any]] = None,
    stability: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """生成可直接提交的实验报告草稿（Markdown）。"""
    meta = meta or {}
    lines: List[str] = []
    title = meta.get("title") or f"{case.name} 仿真实验报告"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 实验人：{meta.get('author', '（请填写）')}")
    lines.append(f"- 学号：{meta.get('student_no', '（请填写）')}")
    lines.append(f"- 算例：{case.name}（{case.id}）")
    lines.append(f"- 基准容量：{case.base_mva:g} MVA，基准电压：{case.base_kv:g} kV")
    lines.append("")
    lines.append("## 一、实验目的")
    lines.append("")
    lines.append("掌握电力系统潮流计算的基本原理与求解流程，熟悉节点类型划分、"
                 "牛顿-拉夫逊法迭代收敛特性，并能对计算结果进行工程判断。")
    lines.append("")
    lines.append("## 二、系统模型")
    lines.append("")
    lines.append(f"系统共 {len(case.buses)} 个节点、{len(case.branches)} 条支路、"
                 f"{len(case.gens)} 台发电机，平衡节点为母线 {case.slack_bus().id}。")
    lines.append("")
    lines.append("| 节点 | 类型 | 电压设定值 (p.u.) | 有功负荷 (MW) | 无功负荷 (MVar) |")
    lines.append("| --- | --- | --- | --- | --- |")
    for bus in case.buses:
        lines.append(f"| {bus.id} | {bus.type} | {bus.vm:.3f} | {bus.pd:.1f} | {bus.qd:.1f} |")
    lines.append("")
    lines.append("| 支路 | 首端 | 末端 | R (p.u.) | X (p.u.) | B (p.u.) | 变比 | 额定 (MVA) |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for branch in case.branches:
        lines.append(
            f"| {branch.id} | {branch.fbus} | {branch.tbus} | {branch.r:.4f} | {branch.x:.4f} "
            f"| {branch.b:.4f} | {branch.tap:.3f} | {branch.rate:.0f} |"
        )
    lines.append("")

    if power_flow and power_flow.get("buses"):
        lines.append("## 三、潮流计算结果")
        lines.append("")
        lines.append(f"牛顿-拉夫逊法迭代 {power_flow['iterations']} 次收敛，"
                     f"最大功率不平衡量 {power_flow['summary']['mismatch']:.3e}。")
        lines.append("")
        lines.append("| 节点 | 电压 (p.u.) | 相角 (°) | 注入有功 (MW) | 注入无功 (MVar) |")
        lines.append("| --- | --- | --- | --- | --- |")
        for bus in power_flow["buses"]:
            lines.append(
                f"| {bus['id']} | {bus['vm']:.4f} | {bus['va']:.3f} "
                f"| {bus['p']:.2f} | {bus['q']:.2f} |"
            )
        lines.append("")
        lines.append("| 支路 | 首端有功 (MW) | 末端有功 (MW) | 有功损耗 (MW) | 负载率 (%) |")
        lines.append("| --- | --- | --- | --- | --- |")
        for branch in power_flow["branches"]:
            lines.append(
                f"| {branch['from']}-{branch['to']} | {branch['p_from']:.2f} "
                f"| {branch['p_to']:.2f} | {branch['loss_p']:.2f} | {branch['loading']:.1f} |"
            )
        lines.append("")
        summary = power_flow["summary"]
        lines.append(
            f"全网有功负荷 {summary['total_load_p']:.2f} MW，有功网损 {summary['loss_p']:.2f} MW，"
            f"平衡机出力 {summary['slack_p']:.2f} MW。"
        )
        lines.append("")
        diag = diagnose(case, power_flow)
        lines.append("## 四、结果分析")
        lines.append("")
        lines.append(diag["text"])
        lines.append("")
        if not diag["findings"]:
            lines.append("（可在此补充与理论分析的对照，例如电压降落公式、网损构成等。）")
            lines.append("")

    if short_circuit and short_circuit.get("per_bus"):
        lines.append("## 五、短路电流计算")
        lines.append("")
        lines.append(
            f"故障母线：{short_circuit['fault_bus']}，三相短路电流 "
            f"{short_circuit['fault_current_ka']:.3f} kA（{short_circuit['fault_current_pu']:.4f} p.u.），"
            f"短路容量 {short_circuit['short_circuit_mva']:.2f} MVA。"
        )
        lines.append("")
        lines.append("| 节点 | 故障前电压 (p.u.) | 自阻抗 (p.u.) | 短路电流 (kA) |")
        lines.append("| --- | --- | --- | --- |")
        for item in short_circuit["per_bus"]:
            lines.append(
                f"| {item['bus']} | {item['vm_pre']:.4f} | {item['zbus_mag']:.4f} "
                f"| {item['current_ka']:.3f} |"
            )
        lines.append("")

    if stability and stability.get("stable") is not None and stability.get("curves"):
        lines.append("## 六、暂态稳定分析")
        lines.append("")
        verdict = "保持稳定" if stability["stable"] else "失去稳定"
        lines.append(
            f"故障母线 {stability['fault_bus']}，切除线路 "
            f"{'-'.join(str(x) for x in stability.get('trip_branch', [])) or '（无）'}，"
            f"切除时间 {stability['clearing_time']:.3f} s，仿真结论：{verdict}，"
            f"最大相对功角差 {stability['max_angle_diff_deg']:.2f}°。"
        )
        lines.append("")
        if stability.get("cct"):
            lines.append(f"极限切除时间（CCT）约为 {stability['cct']:.3f} s。")
            lines.append("")

    lines.append("## 七、实验结论")
    lines.append("")
    lines.append("1. 通过牛顿-拉夫逊法完成潮流求解，验证了节点功率平衡关系。")
    lines.append("2. 依据结果分析提出运行调整建议。")
    lines.append("3. （请结合课堂理论补充个人总结。）")
    lines.append("")
    return "\n".join(lines)


def _llm_settings() -> Optional[Dict[str, str]]:
    """读取大模型配置；未配置返回 None。"""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return {
            "key": os.environ["DEEPSEEK_API_KEY"],
            "base": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        }
    if os.environ.get("OPENAI_API_KEY"):
        return {
            "key": os.environ["OPENAI_API_KEY"],
            "base": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        }
    return None


def llm_available() -> bool:
    """是否已配置大模型密钥。"""
    return _llm_settings() is not None


def _call_llm(message: str, context: Dict[str, Any], timeout: float = 25.0) -> Optional[str]:
    """调用 OpenAI 兼容 Chat Completions 接口，失败返回 None。"""
    settings = _llm_settings()
    if not settings:
        return None
    system = (
        "你是武汉大学电气与自动化学院的电力系统教学助教，回答面向本科生。"
        "要求：先给结论，再给依据；适当引用《电力系统分析》中的公式；"
        "不使用 markdown 表格以外的复杂排版；不确定时明确说明。"
    )
    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"当前算例与结果上下文：{json.dumps(context, ensure_ascii=False)[:6000]}\n\n学生提问：{message}"},
        ],
        "temperature": 0.3,
    }
    request = urllib.request.Request(
        f"{settings['base'].rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def chat(message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """对话入口：优先本规则引擎，必要时调用大模型。"""
    context = context or {}
    case_data = context.get("case")
    case = Case.from_dict(case_data) if case_data else None
    instruction_like = bool(re.search(
        r"(把|将|调|设|改|增加|提高|降低|减少|断开|切除|投入|合上|变比)", message or ""
    ))

    if case is not None and instruction_like:
        outcome = apply_instruction(case, message)
        if outcome["applied"]:
            reply = outcome["reply"]
            if llm_available():
                extra = _call_llm(message, context)
                if extra:
                    reply = f"{reply}\n\n【AI 补充】{extra}"
            return {"reply": reply, "ops": outcome["ops"], "source": "rule", "case": outcome["case"].to_dict()}

    result = context.get("result")
    if case is not None and result and re.search(r"(为什么|解释|分析|诊断|检查|是否|怎么样|如何)", message or ""):
        diag = diagnose(case, result)
        return {"reply": diag["text"], "ops": [], "source": "rule", "level": diag["level"]}

    llm_reply = _call_llm(message, context)
    if llm_reply:
        return {"reply": llm_reply, "ops": [], "source": "llm"}

    if case is not None and result:
        diag = diagnose(case, result)
        return {"reply": diag["text"], "ops": [], "source": "rule", "level": diag["level"]}

    return {
        "reply": (
            "我是电力系统教学助教，可以：\n"
            "1. 按自然语言修改算例（例如“把 5 号母线负荷增加到 120 兆瓦”）；\n"
            "2. 解释潮流、短路、稳定结果（例如“为什么 9 号母线电压偏低”）；\n"
            "3. 生成实验报告草稿。\n"
            "如需更强的自由问答能力，可在服务器配置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY。"
        ),
        "ops": [],
        "source": "rule",
    }
