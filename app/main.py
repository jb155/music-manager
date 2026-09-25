import json
import re
import os
import time
import asyncio
import urllib.request

# Ensure HOME and XDG environment variables point to a writable config directory
# to prevent SpotDL, Spotipy, and yt-dlp from failing with PermissionError when running as unprivileged user
_storage_dir = os.environ.get("STORAGE_DIR")
_default_config = os.path.join(_storage_dir, "config") if _storage_dir else "/config"
if not os.environ.get("HOME") or os.environ.get("HOME") == "/":
    os.environ["HOME"] = _default_config
if not os.environ.get("XDG_CONFIG_HOME"):
    os.environ["XDG_CONFIG_HOME"] = _default_config
if not os.environ.get("XDG_CACHE_HOME"):
    os.environ["XDG_CACHE_HOME"] = os.path.join(_default_config, ".cache")
try:
    os.makedirs(os.path.join(_default_config, "spotdl"), exist_ok=True)
    os.makedirs(os.path.join(_default_config, ".cache"), exist_ok=True)
except Exception:
    pass
from datetime import datetime, timedelta
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union

from app.services.manager import MusicManagerService

try:
    from app.patch_packages import patch_all
    patch_all()
except Exception:
    pass


APP_VERSION = "1.5.5"

app = FastAPI(title="Music Manager Web", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = MusicManagerService()

@app.on_event("startup")
async def on_startup():
    # Initial cleanup of audio previews older than 24h
    try:
        service.cleanup_expired_previews()
    except Exception:
        pass

    # Periodic background task: run cleanup every 1 hour
    async def periodic_preview_cleanup():
        while True:
            await asyncio.sleep(3600)
            try:
                service.cleanup_expired_previews()
            except Exception:
                pass

    asyncio.create_task(periodic_preview_cleanup())

    # Periodic background task: automatically deduplicate and sanitize library after sync
    async def periodic_library_sanitization():
        await asyncio.sleep(30)
        while True:
            try:
                await service.sanitize_and_deduplicate_library()
            except Exception:
                pass

            interval_env = os.environ.get("RECONCILIATION_INTERVAL_HOURS", "").strip()
            if interval_env and interval_env.isdigit() and int(interval_env) > 0:
                sleep_seconds = int(interval_env) * 3600
            else:
                try:
                    now = datetime.now()
                    tomorrow = (now + timedelta(days=1)).date()
                    next_midnight = datetime.combine(tomorrow, datetime.min.time())
                    sleep_seconds = max((next_midnight - now).total_seconds(), 5.0)
                except Exception:
                    sleep_seconds = 21600  # 6 hours fallback

            await asyncio.sleep(sleep_seconds)

    asyncio.create_task(periodic_library_sanitization())

# Request Models
class DownloadRequest(BaseModel):
    query: str
    auto_import: bool = False
    max_retries: int = 3
    auto_complete_album: bool = False
    target_album: Optional[str] = None
    force: bool = False

class MissingDownloadRequest(BaseModel):
    tracks: Optional[List[Union[str, Dict[str, Any]]]] = None
    auto_import: bool = False

class ImportRequest(BaseModel):
    force: bool = False

class BatchDownloadRequest(BaseModel):
    tracks: List[str]
    auto_import: bool = True
    label: Optional[str] = "AI Recommendations"
    auto_complete_album: bool = False

class RecommendRequest(BaseModel):
    prompt: Optional[str] = ""
    model: Optional[str] = None
    overlap_type: Optional[str] = "genre_genre"
    target_a: Optional[str] = ""
    target_b: Optional[str] = ""
    targets: Optional[List[str]] = None
    venn_slice: Optional[str] = "overlap_only"
    preset: Optional[str] = None
    count: Optional[int] = 6
    anchor_artists: Optional[List[str]] = None
    custom_guidance: Optional[str] = None

class AddOllamaServerRequest(BaseModel):
    host: str
    set_active: bool = True

class SelectOllamaServerRequest(BaseModel):
    host: str

class ScanOllamaRequest(BaseModel):
    subnet: Optional[str] = None


class TagGenresRequest(BaseModel):
    force: bool = False

class VennStatsRequest(BaseModel):
    overlap_type: str = "genre_genre"
    target_a: Optional[str] = ""
    target_b: Optional[str] = ""
    targets: Optional[List[str]] = None

class PlaylistGenerateRequest(BaseModel):
    mode: str = "random"
    duration_sec: int = 3600
    target_tracks: int = 15
    limit_by: str = "time"
    genres: Optional[List[str]] = None
    blend_mode: Optional[str] = "interleaved"
    decades: Optional[List[int]] = None
    chronological: Optional[bool] = True
    seed_artists: Optional[List[str]] = None
    smart_shuffle: Optional[bool] = True
    prompt: Optional[str] = ""
    model: Optional[str] = None
    overlap_type: Optional[str] = "genre_genre"
    target_a: Optional[str] = ""
    target_b: Optional[str] = ""
    targets: Optional[List[str]] = None
    venn_slice: Optional[str] = "overlap_only"
    selected_region: Optional[Dict[str, Any]] = None
    playlist_name: Optional[str] = None

class PlaylistSuggestTitleRequest(BaseModel):
    mode: str = "random"
    params: Optional[Dict[str, Any]] = None
    tracks: Optional[List[Dict[str, Any]]] = None

class PlaylistExportRequest(BaseModel):
    playlist_name: Optional[str] = "My Playlist"
    tracks: List[Dict[str, Any]]

class DeleteImpactRequest(BaseModel):
    target_type: str  # "artist", "album", "song"
    target_id: Optional[Any] = None
    artist_name: Optional[str] = None
    album_id: Optional[Union[int, str]] = None
    song_id: Optional[int] = None

class DeleteItemsRequest(BaseModel):
    track_ids: List[int]
    delete_files: bool = True

# Existing API Routes
_version_cache = {"last_check": 0, "data": None}

def parse_semver(v: str):
    """Parse semver string like '1.3.1' or 'v1.3.1' into tuple of ints for comparison."""
    clean = re.sub(r'^[^\d]*', '', v or '')
    parts = []
    for p in clean.split('.'):
        try:
            m = re.match(r'\d+', p)
            parts.append(int(m.group(0)) if m else 0)
        except Exception:
            parts.append(0)
    return tuple(parts)

@app.get("/api/version")
async def get_version_info(refresh: bool = False):
    """Check for new versions from GitHub repository."""
    now = time.time()
    # Cache version check for 5 minutes (300s) to keep it responsive to new releases
    if not refresh and _version_cache["data"] and (now - _version_cache["last_check"] < 300):
        return _version_cache["data"]

    remote_version = APP_VERSION
    release_notes = ""
    release_url = "https://github.com/jb155/music-manager"
    update_available = False

    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/jb155/music-manager/main/version.json",
            headers={"User-Agent": f"MusicManager/{APP_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                vdata = json.loads(resp.read().decode('utf-8'))
                remote_version = vdata.get("version", APP_VERSION)
                release_notes = vdata.get("notes", "")
                if parse_semver(remote_version) > parse_semver(APP_VERSION):
                    update_available = True
    except Exception:
        pass

    res = {
        "current_version": APP_VERSION,
        "latest_version": remote_version,
        "update_available": update_available,
        "release_notes": release_notes,
        "release_url": release_url
    }
    _version_cache["last_check"] = now
    _version_cache["data"] = res
    return res

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "Music Manager Web", "version": APP_VERSION}

@app.get("/api/system/storage")
async def get_storage_info():
    return service.get_storage_info()

@app.get("/api/system/storage")
async def get_storage_info():
    return service.get_storage_info()

@app.get("/api/status")
async def get_status():
    return service.task_progress

@app.get("/api/library/stats")
async def get_stats():
    stats = await service.get_library_stats()
    disk_count = service.count_disk_files()
    stats["disk_tracks"] = str(disk_count)
    return stats

@app.get("/api/staging")
async def get_staging():
    return service.get_staging_files()

@app.get("/api/missing")
async def get_missing(max_albums: int = 40, refresh: bool = False):
    """Return missing tracks from incomplete albums."""
    tracks = await service.get_missing_tracks(max_albums=max_albums, force_refresh=refresh)
    return {"count": len(tracks), "tracks": tracks}

@app.get("/api/missing/cached")
async def get_cached_missing():
    """Return cached scan results instantly without querying MusicBrainz."""
    tracks = service.get_cached_missing_tracks()
    return {"count": len(tracks), "tracks": tracks}

@app.post("/api/missing/scan")
async def trigger_missing_scan(bg: BackgroundTasks, max_albums: int = 40):
    """Trigger missing tracks scan in background with live terminal logs."""
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    service._abort_requested = False
    bg.add_task(service.get_missing_tracks, max_albums, True)
    return {"message": f"Started missing tracks scan (depth: {max_albums} albums)"}

@app.post("/api/library/scan")
async def scan_library(bg: BackgroundTasks):
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    service._abort_requested = False
    bg.add_task(service.scan_and_find_missing)
    return {"message": "Full library scan started"}

@app.post("/api/library/fetchart")
async def fetch_album_art(bg: BackgroundTasks):
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    service._abort_requested = False
    bg.add_task(service.fetch_all_art)
    return {"message": "Album art fetching started"}

@app.post("/api/download")
async def start_download(req: DownloadRequest, bg: BackgroundTasks):
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    service._abort_requested = False
    bg.add_task(
        service.download_track_or_url,
        req.query,
        req.max_retries,
        req.auto_import,
        req.auto_complete_album,
        req.target_album,
        req.force
    )
    return {"message": "Download task started", "query": req.query}

@app.post("/api/missing/download")
async def start_missing_download(req: MissingDownloadRequest, bg: BackgroundTasks):
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    service._abort_requested = False
    bg.add_task(service.download_missing_tracks, req.tracks, req.auto_import)
    return {"message": "Missing tracks download started"}

@app.post("/api/upload")
async def upload_music_files(
    bg: BackgroundTasks,
    files: List[UploadFile] = File(...),
    relative_paths: Optional[List[str]] = Form(None),
    auto_import: bool = Form(False)
):
    """Upload audio files or a folder into staging, with optional automatic Beets import."""
    results = []
    total_bytes = 0

    for i, file_obj in enumerate(files):
        rel_path = relative_paths[i] if (relative_paths and i < len(relative_paths)) else None
        res = await service.save_uploaded_file(file_obj.filename, file_obj, rel_path)
        results.append(res)
        total_bytes += res.get("bytes", 0)

    import_started = False
    if auto_import:
        if service.task_progress.get("status") != "running":
            service._abort_requested = False
            bg.add_task(service.import_library, False)
            import_started = True

    return {
        "success": True,
        "count": len(files),
        "total_bytes": total_bytes,
        "results": results,
        "auto_import_started": import_started
    }

@app.post("/api/import")
async def start_import(bg: BackgroundTasks, req: Optional[ImportRequest] = None):
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    # Eagerly reset abort flag before queuing — prevents stale flag from a prior abort
    service._abort_requested = False
    force = req.force if req else False
    bg.add_task(service.import_library, force)
    return {"message": "Library import task started"}

@app.post("/api/task/abort")
@app.post("/api/download/abort")
async def abort_task_endpoint():
    """Immediately stop and abort any running background task or download."""
    result = await service.abort_current_task()
    return result

# AI Music Recommendation & Ollama Management Routes
@app.get("/api/ai/status")
async def get_ai_status():
    """Check active Ollama connectivity and list available models & remembered servers."""
    return await service.get_ollama_status()

@app.get("/api/ai/servers")
async def get_ai_servers():
    """List remembered Ollama servers and current active server."""
    status = await service.get_ollama_status()
    return {
        "active_host": service.ollama_host,
        "servers": service.ollama_servers,
        "connected": status["connected"],
        "models": status["models"],
        "error": status["error"]
    }

@app.post("/api/ai/servers/scan")
async def scan_ai_servers(req: Optional[ScanOllamaRequest] = None):
    """Scan local network for running Ollama instances on port 11434 and register them."""
    subnet = req.subnet if req else None
    discovered = await service.scan_network_for_ollama(subnet_prefix=subnet)
    status = await service.get_ollama_status()
    return {
        "count": len(discovered),
        "discovered": discovered,
        "active_host": service.ollama_host,
        "servers": service.ollama_servers,
        "models": status["models"],
        "connected": status["connected"]
    }

@app.post("/api/ai/servers/add")
async def add_ai_server(req: AddOllamaServerRequest):
    """Manually add, test, and remember an Ollama server IP or URL."""
    res = await service.add_ollama_server(req.host, set_active=req.set_active)
    return res

@app.post("/api/ai/servers/select")
async def select_ai_server(req: SelectOllamaServerRequest):
    """Switch active Ollama server and refresh models."""
    return await service.set_active_ollama_server(req.host)

@app.delete("/api/ai/servers")
async def remove_ai_server(host: str):
    """Remove a server from remembered servers."""
    return service.remove_ollama_server(host)

@app.get("/api/ai/taste-profile")
async def get_taste_profile(include_all: bool = True):
    """Return library taste profile summary, all artists, and dynamic library styles."""
    return service.get_taste_profile(top_n=40, include_all=include_all)

@app.get("/api/ai/style-focuses")
async def get_ai_style_focuses():
    """Return dynamic style focus presets generated from library taxonomy."""
    return {"styles": service.get_dynamic_style_focuses()}

@app.post("/api/ai/recommend")
async def get_ai_recommendations(req: RecommendRequest):
    """Generate recommendations from local Ollama model."""
    result = await service.generate_ai_recommendations(
        prompt=req.prompt or "",
        model=req.model,
        preset=req.preset,
        count=req.count or 6,
        anchor_artists=req.anchor_artists,
        custom_guidance=req.custom_guidance
    )
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "AI generation failed"))
    return result

