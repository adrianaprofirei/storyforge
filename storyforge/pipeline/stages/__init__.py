"""Episode stages, in execution order."""

from storyforge.pipeline.stages.audio_stage import AudioMixStage
from storyforge.pipeline.stages.blender_stages import BuildStage, RenderStage, SceneSpecStage
from storyforge.pipeline.stages.deliver import CaptionsStage, DeliverablesStage, MuxStage, QualityStage
from storyforge.pipeline.stages.story_stages import ReviewStage, ScreenplayStage
from storyforge.pipeline.stages.timeline_stage import ShotsStage, TimelineStage
from storyforge.pipeline.stages.voice_stages import LipSyncStage, VoicesStage

ALL_STAGES = [
    ScreenplayStage,
    ReviewStage,
    VoicesStage,
    LipSyncStage,
    TimelineStage,
    ShotsStage,
    AudioMixStage,
    SceneSpecStage,
    BuildStage,
    RenderStage,
    CaptionsStage,
    MuxStage,
    QualityStage,
    DeliverablesStage,
]

STAGE_NAMES = [s.name for s in ALL_STAGES]
