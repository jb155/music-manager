# 🎵 Music Manager

A modern, self-hosted music automation suite and Web UI powered by **Beets**, **SpotDL**, and local **AI Curation (Ollama)**. It provides high-speed music downloading, missing album detection, 1-click tagging and library organization, interactive 30-second song previews, and smart Venn-diagram playlist generation.

---

## ✨ Key Features

- **📥 Multi-Source Music Downloader**: Download tracks, full albums, artist discographies, or YouTube/Spotify links with automated retry resilience and fallback matching.
- **🔍 Missing Album Tracks Scanner**: Automatically audit your existing albums against MusicBrainz to find missing tracks and complete albums in one click.
- **📦 1-Click Beets Library Organizer**: Automatic ID3 tagging, genre categorization, album art fetching & embedding, deduplication, and file relocation from staging into your permanent library.
- **🎧 Music Vault Explorer**: Browse your entire catalog by Artist, Album, or Track with embedded **30-second instant audio previews** and artist portrait art.
- **🤖 AI Curated Playlists & Venn Diagrams**: Generate custom playlists using local Ollama models (Qwen, Llama, Mistral) based on genre overlaps, eras, and artist mood blending.
- **📟 Live ANSI Console**: Real-time terminal streaming via Server-Sent Events (SSE) with task abort controls.
- **🔄 Automated CI/CD & Self-Updating**: Built with GitHub Actions and Watchtower for zero-maintenance auto-updates.

---

## 🚀 Installation & Deployment

You can run Music Manager either via the **pre-built container with automated updates** (recommended) or by **building from source**.

### Option A: Quick Setup with Automated Updates (Recommended)

This method requires no build tools. It pulls the pre-built container from the GitHub Container Registry (`ghcr.io`) and includes **Watchtower** for automated zero-downtime updates whenever new releases are pushed.

1. **Download the Client Package** (from the [`music-manager-client/`](./music-manager-client) folder) or create a `docker-compose.yml`:
   ```yaml
   services:
     music-manager:
       image: ghcr.io/jb155/music-manager:latest
       container_name: music_manager
       restart: unless-stopped
       ports:
         - "${PORT:-8085}:8085"
       environment:
         - MUSIC_DIR=/music
         - NEW_MUSIC_DIR=/music_new
         - BEETSDIR=/config/beets
         - PREVIEW_DIR=/.music_preview
         - PYTHONUNBUFFERED=1
         - OLLAMA_HOST=${OLLAMA_HOST:-}
         - OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3.5:9b}
       volumes:
         - ${MUSIC_PATH}:/music
         - ${NEW_MUSIC_PATH}:/music_new
         - ${CONFIG_PATH:-./config}:/config
         - ${PREVIEW_PATH:-./.music_preview}:/.music_preview
       labels:
         - "com.centurylinklabs.watchtower.enable=true"

     watchtower:
       image: containrrr/watchtower
       container_name: watchtower_music
       restart: unless-stopped
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock
       environment:
         - WATCHTOWER_CLEANUP=true
         - WATCHTOWER_POLL_INTERVAL=3600
         - WATCHTOWER_LABEL_ENABLE=true
       command: --interval 3600
   ```

2. **Create a `.env` file** in the same directory:
   ```bash
   # Port where the web UI will be accessible
   PORT=8085

   # Path to your permanent music collection on your host or NAS
   MUSIC_PATH=/path/to/your/Music

   # Path for staging new downloads before import
   NEW_MUSIC_PATH=/path/to/your/Music_New

   # (Optional) Ollama server URL if using local AI playlist curation
   OLLAMA_HOST=
   ```

3. **Start the containers:**
   ```bash
   docker compose up -d
   ```
   Open your browser at **`http://<server-ip>:8085`**.

---

### Option B: Build & Run from Source (Developers)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/jb155/music-manager.git
   cd music-manager
   ```

2. **Configure your paths:**
   ```bash
   cp .env.example .env
   # Edit .env to point MUSIC_PATH and NEW_MUSIC_PATH to your storage folders
   ```

3. **Build and launch:**
   ```bash
   docker compose up -d --build
   ```

---

## ⚙️ Configuration Reference (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8085` | Web interface port on the host |
| `MUSIC_PATH` | `/path/to/your/Music` | Permanent music library directory |
| `NEW_MUSIC_PATH` | `/path/to/your/Music_New` | Staging directory for newly downloaded tracks |
| `CONFIG_PATH` | `./config` | Persistent directory for Beets configuration & SQLite database |
| `PREVIEW_PATH` | `./.music_preview` | Temporary cache directory for 30-second audio previews (auto-purged) |
| `OLLAMA_HOST` | *(empty)* | URL to local Ollama server (e.g. `http://192.168.1.50:11434`) |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Model used for playlist recommendations and smart naming |

---

## 🔄 Automated Updates

- When using **Option A**, Watchtower polls `ghcr.io` every 3600 seconds.
- When an updated image is published, Watchtower downloads it, performs a graceful rolling restart of the container, and cleans up the old image.
- **Your personal music files, tags, and database (`library.db`) are mounted as external volumes and are never touched or altered during updates.**
