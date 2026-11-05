"""Shared vocabularies. These are the contract between the LLM, the pipeline and Blender."""

from __future__ import annotations

# The nine base expressions of the face system (shape keys / face textures).
BASE_EXPRESSIONS = ["neutral", "happy", "sad", "angry", "shocked", "smug", "scared", "confused", "embarrassed"]

# Emotions accepted in screenplays. Derived emotions are blends of base expressions.
DERIVED_EMOTIONS = {
    "excited": {"happy": 0.8, "shocked": 0.35},
    "tired": {"sad": 0.35, "smug": 0.15},
    "determined": {"angry": 0.35, "smug": 0.3},
    "relieved": {"happy": 0.55, "sad": 0.1},
    "suspicious": {"smug": 0.5, "confused": 0.3},
}
EMOTIONS = BASE_EXPRESSIONS + list(DERIVED_EMOTIONS)

TIMES_OF_DAY = ["morning", "day", "afternoon", "sunset", "evening", "night"]

BEAT_TYPES = ["hook", "recap", "setup", "escalation", "turn", "joke", "reveal", "payoff", "cliffhanger", "resolution"]

# Built-in gesture/motion clip names (procedural library; mocap clips can override by tag).
GESTURES = [
    "talk", "wave", "point", "shrug", "nod", "head_shake", "hands_on_hips", "cross_arms",
    "facepalm", "cheer", "jump", "gasp", "laugh", "cry", "think", "look_around", "thumbs_up",
    "scratch_head", "lean_in", "recoil", "clap", "shiver", "bow", "pick_up", "give", "peek",
]

LOCOMOTION = ["enter", "exit", "walk_to", "run_to", "turn_to", "sit", "stand", "tiptoe_to"]

PROPS = [
    "phone", "backpack", "sandwich", "book", "map", "flashlight", "key", "cup", "ball",
    "notebook", "magnifying_glass", "apple", "umbrella", "camera", "gear", "letter", "cookie", "gadget",
]
PROP_ACTIONS = ["hold", "pick_up", "put_down", "use", "give", "show", "drop"]
# continuity: where an object ends up after an episode
OBJECT_STATUSES = ["has", "lost", "broken", "hidden", "given_away", "destroyed", "found", "returned",
                   "stored"]

EMOTION_FX = [
    "sweat_drop", "tears", "anger_mark", "blush", "sparkles", "question_mark", "shock_lines",
    "exclamation_mark", "lightbulb",
]

SHOT_TYPES = [
    "establishing_wide", "wide", "medium_wide", "medium", "medium_close", "close_up",
    "extreme_close_up", "over_the_shoulder", "two_shot", "insert",
]
CAMERA_MOVES = ["static", "push_in", "pull_out", "dolly", "truck", "handheld", "whip_pan", "snap_zoom",
                "pan", "crane_up", "orbit"]

VOLUMES = ["whisper", "soft", "normal", "loud", "shout"]
PACES = ["slow", "normal", "fast"]

MUSIC_MOODS = ["playful", "mysterious", "tense", "sad", "triumphant", "calm", "comedic", "spooky"]

STYLE_PRESETS = ["stylized_3d", "cartoon"]

SURFACES = ["wood", "tile", "carpet", "grass", "concrete", "gravel", "metal"]
ROOM_TYPES = ["small_room", "medium_room", "hallway", "large_hall", "outdoors"]

# recap montage for parts 2+: share of the recap per moment (two key moments, then the cliffhanger);
# picture cuts (render/finishing.py) and the recap whooshes (audio_mix) both use it
RECAP_SPLITS = (0.3, 0.3, 0.4)
