import os
import re
import json
import time
import random
import zipfile
import tempfile
import asyncio
import logging
import sqlite3
import math
import hashlib
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import difflib
from collections import defaultdict, Counter
from typing import AsyncGenerator, List, Dict, Any, Optional, Tuple, Union, Set

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

logger = logging.getLogger("music_manager")

def normalize_ollama_host(host_str: str) -> str:
    """Normalize user-entered host string to http://<ip_or_host>:<port>."""
    if not host_str:
        return ""
    h = host_str.strip().rstrip("/")
    if not h.startswith("http://") and not h.startswith("https://"):
        h = f"http://{h}"
    parts = h.split("://", 1)
    proto, rest = parts[0], parts[1]
    if ":" not in rest.split("/")[0]:
        h = f"{proto}://{rest}:11434"
    return h


def clean_search_query(query: str) -> str:
    """Clean redundant remaster/edition brackets and tags from query for search engines."""
    if not query or query.startswith("http://") or query.startswith("https://") or query.startswith("spotify:"):
        return query
    
    q = query.strip()
    # Remove bracketed tags like [2018 Remaster], [Deluxe Edition], [Bonus Track], [Live]
    q = re.sub(r'\[\s*(?:[0-9]{4}\s+)?(?:Remaster(?:ed)?|Deluxe|Bonus|Live|Mono|Stereo|Anniversary|Explicit|Audio|Official|Video|HQ|HD).*?\]', '', q, flags=re.IGNORECASE)
    # Remove generic trailing brackets like [2018 Remaster]
    q = re.sub(r'\[.*?\]', '', q)
    
    # Remove parenthetical remaster tags like (2018 Remaster), (2011 - Remaster), (Remastered 2013), (Deluxe Edition)
    q = re.sub(r'\(\s*(?:[0-9]{4}\s*[-–]?\s*)?Remaster(?:ed)?(?:\s*[-–]?\s*[0-9]{4})?\s*\)', '', q, flags=re.IGNORECASE)
    q = re.sub(r'\(\s*Deluxe(?:\s+Edition)?\s*\)', '', q, flags=re.IGNORECASE)
    q = re.sub(r'\(\s*Bonus\s+Track\s*\)', '', q, flags=re.IGNORECASE)
    
    # Remove semicolon or hyphen remasters like '; 2013 Remaster' or '- 2013 Remaster'
    q = re.sub(r'[;\-]\s*[0-9]{4}\s+Remaster(?:ed)?', '', q, flags=re.IGNORECASE)
    
    # Clean redundant whitespace
    q = re.sub(r'\s+', ' ', q).strip()
    return q

def simplify_search_query(query: str, attempt: int = 2) -> str:
    """Further simplify a query if initial exact search failed."""
    q = clean_search_query(query)
    # If query has long parentheticals with dates or locations, e.g. (Live at ... 12/31/1999)
    if re.search(r'\(.*Live.*\)', q, flags=re.IGNORECASE):
        m = re.search(r'Live\s+at\s+([^,)]+)', q, flags=re.IGNORECASE)
        if m:
            venue_or_event = m.group(1).strip()
            q = re.sub(r'\(.*?\)', f'Live at {venue_or_event}', q)
        else:
            q = re.sub(r'\(.*?\)', 'Live', q)
    else:
        # Strip any other parenthetical
        q = re.sub(r'\(.*?\)', '', q)

    q = re.sub(r'\s+', ' ', q).strip()

    # On attempt 2+, remove hyphen separators (e.g. 'TOOL - The Grudge' -> 'TOOL The Grudge')
    # Because some search engines treat ' - ' as negation (excluding the title!)
    if attempt >= 2 and " - " in q:
        q = q.replace(" - ", " ")

    # On attempt 3+, title-case (e.g. 'TOOL The Grudge' -> 'Tool The Grudge')
    if attempt >= 3:
        q = q.title()

    q = re.sub(r'\s+', ' ', q).strip()
    return q

def normalize_music_title(title: str) -> str:
    """Normalize track title for reliable library matching."""
    if not title:
        return ""
    s = title.strip()
    # Strip remasters, live, deluxe, anniversary, radio edit, etc. with dash or in brackets/parentheses
    s = re.sub(r'(\s*[-–—]\s*(?:digital\s*)?(?:[0-9]{4}\s*)?remaster(?:ed)?(?:\s*version)?|\s*[\(\[][^)]*remaster[^)]*[\)\]]|\s*[\(\[][^)]*deluxe[^)]*[\)\]]|\s*[\(\[][^)]*expanded[^)]*[\)\]]|\s*[\(\[][^)]*anniversary[^)]*[\)\]]|\s*[\(\[][^)]*single[^)]*[\)\]]|\s*[\(\[][^)]*version[^)]*[\)\]]|\s*[\(\[][^)]*edit[^)]*[\)\]])', '', s, flags=re.IGNORECASE)
    # Remove non-alphanumeric characters and lowercase
    s = re.sub(r'[^a-zA-Z0-9\s]', '', s.lower())
    return re.sub(r'\s+', ' ', s).strip()

