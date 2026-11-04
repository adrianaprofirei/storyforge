"""BVH export of canonical clips (synthetic motion capture).

The built-in procedural clips are written as BVH files so the same import/retarget path used for
Mixamo/CMU mocap is exercised end-to-end (and users get standard files they can inspect in any
tool). BVH joint frames are axis-aligned at rest, so a joint's local BVH rotation equals our
canonical L (local delta in rest armature axes) — only the Z-up -> Y-up change of basis and the
ZXY Euler decomposition are needed.
"""

from __future__ import annotations

import math
from pathlib import Path

from storyforge.animation import quat as Q
from storyforge_blender.bonemap import CANONICAL, CANONICAL_PARENT
from storyforge_blender.proportions import body_metrics

TO_YUP = Q.axis_angle("X", -90.0)  # blender (x, y, z) -> bvh (x, z, -y)


def _yup(v):
    return (v[0], v[2], -v[1])


def rest_heads(body: dict | None = None) -> dict[str, tuple[float, float, float]]:
    m = body_metrics(body)
    hz, kz, az = m["hip_z"], m["knee_z"], m["ankle_z"]
    sx, sz = m["shoulder_x"], m["shoulder_z"]
    ua, fa, hd = m["upper_arm"], m["forearm"], m["hand"]
    fl = m["foot_length"]
    heads = {"hips": (0, 0, hz), "spine": (0, 0, m["torso_base"] + 0.04), "chest": (0, 0, m["chest_z"]),
             "neck": (0, 0, m["neck_base"]), "head": (0, 0, m["head_base"])}
    tails = {"head": (0, 0, m["head_top"])}
    for side, sg in (("L", 1), ("R", -1)):
        heads[f"shoulder.{side}"] = (sg * m["torso_w"] * 0.12, 0, sz)
        heads[f"upper_arm.{side}"] = (sg * sx, 0, sz)
        heads[f"forearm.{side}"] = (sg * (sx + ua), 0, sz)
        heads[f"hand.{side}"] = (sg * (sx + ua + fa), 0, sz)
        tails[f"hand.{side}"] = (sg * (sx + ua + fa + hd), 0, sz)
        hx = sg * m["hip_x"]
        heads[f"thigh.{side}"] = (hx, 0, hz)
        heads[f"shin.{side}"] = (hx, 0, kz)
        heads[f"foot.{side}"] = (hx, 0, az)
        heads[f"toe.{side}"] = (hx, -fl * 0.55, m["foot_height"] * 0.35)
        tails[f"toe.{side}"] = (hx, -fl * 0.8, m["foot_height"] * 0.3)
    heads["_tails"] = tails  # type: ignore[assignment]
    return heads


def quat_to_zxy(q: Q.Q) -> tuple[float, float, float]:
    """Euler angles (z, x, y) in degrees with R = Rz @ Rx @ Ry (BVH 'Zrotation Xrotation Yrotation')."""
    w, x, y, z = Q.norm(q)
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    ax = math.asin(max(-1.0, min(1.0, r[2][1])))
    ay = math.atan2(-r[2][0], r[2][2])
    az = math.atan2(-r[0][1], r[1][1])
    return math.degrees(az), math.degrees(ax), math.degrees(ay)


def write_bvh(clip: dict, path: Path, body: dict | None = None) -> Path:
    heads = rest_heads(body)
    tails = heads.pop("_tails")
    children: dict[str | None, list[str]] = {}
    for b in CANONICAL:
        children.setdefault(CANONICAL_PARENT[b], []).append(b)
    order: list[str] = []
    lines = ["HIERARCHY"]

    def emit(b: str, depth: int):
        ind = "\t" * depth
        parent = CANONICAL_PARENT[b]
        off = heads[b] if parent is None else tuple(heads[b][i] - heads[parent][i] for i in range(3))
        off = _yup(off)
        lines.append(f"{ind}{'ROOT' if parent is None else 'JOINT'} {b}")
        lines.append(f"{ind}{{")
        lines.append(f"{ind}\tOFFSET {off[0]:.6f} {off[1]:.6f} {off[2]:.6f}")
        if parent is None:
            lines.append(f"{ind}\tCHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation")
        else:
            lines.append(f"{ind}\tCHANNELS 3 Zrotation Xrotation Yrotation")
        order.append(b)
        kids = children.get(b, [])
        for k in kids:
            emit(k, depth + 1)
        if not kids:
            t = tails.get(b) or tuple(heads[b][i] + (0, 0, 0.05)[i] for i in range(3))
            end = _yup(tuple(t[i] - heads[b][i] for i in range(3)))
            lines.append(f"{ind}\tEnd Site")
            lines.append(f"{ind}\t{{")
            lines.append(f"{ind}\t\tOFFSET {end[0]:.6f} {end[1]:.6f} {end[2]:.6f}")
            lines.append(f"{ind}\t}}")
        lines.append(f"{ind}}}")

    emit("hips", 0)
    n = clip["frames"]
    lines += ["MOTION", f"Frames: {n}", f"Frame Time: {1.0 / clip['fps']:.7f}"]
    hip_h = heads["hips"][2]
    for f in range(n):
        vals = []
        for b in order:
            seq = clip["bones"].get(b)
            q = tuple(seq[min(f, len(seq) - 1)]) if seq else Q.IDENTITY
            qy = Q.mul(Q.mul(TO_YUP, q), Q.conj(TO_YUP))
            zr, xr, yr = quat_to_zxy(qy)
            if b == "hips":
                r = clip["root"][min(f, len(clip["root"]) - 1)] if clip.get("root") else [0, 0, 0]
                p = _yup((r[0], r[1], hip_h + r[2]))
                vals += [f"{p[0]:.6f}", f"{p[1]:.6f}", f"{p[2]:.6f}"]
            vals += [f"{zr:.5f}", f"{xr:.5f}", f"{yr:.5f}"]
        lines.append(" ".join(vals))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