@app.post("/api/ai/download-all")
async def download_all_recommendations(req: BatchDownloadRequest, bg: BackgroundTasks):
    """Start sequential batch download for all recommended tracks with auto-import."""
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    if not req.tracks:
        raise HTTPException(status_code=400, detail="No tracks provided for download.")
    service._abort_requested = False
    bg.add_task(service.download_batch_tracks, req.tracks, req.label, req.auto_import, req.auto_complete_album)
    return {"message": f"Started batch download of {len(req.tracks)} recommended tracks", "count": len(req.tracks)}

@app.get("/api/logs/stream")
async def stream_logs():
    """Server-Sent Events endpoint to stream terminal output live."""
    queue = service.subscribe_logs()

    async def event_generator():
        try:
            yield "data: [CONNECTED] Live terminal stream established.\n\n"
            while True:
                line = await queue.get()
                formatted = line.replace("\n", "\ndata: ")
                yield f"data: {formatted}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            service.unsubscribe_logs(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Genre Tagging Endpoints
@app.post("/api/library/sanitize")
async def sanitize_library_endpoint(bg: BackgroundTasks):
    """Trigger library sanitation and deduplication in background."""
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    service._abort_requested = False
    bg.add_task(service.sanitize_and_deduplicate_library)
    return {"message": "Started library sanitation and deduplication in background"}

