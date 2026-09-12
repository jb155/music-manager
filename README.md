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

> **No complex dependencies required!** Beets, SpotDL, yt-dlp, ffmpeg, chromaprint, and all Python plugins are **already pre-installed inside the container**. The only requirement on the host machine is **Docker**.

You can run Music Manager either via the **pre-built container with automated updates** (recommended) or by **building from source**.

### Option A: Quick Setup with Automated Updates (Recommended)

This method requires no build tools. It pulls the pre-built container from the GitHub Container Registry (`ghcr.io`) and includes **Watchtower** for automated zero-downtime background updates.

#### 1. Via Terminal (Linux, macOS, NAS, Windows)
1. **Download the Client Package** (from the [`music-manager-client/`](./music-manager-client) directory) or create a `docker-compose.yml`:
   ```yaml
   services:
     music-manager:
       image: ghcr.io/jb155/music-manager:latest
       container_name: music_manager
       restart: unless-stopped
       ports:
         - "${PORT:-8085}:8085"
       environment:
         - STORAGE_DIR=/storage
         - PYTHONUNBUFFERED=1
         - OLLAMA_HOST=${OLLAMA_HOST:-}
         - OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3.5:9b}
       volumes:
         - ${STORAGE_PATH:-./music_data}:/storage
       labels:
         - "com.centurylinklabs.watchtower.enable=true"

     watchtower:
       image: containrrr/watchtower
       container_name: watchtower_music
       restart: unless-stopped
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock
       environment:
         - DOCKER_API_VERSION=1.44
         - WATCHTOWER_CLEANUP=true
         - WATCHTOWER_POLL_INTERVAL=3600
         - WATCHTOWER_LABEL_ENABLE=true
       command: --interval 3600
   ```

2. **Create a `.env` file** in the same directory:
   ```bash
   # Base storage location on your machine or NAS:
   STORAGE_PATH=./music_data

   # Port for the web interface
   PORT=8085

   # (Optional) Ollama server URL if using local AI playlist curation
   # OLLAMA_HOST=http://192.168.1.50:11434
   # OLLAMA_MODEL=qwen3.5:9b
   ```

3. **Start the containers:**
   ```bash
   docker compose up -d
   ```
   Open your browser at **`http://<server-ip>:8085`**.

#### 2. Via OpenMediaVault (OMV) Web GUI
1. In the OMV Dashboard, navigate to **Services** ➔ **Compose** ➔ **Files**.
2. Click **➕ (Add / Create)**.
3. Set **Name** to `music-manager`, and paste the YAML above into **File (Compose)**.
4. Check **Show environment file** and paste:
   ```bash
   STORAGE_PATH=./music_data
   PORT=8085
   ```
   *(Or point `STORAGE_PATH` to an existing shared folder on your OMV data disk, e.g. `/srv/dev-disk-.../MusicData`)*.
5. Click **Save**, apply changes (✓), select `music-manager`, and click **Up (▶️)**.

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
   # Edit .env to set your MUSIC_PATH and NEW_MUSIC_PATH folders
   ```

3. **Build and launch:**
   ```bash
   docker compose up -d --build
   ```

---

## 📂 Storage Structure

With the default single-storage setup (`STORAGE_PATH`), Music Manager automatically provisions and maintains the following directory tree:

```text
your_storage_folder/
  ├── music/          <- Your permanent, organized music library (Artist/Album/Track)
  ├── music_new/      <- Staging folder for incoming downloads before cataloging
  ├── config/beets/   <- Database (library.db) and configuration (config.yaml)
  └── .music_preview/ <- Temporary audio preview clips (auto-cached)
```

---

## ⚙️ Configuration Reference (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `STORAGE_PATH` | `./music_data` | Single base directory housing your library, staging, and Beets database |
| `PORT` | `8085` | Web interface port on the host (`http://<ip>:8085`) |
| `OLLAMA_HOST` | *(empty)* | Optional URL to local Ollama server (e.g. `http://192.168.1.50:11434`) |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Model used for playlist recommendations and smart naming |

---

## 🔄 Automated Updates

- When using **Option A**, Watchtower checks `ghcr.io` every 3600 seconds.
- When an updated version is published, Watchtower pulls it, performs a zero-downtime rolling restart, and purges old image layers.
- **Your personal music files, tags, and database (`library.db`) are mounted as external volumes and are never touched or altered during updates.**
