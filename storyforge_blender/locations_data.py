"""Location presets (pure Python, shared by backend staging and the Blender set builder).

Coordinates: metres, characters face -Y toward the audience side, floor at z=0.
`formations[n]` = (x, y, yaw_deg) for n characters, yaw 0 = facing the audience (-Y),
+90 = facing +X (screen right). Formations "cheat" toward camera like stage blocking.
`key_dir` is the motivated main light direction (azimuth deg around the subject, 0 = from the
audience side, +90 = from +X) used by the three-point generator. Sets are built from these
descriptions in storyforge_blender/location.py.
"""

from __future__ import annotations

LOCATIONS: dict[str, dict] = {
    "library": {
        "name": "School library",
        "kind": "interior",
        "surface": "wood",
        "room": "medium_room",
        "extras": False,
        "bounds": [-4.0, 4.0, -3.5, 3.2],
        "wall_height": 3.6,
        "formations": {
            1: [(0.0, 0.25, 0)],
            2: [(-0.55, 0.25, 55), (0.55, 0.25, -55)],
            3: [(-0.82, 0.18, 62), (0.0, 0.98, 0), (0.82, 0.18, -62)],
            4: [(-1.0, 0.2, 60), (-0.35, 0.98, 10), (0.35, 0.98, -10), (1.0, 0.2, -60)],
        },
        "marks": {"center": (0.0, 0.3), "door": (-3.2, 0.6), "window": (2.2, 2.2), "back": (0.0, 1.8),
                  "left": (-1.0, 0.2), "right": (1.0, 0.2), "table": (0.0, 0.55), "offscreen_left": (-4.5, 0.4),
                  "offscreen_right": (4.5, 0.4)},
        "surfaces": {"table_top": (0.0, 0.52, 0.5)},
        "key_dir": -40.0,          # warm interior key from front-left; the sunlit window is the rim (back-right)
        "window": {"x": 0.35, "z0": 1.0, "w": 1.25, "h": 1.55},
        "sun_dir": 168.0,          # afternoon sun streams in through the window behind the group
        "palette": {"wall": "#B49D7A", "trim": "#5E3B22", "floor": "#6E4A33", "accent": "#2F6B4F"},
        "dressing": ["bookshelves", "reading_table", "lamps", "arched_window", "posters", "rug", "chairs"],
    },
    "clock_tower": {
        "name": "Inside the clock tower",
        "kind": "interior",
        "surface": "wood",
        "room": "large_hall",
        "extras": False,
        "bounds": [-4.5, 4.5, -3.5, 3.6],
        "wall_height": 6.0,
        "formations": {
            1: [(0.0, 0.2, 0)],
            2: [(-0.55, 0.2, 52), (0.55, 0.2, -52)],
            3: [(-0.78, 0.05, 55), (0.04, 0.55, 4), (0.8, 0.08, -55)],
            4: [(-1.0, 0.1, 55), (-0.33, 0.6, 10), (0.33, 0.6, -10), (1.0, 0.1, -55)],
        },
        "marks": {"center": (0.0, 0.3), "stairs": (-2.6, 1.2), "clock": (0.0, 2.6), "back": (0.0, 1.9),
                  "left": (-1.1, 0.2), "right": (1.1, 0.2), "gap": (0.6, 2.4), "start": (-0.2, -1.6),
                  "offscreen_left": (-4.8, 0.6), "offscreen_right": (4.8, 0.6)},
        "surfaces": {"floor": (0.0, 0.3, 0.0)},
        "key_dir": -50.0,          # warm lantern key front-left; moonlight through the clock face is the rim
        "sun_dir": 180.0,          # moonlight comes through the clock face
        "palette": {"wall": "#3E3A4A", "trim": "#5A3E2B", "floor": "#6B4B33", "accent": "#C8A04A"},
        "dressing": ["clock_face", "gears", "beams", "stairs", "dust"],
    },
    "hallway": {
        "name": "School hallway",
        "kind": "interior",
        "surface": "tile",
        "room": "hallway",
        "extras": True,
        "bounds": [-6.0, 6.0, -2.5, 2.2],
        "wall_height": 3.2,
        "formations": {
            1: [(0.0, 0.2, 0)],
            2: [(-0.55, 0.2, 55), (0.55, 0.2, -55)],
            3: [(-0.8, 0.15, 60), (0.0, 0.7, 0), (0.8, 0.15, -60)],
            4: [(-1.0, 0.2, 60), (-0.35, 0.75, 10), (0.35, 0.75, -10), (1.0, 0.2, -60)],
        },
        "marks": {"center": (0.0, 0.2), "left": (-1.2, 0.2), "right": (1.2, 0.2), "back": (0.0, 1.5),
                  "offscreen_left": (-6.5, 0.4), "offscreen_right": (6.5, 0.4)},
        "surfaces": {},
        "key_dir": 20.0,
        "palette": {"wall": "#D9E4EC", "trim": "#2C5D8A", "floor": "#C7C2B8", "accent": "#E8B33C"},
        "dressing": ["lockers", "notice_boards", "ceiling_lights", "windows"],
        "extras_lane": [1.15, 1.7], "extras_x": [-5.5, 5.5],
    },
    "street": {
        "name": "Town square",
        "kind": "exterior",
        "surface": "concrete",
        "room": "outdoors",
        "extras": True,
        "bounds": [-8.0, 8.0, -4.0, 8.0],
        "wall_height": 0.0,
        "formations": {
            1: [(0.0, 0.2, 0)],
            2: [(-0.55, 0.2, 55), (0.55, 0.2, -55)],
            3: [(-0.8, 0.15, 60), (0.0, 0.7, 0), (0.8, 0.15, -60)],
            4: [(-1.0, 0.2, 60), (-0.35, 0.75, 10), (0.35, 0.75, -10), (1.0, 0.2, -60)],
        },
        "marks": {"center": (0.0, 0.2), "left": (-1.2, 0.2), "right": (1.2, 0.2), "back": (0.0, 2.0),
                  "fountain": (2.5, 3.0), "offscreen_left": (-8.5, 0.4), "offscreen_right": (8.5, 0.4)},
        "surfaces": {},
        "key_dir": 40.0,
        "palette": {"wall": "#E7C9A9", "trim": "#7A4E3A", "floor": "#9C9488", "accent": "#5FA8D3"},
        "dressing": ["shopfronts", "fountain", "lamps", "tower_far", "trees"],
        "extras_lane": [2.4, 4.0], "extras_x": [-7.5, 7.5],
    },
}

ALIASES = {"classroom": "library", "school_library": "library", "tower": "clock_tower", "corridor": "hallway",
           "town_square": "street", "town": "street"}


def get_location(preset: str) -> dict:
    key = ALIASES.get(preset, preset)
    return LOCATIONS.get(key, LOCATIONS["library"]) | {"preset": key if key in LOCATIONS else "library"}