@app.post("/api/library/tag-genres")
async def tag_library_genres(req: TagGenresRequest, bg: BackgroundTasks):
    """Trigger full library genre tagging & ID3 updating in background."""
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A task is already running.")
    service._abort_requested = False
    bg.add_task(service.tag_entire_library_genres, req.force)
    return {"message": "Started full library genre tagging and audio file updating in background"}

@app.get("/api/library/genre-stats")
async def get_library_genre_stats():
    return service.get_library_genre_stats()

# Playlist Creator Endpoints
@app.get("/api/playlist/meta")
@app.get("/api/playlist/metadata")
async def get_playlist_metadata():
    return service.get_playlist_meta()

@app.post("/api/playlist/venn-stats")
async def get_venn_stats_endpoint(req: VennStatsRequest):
    return service.get_venn_stats(req.dict())

@app.post("/api/playlist/generate")
async def generate_playlist_endpoint(req: PlaylistGenerateRequest):
    return await service.generate_playlist(req.dict())

@app.post("/api/playlist/suggest-title")
async def suggest_playlist_title_endpoint(req: PlaylistSuggestTitleRequest):
    """Suggest a creative and relevant playlist title based on current mode, settings, and tracks."""
    title = service.generate_playlist_name(req.mode, req.params or {}, req.tracks or [])
    return {"status": "ok", "success": True, "playlist_name": title}

