"""Final assembly with ffmpeg: frames + recap + grain/LUT finishing + graphics + captions -> MP4.

Outputs H.264 High profile, yuv420p, BT.709, AAC 48 kHz stereo, +faststart:
  <episode>_<preset>.mp4        with burned-in captions (libass)
  <episode>_<preset>_clean.mp4  without captions (graphics like the Part card stay)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from storyforge.config import ASSETS_DIR
from storyforge.models.constants import RECAP_SPLITS
from storyforge.util.ffmpeg import capabilities, ffmpeg
from storyforge.util.ffmpeg import duration as media_duration

CRF = {"proxy": 26, "draft": 21, "final": 17, "final_4k": 17}
X264_PRESET = {"proxy": "veryfast", "draft": "medium", "final": "slow", "final_4k": "slow"}


def _fonts_dir() -> str | None:
    d = ASSETS_DIR / "fonts"
    if d.is_dir() and any(d.glob("*.[ot]tf")):
        return str(d)
    return None


def _sub_filter(name: str) -> str:
    fd = _fonts_dir()
    f = f"subtitles={name}"
    if fd:
        f += f":fontsdir='{fd.replace(chr(92), '/').replace(':', chr(92) + ':')}'"
    return f


RECAP_TYPES = {"reveal": 5, "payoff": 4, "escalation": 3, "hook": 2, "turn": 2, "joke": 1}


def _settled_moment(shots: list[dict], start: float, end: float) -> float | None:
    """A readable instant inside [start, end]: prefer a character shot over an insert, the one
    covering most of the span, at 65 % of the overlap (camera moves such as whip pans have
    landed by then)."""
    best = None
    for s in shots:
        lo, hi = max(start, s["start"]), min(end, s["end"])
        if hi - lo < 0.25:
            continue
        score = (hi - lo) * (0.35 if s.get("type") == "insert" else 1.0)
        if best is None or score > best[0]:
            best = (score, lo + 0.65 * (hi - lo))
    return best[1] if best else None


def recap_moments(prev_timeline: dict | None, video_duration: float, prev_shots: dict | None = None) -> list[float]:
    """Pick the recap moments (seconds in the previous part's video), chronologically: two key
    beats (reveals/payoffs/escalations ranked by type and intensity, spread apart) and the
    cliffhanger last, so the montage leads straight into the new part's opening."""
    if not prev_timeline or not prev_timeline.get("beats"):
        return [video_duration * 0.35, video_duration * 0.7, max(0.0, video_duration - 2.4)]
    dur = float(prev_timeline.get("duration", video_duration))
    # the previous part may itself open with a recap lead-in: story time + offset = video time
    offset = max(0.0, video_duration - dur)
    beats = prev_timeline["beats"]
    shots = (prev_shots or {}).get("shots", [])

    def moment(b, default_offset):
        t = _settled_moment(shots, b["start"], b.get("end", b["start"] + 1.0)) if shots else None
        return t if t is not None else b["start"] + default_offset

    cliffs = [b for b in beats if b.get("beat_type") == "cliffhanger"]
    if cliffs:
        cliff = max(cliffs, key=lambda b: (float(b.get("intensity", 0)), -b["start"]))
        cliff_t = moment(cliff, 0.25)
    else:
        cliff_t = max(0.0, dur - 2.4)
    gap = dur * 0.15
    ranked = sorted((b for b in beats if b["start"] < cliff_t - gap and b.get("beat_type") in RECAP_TYPES),
                    key=lambda b: (RECAP_TYPES[b["beat_type"]] + float(b.get("intensity", 0)), -b["start"]),
                    reverse=True)
    picks: list[float] = []
    for b in ranked:
        t = moment(b, 0.3)
        if all(abs(t - q) >= gap for q in picks) and t < cliff_t - gap:
            picks.append(t)
        if len(picks) == 2:
            break
    fill = [dur * 0.35, dur * 0.7]
    while len(picks) < 2:
        picks.append(fill[len(picks)])
    out = sorted(picks) + [cliff_t]
    return [min(max(0.0, t + offset), max(0.0, video_duration - 0.5)) for t in out]


def make_recap_clip(recap: dict, out: Path, fps: int, size: tuple[int, int]) -> Path | None:
    """2-3 s 'previously' montage from the previous part's clean video: two key moments and the
    cliffhanger, each with a slow push-in and a desaturated, vignetted look."""
    from storyforge.util.io import read_json

    video = recap.get("video")
    if not video or not Path(video).is_file():
        return make_recap_card(recap, out, fps, size)
    total = media_duration(video)
    seconds = float(recap["seconds"])
    prev_dir = Path(recap["episode_dir"]) if recap.get("episode_dir") else None
    picks = recap_moments(read_json(prev_dir / "timeline.json", None) if prev_dir else None, total,
                          read_json(prev_dir / "shotlist.json", None) if prev_dir else None)
    parts = []
    w, h = size
    for i, (t, share) in enumerate(zip(picks, RECAP_SPLITS, strict=True)):
        seg = seconds * share
        n = max(1, round(seg * fps))
        p = out.parent / f"_recap_{i}.mp4"
        # CFR first, zoompan per frame (centered push-in), then explicit timestamps: zoompan's own
        # output timestamps do not survive a following fps filter (it multiplied the length ~500x)
        vf = (f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"zoompan=z='min(1+{0.1 / n:.5f}*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
              f"s={w}x{h}:fps={fps},setpts=N/({fps}*TB),eq=saturation=0.72:contrast=1.06,vignette=PI/4.2")
        ffmpeg(["-ss", f"{t:.3f}", "-i", video, "-frames:v", str(n), "-vf", vf, "-an", "-c:v", "libx264", "-crf", "16",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(fps), str(p)])
        parts.append(p)
    lst = out.parent / "_recap_list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    ffmpeg(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", out.name], cwd=out.parent)
    for p in parts:
        p.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    return out


