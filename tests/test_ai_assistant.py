"""AI 助教测试：自然语言改算例、结果诊断、报告生成。"""

from __future__ import annotations

import unittest

from server.ai_assistant import apply_instruction, chat, diagnose, draft_report, llm_available
from server.engine.cases import get_case
from server.engine.powerflow import solve_power_flow


class InstructionTest(unittest.TestCase):
    def test_set_bus_load_in_megawatt(self) -> None:
        out = apply_instruction(get_case("wscc9"), "把5号母线的负荷增加到120兆瓦")
        self.assertTrue(out["applied"])
        bus5 = [bus for bus in out["case"].buses if bus.id == 5][0]
        self.assertEqual(bus5.pd, 120.0)
        self.assertEqual(out["ops"][0]["op"], "set_load")

    def test_set_load_in_kilowatt(self) -> None:
        out = apply_instruction(get_case("wscc9"), "把6号母线负荷设为50000千瓦")
        bus6 = [bus for bus in out["case"].buses if bus.id == 6][0]
        self.assertEqual(bus6.pd, 50.0)

    def test_set_generator_power(self) -> None:
        out = apply_instruction(get_case("wscc9"), "2号发电机出力调到200兆瓦")
        gen2 = [gen for gen in out["case"].gens if gen.id == 2][0]
        self.assertEqual(gen2.pg, 200.0)

    def test_scale_all_loads(self) -> None:
        case = get_case("wscc9")
        before = sum(bus.pd for bus in case.buses)
        out = apply_instruction(case, "全网负荷降低10%")
        after = sum(bus.pd for bus in out["case"].buses)
        self.assertAlmostEqual(after, before / 1.1, places=1)

    def test_toggle_branch(self) -> None:
        out = apply_instruction(get_case("ieee14"), "断开4-7线路")
        branch = [item for item in out["case"].branches if {item.fbus, item.tbus} == {4, 7}][0]
        self.assertEqual(branch.status, 0)
        self.assertEqual(out["ops"][0]["op"], "toggle_branch")

    def test_set_transformer_tap(self) -> None:
        out = apply_instruction(get_case("ieee14"), "把4-7变压器变比改为1.02")
        branch = [item for item in out["case"].branches if {item.fbus, item.tbus} == {4, 7}][0]
        self.assertAlmostEqual(branch.tap, 1.02, places=6)

    def test_instruction_does_not_mutate_source_case(self) -> None:
        case = get_case("wscc9")
        apply_instruction(case, "把5号母线的负荷增加到120兆瓦")
        self.assertEqual(case.buses[4].pd, 90.0)

    def test_unknown_instruction_returns_hint(self) -> None:
        out = apply_instruction(get_case("wscc9"), "今天天气怎么样")
        self.assertFalse(out["applied"])
        self.assertIn("没有识别到", out["reply"])


class DiagnoseTest(unittest.TestCase):
    def test_heavy_load_flags_low_voltage(self) -> None:
        case = get_case("radial5")
        case.buses[4].pd = 2.0
        case.buses[4].qd = 0.8
        result = solve_power_flow(case)
        self.assertTrue(result["converged"])
        diag = diagnose(case, result)
        self.assertIn(diag["level"], ("warn", "risk"))
        self.assertTrue(any("电压" in finding["title"] for finding in diag["findings"]))
        self.assertIn("电压", diag["text"])

    def test_normal_case_is_ok(self) -> None:
        case = get_case("wscc9")
        diag = diagnose(case, solve_power_flow(case))
        self.assertEqual(diag["level"], "ok")
        self.assertTrue(any("网损" in finding["title"] for finding in diag["findings"]))

    def test_nonconverged_result_is_risk(self) -> None:
        diag = diagnose(get_case("wscc9"), {"converged": False, "buses": [{}], "error": "测试"})
        self.assertEqual(diag["level"], "risk")

    def test_missing_result_is_risk(self) -> None:
        diag = diagnose(get_case("wscc9"), {})
        self.assertEqual(diag["level"], "risk")


class ReportTest(unittest.TestCase):
    def test_report_contains_key_sections(self) -> None:
        case = get_case("wscc9")
        report = draft_report(case, solve_power_flow(case), meta={"author": "测试同学", "student_no": "2025001"})
        for token in ("# ", "实验目的", "系统模型", "潮流计算结果", "结果分析", "测试同学", "2025001"):
            self.assertIn(token, report)
        self.assertGreater(len(report), 800)


class ChatTest(unittest.TestCase):
    def test_chat_applies_instruction_and_returns_case(self) -> None:
        case = get_case("wscc9")
        reply = chat("把5号母线负荷增加到130兆瓦", {"case": case.to_dict()})
        self.assertEqual(reply["source"], "rule")
        self.assertTrue(reply["ops"])
        self.assertEqual(reply["case"]["buses"][4]["pd"], 130.0)

    def test_chat_explains_result(self) -> None:
        case = get_case("wscc9")
        result = solve_power_flow(case)
        reply = chat("为什么结果是这样的？", {"case": case.to_dict(), "result": result})
        self.assertIn(reply["source"], ("rule", "llm"))
        self.assertTrue(reply["reply"])

    def test_llm_flag_reflects_environment(self) -> None:
        self.assertIsInstance(llm_available(), bool)


if __name__ == "__main__":
    unittest.main()
