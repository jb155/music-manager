# 🎵 Music Manager — Quick Install & User Guide

A self-hosted, automated music management suite powered by **Beets**, **SpotDL**, and local **AI Curation**. 

This package is pre-configured to run with **Docker Compose** as a clean single service with automated in-app update notifications.

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

### Step 2: Set your Base Storage Location in `.env`
Open `.env` in any text editor and declare where your files will live. **You only need to set one folder!**

```bash
# Set this to your base folder on your machine or NAS:
STORAGE_PATH=/volume1/MusicData
```
*(On Windows: `STORAGE_PATH=D:\MusicData`, or leave default `./music_data` to store next to the compose file)*

The system **automatically creates and organizes** the subfolders for you on startup:
```text
your_storage_folder/
  ├── music/          <- Your permanent, organized music library (Artist/Album/Track)
  ├── music_new/      <- Staging folder for incoming downloads before cataloging
  ├── config/beets/   <- Database (library.db) and configuration (config.yaml)
  └── .music_preview/ <- Temporary audio preview clips
```

> **Have existing music?** Simply drop your existing audio files or artist folders into the generated `music/` folder (or drop unorganized files into `music_new/` to let the auto-importer tag and file them).

### Step 3: Start the Application
In your terminal, run:

```bash
docker compose up -d
```

That's it! Open your web browser and navigate to:
👉 **`http://localhost:8085`** *(or `http://<your-nas-ip>:8085`)*

On first launch, the app automatically initializes all folders, generates a tuned Beets configuration, and connects to the Web UI.

---

## 🖥️ Alternative: OpenMediaVault (OMV) Web GUI Installation

If you manage your NAS using the OpenMediaVault Web GUI with the **Compose Plugin**:

1. Log into your **OMV Web Interface**.
2. Navigate to **Services** ➔ **Compose** ➔ **Files**.
3. Click the **➕ (Add / Create)** button.
4. Fill in the form:
   - **Name:** `music-manager`
   - **Description:** `Music Manager & Beets Automation`
   - **File (Compose):** Paste the contents of `docker-compose.yml`
   - Check **Show environment file**
   - **Environment:**
     ```bash
     STORAGE_PATH=./music_data
     PORT=8085
     ```
     *(Or set `STORAGE_PATH` to any shared folder path on your OMV disk)*
5. Click **Save**, then click the yellow banner's **Apply (✓)** checkmark.
6. Select `music-manager` in the table and click **Up (▶️)** to pull and start the service.
7. Open **`http://<your-nas-ip>:8085`** in your browser!

### 📥 Adding Music:
- **Web UI (Easiest)**: Navigate to the **Staging & Import** tab and drag & drop a music folder, loose audio files, or a `.zip` album archive right into the window (or click **Select Music Folder**). With auto-import enabled, the system automatically identifies the tracks via MusicBrainz, fetches album artwork, embeds metadata, and files them into `Artist/Album/Track`.
- **Direct Copy**: You can also drop audio files directly into your host machine's `music_new/` folder and click **1-Click Beets Import** in the web UI.

---

## 🔄 Updates & Version Notifications

Music Manager includes built-in version checking without requiring any third-party background updater services running on your server:
- When a new version is published, an **Update Available (vX.X.X)** button appears directly in the Web UI header.
- Click the notification to view the release notes and update instructions.
- To update:
  - **OpenMediaVault GUI:** Go to **Services ➔ Compose ➔ Files**, select `music-manager`, click **Pull**, then click **Up**.
  - **Terminal / Docker CLI:** Run:
    ```bash
    docker compose pull && docker compose up -d
    ```
- **Your music library, beets database (`library.db`), and configurations are 100% persistent in your storage volume.**

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
- **Manually Pull & Update:**
  ```bash
  docker compose pull && docker compose up -d
  ```
