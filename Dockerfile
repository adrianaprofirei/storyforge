# Optional CPU-only container (the primary target is a Windows/Linux PC with Blender + GPU).
#
#   docker build -t storyforge .
#   docker run --rm -p 8000:8000 -v "$PWD/data:/app/data" --env-file .env storyforge
#
# Renders use Cycles/EEVEE on the CPU inside the container, so finals are slow; drafts and the
# whole story/audio pipeline are fine. GPU rendering in Docker is possible with the NVIDIA container
# toolkit, but running Blender natively is simpler and faster.
FROM python:3.12-slim-bookworm

ARG BLENDER_SERIES=4.2
ARG BLENDER_VERSION=4.2.3

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg espeak-ng xz-utils curl ca-certificates \
        libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libice6 libgl1 libegl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        -o /tmp/blender.tar.xz \
    && mkdir -p /opt/blender && tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && rm /tmp/blender.tar.xz

WORKDIR /app
COPY pyproject.toml README.md ./
COPY storyforge ./storyforge
COPY storyforge_blender ./storyforge_blender
COPY assets ./assets
COPY web/dist ./web/dist
COPY scripts ./scripts
RUN pip install --no-cache-dir -e ".[piper]"

ENV BLENDER_PATH=/opt/blender/blender \
    STORYFORGE_HOST=0.0.0.0 \
    STORYFORGE_PORT=8000 \
    RENDER_DEVICE=CPU \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["storyforge", "serve"]
