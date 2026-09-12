FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8085

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

# Defensively patch spotapi, SpotipyFree, and spotdl against Spotify GraphQL crashes, timeouts, and empty search results
RUN python3 -c 'import os, re, spotapi.song, spotapi.client, spotdl.types.song, SpotipyFree; \
s_file = spotapi.song.__file__; \
c = open(s_file).read(); \
c = c.replace("total_count: int = songs[\"data\"][\"searchV2\"][\"tracksV2\"][\"totalCount\"]", "if not isinstance(songs, dict): return\ntracks_v2 = (songs.get(\"data\") or {}).get(\"searchV2\", {}).get(\"tracksV2\")\nif not isinstance(tracks_v2, dict): return\ntotal_count = tracks_v2.get(\"totalCount\") or 0"); \
open(s_file, "w").write(c); \
sp_file = os.path.join(os.path.dirname(SpotipyFree.__file__), "Spotify.py"); \
c2 = open(sp_file).read(); \
c2 = c2.replace("for res in results:\n            res = res[\"item\"][\"data\"]", "for res in (results or []):\n            if not isinstance(res, dict): continue\n            res = (res.get(\"item\") or {}).get(\"data\") or {}\n            if not isinstance(res, dict): continue"); \
open(sp_file, "w").write(c2); \
sc_file = spotapi.client.__file__; \
c3 = open(sc_file).read(); \
c3 = c3.replace("url = \"https://code.thetadev.de", "return _FALLBACK_SECRET\n    try:\n        url = \"https://code.thetadev.de"); \
open(sc_file, "w").write(c3); \
ss_file = spotdl.types.song.__file__; \
c4 = open(ss_file).read(); \
t_old = "if len(raw_search_results[\"tracks\"][\"items\"]) == 0:\n            raise SongError(f\"No results found for: {search_term}\")"; \
t_new = "if len(raw_search_results[\"tracks\"][\"items\"]) == 0:\n            if \" - \" in search_term:\n                try:\n                    alt = Song.search(search_term.replace(\" - \", \" \"))\n                    if alt and len(alt.get(\"tracks\", {}).get(\"items\", [])) > 0: raw_search_results = alt\n                except Exception: pass\n            if len(raw_search_results[\"tracks\"][\"items\"]) == 0:\n                try:\n                    alt = Song.search(search_term.title().replace(\" - \", \" \"))\n                    if alt and len(alt.get(\"tracks\", {}).get(\"items\", [])) > 0: raw_search_results = alt\n                except Exception: pass\n        if len(raw_search_results[\"tracks\"][\"items\"]) == 0:\n            raise SongError(f\"No results found for: {search_term}\")"; \
c4 = c4.replace(t_old, t_new); \
open(ss_file, "w").write(c4)' || true

# Copy application code
COPY app/ ./app/

# Create mount points & host path compatibility symlinks
RUN mkdir -p /storage /music /music_new /config/beets /srv/dev-disk-by-uuid-5c92a2d3-bb90-43b8-9626-372dd587ab8b && \
    ln -s /music /srv/dev-disk-by-uuid-5c92a2d3-bb90-43b8-9626-372dd587ab8b/Music 2>/dev/null || true && \
    ln -s /music_new /srv/dev-disk-by-uuid-5c92a2d3-bb90-43b8-9626-372dd587ab8b/Music_New 2>/dev/null || true

EXPOSE 8085

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085"]