@app.post("/api/playlist/export/m3u8")
async def export_playlist_m3u8(req: PlaylistExportRequest):
    content = service.build_m3u8_content(req.tracks, req.playlist_name or "Playlist", relative_paths=False)
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', req.playlist_name or "playlist").strip('_') or "playlist"
    return Response(
        content=content.encode("utf-8"),
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.m3u8"'}
    )

@app.post("/api/playlist/export/pls")
async def export_playlist_pls(req: PlaylistExportRequest):
    content = service.build_pls_content(req.tracks, req.playlist_name or "Playlist", relative_paths=False)
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', req.playlist_name or "playlist").strip('_') or "playlist"
    return Response(
        content=content.encode("utf-8"),
        media_type="audio/x-scpls",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.pls"'}
    )

@app.post("/api/playlist/export/json")
async def export_playlist_json(req: PlaylistExportRequest):
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', req.playlist_name or "playlist").strip('_') or "playlist"
    data_str = json.dumps({"playlist_name": req.playlist_name, "tracks": req.tracks}, indent=2)
    return Response(
        content=data_str.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'}
    )

@app.post("/api/playlist/export/zip")
async def export_playlist_zip(req: PlaylistExportRequest):
    if not req.tracks:
        raise HTTPException(status_code=400, detail="No tracks provided for zip export.")
    zip_path = service.create_playlist_zip(req.tracks, req.playlist_name or "playlist")
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', req.playlist_name or "playlist").strip('_') or "playlist"

    def iterfile():
        with open(zip_path, mode="rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        iterfile(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.zip"'}
    )

