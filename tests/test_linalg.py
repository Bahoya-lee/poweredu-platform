"""线性代数内核测试。"""

from __future__ import annotations

import unittest

from server.engine.linalg import identity, invert, matmul, matvec, solve


class LinalgTest(unittest.TestCase):
    def test_solve_matches_hand_calculation(self) -> None:
        result = solve([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0])
        self.assertAlmostEqual(result[0], 1.0, places=9)
        self.assertAlmostEqual(result[1], 3.0, places=9)

    def test_solve_complex_system(self) -> None:
        matrix = [[2 + 1j, 1 - 1j], [0.5j, 3 + 2j]]
        rhs = [1 + 0j, 2 - 1j]
        x = solve(matrix, rhs)
        for got, want in zip(matvec(matrix, x), rhs):
            self.assertAlmostEqual(abs(got - want), 0.0, places=9)

    def test_invert_complex_matrix_gives_identity(self) -> None:
        matrix = [[1 + 1j, 2 - 1j], [0.5j, 3 + 0j]]
        product = matmul(invert(matrix), matrix)
        for i in range(2):
            for j in range(2):
                self.assertAlmostEqual(abs(product[i][j] - identity(2)[i][j]), 0.0, places=9)

    def test_singular_matrix_raises(self) -> None:
        with self.assertRaises(ValueError):
            solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
