"""Minimal pure-Python quaternion math (w, x, y, z) for the backend (Blender uses mathutils)."""

from __future__ import annotations

import math

Q = tuple[float, float, float, float]
IDENTITY: Q = (1.0, 0.0, 0.0, 0.0)
AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


def axis_angle(axis, deg: float) -> Q:
    if isinstance(axis, str):
        axis = AXES[axis]
    n = math.sqrt(sum(c * c for c in axis)) or 1.0
    a = math.radians(deg) / 2
    s = math.sin(a) / n
    return (math.cos(a), axis[0] * s, axis[1] * s, axis[2] * s)


def mul(a: Q, b: Q) -> Q:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def conj(a: Q) -> Q:
    return (a[0], -a[1], -a[2], -a[3])


def norm(a: Q) -> Q:
    n = math.sqrt(sum(c * c for c in a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n, a[3] / n)


def dot(a: Q, b: Q) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def slerp(a: Q, b: Q, t: float) -> Q:
    d = dot(a, b)
    if d < 0:
        b = (-b[0], -b[1], -b[2], -b[3])
        d = -d
    if d > 0.9995:
        return norm(tuple(a[i] + (b[i] - a[i]) * t for i in range(4)))
    th = math.acos(max(-1.0, min(1.0, d)))
    s = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return tuple(a[i] * wa + b[i] * wb for i in range(4))


def power(a: Q, k: float) -> Q:
    """Scale a rotation's angle by k (k > 1 exaggerates, < 1 damps)."""
    a = norm(a)
    w = max(-1.0, min(1.0, a[0]))
    ang = 2 * math.acos(w)
    s = math.sqrt(max(0.0, 1 - w * w))
    if s < 1e-8:
        return IDENTITY
    axis = (a[1] / s, a[2] / s, a[3] / s)
    return axis_angle(axis, math.degrees(ang * k))


def angle_deg(a: Q) -> float:
    w = max(-1.0, min(1.0, abs(norm(a)[0])))
    return math.degrees(2 * math.acos(w))


def rotate(a: Q, v) -> tuple[float, float, float]:
    p = (0.0, v[0], v[1], v[2])
    r = mul(mul(a, p), conj(a))
    return (r[1], r[2], r[3])


def between(u, v) -> Q:
    """Shortest rotation taking direction u onto direction v."""
    nu = math.sqrt(sum(c * c for c in u)) or 1.0
    nv = math.sqrt(sum(c * c for c in v)) or 1.0
    u = [c / nu for c in u]
    v = [c / nv for c in v]
    d = sum(a * b for a, b in zip(u, v, strict=False))
    if d < -0.999999:
        ortho = (1.0, 0.0, 0.0) if abs(u[0]) < 0.9 else (0.0, 1.0, 0.0)
        c = (u[1] * ortho[2] - u[2] * ortho[1], u[2] * ortho[0] - u[0] * ortho[2], u[0] * ortho[1] - u[1] * ortho[0])
        return axis_angle(c, 180.0)
    c = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return norm((1.0 + d, c[0], c[1], c[2]))


def euler(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Q:
    """XYZ euler (degrees, armature axes): X applied first, then Y, then Z."""
    return mul(axis_angle("Z", z), mul(axis_angle("Y", y), axis_angle("X", x)))


def mirror(a: Q) -> Q:
    """Mirror across the YZ plane (character left <-> right)."""
    return (a[0], a[1], -a[2], -a[3])


def rounded(a: Q, nd: int = 5) -> list[float]:
    return [round(c, nd) for c in a]
