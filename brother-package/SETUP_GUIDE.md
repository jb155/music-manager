# Music Manager — Distribution & Setup Guide

This guide explains how to publish the **Music Manager** container to GitHub Container Registry (`ghcr.io`), and how your brother can run it with **automatic background updates via Watchtower**.

---

## Part 1: Publishing to GitHub (One-Time Setup for You)

### Step 1: Create a GitHub Repository
1. Go to [github.com/new](https://github.com/new).
2. Name the repository `music-manager`.
3. Choose **Public** (easiest for your brother so no docker login token is needed) or **Private**.
4. Click **Create repository**.

### Step 2: Push Your Code
On your machine / NAS, run:
```bash
cd /path/to/DockerFolder/music-manager
git init
git add .
git commit -m "Initial release of Music Manager"
git branch -M main
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/music-manager.git
git push -u origin main
```

### Step 3: Enable Package Permissions (If Repository is Public)
1. Go to your repository on GitHub: `Actions` tab -> You will see the **Build and Publish Docker Image** workflow running.
2. Once finished, go to your GitHub Profile -> **Packages** -> Click `music-manager`.
3. Under **Package settings**, ensure package visibility is set to **Public** (or grant your brother access if private).

---

## Part 2: Running on Your Brother's Machine / NAS

All your brother needs is the `brother-package` folder containing:
- `docker-compose.yml`
- `.env.example`

### Step 1: Create his `.env` file
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and set:
   - `IMAGE_NAME=ghcr.io/<YOUR_GITHUB_USERNAME>/music-manager:latest`
   - `MUSIC_PATH`: The path to where his music lives (e.g. `/volume1/Music` or `D:/Music`).
   - `NEW_MUSIC_PATH`: The path for staging new downloads (e.g. `/volume1/Music_New`).

*(If the GitHub repository/package is private, he runs `docker login ghcr.io` once with a personal access token).*

### Step 2: Start the System
Run:
```bash
docker compose up -d
```
The Music Manager will start up at `http://<his-ip>:8085`. On first launch, it will automatically generate a clean Beets configuration and database for his library.

---

## Part 3: How Automatic Updates Work

1. Whenever you make code improvements or bug fixes, simply run:
   ```bash
   git commit -am "Added new feature"
   git push
   ```
2. **GitHub Actions** will automatically compile the new Docker image and push it to `ghcr.io/...:latest`.
3. **Watchtower** running on your brother's NAS/machine automatically polls `ghcr.io` every hour:
   - When it detects that you pushed a new image, it downloads the update.
   - It performs a rolling restart of his `music_manager` container.
   - It cleans up the old image to save disk space.
   - **His personal music files, tags, and database are 100% preserved.**
