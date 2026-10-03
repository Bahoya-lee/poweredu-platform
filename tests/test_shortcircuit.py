"""三相短路电流测试。"""

from __future__ import annotations

import math
import unittest

from server.engine.cases import get_case
from server.engine.shortcircuit import solve_short_circuit


class ShortCircuitTest(unittest.TestCase):
    def test_two_machine_matches_analytic_solution(self) -> None:
        """单机经线路供电：I_pu 应等于 故障前电压 / |Z_line + X'd|。"""
        case = get_case("two_machine")
        result = solve_short_circuit(case, fault_bus=2)
        expected_pu = result["prefault_vm"] / abs(complex(0.01, 0.30))
        self.assertLess(abs(result["fault_current_pu"] - expected_pu) / expected_pu, 1e-6)
        current_base = case.base_mva / (math.sqrt(3.0) * case.base_kv)
        self.assertAlmostEqual(result["fault_current_ka"], expected_pu * current_base, places=4)

    def test_fault_bus_voltage_collapses(self) -> None:
        result = solve_short_circuit(get_case("ieee14"), fault_bus=4)
        voltage = {item["bus"]: item["vm"] for item in result["bus_voltages"]}
        self.assertLess(voltage[4], 0.05)
        self.assertGreater(voltage[8], 0.5)

    def test_per_bus_table_covers_all_buses(self) -> None:
        case = get_case("ieee14")
        result = solve_short_circuit(case, fault_bus=9)
        self.assertEqual(len(result["per_bus"]), len(case.buses))
        strongest = max(result["per_bus"], key=lambda item: item["current_ka"])
        self.assertGreater(strongest["current_ka"], 0.0)

    def test_default_fault_bus_is_heaviest_load(self) -> None:
        case = get_case("wscc9")
        result = solve_short_circuit(case)
        self.assertIn(result["fault_bus"], [6, 8])

    def test_unknown_bus_returns_error(self) -> None:
        result = solve_short_circuit(get_case("wscc9"), fault_bus=99)
        self.assertIn("99", result["error"])


if __name__ == "__main__":
    unittest.main()
