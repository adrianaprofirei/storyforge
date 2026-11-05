"""Pose math shared by clips, retargeting and procedural layers.

Canonical clip convention: for every bone a quaternion L expressed in the *rest-pose armature
axes* and relative to the parent ("local delta in armature axes"). With R = bone rest orientation
(bone.matrix_local), the bone's local pose rotation is  basis = R^-1 @ L @ R. Because L does not
depend on bone roll or local axis conventions, the same clip drives any rig whose rest pose is a
T-pose with the same bone semantics (and retargeting only has to produce L)."""

from __future__ import annotations

import math

from mathutils import Euler, Quaternion

AX = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}


def q(axis: str, deg: float) -> Quaternion:
    return Quaternion(AX[axis], math.radians(deg))


def qe(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Quaternion:
    """Rotation from XYZ euler degrees (armature axes)."""
    return Euler((math.radians(x), math.radians(y), math.radians(z)), "XYZ").to_quaternion()


def to_local(pose_bone, l_arm: Quaternion) -> Quaternion:
    rest = pose_bone.bone.matrix_local.to_quaternion()
    return rest.inverted() @ l_arm @ rest


def from_local(pose_bone, basis: Quaternion) -> Quaternion:
    rest = pose_bone.bone.matrix_local.to_quaternion()
    return rest @ basis @ rest.inverted()


def mirror_bone(name: str) -> str:
    if name.endswith(".L"):
        return name[:-2] + ".R"
    if name.endswith(".R"):
        return name[:-2] + ".L"
    return name


def mirror_q(qt: Quaternion) -> Quaternion:
    """Mirror an armature-space rotation across the YZ plane (left <-> right)."""
    return Quaternion((qt.w, qt.x, -qt.y, -qt.z))
