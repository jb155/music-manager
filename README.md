# 🎵 Music Manager Web

A modern, containerized Web UI and automation suite for **SpotDL** and **Beets**, providing real-time download streaming, missing album track detection, and 1-click library organization.

---

## ✨ Features
- **📥 Music Downloader**: Download Spotify songs, albums, playlists, or search queries with automatic retry logic.
- **🔍 Missing Tracks Scanner**: Scan your Beets catalog to find missing album tracks and download them in one click.
- **📦 1-Click Library Import**: Automatically organize, tag, and move downloads from staging into your permanent library.
- **📟 Live ANSI Console**: Real-time terminal streaming via Server-Sent Events (SSE).
- **🐳 Docker Ready**: Portable, lightweight, and configurable with persistent Beets configuration.

---

## 🚀 Quick Start

```bash
docker compose up -d --build
```

Access the Web UI at: `http://<server-ip>:8085`

---

## ⚙️ Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8085` | Web interface port |
| `MUSIC_PATH` | `/srv/.../Music` | Permanent music library directory |
| `NEW_MUSIC_PATH` | `/srv/.../Music_New` | Temporary staging folder for new downloads |
| `CONFIG_PATH` | `./config` | Directory containing Beets configuration & DB |
