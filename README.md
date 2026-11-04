# StoryForge

StoryForge turns a story idea into vertical (9:16) animated shorts rendered in Blender:
series bible -> arc plan -> screenplay -> script review -> voices -> lip-sync -> timeline ->
shot list -> Blender scene build -> render -> audio mix -> captions -> final MP4.

> Work in progress: this README is completed in milestone M8 (setup, architecture, every stage,
> design decisions, licensing, limitations).

## Quick start (demo mode, no API keys)

```bash
python -m venv .venv && .venv/bin/pip install -e .[piper]
cp .env.example .env            # set BLENDER_PATH (or BLENDER_PYTHON for a bpy-module Python)
storyforge doctor
storyforge demo --preset draft  # renders the bundled 2-part sample arc
```
