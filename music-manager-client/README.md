# 🎵 Music Manager — Quick Install & User Guide

A self-hosted, automated music management suite powered by **Beets**, **SpotDL**, and local **AI Curation**. 

This package is pre-configured to run with **Docker Compose** and includes **Watchtower** for automatic background updates.

---

## 📋 Prerequisites

**The only prerequisite is Docker.** You do **NOT** need to install Beets, Python, SpotDL, yt-dlp, or ffmpeg on your machine — all of them are already pre-installed and configured inside the Docker container!

- **Docker** and **Docker Compose** on your NAS, Linux server, or PC:
  - **Linux / Debian / Ubuntu / OMV:** `sudo apt install docker.io docker-compose-plugin`
  - **Synology / TrueNAS / Unraid:** Use the built-in Docker / Container Manager app
  - **Windows / macOS:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)

---

## 🚀 3-Step Quick Installation

### Step 1: Create your `.env` configuration
In the folder where you placed `docker-compose.yml`, copy `.env.example` to `.env`:

**On Linux / macOS / NAS terminal:**
```bash
cp .env.example .env
```

**On Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

### Step 2: Set your Music paths in `.env`
Open `.env` in any text editor and point to your music folders:

```bash
# Path to your existing music collection
MUSIC_PATH=/volume1/Music

# Path for staging new downloads (before they are tagged and imported)
NEW_MUSIC_PATH=/volume1/Music_New

# (Optional) Port to access the web UI (default: 8085)
PORT=8085
```

> **Note**: If you don't already have a `Music_New` folder, create an empty folder next to your music library.

### Step 3: Start the Application
In your terminal, run:

```bash
docker compose up -d
```

That's it! Open your web browser and navigate to:
👉 **`http://localhost:8085`** *(or `http://<your-nas-ip>:8085`)*

On the first launch, the app automatically generates a clean Beets database and settings.

---

## 🔄 Automatic Updates via Watchtower

This installation comes with **Watchtower** enabled by default:
- Every hour, Watchtower checks for any updates or improvements released by the developer.
- If a new version is detected, Watchtower downloads it, gracefully restarts the `music-manager` container, and cleans up old image data.
- **Your music files, personal database (`library.db`), and settings are 100% preserved and never touched during updates.**

---

## 🛠 Useful Commands

- **View Live Logs:**
  ```bash
  docker compose logs -f music-manager
  ```
- **Stop the Application:**
  ```bash
  docker compose down
  ```
- **Restart the Application:**
  ```bash
  docker compose restart
  ```
- **Manually Force an Immediate Update:**
  ```bash
  docker compose pull && docker compose up -d
  ```
