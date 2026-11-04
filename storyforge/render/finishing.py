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


def make_recap_clip(recap: dict, out: Path, fps: int, size: tuple[int, int]) -> Path | None:
    """2-3 s 'previously' montage: the previous part's cliffhanger first (it doubles as the hook),
    then two earlier key moments, with a slight push and a desaturated, vignetted look."""
    video = recap.get("video")
    if not video or not Path(video).is_file():
        return None
    total = media_duration(video)
    seconds = float(recap["seconds"])
    # pick moments: the cliffhanger (end), ~35 %, ~70 % of the previous part
    picks = [max(0.0, total - 2.4), total * 0.35, total * 0.7]
    seg = seconds / len(picks)
    parts = []
    w, h = size
    for i, t in enumerate(picks):
        p = out.parent / f"_recap_{i}.mp4"
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"zoompan=z='min(zoom+0.0025,1.12)':d=1:s={w}x{h}:fps={fps},eq=saturation=0.72:contrast=1.06,"
              f"vignette=PI/4.2,fps={fps}")
        ffmpeg(["-ss", f"{t:.3f}", "-t", f"{seg:.3f}", "-i", video, "-vf", vf, "-an", "-c:v", "libx264", "-crf", "16",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", str(p)])
        parts.append(p)
    lst = out.parent / "_recap_list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    ffmpeg(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", out.name], cwd=out.parent)
    for p in parts:
        p.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
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
    video_in = story
    recap_dur = 0.0
    if recap:
        rc = make_recap_clip(recap, work / "recap.mp4", fps, size)
        if rc:
            recap_dur = media_duration(rc)
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
                  "-colorspace", "bt709", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
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
