#!/usr/bin/env python3
"""
Music Manager — Standalone Library 5-Genre Bulk Upgrade Engine

This script can be executed directly inside the Docker container or via SSH:
    docker exec -d music_manager python3 /app/app/upgrade_genres_cli.py

Features:
- Runs detached in background without requiring an active terminal session.
- Identifies all artists with fewer than 5 genres and enriches them from Last.fm.
- Preserves existing accurate tags and enriches up to 5 distinct, canonical subgenres.
- Updates Beets SQLite database (items & albums).
- Updates ID3 tags on physical files (mp3, flac, m4a) via mutagen.
- Updates /config/beets/genre_cache.json.
- Real-time logging to /config/genre_update.log and /config/genre_update_progress.json.
"""

import os
import sys
import time
import json
import sqlite3
import argparse
import datetime
from typing import Optional

# Ensure app package is importable
sys.path.insert(0, "/app")

from app.services.manager import MusicManagerService

def log_msg(msg: str, log_file):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{ts}] {msg}"
    print(formatted, flush=True)
    if log_file:
        try:
            log_file.write(formatted + "\n")
            log_file.flush()
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser(description="Enrich Beets music library with up to 5 genres per track.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect what would be updated without modifying database or files.")
    parser.add_argument("--limit", type=int, default=0, help="Limit to N artists for testing.")
    parser.add_argument("--force", action="store_true", help="Re-query all artists even if they already have 5 genres.")
    args = parser.parse_args()

    beets_dir = os.environ.get("BEETSDIR", "/config/beets")
    db_path = os.path.join(beets_dir, "library.db")
    progress_path = "/config/genre_update_progress.json"
    log_path = "/config/genre_update.log"
    pid_path = "/config/genre_update.pid"

    # Write PID file
    my_pid = os.getpid()
    with open(pid_path, "w") as f:
        f.write(str(my_pid))

    log_file = open(log_path, "a", encoding="utf-8")
    start_ts = time.time()

    log_msg("=" * 65, log_file)
    log_msg("Music Manager — Library 5-Genre Bulk Upgrade Started", log_file)
    log_msg(f"PID: {my_pid} | Mode: {'DRY RUN' if args.dry_run else 'LIVE UPDATE'}", log_file)
    log_msg("=" * 65, log_file)

    service = MusicManagerService()
    genre_cache = service._load_genre_cache()

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Query distinct artists and their current genres
    c.execute("SELECT artist, genre, count(*) as track_cnt FROM items WHERE artist != '' GROUP BY artist")
    rows = c.fetchall()

    artists_needing_update = []
    already_5_genres = 0

    for artist, cur_genre, cnt in rows:
        parts = [g.strip() for g in (cur_genre or "").replace(";", ",").split(",") if g.strip()]
        if args.force or len(parts) < 5:
            artists_needing_update.append((artist, cur_genre or "", cnt, len(parts)))
        else:
            already_5_genres += 1

    total_needing = len(artists_needing_update)
    if args.limit > 0:
        artists_needing_update = artists_needing_update[:args.limit]
        total_needing = len(artists_needing_update)

    log_msg(f"Total artists in library: {len(rows)}", log_file)
    log_msg(f"Artists already possessing 5 genres: {already_5_genres}", log_file)
    log_msg(f"Artists scheduled for 5-genre enrichment: {total_needing}", log_file)
    log_msg("-" * 65, log_file)

    updated_artists_count = 0
    updated_tracks_count = 0
    updated_files_count = 0

    # Initialize progress JSON
    progress_data = {
        "status": "running",
        "pid": my_pid,
        "current": 0,
        "total": total_needing,
        "percent": 0.0,
        "tracks_updated": 0,
        "files_updated": 0,
        "current_artist": "",
        "current_genre": "",
        "start_time": datetime.datetime.now().isoformat(),
        "elapsed_sec": 0
    }
    with open(progress_path, "w", encoding="utf-8") as pf:
        json.dump(progress_data, pf, indent=2)

    try:
        for idx, (artist, cur_genre, track_cnt, cur_tag_count) in enumerate(artists_needing_update, 1):
            elapsed = round(time.time() - start_ts, 1)
            pct = round((idx / total_needing) * 100, 1)

            # Query Last.fm
            fetched = service._fetch_artist_genre_lastfm(artist, max_genres=5)
            
            # Merge with existing
            new_genre = service._merge_genre_strings(cur_genre, fetched, max_tags=5) if fetched else (cur_genre or "Rock")
            new_parts_count = len([g for g in new_genre.split(",") if g.strip()])

            is_changed = (new_genre != cur_genre)

            if is_changed and not args.dry_run:
                # Update SQLite items
                c.execute("UPDATE items SET genre = ? WHERE artist = ?", (new_genre, artist))
                # Update SQLite albums
                c.execute("UPDATE albums SET genre = ? WHERE albumartist = ?", (new_genre, artist))
                
                # Update cache
                genre_cache[artist] = new_genre
                updated_artists_count += 1
                updated_tracks_count += track_cnt

                # Mutagen physical file tagging
                c.execute("SELECT path FROM items WHERE artist = ?", (artist,))
                for p_row in c.fetchall():
                    raw_p = p_row[0]
                    p_str = service.resolve_audio_path(raw_p)
                    if os.path.exists(p_str):
                        try:
                            import mutagen
                            mfile = mutagen.File(p_str)
                            if mfile is not None:
                                ext = os.path.splitext(p_str)[1].lower()
                                if ext == ".mp3":
                                    from mutagen.id3 import TCON
                                    if mfile.tags is None:
                                        mfile.add_tags()
                                    mfile.tags["TCON"] = TCON(encoding=3, text=new_genre)
                                    mfile.save()
                                    updated_files_count += 1
                                elif ext in (".flac", ".ogg", ".opus"):
                                    mfile["genre"] = [new_genre]
                                    mfile.save()
                                    updated_files_count += 1
                                elif ext in (".m4a", ".mp4"):
                                    mfile["\xa9gen"] = [new_genre]
                                    mfile.save()
                                    updated_files_count += 1
                        except Exception:
                            pass

            status_str = f"+{new_parts_count - cur_tag_count} genres" if new_parts_count > cur_tag_count else "unchanged"
            log_msg(f"[{idx}/{total_needing}] ({pct}%) '{artist}': '{cur_genre}' -> '{new_genre}' ({status_str}, {track_cnt} tracks)", log_file)

            # Update progress file every 5 artists or at end
            if idx % 5 == 0 or idx == total_needing:
                if not args.dry_run:
                    conn.commit()
                    service._save_genre_cache(genre_cache)

                progress_data.update({
                    "current": idx,
                    "percent": pct,
                    "tracks_updated": updated_tracks_count,
                    "files_updated": updated_files_count,
                    "current_artist": artist,
                    "current_genre": new_genre,
                    "elapsed_sec": elapsed
                })
                try:
                    with open(progress_path, "w", encoding="utf-8") as pf:
                        json.dump(progress_data, pf, indent=2)
                except Exception:
                    pass

            # Respect Last.fm rate limiting
            time.sleep(0.12)

        total_elapsed = round(time.time() - start_ts, 1)
        log_msg("=" * 65, log_file)
        log_msg("Music Manager — Library 5-Genre Upgrade Completed Successfully!", log_file)
        log_msg(f"Total Artists Processed: {total_needing}", log_file)
        log_msg(f"Artists Enriched: {updated_artists_count}", log_file)
        log_msg(f"Total Tracks Updated: {updated_tracks_count}", log_file)
        log_msg(f"Physical Files Tagged: {updated_files_count}", log_file)
        log_msg(f"Total Elapsed Time: {datetime.timedelta(seconds=int(total_elapsed))}", log_file)
        log_msg("=" * 65, log_file)

        progress_data.update({
            "status": "completed",
            "percent": 100.0,
            "elapsed_sec": total_elapsed,
            "completed_at": datetime.datetime.now().isoformat()
        })
        with open(progress_path, "w", encoding="utf-8") as pf:
            json.dump(progress_data, pf, indent=2)

    except Exception as e:
        log_msg(f"[ERROR] Exception occurred during genre upgrade: {e}", log_file)
        progress_data["status"] = f"error: {str(e)}"
        with open(progress_path, "w", encoding="utf-8") as pf:
            json.dump(progress_data, pf, indent=2)
    finally:
        conn.close()
        log_file.close()
        if os.path.exists(pid_path):
            try:
                os.remove(pid_path)
            except Exception:
                pass

if __name__ == "__main__":
    main()
