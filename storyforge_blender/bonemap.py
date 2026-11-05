"""Automatic bone mapping from common rig conventions onto StoryForge canonical bones
(pure Python, shared by the backend and Blender).

Recognised: StoryForge canonical, Mixamo (mixamorig:*), CMU/BVH (Hips, LeftUpLeg, ...), Unreal
mannequin (pelvis, upperarm_l, ...), Rigify (DEF-*), VRM/VRoid (J_Bip_*), Daz/Genesis-ish and
generic "left arm"-style names. Users can override any entry with an explicit `bone_map`.
"""

from __future__ import annotations

import re

CANONICAL = ["hips", "spine", "chest", "neck", "head", "shoulder.L", "upper_arm.L", "forearm.L", "hand.L",
             "shoulder.R", "upper_arm.R", "forearm.R", "hand.R", "thigh.L", "shin.L", "foot.L", "toe.L",
             "thigh.R", "shin.R", "foot.R", "toe.R"]

CANONICAL_PARENT = {"hips": None, "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
                    "shoulder.L": "chest", "upper_arm.L": "shoulder.L", "forearm.L": "upper_arm.L",
                    "hand.L": "forearm.L", "shoulder.R": "chest", "upper_arm.R": "shoulder.R",
                    "forearm.R": "upper_arm.R", "hand.R": "forearm.R", "thigh.L": "hips", "shin.L": "thigh.L",
                    "foot.L": "shin.L", "toe.L": "foot.L", "thigh.R": "hips", "shin.R": "thigh.R",
                    "foot.R": "shin.R", "toe.R": "foot.R"}

# canonical rest (T-pose) bone directions in armature space (+X = left, -Y = forward, +Z = up)
REST_DIR = {"hips": (0, 0, 1), "spine": (0, 0, 1), "chest": (0, 0, 1), "neck": (0, 0, 1), "head": (0, 0, 1),
            "shoulder.L": (1, 0, 0), "upper_arm.L": (1, 0, 0), "forearm.L": (1, 0, 0), "hand.L": (1, 0, 0),
            "shoulder.R": (-1, 0, 0), "upper_arm.R": (-1, 0, 0), "forearm.R": (-1, 0, 0), "hand.R": (-1, 0, 0),
            "thigh.L": (0, 0, -1), "shin.L": (0, 0, -1), "foot.L": (0, -0.93, -0.37), "toe.L": (0, -1, -0.05),
            "thigh.R": (0, 0, -1), "shin.R": (0, 0, -1), "foot.R": (0, -0.93, -0.37), "toe.R": (0, -1, -0.05)}

# (canonical, side-free synonyms in priority order); side handled separately
SYNONYMS = {
    "hips": ["hips", "pelvis", "hip", "root_hips", "cbiphips", "jbipchips", "bip01pelvis"],
    "spine": ["spine", "spine01", "lowerback", "spine1_lower", "jbipcspine", "abdomen", "abdomenlower", "spine_01"],
    "chest": ["spine2", "chest", "spine03", "spine02", "upperchest", "spine1", "jbipcchest", "jbipcupperchest",
              "chestupper", "spine_03", "spine_02", "spine004", "spine003"],
    "neck": ["neck", "neck01", "neck1", "jbipcneck", "necklower"],
    "head": ["head", "jbipchead"],
    "shoulder": ["shoulder", "clavicle", "collar", "jbipshoulder"],
    "upper_arm": ["arm", "upperarm", "uparm", "humerus", "jbipupperarm", "shldr", "upper_arm"],
    "forearm": ["forearm", "lowerarm", "elbow", "jbiplowerarm", "fore_arm"],
    "hand": ["hand", "wrist", "jbiphand"],
    "thigh": ["upleg", "thigh", "upperleg", "jbipupperleg", "hip_l", "femur"],
    "shin": ["leg", "shin", "calf", "lowerleg", "knee", "jbiplowerleg", "shank"],
    "foot": ["foot", "ankle", "jbipfoot"],
    "toe": ["toebase", "toe", "ball", "toes", "jbiptoebase", "toe_base"],
}
SIDE_PATTERNS = {
    "L": [r"^left", r"left$", r"^l_", r"_l$", r"\.l$", r"^l(?=[A-Z])", r"_l_", r"^lft", r"jbipl", r"^l\.",
          r"(?<=[a-z])l$"],
    "R": [r"^right", r"right$", r"^r_", r"_r$", r"\.r$", r"^r(?=[A-Z])", r"_r_", r"^rgt", r"jbipr", r"^r\.",
          r"(?<=[a-z])r$"],
}
PREFIX = re.compile(r"^(mixamorig\d*:|def-|org-|mch-|bip0?1[_ ]?|cc_base_|rig[:_]|armature[:_|]|j_bip_)", re.I)