def _check_duration(path: Path, expected: float, what: str, tol: float = 0.25) -> float:
    got = media_duration(path)
    if abs(got - expected) > tol:
        raise RuntimeError(f"{what} is {got:.2f}s, expected {expected:.2f}s (ffmpeg filter/timestamp problem)")
    return got


def make_recap_card(recap: dict, out: Path, fps: int, size: tuple[int, int]) -> Path:
    """Fallback when the previous part has not been rendered yet: a styled text card with the
    previous part's summary, same duration, so audio, captions and picture stay aligned."""
    from storyforge.captions.ass import PLAY_H, PLAY_W, ass_color

    w, h = size
    seconds = float(recap["seconds"])
    text = (recap.get("text") or "Previously...").replace("\n", " ")
    ass = out.parent / "_recap_card.ass"
    ass.write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {PLAY_W}", f"PlayResY: {PLAY_H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Card,Inter,62,{ass_color('#FFFFFF')},{ass_color('#FFFFFF')},{ass_color('#000000')},"
        f"{ass_color('#000000', 0x80)},-1,0,0,0,100,100,0,0,1,3,0,5,120,120,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,0:00:{seconds:05.2f},Card,,0,0,0,,{{\\fad(200,250)}}{text}",
    ]) + "\n", encoding="utf-8")
    ffmpeg(["-f", "lavfi", "-i", f"color=c=0x1B1B2F:s={w}x{h}:d={seconds:.3f}:r={fps}", "-vf",
            f"subtitles={ass.name},vignette=PI/4", "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-pix_fmt",
            "yuv420p", out.name], cwd=out.parent)
    ass.unlink(missing_ok=True)
    return out