def stream_file_with_range(file_path: str, request: Request, default_media_type: str = "audio/mpeg"):
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Audio file not found: {os.path.basename(file_path)}")
    
    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".wav": "audio/wav"
    }
    content_type = media_types.get(ext, default_media_type)
    range_header = request.headers.get("Range")

    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            end = min(end, file_size - 1)
            chunk_size = (end - start) + 1

            def range_iter():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = chunk_size
                    while remaining > 0:
                        read_bytes = min(remaining, 65536)
                        chunk = f.read(read_bytes)
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Content-Type": content_type,
                "Cache-Control": "public, max-age=3600"
            }
            return StreamingResponse(range_iter(), status_code=206, headers=headers)

    def full_iter():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=3600"
    }
    return StreamingResponse(full_iter(), status_code=200, headers=headers)

# -------------------------------------------------------------
# AUDIO STREAMING & PREVIEW ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/audio/preview/{track_id}")
async def get_audio_preview(track_id: int, request: Request):
    """Extract/serve on-demand 30s preview clip from /.music_preview with Range support."""
    preview_file = service.get_or_create_audio_preview(track_id)
    if not preview_file or not os.path.exists(preview_file):
        # Fallback to streaming local file directly if preview extraction failed
        track = service.get_track_by_id(track_id)
        if track and track.get("path") and os.path.exists(track["path"]):
            return stream_file_with_range(track["path"], request)
        raise HTTPException(status_code=404, detail=f"Audio preview not available for track {track_id}")
    return stream_file_with_range(preview_file, request)

@app.get("/api/audio/stream/{track_id}")
async def get_audio_stream(track_id: int, request: Request):
    """Stream full audio track from library vault with Range support."""
    track = service.get_track_by_id(track_id)
    if not track or not track.get("path") or not os.path.exists(track["path"]):
        raise HTTPException(status_code=404, detail=f"Audio file not found in library vault for track {track_id}")
    return stream_file_with_range(track["path"], request)

