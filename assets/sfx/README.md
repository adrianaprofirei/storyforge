# Sound-effects library

Drop your own sound effects here (`.wav`, `.flac`, `.ogg`, `.mp3`, `.aiff`), in any folder
structure. They are git-ignored: only this README and `license_manifest.yaml` are committed.

How sounds are chosen: every automatic cue asks for a tag such as `footstep+wood`, `whoosh`,
`impact_soft`, `paper_slam`, `clink`, `key_jingle`, `clock_chime`, `boing` or `twinkle`
(`+` means "all of these tags"). Your files win over the built-in ones whenever their tags
match, and several matching files are rotated deterministically so repeated footsteps don't
sound identical. Tags come from `license_manifest.yaml`, or are guessed from folder and file
names (`foley/footsteps/wood_step_03.wav` -> `foley`, `footsteps`, `wood`, `step`).

Writers can also request a sound on a beat with `"sfx": ["clock_chime"]` in the screenplay.

The built-in library (63 sounds) is synthesized by `storyforge.audio.synth` into
`data/library/sfx/` on first use; it is CC0. Run `storyforge assets` to regenerate it.

Good CC0 / permissive sources (download yourself, record the license in the manifest):
Freesound (filter by CC0), Sonniss GDC bundles (royalty-free), Kenney audio packs (CC0).
