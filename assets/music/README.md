# Music library

Drop music beds and stings here (`.wav`, `.flac`, `.ogg`, `.mp3`). They are git-ignored:
only this README and `license_manifest.yaml` are committed.

Each episode has a `music_mood` (from the screenplay; one of `playful`, `mysterious`, `tense`,
`sad`, `triumphant`, `calm`, `comedic`, `spooky`). The mixer picks a bed whose `moods` include
it (your tracks first), loops it seamlessly if it is shorter than the episode, fades it in and
out, ducks it under dialogue with a look-ahead sidechain envelope, pulls it out right before a
cliffhanger sting and swells it under a finale payoff.

Without user tracks, StoryForge synthesizes eight CC0 beds (one per mood, 16 bars, loopable) into
`data/library/music/` on first use. Run `storyforge assets` to regenerate them.
