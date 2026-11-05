"""Per-series colour grade presets.

A series picks one preset in its bible (`look.grade.preset`) and may override any field; the same
grade is applied to every shot and every part so the series keeps one consistent look. Fields:
exposure (stops), contrast (1 = neutral), saturation, warmth (+ warm / - cool), shadows_tint and
highlights_tint (lift/gain colour), vignette (0..1), grain (0..1, temporal, in the finishing pass),
lut (optional .cube file applied after the grade).
"""

from __future__ import annotations

from pathlib import Path

GRADE_PRESETS: dict[str, dict] = {
    "warm_storybook": {"exposure": 0.0, "contrast": 1.06, "saturation": 1.08, "warmth": 0.03,
                       "shadows_tint": "#2B2D5A", "highlights_tint": "#FFE7C2", "vignette": 0.22, "grain": 0.035},
    "cool_mystery": {"exposure": -0.1, "contrast": 1.1, "saturation": 0.95, "warmth": -0.06,
                     "shadows_tint": "#1E3A5F", "highlights_tint": "#E8F1FF", "vignette": 0.3, "grain": 0.045},
    "vibrant_cartoon": {"exposure": 0.05, "contrast": 1.04, "saturation": 1.18, "warmth": 0.0,
                        "shadows_tint": "#3A2E6B", "highlights_tint": "#FFFFFF", "vignette": 0.12, "grain": 0.0},
    "golden_hour": {"exposure": 0.05, "contrast": 1.08, "saturation": 1.1, "warmth": 0.1,
                    "shadows_tint": "#3B2A55", "highlights_tint": "#FFD9A0", "vignette": 0.25, "grain": 0.03},
    "moonlit": {"exposure": -0.15, "contrast": 1.12, "saturation": 0.9, "warmth": -0.1,
                "shadows_tint": "#14284A", "highlights_tint": "#D6E6FF", "vignette": 0.32, "grain": 0.05},
    "neutral_clean": {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0, "warmth": 0.0,
                      "shadows_tint": "#808080", "highlights_tint": "#FFFFFF", "vignette": 0.1, "grain": 0.0},
}


def resolve_grade(grade: dict | None) -> dict:
    grade = dict(grade or {})
    preset = grade.get("preset") or "warm_storybook"
    base = dict(GRADE_PRESETS.get(preset, GRADE_PRESETS["warm_storybook"]))
    base.update({k: v for k, v in grade.items() if v is not None})
    base["preset"] = preset
    lut = base.get("lut")
    if lut and not Path(lut).is_absolute():
        # bible values are file names relative to assets/luts (LUT files are never committed)
        from storyforge.config import ASSETS_DIR

        base["lut"] = str(ASSETS_DIR / "luts" / lut)
    return base
