"""Burned-in captions (ASS/libass) with word-by-word highlight, SRT export, and the graphics
layer (Part N card, "previously" tag) that also appears in the clean version.

Layout is computed for a 1080x1920 PlayRes so styles scale to every render size. Captions live in
the caption safe area: centred horizontally inside 8 % side margins, baseline ~29 % above the
bottom edge (clear of platform UI at the bottom and of faces composed in the upper thirds).
"""

from __future__ import annotations

from dataclasses import dataclass

PLAY_W, PLAY_H = 1080, 1920
SAFE = {"left": 0.08, "right": 0.08, "top": 0.12, "bottom": 0.22}  # fractions of the frame

STYLE_PRESETS = {
    "bold_pop": {"font": "Inter", "size": 74, "bold": True, "primary": "#FFFFFF", "highlight": "#FFD447",
                 "outline": "#1B1B2F", "outline_w": 6, "shadow": 2, "back": "#000000", "pop": 112, "upper": False,
                 "max_words": 4, "margin_v": 560},
    "clean_minimal": {"font": "Inter", "size": 64, "bold": True, "primary": "#FFFFFF", "highlight": "#7FD3E8",
                      "outline": "#000000", "outline_w": 4, "shadow": 0, "back": "#000000", "pop": 104,
                      "upper": False, "max_words": 5, "margin_v": 540},
    "comic": {"font": "DejaVu Sans", "size": 76, "bold": True, "primary": "#FFFFFF", "highlight": "#FF6F91",
              "outline": "#000000", "outline_w": 7, "shadow": 3, "back": "#000000", "pop": 116, "upper": True,
              "max_words": 3, "margin_v": 560},
}


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def srt_ts(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@dataclass
class Chunk:
    start: float
    end: float
    words: list[dict]
    speaker: str | None


def chunk_words(words: list[dict], max_words: int, max_chars: int = 22, speaker: str | None = None) -> list[Chunk]:
    """Group timed words into short caption chunks, breaking at punctuation and pauses."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(x["word"] for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = (len(cur) >= max_words or len(text) >= max_chars or w["word"][-1:] in ".!?,;:" or
               (nxt is not None and nxt["start"] - w["end"] > 0.35))
        if brk or nxt is None:
            chunks.append(Chunk(cur[0]["start"], cur[-1]["end"], cur, speaker))
            cur = []
    return chunks


def measure_text_px(text: str, size: int, font: str = "Inter", bold: bool = True) -> float:
    """Approximate rendered width in PlayRes pixels (PIL when available, heuristic otherwise)."""
    try:
        from PIL import ImageFont

        for candidate in (f"{font}-Bold.ttf" if bold else f"{font}.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
            try:
                f = ImageFont.truetype(candidate, size)
                return float(f.getlength(text))
            except OSError:
                continue
    except ImportError:
        pass
    return len(text) * size * 0.56


def build_ass(timeline: dict, style_name: str = "bold_pop", offset: float = 0.0, names: dict | None = None,
              accent: str | None = None, scale: float = 1.0) -> tuple[str, list[dict]]:
    st = dict(STYLE_PRESETS.get(style_name, STYLE_PRESETS["bold_pop"]))
    st["size"] = int(round(st["size"] * scale))  # quality auto-fix: smaller font when lines leave the safe area
    if accent:
        st["highlight"] = accent
    lines_meta: list[dict] = []
    max_w = PLAY_W * (1 - SAFE["left"] - SAFE["right"])
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {PLAY_W}", f"PlayResY: {PLAY_H}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Caption,{st['font']},{st['size']},{ass_color(st['primary'])},{ass_color(st['highlight'])},"
        f"{ass_color(st['outline'])},{ass_color(st['back'], 0x80)},{-1 if st['bold'] else 0},0,0,0,100,100,0,0,1,"
        f"{st['outline_w']},{st['shadow']},2,{int(PLAY_W * SAFE['left'])},{int(PLAY_W * SAFE['right'])},{st['margin_v']},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = []
    for b in timeline["beats"]:
        if not b.get("words"):
            continue
        for ch in chunk_words(b["words"], st["max_words"], speaker=b.get("speaker")):
            words = [w["word"].upper() if st["upper"] else w["word"] for w in ch.words]
            size = st["size"]
            width = measure_text_px(" ".join(words), int(size * st["pop"] / 100), st["font"])
            while width > max_w and size > 40:
                size -= 4
                width = measure_text_px(" ".join(words), int(size * st["pop"] / 100), st["font"])
            lines_meta.append({"start": ch.start + offset, "end": ch.end + offset, "text": " ".join(words),
                               "width_px": round(width, 1), "size": size, "margin_v": st["margin_v"],
                               "play_w": PLAY_W, "play_h": PLAY_H})
            for i, w in enumerate(ch.words):
                s = w["start"] + offset
                e = (ch.words[i + 1]["start"] if i + 1 < len(ch.words) else max(ch.end, w["end"] + 0.15)) + offset
                parts = []
                for j, ww in enumerate(words):
                    if j == i:
                        parts.append(f"{{\\c{ass_color(st['highlight'])}\\fscx{st['pop']}\\fscy{st['pop']}}}{ww}"
                                     f"{{\\c{ass_color(st['primary'])}\\fscx100\\fscy100}}")
                    else:
                        parts.append(ww)
                fs = f"{{\\fs{size}}}" if size != st["size"] else ""
                events.append(f"Dialogue: 0,{ts(s)},{ts(e)},Caption,,0,0,0,,{fs}{' '.join(parts)}")
    return "\n".join(header + events) + "\n", lines_meta


def build_srt(timeline: dict, offset: float = 0.0, max_words: int = 7) -> str:
    out, n = [], 1
    for b in timeline["beats"]:
        if not b.get("words"):
            continue
        for ch in chunk_words(b["words"], max_words, max_chars=42):
            out.append(f"{n}\n{srt_ts(ch.start + offset)} --> {srt_ts(ch.end + offset + 0.1)}\n"
                       f"{' '.join(w['word'] for w in ch.words)}\n")
            n += 1
    return "\n".join(out)


def build_graphics_ass(part: int | None, part_card: dict, recap: tuple[float, float] | None,
                       story_start: float, accent: str = "#FFD447") -> str:
    """Part N badge (top, inside the safe area) + 'Previously...' tag over the recap."""
    color = part_card.get("color", accent)
    text_color = part_card.get("text_color", "#1B1B2F")
    seconds = float(part_card.get("seconds", 2.0))
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {PLAY_W}", f"PlayResY: {PLAY_H}",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Badge,Inter,58,{ass_color(text_color)},{ass_color(text_color)},{ass_color(color)},{ass_color(color)},"
        f"-1,0,0,0,100,100,6,0,3,22,0,8,0,0,{int(PLAY_H * SAFE['top'])},1",
        f"Style: Tag,Inter,48,{ass_color('#FFFFFF')},{ass_color('#FFFFFF')},{ass_color('#000000', 0x40)},"
        f"{ass_color('#000000', 0x60)},-1,1,0,0,100,100,10,0,1,3,2,8,0,0,{int(PLAY_H * SAFE['top'])},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    ev = []
    if recap:
        a, b = recap
        ev.append(f"Dialogue: 1,{ts(a)},{ts(b)},Tag,,0,0,0,,{{\\fad(120,160)}}PREVIOUSLY...")
    if part:
        txt = part_card.get("text", "PART {n}").replace("{n}", str(part))
        s = story_start + 0.15
        ev.append(f"Dialogue: 2,{ts(s)},{ts(s + seconds)},Badge,,0,0,0,,"
                  f"{{\\fad(150,250)\\t(0,180,\\fscx112\\fscy112)\\t(180,320,\\fscx100\\fscy100)}} {txt} ")
    return "\n".join(header + ev) + "\n"
