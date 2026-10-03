"""牛顿-拉夫逊潮流测试：以独立公式复算 KCL 残差，并对 IEEE 14 标准解回归。"""

from __future__ import annotations

import cmath
import math
import unittest

from server.engine.cases import get_case
from server.engine.models import Bus, Case, Gen
from server.engine.powerflow import build_ybus, solve_power_flow

# IEEE 14 节点公开标准解的电压幅值（p.u.）与相角（度）
IEEE14_VM = [1.06000, 1.04500, 1.01000, 1.01905, 1.01953, 1.07000, 1.06196,
             1.09000, 1.05593, 1.05110, 1.05661, 1.05500, 1.05001, 1.03544]
IEEE14_VA = [0.0, -4.98, -12.72, -10.33, -8.78, -14.22, -13.37, -13.36,
             -14.94, -15.10, -14.79, -15.07, -15.16, -16.04]


def independent_injection(case: Case, vm, va_deg):
    """用测试内独立编写的 π 型等效公式复算各母线注入功率（标幺值）。"""
    n = len(case.buses)
    position = {bus.id: i for i, bus in enumerate(case.buses)}
    admittance = [[0j for _ in range(n)] for _ in range(n)]
    for branch in case.branches:
        i, j = position[branch.fbus], position[branch.tbus]
        series = 1.0 / complex(branch.r, branch.x)
        ratio = branch.tap * cmath.exp(1j * math.radians(branch.shift))
        # 与生产代码写法不同：显式用 1/(t·t*) 与共轭形式装配
        admittance[i][i] += (series + 1j * branch.b / 2.0) / (ratio * ratio.conjugate()).real
        admittance[i][j] += -series / ratio.conjugate()
        admittance[j][i] += -series / ratio
        admittance[j][j] += series + 1j * branch.b / 2.0
    for bus in case.buses:
        index = position[bus.id]
        admittance[index][index] += complex(bus.gs, bus.bs) / case.base_mva

    voltage = [cmath.rect(m, math.radians(a)) for m, a in zip(vm, va_deg)]
    injections = []
    for i in range(n):
        current = sum(admittance[i][j] * voltage[j] for j in range(n))
        injections.append(voltage[i] * current.conjugate())
    return injections


class PowerFlowTest(unittest.TestCase):
    def test_wscc9_converges_and_satisfies_kcl(self) -> None:
        case = get_case("wscc9")
        result = solve_power_flow(case)
        self.assertTrue(result["converged"], result.get("error"))
        self.assertLessEqual(result["iterations"], 6)

        vm = [bus["vm"] for bus in result["buses"]]
        va = [bus["va"] for bus in result["buses"]]
        injections = independent_injection(case, vm, va)
        for i, bus in enumerate(case.buses):
            pg, qg = case.gen_power_at(bus.id)
            if bus.type == "SLACK":
                continue
            self.assertAlmostEqual(injections[i].real, (pg - bus.pd) / case.base_mva, places=6,
                                   msg=f"母线 {bus.id} 有功不平衡")
            if bus.type == "PQ":
                self.assertAlmostEqual(injections[i].imag, (qg - bus.qd) / case.base_mva, places=6,
                                       msg=f"母线 {bus.id} 无功不平衡")

    def test_ieee14_matches_published_solution(self) -> None:
        result = solve_power_flow(get_case("ieee14"))
        self.assertTrue(result["converged"], result.get("error"))
        vm = [bus["vm"] for bus in result["buses"]]
        va = [bus["va"] for bus in result["buses"]]
        for got, want in zip(vm, IEEE14_VM):
            self.assertLess(abs(got - want), 3e-3, "电压幅值偏离 IEEE 14 标准解")
        for got, want in zip(va, IEEE14_VA):
            self.assertLess(abs(got - want), 0.05, "电压相角偏离 IEEE 14 标准解")

    def test_power_balance_holds(self) -> None:
        result = solve_power_flow(get_case("wscc9"))
        summary = result["summary"]
        self.assertAlmostEqual(
            summary["total_load_p"] + summary["loss_p"],
            summary["total_gen_p"],
            places=6,
        )
        self.assertGreater(summary["loss_p"], 0.0)

    def test_branch_flow_consistency(self) -> None:
        result = solve_power_flow(get_case("ieee14"))
        for branch in result["branches"]:
            self.assertAlmostEqual(
                branch["loss_p"], branch["p_from"] + branch["p_to"], places=6
            )

    def test_flat_start_still_converges(self) -> None:
        result = solve_power_flow(get_case("ieee14"), flat_start=True)
        self.assertTrue(result["converged"], result.get("error"))

    def test_invalid_case_returns_error(self) -> None:
        case = Case(id="bad", name="缺平衡节点",
                    buses=[Bus(id=1, type="PQ", pd=10.0)],
                    gens=[Gen(id=1, bus=1, pg=10.0)], branches=[])
        result = solve_power_flow(case)
        self.assertFalse(result["converged"])
        self.assertTrue(result["error"])

    def test_radial5_voltage_drops_along_feeder(self) -> None:
        result = solve_power_flow(get_case("radial5"))
        vm = [bus["vm"] for bus in result["buses"]]
        self.assertEqual(vm, sorted(vm, reverse=True))

    def test_ybus_is_symmetric_without_transformers(self) -> None:
        case = get_case("radial5")
        ybus = build_ybus(case)
        for i in range(len(ybus)):
            for j in range(len(ybus)):
                self.assertAlmostEqual(ybus[i][j], ybus[j][i], places=12)


if __name__ == "__main__":
    unittest.main()
