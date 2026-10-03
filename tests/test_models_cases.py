"""元件模型与算例库测试。"""

from __future__ import annotations

import unittest

from server.engine.cases import all_cases, case_ids, get_case, list_cases, register_case
from server.engine.models import Bus, Case, Gen


class ModelTest(unittest.TestCase):
    def test_roundtrip_keeps_bus_order_and_types(self) -> None:
        case = get_case("wscc9")
        data = case.to_dict()
        again = Case.from_dict(data)
        self.assertEqual(again.bus_ids(), case.bus_ids())
        self.assertEqual(again.buses[0].type, "SLACK")
        self.assertEqual(again.validate(), [])

    def test_invalid_bus_type_falls_back_to_pq(self) -> None:
        bus = Bus.from_dict({"id": 3, "type": "unknown"})
        self.assertEqual(bus.type, "PQ")

    def test_validate_reports_dangling_branch(self) -> None:
        case = get_case("wscc9")
        case.branches[0].tbus = 99
        self.assertTrue(any("99" in msg for msg in case.validate()))

    def test_validate_requires_exactly_one_slack(self) -> None:
        case = get_case("wscc9")
        case.buses[1].type = "SLACK"
        case.gens  # 保持结构
        self.assertTrue(any("平衡节点" in msg for msg in case.validate()))

    def test_validate_requires_generator_on_pv_bus(self) -> None:
        case = Case(id="t", name="t", buses=[Bus(id=1, type="SLACK")], gens=[], branches=[])
        self.assertTrue(any("没有投运的发电机" in msg for msg in case.validate()))

    def test_clone_is_deep(self) -> None:
        case = get_case("wscc9")
        clone = case.clone()
        clone.buses[4].pd = 999.0
        self.assertNotEqual(case.buses[4].pd, 999.0)


class CaseLibraryTest(unittest.TestCase):
    def test_all_builtin_cases_are_valid(self) -> None:
        for case in all_cases():
            self.assertEqual(case.validate(), [], f"{case.id} 参数存在问题")

    def test_expected_case_inventory(self) -> None:
        self.assertEqual(len(get_case("wscc9").buses), 9)
        self.assertEqual(len(get_case("ieee14").branches), 20)
        self.assertIn("two_machine", case_ids())
        self.assertIn("radial5", case_ids())

    def test_unknown_case_raises(self) -> None:
        with self.assertRaises(KeyError):
            get_case("not_exist")

    def test_list_cases_returns_summaries(self) -> None:
        summaries = list_cases()
        self.assertTrue(summaries)
        for item in summaries:
            for key in ("id", "name", "bus_count", "branch_count", "load_p_mw", "slack_bus"):
                self.assertIn(key, item)

    def test_register_custom_case_keeps_copy(self) -> None:
        case = get_case("two_machine")
        case.id = "custom_demo"
        case.name = "自定义演示"
        register_case("custom_demo", case)
        case.name = "被改坏的名字"
        self.assertEqual(get_case("custom_demo").name, "自定义演示")


if __name__ == "__main__":
    unittest.main()
