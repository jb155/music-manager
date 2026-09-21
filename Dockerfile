FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8085 \
    HOME=/config \
    XDG_CONFIG_HOME=/config \
    XDG_CACHE_HOME=/config/.cache

# Install system dependencies & ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libchromaprint-tools \
    git \
    curl \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Defensively patch spotapi, SpotipyFree, and spotdl against Spotify GraphQL crashes, timeouts, and empty search results
RUN python3 app/patch_packages.py

# Create mount points & host path compatibility symlinks
RUN mkdir -p /storage /music /music_new /config/beets /config/.cache /config/spotdl /srv/dev-disk-by-uuid-5c92a2d3-bb90-43b8-9626-372dd587ab8b && \
    chmod -R 777 /config /storage 2>/dev/null || true && \
    ln -s /music /srv/dev-disk-by-uuid-5c92a2d3-bb90-43b8-9626-372dd587ab8b/Music 2>/dev/null || true && \
    ln -s /music_new /srv/dev-disk-by-uuid-5c92a2d3-bb90-43b8-9626-372dd587ab8b/Music_New 2>/dev/null || true

EXPOSE 8085

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085"]