def normalize_album_name(album: str) -> str:
    """Normalize album name for reliable discography and completion matching."""
    if not album:
        return ""
    s = album.strip()
    s = re.sub(r'(\s*[-–—]\s*(?:digital\s*)?(?:[0-9]{4}\s*)?remaster(?:ed)?(?:\s*version)?|\s*[-–—]\s*Single|\s*[-–—]\s*EP|\s*[\(\[][^)]*remaster[^)]*[\)\]]|\s*[\(\[][^)]*deluxe[^)]*[\)\]]|\s*[\(\[][^)]*expanded[^)]*[\)\]]|\s*[\(\[][^)]*anniversary[^)]*[\)\]]|\s*[\(\[][^)]*single[^)]*[\)\]]|\s*[\(\[][^)]*ep[^)]*[\)\]]|\s*[\(\[][^)]*edition[^)]*[\)\]])', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[^a-zA-Z0-9\s]', '', s.lower())
    return re.sub(r'\s+', ' ', s).strip()

class MusicManagerService:
    def __init__(self):
        # Base storage directory support (single declaration point for entire platform)
        self.storage_dir = os.environ.get("STORAGE_DIR")
        if self.storage_dir:
            default_music = os.path.join(self.storage_dir, "music")
            default_new = os.path.join(self.storage_dir, "music_new")
            default_beets = os.path.join(self.storage_dir, "config", "beets")
            default_preview = os.path.join(self.storage_dir, ".music_preview")

            custom_music = os.environ.get("MUSIC_DIR")
            self.music_dir = custom_music if (custom_music and custom_music != "/music") else default_music

            custom_new = os.environ.get("NEW_MUSIC_DIR")
            self.new_music_dir = custom_new if (custom_new and custom_new != "/music_new") else default_new

            custom_beets = os.environ.get("BEETSDIR")
            self.beets_dir = custom_beets if (custom_beets and custom_beets != "/config/beets") else default_beets

            custom_preview = os.environ.get("PREVIEW_DIR")
            self.preview_dir = custom_preview if (custom_preview and custom_preview != "/.music_preview") else default_preview
        else:
            self.music_dir = os.environ.get("MUSIC_DIR", "/music")
            self.new_music_dir = os.environ.get("NEW_MUSIC_DIR", "/music_new")
            self.beets_dir = os.environ.get("BEETSDIR", "/config/beets")
            self.preview_dir = os.environ.get("PREVIEW_DIR", "/.music_preview")

        os.environ["BEETSDIR"] = self.beets_dir
        try:
            os.makedirs(self.preview_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create preview dir {self.preview_dir}: {e}")
        self._external_preview_cache: Dict[str, Dict[str, Any]] = {}
        self.ollama_host = normalize_ollama_host(os.environ.get("OLLAMA_HOST", "http://192.168.178.31:11434"))
        self.ollama_default_model = os.environ.get("OLLAMA_MODEL", "qwen3.5:9b")

        self.current_task: Optional[str] = None
        self.task_progress: Dict[str, Any] = {"status": "idle", "action": None, "current": 0, "total": 0, "message": ""}
        self.log_subscribers: List[asyncio.Queue] = []
        self._abort_requested = False
        self._active_process: Optional[asyncio.subprocess.Process] = None

        # Missing tracks cache
        self.missing_cache_file = os.path.join(self.beets_dir, "missing_cache.json")
        self._last_missing_tracks: Optional[List[Dict[str, Any]]] = None
        if os.path.exists(self.missing_cache_file):
            try:
                with open(self.missing_cache_file, "r", encoding="utf-8") as f:
                    self._last_missing_tracks = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load missing cache: {e}")
                self._last_missing_tracks = None

        # Disk files count cache (TTL 120s)
        self._disk_files_cache: Optional[int] = None
        self._disk_files_cache_time: float = 0.0

        # Ollama servers configuration & persistence
        self.ollama_servers_file = os.path.join(self.beets_dir, "ollama_servers.json")
        self.ollama_servers: List[str] = []
        self._load_ollama_config()

        # Ensure directories exist
        os.makedirs(self.music_dir, exist_ok=True)
        os.makedirs(self.new_music_dir, exist_ok=True)
        os.makedirs(self.beets_dir, exist_ok=True)
        self._ensure_beets_config()

        # Set writable config and cache directory for SpotDL, Spotipy, and yt-dlp in non-root containers
        self.config_dir = os.environ.get("CONFIG_DIR") or (os.path.join(self.storage_dir, "config") if self.storage_dir else os.path.dirname(self.beets_dir) or "/config")
        os.environ["HOME"] = self.config_dir
        os.environ["XDG_CONFIG_HOME"] = self.config_dir
        os.environ["XDG_CACHE_HOME"] = os.path.join(self.config_dir, ".cache")
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            os.makedirs(os.path.join(self.config_dir, "spotdl"), exist_ok=True)
            os.makedirs(os.path.join(self.config_dir, ".cache"), exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create config/spotdl cache dirs: {e}")

        # Defensively ensure spotapi, SpotipyFree, and spotdl are patched and resilient
        self._ensure_packages_patched()

    def get_storage_info(self) -> Dict[str, Any]:
        """Return configured base storage paths, subfolders, and database health."""
        db_file = os.path.join(self.beets_dir, "library.db")
        return {
            "base_storage": self.storage_dir or "discrete",
            "music_dir": self.music_dir,
            "new_music_dir": self.new_music_dir,
            "beets_dir": self.beets_dir,
            "preview_dir": self.preview_dir,
            "library_db_exists": os.path.exists(db_file),
            "library_db_path": db_file
        }

    def _ensure_beets_config(self):
        """Ensure Beets configuration file exists; create default config if missing on first run."""
        cfg_file = os.path.join(self.beets_dir, "config.yaml")
        if os.path.exists(cfg_file):
            return

        bundled = "/app/default_beets_config.yaml"
        if os.path.exists(bundled):
            try:
                import shutil
                shutil.copy2(bundled, cfg_file)
                logger.info("Provisioned default Beets config from bundled template.")
                return
            except Exception as e:
                logger.warning(f"Could not copy bundled beets config: {e}")

        db_path = os.path.join(self.beets_dir, "library.db")
        default_yaml = """directory: __MUSIC_DIR__
library: __LIBRARY_DB__
asciify_paths: yes
ignore:
    - '.*'
    - '*~'
    - 'System Volume Information'
    - 'lost+found'
    - '.syncthing*'
    - '*.tmp'
    - '*.part'
    - '*.crdownload'
    - '*.sync-conflict-*'
    - '.stfolder'
    - '.stversions'
    - '.stignore'
ignore_hidden: yes

plugins: ftintitle inline missing duplicates permissions fetchart embedart musicbrainz lastgenre

permissions:
    file: 664
    dir: 775

fetchart:
    auto: yes
    minwidth: 300
    maxwidth: 1200
    enforce_ratio: 0.5%
    cautious: no
    cover_names: cover front art album
    sources: [filesystem, coverart, itunes, amazon, albumart]

embedart:
    auto: yes
    remove_art_file: no
    maxwidth: 1200

duplicates:
    album: yes
    path: yes
    tiebreak:
        items: [bitrate, format]
    strict: no

import:
    move: yes
    write: yes
    resume: yes
    quiet_fallback: asis
    duplicate_action: merge
    group_albums: yes
    incremental: yes
    duplicate_keys:
        album: albumartist album
        item: artist title

missing:
    count: no
    format: $albumartist - $title

item_fields:
    custom_artist: |
        import re
        art = ""
        try:
            if albumartist: art = albumartist
        except NameError: pass
        if not art:
            try:
                if artist: art = artist
            except NameError: pass
        if not art:
            art = "Unknown Artist"
        art = re.split(r'[\\s(]+(?:[Ff]eat\\.?|[Ff]t\\.?|[Ff]eaturing)\\s+', art)[0].strip()
        art = re.split(r'\\s+(?:&|,|x|X|×)\\s+', art)[0].strip()
        art = art.replace("’", "'").replace("‘", "'").replace('“', '"').replace('”', '"').replace('‐', '-').replace('–', '-').replace('—', '-')
        art = re.sub(r'\\s+', ' ', art).strip()
        return art

    custom_track_name: |
        import re
        try: d = disc
        except NameError: d = 0
        try: td = totaldiscs
        except NameError: td = 1
        disc_str = f"{d}-" if int(td) > 1 else ""
        try: t = track
        except NameError: t = 0
        track_str = f"{t:02d} " if int(t) > 0 else ""
        tit = "Unknown Title"
        try:
            if title: tit = title
        except NameError: pass
        tit = tit.replace("’", "'").replace("‘", "'").replace('“', '"').replace('”', '"').replace('‐', '-').replace('–', '-').replace('—', '-')
        tit = re.sub(r'\\s+', ' ', tit).strip()
        return f"{disc_str}{track_str}{tit}"

album_fields:
    custom_artist: |
        import re
        art = ""
        try:
            if albumartist: art = albumartist
        except NameError: pass
        if not art:
            try:
                if artist: art = artist
            except NameError: pass
        if not art:
            art = "Unknown Artist"
        art = re.split(r'[\\s(]+(?:[Ff]eat\\.?|[Ff]t\\.?|[Ff]eaturing)\\s+', art)[0].strip()
        art = re.split(r'\\s+(?:&|,|x|X|×)\\s+', art)[0].strip()
        art = art.replace("’", "'").replace("‘", "'").replace('“', '"').replace('”', '"').replace('‐', '-').replace('–', '-').replace('—', '-')
        art = re.sub(r'\\s+', ' ', art).strip()
        return art

    custom_album: |
        import re
        alb = ""
        try:
            if album: alb = album
        except NameError: pass
        if not alb:
            alb = "Non-Album"
        alb = alb.replace("’", "'").replace("‘", "'").replace('“', '"').replace('”', '"').replace('‐', '-').replace('–', '-').replace('—', '-')
        alb = re.sub(r'\\s+', ' ', alb).strip()
        return alb

paths:
    default: $custom_artist/$custom_album/$custom_track_name
    singleton: $custom_artist/Non-Album/$custom_track_name
"""
        default_yaml = default_yaml.replace("__MUSIC_DIR__", self.music_dir).replace("__LIBRARY_DB__", db_path)
        try:
            with open(cfg_file, "w", encoding="utf-8") as f:
                f.write(default_yaml)
            logger.info("Auto-generated default Beets config.yaml in /config/beets/")
        except Exception as e:
            logger.error(f"Failed to auto-generate default Beets config: {e}")

    def _load_ollama_config(self):
        """Load remembered Ollama servers and active server from disk."""
        default_host = normalize_ollama_host(self.ollama_host)
        self.ollama_servers = [default_host]
        if os.path.exists(self.ollama_servers_file):
            try:
                with open(self.ollama_servers_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if cfg.get("active_host"):
                        self.ollama_host = normalize_ollama_host(cfg["active_host"])
                    if cfg.get("servers"):
                        servers = [normalize_ollama_host(s) for s in cfg["servers"] if s]
                        self.ollama_servers = list(dict.fromkeys(servers))
            except Exception as e:
                logger.warning(f"Could not load ollama_servers.json: {e}")
        if self.ollama_host not in self.ollama_servers:
            self.ollama_servers.insert(0, self.ollama_host)

    def _save_ollama_config(self):
        """Save remembered Ollama servers and active server to disk."""
        try:
            cfg = {
                "active_host": self.ollama_host,
                "servers": self.ollama_servers
            }
            with open(self.ollama_servers_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save ollama_servers.json: {e}")

    def _ensure_packages_patched(self):
        """Ensure spotapi, SpotipyFree, and spotdl are patched with timeout and query resilience."""
        try:
            from app.patch_packages import patch_all
            patch_all()
        except Exception as e:
            logger.debug(f"Package patch check skipped: {e}")

    async def broadcast_log(self, text: str):
        """Broadcast log message to all active SSE subscribers."""
        for queue in list(self.log_subscribers):
            try:
                await queue.put(text)
            except Exception:
                pass

    def subscribe_logs(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.log_subscribers.append(q)
        return q

    def unsubscribe_logs(self, q: asyncio.Queue):
        if q in self.log_subscribers:
            self.log_subscribers.remove(q)

    def cleanup_expired_previews(self, ttl_seconds: int = 86400) -> int:
        """Purge audio preview files older than TTL (default 24h) from /.music_preview."""
        if not os.path.exists(self.preview_dir):
            return 0

        audio_exts = (".mp3", ".m4a", ".aac", ".ogg", ".wav", ".flac")
        now = time.time()
        removed_count = 0

        try:
            for entry in os.listdir(self.preview_dir):
                full_path = os.path.join(self.preview_dir, entry)
                # Ensure we only check files, leaving subdirectories (like artists/) untouched
                if os.path.isfile(full_path) and entry.lower().endswith(audio_exts):
                    try:
                        mtime = os.path.getmtime(full_path)
                        if (now - mtime) > ttl_seconds:
                            os.remove(full_path)
                            removed_count += 1
                    except Exception as fe:
                        logger.warning(f"Could not remove expired preview {entry}: {fe}")

            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} expired audio preview file(s) from {self.preview_dir}")
        except Exception as e:
            logger.error(f"Error during preview cleanup in {self.preview_dir}: {e}")

        return removed_count

    def get_artist_library_stats(self, artist_name: str) -> Dict[str, Any]:
        """Query Beets library database for artist's owned tracks and album completion stats."""
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path) or not artist_name:
            return {"total_tracks": 0, "complete_albums": 0, "albums_map": {}}

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                SELECT items.album, items.title, items.track, items.tracktotal
                FROM items
                WHERE LOWER(items.artist) = LOWER(?) OR LOWER(items.albumartist) = LOWER(?)
            """, (artist_name.strip(), artist_name.strip()))
            rows = c.fetchall()
            conn.close()

            total_tracks = len(rows)
            albums_map: Dict[str, Dict[str, Any]] = {}
            for alb, tit, trk, total in rows:
                c_alb = normalize_album_name(alb)
                c_tit = normalize_music_title(tit)
                if c_alb not in albums_map:
                    albums_map[c_alb] = {"songs": set(), "tracktotal": total or 0, "raw_album": alb}
                albums_map[c_alb]["songs"].add(c_tit)
                if total and total > albums_map[c_alb]["tracktotal"]:
                    albums_map[c_alb]["tracktotal"] = total

            complete_count = 0
            for calb, info in albums_map.items():
                song_count = len(info["songs"])
                tot = info["tracktotal"]
                is_comp = (tot > 0 and song_count >= tot)
                info["is_complete"] = is_comp
                info["in_library_count"] = song_count
                if is_comp:
                    complete_count += 1

            return {
                "total_tracks": total_tracks,
                "complete_albums": complete_count,
                "albums_map": albums_map
            }
        except Exception as e:
            logger.error(f"Error getting library stats for {artist_name}: {e}")
            return {"total_tracks": 0, "complete_albums": 0, "albums_map": {}}

    def is_song_in_library(self, artist: str, title: str, album: Optional[str] = None) -> bool:
        """Check if a specific song title by an artist already exists in the Beets library.
        If album is provided, checks if the song exists specifically within that album (or equivalent normalized album).
        If album is None, checks across the entire library.
        """
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path) or not artist or not title:
            return False

        norm_title = normalize_music_title(title)
        if not norm_title:
            return False

        norm_album = normalize_album_name(album) if album else None

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            if norm_album:
                c.execute("""
                    SELECT items.title, items.album
                    FROM items
                    WHERE LOWER(items.artist) = LOWER(?) OR LOWER(items.albumartist) = LOWER(?)
                """, (artist.strip(), artist.strip()))
                rows = c.fetchall()
                conn.close()

                for (t, a) in rows:
                    if normalize_music_title(t) == norm_title and normalize_album_name(a or "") == norm_album:
                        return True
                return False
            else:
                c.execute("""
                    SELECT items.title
                    FROM items
                    WHERE LOWER(items.artist) = LOWER(?) OR LOWER(items.albumartist) = LOWER(?)
                """, (artist.strip(), artist.strip()))
                rows = c.fetchall()
                conn.close()

                for (t,) in rows:
                    if normalize_music_title(t) == norm_title:
                        return True
        except Exception as e:
            logger.error(f"Error checking if song is in library '{artist} - {title}': {e}")
        return False

    async def _run_command(self, cmd: List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None, timeout: Optional[int] = 600) -> int:
        """Run an async subprocess and stream stdout and stderr line-by-line with timeout safety and abort handling."""
        if self._abort_requested:
            await self.broadcast_log(f"[ABORT] Skipping command execution due to abort request: {' '.join(cmd)}\n")
            return 1

        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        run_env["BEETSDIR"] = self.beets_dir
        run_env["PYTHONUNBUFFERED"] = "1"
        run_env["HOME"] = self.config_dir
        run_env["XDG_CONFIG_HOME"] = self.config_dir
        run_env["XDG_CACHE_HOME"] = os.path.join(self.config_dir, ".cache")

        await self.broadcast_log(f"\n[RUNNING] {' '.join(cmd)}\n")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd or self.new_music_dir,
                env=run_env
            )
            self._active_process = proc
        except Exception as e:
            await self.broadcast_log(f"[EXEC ERROR] Failed to start process: {e}\n")
            return 1

        async def _read_stream():
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                await self.broadcast_log(text)

        try:
            if timeout:
                await asyncio.wait_for(_read_stream(), timeout=timeout)
                await asyncio.wait_for(proc.wait(), timeout=10)
            else:
                await _read_stream()
                await proc.wait()
            return proc.returncode or 0
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            await self.broadcast_log(f"\n[TIMEOUT] Process timed out after {timeout} seconds: {' '.join(cmd)}\n")
            return 1
        except asyncio.CancelledError:
            try:
                proc.kill()
            except Exception:
                pass
            await self.broadcast_log(f"\n[ABORT] Process terminated due to cancellation request: {' '.join(cmd)}\n")
            return 1
        except Exception as e:
            await self.broadcast_log(f"\n[ERROR] Command stream error: {e}\n")
            return 1
        finally:
            self._active_process = None

    async def abort_current_task(self) -> Dict[str, Any]:
        """Stop and abort any currently running operation, subprocess, or background task."""
        self._abort_requested = True
        killed_proc = False

        if self._active_process:
            try:
                self._active_process.kill()
                killed_proc = True
                logger.info("Active subprocess terminated by abort request.")
            except Exception as e:
                logger.warning(f"Failed to kill active subprocess: {e}")

        await self.broadcast_log("\n================================================\n")
        await self.broadcast_log("[STOP/ABORT] User triggered operation abort!\n")
        await self.broadcast_log("Terminating active processes and halting task queue...\n")
        await self.broadcast_log("================================================\n")

        self.task_progress = {
            "status": "idle",
            "action": None,
            "current": 0,
            "total": 0,
            "message": "Operation stopped by user"
        }
        self.current_task = None

        return {
            "success": True,
            "status": "aborted",
            "message": "Task and active processes stopped successfully.",
            "killed_process": killed_proc
        }

    async def _ytdlp_fallback(self, query: str) -> bool:
        """Direct yt-dlp YouTube search fallback when SpotDL fails."""
        if self._abort_requested:
            return False

        is_url = query.strip().startswith("http://") or query.strip().startswith("https://")
        clean_target = clean_search_query(query)
        target = query.strip() if is_url else f"ytsearch1:{clean_target}"
        log_target = query if is_url else f"YouTube search for '{clean_target}'"
        await self.broadcast_log(f"\n[YT-DLP FALLBACK] Downloading via yt-dlp: {log_target}\n")
        cmd = [
            "yt-dlp", "-x",
            "--audio-format", "mp3",
            "--embed-metadata",
            "--no-playlist",
            "-o", f"{self.new_music_dir}/%(title)s.%(ext)s",
            target
        ]
        code = await self._run_command(cmd, cwd=self.new_music_dir, timeout=300)
        if code == 0:
            await self.broadcast_log(f"[OK] yt-dlp successfully downloaded: {clean_target}\n")
            return True
        else:
            if not self._abort_requested:
                await self.broadcast_log(f"[FAIL] yt-dlp search also failed for: {clean_target}\n")
            return False

    async def _download_query(self, query: str, max_retries: int = 2, check_library_duplicate: bool = True, target_album: Optional[str] = None) -> Tuple[bool, bool]:
        """Download query using spotdl with audio provider fallbacks, progressive query simplification, then yt-dlp fallback.
        Returns: (downloaded: bool, skipped: bool)
        """
        if self._abort_requested:
            return False, False

        is_url = query.strip().startswith("http://") or query.strip().startswith("https://")

        # Smart skip if song is already in library (Artist - Title)
        if check_library_duplicate and not is_url and " - " in query:
            parts = query.split(" - ", 1)
            art, tit = parts[0].strip(), parts[1].strip()
            if self.is_song_in_library(art, tit, album=target_album):
                target_str = f" in '{target_album}'" if target_album else ""
                await self.broadcast_log(f"[SKIP] '{art} - {tit}' is already in your library{target_str}. Skipping download.\n")
                return False, True

        current_query = query if is_url else clean_search_query(query)

        success = False
        for attempt in range(1, max_retries + 1):
            if self._abort_requested:
                return False, False

            if attempt > 1 and not is_url:
                simplified = simplify_search_query(query, attempt=attempt)
                if simplified != current_query:
                    await self.broadcast_log(f"--- Download Attempt {attempt} of {max_retries} with simplified query: '{simplified}' ---\n")
                    current_query = simplified
                else:
                    await self.broadcast_log(f"--- Download Attempt {attempt} of {max_retries} for: '{current_query}' ---\n")

            spotdl_cmd = ["spotdl", "download", current_query, "--audio", "youtube-music", "youtube", "--dont-filter-results"]

            code = await self._run_command(spotdl_cmd, cwd=self.new_music_dir, timeout=300)
            if self._abort_requested:
                return False, False

            if code == 0:
                success = True
                await self.broadcast_log(f"[OK] Successfully downloaded: {current_query}\n")
                break
            else:
                if attempt < max_retries:
                    if self._abort_requested:
                        return False, False
                    await self.broadcast_log(f"[WARN] SpotDL attempt {attempt} failed. Retrying in 2 seconds...\n")
                    await asyncio.sleep(2)

        # Fallback to direct yt-dlp search if SpotDL failed on text queries
        if not success and not is_url and not self._abort_requested:
            success = await self._ytdlp_fallback(current_query)

        # If target_album was provided, ensure any newly downloaded audio files in staging are tagged with target_album
        if success and target_album:
            try:
                audio_exts = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus", ".aac"}
                for root, dirs, files in os.walk(self.new_music_dir):
                    dirs[:] = [d for d in dirs if not d.startswith(".st") and not d.startswith(".syncthing") and d not in {".stfolder", ".stversions"}]
                    for f in files:
                        if not self.is_ignored_staging_file(f) and os.path.splitext(f)[1].lower() in audio_exts:
                            fp = os.path.join(root, f)
                            try:
                                import mutagen
                                mf = mutagen.File(fp, easy=True)
                                if mf is not None:
                                    mf["album"] = target_album
                                    mf.save()
                                    await self.broadcast_log(f"[METADATA] Set album tag of '{f}' to target album: '{target_album}'\n")
                            except Exception as tag_err:
                                logger.warning(f"Could not retag album on {f}: {tag_err}")
            except Exception as e:
                logger.warning(f"Error tagging staging files with target_album: {e}")

        return success, False

    async def download_track_or_url(self, query: str, max_retries: int = 3, auto_import: bool = False, auto_complete_album: bool = False, target_album: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Download a query or Spotify/YouTube URL using spotdl with retries and timeout safety."""
        if not query or not query.strip():
            return {"success": False, "error": "Query cannot be empty"}

        self._abort_requested = False
        start_time = time.time()
        self.task_progress = {
            "status": "running",
            "action": f"Downloading: {query}",
            "current": 0,
            "total": 1,
            "message": f"Downloading '{query}'..."
        }

        downloaded = False
        skipped = False
        try:
            downloaded, skipped = await self._download_query(
                query,
                max_retries=max_retries,
                check_library_duplicate=(not force),
                target_album=target_album
            )

            if downloaded and auto_import and not self._abort_requested:
                await self.broadcast_log("\n[AUTO-IMPORT] Triggering library import after download...\n")
                await self.import_library()

                if auto_complete_album and not self._abort_requested:
                    await self.auto_complete_recent_albums(since_timestamp=start_time)
            elif skipped:
                await self.broadcast_log("\n[INFO] Track already exists in library; auto-import skipped.\n")
        except Exception as e:
            logger.error(f"Error in download_track_or_url: {e}", exc_info=True)
            await self.broadcast_log(f"\n[ERROR] Unhandled error during download: {e}\n")
        finally:
            if not self._abort_requested:
                self.task_progress = {
                    "status": "idle",
                    "action": None,
                    "current": 1 if (downloaded or skipped) else 0,
                    "total": 1,
                    "message": "Completed" if (downloaded or skipped) else "Failed"
                }

        return {"success": (downloaded or skipped), "downloaded": downloaded, "skipped": skipped, "query": query, "aborted": self._abort_requested}

    async def auto_complete_recent_albums(self, since_timestamp: float) -> Dict[str, Any]:
        """Check newly imported albums for missing tracks via MusicBrainz and automatically download them."""
        await self.broadcast_log("\n[ALBUM AUTO-COMPLETE] Checking if newly imported songs belong to incomplete albums...\n")

        from beets import metadata_plugins
        from beets.plugins import load_plugins
        from beets.library import Library

        try:
            load_plugins()
            lib = Library(os.path.join(self.beets_dir, "library.db"))
        except Exception as e:
            await self.broadcast_log(f"[ALBUM AUTO-COMPLETE ERROR] Could not open Beets library: {e}\n")
            return {"success": False, "error": str(e)}

        # Fast SQL check: find albums that had items added in this session
        db_path = os.path.join(self.beets_dir, "library.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                SELECT DISTINCT a.id
                FROM albums a
                JOIN items i ON i.album_id = a.id
                WHERE i.added >= ?
            """, (since_timestamp - 15,))
            recent_album_ids = [r[0] for r in c.fetchall()]
            conn.close()
        except Exception as e:
            logger.error(f"Error checking recent album ids: {e}")
            recent_album_ids = []

        if not recent_album_ids:
            await self.broadcast_log("[ALBUM AUTO-COMPLETE] No recent albums found to evaluate.\n")
            return {"success": True, "downloaded": 0}

        incomplete_albums = []
        for aid in recent_album_ids:
            try:
                alb = lib.get_album(aid)
                if alb and alb.albumtotal and len(alb.items()) < alb.albumtotal:
                    incomplete_albums.append(alb)
            except Exception:
                pass

        if not incomplete_albums:
            await self.broadcast_log("[ALBUM AUTO-COMPLETE] All newly cataloged albums are already complete! No missing tracks.\n")
            return {"success": True, "downloaded": 0}

        await self.broadcast_log(f"[ALBUM AUTO-COMPLETE] Found {len(incomplete_albums)} incomplete album(s) from recent imports. Fetching tracklists...\n")

        all_missing_tracks = []
        for album in incomplete_albums:
            current_count = len(album.items())
            total_count = album.albumtotal
            await self.broadcast_log(f"   -> Album '{album.album}' by '{album.albumartist}' has {current_count}/{total_count} tracks cataloged.\n")

            if album.mb_albumid:
                try:
                    album_info = metadata_plugins.album_for_id(album.mb_albumid, "musicbrainz")
                    if album_info:
                        existing_titles = {normalize_music_title(i.title) for i in album.items() if i.title}
                        missing = []
                        for track in album_info.tracks:
                            if normalize_music_title(track.title) not in existing_titles:
                                missing.append(f"{album.albumartist} - {track.title}")

                        if missing:
                            await self.broadcast_log(f"      Missing {len(missing)} track(s): {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}\n")
                            all_missing_tracks.extend(missing)
                except Exception as e:
                    await self.broadcast_log(f"      [WARN] Could not fetch tracklist for '{album.album}': {e}\n")

        if not all_missing_tracks:
            await self.broadcast_log("[ALBUM AUTO-COMPLETE] No missing tracks identified to download.\n")
            return {"success": True, "downloaded": 0}

        unique_missing = list(dict.fromkeys(all_missing_tracks))
        await self.broadcast_log(f"\n[ALBUM AUTO-COMPLETE] Starting automated download of {len(unique_missing)} missing album track(s)...\n")

        res = await self.download_batch_tracks(unique_missing, label="Missing Album Tracks", auto_import=True, auto_complete_album=False, check_library_duplicate=False)
        return res

    def get_cached_missing_tracks(self) -> List[Dict[str, Any]]:
        """Return cached missing tracks from memory or disk without re-scanning."""
        if self._last_missing_tracks is not None:
            return self._last_missing_tracks
        if os.path.exists(self.missing_cache_file):
            try:
                with open(self.missing_cache_file, "r", encoding="utf-8") as f:
                    self._last_missing_tracks = json.load(f)
                    return self._last_missing_tracks or []
            except Exception:
                pass
        return []

    async def get_missing_tracks(self, max_albums: int = 40, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Find missing album tracks using local SQLite and MusicBrainz diffs.
        Caches results to disk for instant subsequent retrieval.
        """
        if not force_refresh and self._last_missing_tracks is not None:
            return self._last_missing_tracks

        await self.broadcast_log(f"\n[MISSING SCAN] Querying Beets library for incomplete studio albums (depth: top {max_albums} albums)...\n")

        db_path = os.path.join(self.beets_dir, "library.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                SELECT sub.album_id, sub.albumartist, sub.album, sub.mb_albumid, sub.expected, sub.have
                FROM (
                    SELECT a.id as album_id, a.albumartist, a.album, a.mb_albumid,
                           max(i.tracktotal) as expected, count(i.id) as have
                    FROM albums a
                    JOIN items i ON i.album_id = a.id
                    WHERE i.tracktotal IS NOT NULL AND i.tracktotal > 0
                    GROUP BY a.id
                ) sub
                WHERE sub.have < sub.expected AND sub.expected <= 30
                ORDER BY (sub.expected - sub.have) ASC
            """)
            incomplete = c.fetchall()
        except Exception as e:
            await self.broadcast_log(f"[MISSING SCAN ERROR] SQLite query failed: {e}\n")
            return []

        if not incomplete:
            conn.close()
            self._last_missing_tracks = []
            return []

        await self.broadcast_log(f"[MISSING SCAN] Found {len(incomplete)} incomplete albums in library. Inspecting tracklists for top {min(len(incomplete), max_albums)}...\n")

        from beets import metadata_plugins
        from beets.plugins import load_plugins
        try:
            load_plugins()
        except Exception:
            pass

        tracks = []
        seen_queries = set()
        albums_to_check = incomplete[:max_albums]
        total_to_check = len(albums_to_check)

        for idx, (album_id, albumartist, album, mb_albumid, expected, have) in enumerate(albums_to_check, 1):
            if mb_albumid:
                try:
                    album_info = metadata_plugins.album_for_id(mb_albumid, "musicbrainz")
                    if album_info:
                        norm_alb = normalize_album_name(album)
                        c.execute("""
                            SELECT i.title, a.album
                            FROM items i
                            JOIN albums a ON a.id = i.album_id
                            WHERE (LOWER(a.albumartist) = LOWER(?) OR LOWER(i.artist) = LOWER(?))
                        """, (albumartist, albumartist))
                        existing_titles = {
                            normalize_music_title(r[0])
                            for r in c.fetchall()
                            if r[0] and normalize_album_name(r[1] or "") == norm_alb
                        }
                        found_for_album = 0
                        for track in album_info.tracks:
                            if normalize_music_title(track.title) not in existing_titles:
                                query = f"{albumartist} - {track.title}"
                                if query not in seen_queries:
                                    seen_queries.add(query)
                                    tracks.append({
                                        "artist": albumartist,
                                        "album": album,
                                        "title": track.title,
                                        "track_num": track.index,
                                        "query": query
                                    })
                                    found_for_album += 1
                        if found_for_album > 0 and idx % 5 == 0:
                            await self.broadcast_log(f"   [{idx}/{total_to_check}] Checked {albumartist} - {album} (found {found_for_album} missing tracks)\n")
                except Exception:
                    pass

        conn.close()

        # Save to memory and disk cache
        self._last_missing_tracks = tracks
        try:
            with open(self.missing_cache_file, "w", encoding="utf-8") as f:
                json.dump(tracks, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not write missing cache to disk: {e}")

        await self.broadcast_log(f"[MISSING SCAN] Complete! Cataloged {len(tracks)} missing tracks across {total_to_check} albums.\n")
        return tracks

    async def download_batch_tracks(self, tracks: List[str], label: str = "Recommendations", auto_import: bool = True, auto_complete_album: bool = False, check_library_duplicate: bool = True) -> Dict[str, Any]:
        """Download a batch of track queries sequentially with progress tracking, abort handling, and auto-import."""
        self._abort_requested = False
        start_time = time.time()
        total = len(tracks)
        if total == 0:
            await self.broadcast_log(f"[INFO] No tracks provided for batch download.\n")
            return {"success": True, "downloaded": 0, "failed": 0, "total": 0}

        self.task_progress = {
            "status": "running",
            "action": f"Downloading {label}",
            "current": 0,
            "total": total,
            "message": f"Starting download of {total} {label}..."
        }

        await self.broadcast_log(f"================================================\n")
        await self.broadcast_log(f"Starting batch download of {total} {label}...\n")
        await self.broadcast_log(f"================================================\n")

        success_count = 0
        fail_count = 0

        try:
            for i, track in enumerate(tracks, 1):
                if self._abort_requested:
                    await self.broadcast_log(f"\n[ABORT] Stopped batch download before item {i}/{total}.\n")
                    break

                self.task_progress["current"] = i
                self.task_progress["message"] = f"Downloading ({i}/{total}): {track}"
                await self.broadcast_log(f"\n[{i}/{total}] Downloading: {track}\n")

                downloaded, skipped = await self._download_query(track, max_retries=2, check_library_duplicate=check_library_duplicate)
                if self._abort_requested:
                    await self.broadcast_log(f"\n[ABORT] Stopped batch download after item {i}/{total}.\n")
                    break

                if downloaded:
                    success_count += 1
                elif skipped:
                    pass
                else:
                    await self.broadcast_log(f"[ERROR] Failed to download: {track}. Skipping to next.\n")
                    fail_count += 1

            if self._abort_requested:
                await self.broadcast_log(f"================================================\n")
                await self.broadcast_log(f"[ABORTED] Batch download cancelled by user.\n")
                await self.broadcast_log(f"Downloaded before abort: {success_count} | Total requested: {total}\n")
                await self.broadcast_log(f"================================================\n")
            else:
                await self.broadcast_log(f"================================================\n")
                await self.broadcast_log(f"[OK] Batch download completed!\n")
                await self.broadcast_log(f"Successfully downloaded: {success_count} | Failed: {fail_count}\n")
                await self.broadcast_log(f"================================================\n")

            if success_count > 0 and auto_import and not self._abort_requested:
                await self.broadcast_log("\n[AUTO-IMPORT] Importing newly downloaded tracks into Beets library...\n")
                await self.import_library()

                if auto_complete_album and not self._abort_requested:
                    await self.auto_complete_recent_albums(since_timestamp=start_time)
        except Exception as e:
            logger.error(f"Error in download_batch_tracks: {e}", exc_info=True)
            await self.broadcast_log(f"\n[ERROR] Unhandled error during batch download: {e}\n")
        finally:
            if not self._abort_requested:
                self.task_progress = {"status": "idle", "action": None, "current": 0, "total": 0, "message": ""}

        return {"success": not self._abort_requested, "downloaded": success_count, "failed": fail_count, "total": total, "aborted": self._abort_requested}

    async def download_missing_tracks(self, tracks: Optional[List[Union[str, Dict[str, Any]]]] = None, auto_import: bool = False) -> Dict[str, Any]:
        """Download missing tracks sequentially with error resilience, abort handling, and cache pruning."""
        self._abort_requested = False
        cached_items = self.get_cached_missing_tracks()

        track_items = []
        if tracks is not None:
            for item in tracks:
                if isinstance(item, dict) and item.get("query"):
                    track_items.append({
                        "query": item["query"],
                        "album": item.get("album"),
                        "artist": item.get("artist"),
                        "title": item.get("title")
                    })
                elif isinstance(item, str) and item.strip():
                    track_items.append({
                        "query": item.strip(),
                        "album": None,
                        "artist": None,
                        "title": None
                    })
        else:
            if not cached_items:
                cached_items = await self.get_missing_tracks()
            for item in (cached_items or []):
                if isinstance(item, dict) and item.get("query"):
                    track_items.append({
                        "query": item["query"],
                        "album": item.get("album"),
                        "artist": item.get("artist"),
                        "title": item.get("title")
                    })

        total = len(track_items)
        if total == 0:
            await self.broadcast_log("[INFO] No missing tracks to download.\n")
            return {"success": True, "downloaded": 0, "failed": 0, "total": 0}

        cache_query_to_album = {}
        if cached_items:
            for c_item in cached_items:
                if isinstance(c_item, dict) and c_item.get("query") and c_item.get("album"):
                    cache_query_to_album[c_item["query"]] = c_item["album"]

        self.task_progress = {
            "status": "running",
            "action": "Downloading Missing Tracks",
            "current": 0,
            "total": total,
            "message": f"Processing {total} missing tracks..."
        }

        await self.broadcast_log(f"================================================\n")
        await self.broadcast_log(f"Found {total} missing tracks. Starting sequential download...\n")
        await self.broadcast_log(f"================================================\n")

        success_count = 0
        fail_count = 0
        downloaded_queries = set()

        try:
            for i, item in enumerate(track_items, 1):
                if self._abort_requested:
                    await self.broadcast_log(f"\n[ABORT] Stopped missing tracks download before item {i}/{total}.\n")
                    break

                track_query = item["query"]
                target_album = item.get("album") or cache_query_to_album.get(track_query)

                self.task_progress["current"] = i
                self.task_progress["message"] = f"Downloading ({i}/{total}): {track_query}"
                target_desc = f" (target album: '{target_album}')" if target_album else ""
                await self.broadcast_log(f"\n[{i}/{total}] Downloading: {track_query}{target_desc}\n")

                downloaded, skipped = await self._download_query(
                    track_query,
                    max_retries=2,
                    check_library_duplicate=True,
                    target_album=target_album
                )
                if self._abort_requested:
                    await self.broadcast_log(f"\n[ABORT] Stopped missing tracks download after item {i}/{total}.\n")
                    break

                if downloaded:
                    success_count += 1
                    downloaded_queries.add(track_query)
                elif skipped:
                    downloaded_queries.add(track_query)
                else:
                    await self.broadcast_log(f"[ERROR] Failed to download: {track_query}. Skipping to next.\n")
                    fail_count += 1

            if self._abort_requested:
                await self.broadcast_log(f"================================================\n")
                await self.broadcast_log(f"[ABORTED] Missing tracks download cancelled by user.\n")
                await self.broadcast_log(f"Downloaded before abort: {success_count} | Total requested: {total}\n")
                await self.broadcast_log(f"================================================\n")
            else:
                await self.broadcast_log(f"================================================\n")
                await self.broadcast_log(f"[OK] Missing tracks download completed!\n")
                await self.broadcast_log(f"Successfully downloaded: {success_count} | Failed: {fail_count}\n")
                await self.broadcast_log(f"================================================\n")

            if success_count > 0 and auto_import and not self._abort_requested:
                await self.broadcast_log("\n[AUTO-IMPORT] Importing downloaded tracks into library...\n")
                await self.import_library()

            # Prune downloaded queries from missing cache so UI updates immediately
            if downloaded_queries and self._last_missing_tracks:
                self._last_missing_tracks = [t for t in self._last_missing_tracks if t.get("query") not in downloaded_queries]
                try:
                    with open(self.missing_cache_file, "w", encoding="utf-8") as f:
                        json.dump(self._last_missing_tracks, f, indent=2)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error in download_missing_tracks: {e}", exc_info=True)
            await self.broadcast_log(f"\n[ERROR] Unhandled error during missing tracks download: {e}\n")
        finally:
            if not self._abort_requested:
                self.task_progress = {"status": "idle", "action": None, "current": 0, "total": 0, "message": ""}

        return {"success": not self._abort_requested, "downloaded": success_count, "failed": fail_count, "total": total, "aborted": self._abort_requested}

    async def import_library(self, force: bool = False) -> Dict[str, Any]:
        """Move, import with Beets, and clean up staging folder."""
        self._abort_requested = False
        self.task_progress = {
            "status": "running",
            "action": "Importing Music Library",
            "current": 0,
            "total": 4,
            "message": "Step 1: Moving existing matched files..."
        }

        leftovers = []
        try:
            # Check if staging folder has any audio files to import
            audio_exts = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus", ".aac"}
            has_staging_audio = False
            if os.path.exists(self.new_music_dir):
                for root, dirs, files in os.walk(self.new_music_dir):
                    dirs[:] = [d for d in dirs if not d.startswith(".st") and not d.startswith(".syncthing") and d not in {".stfolder", ".stversions"}]
                    for f in files:
                        if not self.is_ignored_staging_file(f) and os.path.splitext(f)[1].lower() in audio_exts:
                            has_staging_audio = True
                            break
                    if has_staging_audio:
                        break

            if not has_staging_audio:
                await self.broadcast_log("[INFO] Staging directory '/music_new' is empty. Nothing to import.\n")
                return {"status": "ok", "message": "Staging directory is empty. Nothing to import.", "leftovers": []}

            # Clean any stale/interrupted Beets resume state so it doesn't force bad grouped imports
            state_file = os.path.join(self.beets_dir, "state.pickle")
            if os.path.exists(state_file):
                try:
                    os.remove(state_file)
                except Exception:
                    pass

            await self.broadcast_log("\n[STEP 1/3] Moving files already cataloged out of staging...\n")
            await self._run_command(["beet", "move", f"path:{self.new_music_dir}"], timeout=180)

            if not self._abort_requested:
                self.task_progress["current"] = 1
                self.task_progress["message"] = "Step 2: Importing unorganized music..."
                await self.broadcast_log("\n[STEP 2/3] Importing unorganized music from staging into Library...\n")
                if force:
                    import_cmd = ["beet", "import", "-P", "-m", self.new_music_dir]
                else:
                    import_cmd = ["beet", "import", "-P", "-q", "-m", self.new_music_dir]
                await self._run_command(import_cmd, timeout=600)

            # Step 2b: If loose tracks remain that could not be matched as full albums, import them as singletons
            audio_exts = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus", ".aac"}
            staging_audio = []
            for root, dirs, files in os.walk(self.new_music_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".st") and not d.startswith(".syncthing") and d not in {".stfolder", ".stversions"}]
                for f in files:
                    if self.is_ignored_staging_file(f):
                        continue
                    if os.path.splitext(f)[1].lower() in audio_exts:
                        staging_audio.append(f)

            if staging_audio and not self._abort_requested:
                await self.broadcast_log(f"\n[STEP 2b] Importing {len(staging_audio)} loose track(s) as singletons...\n")
                singleton_cmd = ["beet", "import", "-P", "-q", "-m", "-s", self.new_music_dir]
                await self._run_command(singleton_cmd, timeout=600)

            if not self._abort_requested:
                self.task_progress["current"] = 2
                self.task_progress["message"] = "Step 3: Cleaning up staging artifacts..."
                await self.broadcast_log("\n[STEP 3/3] Cleaning leftover spotdl artifacts and empty folders...\n")

                cleaned_files = 0
                for root, dirs, files in os.walk(self.new_music_dir, topdown=False):
                    dirs[:] = [d for d in dirs if not d.startswith(".st") and not d.startswith(".syncthing") and d not in {".stfolder", ".stversions"}]
                    for file in files:
                        if file.startswith(".spotdl") or file.endswith(".spotdl"):
                            try:
                                os.remove(os.path.join(root, file))
                                cleaned_files += 1
                            except Exception:
                                pass
                    for dir_name in dirs:
                        if dir_name.startswith(".st") or dir_name.startswith(".syncthing") or dir_name in {".stfolder", ".stversions"}:
                            continue
                        dir_path = os.path.join(root, dir_name)
                        try:
                            if not os.listdir(dir_path):
                                os.rmdir(dir_path)
                        except Exception:
                            pass

                for root, dirs, files in os.walk(self.new_music_dir):
                    dirs[:] = [d for d in dirs if not d.startswith(".st") and not d.startswith(".syncthing") and d not in {".stfolder", ".stversions"}]
                    for file in files:
                        if self.is_ignored_staging_file(file):
                            continue
                        ext = os.path.splitext(file)[1].lower()
                        if ext in audio_exts:
                            rel_path = os.path.relpath(os.path.join(root, file), self.new_music_dir).replace("\\", "/")
                            leftovers.append(rel_path)

                if leftovers:
                    await self.broadcast_log(f"\n[WARN] {len(leftovers)} audio file(s) remain in Staging:\n")
                    for item in leftovers[:10]:
                        await self.broadcast_log(f"   - {item}\n")
                    if len(leftovers) > 10:
                        await self.broadcast_log(f"   ... and {len(leftovers) - 10} more\n")
                    await self.broadcast_log("These files require manual matching or confident metadata.\n")
                else:
                    await self.broadcast_log("\n[OK] Import complete! Staging directory is completely clean.\n")

                # Step 4: Automatically sanitize DB, deduplicate, and tag new additions with genres
                await self.broadcast_log("\n[STEP 4/4] Sanitizing database and applying genre tags to new additions...\n")
                await self.sanitize_and_deduplicate_library()
                await self.tag_untagged_library_genres()
                self.count_disk_files(force_refresh=True)

        except Exception as e:
            logger.error(f"Error in import_library: {e}", exc_info=True)
            await self.broadcast_log(f"\n[ERROR] Unhandled error during library import: {e}\n")
        finally:
            if not self._abort_requested:
                self.task_progress = {"status": "idle", "action": None, "current": 3, "total": 4, "message": "Import finished"}

        return {"success": True, "leftovers": leftovers}

    async def save_uploaded_file(self, filename: str, file_obj, relative_path: Optional[str] = None) -> Dict[str, Any]:
        """Save an uploaded audio/archive file into staging, preserving directory paths or auto-unpacking zip archives."""
        audio_or_media_exts = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus", ".aac", ".alac", ".aiff", ".wma", ".jpg", ".jpeg", ".png", ".cue", ".m3u", ".m3u8"}

        target_name = relative_path if (relative_path and relative_path.strip()) else filename
        clean_rel = os.path.normpath(target_name).replace("\\", "/")
        clean_rel = re.sub(r'^[a-zA-Z]:[/]', '', clean_rel).lstrip("/")
        parts = [p for p in clean_rel.split("/") if p and p != ".." and p != "."]
        if not parts:
            parts = [os.path.basename(filename) or "upload.mp3"]
        safe_rel_path = os.path.join(*parts)

        dest_path = os.path.join(self.new_music_dir, safe_rel_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        bytes_written = 0
        with open(dest_path, "wb") as f_out:
            if hasattr(file_obj, "read"):
                if asyncio.iscoroutinefunction(file_obj.read):
                    while chunk := await file_obj.read(65536):
                        f_out.write(chunk)
                        bytes_written += len(chunk)
                else:
                    import shutil
                    shutil.copyfileobj(file_obj, f_out, length=65536)

        if bytes_written == 0 and os.path.exists(dest_path):
            bytes_written = os.path.getsize(dest_path)

        # If user uploaded a .zip file, automatically unpack audio contents into staging
        if safe_rel_path.lower().endswith(".zip"):
            try:
                import zipfile
                import shutil
                extracted_count = 0
                with zipfile.ZipFile(dest_path, 'r') as zf:
                    for member in zf.infolist():
                        m_clean = os.path.normpath(member.filename).replace("\\", "/")
                        m_parts = [p for p in m_clean.split("/") if p and p != ".." and p != "."]
                        if not m_parts or member.is_dir():
                            continue
                        m_safe_rel = os.path.join(*m_parts)
                        ext = os.path.splitext(m_safe_rel)[1].lower()
                        if ext in audio_or_media_exts:
                            m_dest = os.path.join(self.new_music_dir, m_safe_rel)
                            os.makedirs(os.path.dirname(m_dest), exist_ok=True)
                            with zf.open(member) as source, open(m_dest, "wb") as target:
                                shutil.copyfileobj(source, target)
                            extracted_count += 1
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
                return {"filename": filename, "type": "zip", "extracted": extracted_count, "bytes": bytes_written}
            except Exception as e:
                logger.error(f"Error extracting uploaded zip {filename}: {e}")
                return {"filename": filename, "type": "zip_error", "error": str(e), "bytes": bytes_written}

        return {"filename": filename, "path": safe_rel_path, "type": "file", "bytes": bytes_written}

    @staticmethod
    def is_ignored_staging_file(filename: str) -> bool:
        """Filter out Syncthing temp files, conflict copies, partial downloads, and OS metadata."""
        if not filename:
            return True
        f_lower = filename.lower().strip()
        # Syncthing temporary or partial sync files (e.g. .syncthing.track.mp3.tmp)
        if f_lower.startswith(".syncthing") or f_lower.endswith(".tmp"):
            return True
        # Partial downloads
        if f_lower.endswith(".part") or f_lower.endswith(".crdownload"):
            return True
        # Syncthing conflict files
        if ".sync-conflict-" in f_lower:
            return True
        # SpotDL artifacts
        if f_lower.startswith(".spotdl") or f_lower.endswith(".spotdl"):
            return True
        # OS / macOS resource forks and files
        if f_lower.startswith("._") or f_lower in {".ds_store", "thumbs.db", "ehthumbs.db", "desktop.ini", ".stignore"}:
            return True
        return False

    def get_staging_files(self) -> List[Dict[str, Any]]:
        # Check /app for any stray files and move to /music_new
        try:
            for f in os.listdir("/app"):
                if self.is_ignored_staging_file(f):
                    continue
                if f.lower().endswith((".mp3", ".flac", ".m4a", ".ogg")):
                    os.rename(os.path.join("/app", f), os.path.join(self.new_music_dir, f))
        except Exception:
            pass

        items = []
        audio_exts = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus", ".aac"}
        for root, dirs, files in os.walk(self.new_music_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".st") and not d.startswith(".syncthing") and d not in {".stfolder", ".stversions"}]
            for file in files:
                if self.is_ignored_staging_file(file):
                    continue
                file_path = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()
                size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                rel_path = os.path.relpath(file_path, self.new_music_dir).replace("\\", "/")
                items.append({
                    "name": file,
                    "path": rel_path,
                    "is_audio": ext in audio_exts,
                    "size_bytes": size,
                    "size_str": f"{size / (1024 * 1024):.1f} MB" if size > 1024*1024 else f"{size / 1024:.1f} KB"
                })
        return items

    async def get_library_stats(self) -> Dict[str, Any]:
        run_env = os.environ.copy()
        run_env["BEETSDIR"] = self.beets_dir
        run_env["HOME"] = self.config_dir
        run_env["XDG_CONFIG_HOME"] = self.config_dir
        run_env["XDG_CACHE_HOME"] = os.path.join(self.config_dir, ".cache")

        proc = await asyncio.create_subprocess_exec(
            "beet", "stats",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=run_env
        )
        stdout, _ = await proc.communicate()
        stats_text = stdout.decode("utf-8", errors="replace")

        stats = {"tracks": "0", "albums": "0", "artists": "0", "size": "0 GB", "time": "0"}
        for line in stats_text.splitlines():
            line = line.strip()
            if line.lower().startswith("tracks:"):
                stats["tracks"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("albums:"):
                stats["albums"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("artists:") or line.lower().startswith("album artists:"):
                stats["artists"] = line.split(":", 1)[1].strip()
            elif "size:" in line.lower():
                stats["size"] = line.split(":", 1)[1].strip()
            elif "time:" in line.lower():
                stats["time"] = line.split(":", 1)[1].strip()
        return stats

    def count_disk_files(self, force_refresh: bool = False) -> int:
        """Count audio files on disk with caching to prevent event-loop freezing."""
        now = time.time()
        if not force_refresh and self._disk_files_cache is not None and (now - self._disk_files_cache_time < 120):
            return self._disk_files_cache

        audio_exts = {'.mp3', '.flac', '.m4a', '.ogg', '.wav', '.opus', '.aac'}
        count = 0
        try:
            for root, _, files in os.walk(self.music_dir):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in audio_exts:
                        count += 1
            self._disk_files_cache = count
            self._disk_files_cache_time = now
        except Exception as e:
            logger.error(f"Error counting disk files: {e}")
            if self._disk_files_cache is not None:
                return self._disk_files_cache
        return count

    async def scan_and_find_missing(self) -> None:
        self._abort_requested = False
        self.task_progress = {
            "status": "running",
            "action": "Scanning Full Library",
            "current": 0,
            "total": 4,
            "message": "Step 1/3: Importing uncataloged music files into Beets..."
        }

        try:
            await self.broadcast_log("\n[STEP 1/3] Importing all uncataloged files from /music into Beets library...\n")
            await self.broadcast_log("This may take a while for large libraries. Only new/unmatched files will be processed.\n\n")
            await self._run_command(["beet", "import", "-P", "-q", "-A", self.music_dir], timeout=1800)

            if not self._abort_requested:
                self.task_progress["current"] = 1
                self.task_progress["message"] = "Step 2/3: Updating file paths and metadata..."

                await self.broadcast_log("\n[STEP 2/3] Updating library paths...\n")
                await self._run_command(["beet", "update", "-F", "path"], timeout=300)
                await self.broadcast_log("\n[STEP 2b/3] Pruning dead paths and deduplicating library...\n")
                await self.sanitize_and_deduplicate_library()

            if not self._abort_requested:
                self.task_progress["current"] = 2
                self.task_progress["message"] = "Step 3/3: Scanning for missing album tracks..."

                await self.broadcast_log("\n[STEP 3/3] Scanning for missing album tracks...\n")
                missing = await self.get_missing_tracks(max_albums=40, force_refresh=True)

                await self.broadcast_log(f"\nScan complete! Found {len(missing)} missing tracks across your library.\n")

                stats = await self.get_library_stats()
                await self.broadcast_log(f"Library now has {stats.get('tracks', '?')} cataloged tracks, {stats.get('albums', '?')} albums.\n")

                self.count_disk_files(force_refresh=True)
        except Exception as e:
            logger.error(f"Error in scan_and_find_missing: {e}", exc_info=True)
            await self.broadcast_log(f"\n[ERROR] Unhandled error during library scan: {e}\n")
        finally:
            if not self._abort_requested:
                self.task_progress = {
                    "status": "idle",
                    "action": None,
                    "current": 3,
                    "total": 4,
                    "message": "Library scan complete"
                }

    async def fetch_all_art(self) -> None:
        self._abort_requested = False
        self.task_progress = {
            "status": "running",
            "action": "Fetching Album Art",
            "current": 0,
            "total": 2,
            "message": "Step 1/2: Downloading high-res cover art from MusicBrainz/iTunes..."
        }
        try:
            await self.broadcast_log("\n[STEP 1/2] Fetching cover art for all albums in library...\n")
            await self._run_command(["beet", "fetchart"], timeout=600)

            if not self._abort_requested:
                self.task_progress["current"] = 1
                self.task_progress["message"] = "Step 2/2: Embedding artwork directly into audio files..."
                await self.broadcast_log("\n[STEP 2/2] Embedding cover art into audio files...\n")
                await self._run_command(["beet", "embedart", "-y"], timeout=600)

                # Defensively enforce group-readable permissions on all cover art
                for root, _, files in os.walk(self.music_dir):
                    for f in files:
                        if f.lower().startswith("cover."):
                            try:
                                os.chmod(os.path.join(root, f), 0o664)
                            except Exception:
                                pass
                await self.broadcast_log("\n[OK] Album art fetching and embedding finished!\n")
        except Exception as e:
            logger.error(f"Error in fetch_all_art: {e}", exc_info=True)
            await self.broadcast_log(f"\n[ERROR] Unhandled error during art fetching: {e}\n")
        finally:
            if not self._abort_requested:
                self.task_progress = {
                    "status": "idle",
                    "action": None,
                    "current": 2,
                    "total": 2,
                    "message": "Album art download and embedding complete!"
                }

    # =========================================================================
    # OLLAMA INSTANCE MANAGEMENT & NETWORK SCANNING
    # =========================================================================

    async def probe_ollama_host(self, host: str, timeout: float = 3.0) -> Dict[str, Any]:
        """Test connectivity and list models for a specific Ollama host."""
        norm_host = normalize_ollama_host(host)
        url = f"{norm_host}/api/tags"
        models = []
        connected = False
        error_msg = None

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OMV-MusicManager"})
            loop = asyncio.get_event_loop()
            resp_data = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
            )
            data = json.loads(resp_data)
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            connected = True
        except Exception as e:
            error_msg = str(e)

        return {
            "connected": connected,
            "host": norm_host,
            "models": models,
            "models_count": len(models),
            "error": error_msg
        }

    async def add_ollama_server(self, host: str, set_active: bool = True) -> Dict[str, Any]:
        """Manually add an Ollama server, test it, and persist it."""
        norm_host = normalize_ollama_host(host)
        if not norm_host:
            return {"success": False, "error": "Invalid host or IP address"}

        probe = await self.probe_ollama_host(norm_host, timeout=3.5)

        if norm_host not in self.ollama_servers:
            self.ollama_servers.append(norm_host)

        if set_active:
            self.ollama_host = norm_host

        self._save_ollama_config()

        return {
            "success": True,
            "host": norm_host,
            "connected": probe["connected"],
            "models": probe["models"],
            "servers": self.ollama_servers,
            "error": probe["error"]
        }

    def remove_ollama_server(self, host: str) -> Dict[str, Any]:
        """Remove a server from the remembered list."""
        norm_host = normalize_ollama_host(host)
        if norm_host in self.ollama_servers:
            self.ollama_servers.remove(norm_host)
            if self.ollama_host == norm_host:
                self.ollama_host = self.ollama_servers[0] if self.ollama_servers else "http://127.0.0.1:11434"
            self._save_ollama_config()
            return {"success": True, "active_host": self.ollama_host, "servers": self.ollama_servers}
        return {"success": False, "error": "Server not found in remembered list"}

    async def set_active_ollama_server(self, host: str) -> Dict[str, Any]:
        """Set the active Ollama host and return its status and models."""
        norm_host = normalize_ollama_host(host)
        if not norm_host:
            return {"success": False, "error": "Invalid host"}

        self.ollama_host = norm_host
        if norm_host not in self.ollama_servers:
            self.ollama_servers.append(norm_host)

        self._save_ollama_config()
        status = await self.get_ollama_status()
        return {
            "success": True,
            "active_host": self.ollama_host,
            "connected": status["connected"],
            "models": status["models"],
            "servers": self.ollama_servers,
            "error": status["error"]
        }

    async def scan_network_for_ollama(self, subnet_prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        """Scan local subnet for port 11434, probe for Ollama instances, and register them."""
        if not subnet_prefix:
            match = re.search(r'(\d+\.\d+\.\d+)\.\d+', self.ollama_host)
            if match:
                subnet_prefix = match.group(1)
            else:
                subnet_prefix = "192.168.178"

        await self.broadcast_log(f"\n[OLLAMA SCAN] Scanning subnet {subnet_prefix}.0/24 for running Ollama instances on port 11434...\n")

        sem = asyncio.Semaphore(60)

        async def _probe(ip):
            async with sem:
                try:
                    conn = asyncio.open_connection(ip, 11434)
                    reader, writer = await asyncio.wait_for(conn, timeout=0.35)
                    writer.close()
                    await writer.wait_closed()
                    return ip
                except Exception:
                    return None

        tasks = [_probe(f"{subnet_prefix}.{i}") for i in range(1, 255)]
        results = await asyncio.gather(*tasks)
        open_ips = [ip for ip in results if ip]

        await self.broadcast_log(f"[OLLAMA SCAN] Port 11434 open on: {', '.join(open_ips) if open_ips else 'none'}. Verifying Ollama API...\n")

        discovered = []
        for ip in open_ips:
            probe = await self.probe_ollama_host(f"http://{ip}:11434", timeout=2.5)
            if probe["connected"]:
                discovered.append({
                    "host": probe["host"],
                    "ip": ip,
                    "models_count": probe["models_count"],
                    "models": probe["models"]
                })
                if probe["host"] not in self.ollama_servers:
                    self.ollama_servers.append(probe["host"])
                await self.broadcast_log(f"   -> [FOUND] Verified Ollama instance at {probe['host']} with {probe['models_count']} models ({', '.join(probe['models'][:3])}...)\n")

        if discovered:
            self._save_ollama_config()
            await self.broadcast_log(f"[OLLAMA SCAN] Scan complete! Discovered {len(discovered)} active Ollama server(s).\n")
        else:
            await self.broadcast_log("[OLLAMA SCAN] Scan complete. No active Ollama servers detected on this subnet.\n")

        return discovered

    # =========================================================================
    # AI RECOMMENDATIONS POWERED BY LOCAL OLLAMA
    # =========================================================================

    def get_dynamic_style_focuses(self) -> List[Dict[str, Any]]:
        """Dynamically generate style focus presets grounded in the user's actual Beets library genres and artists."""
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            alt_db = os.path.join(self.music_dir, "library.db")
            if os.path.exists(alt_db):
                db_path = alt_db

        STYLE_TAXONOMY = [
            {
                "id": "metal_hard_rock",
                "name": "Metal & Hard Rock",
                "icon": "fa-skull",
                "keywords": ["metal", "heavy metal", "metalcore", "thrash metal", "groove metal", "hard rock", "industrial metal", "nu metal", "alternative metal"],
                "guidance_template": "Focus specifically on high-energy Heavy Metal, Metalcore, and Hard Rock with crushing riffs and aggressive drive (akin to {artists})."
            },
            {
                "id": "classic_prog",
                "name": "Classic & Prog Rock",
                "icon": "fa-compact-disc",
                "keywords": ["classic rock", "progressive rock", "psychedelic rock", "glam rock", "art rock", "arena rock"],
                "guidance_template": "Focus specifically on legendary Classic Rock, Progressive Rock, and timeless analog masterclasses (akin to {artists})."
            },
            {
                "id": "indie_alt",
                "name": "Indie & Alternative Rock",
                "icon": "fa-guitar",
                "keywords": ["indie", "indie rock", "alternative rock", "garage rock", "post-punk", "punk rock", "indie pop", "grunge"],
                "guidance_template": "Focus specifically on energetic Indie Rock, catchy Alternative hooks, and raw guitar energy (akin to {artists})."
            },
            {
                "id": "electronic_synth",
                "name": "Electronic & Psytrance",
                "icon": "fa-bolt",
                "keywords": ["electronic", "psytrance", "trance", "synthwave", "edm", "techno", "ambient", "goa", "electro", "drum and bass"],
                "guidance_template": "Focus specifically on driving Electronic beats, Psytrance basslines, and hypnotic synth soundscapes (akin to {artists})."
            },
            {
                "id": "blues_roots",
                "name": "Blues & Roots Rock",
                "icon": "fa-fire",
                "keywords": ["blues", "blues rock", "southern rock", "roots rock", "delta blues", "rockabilly", "rock & roll", "rock and roll"],
                "guidance_template": "Focus specifically on gritty Blues-Rock, stomp-and-clap grooves, and swaggering fuzz guitars (akin to {artists})."
            },
            {
                "id": "soul_funk_rnb",
                "name": "Soul, Funk & R&B",
                "icon": "fa-record-vinyl",
                "keywords": ["soul", "funk", "rnb", "r&b", "motown", "disco", "funk rock", "neo-soul"],
                "guidance_template": "Focus specifically on groovy Soul, infectious Funk rhythms, and silky R&B melodies (akin to {artists})."
            },
            {
                "id": "pop_vocal",
                "name": "Pop & Dance-Pop",
                "icon": "fa-sparkles",
                "keywords": ["pop", "dance-pop", "synthpop", "europop", "power pop", "electropop"],
                "guidance_template": "Focus specifically on catchy Pop anthems, crisp modern production, and infectious vocal hooks (akin to {artists})."
            },
            {
                "id": "singer_songwriter",
                "name": "Singer-Songwriter & Acoustic",
                "icon": "fa-feather-pointed",
                "keywords": ["singer-songwriter", "acoustic", "folk", "americana", "ballad", "chanson"],
                "guidance_template": "Focus specifically on intimate Singer-Songwriter craft, rich lyrical storytelling, and acoustic warmth (akin to {artists})."
            },
            {
                "id": "hiphop_rap",
                "name": "Hip-Hop & Rap",
                "icon": "fa-microphone-lines",
                "keywords": ["hip-hop", "rap", "boom bap", "trap", "gangsta rap", "east coast hip hop", "west coast hip hop"],
                "guidance_template": "Focus specifically on authentic Hip-Hop, lyrical flows, and classic boom-bap or modern beats (akin to {artists})."
            },
            {
                "id": "soundtrack_ambient",
                "name": "Soundtrack & Cinematic",
                "icon": "fa-film",
                "keywords": ["soundtrack", "cinematic", "score", "ambient", "composers", "orchestral", "film score"],
                "guidance_template": "Focus specifically on immersive Cinematic scores, atmospheric soundtracks, and modern orchestral compositions (akin to {artists})."
            }
        ]

        style_artists = defaultdict(lambda: Counter())
        style_track_counts = Counter()

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute('''
                SELECT artist, genre, count(*) as track_count
                FROM items
                WHERE artist != '' AND artist NOT LIKE '%Various Artists%' AND genre IS NOT NULL AND genre != ''
                GROUP BY artist, genre
                ORDER BY track_count DESC
            ''')
            rows = c.fetchall()
            conn.close()

            for artist, genre_str, count in rows:
                genre_lower = (genre_str or "").lower()
                parts = [p.strip() for p in genre_lower.replace('/', ',').replace(';', ',').split(',') if p.strip()]
                for tax in STYLE_TAXONOMY:
                    weight = 0
                    for idx, p in enumerate(parts):
                        for kw in tax["keywords"]:
                            if kw == p:
                                weight = max(weight, 3 if idx == 0 else (2 if idx <= 2 else 1))
                            elif len(kw) > 4 and kw in p:
                                weight = max(weight, 2 if idx == 0 else 1)
                    if weight > 0:
                        style_track_counts[tax["id"]] += count
                        style_artists[tax["id"]][artist] += (count * weight)
        except Exception as e:
            logger.error(f"Error building dynamic styles: {e}")

        results = [
            {
                "id": "all",
                "name": "Complete Library Mix",
                "icon": "fa-music",
                "artists_preview": "",
                "guidance": "Draw inspiration across the user's complete eclectic library profile."
            }
        ]

        dynamic_candidates = []
        for tax in STYLE_TAXONOMY:
            sid = tax["id"]
            total_tracks = style_track_counts[sid]
            if total_tracks >= 20:
                top_artists = [a for a, _ in style_artists[sid].most_common(3)]
                artists_str = " / ".join(top_artists)
                dynamic_candidates.append({
                    "id": sid,
                    "name": tax["name"],
                    "icon": tax["icon"],
                    "artists_preview": f"({artists_str})" if artists_str else "",
                    "guidance": tax["guidance_template"].format(artists=artists_str or tax["name"]),
                    "track_count": total_tracks
                })

        dynamic_candidates.sort(key=lambda x: x.get("track_count", 0), reverse=True)

        wildcard = {
            "id": "wildcard",
            "name": "Wildcard / Hidden Gems",
            "icon": "fa-dice",
            "artists_preview": "",
            "guidance": "Focus on hidden gems, indie breakouts, or surprising genre crossover artists that complement the eclectic vibe of this library."
        }

        return results + dynamic_candidates + [wildcard]

    def get_taste_profile(self, top_n: int = 40, include_all: bool = True) -> Dict[str, Any]:
        """Extract top artists, album count, and genres from Beets DB, optionally including all library artists."""
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            alt_db = os.path.join(self.music_dir, "library.db")
            if os.path.exists(alt_db):
                db_path = alt_db

        top_artists = []
        all_artists = []
        total_tracks = 0
        total_artists = 0

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT count(*), count(distinct artist) FROM items")
            row = c.fetchone()
            if row:
                total_tracks = row[0]
                total_artists = row[1]

            if include_all:
                c.execute("""
                    SELECT artist, count(*) as track_count
                    FROM items
                    WHERE artist != '' AND artist NOT LIKE '%Various Artists%'
                    GROUP BY artist
                    ORDER BY track_count DESC
                """)
                for r in c.fetchall():
                    all_artists.append({
                        "artist": r[0],
                        "track_count": r[1]
                    })

            c.execute("""
                SELECT artist, count(*) as track_count, GROUP_CONCAT(DISTINCT album) as albums
                FROM items
                WHERE artist != '' AND artist NOT LIKE '%Various Artists%'
                GROUP BY artist
                ORDER BY track_count DESC
                LIMIT ?
            """, (top_n,))

            for r in c.fetchall():
                albums_list = [a.strip() for a in (r[2] or "").split(",") if a.strip()][:3]
                top_artists.append({
                    "artist": r[0],
                    "track_count": r[1],
                    "sample_albums": albums_list
                })
            conn.close()
        except Exception as e:
            logger.error(f"Error querying taste profile: {e}")

        dynamic_styles = self.get_dynamic_style_focuses()

        return {
            "total_tracks": total_tracks,
            "total_artists": total_artists,
            "top_artists": top_artists,
            "all_artists": all_artists,
            "dynamic_styles": dynamic_styles
        }

    async def get_ollama_status(self) -> Dict[str, Any]:
        """Test connection to active Ollama instance and list available models + servers."""
        url = f"{self.ollama_host}/api/tags"
        models = []
        connected = False
        error_msg = None

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OMV-MusicManager"})
            loop = asyncio.get_event_loop()
            resp_data = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=4).read().decode("utf-8"))
            data = json.loads(resp_data)
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            connected = True
        except Exception as e:
            error_msg = str(e)

        return {
            "connected": connected,
            "host": self.ollama_host,
            "default_model": self.ollama_default_model,
            "models": models,
            "servers": self.ollama_servers,
            "error": error_msg
        }

    def get_library_artist_names(self) -> Set[str]:
        """Return a set of lowercase artist and albumartist names in the library."""
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            alt_db = os.path.join(self.music_dir, "library.db")
            if os.path.exists(alt_db):
                db_path = alt_db
        if not os.path.exists(db_path):
            return set()
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT DISTINCT artist FROM items WHERE artist IS NOT NULL AND artist != ''")
            artists = {row[0].strip().lower() for row in c.fetchall() if row[0] and row[0].strip()}
            c.execute("SELECT DISTINCT albumartist FROM albums WHERE albumartist IS NOT NULL AND albumartist != ''")
            for row in c.fetchall():
                if row[0] and row[0].strip():
                    artists.add(row[0].strip().lower())
            conn.close()
            return artists
        except Exception as e:
            logger.error(f"Error querying library artists: {e}")
            return set()

    async def generate_graph_recommendations(
        self,
        prompt: str = "",
        preset: Optional[str] = None,
        count: int = 6,
        anchor_artists: Optional[List[str]] = None,
        custom_guidance: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fast artist & album discovery grounded in actual Beets library via Deezer Knowledge Graph."""
        taste = self.get_taste_profile(top_n=35, include_all=False)
        lib_artists_set = self.get_library_artist_names()

        # 1. Determine anchor artists
        anchors = [a.strip() for a in (anchor_artists or []) if a and a.strip()]

        if not anchors and preset and preset != "all":
            # Match style preset to library artists
            styles = self.get_dynamic_style_focuses()
            for s in styles:
                if s.get("id") == preset:
                    preview = s.get("artists_preview", "").strip("()").split("/")
                    anchors = [p.strip() for p in preview if p.strip()]
                    break

        if not anchors:
            top_taste = [a["artist"] for a in taste.get("top_artists", []) if a.get("artist")]
            if top_taste:
                anchors = random.sample(top_taste, min(len(top_taste), 4))
            else:
                anchors = ["Queen", "Pink Floyd"]

        if prompt and prompt.strip():
            anchors.insert(0, prompt.strip())

        await self.broadcast_log(f"\n[Recommendations] Discovering music via Knowledge Graph for anchors: {', '.join(anchors)}...\n")

        loop = asyncio.get_event_loop()

        def fetch_json(url: str):
            req = urllib.request.Request(url, headers={"User-Agent": "OMV-MusicManager/1.5"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))

        async def async_fetch_json(url: str):
            try:
                return await loop.run_in_executor(None, lambda: fetch_json(url))
            except Exception as e:
                logger.debug(f"Failed fetching {url}: {e}")
                return {}

        # 2. Search anchors on Deezer concurrently
        search_tasks = [
            async_fetch_json(f"https://api.deezer.com/search/artist?q={urllib.parse.quote(a)}")
            for a in anchors[:6]
        ]
        search_results = await asyncio.gather(*search_tasks)

        best_anchors = []
        for a_name, s_data in zip(anchors[:6], search_results):
            items = s_data.get("data", [])
            if items:
                best = max(items, key=lambda x: x.get("nb_fan", 0))
                best_anchors.append(best)

        if not best_anchors:
            fallback_res = await async_fetch_json("https://api.deezer.com/search/artist?q=Rock")
            if fallback_res.get("data"):
                best_anchors = fallback_res["data"][:2]

        # 3. Fetch related artists concurrently
        related_tasks = [
            async_fetch_json(f"https://api.deezer.com/artist/{b['id']}/related")
            for b in best_anchors
        ]
        related_results = await asyncio.gather(*related_tasks)

        # 4. Filter and aggregate candidate artists
        candidate_map = {}
        for b_item, r_data in zip(best_anchors, related_results):
            b_name = b_item.get("name", "Artist")
            for rel in r_data.get("data", []):
                rel_name = rel.get("name", "").strip()
                if not rel_name:
                    continue
                # Exclude if already in user's library
                if rel_name.lower() in lib_artists_set:
                    continue
                # Also exclude anchor artists themselves
                if any(rel_name.lower() == a.lower() for a in anchors):
                    continue

                key = rel_name.lower()
                if key not in candidate_map:
                    candidate_map[key] = {
                        "item": rel,
                        "anchors": [b_name],
                        "nb_fan": rel.get("nb_fan", 0)
                    }
                else:
                    if b_name not in candidate_map[key]["anchors"]:
                        candidate_map[key]["anchors"].append(b_name)

        # 4b. 2nd-degree expansion if library already has most 1st-degree related artists
        if len(candidate_map) < count * 2:
            second_degree_targets = []
            for r_data in related_results:
                for item in r_data.get("data", [])[:5]:
                    if item.get("id") and item.get("id") not in [t["id"] for t in second_degree_targets]:
                        second_degree_targets.append(item)
            if second_degree_targets:
                second_tasks = [
                    async_fetch_json(f"https://api.deezer.com/artist/{t['id']}/related")
                    for t in second_degree_targets[:8]
                ]
                second_results = await asyncio.gather(*second_tasks)
                for t_item, s_res in zip(second_degree_targets[:8], second_results):
                    t_name = t_item.get("name", "Anchor")
                    for rel in s_res.get("data", []):
                        rel_name = rel.get("name", "").strip()
                        if not rel_name:
                            continue
                        if rel_name.lower() in lib_artists_set:
                            continue
                        if any(rel_name.lower() == a.lower() for a in anchors):
                            continue
                        key = rel_name.lower()
                        if key not in candidate_map:
                            candidate_map[key] = {
                                "item": rel,
                                "anchors": [t_name],
                                "nb_fan": rel.get("nb_fan", 0)
                            }
                        else:
                            if t_name not in candidate_map[key]["anchors"]:
                                candidate_map[key]["anchors"].append(t_name)

        ranked = sorted(
            candidate_map.values(),
            key=lambda c: (len(c["anchors"]), c["nb_fan"]),
            reverse=True
        )

        selected = ranked[:count]

        # 5. Fetch top tracks concurrently for selected artists
        top_tasks = [
            async_fetch_json(f"https://api.deezer.com/artist/{c['item']['id']}/top?limit=3")
            for c in selected
        ]
        top_results = await asyncio.gather(*top_tasks)

        recommendations = []
        for cand, top_data in zip(selected, top_results):
            rel = cand["item"]
            rel_name = rel.get("name", "").strip()
            anchor_desc = " & ".join(cand["anchors"][:2])

            top_tracks = []
            album_name = "Definitive Works"
            for t in top_data.get("data", [])[:3]:
                title = t.get("title", "").strip()
                if title:
                    top_tracks.append({
                        "title": title,
                        "search_query": f"{rel_name} - {title}"
                    })
                alb = t.get("album", {})
                if alb and alb.get("title") and album_name == "Definitive Works":
                    album_name = alb.get("title")

            fan_count = cand["nb_fan"]
            fans_str = f"{fan_count:,} fans" if fan_count > 0 else "acclaimed catalog"
            reason = f"Shares strong musical kinship with {anchor_desc} in your library ({fans_str} on Deezer)."

            genre_label = "Curated Discovery"
            if preset and preset != "all":
                genre_label = preset.replace("_", " ").title()

            recommendations.append({
                "artist": rel_name,
                "genre": genre_label,
                "similarity": f"For fans of {anchor_desc}",
                "reason": reason,
                "recommended_album": album_name,
                "recommended_tracks": top_tracks
            })

        await self.broadcast_log(f"[Recommendations] Generated {len(recommendations)} recommendations via Knowledge Graph.\n")

        return {
            "success": True,
            "engine": "Deezer & Knowledge Graph",
            "preset": preset,
            "anchor_artists": anchors,
            "recommendations": recommendations,
            "taste_summary": {
                "total_tracks": taste.get("total_tracks"),
                "sample_artists": [a["artist"] for a in taste.get("top_artists", [])[:10]]
            }
        }

    async def generate_ai_recommendations(
        self,
        prompt: str = "",
        model: Optional[str] = None,
        preset: Optional[str] = None,
        count: int = 6,
        anchor_artists: Optional[List[str]] = None,
        custom_guidance: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate music recommendations using Deezer & Knowledge Graph grounded in actual library."""
        return await self.generate_graph_recommendations(
            prompt=prompt,
            preset=preset,
            count=count,
            anchor_artists=anchor_artists,
            custom_guidance=custom_guidance
        )

    # =========================================================================
    # GENRE TAGGING & LIBRARY TAXONOMY
    # =========================================================================

    def _load_genre_cache(self) -> Dict[str, str]:
        cache_path = os.path.join(self.beets_dir, "genre_cache.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_genre_cache(self, cache: Dict[str, str]):
        cache_path = os.path.join(self.beets_dir, "genre_cache.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not save genre cache: {e}")

    def _merge_genre_strings(self, existing: Optional[str], new_genres: Optional[str], max_tags: int = 5) -> str:
        """Merge existing and newly fetched comma-separated genres without duplicates, up to max_tags."""
        result = []
        seen = set()
        for source in (existing, new_genres):
            if not source:
                continue
            for g in source.replace(';', ',').split(','):
                cleaned = g.strip().title()
                norm = re.sub(r'[^a-zA-Z0-9]', '', cleaned).lower()
                if norm and norm not in seen and not re.match(r'^\d+s?$', norm):
                    if cleaned.lower() == "r&b":
                        cleaned = "R&B"
                    elif cleaned.lower() == "hip hop":
                        cleaned = "Hip-Hop"
                    result.append(cleaned)
                    seen.add(norm)
                    if len(result) >= max_tags:
                        return ", ".join(result)
        return ", ".join(result) if result else "Rock"

    def _fetch_artist_genre_lastfm(self, artist: str, max_genres: int = 5) -> Optional[str]:
        """Fetch artist genre from Last.fm using pylast or HTTP API, returning up to max_genres."""
        try:
            import pylast
            import beets.plugins
            network = pylast.LastFMNetwork(api_key=beets.plugins.LASTFM_KEY)
            art_obj = network.get_artist(artist)
            tags = art_obj.get_top_tags(limit=12)
            if tags:
                # filter out useless tags like 'seen live', 'favorites', etc.
                ignored = {
                    "seen live", "favorite", "favourites", "loved", "my favorites",
                    "beautiful", "under 2000 listeners", "albums i own", "all", "awesome"
                }
                valid_tags = []
                for t in tags:
                    name = t.item.get_name().strip()
                    title_name = name.title()
                    if name.lower() not in ignored and len(name) > 2 and title_name not in valid_tags:
                        valid_tags.append(title_name)
                        if len(valid_tags) >= max_genres:
                            break
                if valid_tags:
                    return ", ".join(valid_tags)
        except Exception as e:
            logger.debug(f"Last.fm genre lookup failed for {artist}: {e}")
        return None

    async def tag_entire_library_genres(self, force: bool = False) -> Dict[str, Any]:
        """Scan all tracks in the Beets library, fetch genres, update DB and audio tags."""
        if self.current_task:
            return {"success": False, "error": f"Another task is already running: {self.current_task}"}

        self._abort_requested = False
        self.current_task = "genre_tagging"
        self.task_progress = {
            "status": "running",
            "action": "Tagging Library Genres",
            "current": 0,
            "total": 100,
            "message": "Step 1/3: Analyzing library artists and untagged tracks..."
        }

        db_path = os.path.join(self.beets_dir, "library.db")
        genre_cache = self._load_genre_cache()

        # Seed knowledge base for prominent library artists
        seed_kb = {
                        "Imagine Dragons": "Alternative Rock, Pop Rock",
            "Hoobastank": "Post-Grunge, Alternative Rock",
            "Lifehouse": "Post-Grunge, Alternative Rock",
            "Mahadewa": "Hard Rock, Indonesian Rock",
            "For Revenge": "Post-Hardcore, Emo",
            "for Revenge": "Post-Hardcore, Emo",
            "Slank": "Indonesian Rock, Blues Rock",
            "The Tragically Hip": "Alternative Rock, Canadian Rock",
            "Stereophonics": "Britpop, Post-Britpop",
            "Pretenders": "New Wave, Punk Rock",
            "Neil Young & Crazy Horse": "Folk Rock, Heartland Rock",
            "Goo Goo Dolls": "Alternative Rock, Post-Grunge",
            "Balu Brigada": "Indie Pop, Groove Pop",
            "Cartoon feat. Daniel Levi": "Electronic, Drum and Bass",
            "Pink Floyd": "Classic Rock, Progressive Rock",
            "Rare Americans": "Indie Rock, Narrative Rock",
            "Five Finger Death Punch": "Heavy Metal, Groove Metal",
            "ABBA": "Pop, Disco",
            "Joe Bonamassa": "Blues Rock, Modern Blues",
            "Eddie Cochran": "Rock & Roll, Rockabilly",
            "Bee Gees": "Disco, Pop",
            "50 Cent": "Hip-Hop, Gangsta Rap",
            "Georges Brassens": "Chanson, French Folk",
            "Black Rebel Motorcycle Club": "Garage Rock, Alternative Rock",
            "Elvis Presley": "Rock & Roll, Rockabilly",
            "Chuck Berry": "Rock & Roll, Rhythm and Blues",
            "Infected Mushroom": "Psytrance, Electronic",
            "Red Hot Chili Peppers": "Funk Rock, Alternative Rock",
            "Cage the Elephant": "Indie Rock, Garage Rock",
            "Bon Jovi": "Hard Rock, Glam Metal",
            "*NSYNC": "Pop, Dance-Pop",
            "Elton John": "Classic Rock, Pop Rock",
            "Bug Hunter": "Indie Pop, Folk Rock",
            "The Black Eyed Peas": "Hip-Hop, Dance-Pop",
            "Billy Joel": "Classic Rock, Pop Rock",
            "Chicago": "Soft Rock, Jazz Rock",
            "Daniel Pemberton": "Soundtrack, Cinematic",
            "Backstreet Boys": "Pop, Dance-Pop",
            "Britney Spears": "Dance-Pop, Pop",
            "BE:FIRST": "J-Pop, Dance",
            "AC/DC": "Hard Rock, Heavy Metal",
            "Blackstreet": "R&B, New Jack Swing",
            "America": "Folk Rock, Soft Rock",
            "Baguette Quartette": "Chanson, Accordion",
            "The Black Keys": "Blues Rock, Garage Rock",
            "Dire Straits": "Classic Rock, Roots Rock",
            "The Doobie Brothers": "Classic Rock, Soft Rock",
            "The Isley Brothers": "Soul, Funk",
            "Bellamy Brothers": "Classic Country, Country Pop",
            "Queen": "Classic Rock, Glam Rock",
            "Led Zeppelin": "Hard Rock, Classic Rock",
            "The Doors": "Psychedelic Rock, Classic Rock",
            "The Rolling Stones": "Classic Rock, Blues Rock",
            "The Beatles": "Classic Rock, Pop Rock",
            "Fleetwood Mac": "Classic Rock, Pop Rock",
            "Stevie Ray Vaughan": "Blues, Blues Rock",
            "B.B. King": "Blues, Electric Blues",
            "Muddy Waters": "Delta Blues, Chicago Blues",
            "Gary Clark Jr.": "Blues Rock, Modern Blues",
            "Eric Clapton": "Blues Rock, Classic Rock",
            "Daft Punk": "Electronic, French House",
            "The Prodigy": "Electronic, Big Beat",
            "deadmau5": "Electronic, Progressive House",
            "Pendulum": "Drum and Bass, Electronic Rock",
            "Mandragora": "Psytrance, Futureprog",
            "Venjent": "Drum and Bass, Electronic",
            "Eminem": "Hip-Hop, Rap",
            "Dr. Dre": "Hip-Hop, West Coast Rap",
            "Snoop Dogg": "Hip-Hop, West Coast Rap",
            "2Pac": "Hip-Hop, Gangsta Rap",
            "Kendrick Lamar": "Hip-Hop, Conscious Rap",
            "Good Kid": "Indie Rock, J-Rock",
            "The Heavy": "Neo-Soul, Garage Rock",
            "Royal Blood": "Garage Rock, Hard Rock",
            "Jack White": "Garage Rock, Blues Rock",
            "The White Stripes": "Garage Rock, Blues Rock",
            "Queens of the Stone Age": "Desert Rock, Stoner Rock",
            "King Gizzard & The Lizard Wizard": "Psychedelic Rock, Garage Rock",
            "Tame Impala": "Psychedelic Pop, Synth-Pop",
            "Green Day": "Punk Rock, Pop Punk",
            "Blink-182": "Pop Punk, Alternative Rock",
            "Nirvana": "Grunge, Alternative Rock",
            "Pearl Jam": "Grunge, Alternative Rock",
            "Soundgarden": "Grunge, Alternative Metal",
            "Foo Fighters": "Alternative Rock, Post-Grunge",
            "Radiohead": "Art Rock, Alternative Rock",
            "Muse": "Alternative Rock, Space Rock",
            "Coldplay": "Pop Rock, Alternative Rock",
            "The Killers": "Indie Rock, Synthpop",
            "Arctic Monkeys": "Indie Rock, Garage Rock",
            "The Strokes": "Indie Rock, Garage Rock",
            "Franz Ferdinand": "Indie Rock, Dance-Punk",
            "Weezer": "Power Pop, Alternative Rock",
            "Gorillaz": "Alternative Hip-Hop, Electronic",
            "Linkin Park": "Nu Metal, Alternative Rock",
            "System of a Down": "Alternative Metal, Nu Metal",
            "Metallica": "Thrash Metal, Heavy Metal",
            "Iron Maiden": "Heavy Metal",
            "Black Sabbath": "Heavy Metal, Doom Metal",
            "Ozzy Osbourne": "Heavy Metal, Hard Rock",
            "Tool": "Progressive Metal, Alternative Metal",
            "Deftones": "Alternative Metal, Shoegaze",
            "Alice in Chains": "Grunge, Alternative Metal",
            "Stone Temple Pilots": "Grunge, Alternative Rock",
            "Creedence Clearwater Revival": "Roots Rock, Swamp Rock",
            "Johnny Cash": "Country, Rockabilly",
            "Bob Dylan": "Folk Rock, Singer-Songwriter",
            "Neil Young": "Folk Rock, Heartland Rock",
            "Simon & Garfunkel": "Folk Rock, Sunshine Pop",
            "Edith Piaf": "Chanson, Traditional Pop",
            "Jacques Brel": "Chanson",
            "Hans Zimmer": "Soundtrack, Cinematic",
            "John Williams": "Soundtrack, Orchestral",
            "Ennio Morricone": "Soundtrack, Spaghetti Western",
            "Michael Jackson": "Pop, R&B",
            "Prince": "Funk, Pop Rock",
            "Stevie Wonder": "Soul, Funk",
            "Marvin Gaye": "Soul, R&B",
            "Earth, Wind & Fire": "Funk, Disco, Soul",
            "Kool & The Gang": "Funk, Disco",
            "KC and the Sunshine Band": "Disco, Funk",
            "Donna Summer": "Disco, Dance-Pop",
            "Depeche Mode": "Synthpop, New Wave",
            "New Order": "New Wave, Synthpop",
            "The Cure": "Post-Punk, Gothic Rock",
            "The Smiths": "Indie Pop, Jangle Pop",
            "Tears for Fears": "New Wave, Synthpop",
            "Duran Duran": "New Wave, Synthpop",
            "Wham!": "Pop, Dance-Pop",
            "George Michael": "Pop, R&B",
            "a-ha": "Synthpop, New Wave",
            "Eurythmics": "Synthpop, New Wave",
            "Madonna": "Pop, Dance-Pop",
            "Whitney Houston": "Pop, R&B",
            "Mariah Carey": "Pop, R&B"
        }

        # Merge seed into cache
        for a, g in seed_kb.items():
            if a not in genre_cache:
                genre_cache[a] = g

        try:
            await self.broadcast_log("\n================================================\n")
            await self.broadcast_log("[GENRE TAGGER] Starting Full Library Genre Tagging & Audit\n")
            await self.broadcast_log("================================================\n\n")

            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            # Find artists to process
            if force:
                c.execute("SELECT DISTINCT artist FROM items WHERE artist != ''")
            else:
                c.execute("SELECT DISTINCT artist FROM items WHERE artist != '' AND (genre IS NULL OR genre = '')")

            artists_to_process = [r[0] for r in c.fetchall()]
            total_artists = len(artists_to_process)
            await self.broadcast_log(f"Found {total_artists} artists requiring genre classification.\n")

            tagged_count = 0
            file_updates = 0

            for idx, artist in enumerate(artists_to_process, 1):
                if self._abort_requested:
                    await self.broadcast_log(f"\n[ABORT] Stopped genre tagging at artist {idx}/{total_artists}.\n")
                    break

                self.task_progress["current"] = idx
                self.task_progress["total"] = total_artists
                self.task_progress["message"] = f"Tagging ({idx}/{total_artists}): {artist}"

                genre = genre_cache.get(artist)
                existing_parts = [g.strip() for g in genre.replace(';', ',').split(',') if g.strip()] if genre else []
                if force or not genre or len(existing_parts) < 5:
                    loop = asyncio.get_event_loop()
                    fetched = await loop.run_in_executor(None, self._fetch_artist_genre_lastfm, artist, 5)
                    if fetched:
                        genre = self._merge_genre_strings(genre, fetched, max_tags=5)
                        genre_cache[artist] = genre
                    elif not genre:
                        genre = "Rock"
                        genre_cache[artist] = genre

                # Update SQLite database for this artist
                if force:
                    c.execute("UPDATE items SET genre = ? WHERE artist = ?", (genre, artist))
                else:
                    c.execute("UPDATE items SET genre = ? WHERE artist = ? AND (genre IS NULL OR genre = '')", (genre, artist))

                row_cnt = c.rowcount
                tagged_count += row_cnt

                # Also write ID3 tags to actual files on disk
                c.execute("SELECT path FROM items WHERE artist = ?", (artist,))
                for p_row in c.fetchall():
                    raw_p = p_row[0]
                    p_str = raw_p.decode("utf-8", "replace") if isinstance(raw_p, bytes) else str(raw_p)
                    if os.path.exists(p_str):
                        try:
                            import mutagen
                            mfile = mutagen.File(p_str)
                            if mfile is not None:
                                ext = os.path.splitext(p_str)[1].lower()
                                if ext == ".mp3":
                                    from mutagen.id3 import ID3, TCON
                                    if mfile.tags is None:
                                        mfile.add_tags()
                                    mfile.tags["TCON"] = TCON(encoding=3, text=genre)
                                    mfile.save()
                                    file_updates += 1
                                elif ext in (".flac", ".ogg", ".opus"):
                                    mfile["genre"] = [genre]
                                    mfile.save()
                                    file_updates += 1
                                elif ext in (".m4a", ".mp4"):
                                    mfile["\xa9gen"] = [genre]
                                    mfile.save()
                                    file_updates += 1
                        except Exception:
                            pass

                if idx % 15 == 0 or idx == total_artists:
                    conn.commit()
                    self._save_genre_cache(genre_cache)
                    await self.broadcast_log(f"[{idx}/{total_artists}] Tagged '{artist}' -> {genre} ({row_cnt} tracks updated)\n")

            conn.commit()
            self._save_genre_cache(genre_cache)

            # Also update albums table genre if column exists
            try:
                c.execute("UPDATE albums SET genre = (SELECT items.genre FROM items WHERE items.album_id = albums.id AND items.genre IS NOT NULL LIMIT 1)")
                conn.commit()
            except Exception:
                pass

            conn.close()

            await self.broadcast_log("\n================================================\n")
            await self.broadcast_log(f"[OK] Full library genre tagging finished successfully!\n")
            await self.broadcast_log(f"Processed {total_artists} artists, updated {tagged_count} tracks, tagged {file_updates} audio files on disk.\n")
            await self.broadcast_log("================================================\n")

            return {
                "success": True,
                "artists_processed": total_artists,
                "tracks_tagged": tagged_count,
                "files_updated": file_updates
            }
        except Exception as e:
            logger.error(f"Error in tag_entire_library_genres: {e}", exc_info=True)
            await self.broadcast_log(f"[ERROR] Genre tagging error: {e}\n")
            return {"success": False, "error": str(e)}
        finally:
            self.current_task = None
            if not self._abort_requested:
                self.task_progress = {"status": "idle", "action": None, "current": 0, "total": 0, "message": "Genre tagging complete"}

    def get_library_genre_stats(self) -> Dict[str, Any]:
        """Get distribution of genres across cataloged tracks."""
        db_path = os.path.join(self.beets_dir, "library.db")
        stats = []
        total_tagged = 0
        total_tracks = 0
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT count(*) FROM items")
            total_tracks = c.fetchone()[0]

            c.execute("SELECT count(*) FROM items WHERE genre IS NOT NULL AND genre != ''")
            total_tagged = c.fetchone()[0]

            c.execute("""
                SELECT genre, count(*) as cnt 
                FROM items 
                WHERE genre IS NOT NULL AND genre != '' 
                GROUP BY genre 
                ORDER BY cnt DESC 
                LIMIT 30
            """)
            stats = [{"genre": r[0], "count": r[1]} for r in c.fetchall()]
            conn.close()
        except Exception as e:
            logger.error(f"Error getting genre stats: {e}")

        return {
            "total_tracks": total_tracks,
            "total_tagged": total_tagged,
            "untagged": max(0, total_tracks - total_tagged),
            "top_genres": stats
        }

    @staticmethod
    def _item_quality_score(it: Dict[str, Any]) -> float:
        """Calculate quality score for an item to select best keeper among duplicates."""
        format_scores = {
            'flac': 100, 'wav': 90, 'alac': 90,
            'aac': 80, 'm4a': 80,
            'ogg': 70, 'opus': 70,
            'mp3': 60,
        }
        score = 0.0
        # 1. Album track preference over Non-Album track
        is_non_alb = (it.get('album') or '').strip().lower() in ('non-album', 'unknown album', '') or not it.get('album_id')
        if not is_non_alb:
            score += 100000.0

        # 2. Format score
        fmt = (it.get('format') or '').lower()
        score += format_scores.get(fmt, 50) * 1000.0

        # 3. Bitrate (kbps)
        bitrate = it.get('bitrate') or 0
        score += min(int(bitrate / 1000), 500) * 10.0

        # 4. Metadata richness
        meta_points = 0.0
        if it.get('mb_trackid'): meta_points += 50.0
        if it.get('acoustid_id'): meta_points += 30.0
        if it.get('mb_albumid'): meta_points += 20.0
        if it.get('mb_artistid'): meta_points += 10.0
        if it.get('isrc'): meta_points += 10.0
        if it.get('genre'): meta_points += 10.0
        if it.get('lyrics'): meta_points += 10.0
        if it.get('year') and it.get('year') > 0: meta_points += 5.0
        score += meta_points

        # 5. Canonical ASCII path bonus
        p = it.get('clean_path', '')
        if '’' not in p and '‐' not in p and '“' not in p and '”' not in p:
            score += 2.0

        # 6. Newer import ID tiebreak
        score += (it.get('id', 0) / 1000000.0)
        return score

    @staticmethod
    def _normalize_title_for_match(t: str) -> str:
        if not t:
            return ""
        t = t.replace("’", "'").replace("‘", "'").replace('“', '"').replace('”', '"').replace('‐', '-').replace('–', '-').replace('—', '-')
        t = re.sub(r'[\(\[\{].*?[\)\]\}]', '', t)
        t = re.sub(r'\bfeat\.?.*$', '', t, flags=re.IGNORECASE)
        t = re.sub(r'[-–—].*$', '', t)
        t = re.sub(r'[^a-zA-Z0-9]', '', t.lower())
        return t.strip()

    @classmethod
    def _track_titles_match(cls, t1: str, t2: str) -> bool:
        from difflib import SequenceMatcher
        n1 = cls._normalize_title_for_match(t1)
        n2 = cls._normalize_title_for_match(t2)
        if not n1 or not n2:
            return False
        if n1 == n2:
            return True
        if n1 in n2 or n2 in n1:
            if len(n1) >= 4 and len(n2) >= 4:
                return True
        return SequenceMatcher(None, n1, n2).ratio() > 0.8

    async def sanitize_and_deduplicate_library(self) -> Dict[str, Any]:
        """Prune dead records, consolidate duplicate physical file references, delete lesser duplicates, and normalize paths."""
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            return {"success": False, "error": "Library DB not found"}

        try:
            from collections import defaultdict
            from difflib import SequenceMatcher

            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            genre_cache = self._load_genre_cache()

            c.execute("PRAGMA table_info(items)")
            cols = [col[1] for col in c.fetchall()]

            c.execute("SELECT * FROM items")
            all_rows = c.fetchall()
            items = [dict(zip(cols, r)) for r in all_rows]

            # 1. Dead records & physical path resolution
            file_map = {}
            dead_ids = set()

            for it in items:
                rpath = it.get('path')
                p = rpath.decode('utf-8', 'replace') if isinstance(rpath, bytes) else str(rpath)
                full_p = p if p.startswith('/') else os.path.join(self.music_dir, p)
                full_p = os.path.normpath(full_p)
                it['clean_path'] = full_p
                if os.path.exists(full_p):
                    if full_p not in file_map:
                        file_map[full_p] = []
                    file_map[full_p].append(it)
                else:
                    dead_ids.add(it['id'])

            to_delete_ids = set(dead_ids)
            files_to_delete = set()
            to_update_path = []
            to_update_genre = []

            # 2. Consolidate exact same physical path references
            for full_p, entries in file_map.items():
                if len(entries) > 1:
                    sorted_entries = sorted(entries, key=self._item_quality_score, reverse=True)
                    keeper = sorted_entries[0]
                    for other in sorted_entries[1:]:
                        to_delete_ids.add(other['id'])
                    # If keeper is missing genre, inherit
                    if not keeper.get('genre'):
                        for other in sorted_entries[1:]:
                            if other.get('genre'):
                                keeper['genre'] = other['genre']
                                to_update_genre.append((other['genre'], keeper['id']))
                                break

            # 3. Duplicate clustering using union-find
            parent = {it['id']: it['id'] for it in items if it['id'] not in to_delete_ids}
            def find(i):
                if parent[i] != i:
                    parent[i] = find(parent[i])
                return parent[i]
            def union(i, j):
                pi, pj = find(i), find(j)
                if pi != pj:
                    parent[pi] = pj

            surviving_items = [it for it in items if it['id'] not in to_delete_ids]

            # 3a. Group by lower path (case collisions on disk)
            by_lpath = defaultdict(list)
            for it in surviving_items:
                by_lpath[it['clean_path'].lower()].append(it)
            for lp, group in by_lpath.items():
                if len(group) > 1:
                    for it in group[1:]:
                        union(group[0]['id'], it['id'])

            # 3b. Group within the same album
            by_album = defaultdict(list)
            for it in surviving_items:
                alb_id = it.get('album_id')
                if alb_id:
                    by_album[alb_id].append(it)

            for alb_id, alb_items in by_album.items():
                n = len(alb_items)
                for i in range(n):
                    for j in range(i + 1, n):
                        it_a = alb_items[i]
                        it_b = alb_items[j]

                        # Same MusicBrainz Track ID
                        mb_a = it_a.get('mb_trackid')
                        mb_b = it_b.get('mb_trackid')
                        if mb_a and mb_b and mb_a == mb_b:
                            union(it_a['id'], it_b['id'])
                            continue

                        # Same normalized title & close duration
                        t_match = self._track_titles_match(it_a.get('title'), it_b.get('title'))
                        len_a = it_a.get('length') or 0
                        len_b = it_b.get('length') or 0
                        d_match = abs(len_a - len_b) <= 15.0 or (len_a == 0 and len_b == 0)

                        if t_match and d_match:
                            union(it_a['id'], it_b['id'])
                            continue

                        # Same disc and track number AND similar title
                        if it_a.get('track') and it_a.get('track') == it_b.get('track'):
                            disc_a = it_a.get('disc') or 1
                            disc_b = it_b.get('disc') or 1
                            if disc_a == disc_b:
                                ratio = SequenceMatcher(None, self._normalize_title_for_match(it_a.get('title')), self._normalize_title_for_match(it_b.get('title'))).ratio()
                                if ratio > 0.6 and d_match:
                                    union(it_a['id'], it_b['id'])

            # 3c. Redundant loose / Non-Album tracks matching cataloged album tracks
            by_artist = defaultdict(list)
            for it in surviving_items:
                art = (it.get('artist') or '').strip().lower()
                if art:
                    by_artist[art].append(it)

            for art, art_items in by_artist.items():
                non_albs = [x for x in art_items if not x.get('album_id') or (x.get('album') or '').strip().lower() in ('non-album', 'unknown album', '')]
                albs = [x for x in art_items if x.get('album_id') and (x.get('album') or '').strip().lower() not in ('non-album', 'unknown album', '')]
                for na in non_albs:
                    for a in albs:
                        len_na = na.get('length') or 0
                        len_a = a.get('length') or 0
                        if self._track_titles_match(na.get('title'), a.get('title')) and (abs(len_na - len_a) <= 8.0 or len_na == 0 or len_a == 0):
                            union(na['id'], a['id'])

            # Collect clusters
            clusters = defaultdict(list)
            for it in surviving_items:
                root = find(it['id'])
                clusters[root].append(it)

            dup_clusters = [cl for cl in clusters.values() if len(cl) > 1]
            deleted_dups_count = 0

            for cl in dup_clusters:
                sorted_cl = sorted(cl, key=self._item_quality_score, reverse=True)
                keeper = sorted_cl[0]
                keeper_path = keeper['clean_path']

                for lesser in sorted_cl[1:]:
                    to_delete_ids.add(lesser['id'])
                    del_path = lesser['clean_path']
                    if os.path.exists(del_path) and os.path.normcase(del_path) != os.path.normcase(keeper_path):
                        files_to_delete.add(del_path)
                    # Inherit genre if keeper missing
                    if not keeper.get('genre') and lesser.get('genre'):
                        keeper['genre'] = lesser['genre']
                        to_update_genre.append((lesser['genre'], keeper['id']))
                    deleted_dups_count += 1

            # 4. Clean Syncthing conflicts on disk
            for root_dir, dirs, files in os.walk(self.music_dir):
                for f in files:
                    if '.sync-conflict-' in f.lower() or f.startswith('.syncthing.'):
                        files_to_delete.add(os.path.join(root_dir, f))

            # 5. Execute file deletions on disk
            deleted_disk_files = 0
            for fp in files_to_delete:
                try:
                    if os.path.exists(fp):
                        os.remove(fp)
                        deleted_disk_files += 1
                except Exception as ex:
                    logger.warning(f"Could not remove duplicate file {fp}: {ex}")

            # 6. Execute DB deletions
            if to_delete_ids:
                c.executemany("DELETE FROM items WHERE id = ?", [(did,) for did in to_delete_ids])
            if to_update_genre:
                c.executemany("UPDATE items SET genre = ? WHERE id = ?", to_update_genre)

            # 7. Artist Casing Normalization across items and albums
            c.execute("""
                SELECT lower(COALESCE(NULLIF(albumartist, ''), artist)) as norm,
                       GROUP_CONCAT(DISTINCT COALESCE(NULLIF(albumartist, ''), artist)) as variants
                FROM items
                WHERE length > 10
                GROUP BY norm
                HAVING COUNT(DISTINCT COALESCE(NULLIF(albumartist, ''), artist)) > 1
            """)
            for norm_art, variants in c.fetchall():
                vars_list = [v.strip() for v in variants.split(',') if v.strip()]
                counts = {}
                for v in vars_list:
                    c.execute("SELECT count(*) FROM items WHERE COALESCE(NULLIF(albumartist, ''), artist) = ?", (v,))
                    counts[v] = c.fetchone()[0]
                canonical = max(counts.items(), key=lambda x: x[1])[0]
                c.execute("UPDATE items SET artist = ? WHERE lower(artist) = ? AND artist != ?", (canonical, norm_art, canonical))
                c.execute("UPDATE items SET albumartist = ? WHERE lower(albumartist) = ? AND albumartist != ?", (canonical, norm_art, canonical))
                c.execute("UPDATE albums SET albumartist = ? WHERE lower(albumartist) = ? AND albumartist != ?", (canonical, norm_art, canonical))

            # 8. Duplicate Album Records Consolidation (same artist and album name)
            c.execute("""
                SELECT lower(COALESCE(NULLIF(a.albumartist, ''), '')) as norm_artist,
                       lower(a.album) as norm_album,
                       GROUP_CONCAT(a.id) as album_ids
                FROM albums a
                WHERE a.album != ''
                GROUP BY norm_artist, norm_album
                HAVING COUNT(a.id) > 1
            """)
            for _, _, ids_str in c.fetchall():
                ids = [int(x) for x in ids_str.split(',')]
                c.execute(f"""
                    SELECT id, albumartist, album, year, artpath, genre,
                           (SELECT count(*) FROM items WHERE album_id = albums.id) 
                    FROM albums 
                    WHERE id IN ({','.join(map(str, ids))})
                """)
                records = c.fetchall()
                if not records:
                    continue
                primary = max(records, key=lambda r: (r[6], 1 if r[4] else 0, -r[0]))
                primary_id = primary[0]
                artpath_to_use = primary[4]
                year_to_use = primary[3]
                genre_to_use = primary[5]
                for r in records:
                    if r[0] == primary_id:
                        continue
                    if not artpath_to_use and r[4]:
                        artpath_to_use = r[4]
                    if (not year_to_use or year_to_use == 0) and r[3]:
                        year_to_use = r[3]
                    if not genre_to_use and r[5]:
                        genre_to_use = r[5]
                    c.execute("UPDATE items SET album_id = ? WHERE album_id = ?", (primary_id, r[0]))
                    c.execute("DELETE FROM albums WHERE id = ?", (r[0],))

                c.execute("""
                    UPDATE albums 
                    SET artpath = COALESCE(NULLIF(artpath, ''), ?),
                        year = CASE WHEN year IS NULL OR year = 0 THEN ? ELSE year END,
                        genre = COALESCE(NULLIF(genre, ''), ?)
                    WHERE id = ?
                """, (artpath_to_use, year_to_use, genre_to_use, primary_id))

            # 9. Prune empty albums and update album genres
            c.execute("""
                DELETE FROM albums 
                WHERE id NOT IN (SELECT DISTINCT album_id FROM items WHERE album_id IS NOT NULL)
            """)

            c.execute("""
                UPDATE albums 
                SET genre = (SELECT items.genre FROM items WHERE items.album_id = albums.id AND items.genre IS NOT NULL AND items.genre != '' LIMIT 1)
                WHERE genre IS NULL OR genre = ''
            """)

            conn.commit()
            conn.close()

            # 10. Clean empty directories under music_dir
            cleaned_dirs = 0
            for root_dir, dirs, files in os.walk(self.music_dir, topdown=False):
                for dir_name in dirs:
                    full_dir = os.path.join(root_dir, dir_name)
                    try:
                        if not os.listdir(full_dir):
                            os.rmdir(full_dir)
                            cleaned_dirs += 1
                    except Exception:
                        pass

            # 11. Defensively enforce group-readable permissions on all cover art files
            for root_dir, _, files in os.walk(self.music_dir):
                for f in files:
                    if f.lower().startswith("cover."):
                        try:
                            os.chmod(os.path.join(root_dir, f), 0o664)
                        except Exception:
                            pass

            # Refresh disk count cache
            self.count_disk_files(force_refresh=True)

            msg = f"[SANITY] Pruned {len(to_delete_ids)} records ({deleted_disk_files} duplicate files deleted from disk across {len(dup_clusters)} duplicate groups)."
            await self.broadcast_log(f"{msg}\n")
            return {
                "success": True,
                "deleted_records": len(to_delete_ids),
                "deleted_disk_files": deleted_disk_files,
                "duplicate_groups": len(dup_clusters),
                "cleaned_empty_dirs": cleaned_dirs
            }
        except Exception as e:
            logger.error(f"Error during library sanitization: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def tag_untagged_library_genres(self) -> int:
        """Fast incremental genre tagging for newly imported or unclassified songs."""
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            return 0

        genre_cache = self._load_genre_cache()
        updated_count = 0

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT DISTINCT artist FROM items WHERE artist != '' AND (genre IS NULL OR genre = '')")
            untagged_artists = [r[0] for r in c.fetchall()]

            if not untagged_artists:
                conn.close()
                return 0

            await self.broadcast_log(f"[AUTO-GENRE] Checking genre tags for {len(untagged_artists)} artist(s)...\n")

            for artist in untagged_artists:
                genre = genre_cache.get(artist)
                if not genre:
                    loop = asyncio.get_event_loop()
                    genre = await loop.run_in_executor(None, self._fetch_artist_genre_lastfm, artist)
                    if genre:
                        genre_cache[artist] = genre
                    else:
                        genre = "Rock"
                        genre_cache[artist] = genre

                c.execute("UPDATE items SET genre = ? WHERE artist = ? AND (genre IS NULL OR genre = '')", (genre, artist))
                cnt = c.rowcount
                updated_count += cnt

                # Mutagen tagging on disk
                c.execute("SELECT path FROM items WHERE artist = ?", (artist,))
                for p_row in c.fetchall():
                    p_str = self.resolve_audio_path(p_row[0])
                    if os.path.exists(p_str):
                        try:
                            import mutagen
                            mfile = mutagen.File(p_str)
                            if mfile is not None:
                                ext = os.path.splitext(p_str)[1].lower()
                                if ext == ".mp3":
                                    from mutagen.id3 import ID3, TCON
                                    if mfile.tags is None:
                                        mfile.add_tags()
                                    mfile.tags["TCON"] = TCON(encoding=3, text=genre)
                                    mfile.save()
                                elif ext in (".flac", ".ogg", ".opus"):
                                    mfile["genre"] = [genre]
                                    mfile.save()
                                elif ext in (".m4a", ".mp4"):
                                    mfile["\xa9gen"] = [genre]
                                    mfile.save()
                        except Exception:
                            pass

            conn.commit()
            self._save_genre_cache(genre_cache)

            c.execute("""
                UPDATE albums 
                SET genre = (SELECT items.genre FROM items WHERE items.album_id = albums.id AND items.genre IS NOT NULL AND items.genre != '' LIMIT 1)
                WHERE genre IS NULL OR genre = ''
            """)
            conn.commit()
            conn.close()

            if updated_count > 0:
                await self.broadcast_log(f"[AUTO-GENRE] Successfully tagged {updated_count} track(s) with rich genres.\n")
        except Exception as e:
            logger.error(f"Error in tag_untagged_library_genres: {e}")

        return updated_count

    # =========================================================================
    # PLAYLIST CREATOR ENGINE
    # =========================================================================


    def resolve_audio_path(self, raw_path) -> str:
        """Resolve any relative or legacy host disk path to container music directory."""
        if isinstance(raw_path, bytes):
            p = raw_path.decode('utf-8', 'replace')
        else:
            p = str(raw_path or '')
        if not p:
            return ''
        if os.path.exists(p):
            return p
        candidate = os.path.join(self.music_dir, p)
        if os.path.exists(candidate):
            return candidate
        if '/Music/' in p:
            cand = os.path.join(self.music_dir, p.split('/Music/', 1)[1])
            if os.path.exists(cand):
                return cand
        if '/music/' in p:
            cand = os.path.join(self.music_dir, p.split('/music/', 1)[1])
            if os.path.exists(cand):
                return cand
        return candidate if not os.path.isabs(p) else p

    def get_track_by_id(self, track_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single track row by SQLite item ID."""
        db_path = os.path.join(self.beets_dir, "library.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE id = ?", (track_id,))
            row = c.fetchone()
            conn.close()
            if row:
                path_str = self.resolve_audio_path(row[6])
                length_sec = max(1, round(float(row[5] or 0)))
                return {
                    "id": row[0],
                    "title": row[1] or "Unknown Title",
                    "artist": row[2] or "Unknown Artist",
                    "album": row[3] or "",
                    "genre": row[4] or "Unclassified",
                    "length": length_sec,
                    "length_str": f"{length_sec // 60}:{length_sec % 60:02d}",
                    "path": path_str,
                    "year": row[7] if len(row) > 7 and row[7] and row[7] > 1900 else "",
                    "file_exists": os.path.exists(path_str)
                }
        except Exception as e:
            logger.error(f"Error fetching track ID {track_id}: {e}")
        return None

    def find_track_by_query(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        """Find track in local Beets library matching artist and title."""
        db_path = os.path.join(self.beets_dir, "library.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            clean_art = re.split(r'[\s(]+(?:feat\.?|ft\.?|featuring)\s+', artist, flags=re.I)[0].split('&')[0].strip()
            clean_title = re.split(r'[\s(]+(?:feat\.?|ft\.?|featuring)\s+', title, flags=re.I)[0].split('(')[0].strip()
            c.execute(
                "SELECT id, title, artist, album, genre, length, path, year FROM items WHERE artist LIKE ? AND title LIKE ? LIMIT 1",
                (f"%{clean_art}%", f"%{clean_title}%")
            )
            row = c.fetchone()
            conn.close()
            if row:
                path_str = self.resolve_audio_path(row[6])
                length_sec = max(1, round(float(row[5] or 0)))
                return {
                    "id": row[0],
                    "title": row[1] or "Unknown Title",
                    "artist": row[2] or "Unknown Artist",
                    "album": row[3] or "",
                    "genre": row[4] or "Unclassified",
                    "length": length_sec,
                    "length_str": f"{length_sec // 60}:{length_sec % 60:02d}",
                    "path": path_str,
                    "year": row[7] if len(row) > 7 and row[7] and row[7] > 1900 else "",
                    "file_exists": os.path.exists(path_str)
                }
        except Exception as e:
            logger.error(f"Error finding track '{artist} - {title}': {e}")
        return None

    def get_deletion_impact(
        self,
        target_type: str,
        target_id: Optional[Any] = None,
        artist_name: Optional[str] = None,
        album_id: Optional[int] = None,
        song_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Calculate the precise impact (albums, tracks, byte size, file paths) of deleting an artist, album, or song."""
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            return {"success": False, "error": "Library DB not found"}

        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        target_name = ""
        items_query = ""
        params = ()

        if target_type == "artist":
            name = artist_name or str(target_id or "")
            target_name = name
            items_query = """
                SELECT id, album_id, album, artist, albumartist, title, track, disc, length, path, year, format
                FROM items
                WHERE artist = ? OR albumartist = ?
                ORDER BY album, disc, track, title
            """
            params = (name, name)
        elif target_type == "album":
            alb_id = album_id if album_id is not None else target_id
            if isinstance(alb_id, int) or (isinstance(alb_id, str) and str(alb_id).isdigit()):
                alb_id_int = int(alb_id)
                c.execute("SELECT album, albumartist, year FROM albums WHERE id = ?", (alb_id_int,))
                arow = c.fetchone()
                if arow:
                    target_name = f"{arow[1]} - {arow[0]}" if arow[1] else arow[0]
                items_query = """
                    SELECT id, album_id, album, artist, albumartist, title, track, disc, length, path, year, format
                    FROM items
                    WHERE album_id = ?
                    ORDER BY disc, track, title
                """
                params = (alb_id_int,)
            else:
                alb_name = str(alb_id or "")
                target_name = alb_name
                items_query = """
                    SELECT id, album_id, album, artist, albumartist, title, track, disc, length, path, year, format
                    FROM items
                    WHERE album = ?
                    ORDER BY disc, track, title
                """
                params = (alb_name,)
        elif target_type == "song":
            s_id = song_id if song_id is not None else target_id
            s_id_int = int(s_id)
            items_query = """
                SELECT id, album_id, album, artist, albumartist, title, track, disc, length, path, year, format
                FROM items
                WHERE id = ?
            """
            params = (s_id_int,)
        else:
            conn.close()
            return {"success": False, "error": f"Invalid target_type: {target_type}"}

        c.execute(items_query, params)
        rows = c.fetchall()

        if rows and not target_name:
            if target_type == "song":
                target_name = f"{rows[0][3]} - {rows[0][5]}"
            elif target_type == "album":
                target_name = f"{rows[0][3]} - {rows[0][2]}"

        from collections import OrderedDict
        albums_dict = OrderedDict()
        total_bytes = 0

        for r in rows:
            t_id = r[0]
            t_alb_id = r[1]
            t_alb_name = r[2] or "Non-Album Tracks"
            t_artist = r[3] or r[4] or "Unknown Artist"
            t_title = r[5] or "Unknown Title"
            t_track_num = r[6] or 0
            t_disc = r[7] or 1
            t_length = max(1, round(float(r[8] or 0)))
            raw_path = r[9]
            t_year = r[10] or ""
            t_format = r[11] or "MP3"

            full_path = self.resolve_audio_path(raw_path)
            file_exists = os.path.exists(full_path)
            file_size = os.path.getsize(full_path) if file_exists else 0
            total_bytes += file_size

            album_key = f"{t_alb_id}_{t_alb_name}"
            if album_key not in albums_dict:
                albums_dict[album_key] = {
                    "album_id": t_alb_id,
                    "album_name": t_alb_name,
                    "artist": t_artist,
                    "year": t_year,
                    "track_count": 0,
                    "total_bytes": 0,
                    "tracks": []
                }

            albums_dict[album_key]["track_count"] += 1
            albums_dict[album_key]["total_bytes"] += file_size
            albums_dict[album_key]["tracks"].append({
                "id": t_id,
                "album_id": t_alb_id,
                "title": t_title,
                "artist": t_artist,
                "album": t_alb_name,
                "track_number": t_track_num,
                "disc": t_disc,
                "duration": f"{t_length // 60}:{t_length % 60:02d}",
                "format": t_format,
                "size_bytes": file_size,
                "size_str": f"{file_size / (1024*1024):.1f} MB" if file_size > 1024*1024 else f"{file_size / 1024:.1f} KB",
                "file_exists": file_exists,
                "path": full_path
            })

        for a in albums_dict.values():
            a_bytes = a["total_bytes"]
            a["size_str"] = f"{a_bytes / (1024*1024):.1f} MB" if a_bytes > 1024*1024 else f"{a_bytes / 1024:.1f} KB"

        conn.close()

        total_tracks = len(rows)
        total_albums = len(albums_dict)
        if total_bytes >= 1024 * 1024 * 1024:
            total_size_str = f"{total_bytes / (1024 * 1024 * 1024):.2f} GB"
        elif total_bytes >= 1024 * 1024:
            total_size_str = f"{total_bytes / (1024 * 1024):.1f} MB"
        else:
            total_size_str = f"{total_bytes / 1024:.1f} KB"

        return {
            "success": True,
            "target_type": target_type,
            "target_name": target_name,
            "total_albums": total_albums,
            "total_tracks": total_tracks,
            "total_bytes": total_bytes,
            "total_size_str": total_size_str,
            "albums": list(albums_dict.values())
        }

    async def delete_library_items(self, track_ids: List[int], delete_files: bool = True) -> Dict[str, Any]:
        """Permanently delete specified tracks, associated empty album/artist directories, and DB rows."""
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            return {"success": False, "error": "Library DB not found"}

        if not track_ids:
            return {"success": False, "error": "No track IDs provided for deletion"}

        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        placeholders = ",".join("?" for _ in track_ids)
        c.execute(f"SELECT id, album_id, album, artist, albumartist, path FROM items WHERE id IN ({placeholders})", track_ids)
        track_rows = c.fetchall()

        if not track_rows:
            conn.close()
            return {"success": False, "error": "None of the specified tracks were found in the database"}

        affected_album_ids = set()
        affected_artists = set()
        deleted_files_count = 0
        freed_bytes = 0
        album_dirs_to_check = set()
        artist_dirs_to_check = set()

        for r in track_rows:
            t_id = r[0]
            alb_id = r[1]
            artist = r[3]
            albumartist = r[4]
            raw_path = r[5]

            if alb_id:
                affected_album_ids.add(alb_id)
            if artist:
                affected_artists.add(artist)
            if albumartist:
                affected_artists.add(albumartist)

            full_path = self.resolve_audio_path(raw_path)
            if delete_files and full_path and os.path.exists(full_path):
                try:
                    f_size = os.path.getsize(full_path)
                    freed_bytes += f_size
                    parent_dir = os.path.dirname(full_path)
                    album_dirs_to_check.add(parent_dir)
                    artist_dirs_to_check.add(os.path.dirname(parent_dir))
                    os.remove(full_path)
                    deleted_files_count += 1
                except Exception as e:
                    logger.warning(f"Could not remove audio file {full_path}: {e}")

        c.execute(f"DELETE FROM items WHERE id IN ({placeholders})", track_ids)
        conn.commit()

        deleted_albums_count = 0
        for a_id in affected_album_ids:
            c.execute("SELECT count(*) FROM items WHERE album_id = ?", (a_id,))
            remaining = c.fetchone()[0]
            if remaining == 0:
                c.execute("DELETE FROM albums WHERE id = ?", (a_id,))
                deleted_albums_count += 1

        conn.commit()
        conn.close()

        if delete_files:
            for adir in album_dirs_to_check:
                if os.path.exists(adir) and os.path.isdir(adir):
                    try:
                        entries = os.listdir(adir)
                        remaining_files = [f for f in entries if os.path.isfile(os.path.join(adir, f))]
                        audio_remaining = [f for f in remaining_files if os.path.splitext(f)[1].lower() in {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus", ".aac"}]
                        if not audio_remaining:
                            for f in remaining_files:
                                try:
                                    os.remove(os.path.join(adir, f))
                                except Exception:
                                    pass
                            try:
                                os.rmdir(adir)
                            except Exception:
                                pass
                    except Exception as e:
                        logger.warning(f"Error cleaning album dir {adir}: {e}")

            for ardir in artist_dirs_to_check:
                if os.path.exists(ardir) and os.path.isdir(ardir):
                    try:
                        if not os.listdir(ardir):
                            os.rmdir(ardir)
                    except Exception:
                        pass

        self._disk_files_cache = None
        self._last_missing_tracks = None
        if os.path.exists(self.missing_cache_file):
            try:
                os.remove(self.missing_cache_file)
            except Exception:
                pass

        if freed_bytes >= 1024 * 1024 * 1024:
            freed_str = f"{freed_bytes / (1024 * 1024 * 1024):.2f} GB"
        elif freed_bytes >= 1024 * 1024:
            freed_str = f"{freed_bytes / (1024 * 1024):.1f} MB"
        else:
            freed_str = f"{freed_bytes / 1024:.1f} KB"

        await self.broadcast_log(f"\n[LIBRARY] Permanently deleted {len(track_ids)} track(s) ({deleted_files_count} file(s) on disk). Freed {freed_str}.\n")

        return {
            "success": True,
            "deleted_tracks": len(track_ids),
            "deleted_albums": deleted_albums_count,
            "deleted_files": deleted_files_count,
            "freed_bytes": freed_bytes,
            "freed_str": freed_str
        }

    def get_or_create_audio_preview(self, track_id: int) -> Optional[str]:
        """On-demand 30-second preview clip extraction using ffmpeg into /.music_preview."""
        os.makedirs(self.preview_dir, exist_ok=True)
        preview_path = os.path.join(self.preview_dir, f"track_{track_id}.mp3")
        if os.path.exists(preview_path) and os.path.getsize(preview_path) > 1000:
            return preview_path

        track = self.get_track_by_id(track_id)
        if not track or not track.get("path") or not os.path.exists(track["path"]):
            return None

        file_path = track["path"]
        track_len = track.get("length", 180)
        start_sec = max(0, int((track_len - 30) / 2)) if track_len > 45 else 0

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-t", "30",
            "-i", file_path,
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-ar", "44100",
            preview_path
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and os.path.exists(preview_path) and os.path.getsize(preview_path) > 1000:
                return preview_path
            else:
                logger.warning(f"FFmpeg failed creating preview for track {track_id}: {res.stderr}")
        except Exception as e:
            logger.error(f"Exception creating FFmpeg preview for track {track_id}: {e}")
        return None

    def get_or_create_staging_preview(self, rel_path: str) -> Optional[str]:
        """On-demand 30-second preview for files currently in staging (/music_new)."""
        os.makedirs(self.preview_dir, exist_ok=True)
        norm_rel = rel_path.lstrip("/\\")
        full_path = os.path.normpath(os.path.join(self.new_music_dir, norm_rel))
        if not os.path.exists(full_path) or not full_path.startswith(self.new_music_dir):
            return None
        if self.is_ignored_staging_file(os.path.basename(full_path)):
            return None

        h = hashlib.md5(norm_rel.encode("utf-8")).hexdigest()[:16]
        preview_path = os.path.join(self.preview_dir, f"staging_{h}.mp3")
        if os.path.exists(preview_path) and os.path.getsize(preview_path) > 1000:
            return preview_path

        cmd = [
            "ffmpeg", "-y",
            "-ss", "15",
            "-t", "30",
            "-i", full_path,
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-ar", "44100",
            preview_path
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and os.path.exists(preview_path) and os.path.getsize(preview_path) > 1000:
                return preview_path
        except Exception as e:
            logger.error(f"Error creating staging preview for {rel_path}: {e}")
        return None

    def fetch_external_audio_preview(self, artist: str, title: str) -> Dict[str, Any]:
        """Resolve preview on-demand: local library if owned, or cached iTunes 30s preview."""
        cache_key = f"{artist.lower().strip()} - {title.lower().strip()}"
        if cache_key in self._external_preview_cache:
            return self._external_preview_cache[cache_key]

        # 1. Check local library first
        local = self.find_track_by_query(artist, title)
        if local and local.get("id"):
            res = {
                "source": "local",
                "track_id": local["id"],
                "title": local["title"],
                "artist": local["artist"],
                "album": local["album"],
                "genre": local.get("genre", "Rock"),
                "duration": 30,
                "stream_url": f"/api/audio/preview/{local['id']}",
                "artwork": None
            }
            self._external_preview_cache[cache_key] = res
            return res

        # 2. Query Apple iTunes Search API (no key needed, fast, public)
        clean_term = f"{artist} {title}".strip()
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(clean_term)}&entity=song&limit=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                results = data.get('results', [])
                if results:
                    item = results[0]
                    preview_url = item.get('previewUrl')
                    if preview_url:
                        h = hashlib.md5(preview_url.encode('utf-8')).hexdigest()[:16]
                        ext_file = f"ext_{h}.m4a"
                        ext_path = os.path.join(self.preview_dir, ext_file)

                        # Download preview on-demand into /.music_preview
                        if not os.path.exists(ext_path) or os.path.getsize(ext_path) < 500:
                            try:
                                with urllib.request.urlopen(preview_url, timeout=8) as p_resp:
                                    with open(ext_path, 'wb') as pf:
                                        pf.write(p_resp.read())
                            except Exception as down_err:
                                logger.warning(f"Failed downloading preview file {ext_file}: {down_err}")

                        res = {
                            "source": "remote_preview",
                            "track_id": None,
                            "title": item.get('trackName', title),
                            "artist": item.get('artistName', artist),
                            "album": item.get('collectionName', ''),
                            "genre": item.get('primaryGenreName', 'Preview'),
                            "duration": 30,
                            "stream_url": f"/api/audio/preview-cached/{ext_file}" if os.path.exists(ext_path) else preview_url,
                            "artwork": item.get('artworkUrl100')
                        }
                        self._external_preview_cache[cache_key] = res
                        return res
        except Exception as e:
            logger.debug(f"iTunes preview search failed for '{clean_term}': {e}")

        res = {
            "source": "none",
            "track_id": None,
            "title": title,
            "artist": artist,
            "album": "",
            "genre": "",
            "duration": 0,
            "stream_url": None,
            "artwork": None,
            "message": "No audio preview available for this track"
        }
        self._external_preview_cache[cache_key] = res
        return res

    @staticmethod
    def calculate_artist_match_score(query: str, artist_name: str) -> float:
        """Calculate match percentage score (0.0 to 100.0) for an artist name against search query."""
        if not query or not artist_name:
            return 0.0

        def canon(s: str) -> str:
            s = s.lower().strip()
            if s.startswith("the "):
                s = s[4:].strip()
            s = s.replace("&", "and")
            s = re.sub(r'[^\w\s]', '', s)
            return re.sub(r'\s+', ' ', s).strip()

        clean_q = canon(query)
        clean_a = canon(artist_name)
        if not clean_q or not clean_a:
            return 0.0

        # Exact match
        if clean_a == clean_q:
            return 100.0

        words = re.findall(r'\b\w+\b', clean_a)
        q_words = re.findall(r'\b\w+\b', clean_q)

        # All query words present as full words in artist name (e.g. "michael jackson" in "the michael jackson experience")
        if q_words and len(q_words) > 1 and all(qw in words for qw in q_words):
            return 96.0

        # Query is a single word and matches a full word in artist name (e.g. "jackson" in "michael jackson", "jackson 5")
        if clean_q in words:
            return 95.0

        # Plural / singular counterpart (e.g. "jackson" vs "jacksons", "eagle" vs "eagles")
        if clean_a == clean_q + "s" or clean_q == clean_a + "s":
            return 95.0

        # Any word in artist starts with the query word (e.g. "micha" -> "michael jackson")
        for w in words:
            if w.startswith(clean_q) and len(clean_q) >= 3:
                ratio = len(clean_q) / max(1, len(w))
                return round(80.0 + 10.0 * ratio, 1)

        # Word-level fuzzy similarity for typos (e.g. "micheal" in "michael jackson")
        best_word_sim = 0.0
        for w in words:
            w_sim = difflib.SequenceMatcher(None, clean_q, w).ratio() * 100.0
            if w_sim > best_word_sim:
                best_word_sim = w_sim
        if best_word_sim >= 75.0:
            return round(best_word_sim * 0.9, 1)

        # Substring match
        if clean_q in clean_a:
            return 70.0

        # Fuzzy sequence similarity for minor typos
        sim = difflib.SequenceMatcher(None, clean_q, clean_a).ratio() * 100.0
        if sim >= 65.0:
            return round(sim, 1)

        return 0.0

    # -------------------------------------------------------------
    # LIBRARY HIERARCHY EXPLORER (ARTIST -> ALBUM -> SONGS)
    # -------------------------------------------------------------
    def get_library_artists(
        self,
        query: str = "",
        genre: str = "",
        decade: Optional[Any] = None,
        sort_by: str = "artist",
        sort_order: str = "asc",
        page: int = 1,
        limit: int = 25
    ) -> Dict[str, Any]:
        """Fetch paginated library artists with album and track counts, ranked by % match when searching."""
        db_path = os.path.join(self.beets_dir, "library.db")
        page = max(1, page)
        limit = max(1, min(100, limit))
        offset = (page - 1) * limit

        where_clauses = ["items.length > 10", "COALESCE(NULLIF(items.albumartist, ''), items.artist) != ''"]
        sql_params = []

        clean_q = query.strip() if query else ""
        if clean_q:
            q_like = f"%{clean_q}%"
            where_clauses.append("(items.artist LIKE ? OR items.albumartist LIKE ?)")
            sql_params.extend([q_like, q_like])

        # Ignore empty or "all" genres
        if genre and genre.strip() and genre.strip().lower() not in ("", "all", "all genres", "all genre"):
            where_clauses.append("items.genre LIKE ?")
            sql_params.append(f"%{genre.strip()}%")

        # Parse decade safely
        if decade:
            try:
                dec_match = re.search(r'\d{4}', str(decade))
                if dec_match:
                    dec = int(dec_match.group(0))
                    where_clauses.append("items.year >= ? AND items.year < ?")
                    sql_params.extend([dec, dec + 10])
            except (ValueError, TypeError):
                pass

        where_sql = " AND ".join(where_clauses)

        # Determine sorting column and direction
        order_dir = "DESC" if str(sort_order).lower() == "desc" else "ASC"
        s_by = str(sort_by).lower().strip()

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            # When a search query is active, fetch matching artists, calculate match percentage and rank
            if clean_q:
                query_sql = f"""
                    SELECT 
                        COALESCE(NULLIF(items.albumartist, ''), items.artist) as artist_name,
                        COUNT(DISTINCT items.id) as track_count,
                        COUNT(DISTINCT NULLIF(lower(items.album), '')) as album_count,
                        MAX(items.genre) as top_genre,
                        MIN(NULLIF(items.year, 0)) as min_year,
                        MAX(items.year) as max_year,
                        MAX(items.added) as max_added
                    FROM items
                    WHERE {where_sql}
                    GROUP BY lower(artist_name)
                """
                c.execute(query_sql, sql_params)
                all_rows = c.fetchall()

                # Fallback: if LIKE query returned 0 rows, check distinct artists with fuzzy sequence matcher for typos (e.g. 'micheal jackson')
                if not all_rows:
                    fallback_sql = """
                        SELECT 
                            COALESCE(NULLIF(items.albumartist, ''), items.artist) as artist_name,
                            COUNT(DISTINCT items.id) as track_count,
                            COUNT(DISTINCT NULLIF(lower(items.album), '')) as album_count,
                            MAX(items.genre) as top_genre,
                            MIN(NULLIF(items.year, 0)) as min_year,
                            MAX(items.year) as max_year,
                            MAX(items.added) as max_added
                        FROM items
                        WHERE items.length > 10 AND COALESCE(NULLIF(items.albumartist, ''), items.artist) != ''
                        GROUP BY lower(artist_name)
                    """
                    c.execute(fallback_sql)
                    for r in c.fetchall():
                        s = self.calculate_artist_match_score(clean_q, r[0])
                        if s >= 60.0:
                            all_rows.append(r)

                conn.close()

                scored_rows = []
                for r in all_rows:
                    name = r[0]
                    score = self.calculate_artist_match_score(clean_q, name)
                    if score > 0:
                        scored_rows.append((score, r))

                # If sorting by artist or relevance (default search behavior), sort primarily by % match!
                if s_by in ("artist", "relevance", "match") or not s_by:
                    scored_rows.sort(key=lambda x: (x[0], x[1][1]), reverse=True)
                elif s_by in ("album", "albums"):
                    scored_rows.sort(key=lambda x: x[1][2], reverse=(order_dir == "DESC"))
                elif s_by in ("title", "track", "tracks"):
                    scored_rows.sort(key=lambda x: x[1][1], reverse=(order_dir == "DESC"))
                elif s_by in ("year", "era"):
                    scored_rows.sort(key=lambda x: x[1][5] or 0, reverse=(order_dir == "DESC"))
                elif s_by in ("added", "recent"):
                    scored_rows.sort(key=lambda x: x[1][6] or 0, reverse=(order_dir == "DESC"))

                total_artists = len(scored_rows)
                page_rows = scored_rows[offset:offset + limit]

                artists = []
                for score, r in page_rows:
                    name, t_count, a_count, g, min_y, max_y, _ = r
                    year_str = ""
                    if min_y and max_y:
                        year_str = f"{min_y} - {max_y}" if min_y != max_y else str(min_y)
                    elif max_y:
                        year_str = str(max_y)

                    artists.append({
                        "name": name,
                        "artist": name,
                        "track_count": t_count,
                        "album_count": max(1, a_count),
                        "genre": g or "Music",
                        "year_range": year_str,
                        "match_percent": score,
                        "image_url": f"/api/library/artist-art?artist={urllib.parse.quote(name)}"
                    })

                total_pages = max(1, math.ceil(total_artists / limit))
                return {
                    "artists": artists,
                    "total": total_artists,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages
                }

            # Standard browsing (no query): fast SQL paginated path
            if s_by in ("album", "albums"):
                order_col = "album_count"
            elif s_by in ("title", "track", "tracks"):
                order_col = "track_count"
            elif s_by in ("year", "era"):
                order_col = "max_year"
            elif s_by in ("added", "recent"):
                order_col = "max_added"
            else:
                order_col = "artist_name COLLATE NOCASE"

            order_clause = f"{order_col} {order_dir}"
            if order_col != "artist_name COLLATE NOCASE":
                order_clause += ", artist_name COLLATE NOCASE ASC"

            count_sql = f"""
                SELECT COUNT(DISTINCT lower(COALESCE(NULLIF(items.albumartist, ''), items.artist)))
                FROM items
                WHERE {where_sql}
            """
            c.execute(count_sql, sql_params)
            total_artists = c.fetchone()[0]

            query_sql = f"""
                SELECT 
                    COALESCE(NULLIF(items.albumartist, ''), items.artist) as artist_name,
                    COUNT(DISTINCT items.id) as track_count,
                    COUNT(DISTINCT NULLIF(lower(items.album), '')) as album_count,
                    MAX(items.genre) as top_genre,
                    MIN(NULLIF(items.year, 0)) as min_year,
                    MAX(items.year) as max_year,
                    MAX(items.added) as max_added
                FROM items
                WHERE {where_sql}
                GROUP BY lower(artist_name)
                ORDER BY {order_clause}
                LIMIT ? OFFSET ?
            """
            c.execute(query_sql, sql_params + [limit, offset])
            rows = c.fetchall()
            conn.close()

            artists = []
            for r in rows:
                name, t_count, a_count, g, min_y, max_y, _ = r
                year_str = ""
                if min_y and max_y:
                    year_str = f"{min_y} - {max_y}" if min_y != max_y else str(min_y)
                elif max_y:
                    year_str = str(max_y)

                artists.append({
                    "name": name,
                    "artist": name,
                    "track_count": t_count,
                    "album_count": max(1, a_count),
                    "genre": g or "Music",
                    "year_range": year_str,
                    "match_percent": None,
                    "image_url": f"/api/library/artist-art?artist={urllib.parse.quote(name)}"
                })

            total_pages = max(1, math.ceil(total_artists / limit))
            return {
                "artists": artists,
                "total": total_artists,
                "page": page,
                "limit": limit,
                "total_pages": total_pages
            }
        except Exception as e:
            logger.error(f"Error in get_library_artists: {e}", exc_info=True)
            return {"artists": [], "total": 0, "page": page, "limit": limit, "total_pages": 1, "error": str(e)}

    def get_library_artist_albums(self, artist_name: str) -> Dict[str, Any]:
        """Fetch all albums by an artist from Beets library with artwork, years, and track counts."""
        db_path = os.path.join(self.beets_dir, "library.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            c.execute("""
                SELECT 
                    a.id,
                    a.album,
                    a.year,
                    a.genre,
                    a.artpath,
                    COUNT(i.id) as track_count,
                    SUM(i.length) as total_duration
                FROM albums a
                JOIN items i ON i.album_id = a.id
                WHERE lower(a.albumartist) = lower(?) OR lower(i.artist) = lower(?) OR lower(i.albumartist) = lower(?)
                GROUP BY a.id
                ORDER BY a.year DESC, a.album ASC
            """, (artist_name, artist_name, artist_name))
            rows = c.fetchall()
            conn.close()

            albums = []
            for r in rows:
                alb_id, title, year, genre, artpath, t_count, dur = r
                dur_sec = int(dur or 0)
                dur_str = f"{dur_sec // 60}:{dur_sec % 60:02d}" if dur_sec > 0 else ""
                has_art = bool(artpath and len(artpath) > 0)

                albums.append({
                    "id": alb_id,
                    "name": title or "Unknown Album",
                    "year": year or "",
                    "genre": genre or "Music",
                    "track_count": t_count,
                    "duration": dur_str,
                    "has_art": has_art,
                    "art_url": f"/api/library/album-art/{alb_id}" if has_art else None
                })

            return {"artist": artist_name, "albums": albums}
        except Exception as e:
            logger.error(f"Error in get_library_artist_albums for '{artist_name}': {e}", exc_info=True)
            return {"artist": artist_name, "albums": [], "error": str(e)}

    def get_library_album_tracks(self, album_id: int) -> Dict[str, Any]:
        """Fetch all tracks for a given library album ordered by disc and track number."""
        db_path = os.path.join(self.beets_dir, "library.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                SELECT 
                    id,
                    track,
                    title,
                    artist,
                    album,
                    length,
                    year,
                    genre,
                    path
                FROM items
                WHERE album_id = ?
                ORDER BY disc ASC, track ASC, title ASC
            """, (album_id,))
            rows = c.fetchall()
            conn.close()

            tracks = []
            for r in rows:
                tid, track_num, title, artist, album, length, year, genre, raw_path = r
                length_sec = int(length or 0)
                dur_str = f"{length_sec // 60}:{length_sec % 60:02d}" if length_sec > 0 else "0:00"
                path_str = self.resolve_audio_path(raw_path)
                file_exists = bool(path_str and os.path.exists(path_str))
                size_bytes = os.path.getsize(path_str) if file_exists else 0

                tracks.append({
                    "id": tid,
                    "number": track_num or len(tracks) + 1,
                    "title": title or "Untitled Track",
                    "artist": artist or "Unknown Artist",
                    "album": album or "",
                    "duration": dur_str,
                    "length": length_sec,
                    "length_str": dur_str,
                    "year": year if year and year > 1900 else "",
                    "genre": genre or "Unclassified",
                    "path": path_str,
                    "file_exists": file_exists,
                    "size_bytes": size_bytes,
                    "preview_url": f"/api/audio/preview/{tid}"
                })

            return {"album_id": album_id, "tracks": tracks}
        except Exception as e:
            logger.error(f"Error in get_library_album_tracks for album {album_id}: {e}", exc_info=True)
            return {"album_id": album_id, "tracks": [], "error": str(e)}

    @staticmethod
    def get_base_album_name(album_name: str) -> str:
        """Normalize an album name by stripping edition tags to identify the core release."""
        if not album_name:
            return ""
        name = album_name.lower().strip()
        # Remove anything in brackets or parentheses that suggests edition/remaster/deluxe
        name = re.sub(r'\[.*?\]', '', name)
        name = re.sub(
            r'\(.*?(?:deluxe|super\s+deluxe|remaster(?:ed)?|edition|version|bonus|expanded|collector(?:\'s)?|special|anniversary|soundtrack|ost|legacy|tour|international|unplugged|sessions?|live|mono|stereo|mix|explicit|clean).*?\)',
            '',
            name,
            flags=re.IGNORECASE
        )
        # Remove trailing dash/colon clauses
        name = re.sub(
            r'\s*[-:\u2013\u2014]\s*(?:(?:original\s+)?(?:motion\s+picture\s+)?soundtrack|ost|deluxe|super\s+deluxe|remaster(?:ed)?|edition|version|bonus|expanded|collector(?:\'s)?|special|anniversary|legacy).*$',
            '',
            name,
            flags=re.IGNORECASE
        )
        name = re.sub(
            r'\s+(?:deluxe|remaster(?:ed)?|edition|version|bonus|expanded|collector(?:\'s)?|soundtrack)(?:\s+(?:edition|version|release))?$',
            '',
            name,
            flags=re.IGNORECASE
        )
        # Clean up any leftover punctuation or multiple spaces
        name = re.sub(r'[^\w\s]', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name if name else album_name.lower().strip()

    @staticmethod
    def normalize_track_title_for_dedup(title: str) -> str:
        """Normalize track title by stripping version/remaster qualifiers."""
        if not title:
            return ""
        t = title.lower().strip()
        t = re.sub(r'\s*[\[\(](?:remaster|live|deluxe|version|mono|stereo|single|edit|mix)[^\]\)]*[\]\)]', '', t, flags=re.IGNORECASE)
        t = re.sub(r'[\W_]+', ' ', t).strip()
        return t

    def analyze_album_consolidation(self, artist_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze album edition variants (Deluxe, Remaster, etc.) to consolidate into minimal complete albums.
        Identifies duplicate tracks to delete and unique tracks to merge into the primary album edition.
        """
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            return {"success": False, "error": "Library database not found", "groups": []}

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            where_clauses = ["items.length > 10"]
            params = []
            if artist_name and artist_name.strip():
                clean_art = artist_name.strip()
                where_clauses.append("(lower(items.artist) = lower(?) OR lower(items.albumartist) = lower(?))")
                params.extend([clean_art, clean_art])

            where_sql = " AND ".join(where_clauses)
            c.execute(f"""
                SELECT 
                    items.id, items.album_id, items.album, items.title, items.track, items.disc, 
                    items.year, items.length, items.bitrate, items.format, items.path,
                    COALESCE(NULLIF(items.albumartist, ''), items.artist) as effective_artist
                FROM items 
                WHERE {where_sql}
            """, params)
            cols = [col[0] for col in c.description]
            items = [dict(zip(cols, r)) for r in c.fetchall()]
            conn.close()

            # Group items by effective_artist -> base_album_name -> exact_album_name
            artist_album_groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
            for it in items:
                art = it['effective_artist'] or "Unknown Artist"
                alb = it['album'] or "Unknown Album"
                base = self.get_base_album_name(alb)
                artist_album_groups[art][base][alb].append(it)

            groups_res = []
            total_variants = 0
            total_dups = 0
            total_merges = 0
            total_bytes = 0

            for art, base_groups in artist_album_groups.items():
                for base, editions in base_groups.items():
                    # Only consolidate if there are 2 or more album editions for this base title
                    if len(editions) <= 1:
                        continue

                    # Choose primary edition: highest track count, prefer standard over deluxe if equal
                    sorted_editions = sorted(
                        editions.items(),
                        key=lambda x: (
                            len(x[1]),
                            not any(w in x[0].lower() for w in ['deluxe', 'collector', 'special', 'expanded', 'soundtrack']),
                            -len(x[0])
                        ),
                        reverse=True
                    )
                    primary_name, primary_tracks = sorted_editions[0]
                    primary_album_id = primary_tracks[0]['album_id']
                    primary_year = primary_tracks[0]['year'] or ""

                    primary_titles = {}
                    for pt in primary_tracks:
                        nt = self.normalize_track_title_for_dedup(pt['title'])
                        primary_titles[nt] = pt

                    other_editions = []
                    for other_name, other_tracks in sorted_editions[1:]:
                        total_variants += 1
                        dups = []
                        uniques = []
                        for ot in other_tracks:
                            ont = self.normalize_track_title_for_dedup(ot['title'])
                            is_dup = False
                            if ont in primary_titles:
                                pt = primary_titles[ont]
                                len_diff = abs((ot['length'] or 0) - (pt['length'] or 0))
                                if len_diff <= 15 or ot['length'] == 0:
                                    is_dup = True

                            p_str = self.resolve_audio_path(ot.get('path'))
                            sz = os.path.getsize(p_str) if (p_str and os.path.exists(p_str)) else 0

                            t_info = {
                                'id': ot['id'],
                                'title': ot['title'] or "Untitled",
                                'track': ot['track'] or 0,
                                'album': other_name,
                                'duration': f"{int(ot.get('length') or 0) // 60}:{int(ot.get('length') or 0) % 60:02d}",
                                'size_bytes': sz,
                                'path': p_str
                            }

                            if is_dup:
                                dups.append(t_info)
                                total_dups += 1
                                total_bytes += sz
                            else:
                                uniques.append(t_info)
                                total_merges += 1

                        other_editions.append({
                            'album': other_name,
                            'album_id': other_tracks[0]['album_id'],
                            'track_count': len(other_tracks),
                            'duplicate_tracks': dups,
                            'unique_tracks': uniques
                        })

                    group_dups_count = sum(len(e['duplicate_tracks']) for e in other_editions)
                    group_uniques_count = sum(len(e['unique_tracks']) for e in other_editions)
                    group_bytes = sum(sum(t['size_bytes'] for t in e['duplicate_tracks']) for e in other_editions)
                    if group_bytes >= 1024 * 1024 * 1024:
                        group_freed_str = f"{group_bytes / (1024 * 1024 * 1024):.2f} GB"
                    elif group_bytes >= 1024 * 1024:
                        group_freed_str = f"{group_bytes / (1024 * 1024):.1f} MB"
                    else:
                        group_freed_str = f"{group_bytes / 1024:.1f} KB"

                    groups_res.append({
                        'artist': art,
                        'base_name': base,
                        'base_album': base,
                        'primary_album': primary_name,
                        'primary_album_name': primary_name,
                        'primary_album_id': primary_album_id,
                        'primary_year': primary_year,
                        'primary_track_count': len(primary_tracks),
                        'variant_albums': [{'name': e['album'], 'track_count': e['track_count'], 'id': e['album_id']} for e in other_editions],
                        'other_editions': other_editions,
                        'duplicate_tracks_count': group_dups_count,
                        'unique_bonus_tracks_count': group_uniques_count,
                        'freed_bytes': group_bytes,
                        'freed_str': group_freed_str
                    })

            # Sort groups by artist then base album
            groups_res.sort(key=lambda x: (x['artist'].lower(), x['base_album']))

            if total_bytes >= 1024 * 1024 * 1024:
                freed_str = f"{total_bytes / (1024 * 1024 * 1024):.2f} GB"
            elif total_bytes >= 1024 * 1024:
                freed_str = f"{total_bytes / (1024 * 1024):.1f} MB"
            else:
                freed_str = f"{total_bytes / 1024:.1f} KB"

            return {
                "success": True,
                "artist": artist_name,
                "groups_count": len(groups_res),
                "redundant_groups_count": len(groups_res),
                "total_variant_editions": total_variants,
                "total_variants_to_prune": total_variants,
                "total_duplicate_tracks": total_dups,
                "total_unique_tracks_to_merge": total_merges,
                "total_bytes_freed": total_bytes,
                "estimated_freed_bytes": total_bytes,
                "freed_str": freed_str,
                "estimated_freed_str": freed_str,
                "groups": groups_res
            }
        except Exception as e:
            logger.error(f"Error in analyze_album_consolidation: {e}", exc_info=True)
            return {"success": False, "error": str(e), "groups": []}
            return {"success": False, "error": str(e), "groups": []}

    def execute_album_consolidation(
        self,
        artist_name: Optional[str] = None,
        group_bases: Optional[List[str]] = None,
        exclude_track_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Execute consolidation of album variants:
        1. Permanently delete duplicate track audio files from disk.
        2. Remove duplicate track rows from beets SQLite DB.
        3. Merge unique bonus tracks into the primary album by updating their album & album_id.
        4. Clean up orphaned album records in beets DB.
        """
        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            return {"success": False, "error": "Library database not found"}

        analysis = self.analyze_album_consolidation(artist_name)
        if not analysis.get("success"):
            return analysis

        excluded_ids = set(exclude_track_ids or [])
        allowed_bases = set(group_bases) if group_bases else None

        groups_to_process = []
        for g in analysis.get("groups", []):
            if allowed_bases is None or g["base_album"] in allowed_bases:
                groups_to_process.append(g)

        deleted_tracks_count = 0
        deleted_files_count = 0
        merged_tracks_count = 0
        freed_bytes = 0

        tracks_to_delete_ids = []
        tracks_to_merge = []  # tuple of (new_album_name, new_album_id, track_id)

        for g in groups_to_process:
            primary_name = g["primary_album"]
            primary_album_id = g["primary_album_id"]

            for ed in g.get("other_editions", []):
                # Process duplicate tracks
                for dt in ed.get("duplicate_tracks", []):
                    tid = dt["id"]
                    if tid in excluded_ids:
                        continue
                    tracks_to_delete_ids.append(tid)
                    freed_bytes += dt.get("size_bytes", 0)

                    # Delete physical file
                    p = dt.get("path")
                    if p and os.path.exists(p):
                        try:
                            os.remove(p)
                            deleted_files_count += 1
                        except Exception as ex:
                            logger.warning(f"Could not delete physical file {p}: {ex}")

                # Process unique tracks to merge into primary album
                for ut in ed.get("unique_tracks", []):
                    tid = ut["id"]
                    if tid in excluded_ids:
                        continue
                    tracks_to_merge.append((primary_name, primary_album_id, tid))

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            # 1. Delete duplicate tracks from items
            if tracks_to_delete_ids:
                for i in range(0, len(tracks_to_delete_ids), 500):
                    batch = tracks_to_delete_ids[i:i + 500]
                    placeholders = ",".join(["?"] * len(batch))
                    c.execute(f"DELETE FROM items WHERE id IN ({placeholders})", batch)
                deleted_tracks_count = len(tracks_to_delete_ids)

            # 2. Merge unique tracks into primary album
            if tracks_to_merge:
                for new_alb, new_alb_id, tid in tracks_to_merge:
                    c.execute("UPDATE items SET album = ?, album_id = ? WHERE id = ?", (new_alb, new_alb_id, tid))
                merged_tracks_count = len(tracks_to_merge)

            # 3. Clean up orphaned albums in albums table
            c.execute("""
                DELETE FROM albums 
                WHERE id NOT IN (SELECT DISTINCT album_id FROM items WHERE album_id IS NOT NULL)
            """)

            conn.commit()
            conn.close()

            if freed_bytes >= 1024 * 1024 * 1024:
                freed_str = f"{freed_bytes / (1024 * 1024 * 1024):.2f} GB"
            elif freed_bytes >= 1024 * 1024:
                freed_str = f"{freed_bytes / (1024 * 1024):.1f} MB"
            else:
                freed_str = f"{freed_bytes / 1024:.1f} KB"

            return {
                "success": True,
                "artist": artist_name,
                "processed_groups": len(groups_to_process),
                "consolidated_groups": len(groups_to_process),
                "deleted_tracks": deleted_tracks_count,
                "deleted_files": deleted_files_count,
                "merged_tracks": merged_tracks_count,
                "freed_bytes": freed_bytes,
                "freed_str": freed_str
            }
        except Exception as e:
            logger.error(f"Error executing album consolidation: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def get_library_album_art_path(self, album_id: int) -> Optional[str]:
        """Get absolute path to album art cover image for a library album."""
        db_path = os.path.join(self.beets_dir, "library.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT artpath FROM albums WHERE id = ?;", (album_id,))
            row = c.fetchone()
            conn.close()

            if not row or not row[0]:
                return None

            raw_art = row[0]
            if isinstance(raw_art, bytes):
                try:
                    art_str = raw_art.decode("utf-8")
                except UnicodeDecodeError:
                    art_str = raw_art.decode("latin1", errors="replace")
            else:
                art_str = str(raw_art)

            art_str = art_str.replace("\\", "/")
            if os.path.isabs(art_str):
                full_path = art_str
            else:
                full_path = os.path.join(self.music_dir, art_str)

            if os.path.exists(full_path):
                return full_path
            return None
        except Exception as e:
            logger.error(f"Error getting artpath for album {album_id}: {e}")
            return None

    def get_library_artist_art_path(self, artist_name: str) -> Optional[str]:
        """Resolve, fetch, and cache high-resolution artist portrait cover image."""
        if not artist_name or not artist_name.strip():
            return None

        clean_name = artist_name.strip()
        artists_dir = os.path.join(self.preview_dir, "artists")
        try:
            os.makedirs(artists_dir, exist_ok=True)
        except Exception:
            pass

        cache_key = hashlib.md5(clean_name.lower().encode("utf-8")).hexdigest()
        cached_file = os.path.join(artists_dir, f"{cache_key}.jpg")

        # 1. Return cached image if already downloaded
        if os.path.exists(cached_file) and os.path.getsize(cached_file) > 1024:
            return cached_file

        # 2. Try fetching artist portrait from Deezer API
        try:
            url = f"https://api.deezer.com/search/artist?q={urllib.parse.quote(clean_name)}&limit=1"
            req = urllib.request.Request(url, headers={"User-Agent": "MusicManager/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("data", [])
                if results:
                    art_item = results[0]
                    pic_url = art_item.get("picture_big") or art_item.get("picture_medium")
                    if pic_url and "artist-default" not in pic_url:
                        dl_req = urllib.request.Request(pic_url, headers={"User-Agent": "MusicManager/1.0"})
                        with urllib.request.urlopen(dl_req, timeout=6) as img_resp:
                            img_data = img_resp.read()
                            if len(img_data) > 1024:
                                with open(cached_file, "wb") as f:
                                    f.write(img_data)
                                return cached_file
        except Exception as e:
            logger.debug(f"Deezer artist search failed for '{clean_name}': {e}")

        # 3. Fallback: try iTunes album artwork for this artist
        try:
            url = f"https://itunes.apple.com/search?term={urllib.parse.quote(clean_name)}&entity=album&limit=1"
            req = urllib.request.Request(url, headers={"User-Agent": "MusicManager/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                if results:
                    pic_url = results[0].get("artworkUrl100")
                    if pic_url:
                        pic_url = pic_url.replace("100x100bb", "500x500bb")
                        dl_req = urllib.request.Request(pic_url, headers={"User-Agent": "MusicManager/1.0"})
                        with urllib.request.urlopen(dl_req, timeout=6) as img_resp:
                            img_data = img_resp.read()
                            if len(img_data) > 1024:
                                with open(cached_file, "wb") as f:
                                    f.write(img_data)
                                return cached_file
        except Exception as e:
            logger.debug(f"iTunes artwork fallback failed for '{clean_name}': {e}")

        # 4. Fallback: check local library for an album with cover art
        try:
            db_path = os.path.join(self.beets_dir, "library.db")
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                SELECT artpath FROM albums 
                WHERE (albumartist = ? OR id IN (SELECT album_id FROM items WHERE artist = ?))
                  AND artpath IS NOT NULL AND artpath != ''
                LIMIT 1;
            """, (clean_name, clean_name))
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                art_str = row[0].decode("utf-8", errors="replace") if isinstance(row[0], bytes) else str(row[0])
                art_str = art_str.replace("\\", "/")
                full_p = art_str if os.path.isabs(art_str) else os.path.join(self.music_dir, art_str)
                if os.path.exists(full_p):
                    return full_p
        except Exception:
            pass

        return None

    def search_library_tracks(
        self,
        query: str = "",
        genre: str = "",
        decade: Optional[int] = None,
        sort_by: str = "artist",
        sort_order: str = "asc",
        page: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Search and browse the library with pagination, genre/decade filters, and sorting."""
        db_path = os.path.join(self.beets_dir, "library.db")
        page = max(1, page)
        limit = max(1, min(100, limit))
        offset = (page - 1) * limit

        allowed_sorts = {
            "artist": "artist",
            "title": "title",
            "album": "album",
            "year": "year",
            "length": "length",
            "id": "id"
        }
        col_sort = allowed_sorts.get(sort_by.lower(), "artist")
        order_sort = "DESC" if sort_order.lower() == "desc" else "ASC"

        where_clauses = ["items.length > 10"]
        sql_params = []

        if query and query.strip():
            q = f"%{query.strip()}%"
            where_clauses.append("(items.title LIKE ? OR items.artist LIKE ? OR items.album LIKE ?)")
            sql_params.extend([q, q, q])

        if genre and genre.strip():
            g = f"%{genre.strip()}%"
            where_clauses.append("items.genre LIKE ?")
            sql_params.append(g)

        if decade and decade > 1900:
            where_clauses.append("items.year >= ? AND items.year <= ?")
            sql_params.extend([decade, decade + 9])

        where_str = " AND ".join(where_clauses)

        total_tracks = 0
        tracks = []

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            # Count total matches
            count_sql = f"SELECT count(*) FROM items WHERE {where_str}"
            c.execute(count_sql, sql_params)
            c_row = c.fetchone()
            total_tracks = c_row[0] if c_row else 0

            # Fetch paginated rows
            query_sql = f"""
                SELECT id, title, artist, album, genre, length, path, year 
                FROM items 
                WHERE {where_str} 
                ORDER BY {col_sort} {order_sort}, id ASC 
                LIMIT ? OFFSET ?
            """
            c.execute(query_sql, sql_params + [limit, offset])
            rows = c.fetchall()
            conn.close()

            for r in rows:
                path_str = self.resolve_audio_path(r[6])
                length_sec = max(1, round(float(r[5] or 0)))
                dur_str = f"{length_sec // 60}:{length_sec % 60:02d}"
                file_exists = bool(path_str and os.path.exists(path_str))
                size_bytes = os.path.getsize(path_str) if file_exists else 0
                tracks.append({
                    "id": r[0],
                    "title": r[1] or "Unknown Title",
                    "artist": r[2] or "Unknown Artist",
                    "album": r[3] or "-",
                    "genre": r[4] or "Unclassified",
                    "length": length_sec,
                    "length_str": dur_str,
                    "duration": dur_str,
                    "year": r[7] if len(r) > 7 and r[7] and r[7] > 1900 else "",
                    "path": path_str,
                    "file_exists": file_exists,
                    "size_bytes": size_bytes
                })
        except Exception as e:
            logger.error(f"Error searching library tracks: {e}")

        total_pages = math.ceil(total_tracks / limit) if total_tracks > 0 else 1
        return {
            "tracks": tracks,
            "total": total_tracks,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        }

    def get_playlist_meta(self) -> Dict[str, Any]:
        """Return average track length, all library genres, decades, and all detected artists."""
        db_path = os.path.join(self.beets_dir, "library.db")
        avg_length = 234.0
        total_tracks = 0
        genres = []
        decades = []
        top_artists = []

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            c.execute("SELECT count(*), avg(length) FROM items WHERE length > 30 AND length < 1800")
            row = c.fetchone()
            if row and row[0]:
                total_tracks = row[0]
                avg_length = round(float(row[1] or 234.0), 1)

            # ALL detected genres parsed from items, regardless of count
            c.execute("SELECT genre, count(*) FROM items WHERE genre IS NOT NULL AND genre != '' GROUP BY genre")
            raw_genres = c.fetchall()

            genre_counts = {}
            for g_str, cnt in raw_genres:
                parts = [p.strip() for p in g_str.replace(';', ',').replace('/', ',').split(',') if p.strip()]
                for p in parts:
                    genre_counts[p] = genre_counts.get(p, 0) + cnt

            genres = [
                {
                    "id": re.sub(r'[^a-zA-Z0-9_-]', '_', g_name).lower(),
                    "name": g_name,
                    "count": cnt,
                    "keywords": [g_name]
                }
                for g_name, cnt in sorted(genre_counts.items(), key=lambda x: (-x[1], x[0].lower()))
            ]

            # Decades
            c.execute("""
                SELECT (year / 10) * 10 as decade, count(*) 
                FROM items 
                WHERE year >= 1950 AND year <= 2030 
                GROUP BY decade 
                ORDER BY decade ASC
            """)
            decades = [{"decade": r[0], "label": f"{r[0]}s", "count": r[1]} for r in c.fetchall() if r[0]]

            # ALL detected artists in library (returned as strings for clean JS compatibility)
            c.execute("""
                SELECT artist, count(*) as cnt 
                FROM items 
                WHERE artist != '' AND artist NOT LIKE '%Various Artists%' 
                GROUP BY artist 
                ORDER BY cnt DESC, artist ASC
            """)
            artist_rows = c.fetchall()
            top_artists = [r[0] for r in artist_rows]
            artist_counts = {r[0]: r[1] for r in artist_rows}

            conn.close()
        except Exception as e:
            logger.error(f"Error getting playlist metadata: {e}")
            top_artists = []
            artist_counts = {}

        return {
            "avg_track_length": avg_length,
            "total_tracks": total_tracks,
            "genres": genres,
            "decades": decades,
            "top_artists": top_artists,
            "artist_counts": artist_counts
        }

    def get_venn_stats(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate track counts for 1, 2, 3, or 4 circles and all pairwise & core intersections."""
        import itertools
        overlap_type = params.get("overlap_type", "genre_genre")
        targets = params.get("targets")
        if not targets:
            ta = str(params.get("target_a", "")).strip()
            tb = str(params.get("target_b", "")).strip()
            targets = [t for t in [ta, tb] if t]
        if not targets:
            targets = ["Rock", "Blues"]

        # Limit to 4 circles max
        targets = [str(t).strip() for t in targets[:4] if str(t).strip()]
        if not targets:
            targets = ["Rock"]

        db_path = os.path.join(self.beets_dir, "library.db")
        if not os.path.exists(db_path):
            return {"circles": [], "pairwise": [], "regions": [], "count_full_overlap": 0, "count_any_overlap": 0, "total": 0}

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            circles = []
            pairwise = []
            regions = []
            count_full_overlap = 0
            count_any_overlap = 0
            label_overlap = " ∩ ".join(targets)

            circle_colors = ["#8b5cf6", "#06b6d4", "#ec4899", "#f59e0b"]

            if overlap_type == "genre_genre":
                for idx, t in enumerate(targets):
                    c.execute("SELECT count(*) FROM items WHERE length > 30 AND genre LIKE ?", (f"%{t}%",))
                    cnt = c.fetchone()[0]
                    circles.append({
                        "id": f"circle_{idx}",
                        "index": idx,
                        "target": t,
                        "count": cnt,
                        "label": t,
                        "color": circle_colors[idx % len(circle_colors)]
                    })

                # Pairwise Overlaps for every combination of 2 circles
                if len(targets) > 1:
                    for i, j in itertools.combinations(range(len(targets)), 2):
                        t1, t2 = targets[i], targets[j]
                        c.execute("SELECT count(*) FROM items WHERE length > 30 AND genre LIKE ? AND genre LIKE ?", (f"%{t1}%", f"%{t2}%"))
                        cnt_pair = c.fetchone()[0]
                        pairwise.append({
                            "id": f"overlap_{i}_{j}",
                            "type": "pairwise",
                            "indices": [i, j],
                            "label": f"{t1} ∩ {t2}",
                            "targets": [t1, t2],
                            "count": cnt_pair
                        })

                # Full Core Overlap (ALL targets)
                clause_all = " AND ".join(["genre LIKE ?"] * len(targets))
                args_all = [f"%{t}%" for t in targets]
                c.execute(f"SELECT count(*) FROM items WHERE length > 30 AND ({clause_all})", args_all)
                count_full_overlap = c.fetchone()[0]

                # Union (ANY target)
                clause_any = " OR ".join(["genre LIKE ?"] * len(targets))
                args_any = [f"%{t}%" for t in targets]
                c.execute(f"SELECT count(*) FROM items WHERE length > 30 AND ({clause_any})", args_any)
                count_any_overlap = c.fetchone()[0]

            elif overlap_type == "artist_artist":
                artist_genre_sets = []
                for idx, t in enumerate(targets):
                    c.execute("SELECT count(*) FROM items WHERE length > 30 AND artist = ?", (t,))
                    cnt = c.fetchone()[0]
                    circles.append({
                        "id": f"circle_{idx}",
                        "index": idx,
                        "target": t,
                        "count": cnt,
                        "label": t,
                        "color": circle_colors[idx % len(circle_colors)]
                    })

                    c.execute("SELECT DISTINCT genre FROM items WHERE artist = ? AND genre IS NOT NULL AND genre != ''", (t,))
                    g_raw = [r[0] for r in c.fetchall()]
                    s = set()
                    for g in g_raw:
                        for p in g.replace(';', ',').replace('/', ',').split(','):
                            if p.strip(): s.add(p.strip())
                    artist_genre_sets.append(s)

                if len(targets) == 1:
                    count_full_overlap = circles[0]["count"]
                    count_any_overlap = circles[0]["count"]
                else:
                    # Pairwise bridges
                    for i, j in itertools.combinations(range(len(targets)), 2):
                        t1, t2 = targets[i], targets[j]
                        shared_pair = artist_genre_sets[i] & artist_genre_sets[j]
                        if shared_pair:
                            clause_sh = " OR ".join(["genre LIKE ?"] * len(shared_pair))
                            args_sh = [f"%{k}%" for k in shared_pair]
                            c.execute(f"SELECT count(*) FROM items WHERE length > 30 AND ({clause_sh})", args_sh)
                            cnt_pair = c.fetchone()[0]
                        else:
                            cnt_pair = 0
                        pairwise.append({
                            "id": f"overlap_{i}_{j}",
                            "type": "pairwise",
                            "indices": [i, j],
                            "label": f"{t1} ∩ {t2}",
                            "targets": [t1, t2],
                            "count": cnt_pair
                        })

                    shared_all = set.intersection(*artist_genre_sets) if artist_genre_sets else set()
                    if shared_all:
                        clause_sh = " OR ".join(["genre LIKE ?"] * len(shared_all))
                        not_art = " AND ".join(["artist != ?"] * len(targets))
                        args_sh = [f"%{k}%" for k in shared_all] + targets
                        c.execute(f"SELECT count(*) FROM items WHERE length > 30 AND ({clause_sh}) AND ({not_art})", args_sh)
                        count_full_overlap = c.fetchone()[0]
                        label_overlap = f"Bridge ({', '.join(list(shared_all)[:2])})"
                    else:
                        count_full_overlap = 0
                        label_overlap = "No Direct Shared Genre"

                    count_any_overlap = sum(ci["count"] for ci in circles) + count_full_overlap

            elif overlap_type == "genre_decade":
                for idx, t in enumerate(targets):
                    if idx == 0 and not str(t).isdigit():
                        c.execute("SELECT count(*) FROM items WHERE length > 30 AND genre LIKE ?", (f"%{t}%",))
                        cnt = c.fetchone()[0]
                        circles.append({
                            "id": f"circle_{idx}",
                            "index": idx,
                            "target": t,
                            "count": cnt,
                            "label": t,
                            "color": circle_colors[idx % len(circle_colors)]
                        })
                    else:
                        dec = int(t) if str(t).isdigit() else 1970
                        c.execute("SELECT count(*) FROM items WHERE length > 30 AND (year / 10) * 10 = ?", (dec,))
                        cnt = c.fetchone()[0]
                        circles.append({
                            "id": f"circle_{idx}",
                            "index": idx,
                            "target": str(t),
                            "count": cnt,
                            "label": f"{dec}s",
                            "color": circle_colors[idx % len(circle_colors)]
                        })

                if len(targets) > 1:
                    for i, j in itertools.combinations(range(len(targets)), 2):
                        t1, t2 = targets[i], targets[j]
                        is_d1 = str(t1).isdigit()
                        is_d2 = str(t2).isdigit()
                        if not is_d1 and is_d2:
                            c.execute("SELECT count(*) FROM items WHERE length > 30 AND genre LIKE ? AND (year / 10) * 10 = ?", (f"%{t1}%", int(t2)))
                            cnt_pair = c.fetchone()[0]
                            lbl = f"{t2}s {t1}"
                        elif is_d1 and not is_d2:
                            c.execute("SELECT count(*) FROM items WHERE length > 30 AND (year / 10) * 10 = ? AND genre LIKE ?", (int(t1), f"%{t2}%"))
                            cnt_pair = c.fetchone()[0]
                            lbl = f"{t1}s {t2}"
                        elif not is_d1 and not is_d2:
                            c.execute("SELECT count(*) FROM items WHERE length > 30 AND genre LIKE ? AND genre LIKE ?", (f"%{t1}%", f"%{t2}%"))
                            cnt_pair = c.fetchone()[0]
                            lbl = f"{t1} ∩ {t2}"
                        else:
                            cnt_pair = 0
                            lbl = f"{t1}s ∩ {t2}s"
                        pairwise.append({
                            "id": f"overlap_{i}_{j}",
                            "type": "pairwise",
                            "indices": [i, j],
                            "label": lbl,
                            "targets": [t1, t2],
                            "count": cnt_pair
                        })

                    g = targets[0]
                    dec = int(targets[1]) if str(targets[1]).isdigit() else 1970
                    c.execute("SELECT count(*) FROM items WHERE length > 30 AND genre LIKE ? AND (year / 10) * 10 = ?", (f"%{g}%", dec))
                    count_full_overlap = c.fetchone()[0]
                    label_overlap = f"{dec}s {g}"

                    c.execute("SELECT count(*) FROM items WHERE length > 30 AND (genre LIKE ? OR (year / 10) * 10 = ?)", (f"%{g}%", dec))
                    count_any_overlap = c.fetchone()[0]
                else:
                    count_full_overlap = circles[0]["count"]
                    count_any_overlap = circles[0]["count"]

            conn.close()

            # Compile selectable regions list for the frontend
            if len(targets) > 1:
                # 1. Full Core Overlap (all targets)
                core_label = " ∩ ".join(targets) + (" (Sweet Spot)" if len(targets) == 2 else f" (All {len(targets)} Core)")
                regions.append({
                    "id": "overlap_core",
                    "type": "core",
                    "label": core_label,
                    "targets": list(targets),
                    "count": max(0, count_full_overlap),
                    "color": "#c084fc",
                    "icon": "fa-bullseye"
                })

                # 2. Pairwise overlaps
                for p in pairwise:
                    regions.append({
                        "id": p["id"],
                        "type": "pairwise",
                        "label": p["label"],
                        "targets": p["targets"],
                        "count": p["count"],
                        "color": "#38bdf8",
                        "icon": "fa-circle-nodes"
                    })

                # 3. Individual Circles
                for c_item in circles:
                    regions.append({
                        "id": c_item["id"],
                        "type": "circle",
                        "label": f"{c_item['label']} (Circle)",
                        "targets": [c_item["target"]],
                        "count": c_item["count"],
                        "color": c_item["color"],
                        "icon": "fa-circle"
                    })

                # 4. Total Combined Pool (Union)
                regions.append({
                    "id": "union_all",
                    "type": "union",
                    "label": f"Combined Pool (Any of {len(targets)})",
                    "targets": list(targets),
                    "count": max(0, count_any_overlap),
                    "color": "#a855f7",
                    "icon": "fa-layer-group"
                })
            else:
                c_item = circles[0]
                regions.append({
                    "id": "circle_0",
                    "type": "circle",
                    "label": c_item["label"],
                    "targets": [c_item["target"]],
                    "count": c_item["count"],
                    "color": c_item["color"],
                    "icon": "fa-circle"
                })

            return {
                "success": True,
                "overlap_type": overlap_type,
                "circles": circles,
                "pairwise": pairwise,
                "regions": regions,
                "count_full_overlap": max(0, count_full_overlap),
                "count_any_overlap": count_any_overlap,
                "count_a_only": max(0, circles[0]["count"] - count_full_overlap if len(circles) > 0 else 0),
                "count_b_only": max(0, circles[1]["count"] - count_full_overlap if len(circles) > 1 else 0),
                "count_overlap": max(0, count_full_overlap),
                "label_a": circles[0]["label"] if len(circles) > 0 else "",
                "label_b": circles[1]["label"] if len(circles) > 1 else "",
                "label_overlap": label_overlap,
                "total": count_any_overlap
            }
        except Exception as e:
            logger.error(f"Error calculating dynamic venn stats: {e}", exc_info=True)
            if conn:
                try: conn.close()
                except Exception: pass
            return {
                "success": False,
                "error": str(e),
                "circles": [],
                "pairwise": [],
                "regions": [],
                "count_full_overlap": 0,
                "count_any_overlap": 0,
                "total": 0
            }

    def generate_playlist_name(self, mode: str, params: Dict[str, Any], tracks: List[Dict[str, Any]], ai_suggested_name: Optional[str] = None) -> str:
        """Generate a creative, highly relevant playlist name based on mode, parameters, and curated tracks."""
        if ai_suggested_name and ai_suggested_name.strip():
            clean_ai = ai_suggested_name.strip().strip('"\'')
            if clean_ai.lower() not in ["playlist", "playlist title", "my awesome mix", "my playlist", "untitled"] and len(clean_ai) > 3:
                return clean_ai

        # Extract dominant artists & genres from actual curated tracks
        artist_counts: Dict[str, int] = {}
        genre_counts: Dict[str, int] = {}
        years: List[int] = []
        for t in tracks:
            a = t.get("artist")
            if a and a != "Unknown Artist":
                artist_counts[a] = artist_counts.get(a, 0) + 1
            g = t.get("genre")
            if g and g not in ["Unclassified", "Other", "Music"]:
                genre_counts[g] = genre_counts.get(g, 0) + 1
            y = t.get("year")
            if y and str(y).isdigit() and int(y) > 1900:
                years.append(int(y))

        top_artists = [a for a, _ in sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)]
        top_genres = [g for g, _ in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)]
        clean_top_genre = top_genres[0].split("/")[0].split("&")[0].strip() if top_genres else "Vibe"

        def _clean_g(g_name: str) -> str:
            g = re.sub(r'\s*&\s*[0-9]{2}s\s*', ' ', g_name)
            return re.sub(r'\s+', ' ', g).strip()

        # 1. ARTIST SEED & FLOW
        if mode == "artist_seed":
            seed_artists = params.get("seed_artists", [])
            if not seed_artists and top_artists:
                seed_artists = top_artists[:2]

            if len(seed_artists) == 1:
                seed = seed_artists[0]
                other_artists = [a for a in top_artists if a.lower() != seed.lower()]
                if other_artists and len(tracks) > 3:
                    second_art = other_artists[0]
                    templates = [
                        f"Artist Flow: {seed} & {second_art}",
                        f"{seed} & Echoes Flow",
                        f"In the Orbit of {seed}",
                        f"Artist Flow: {seed} & Related Sounds",
                        f"{seed} & {clean_top_genre} Flow"
                    ]
                    return random.choice(templates)
                else:
                    return f"Artist Flow: {seed} & Beyond"
            elif len(seed_artists) == 2:
                templates = [
                    f"Artist Flow: {seed_artists[0]} & {seed_artists[1]}",
                    f"From {seed_artists[0]} to {seed_artists[1]} Flow",
                    f"{seed_artists[0]} ∩ {seed_artists[1]}: Artist Flow",
                    f"Artist Flow: {seed_artists[0]}, {seed_artists[1]} & Beyond"
                ]
                return random.choice(templates)
            elif len(seed_artists) > 2:
                first_two = ", ".join(seed_artists[:2])
                return f"Artist Flow: {first_two} & Friends"
            return "Artist Flow & Related Sounds"

        # 2. GENRE COMBO
        elif mode == "genre_combo":
            genres = params.get("genres", [])
            if not genres and top_genres:
                genres = top_genres[:2]

            cleaned = [_clean_g(g) for g in genres]
            blend_mode = params.get("blend_mode", "interleaved")

            if len(cleaned) == 1:
                return f"{cleaned[0]} Selection"
            elif len(cleaned) == 2:
                if blend_mode == "interleaved":
                    templates = [
                        f"{cleaned[0]} & {cleaned[1]} Blend",
                        f"{cleaned[0]} x {cleaned[1]} Crossover",
                        f"The {cleaned[0]} & {cleaned[1]} Dialogue",
                        f"{cleaned[0]} & {cleaned[1]} Flow"
                    ]
                elif blend_mode == "grouped":
                    templates = [
                        f"Dual Vibe: {cleaned[0]} to {cleaned[1]}",
                        f"Two Worlds: {cleaned[0]} & {cleaned[1]}",
                        f"{cleaned[0]} & {cleaned[1]} Sessions"
                    ]
                else:
                    templates = [
                        f"{cleaned[0]} & {cleaned[1]} Shuffle",
                        f"{cleaned[0]} meets {cleaned[1]} Mix",
                        f"{cleaned[0]} & {cleaned[1]} Fusion"
                    ]
                return random.choice(templates)
            elif len(cleaned) > 2:
                return f"{cleaned[0]}, {cleaned[1]} & {cleaned[2]} Combo"
            return "Genre Blend & Flow"

        # 3. DECADE BLEND
        elif mode == "decade":
            decades = sorted(params.get("decades", []))
            chrono = params.get("chronological", True)
            decade_strs = [f"{str(d)[2:]}s" if d >= 1900 else f"{d}s" for d in decades]

            if len(decades) == 1:
                d_str = f"{decades[0]}s"
                templates = [
                    f"{d_str} Time Capsule",
                    f"Golden {d_str} Retrospective",
                    f"Pure {d_str} Vault",
                    f"{d_str} {clean_top_genre} Rewind"
                ]
                return random.choice(templates)
            elif len(decades) == 2:
                if chrono:
                    return f"From the {decade_strs[0]} to the {decade_strs[1]}: Chronological Flow"
                else:
                    return f"{decade_strs[0]} & {decade_strs[1]} Time Travel Mix"
            elif len(decades) > 2:
                if chrono:
                    return f"Through the Decades ({decade_strs[0]} - {decade_strs[-1]})"
                else:
                    return f"Decades Collide: {', '.join(decade_strs[:-1])} & {decade_strs[-1]}"
            return "Decades Time Capsule"

        # 4. VENN OVERLAP
        elif mode == "venn":
            targets = params.get("targets", [])
            if not targets:
                ta = str(params.get("target_a", "")).strip()
                tb = str(params.get("target_b", "")).strip()
                targets = [t for t in [ta, tb] if t]

            overlap_type = params.get("overlap_type", "genre_genre")
            slice_type = params.get("venn_slice", "overlap_only")
            reg = params.get("selected_region")

            reg_prefix = ""
            if reg and isinstance(reg, dict):
                reg_t = reg.get("type")
                if reg_t == "core":
                    reg_prefix = "Sweet Spot: "
                elif reg_t == "intersection":
                    reg_prefix = "Crossroads: "
                elif reg_t == "circle":
                    reg_prefix = "Spotlight on "

            if overlap_type == "artist_artist" and len(targets) >= 2:
                if slice_type == "journey":
                    return f"From {targets[0]} to {targets[1]}: Sonic Journey"
                elif slice_type == "balanced":
                    return f"Vibe Balance: {targets[0]} & {targets[1]}"
                else:
                    return f"{reg_prefix}{targets[0]} ∩ {targets[1]}" if reg_prefix else f"Sonic Crossroads: {targets[0]} & {targets[1]}"
            elif overlap_type == "genre_decade":
                g_part = next((t for t in targets if not str(t).isdigit()), "Rock")
                d_part = next((t for t in targets if str(t).isdigit()), "1970")
                d_str = f"{str(d_part)[2:]}s" if int(d_part) >= 1900 else f"{d_part}s"
                return f"{reg_prefix}{d_str} {g_part} Intersection"
            else:
                if len(targets) >= 2:
                    return f"{reg_prefix}{targets[0]} ∩ {targets[1]}" if reg_prefix else f"Vibe Overlap: {targets[0]} & {targets[1]}"
                elif targets:
                    return f"Venn Spotlight: {targets[0]}"
                return "Vibe Overlap Mix"

        # 5. AI CURATOR
        elif mode == "ai":
            prompt = params.get("prompt", "").strip()
            if prompt:
                p_clean = re.sub(r'^(create|make|curate|generate)\s+(a|an)?\s*', '', prompt, flags=re.IGNORECASE).strip()
                p_words = p_clean.split()
                if len(p_words) > 6:
                    p_short = " ".join(p_words[:6]).title()
                else:
                    p_short = p_clean.title()
                return f"AI Vibe: {p_short}"
            return "AI Curated Vibe"

        # 6. RANDOM / SMART SHUFFLE
        else:
            smart_shuffle = params.get("smart_shuffle", True)
            if top_artists and len(top_artists) >= 2:
                if smart_shuffle:
                    templates = [
                        f"Smart Shuffle: {top_artists[0]}, {top_artists[1]} & Vault Gems",
                        f"Library Flow: {clean_top_genre} & Deep Cuts",
                        f"Eclectic Library Shuffle",
                        f"Handpicked Library Rotation"
                    ]
                else:
                    templates = [
                        f"Wildcard Library Shuffle",
                        f"Random Vault Discovery",
                        f"Deep Cuts & Random Gems"
                    ]
                return random.choice(templates)
            return "Library Flow & Deep Cuts"

    async def generate_playlist(self, params: Dict[str, Any]) -> Dict[str, Any]:

        """Generate a playlist tailored to duration/songs and mode."""
        mode = params.get("mode", "random")
        target_duration_sec = int(params.get("duration_sec", 3600))
        target_tracks = int(params.get("target_tracks", 15))
        limit_by = params.get("limit_by", "time")  # 'time' or 'songs'

        db_path = os.path.join(self.beets_dir, "library.db")
        selected_tracks = []
        seen_ids = set()

        def _format_track_row(r):
            path_str = self.resolve_audio_path(r[6])
            length_sec = max(1, round(float(r[5] or 0)))
            return {
                "id": r[0],
                "title": r[1],
                "artist": r[2],
                "album": r[3],
                "genre": r[4] or "Unclassified",
                "year": r[7] if len(r) > 7 and r[7] and r[7] > 1900 else "",
                "length": length_sec,
                "length_str": f"{length_sec // 60}:{length_sec % 60:02d}",
                "path": path_str,
                "size_bytes": os.path.getsize(path_str) if os.path.exists(path_str) else 0,
                "file_exists": os.path.exists(path_str)
            }

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            # -------------------------------------------------------------
            # MODE 1: GENRE COMBO
            # -------------------------------------------------------------
            if mode == "genre_combo":
                selected_genres = params.get("genres", [])
                blend_mode = params.get("blend_mode", "interleaved")  # interleaved, shuffled, grouped

                # If no specific genres passed, take all
                if not selected_genres:
                    selected_genres = ["Classic & 70s Rock", "Indie & Alternative Rock"]

                # Gather track pools per genre keyword
                meta = self.get_playlist_meta()
                genre_map = {b["name"]: b.get("keywords", [b["name"]]) for b in meta.get("genres", [])}
                genre_map.update({b["id"]: b.get("keywords", [b["name"]]) for b in meta.get("genres", [])})

                genre_pools = {}
                for g_spec in selected_genres:
                    keywords = genre_map.get(g_spec, [g_spec])
                    clause = " OR ".join(["genre LIKE ?"] * len(keywords))
                    params_list = [f"%{k}%" for k in keywords]
                    c.execute(f"SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND ({clause}) ORDER BY RANDOM() LIMIT 250", params_list)
                    genre_pools[g_spec] = [_format_track_row(r) for r in c.fetchall()]

                # Combine pools according to blend_mode
                cur_dur = 0
                if blend_mode == "interleaved":
                    pool_keys = list(genre_pools.keys())
                    indices = {k: 0 for k in pool_keys}
                    while True:
                        progressed = False
                        for k in pool_keys:
                            p = genre_pools[k]
                            idx = indices[k]
                            while idx < len(p) and p[idx]["id"] in seen_ids:
                                idx += 1
                            if idx < len(p):
                                item = p[idx]
                                indices[k] = idx + 1
                                seen_ids.add(item["id"])
                                selected_tracks.append(item)
                                cur_dur += item["length"]
                                progressed = True

                                if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                                    break
                                if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                                    break
                        if not progressed:
                            break
                        if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                            break
                        if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                            break

                elif blend_mode == "grouped":
                    for k, p in genre_pools.items():
                        for item in p:
                            if item["id"] not in seen_ids:
                                seen_ids.add(item["id"])
                                selected_tracks.append(item)
                                cur_dur += item["length"]
                            if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                                break
                            if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                                break

                else:  # shuffled
                    combined = []
                    for p in genre_pools.values():
                        combined.extend(p)
                    random.shuffle(combined)
                    for item in combined:
                        if item["id"] not in seen_ids:
                            seen_ids.add(item["id"])
                            selected_tracks.append(item)
                            cur_dur += item["length"]
                        if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                            break
                        if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                            break

            # -------------------------------------------------------------
            # MODE 2: DOWNLOADED MUSIC (RANDOM / SMART SHUFFLE)
            # -------------------------------------------------------------
            elif mode == "random":
                smart_shuffle = params.get("smart_shuffle", True)
                c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 ORDER BY RANDOM() LIMIT 400")
                candidates = [_format_track_row(r) for r in c.fetchall()]

                cur_dur = 0
                if smart_shuffle:
                    # Ensure no consecutive tracks share same artist
                    last_artist = ""
                    leftover = candidates.copy()
                    while leftover:
                        picked = None
                        for i, item in enumerate(leftover):
                            if item["artist"] != last_artist:
                                picked = leftover.pop(i)
                                break
                        if not picked:
                            picked = leftover.pop(0)

                        if picked["id"] not in seen_ids:
                            seen_ids.add(picked["id"])
                            selected_tracks.append(picked)
                            cur_dur += picked["length"]
                            last_artist = picked["artist"]

                        if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                            break
                        if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                            break
                else:
                    for item in candidates:
                        if item["id"] not in seen_ids:
                            seen_ids.add(item["id"])
                            selected_tracks.append(item)
                            cur_dur += item["length"]
                        if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                            break
                        if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                            break

            # -------------------------------------------------------------
            # MODE 3: DECADE BLEND
            # -------------------------------------------------------------
            elif mode == "decade":
                chosen_decades = params.get("decades", [1970, 1980, 1990])
                chronological = params.get("chronological", True)

                placeholders = ",".join(["?"] * len(chosen_decades))
                order_clause = "ORDER BY year ASC, RANDOM()" if chronological else "ORDER BY RANDOM()"
                c.execute(f"""
                    SELECT id, title, artist, album, genre, length, path, year 
                    FROM items 
                    WHERE length > 30 AND (year / 10) * 10 IN ({placeholders})
                    {order_clause}
                    LIMIT 300
                """, chosen_decades)
                candidates = [_format_track_row(r) for r in c.fetchall()]

                cur_dur = 0
                for item in candidates:
                    if item["id"] not in seen_ids:
                        seen_ids.add(item["id"])
                        selected_tracks.append(item)
                        cur_dur += item["length"]
                    if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                        break
                    if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                        break

            # -------------------------------------------------------------
            # MODE 4: ARTIST SEED & FLOW
            # -------------------------------------------------------------
            elif mode == "artist_seed":
                seed_artists = params.get("seed_artists", [])
                if not seed_artists:
                    seed_artists = ["Pink Floyd"]

                # By default, if multiple artists are selected, focus on balancing them without outside dilution
                include_adjacent = bool(params.get("include_adjacent", len(seed_artists) <= 1))
                num_seeds = len(seed_artists)
                target_per_artist = max(1, math.ceil(target_tracks / num_seeds)) if limit_by == "songs" else 30

                # Fetch candidate pools separately for each artist to ensure balanced representation
                artist_track_pools = {}
                for art in seed_artists:
                    c.execute("""
                        SELECT id, title, artist, album, genre, length, path, year 
                        FROM items 
                        WHERE length > 30 AND (lower(artist) = lower(?) OR lower(albumartist) = lower(?))
                        ORDER BY RANDOM() 
                        LIMIT ?
                    """, (art, art, max(50, target_per_artist * 4)))
                    artist_track_pools[art] = [_format_track_row(r) for r in c.fetchall()]

                # Round-robin interleaved pool across all seed artists
                seed_tracks = []
                indices = {art: 0 for art in seed_artists}
                counts = {art: 0 for art in seed_artists}

                while True:
                    progress = False
                    for art in seed_artists:
                        pool = artist_track_pools[art]
                        idx = indices[art]
                        while idx < len(pool) and pool[idx]["id"] in seen_ids:
                            idx += 1
                        if idx < len(pool):
                            # In strict artist mode, stop adding to this artist if quota reached and other artists still have tracks
                            if not include_adjacent and limit_by == "songs" and counts[art] >= target_per_artist and any(counts[o] < target_per_artist and indices[o] < len(artist_track_pools[o]) for o in seed_artists):
                                pass
                            else:
                                item = pool[idx]
                                indices[art] = idx + 1
                                counts[art] += 1
                                seed_tracks.append(item)
                                progress = True
                    if not progress:
                        break
                    if not include_adjacent and limit_by == "songs" and len(seed_tracks) >= target_tracks:
                        break
                    if not include_adjacent and limit_by == "time":
                        cur_sec = sum(t["length"] for t in seed_tracks)
                        if cur_sec >= target_duration_sec:
                            break

                adjacent_tracks = []
                if include_adjacent:
                    # Find genres of seed artists to pull adjacent artists
                    seed_genres = set([t["genre"] for t in seed_tracks if t["genre"] and t["genre"] != "Unclassified"])
                    if seed_genres:
                        seed_placeholders = ",".join(["?"] * len(seed_artists))
                        g_clauses = " OR ".join(["genre LIKE ?"] * len(seed_genres))
                        c.execute(f"SELECT id, title, artist, album, genre, length, path, year FROM items WHERE ({g_clauses}) AND artist NOT IN ({seed_placeholders}) ORDER BY RANDOM() LIMIT 150", [f"%{g}%" for g in seed_genres] + seed_artists)
                        adjacent_tracks = [_format_track_row(r) for r in c.fetchall()]

                # Interleave balanced seed tracks with adjacent tracks
                cur_dur = 0
                if include_adjacent and adjacent_tracks:
                    mix = []
                    s_idx, a_idx = 0, 0
                    while s_idx < len(seed_tracks) or a_idx < len(adjacent_tracks):
                        if s_idx < len(seed_tracks):
                            mix.append(seed_tracks[s_idx])
                            s_idx += 1
                        if s_idx < len(seed_tracks):
                            mix.append(seed_tracks[s_idx])
                            s_idx += 1
                        if a_idx < len(adjacent_tracks):
                            mix.append(adjacent_tracks[a_idx])
                            a_idx += 1
                        if len(mix) > (target_tracks * 2):
                            break
                    candidates_final = mix
                else:
                    candidates_final = seed_tracks

                for item in candidates_final:
                    if item["id"] not in seen_ids:
                        seen_ids.add(item["id"])
                        selected_tracks.append(item)
                        cur_dur += item["length"]
                    if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                        break
                    if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                        break

            # -------------------------------------------------------------
            # MODE 5: AI CURATOR (OLLAMA)
            # -------------------------------------------------------------
            elif mode == "ai":
                ai_prompt = params.get("prompt", "High energy road trip mix with driving rhythms and anthems")
                ai_model = params.get("model") or self.ollama_default_model

                # Get sample artists from library
                c.execute("SELECT DISTINCT artist FROM items WHERE artist != '' ORDER BY RANDOM() LIMIT 40")
                sample_artists = [r[0] for r in c.fetchall()]

                system_prompt = (
                    "You are an expert AI Music DJ. Create an awesome, cohesive playlist tracklist. "
                    f"User Theme / Direction: '{ai_prompt}'.\n"
                    f"Prioritize artists and songs that fit this vibe, especially drawing inspiration from this library: {', '.join(sample_artists[:25])}.\n"
                    "Output MUST be ONLY valid JSON adhering to this schema:\n"
                    '{"playlist_name": "Playlist Title", "tracks": [{"artist": "Artist Name", "title": "Track Title"}]}'
                )

                payload = {
                    "model": ai_model,
                    "prompt": f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\nCurate a 25-song playlist for: {ai_prompt}<|im_end|>\n<|im_start|>assistant\n",
                    "stream": False
                }

                data_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.ollama_host}/api/generate",
                    data=data_bytes,
                    headers={"Content-Type": "application/json", "User-Agent": "OMV-MusicManager"}
                )

                try:
                    loop = asyncio.get_event_loop()
                    resp_data = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=120).read().decode("utf-8"))
                    parsed_resp = json.loads(resp_data)
                    raw_text = parsed_resp.get("response", "")
                    clean_json = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
                    code_block = re.search(r'```(?:json)?\s*(\{.*\}|\[.*\])\s*```', clean_json, re.DOTALL)
                    if code_block:
                        clean_json = code_block.group(1).strip()
                    else:
                        brace_match = re.search(r'(\{.*\})', clean_json, re.DOTALL)
                        if brace_match:
                            clean_json = brace_match.group(1).strip()

                    ai_data = json.loads(clean_json)
                    suggested_tracks = ai_data.get("tracks", [])

                    # Match suggestions to SQLite library
                    cur_dur = 0
                    for st in suggested_tracks:
                        art = st.get("artist", "").strip()
                        tit = st.get("title", "").strip()
                        if not art:
                            continue

                        # Exact or close title match
                        c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE artist LIKE ? AND title LIKE ? LIMIT 1", (f"%{art}%", f"%{tit}%"))
                        row = c.fetchone()
                        if not row:
                            # Fallback to any song by this artist in library
                            c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE artist LIKE ? ORDER BY RANDOM() LIMIT 1", (f"%{art}%",))
                            row = c.fetchone()

                        if row and row[0] not in seen_ids:
                            item = _format_track_row(row)
                            seen_ids.add(item["id"])
                            selected_tracks.append(item)
                            cur_dur += item["length"]

                            if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                                break
                            if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                                break

                except Exception as e:
                    logger.warning(f"AI playlist generation failed, falling back to smart shuffle: {e}")

                # If AI returned fewer matches than target, fill in with library tracks
                if (limit_by == "songs" and len(selected_tracks) < target_tracks) or (limit_by == "time" and cur_dur < target_duration_sec - 60):
                    c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 ORDER BY RANDOM() LIMIT 50")
                    for row in c.fetchall():
                        if row[0] not in seen_ids:
                            item = _format_track_row(row)
                            seen_ids.add(item["id"])
                            selected_tracks.append(item)
                            cur_dur += item["length"]
                        if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                            break
                        if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                            break

            # -------------------------------------------------------------
            # MODE 6: DYNAMIC VENN OVERLAP (1 to 4 CIRCLES)
            # -------------------------------------------------------------
            elif mode == "venn":
                overlap_type = params.get("overlap_type", "genre_genre")
                targets = params.get("targets")
                if not targets:
                    ta = str(params.get("target_a", "")).strip()
                    tb = str(params.get("target_b", "")).strip()
                    targets = [t for t in [ta, tb] if t]
                if not targets:
                    targets = ["Rock"]
                targets = [str(t).strip() for t in targets[:4] if str(t).strip()]

                venn_slice = params.get("venn_slice", "overlap_only")  # overlap_only, journey, balanced
                selected_region = params.get("selected_region")

                # -------------------------------------------------------------
                # CASE A: USER SELECTED A SPECIFIC CIRCLE OR OVERLAP REGION
                # -------------------------------------------------------------
                if selected_region and isinstance(selected_region, dict) and selected_region.get("type") != "union":
                    reg_type = selected_region.get("type", "core")
                    reg_targets = selected_region.get("targets", [])
                    if not reg_targets and "target" in selected_region:
                        reg_targets = [selected_region["target"]]

                    candidates = []

                    # 1. Single Circle Selected
                    if reg_type == "circle" or len(reg_targets) == 1:
                        single_target = reg_targets[0] if reg_targets else targets[0]
                        if overlap_type == "artist_artist":
                            c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND artist = ? ORDER BY RANDOM() LIMIT 200", (single_target,))
                        elif overlap_type == "genre_decade" and str(single_target).isdigit():
                            c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND (year / 10) * 10 = ? ORDER BY RANDOM() LIMIT 200", (int(single_target),))
                        else:
                            c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND genre LIKE ? ORDER BY RANDOM() LIMIT 200", (f"%{single_target}%",))
                        candidates = [_format_track_row(r) for r in c.fetchall()]

                    # 2. Specific Intersection (Pairwise, Triple, or Core Sweet Spot)
                    else:
                        if overlap_type == "genre_genre":
                            clause_all = " AND ".join(["genre LIKE ?"] * len(reg_targets))
                            args_all = [f"%{t}%" for t in reg_targets]
                            c.execute(f"SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND ({clause_all}) ORDER BY RANDOM() LIMIT 200", args_all)
                            candidates = [_format_track_row(r) for r in c.fetchall()]

                            # Graceful pad: If intersection has fewer than target_tracks, pull from pairwise or union of reg_targets
                            if len(candidates) < target_tracks:
                                seen_cand_ids = set(x["id"] for x in candidates)
                                clause_any = " OR ".join(["genre LIKE ?"] * len(reg_targets))
                                c.execute(f"SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND ({clause_any}) ORDER BY RANDOM() LIMIT 150", args_all)
                                for r in c.fetchall():
                                    row_item = _format_track_row(r)
                                    if row_item["id"] not in seen_cand_ids:
                                        candidates.append(row_item)
                                        seen_cand_ids.add(row_item["id"])
                                    if len(candidates) >= target_tracks:
                                        break

                        elif overlap_type == "artist_artist":
                            artist_genre_sets = []
                            for art in reg_targets:
                                c.execute("SELECT DISTINCT genre FROM items WHERE artist = ? AND genre IS NOT NULL AND genre != ''", (art,))
                                g_raw = [r[0] for r in c.fetchall()]
                                s = set()
                                for g in g_raw:
                                    for p in g.replace(';', ',').replace('/', ',').split(','):
                                        if p.strip(): s.add(p.strip())
                                artist_genre_sets.append(s)

                            shared = set.intersection(*artist_genre_sets) if artist_genre_sets else set()
                            if shared:
                                clause_sh = " OR ".join(["genre LIKE ?"] * len(shared))
                                not_art = " AND ".join(["artist != ?"] * len(reg_targets))
                                args_sh = [f"%{k}%" for k in shared] + reg_targets
                                c.execute(f"SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND ({clause_sh}) AND ({not_art}) ORDER BY RANDOM() LIMIT 150", args_sh)
                                candidates = [_format_track_row(r) for r in c.fetchall()]

                            # If empty or short, include tracks by the selected artists
                            if len(candidates) < target_tracks:
                                placeholders = ",".join(["?"] * len(reg_targets))
                                c.execute(f"SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND artist IN ({placeholders}) ORDER BY RANDOM() LIMIT 100", reg_targets)
                                for r in c.fetchall():
                                    candidates.append(_format_track_row(r))

                        elif overlap_type == "genre_decade":
                            genres = [t for t in reg_targets if not str(t).isdigit()]
                            decades = [int(t) for t in reg_targets if str(t).isdigit()]
                            conds = ["length > 30"]
                            c_args = []
                            for g in genres:
                                conds.append("genre LIKE ?")
                                c_args.append(f"%{g}%")
                            for d in decades:
                                conds.append("(year / 10) * 10 = ?")
                                c_args.append(d)
                            c.execute(f"SELECT id, title, artist, album, genre, length, path, year FROM items WHERE {' AND '.join(conds)} ORDER BY RANDOM() LIMIT 200", c_args)
                            candidates = [_format_track_row(r) for r in c.fetchall()]

                    cur_dur = 0
                    for item in candidates:
                        if item["id"] not in seen_ids:
                            seen_ids.add(item["id"])
                            selected_tracks.append(item)
                            cur_dur += item["length"]
                        if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                            break
                        if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                            break

                # -------------------------------------------------------------
                # CASE B: MULTI-CIRCLE BLEND / UNION / FALLBACK
                # -------------------------------------------------------------
                elif len(targets) == 1:
                    t = targets[0]
                    if overlap_type == "artist_artist":
                        c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND artist = ? ORDER BY RANDOM() LIMIT 200", (t,))
                    else:
                        c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND genre LIKE ? ORDER BY RANDOM() LIMIT 200", (f"%{t}%",))
                    for r in c.fetchall():
                        item = _format_track_row(r)
                        selected_tracks.append(item)
                        if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                            break
                        if limit_by == "time" and sum(t["length"] for t in selected_tracks) >= target_duration_sec - 45:
                            break
                else:
                    # 2, 3, or 4 Circles
                    circle_pools = {}
                    for t in targets:
                        if overlap_type == "artist_artist":
                            c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND artist = ? ORDER BY RANDOM() LIMIT 100", (t,))
                        else:
                            c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND genre LIKE ? ORDER BY RANDOM() LIMIT 150", (f"%{t}%",))
                        circle_pools[t] = [_format_track_row(r) for r in c.fetchall()]

                    # Fetch Full Intersection (tracks matching ALL targets)
                    full_overlap_pool = []
                    if overlap_type == "genre_genre":
                        clause_all = " AND ".join(["genre LIKE ?"] * len(targets))
                        args_all = [f"%{t}%" for t in targets]
                        c.execute(f"SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND ({clause_all}) ORDER BY RANDOM() LIMIT 150", args_all)
                        full_overlap_pool = [_format_track_row(r) for r in c.fetchall()]

                    cur_dur = 0
                    if venn_slice == "overlap_only":
                        candidates = list(full_overlap_pool)
                        if len(candidates) < target_tracks and overlap_type == "genre_genre" and len(targets) > 2:
                            import itertools
                            for pair in itertools.combinations(targets, 2):
                                c.execute("SELECT id, title, artist, album, genre, length, path, year FROM items WHERE length > 30 AND genre LIKE ? AND genre LIKE ? ORDER BY RANDOM() LIMIT 50", (f"%{pair[0]}%", f"%{pair[1]}%"))
                                for r in c.fetchall():
                                    candidates.append(_format_track_row(r))

                        if len(candidates) < target_tracks:
                            for t in targets:
                                candidates.extend(circle_pools.get(t, []))

                        for item in candidates:
                            if item["id"] not in seen_ids:
                                seen_ids.add(item["id"])
                                selected_tracks.append(item)
                                cur_dur += item["length"]
                            if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                                break
                            if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                                break

                    elif venn_slice == "journey":
                        seg_tracks = max(1, target_tracks // len(targets))
                        seg_sec = target_duration_sec // len(targets)

                        for t_idx, t in enumerate(targets):
                            seg_cur = 0
                            for item in circle_pools.get(t, []):
                                if item["id"] not in seen_ids:
                                    seen_ids.add(item["id"])
                                    selected_tracks.append(item)
                                    cur_dur += item["length"]
                                    seg_cur += item["length"]
                                if limit_by == "songs" and len(selected_tracks) >= seg_tracks * (t_idx + 1):
                                    break
                                if limit_by == "time" and cur_dur >= seg_sec * (t_idx + 1):
                                    break

                    else:  # balanced
                        max_len = max(len(p) for p in circle_pools.values()) if circle_pools else 0
                        round_robin = []
                        for i in range(max_len):
                            for t in targets:
                                p = circle_pools.get(t, [])
                                if i < len(p):
                                    round_robin.append(p[i])
                            if len(round_robin) >= target_tracks * 3:
                                break

                        for item in round_robin:
                            if item["id"] not in seen_ids:
                                seen_ids.add(item["id"])
                                selected_tracks.append(item)
                                cur_dur += item["length"]
                            if limit_by == "songs" and len(selected_tracks) >= target_tracks:
                                break
                            if limit_by == "time" and cur_dur >= target_duration_sec - 45:
                                break
        except Exception as e:
            logger.error(f"Error generating playlist: {e}", exc_info=True)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        total_sec = sum(t["length"] for t in selected_tracks)
        total_bytes = sum(t["size_bytes"] for t in selected_tracks)
        genre_dist = {}
        for t in selected_tracks:
            g = t["genre"] or "Other"
            genre_dist[g] = genre_dist.get(g, 0) + 1

        duration_formatted = f"{total_sec // 3600}h {(total_sec % 3600) // 60}m" if total_sec >= 3600 else f"{total_sec // 60}m {total_sec % 60}s"

        user_name = (params.get("playlist_name") or "").strip()
        is_generic_name = not user_name or user_name.lower() in [
            "my playlist", "my awesome mix", "playlist", "playlist title", "new playlist", "untitled"
        ]

        suggested_ai_title = ai_data.get("playlist_name") if (mode == "ai" and "ai_data" in locals() and isinstance(ai_data, dict)) else None

        if not is_generic_name:
            final_name = user_name
        else:
            final_name = self.generate_playlist_name(mode, params, selected_tracks, ai_suggested_name=suggested_ai_title)

        return {
            "success": True,
            "mode": mode,
            "playlist_name": final_name,
            "tracks": selected_tracks,
            "summary": {
                "track_count": len(selected_tracks),
                "total_duration_sec": total_sec,
                "total_duration_str": duration_formatted,
                "total_size_mb": round(total_bytes / (1024 * 1024), 1),
                "genres_breakdown": genre_dist
            }
        }

    # =========================================================================
    # PLAYLIST EXPORT ENGINES
    # =========================================================================

    def build_m3u8_content(self, tracks: List[Dict[str, Any]], playlist_name: str = "Playlist", relative_paths: bool = False) -> str:
        """Generate UTF-8 extended M3U playlist file content."""
        lines = ["#EXTM3U", f"#PLAYLIST:{playlist_name}"]
        for i, t in enumerate(tracks, 1):
            artist = t.get("artist", "Unknown Artist")
            title = t.get("title", "Unknown Title")
            duration = int(t.get("length", 0))
            path = t.get("path", "")
            if not path and t.get("id"):
                try:
                    db_t = self.get_track_by_id(int(t["id"]))
                    if db_t and db_t.get("path"):
                        path = db_t["path"]
                except Exception:
                    pass
            if path and not os.path.exists(path):
                resolved = self.resolve_audio_path(path)
                if os.path.exists(resolved):
                    path = resolved
            ext = os.path.splitext(path)[1] or ".mp3"
            lines.append(f"#EXTINF:{duration},{artist} - {title}")
            if relative_paths:
                clean_name = f"{i:02d}. {artist} - {title}{ext}"
                lines.append(clean_name)
            else:
                lines.append(path if path else f"{i:02d}. {artist} - {title}{ext}")
        return "\n".join(lines)

    def build_pls_content(self, tracks: List[Dict[str, Any]], playlist_name: str = "Playlist", relative_paths: bool = False) -> str:
        """Generate Shoutcast/Winamp PLS playlist format."""
        lines = ["[playlist]", f"NumberOfEntries={len(tracks)}"]
        for i, t in enumerate(tracks, 1):
            artist = t.get("artist", "Unknown Artist")
            title = t.get("title", "Unknown Title")
            duration = int(t.get("length", 0))
            path = t.get("path", "")
            if not path and t.get("id"):
                try:
                    db_t = self.get_track_by_id(int(t["id"]))
                    if db_t and db_t.get("path"):
                        path = db_t["path"]
                except Exception:
                    pass
            if path and not os.path.exists(path):
                resolved = self.resolve_audio_path(path)
                if os.path.exists(resolved):
                    path = resolved
            ext = os.path.splitext(path)[1] or ".mp3"
            file_entry = f"{i:02d}. {artist} - {title}{ext}" if relative_paths else (path if path else f"{i:02d}. {artist} - {title}{ext}")
            lines.append(f"File{i}={file_entry}")
            lines.append(f"Title{i}={artist} - {title}")
            lines.append(f"Length{i}={duration}")
        lines.append("Version=2")
        return "\n".join(lines)

    def create_playlist_zip(self, tracks: List[Dict[str, Any]], playlist_name: str = "playlist") -> str:
        """Create a compressed ZIP file containing all songs and embedded M3U8."""
        export_dir = os.path.join(tempfile.gettempdir(), "playlist_exports")
        os.makedirs(export_dir, exist_ok=True)

        # Clean old zip files (> 2 hours)
        try:
            now = time.time()
            for old_f in os.listdir(export_dir):
                f_path = os.path.join(export_dir, old_f)
                if old_f.endswith(".zip") and os.path.isfile(f_path) and (now - os.path.getmtime(f_path) > 7200):
                    os.remove(f_path)
        except Exception:
            pass

        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', playlist_name).strip('_') or "playlist"
        zip_filename = f"{safe_name}_{int(time.time())}.zip"
        zip_path = os.path.join(export_dir, zip_filename)

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            # 1. Add M3U8 file with relative paths inside zip
            m3u8_text = self.build_m3u8_content(tracks, safe_name, relative_paths=True)
            zf.writestr(f"{safe_name}.m3u8", m3u8_text.encode("utf-8"))

            # 2. Add each track with nice formatted filename
            for i, t in enumerate(tracks, 1):
                src_path = t.get("path", "")
                if (not src_path or not os.path.exists(src_path)) and t.get("id"):
                    try:
                        db_track = self.get_track_by_id(int(t["id"]))
                        if db_track and db_track.get("path") and os.path.exists(db_track["path"]):
                            src_path = db_track["path"]
                    except Exception:
                        pass
                if src_path and not os.path.exists(src_path):
                    src_path = self.resolve_audio_path(src_path)

                if src_path and os.path.exists(src_path):
                    ext = os.path.splitext(src_path)[1] or ".mp3"
                    artist = re.sub(r'[/\\:*?"<>|]', '_', t.get("artist", "Unknown"))
                    title = re.sub(r'[/\\:*?"<>|]', '_', t.get("title", "Track"))
                    clean_filename = f"{i:02d}. {artist} - {title}{ext}"
                    zf.write(src_path, arcname=clean_filename)

        return zip_path


    # -------------------------------------------------------------
    # ARTIST DISCOGRAPHY & ALBUM DOWNLOAD METHODS
    # -------------------------------------------------------------
    def get_artist_albums(self, artist_id: int, artist_name: str) -> List[Dict[str, Any]]:
        """Fetch and format deduplicated albums for an artist via iTunes Catalog API."""
        import urllib.request
        import urllib.parse
        import json
        import re

        url = f"https://itunes.apple.com/lookup?id={artist_id}&entity=album&limit=60"
        req = urllib.request.Request(url, headers={"User-Agent": "MusicManager/1.5"})
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Error looking up albums for artist {artist_id}: {e}")
            return []

        albums_raw = [x for x in data.get("results", []) if x.get("wrapperType") == "collection"]
        seen_titles = set()
        clean_albums = []

        # Sort by release date descending
        sorted_raw = sorted(albums_raw, key=lambda x: x.get("releaseDate", ""), reverse=True)

        # Get library presence information
        lib_stats = self.get_artist_library_stats(artist_name)
        albums_map = lib_stats.get("albums_map", {})

        for a in sorted_raw:
            raw_name = a.get("collectionName", "")
            if not raw_name:
                continue

            # Normalize title to deduplicate identical remasters / deluxe re-releases
            base_name = re.sub(
                r'(\s*[\(\[][^)]*remaster[^)]*[\)\]]|\s*[\(\[][^)]*deluxe[^)]*[\)\]]|\s*[\(\[][^)]*expanded[^)]*[\)\]]|\s*[\(\[][^)]*anniversary[^)]*[\)\]])',
                '',
                raw_name,
                flags=re.IGNORECASE
            ).strip().lower()

            if base_name in seen_titles:
                continue
            seen_titles.add(base_name)

            year_str = (a.get("releaseDate") or "")[:4]
            art_url = (a.get("artworkUrl100") or "").replace("100x100bb", "300x300bb")

            c_alb = normalize_album_name(raw_name)
            match_info = albums_map.get(c_alb)
            track_count = a.get("trackCount", 0)
            in_lib_cnt = 0
            is_comp = False
            if match_info:
                in_lib_cnt = match_info.get("in_library_count", 0)
                tot_expected = track_count or match_info.get("tracktotal", 0)
                is_comp = bool(tot_expected > 0 and in_lib_cnt >= tot_expected)

            clean_albums.append({
                "id": a.get("collectionId"),
                "name": raw_name,
                "clean_name": base_name,
                "year": year_str,
                "track_count": track_count,
                "in_library_count": in_lib_cnt,
                "is_complete": is_comp,
                "artwork_url": art_url,
                "genre": a.get("primaryGenreName", ""),
                "artist": artist_name,
                "download_query": f"{artist_name} - {raw_name}"
            })

        return clean_albums

    def get_album_tracks(self, album_id: int, artist_name: Optional[str] = None) -> Dict[str, Any]:
        """Fetch all songs in an album from iTunes lookup API with track numbers, durations, and preview URLs."""
        import urllib.request
        import json

        url = f"https://itunes.apple.com/lookup?id={album_id}&entity=song"
        req = urllib.request.Request(url, headers={"User-Agent": "MusicManager/1.5"})
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Error fetching album tracks for album {album_id}: {e}")
            return {"album_id": album_id, "tracks": []}

        # Query owned song titles if artist_name is provided
        owned_titles = set()
        if artist_name:
            try:
                db_path = os.path.join(self.beets_dir, "library.db")
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    c = conn.cursor()
                    c.execute("""
                        SELECT items.title
                        FROM items
                        WHERE LOWER(items.artist) = LOWER(?) OR LOWER(items.albumartist) = LOWER(?)
                    """, (artist_name.strip(), artist_name.strip()))
                    for (t,) in c.fetchall():
                        owned_titles.add(normalize_music_title(t))
                    conn.close()
            except Exception as e:
                logger.error(f"Error fetching owned titles for {artist_name}: {e}")

        results = data.get("results", [])
        tracks = []
        for r in results:
            if r.get("wrapperType") == "track":
                track_name = r.get("trackName")
                if not track_name:
                    continue
                millis = r.get("trackTimeMillis", 0)
                sec = (millis // 1000) % 60
                mins = (millis // 1000) // 60
                duration_str = f"{mins}:{sec:02d}" if millis > 0 else ""
                norm_track = normalize_music_title(track_name)
                in_lib = norm_track in owned_titles

                tracks.append({
                    "id": r.get("trackId"),
                    "number": r.get("trackNumber", len(tracks) + 1),
                    "name": track_name,
                    "duration": duration_str,
                    "preview_url": r.get("previewUrl", ""),
                    "in_library": in_lib
                })

        tracks.sort(key=lambda x: x["number"])
        return {"album_id": album_id, "tracks": tracks}

    def check_artist_and_discography(self, query: str) -> Dict[str, Any]:
        """Search for artist: returns exact discography match or ranked list of matching candidate artists."""
        import urllib.request
        import urllib.parse
        import json
        import re
        import difflib

        q = query.strip()
        if not q:
            return {"match_type": "none", "query": q}

        def canonicalize_art(s: str) -> str:
            s = s.lower().strip()
            if s.startswith("the "):
                s = s[4:].strip()
            s = s.replace("&", " and ")
            s = re.sub(r'[^a-z0-9\s]', '', s)
            s = re.sub(r'\s+', ' ', s).strip()
            return s

        canon_q = canonicalize_art(q)
        q_words = re.findall(r'\b\w+\b', canon_q)

        # Increase limit from 8 to 25 so all legitimate matching artists are fetched
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(q)}&entity=musicArtist&limit=25"
        req = urllib.request.Request(url, headers={"User-Agent": "MusicManager/1.5"})
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Error querying iTunes artist search for '{q}': {e}")
            return {"match_type": "none", "query": q, "error": str(e)}

        results = data.get("results", [])
        if not results:
            return {"match_type": "none", "query": q}

        candidates = []
        seen = set()

        for idx, r in enumerate(results):
            artist_name = r.get("artistName", "").strip()
            if not artist_name:
                continue
            genre = r.get("primaryGenreName", "Music")
            art_id = r.get("artistId")
            art_canon = canonicalize_art(artist_name)

            dedup_key = art_canon
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            score = self.calculate_artist_match_score(q, artist_name)

            # Include any artist with a decent match score (>= 50%)
            if score < 50.0:
                continue

            lib_stats = self.get_artist_library_stats(artist_name)
            in_lib_tracks = lib_stats.get("total_tracks", 0)

            candidates.append({
                "id": art_id,
                "name": artist_name,
                "genre": genre,
                "match_percent": score,
                "in_library_tracks": in_lib_tracks,
                "library_stats": lib_stats,
                "rank": score,
                "is_exact": (art_canon == canon_q),
                "itunes_index": idx
            })

        if not candidates:
            return {"match_type": "none", "query": q}

        # Sort candidates strictly by % match descending!
        # Tie-breakers when % match is equal: in_library_tracks (desc), then iTunes index (asc)
        candidates.sort(key=lambda x: (x["match_percent"], x["in_library_tracks"], -x["itunes_index"]), reverse=True)

        top_cand = candidates[0]
        other_strong_matches = [c for c in candidates[1:] if c["match_percent"] >= 75.0]

        # Exact match bypass should ONLY occur if:
        # 1. The top candidate is an exact match (is_exact is True and was iTunes #0).
        # 2. AND either:
        #    - Query is multi-word (e.g. "Michael Jackson", "Pink Floyd")
        #    - OR there are no other candidate artists with high match score (>= 75%)
        is_unambiguous_exact = (
            top_cand["is_exact"] and
            top_cand["itunes_index"] == 0 and
            (len(q_words) >= 2 or len(other_strong_matches) == 0)
        )

        if is_unambiguous_exact:
            albums = self.get_artist_albums(top_cand["id"], top_cand["name"])
            return {
                "match_type": "exact",
                "artist": top_cand,
                "albums": albums
            }
        else:
            return {
                "match_type": "partial",
                "query": q,
                "artists": candidates[:16]
            }

    async def download_batch_albums(self, artist: str, albums: List[Dict[str, Any]], auto_import: bool = True, auto_complete_album: bool = True) -> Dict[str, Any]:
        """Batch download multiple albums for an artist sequentially with Beets auto-import."""
        queries = []
        seen_tracks = set()
        skipped_count = 0

        await self.broadcast_log(f"\n[ALBUM DOWNLOAD] Preparing tracklists for {artist} ({len(albums)} album(s) selected)...\n")

        for a in albums:
            album_id = a.get("id")
            album_name = a.get("name") or a.get("clean_name") or ""
            fetched_tracks = []

            # 1. If frontend explicitly passed selected_tracks, prioritize them!
            if a.get("selected_tracks"):
                fetched_tracks = a.get("selected_tracks")
            elif album_id:
                try:
                    lookup_url = f"https://itunes.apple.com/lookup?id={album_id}&entity=song"
                    req = urllib.request.Request(lookup_url, headers={"User-Agent": "MusicManager/1.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    fetched_tracks = [
                        x.get("trackName") for x in data.get("results", [])
                        if x.get("wrapperType") == "track" and x.get("trackName")
                    ]
                except Exception as e:
                    logger.warning(f"Could not fetch tracklist for album {album_id}: {e}")

            if fetched_tracks:
                await self.broadcast_log(f"   * Album '{album_name}': {len(fetched_tracks)} tracks selected/found.\n")
                for t in fetched_tracks:
                    # Check if already in library for this album
                    if self.is_song_in_library(artist, t, album=album_name):
                        target_str = f" in '{album_name}'" if album_name else ""
                        await self.broadcast_log(f"   [SKIP] '{artist} - {t}' is already in your library{target_str}.\n")
                        skipped_count += 1
                        continue

                    clean_t = clean_search_query(t)
                    norm_key = clean_t.lower().strip()
                    if norm_key not in seen_tracks:
                        seen_tracks.add(norm_key)
                        queries.append(f"{artist} - {clean_t}")
            elif album_name:
                clean_alb = clean_search_query(album_name)
                queries.append(f"{artist} - {clean_alb}")

        if not queries:
            if skipped_count > 0:
                await self.broadcast_log(f"[INFO] All {skipped_count} track(s) in selected album(s) are already in your library. Nothing to download.\n")
                return {"success": True, "downloaded": 0, "skipped": skipped_count, "message": "All tracks already in library"}
            await self.broadcast_log(f"[ERROR] No valid album tracks found to download for {artist}.\n")
            return {"success": False, "error": "No valid albums provided"}

        if skipped_count > 0:
            await self.broadcast_log(f"[INFO] Skipped {skipped_count} track(s) already owned in library.\n")

        await self.broadcast_log(f"[ALBUM DOWNLOAD] Queuing {len(queries)} unique missing tracks across {len(albums)} album(s)...\n")

        return await self.download_batch_tracks(
            tracks=queries,
            label=f"Albums for {artist}",
            auto_import=auto_import,
            auto_complete_album=auto_complete_album,
            check_library_duplicate=False
        )

