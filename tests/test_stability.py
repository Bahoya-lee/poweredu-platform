"""暂态稳定时域仿真测试。"""

from __future__ import annotations

import unittest

from server.engine.cases import get_case
from server.engine.stability import (
    find_critical_clearing_time,
    resolve_branch_ids,
    simulate_transient_stability,
)


class StabilityTest(unittest.TestCase):
    def test_resolve_branch_ids_accepts_bus_pair_and_id(self) -> None:
        case = get_case("wscc9")
        self.assertEqual(len(resolve_branch_ids(case, (6, 7))), 1)
        self.assertEqual(resolve_branch_ids(case, 5), [5])
        self.assertEqual(resolve_branch_ids(case, [(6, 7), 8]), [5, 8])
        # 母线对不分首末端：5-6 与 6-5 指向同一条支路
        self.assertEqual(resolve_branch_ids(case, (6, 5)), resolve_branch_ids(case, (5, 6)))
        # 不存在的母线对返回空列表
        self.assertEqual(resolve_branch_ids(case, (1, 2)), [])

    def test_early_clearing_stable_late_clearing_unstable(self) -> None:
        early = simulate_transient_stability(get_case("wscc9"), 7, (6, 7), 0.05)
        late = simulate_transient_stability(get_case("wscc9"), 7, (6, 7), 0.60)
        self.assertTrue(early["stable"], early.get("error"))
        self.assertFalse(late["stable"])
        self.assertLess(early["max_angle_diff_deg"], 180.0)

    def test_curves_have_consistent_length(self) -> None:
        result = simulate_transient_stability(get_case("wscc9"), 7, (6, 7), 0.1, t_end=1.0, dt=0.01)
        length = len(result["curves"]["t"])
        self.assertEqual(length, 101)
        for machine in result["curves"]["machines"]:
            self.assertEqual(len(machine["delta_deg"]), length)
            self.assertEqual(len(machine["omega_pu"]), length)

    def test_more_severe_fault_reduces_cct(self) -> None:
        mild = find_critical_clearing_time(get_case("wscc9"), 7, (6, 7), lo=0.02, hi=0.5, tol=0.02)
        severe = find_critical_clearing_time(get_case("wscc9"), 5, (4, 5), lo=0.02, hi=0.5, tol=0.02)
        self.assertGreater(mild["cct"], 0.05)
        self.assertLess(mild["cct"], 0.5)
        self.assertLessEqual(severe["cct"], 0.5)

    def test_unknown_trip_branch_returns_error(self) -> None:
        result = simulate_transient_stability(get_case("wscc9"), 7, (1, 2), 0.1)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
