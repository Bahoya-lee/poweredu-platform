"""稠密线性代数核心（纯标准库，兼容实数与复数）。

电力系统计算中反复出现的线性方程组求解、矩阵求逆都在这里实现，
不依赖 numpy，保证平台在任何只有 Python 的机器上都能跑起来。
"""

from __future__ import annotations

from typing import List, Sequence, TypeVar

Number = TypeVar("Number", float, complex)

EPS = 1e-12


def identity(size: int) -> List[List[float]]:
    """返回 size 阶单位矩阵。"""
    return [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]


def matmul(a: Sequence[Sequence[Number]], b: Sequence[Sequence[Number]]) -> List[List[Number]]:
    """矩阵乘法 a · b。"""
    if not a:
        return []
    inner = len(b)
    cols = len(b[0]) if b else 0
    out: List[List[Number]] = [[0.0 for _ in range(cols)] for _ in range(len(a))]
    for i, row in enumerate(a):
        for k in range(inner):
            aik = row[k]
            if aik == 0:
                continue
            b_row = b[k]
            out_row = out[i]
            for j in range(cols):
                out_row[j] += aik * b_row[j]
    return out


def matvec(a: Sequence[Sequence[Number]], x: Sequence[Number]) -> List[Number]:
    """矩阵乘向量 a · x。"""
    return [sum(aij * xj for aij, xj in zip(row, x)) for row in a]


def solve(matrix: Sequence[Sequence[Number]], rhs: Sequence[Number]) -> List[Number]:
    """用列主元高斯消元求解线性方程组 matrix · x = rhs。"""
    n = len(matrix)
    if n == 0:
        return []
    if len(rhs) != n:
        raise ValueError("矩阵与右端向量维度不匹配")

    a = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < EPS:
            raise ValueError(f"矩阵奇异或接近奇异：第 {col} 列主元过小")
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]

        pivot_row = a[col]
        pivot_value = pivot_row[col]
        for j in range(col, n + 1):
            pivot_row[j] /= pivot_value

        for r in range(n):
            if r == col:
                continue
            factor = a[r][col]
            if factor == 0:
                continue
            row = a[r]
            for j in range(col, n + 1):
                row[j] -= factor * pivot_row[j]

    return [row[n] for row in a]


def invert(matrix: Sequence[Sequence[Number]]) -> List[List[Number]]:
    """Gauss-Jordan 求逆，奇异矩阵抛 ValueError。"""
    n = len(matrix)
    if n == 0:
        return []
    a = [list(row) + eye for row, eye in zip(matrix, identity(n))]

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < EPS:
            raise ValueError(f"矩阵不可逆：第 {col} 列主元过小")
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]

        pivot_row = a[col]
        pivot_value = pivot_row[col]
        for j in range(2 * n):
            pivot_row[j] /= pivot_value

        for r in range(n):
            if r == col:
                continue
            factor = a[r][col]
            if factor == 0:
                continue
            row = a[r]
            for j in range(2 * n):
                row[j] -= factor * pivot_row[j]

    return [row[n:] for row in a]