@app.get("/api/audio/download/{track_id}")
async def download_audio_track(track_id: int):
    """Directly download a single audio file from library vault."""
    track = service.get_track_by_id(track_id)
    if not track or not track.get("path") or not os.path.exists(track["path"]):
        raise HTTPException(status_code=404, detail=f"Audio file not found in library vault for track {track_id}")
    file_path = track["path"]
    ext = os.path.splitext(file_path)[1] or ".mp3"
    clean_artist = re.sub(r'[/\\:*?"<>|]', '_', track.get("artist", "Unknown")).strip() or "Artist"
    clean_title = re.sub(r'[/\\:*?"<>|]', '_', track.get("title", "Track")).strip() or "Track"
    filename = f"{clean_artist} - {clean_title}{ext}"
    media_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".wav": "audio/wav"
    }
    content_type = media_types.get(ext.lower(), "application/octet-stream")
    return FileResponse(
        file_path,
        media_type=content_type,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/audio/preview-staging")
async def get_staging_audio_preview(file: str, request: Request):
    """Extract/serve on-demand 30s preview clip for a staging file in /music_new."""
    preview_file = service.get_or_create_staging_preview(file)
    if not preview_file or not os.path.exists(preview_file):
        norm_rel = file.lstrip("/\\")
        full_p = os.path.normpath(os.path.join(service.new_music_dir, norm_rel))
        if os.path.exists(full_p) and full_p.startswith(service.new_music_dir):
            return stream_file_with_range(full_p, request)
        raise HTTPException(status_code=404, detail="Staging audio file not found")
    return stream_file_with_range(preview_file, request)

@app.get("/api/audio/preview-cached/{filename}")
async def get_cached_audio_preview(filename: str, request: Request):
    """Stream cached external preview from /.music_preview."""
    safe_fn = os.path.basename(filename)
    cache_p = os.path.join(service.preview_dir, safe_fn)
    if not os.path.exists(cache_p):
        raise HTTPException(status_code=404, detail="Cached preview not found")
    return stream_file_with_range(cache_p, request)

@app.get("/api/audio/preview-query")
async def query_audio_preview(artist: str = Query(...), title: str = Query(...)):
    """On-demand audio preview resolver: checks local library first, falls back to iTunes 30s preview."""
    return service.fetch_external_audio_preview(artist, title)

# -------------------------------------------------------------
# LIBRARY BROWSER ENDPOINTS
# -------------------------------------------------------------
# ----------------------------------------------------------------------
# LIBRARY HIERARCHY ENDPOINTS
# ----------------------------------------------------------------------
@app.get("/api/library/artists")
async def get_library_artists_endpoint(
    query: str = Query("", description="Search term"),
    genre: str = Query("", description="Genre filter"),
    decade: Optional[str] = Query(None, description="Decade/era filter"),
    sort_by: str = Query("artist", description="Sort field"),
    sort_order: str = Query("asc", description="Sort direction"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100)
):
    """Get paginated library artists with album and track counts."""
    dec_int = None
    if decade and str(decade).strip():
        m = re.search(r'\d{4}', str(decade))
        if m:
            dec_int = int(m.group(0))
    return service.get_library_artists(
        query=query or "",
        genre=genre or "",
        decade=dec_int,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        limit=limit
    )

@app.get("/api/library/artist-albums")
async def get_library_artist_albums_endpoint(artist: str = Query(...)):
    """Get all library albums for a specific artist."""
    return service.get_library_artist_albums(artist_name=artist)

@app.get("/api/library/album-tracks")
async def get_library_album_tracks_endpoint(album_id: int = Query(...)):
    """Get all library tracks for a specific album."""
    return service.get_library_album_tracks(album_id=album_id)

class ConsolidateAlbumsRequest(BaseModel):
    artist: Optional[str] = None
    group_bases: Optional[List[str]] = None
    exclude_track_ids: Optional[List[int]] = None

@app.get("/api/library/albums/consolidate/analyze")
async def analyze_album_consolidation_endpoint(artist: Optional[str] = Query(None, description="Optional artist name to filter analysis")):
    """Analyze album edition variants to identify duplicate tracks and consolidation plan."""
    return service.analyze_album_consolidation(artist_name=artist)

@app.post("/api/library/albums/consolidate/execute")
async def execute_album_consolidation_endpoint(req: ConsolidateAlbumsRequest):
    """Execute album consolidation: delete duplicate files and merge unique tracks into primary album."""
    res = service.execute_album_consolidation(
        artist_name=req.artist,
        group_bases=req.group_bases,
        exclude_track_ids=req.exclude_track_ids
    )
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error", "Consolidation failed"))
    return res

@app.get("/api/library/artist-art")
async def get_library_artist_art_endpoint(artist: str = Query(...)):
    """Serve high-resolution artist portrait cover image with caching."""
    art_path = service.get_library_artist_art_path(artist)
    if not art_path or not os.path.exists(art_path):
        raise HTTPException(status_code=404, detail="Artist artwork not found")
    media_type = "image/jpeg" if art_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return FileResponse(
        art_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800"}
    )

@app.get("/api/library/album-art/{album_id}")
async def get_library_album_art_endpoint(album_id: int):
    """Serve cover art image for a library album."""
    art_path = service.get_library_album_art_path(album_id)
    if not art_path or not os.path.exists(art_path):
        raise HTTPException(status_code=404, detail="Album artwork not found")
    media_type = "image/jpeg" if art_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return FileResponse(art_path, media_type=media_type)

@app.get("/api/library/tracks")
async def get_library_tracks(
    search: str = Query("", description="Search term for title, artist, album"),
    query: Optional[str] = Query(None, description="Alias for search"),
    genre: str = Query("", description="Filter by genre"),
    decade: Optional[str] = Query(None, description="Filter by decade (e.g. 1980 or 1980s)"),
    sort_by: str = Query("artist", description="Sort field"),
    sort_order: str = Query("asc", description="Sort direction (asc/desc)"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100)
):
    """Paginated search across entire library with multi-filtering."""
    term = (query if query is not None else search) or ""
    parsed_decade = None
    if decade:
        m = re.search(r'\d{4}', str(decade))
        if m:
            parsed_decade = int(m.group(0))
    return service.search_library_tracks(
        query=term,
        genre=genre,
        decade=parsed_decade,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        limit=limit
    )

@app.post("/api/library/delete-impact")
async def get_library_delete_impact(req: DeleteImpactRequest):
    """Calculate the deletion impact (tracks, albums, bytes) before permanent deletion."""
    impact = service.get_deletion_impact(
        target_type=req.target_type,
        target_id=req.target_id,
        artist_name=req.artist_name,
        album_id=req.album_id,
        song_id=req.song_id
    )
    if not impact.get("success"):
        raise HTTPException(status_code=400, detail=impact.get("error", "Error calculating deletion impact"))
    return impact

@app.post("/api/library/delete")
async def delete_library_items_endpoint(req: DeleteItemsRequest):
    """Permanently delete confirmed tracks and clean up parent album/artist folders & DB rows."""
    if service.task_progress.get("status") == "running":
        raise HTTPException(status_code=409, detail="A library task is currently running. Please wait for it to complete.")
    result = await service.delete_library_items(track_ids=req.track_ids, delete_files=req.delete_files)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Error deleting items"))
    return result


# -------------------------------------------------------------
# ARTIST DISCOGRAPHY & ALBUM DOWNLOAD ENDPOINTS
# -------------------------------------------------------------
class BatchAlbumsRequest(BaseModel):
    artist: str
    albums: List[Dict[str, Any]]
    auto_import: bool = True
    auto_complete_album: bool = True

@app.get("/api/download/artist-check")
async def check_artist_endpoint(query: str = Query(..., description="Artist name or search term")):
    """Check if query matches an artist (exact vs partial match with albums)."""
    return service.check_artist_and_discography(query)

@app.get("/api/download/artist-albums")
async def get_artist_albums_endpoint(artist_id: int = Query(...), artist_name: str = Query(...)):
    """Get albums for a selected artist ID with library presence stats."""
    albums = service.get_artist_albums(artist_id, artist_name)
    lib_stats = service.get_artist_library_stats(artist_name)
    return {
        "artist": {
            "id": artist_id,
            "name": artist_name,
            "library_stats": lib_stats
        },
        "albums": albums
    }

@app.get("/api/download/album-tracks")
async def get_album_tracks_endpoint(album_id: int = Query(...), artist_name: Optional[str] = Query(None)):
    """Get all tracks for an album ID with preview URLs, durations, and library ownership status."""
    return service.get_album_tracks(album_id, artist_name)

@app.post("/api/audio/preview/cleanup")
async def cleanup_preview_endpoint(ttl_hours: int = Query(24)):
    """Trigger manual cleanup of expired audio preview files."""
    removed = service.cleanup_expired_previews(ttl_seconds=ttl_hours * 3600)
    return {"status": "ok", "removed_files": removed, "ttl_hours": ttl_hours}

@app.post("/api/download/batch-albums")
async def download_batch_albums_endpoint(req: BatchAlbumsRequest, bg: BackgroundTasks):
    """Queue sequential download of multiple selected albums in background."""
    if service.task_progress["status"] == "running":
        raise HTTPException(status_code=409, detail="A download task is already in progress.")
    service._abort_requested = False
    bg.add_task(service.download_batch_albums, req.artist, req.albums, req.auto_import, req.auto_complete_album)
    return {"status": "queued", "count": len(req.albums), "artist": req.artist}

# Prevent Browser Caching of Static UI Assets
@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Mount Static Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return Response(
                content=f.read(),
                media_type="text/html",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    return {"message": "Music Manager API is active."}