def normalize(name: str) -> tuple[str, str | None]:
    raw = name.split("|")[-1].split(":")[-1] if ":" in name or "|" in name else name
    raw = PREFIX.sub("", raw)
    lower = raw.lower()
    side = None
    for s, pats in SIDE_PATTERNS.items():
        for p in pats:
            if re.search(p, raw) or re.search(p, lower):
                side = s
                break
        if side:
            break
    if "left" in lower:
        side = "L"
    elif "right" in lower:
        side = "R"
    elif re.search(r"jbipl|^l_|_l$|\.l$|^l\.", lower):
        side = "L"
    elif re.search(r"jbipr|^r_|_r$|\.r$|^r\.", lower):
        side = "R"
    core = re.sub(r"left|right", "", lower)
    core = re.sub(r"(^l_|_l$|\.l$|^r_|_r$|\.r$|^l\.|^r\.)", "", core)
    core = re.sub(r"[^a-z0-9]", "", core)
    core = core.replace("jbipl", "jbip").replace("jbipr", "jbip").replace("jbipc", "jbipc")
    return core, side


VRM_MAP = {"hips": "C_Hips", "spine": "C_Spine", "chest": "C_UpperChest", "neck": "C_Neck", "head": "C_Head",
           "shoulder.L": "L_Shoulder", "upper_arm.L": "L_UpperArm", "forearm.L": "L_LowerArm", "hand.L": "L_Hand",
           "thigh.L": "L_UpperLeg", "shin.L": "L_LowerLeg", "foot.L": "L_Foot", "toe.L": "L_ToeBase"}


def _special(names: list[str]) -> dict[str, str] | None:
    lower = {n.lower(): n for n in names}
    # Rigify deform chain: DEF-spine (pelvis) .001 spine .002/.003 chest .004/.005 neck .006 head
    if "def-spine" in lower and "def-upper_arm.l" in lower:
        m = {"hips": lower["def-spine"]}
        for canon, cands in (("spine", ["def-spine.001"]), ("chest", ["def-spine.003", "def-spine.002"]),
                             ("neck", ["def-spine.004"]), ("head", ["def-spine.006", "def-spine.005"])):
            for c in cands:
                if c in lower:
                    m[canon] = lower[c]
                    break
        for side in ("L", "R"):
            for canon in ("shoulder", "upper_arm", "forearm", "hand", "thigh", "shin", "foot", "toe"):
                key = f"def-{canon}.{side.lower()}"
                if key in lower:
                    m[f"{canon}.{side}"] = lower[key]
        return m
    # VRM / VRoid: J_Bip_C_Hips, J_Bip_L_UpperArm ...
    if any(n.lower().startswith("j_bip_") for n in names):
        m = {}
        by_suffix = {n.lower().replace("j_bip_", ""): n for n in names}
        for canon, suf in VRM_MAP.items():
            if suf.lower() in by_suffix:
                m[canon] = by_suffix[suf.lower()]
            if canon.endswith(".L"):
                rs = "r_" + suf[2:].lower()
                if rs in by_suffix:
                    m[canon[:-2] + ".R"] = by_suffix[rs]
        if "chest" not in m and "c_chest" in by_suffix:
            m["chest"] = by_suffix["c_chest"]
        return m
    return None


def auto_map(bone_names: list[str]) -> dict[str, str]:
    """Return {canonical: source_bone} for every canonical bone that could be matched."""
    names = list(bone_names)
    if all(c in names for c in ("hips", "upper_arm.L", "thigh.L")):  # already canonical
        return {c: c for c in CANONICAL if c in names}
    special = _special(names)
    if special:
        return special
    info = {n: normalize(n) for n in names}
    out: dict[str, str] = {}
    used: set[str] = set()
    for canon in CANONICAL:
        base, side = (canon.split(".") + [None])[:2]
        syns = SYNONYMS[base] if base in SYNONYMS else SYNONYMS.get(canon, [])
        best, best_rank = None, 10 ** 9
        for n in names:
            if n in used:
                continue
            core, s = info[n]
            if side and s != side:
                continue
            if not side and s is not None and base not in ("hips", "spine", "chest", "neck", "head"):
                continue
            for rank, syn in enumerate(syns):
                syn_n = re.sub(r"[^a-z0-9]", "", syn.lower())
                if side and syn_n.endswith("l") and syn_n[:-1] in core:
                    pass
                if core == syn_n or core == f"jbip{syn_n}":
                    r = rank
                elif base == "chest" and core.startswith("spine") and core[5:].isdigit():
                    r = 50 - int(core[5:])  # prefer the highest spine index for chest
                else:
                    continue
                if side is None and s is not None:
                    continue
                if r < best_rank:
                    best, best_rank = n, r
        if best:
            out[canon] = best
            used.add(best)
    # spine/chest disambiguation: if chest grabbed "spine1" but "spine2" exists, keep the highest index
    if "spine" in out and "chest" in out and out["spine"] == out["chest"]:
        del out["chest"]
    return out


def missing_required(mapping: dict[str, str]) -> list[str]:
    required = ["hips", "spine", "head", "upper_arm.L", "forearm.L", "upper_arm.R", "forearm.R", "thigh.L", "shin.L",
                "thigh.R", "shin.R"]
    return [r for r in required if r not in mapping]