def encode_episode(*, seq_dir: Path, fps: int, mix: Path, captions_dir: Path, out_captioned: Path, out_clean: Path,
                   grade: dict, preset: str, recap: dict | None, log=print) -> dict:
    caps = capabilities()
    if not caps["libx264"]:
        raise RuntimeError("ffmpeg has no libx264 encoder; install a full ffmpeg build")
    first = sorted(seq_dir.glob("*.png"))[0]
    from PIL import Image

    with Image.open(first) as im:
        size = im.size
    work = out_captioned.parent / "_work"
    work.mkdir(parents=True, exist_ok=True)
    # 1) graded story video (grain + optional LUT), lossless-ish intermediate
    vf = []
    vig = float(grade.get("vignette", 0.0) or 0.0)
    if vig > 0:
        # angle controls strength (PI/5 subtle .. PI/3 strong); mode=forward darkens the corners
        vf.append(f"vignette=angle={0.35 + vig * 1.6:.3f}:mode=forward")
    grain = float(grade.get("grain", 0.0) or 0.0)
    if grain > 0:
        vf.append(f"noise=alls={max(1, int(grain * 120))}:allf=t")
    lut = grade.get("lut")
    if lut and Path(lut).is_file():
        lut_path = str(Path(lut).resolve()).replace("\\", "/").replace(":", "\\:")
        vf.append(f"lut3d='{lut_path}'")
    vf.append("format=yuv420p")
    story = work / "story.mp4"
    ffmpeg(["-framerate", str(fps), "-i", str(seq_dir / "%06d.png"), "-vf", ",".join(vf), "-c:v", "libx264",
            "-crf", "12", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc",
            "bt709", "-colorspace", "bt709", str(story)])
    n_frames = len(list(seq_dir.glob("*.png")))
    _check_duration(story, n_frames / fps, "graded story video")
    video_in = story
    recap_dur = 0.0
    if recap:
        rc = make_recap_clip(recap, work / "recap.mp4", fps, size)
        if rc:
            recap_dur = _check_duration(rc, float(recap["seconds"]), "recap montage")
            joined = work / "joined.mp4"
            (work / "join.txt").write_text("file 'recap.mp4'\nfile 'story.mp4'\n", encoding="utf-8")
            ffmpeg(["-f", "concat", "-safe", "0", "-i", "join.txt", "-c", "copy", joined.name], cwd=work)
            video_in = joined
        else:
            log("recap requested but previous part video not found; skipping recap montage")
    # copy subtitle files next to the work dir so the filter can use plain relative names (Windows safe)
    for name in ("captions.ass", "graphics.ass"):
        src = captions_dir / name
        if src.is_file():
            shutil.copy2(src, work / name)
    # the mix already starts with the recap lead-in (see audio_mix), so audio and video stay aligned
    audio_args = ["-i", str(mix)]
    common_out = ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2"
                  if size[1] <= 1920 else "5.2", "-preset", X264_PRESET.get(preset, "medium"), "-crf",
                  str(CRF.get(preset, 20)), "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
                  "-colorspace", "bt709", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
                  "-movflags", "+faststart", "-shortest"]
    gfx = "graphics.ass" if (work / "graphics.ass").is_file() else None
    filters_clean = [_sub_filter(gfx)] if gfx and caps["libass"] else []
    filters_cap = list(filters_clean)
    if (work / "captions.ass").is_file() and caps["libass"]:
        filters_cap.append(_sub_filter("captions.ass"))
    for out, filters in ((out_clean, filters_clean), (out_captioned, filters_cap)):
        args = ["-i", os.path.relpath(video_in, work), *audio_args]
        if filters:
            args += ["-vf", ",".join(filters)]
        args += common_out + [str(out.resolve())]
        ffmpeg(args, cwd=work)
    srt = captions_dir / "captions.srt"
    if srt.is_file():
        shutil.copy2(srt, out_clean.with_suffix(".srt"))
    shutil.rmtree(work, ignore_errors=True)
    return {"captioned": str(out_captioned), "clean": str(out_clean), "duration": round(media_duration(out_captioned), 3),
            "size": list(size), "libass": caps["libass"], "recap_seconds": round(recap_dur, 3)}
