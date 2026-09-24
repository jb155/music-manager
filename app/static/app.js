// Music Manager Web Frontend Logic
let audioManager;

document.addEventListener("DOMContentLoaded", () => {
    initThemeSelector();
    initTabs();
    initSSE();
    initAbortControls();
    loadLibraryStats();
    loadOllamaServers();
    loadMissingTracks();
    loadStagingFiles();
    initManualUpload();
    initAIRecommendations();
    initPlaylistCreator();
    audioManager = new AudioManager();
    initLibraryBrowser();
    startStatusPoller();
    initUpdateBadge();
    initSlideLockout();
    checkAppVersion();
});

// Toast Notifications
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;

    let icon = "info-circle";
    if (type === "success") icon = "circle-check";
    if (type === "error") icon = "triangle-exclamation";

    toast.innerHTML = `<i class="fa-solid fa-${icon}"></i> <span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = "slideIn 0.3s ease-out reverse forwards";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Version & Update Check
let _latestVersionInfo = null;

function initUpdateBadge() {
    const badge = document.getElementById("update-badge");
    if (badge) {
        badge.addEventListener("click", () => showUpdateModal());
    }
    const watermark = document.getElementById("app-version-watermark");
    if (watermark) {
        watermark.addEventListener("click", () => showUpdateModal());
    }
}

async function checkAppVersion() {
    try {
        const resp = await fetch("/api/version");
        if (!resp.ok) return;
        const data = await resp.json();
        _latestVersionInfo = data;

        const badge = document.getElementById("update-badge");
        const label = document.getElementById("update-badge-label");

        if (badge) {
            badge.onclick = () => showUpdateModal(data);

            if (data.update_available) {
                badge.style.display = "inline-flex";
                badge.classList.remove("hidden");
                if (label) label.textContent = `Update: v${data.latest_version}`;
            } else {
                badge.style.display = "none";
                badge.classList.add("hidden");
            }
        }

        const watermark = document.getElementById("app-version-watermark");
        if (watermark && data.current_version) {
            watermark.innerHTML = `<i class="fa-solid fa-code-branch" style="font-size: 10px; margin-right: 4px; opacity: 0.7;"></i>v${data.current_version}`;
        }
    } catch (e) {
        console.debug("Update check skipped:", e);
    }
}

async function showUpdateModal(data) {
    let info = data || _latestVersionInfo;
    if (!info) {
        try {
            const resp = await fetch("/api/version");
            if (resp.ok) {
                info = await resp.json();
                _latestVersionInfo = info;
            }
        } catch (e) {
            console.debug("Error fetching version info for modal:", e);
        }
    }
    if (!info) {
        info = {
            current_version: "1.3.2",
            latest_version: "1.3.2",
            update_available: false,
            release_notes: "Automated Beets deduplication, daily midnight scheduler, and Syncthing sync filters.",
            release_url: "https://github.com/jb155/music-manager"
        };
    }

    const modal = document.getElementById("update-modal");
    const currentEl = document.getElementById("modal-current-ver");
    const latestEl = document.getElementById("modal-latest-ver");
    const notesEl = document.getElementById("modal-update-notes");
    const repoLink = document.getElementById("modal-repo-link");
    const instructionsBlock = document.querySelector(".update-instructions");

    if (currentEl) currentEl.textContent = `v${info.current_version}`;
    if (latestEl) {
        if (info.update_available) {
            latestEl.textContent = `v${info.latest_version}`;
        } else {
            latestEl.textContent = `v${info.current_version} (Latest)`;
        }
    }
    if (notesEl) {
        if (info.update_available) {
            notesEl.textContent = info.release_notes || "Performance and stability improvements.";
        } else {
            notesEl.textContent = `You are running the latest version of Music Manager (v${info.current_version}). No updates are currently needed.`;
        }
    }
    if (instructionsBlock) {
        instructionsBlock.style.display = info.update_available ? "block" : "none";
    }
    if (repoLink && info.release_url) repoLink.href = info.release_url;

    if (modal) {
        modal.style.display = "flex";
        modal.classList.remove("hidden");
    }

    const closeBtn = document.getElementById("btn-close-update-modal");
    const dismissBtn = document.getElementById("btn-dismiss-update");

    const closeModal = () => {
        if (modal) {
            modal.style.display = "none";
            modal.classList.add("hidden");
        }
    };
    if (closeBtn) closeBtn.onclick = closeModal;
    if (dismissBtn) dismissBtn.onclick = closeModal;
    if (modal) {
        modal.onclick = (e) => {
            if (e.target === modal) closeModal();
        };
    }
}

// Navigation Tabs
function initTabs() {
    const tabBtns = document.querySelectorAll(".tab-btn");
    const panes = document.querySelectorAll(".tab-pane");

    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const tabName = btn.dataset.tab;

            tabBtns.forEach(b => b.classList.remove("active"));
            panes.forEach(p => p.classList.remove("active"));

            btn.classList.add("active");
            const targetPane = document.getElementById(`pane-${tabName}`);
            if (targetPane) targetPane.classList.add("active");

            // Refresh tab-specific data
            if (tabName === "playlist") {
                loadPlaylistMetadata();
            }
            if (tabName === "missing") loadMissingTracks();
            if (tabName === "library") loadLibraryActiveView();
            if (tabName === "staging") loadStagingFiles();
            if (tabName === "recommendations") {
                refreshAITasteProfile();
                loadOllamaServers();
            }
        });
    });
}

// Stats & Polling
async function loadLibraryStats() {
    try {
        const res = await fetch("/api/library/stats");
        if (!res.ok) return;
        const data = await res.json();

        const trackText = data.disk_tracks ? `${data.disk_tracks} Tracks` : `${data.tracks} Tracks`;
        document.getElementById("stat-tracks").querySelector("span").textContent = trackText;
        document.getElementById("stat-albums").querySelector("span").textContent = `${data.albums} Albums`;
        document.getElementById("stat-size").querySelector("span").textContent = data.size || "0 GB";
    } catch (e) {
        console.error("Failed to load stats", e);
    }
}

function startStatusPoller() {
    setInterval(async () => {
        try {
            const res = await fetch("/api/status");
            const status = await res.json();
            updateProgressUI(status);
        } catch (e) {}
    }, 2000);
}

function initAbortControls() {
    const handleAbort = async (btn) => {
        if (!confirm("Are you sure you want to stop/abort the running operation?")) {
            return;
        }
        const origHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Aborting...`;
        try {
            const res = await fetch("/api/task/abort", { method: "POST" });
            const data = await res.json();
            if (data.success) {
                showToast("Operation aborted by user.", "info");
                // Immediately refresh status UI
                try {
                    const stRes = await fetch("/api/status");
                    const stData = await stRes.json();
                    updateProgressUI(stData);
                } catch (err) {}
            } else {
                showToast(data.message || "Failed to abort task", "error");
            }
        } catch (e) {
            showToast("Error requesting task abort: " + e.message, "error");
        } finally {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    };

    const btnAbortTask = document.getElementById("btn-abort-task");
    if (btnAbortTask) {
        btnAbortTask.addEventListener("click", () => handleAbort(btnAbortTask));
    }

    const btnAbortTerminal = document.getElementById("btn-abort-terminal");
    if (btnAbortTerminal) {
        btnAbortTerminal.addEventListener("click", () => handleAbort(btnAbortTerminal));
    }
}

function updateProgressUI(status) {
    const banner = document.getElementById("progress-banner");
    const sysStatus = document.getElementById("system-status");
    const btnAbortTerm = document.getElementById("btn-abort-terminal");

    if (status.status === "running") {
        banner.style.display = "block";
        document.getElementById("progress-action").textContent = status.action || "Task in progress...";
        document.getElementById("progress-message").textContent = status.message || "";

        let pct = 0;
        if (status.total > 0) {
            pct = Math.round((status.current / status.total) * 100);
            document.getElementById("progress-counts").textContent = `${status.current} of ${status.total} processed`;
        } else {
            document.getElementById("progress-counts").textContent = "";
        }
        document.getElementById("progress-percent").textContent = `${pct}%`;
        document.getElementById("progress-bar-fill").style.width = `${pct}%`;

        sysStatus.className = "status-badge running";
        sysStatus.querySelector(".status-text").textContent = "Processing";
        if (btnAbortTerm) btnAbortTerm.style.display = "inline-flex";
    } else {
        banner.style.display = "none";
        sysStatus.className = "status-badge idle";
        sysStatus.querySelector(".status-text").textContent = "Idle";
        if (btnAbortTerm) btnAbortTerm.style.display = "none";
    }
}

// SSE Live Console
function initSSE() {
    const term = document.getElementById("terminal-output");
    const evtSource = new EventSource("/api/logs/stream");

    evtSource.onmessage = (e) => {
        const line = document.createElement("div");
        line.className = "log-line";
        line.textContent = e.data;
        term.appendChild(line);
        term.scrollTop = term.scrollHeight;
    };

    evtSource.onerror = () => {
        // SSE auto-reconnects
    };

    document.getElementById("btn-clear-terminal").addEventListener("click", () => {
        term.innerHTML = '<span class="log-info">[System] Console cleared.</span>';
    });

    document.getElementById("btn-copy-terminal").addEventListener("click", () => {
        navigator.clipboard.writeText(term.innerText)
            .then(() => showToast("Terminal output copied to clipboard", "success"))
            .catch(() => showToast("Failed to copy terminal output", "error"));
    });
}

// Download Form & Smart Artist Discography Flow
async function executeDirectDownload(query, autoImport = true, autoComplete = true, maxRetries = 3) {
    try {
        const res = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query,
                auto_import: autoImport,
                max_retries: maxRetries,
                auto_complete_album: autoComplete
            })
        });

        if (res.ok) {
            showToast(`Download started: ${query}`, "success");
            const qInput = document.getElementById("download-query");
            if (qInput) qInput.value = "";
            const discSec = document.getElementById("artist-discography-section");
            if (discSec) discSec.style.display = "none";
            document.querySelector('[data-tab="terminal"]').click();
        } else {
            const err = await res.json();
            showToast(err.detail || "Error starting download", "error");
        }
    } catch (err) {
        showToast("Network error starting download", "error");
    }
}

document.getElementById("download-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = document.getElementById("download-query").value.trim();
    const autoImport = document.getElementById("auto-import-toggle").checked;
    const autoComplete = document.getElementById("auto-complete-toggle") ? document.getElementById("auto-complete-toggle").checked : true;
    const maxRetries = parseInt(document.getElementById("max-retries-input").value) || 3;

    if (!query) return;

    const isUrl = query.startsWith("http://") || query.startsWith("https://") || query.startsWith("spotify:");
    const hasTrackSeparator = query.includes(" - ");

    // Direct download if URL or explicit track query
    if (isUrl || hasTrackSeparator) {
        await executeDirectDownload(query, autoImport, autoComplete, maxRetries);
        return;
    }

    // Artist Discography Discovery Flow
    const btnSubmit = document.getElementById("btn-start-download");
    const origBtnHtml = btnSubmit ? btnSubmit.innerHTML : "";
    if (btnSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Checking Artist...`;
    }

    try {
        const res = await fetch(`/api/download/artist-check?query=${encodeURIComponent(query)}`);
        const data = await res.json();

        if (data.match_type === "exact" && data.albums && data.albums.length > 0) {
            renderAlbumChecklist(data.artist, data.albums, query, autoImport, autoComplete);
        } else if (data.match_type === "partial" && data.artists && data.artists.length > 0) {
            renderArtistChoices(data.artists, query, autoImport, autoComplete);
        } else {
            // No artist matched, proceed with standard single download
            await executeDirectDownload(query, autoImport, autoComplete, maxRetries);
        }
    } catch (err) {
        console.error("Artist lookup error:", err);
        await executeDirectDownload(query, autoImport, autoComplete, maxRetries);
    } finally {
        if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = origBtnHtml;
        }
    }
});

// Missing Tracks
let missingTracksData = [];

async function loadMissingTracks() {
    const tbody = document.getElementById("missing-tbody");
    if (missingTracksData.length > 0) {
        renderMissingTable(missingTracksData);
        return;
    }

    try {
        const res = await fetch("/api/missing/cached");
        const data = await res.json();
        if (data.tracks && data.tracks.length > 0) {
            missingTracksData = data.tracks;
            document.getElementById("missing-badge").textContent = data.count || 0;
            document.getElementById("missing-count-text").textContent = `${data.count || 0} missing tracks cataloged (cached)`;
            document.getElementById("btn-download-all-missing").disabled = data.count === 0;
            renderMissingTable(missingTracksData);
        } else {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted" style="padding: 32px;">
                <i class="fa-solid fa-magnifying-glass-chart" style="font-size: 2rem; margin-bottom: 12px; display: block; opacity: 0.5;"></i>
                No cached missing tracks found. Click <strong>Scan Library</strong> to scan your catalog.<br>
                <small style="opacity: 0.6;">Uses MusicBrainz release diffs to pinpoint exact missing songs.</small>
            </td></tr>`;
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">Error loading missing tracks.</td></tr>`;
    }
}

async function runMissingScan(refresh = true) {
    const tbody = document.getElementById("missing-tbody");
    const depth = document.getElementById("missing-scan-depth") ? parseInt(document.getElementById("missing-scan-depth").value) || 50 : 50;

    tbody.innerHTML = `<tr><td colspan="5" class="text-center"><div class="spinner" style="margin: 10px auto;"></div> Scanning top ${depth} incomplete albums via MusicBrainz... this takes ~15-20s.</td></tr>`;

    try {
        const res = await fetch(`/api/missing?refresh=${refresh}&max_albums=${depth}`);
        const data = await res.json();
        missingTracksData = data.tracks || [];

        document.getElementById("missing-badge").textContent = data.count || 0;
        document.getElementById("missing-count-text").textContent = `${data.count || 0} missing tracks found`;
        document.getElementById("btn-download-all-missing").disabled = data.count === 0;

        renderMissingTable(missingTracksData);
        showToast(`Scan complete: found ${data.count || 0} missing tracks!`, "success");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">Error scanning missing tracks.</td></tr>`;
        showToast("Error scanning missing tracks", "error");
    }
}

function renderMissingTable(tracks) {
    const tbody = document.getElementById("missing-tbody");
    if (!tracks || tracks.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No missing tracks found! Your library looks complete.</td></tr>`;
        return;
    }

    tbody.innerHTML = tracks.map((t, idx) => `
        <tr id="missing-row-${idx}" data-artist="${escapeAttr(t.artist)}" data-title="${escapeAttr(t.title)}">
            <td style="text-align: center;">
                <button type="button" class="btn-track-play btn-missing-play" data-artist="${escapeAttr(t.artist)}" data-title="${escapeAttr(t.title)}" title="Play 30s Audio Preview">
                    <i class="fa-solid fa-play"></i>
                </button>
            </td>
            <td><strong>${escapeHtml(t.artist)}</strong></td>
            <td><span class="text-muted">${escapeHtml(t.album || "")}</span></td>
            <td class="text-muted" style="text-align:center; font-size: 0.8em;">${escapeHtml(String(t.track_num || "?"))}</td>
            <td>${escapeHtml(t.title)}</td>
            <td class="text-right">
                <button class="btn btn-secondary btn-sm" id="btn-missing-dl-${idx}" onclick="downloadMissingSingleTrack(${idx}, '${escapeAttr(t.query)}')">
                    <i class="fa-solid fa-download"></i> Download
                </button>
            </td>
        </tr>
    `).join("");

    tbody.querySelectorAll(".btn-missing-play").forEach(btn => {
        btn.addEventListener("click", () => {
            const artist = btn.dataset.artist;
            const title = btn.dataset.title;
            if (audioManager) audioManager.playQuery(artist, title, btn);
        });
    });

    if (audioManager) audioManager.updatePlayStateUI();
}

async function downloadMissingSingleTrack(idx, query) {
    const btn = document.getElementById(`btn-missing-dl-${idx}`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Downloading...`;
    }
    const track = (typeof missingTracksData !== 'undefined' && missingTracksData && missingTracksData[idx]) ? missingTracksData[idx] : null;
    const targetAlbum = track ? (track.album || null) : null;
    await downloadSingleTrack(query, false, targetAlbum);
    if (btn) {
        btn.className = "btn btn-sm";
        btn.style.background = "rgba(34, 197, 94, 0.2)";
        btn.style.color = "#4ade80";
        btn.style.border = "1px solid rgba(34, 197, 94, 0.4)";
        btn.innerHTML = `<i class="fa-solid fa-check"></i> Queued`;
    }
}

document.getElementById("btn-scan-missing").addEventListener("click", async () => {
    missingTracksData = [];
    await runMissingScan(true);
});

document.getElementById("missing-search").addEventListener("input", (e) => {
    const term = e.target.value.toLowerCase();
    const filtered = missingTracksData.filter(t =>
        `${t.artist} ${t.album || ""} ${t.title}`.toLowerCase().includes(term)
    );
    renderMissingTable(filtered);
});

document.getElementById("btn-download-all-missing").addEventListener("click", async () => {
    if (missingTracksData.length === 0) {
        showToast("No missing tracks loaded. Please scan first.", "error");
        return;
    }
    if (!confirm(`Download all ${missingTracksData.length} missing tracks sequentially?`)) return;

    const trackItems = missingTracksData.map(t => ({
        query: t.query,
        album: t.album,
        artist: t.artist,
        title: t.title
    })).filter(t => Boolean(t.query));

    try {
        const res = await fetch("/api/missing/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tracks: trackItems, auto_import: true })
        });
        if (res.ok) {
            showToast(`Started batch download of ${trackItems.length} missing tracks`, "success");
            document.querySelector('[data-tab="terminal"]').click();
        } else {
            const err = await res.json();
            showToast(err.detail || "Error starting missing download", "error");
        }
    } catch (e) {
        showToast("Network error", "error");
    }
});

async function downloadSingleTrack(query, autoComplete = null, targetAlbum = null, force = false) {
    if (autoComplete === null && document.getElementById("auto-complete-toggle")) {
        autoComplete = document.getElementById("auto-complete-toggle").checked;
    }
    try {
        const payload = {
            query: query,
            auto_import: true,
            max_retries: 3,
            auto_complete_album: Boolean(autoComplete),
            force: Boolean(force)
        };
        if (targetAlbum) {
            payload.target_album = targetAlbum;
        }
        const res = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            showToast(`Downloading: ${query}`, "success");
            document.querySelector('[data-tab="terminal"]').click();
        } else {
            const err = await res.json();
            showToast(err.detail || "Error", "error");
        }
    } catch (e) {
        showToast("Error starting download", "error");
    }
}

// Staging Files & Import
async function loadStagingFiles() {
    const tbody = document.getElementById("staging-tbody");
    try {
        const res = await fetch("/api/staging");
        const files = await res.json();

        document.getElementById("staging-badge").textContent = files.length;
        document.getElementById("staging-files-count").textContent = files.length;

        const totalBytes = files.reduce((acc, f) => acc + (f.size_bytes || 0), 0);
        document.getElementById("staging-total-size").textContent = `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`;

        if (files.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">Staging directory is clean and empty.</td></tr>`;
            return;
        }

        tbody.innerHTML = files.map((f, idx) => `
            <tr id="staging-row-${idx}" data-path="${escapeAttr(f.path)}">
                <td style="text-align: center;">
                    ${f.is_audio ? `
                        <button type="button" class="btn-track-play btn-staging-play" data-path="${escapeAttr(f.path)}" data-name="${escapeAttr(f.path.split('/').pop())}" title="Play 30s Audio Preview">
                            <i class="fa-solid fa-play"></i>
                        </button>
                    ` : `<span class="text-muted">-</span>`}
                </td>
                <td><i class="fa-solid ${f.is_audio ? 'fa-music' : 'fa-file'} text-muted" style="margin-right: 8px;"></i> ${escapeHtml(f.path)}</td>
                <td><span class="badge">${f.is_audio ? 'Audio' : 'File'}</span></td>
                <td>${f.size_str}</td>
            </tr>
        `).join("");

        tbody.querySelectorAll(".btn-staging-play").forEach(btn => {
            btn.addEventListener("click", () => {
                const path = btn.dataset.path;
                const name = btn.dataset.name;
                if (audioManager) audioManager.playStaging(path, name, btn);
            });
        });

        if (audioManager) audioManager.updatePlayStateUI();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="3" class="text-center text-muted">Error loading staging files.</td></tr>`;
    }
}

document.getElementById("btn-refresh-staging").addEventListener("click", loadStagingFiles);

document.getElementById("btn-run-import").addEventListener("click", async () => {
    try {
        const res = await fetch("/api/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ force: false })
        });
        if (res.ok) {
            showToast("Library import triggered", "success");
            document.querySelector('[data-tab="terminal"]').click();
        } else {
            const err = await res.json();
            showToast(err.detail || "Import error", "error");
        }
    } catch (e) {
        showToast("Network error triggering import", "error");
    }
});

const btnFetchArt = document.getElementById("btn-fetch-art");
if (btnFetchArt) {
    btnFetchArt.addEventListener("click", async () => {
        try {
            const res = await fetch("/api/library/fetchart", {
                method: "POST",
                headers: { "Content-Type": "application/json" }
            });
            if (res.ok) {
                showToast("Fetching album art and embedding into files...", "success");
                document.querySelector('[data-tab="terminal"]').click();
            } else {
                const err = await res.json();
                showToast(err.detail || "Error fetching album art", "error");
            }
        } catch (e) {
            showToast("Network error", "error");
        }
    });
}

// ============================================================================
// MANUAL MUSIC FOLDER & FILE UPLOAD MODULE
// ============================================================================
function initManualUpload() {
    const dropzone = document.getElementById("staging-upload-dropzone");
    const btnSelectFolder = document.getElementById("btn-select-folder");
    const btnSelectFiles = document.getElementById("btn-select-files");
    const inputFolder = document.getElementById("input-folder-upload");
    const inputFiles = document.getElementById("input-files-upload");
    const autoImportToggle = document.getElementById("upload-auto-import-toggle");
    const progressContainer = document.getElementById("upload-progress-container");
    const progressStatus = document.getElementById("upload-progress-status");
    const progressBar = document.getElementById("upload-progress-bar");
    const progressPercent = document.getElementById("upload-progress-percent");
    const currentFileText = document.getElementById("upload-current-file");

    if (!dropzone) return;

    const VALID_EXTS = ['.mp3', '.flac', '.m4a', '.ogg', '.wav', '.opus', '.aac', '.alac', '.aiff', '.wma', '.zip', '.jpg', '.jpeg', '.png', '.cue', '.m3u', '.m3u8'];

    function isAudioOrMedia(filename) {
        if (!filename) return false;
        const dot = filename.lastIndexOf('.');
        if (dot === -1) return false;
        const ext = filename.slice(dot).toLowerCase();
        return VALID_EXTS.includes(ext);
    }

    // Prevent default browser drag navigation
    window.addEventListener("dragover", (e) => e.preventDefault(), false);
    window.addEventListener("drop", (e) => e.preventDefault(), false);

    // Dropzone highlight effects
    dropzone.addEventListener("dragenter", (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragleave", (e) => {
        e.preventDefault();
        if (!dropzone.contains(e.relatedTarget)) {
            dropzone.classList.remove("dragover");
        }
    });

    // Handle Dropped Files / Folders
    dropzone.addEventListener("drop", async (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        const items = e.dataTransfer.items;
        if (!items || items.length === 0) return;

        try {
            const filesToUpload = await extractFilesFromDataTransfer(items);
            if (filesToUpload.length > 0) {
                uploadQueue(filesToUpload);
            } else {
                showToast("No audio files found in dropped item(s)", "warning");
            }
        } catch (err) {
            console.error("Error reading dropped entries:", err);
            showToast("Failed reading dropped files", "error");
        }
    });

    // Button triggers
    if (btnSelectFolder && inputFolder) {
        btnSelectFolder.addEventListener("click", (e) => {
            e.stopPropagation();
            inputFolder.click();
        });
        inputFolder.addEventListener("change", () => {
            if (!inputFolder.files || inputFolder.files.length === 0) return;
            const filesToUpload = [];
            for (let i = 0; i < inputFolder.files.length; i++) {
                const f = inputFolder.files[i];
                const relPath = f.webkitRelativePath || f.name;
                if (isAudioOrMedia(relPath)) {
                    filesToUpload.push({ file: f, path: relPath });
                }
            }
            inputFolder.value = "";
            if (filesToUpload.length > 0) {
                uploadQueue(filesToUpload);
            } else {
                showToast("No audio files found in selected folder", "warning");
            }
        });
    }

    if (btnSelectFiles && inputFiles) {
        btnSelectFiles.addEventListener("click", (e) => {
            e.stopPropagation();
            inputFiles.click();
        });
        inputFiles.addEventListener("change", () => {
            if (!inputFiles.files || inputFiles.files.length === 0) return;
            const filesToUpload = [];
            for (let i = 0; i < inputFiles.files.length; i++) {
                const f = inputFiles.files[i];
                if (isAudioOrMedia(f.name)) {
                    filesToUpload.push({ file: f, path: f.name });
                }
            }
            inputFiles.value = "";
            if (filesToUpload.length > 0) {
                uploadQueue(filesToUpload);
            } else {
                showToast("No valid audio files or archives selected", "warning");
            }
        });
    }

    // Recursive directory reader for drag-and-drop folders
    async function extractFilesFromDataTransfer(items) {
        const fileList = [];
        const queue = [];

        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.webkitGetAsEntry) {
                const entry = item.webkitGetAsEntry();
                if (entry) queue.push(entry);
            } else if (item.getAsFile) {
                const f = item.getAsFile();
                if (f && isAudioOrMedia(f.name)) fileList.push({ file: f, path: f.name });
            }
        }

        while (queue.length > 0) {
            const entry = queue.shift();
            if (entry.isFile) {
                await new Promise((resolve) => {
                    entry.file((f) => {
                        const relPath = entry.fullPath ? entry.fullPath.replace(/^\//, '') : f.name;
                        if (isAudioOrMedia(relPath)) {
                            fileList.push({ file: f, path: relPath });
                        }
                        resolve();
                    }, () => resolve());
                });
            } else if (entry.isDirectory) {
                const reader = entry.createReader();
                const readBatch = async () => {
                    return new Promise((resolve) => {
                        reader.readEntries((entries) => {
                            if (!entries || entries.length === 0) {
                                resolve();
                            } else {
                                for (const child of entries) {
                                    queue.push(child);
                                }
                                readBatch().then(resolve);
                            }
                        }, () => resolve());
                    });
                };
                await readBatch();
            }
        }
        return fileList;
    }

    // Upload files sequentially with progress tracking
    async function uploadQueue(fileList) {
        progressContainer.style.display = "block";
        progressBar.style.width = "0%";
        progressPercent.innerText = "0%";
        progressStatus.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Uploading files to staging...';

        const totalBytes = fileList.reduce((acc, it) => acc + it.file.size, 0);
        let uploadedBytesPrevious = 0;
        let successCount = 0;

        for (let idx = 0; idx < fileList.length; idx++) {
            const item = fileList[idx];
            currentFileText.innerText = `(${idx + 1}/${fileList.length}) ${item.path}`;

            try {
                await new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    const formData = new FormData();
                    formData.append("files", item.file, item.file.name);
                    formData.append("relative_paths", item.path);
                    formData.append("auto_import", "false");

                    xhr.upload.addEventListener("progress", (ev) => {
                        if (ev.lengthComputable) {
                            const currentTotal = uploadedBytesPrevious + ev.loaded;
                            const percent = Math.min(99, Math.round((currentTotal / (totalBytes || 1)) * 100));
                            progressBar.style.width = `${percent}%`;
                            progressPercent.innerText = `${percent}%`;
                        }
                    });

                    xhr.onload = () => {
                        if (xhr.status >= 200 && xhr.status < 300) {
                            uploadedBytesPrevious += item.file.size;
                            successCount++;
                            resolve();
                        } else {
                            reject(new Error(`Server error: ${xhr.statusText}`));
                        }
                    };

                    xhr.onerror = () => reject(new Error("Network error during upload"));
                    xhr.open("POST", "/api/upload");
                    xhr.send(formData);
                });
            } catch (err) {
                console.error("Upload error for file:", item.path, err);
                showToast(`Failed to upload: ${item.path}`, "error");
            }
        }

        progressBar.style.width = "100%";
        progressPercent.innerText = "100%";
        progressStatus.innerHTML = '<i class="fa-solid fa-check text-success"></i> Upload complete!';
        currentFileText.innerText = `Transferred ${successCount} file(s) into Staging.`;
        showToast(`${successCount} file(s) transferred to Staging`, "success");

        await loadStagingFiles();

        if (autoImportToggle && autoImportToggle.checked && successCount > 0) {
            showToast("Auto-importing into library with Beets...", "info");
            const termTab = document.querySelector('[data-tab="terminal"]');
            if (termTab) termTab.click();

            try {
                const res = await fetch("/api/import", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ force: false })
                });
                if (!res.ok) {
                    const err = await res.json();
                    showToast(err.detail || "Import error", "error");
                }
            } catch (e) {
                showToast("Network error starting import", "error");
            }
        }

        setTimeout(() => {
            if (progressStatus.innerHTML.includes("Upload complete!")) {
                progressContainer.style.display = "none";
            }
        }, 5000);
    }
}

// ============================================================================
// AI RECOMMENDATIONS & OLLAMA SERVER MANAGEMENT MODULE
// ============================================================================
let activePreset = "all";
let currentRecommendations = [];
let knownOllamaServers = [];

async function initAIRecommendations() {
    await loadOllamaServers();
    await refreshAITasteProfile();

    // Wire up server selector
    const serverSelect = document.getElementById("ollama-server-select");
    if (serverSelect) {
        serverSelect.addEventListener("change", async (e) => {
            await selectOllamaServer(e.target.value);
        });
    }

    // Wire up scan network button
    const btnScan = document.getElementById("btn-scan-ollama");
    if (btnScan) {
        btnScan.addEventListener("click", scanOllamaNetwork);
    }

    // Wire up add server button
    const btnAdd = document.getElementById("btn-add-ollama");
    if (btnAdd) {
        btnAdd.addEventListener("click", promptAddOllamaServer);
    }

    // Wire up remove server button
    const btnRemove = document.getElementById("btn-remove-ollama");
    if (btnRemove) {
        btnRemove.addEventListener("click", removeCurrentOllamaServer);
    }

    // Wire up preset buttons
    const presetBtns = document.querySelectorAll(".btn-preset");
    presetBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            presetBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            activePreset = btn.dataset.preset;
        });
    });

    // Wire up generate button (ONCE)
    const btnGen = document.getElementById("btn-generate-recs");
    if (btnGen) {
        btnGen.addEventListener("click", generateRecommendations);
    }

    // Wire up batch download button (ONCE)
    const btnDownloadAll = document.getElementById("btn-download-all-recs");
    if (btnDownloadAll) {
        btnDownloadAll.addEventListener("click", downloadAllRecommendations);
    }

    // Allow enter on prompt input
    const promptInput = document.getElementById("ai-custom-prompt");
    if (promptInput) {
        promptInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                generateRecommendations();
            }
        });
    }
}

async function loadOllamaServers() {
    const pill = document.getElementById("ollama-connection-pill");
    const serverSelect = document.getElementById("ollama-server-select");
    const btnRemove = document.getElementById("btn-remove-ollama");

    try {
        const res = await fetch("/api/ai/servers");
        const data = await res.json();

        knownOllamaServers = data.servers || [];
        const activeHost = data.active_host;

        if (serverSelect) {
            serverSelect.innerHTML = knownOllamaServers.map(s => `
                <option value="${s}" ${s === activeHost ? "selected" : ""}>${s.replace(/^https?:\/\//, '')}</option>
            `).join("");
        }

        if (btnRemove) {
            btnRemove.disabled = knownOllamaServers.length <= 1;
        }

        updateOllamaStatusUI(data.connected, activeHost, data.models || [], data.error);
    } catch (e) {
        if (pill) {
            pill.className = "status-pill offline";
            pill.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Ollama Offline`;
        }
    }
}

function updateOllamaStatusUI(connected, host, models, error) {
    const pill = document.getElementById("ollama-connection-pill");
    const modelSelect = document.getElementById("ai-model-select");

    if (pill) {
        if (connected) {
            pill.className = "status-pill online";
            pill.innerHTML = `<i class="fa-solid fa-circle-check"></i> Connected (${models.length} models)`;
        } else {
            pill.className = "status-pill offline";
            pill.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Offline (${error ? 'timed out' : 'unreachable'})`;
        }
    }

    if (modelSelect) {
        if (models && models.length > 0) {
            const currentVal = modelSelect.value;
            modelSelect.innerHTML = models.map(m => `
                <option value="${m}" ${m === currentVal ? "selected" : ""}>${m}</option>
            `).join("");
            modelSelect.disabled = false;
        } else {
            modelSelect.innerHTML = `<option value="">No models installed</option>`;
            modelSelect.disabled = true;
        }
    }
}

async function selectOllamaServer(host) {
    const pill = document.getElementById("ollama-connection-pill");
    if (pill) {
        pill.className = "status-pill";
        pill.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Connecting...`;
    }

    try {
        const res = await fetch("/api/ai/servers/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ host })
        });
        const data = await res.json();
        updateOllamaStatusUI(data.connected, data.active_host, data.models || [], data.error);

        if (data.connected) {
            showToast(`Connected to Ollama at ${data.active_host} (${(data.models || []).length} models)`, "success");
        } else {
            showToast(`Switched to ${data.active_host}, but host is not responding`, "error");
        }
    } catch (e) {
        showToast("Error switching Ollama server", "error");
    }
}

async function scanOllamaNetwork() {
    const btnScan = document.getElementById("btn-scan-ollama");
    const origHtml = btnScan.innerHTML;
    btnScan.disabled = true;
    btnScan.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Scanning...`;
    showToast("Scanning local subnet on port 11434...", "info");

    try {
        const res = await fetch("/api/ai/servers/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({})
        });
        const data = await res.json();

        await loadOllamaServers();

        if (data.count > 0) {
            showToast(`Network scan complete: found ${data.count} Ollama server(s)!`, "success");
        } else {
            showToast("Scan complete. No additional Ollama servers detected on subnet.", "info");
        }
    } catch (e) {
        showToast("Error scanning network for Ollama", "error");
    } finally {
        btnScan.disabled = false;
        btnScan.innerHTML = origHtml;
    }
}

async function promptAddOllamaServer() {
    const entered = prompt(
        "Enter Ollama Server IP or Hostname:\n(e.g. 192.168.178.50 or 192.168.178.50:11434 or http://ai-server:11434)",
        ""
    );
    if (!entered || !entered.trim()) return;

    try {
        showToast(`Testing connection to ${entered.trim()}...`, "info");
        const res = await fetch("/api/ai/servers/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ host: entered.trim(), set_active: true })
        });
        const data = await res.json();

        await loadOllamaServers();

        if (data.connected) {
            showToast(`Connected to ${data.host}! (${(data.models || []).length} models)`, "success");
        } else {
            showToast(`Added ${data.host}, but connection test failed. Check if Ollama is listening on 0.0.0.0.`, "error");
        }
    } catch (e) {
        showToast("Error adding Ollama server", "error");
    }
}

async function removeCurrentOllamaServer() {
    const serverSelect = document.getElementById("ollama-server-select");
    const host = serverSelect ? serverSelect.value : "";
    if (!host) return;

    if (!confirm(`Remove server ${host} from remembered list?`)) return;

    try {
        const res = await fetch(`/api/ai/servers?host=${encodeURIComponent(host)}`, {
            method: "DELETE"
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Removed server ${host}`, "info");
            await loadOllamaServers();
        } else {
            showToast(data.error || "Could not remove server", "error");
        }
    } catch (e) {
        showToast("Error removing server", "error");
    }
}

async function refreshAITasteProfile() {
    const chipsContainer = document.getElementById("profile-artist-chips");
    try {
        const res = await fetch("/api/ai/taste-profile");
        const data = await res.json();

        if (data.top_artists && data.top_artists.length > 0) {
            chipsContainer.innerHTML = data.top_artists.slice(0, 18).map(a => `
                <span class="taste-chip">
                    <strong>${escapeHtml(a.artist)}</strong>
                    <span class="chip-count">${a.track_count}</span>
                </span>
            `).join("");
        } else {
            chipsContainer.innerHTML = `<span class="text-muted">No library artists cataloged yet. Run a library scan!</span>`;
        }
    } catch (e) {
        chipsContainer.innerHTML = `<span class="text-muted">Could not load taste profile.</span>`;
    }
}

async function generateRecommendations() {
    const btnGen = document.getElementById("btn-generate-recs");
    const placeholder = document.getElementById("recs-placeholder");
    const loading = document.getElementById("recs-loading");
    const grid = document.getElementById("recs-grid");
    const modelSelect = document.getElementById("ai-model-select");
    const customPrompt = document.getElementById("ai-custom-prompt").value.trim();

    const selectedModel = modelSelect.value;
    if (!selectedModel) {
        showToast("No AI model available. Check Ollama server connection.", "error");
        return;
    }

    btnGen.disabled = true;
    placeholder.style.display = "none";
    grid.style.display = "none";
    loading.style.display = "block";

    try {
        const res = await fetch("/api/ai/recommend", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                model: selectedModel,
                preset: activePreset,
                prompt: customPrompt,
                count: 6
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "AI generation failed");
        }

        const data = await res.json();
        renderRecommendations(data.recommendations || []);
        showToast("Recommendations generated!", "success");
    } catch (err) {
        showToast(`AI Error: ${err.message}`, "error");
        placeholder.style.display = "block";
        placeholder.innerHTML = `<i class="fa-solid fa-triangle-exclamation fa-2x mb-2 text-danger"></i><p>Failed to generate recommendations: ${escapeHtml(err.message)}</p>`;
    } finally {
        btnGen.disabled = false;
        loading.style.display = "none";
    }
}

function renderRecommendations(recs) {
    currentRecommendations = recs || [];
    const grid = document.getElementById("recs-grid");
    const placeholder = document.getElementById("recs-placeholder");
    const actionBar = document.getElementById("recs-action-bar");

    if (!recs || recs.length === 0) {
        placeholder.style.display = "block";
        grid.style.display = "none";
        if (actionBar) actionBar.style.display = "none";
        return;
    }

    // Collect all tracks for the batch action bar
    const allTracks = [];
    recs.forEach(r => {
        (r.recommended_tracks || []).forEach(t => {
            const q = t.search_query || `${r.artist} - ${t.title}`;
            if (q) allTracks.push(q);
        });
    });

    if (actionBar) {
        if (allTracks.length > 0) {
            actionBar.style.display = "flex";
            const countText = document.getElementById("recs-count-text");
            if (countText) countText.textContent = `${recs.length} artists recommended (${allTracks.length} tracks)`;
            const trackCount = document.getElementById("recs-track-count");
            if (trackCount) trackCount.textContent = allTracks.length;
        } else {
            actionBar.style.display = "none";
        }
    }

    grid.innerHTML = recs.map((item) => {
        const tracksHtml = (item.recommended_tracks || []).map(t => {
            const query = t.search_query || `${item.artist} - ${t.title}`;
            return `
                <div class="rec-track-item" data-artist="${escapeAttr(item.artist)}" data-title="${escapeAttr(t.title)}">
                    <div class="track-title-wrap">
                        <button type="button" class="btn-track-play btn-rec-play" data-artist="${escapeAttr(item.artist)}" data-title="${escapeAttr(t.title)}" title="Play 30s Audio Preview">
                            <i class="fa-solid fa-play"></i>
                        </button>
                        <span class="track-name">${escapeHtml(t.title)}</span>
                    </div>
                    <div class="rec-track-actions">
                        <button class="btn-icon-sm" title="Download '${escapeAttr(query)}'" onclick="downloadSingleTrack('${escapeAttr(query)}')">
                            <i class="fa-solid fa-cloud-arrow-down"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join("");

        const artistQuery = item.artist;

        return `
            <div class="rec-card glass">
                <div class="rec-card-header">
                    <div class="rec-artist-info">
                        <h3 class="rec-artist-name">${escapeHtml(item.artist)}</h3>
                        <div class="rec-tags">
                            ${item.genre ? `<span class="rec-badge genre">${escapeHtml(item.genre)}</span>` : ""}
                            ${item.similarity ? `<span class="rec-badge similarity"><i class="fa-solid fa-link"></i> ${escapeHtml(item.similarity)}</span>` : ""}
                        </div>
                    </div>
                </div>

                <p class="rec-reason">${escapeHtml(item.reason)}</p>

                ${item.recommended_album ? `
                    <div class="rec-album">
                        <i class="fa-solid fa-compact-disc"></i> 
                        <span>Recommended Album: <strong>${escapeHtml(item.recommended_album)}</strong></span>
                    </div>
                ` : ""}

                <div class="rec-tracks-list">
                    <div class="rec-tracks-heading">Standout Starter Tracks:</div>
                    ${tracksHtml}
                </div>

                <div class="rec-card-footer mt-3">
                    <button class="btn btn-secondary btn-sm full-width" onclick="downloadArtistTopTracks('${escapeAttr(artistQuery)}')">
                        <i class="fa-solid fa-download"></i> Download Artist Top Tracks
                    </button>
                </div>
            </div>
        `;
    }).join("");

    placeholder.style.display = "none";
    grid.style.display = "grid";

    grid.querySelectorAll(".btn-rec-play").forEach(btn => {
        btn.addEventListener("click", () => {
            const artist = btn.dataset.artist;
            const title = btn.dataset.title;
            if (audioManager) audioManager.playQuery(artist, title, btn);
        });
    });

    if (audioManager) audioManager.updatePlayStateUI();
}

async function downloadArtistTopTracks(artistName) {
    const query = `${artistName} top tracks`;
    downloadSingleTrack(query);
}

// Helpers
function escapeHtml(str) {
    if (!str) return "";
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function escapeAttr(str) {
    if (!str) return "";
    return String(str).replace(/&/g, "&amp;").replace(/'/g, "&#39;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function downloadAllRecommendations() {
    if (!currentRecommendations || currentRecommendations.length === 0) {
        showToast("No recommendations available to download", "error");
        return;
    }

    const allTracks = [];
    currentRecommendations.forEach(r => {
        (r.recommended_tracks || []).forEach(t => {
            const q = t.search_query || `${r.artist} - ${t.title}`;
            if (q) allTracks.push(q);
        });
    });

    if (allTracks.length === 0) {
        showToast("No recommended tracks found to download", "error");
        return;
    }

    if (!confirm(`Download all ${allTracks.length} recommended tracks across ${currentRecommendations.length} artists sequentially into your library?`)) {
        return;
    }

    try {
        const autoComplete = document.getElementById("recs-auto-complete-toggle") ? document.getElementById("recs-auto-complete-toggle").checked : false;
        const res = await fetch("/api/ai/download-all", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tracks: allTracks,
                auto_import: true,
                label: "AI Recommended Tracks",
                auto_complete_album: autoComplete
            })
        });

        if (res.ok) {
            showToast(`Started batch download of ${allTracks.length} recommended tracks!`, "success");
            document.querySelector('[data-tab="terminal"]').click();
        } else {
            const err = await res.json();
            showToast(err.detail || "Error initiating batch download", "error");
        }
    } catch (e) {
        showToast("Network error starting batch download", "error");
    }
}

// =========================================================================
// PLAYLIST CREATOR CLIENT LOGIC
// =========================================================================

let libraryAvgSongLengthSec = 239.0;
let currentPlaylistTracks = [];
let playlistMetadataLoaded = false;

function initPlaylistCreator() {
    // 1. Tied Length Controls (Duration <-> Song Count)
    const timeSlider = document.getElementById("playlist-time-slider");
    const timeInput = document.getElementById("playlist-time-input");
    const timeDisplay = document.getElementById("playlist-time-display");

    const songsSlider = document.getElementById("playlist-songs-slider");
    const songsInput = document.getElementById("playlist-songs-input");
    const songsDisplay = document.getElementById("playlist-songs-display");

    function updateFromTime(minutes) {
        minutes = Math.max(5, Math.min(720, parseInt(minutes) || 60));
        timeSlider.value = Math.min(timeSlider.max, minutes);
        timeInput.value = minutes;

        const hrs = Math.floor(minutes / 60);
        const mins = minutes % 60;
        const hrStr = hrs > 0 ? `${hrs}h ${mins.toString().padStart(2, "0")}m` : `${mins}m`;
        timeDisplay.textContent = `${minutes} min (${hrStr})`;

        // Calculate tied song count based on library average
        const estSongs = Math.max(1, Math.round((minutes * 60) / libraryAvgSongLengthSec));
        songsSlider.value = Math.min(songsSlider.max, estSongs);
        songsInput.value = estSongs;
        songsDisplay.textContent = `${estSongs} songs`;
    }

    function updateFromSongs(count) {
        count = Math.max(1, Math.min(300, parseInt(count) || 15));
        songsSlider.value = Math.min(songsSlider.max, count);
        songsInput.value = count;
        songsDisplay.textContent = `${count} songs`;

        // Calculate tied duration based on library average (rounded to nearest 5 min)
        const estSec = count * libraryAvgSongLengthSec;
        let estMin = Math.max(5, Math.round(estSec / 60 / 5) * 5);
        timeSlider.value = Math.min(timeSlider.max, estMin);
        timeInput.value = estMin;

        const hrs = Math.floor(estMin / 60);
        const mins = estMin % 60;
        const hrStr = hrs > 0 ? `${hrs}h ${mins.toString().padStart(2, "0")}m` : `${mins}m`;
        timeDisplay.textContent = `${estMin} min (${hrStr})`;
    }

    if (timeSlider && timeInput) {
        timeSlider.addEventListener("input", (e) => updateFromTime(e.target.value));
        timeInput.addEventListener("change", (e) => updateFromTime(e.target.value));
    }

    if (songsSlider && songsInput) {
        songsSlider.addEventListener("input", (e) => updateFromSongs(e.target.value));
        songsInput.addEventListener("change", (e) => updateFromSongs(e.target.value));
    }

    // Initial sync
    updateFromTime(60);

    // 2. Generator System Selector Tabs
    const sysBtns = document.querySelectorAll(".btn-system");
    sysBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            sysBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            const sys = btn.dataset.system;
            document.querySelectorAll(".system-panel").forEach(p => p.style.display = "none");
            const activePanel = document.getElementById(`panel-${sys}`);
            if (activePanel) activePanel.style.display = "block";
        });
    });

    // 2.5 Dynamic Venn Diagram Controls & Wiring (1 to 4 Circles)
    const btnAddVennCircle = document.getElementById("btn-add-venn-circle");
    if (btnAddVennCircle) {
        btnAddVennCircle.addEventListener("click", addVennCircle);
    }

    const vennTypeBtns = document.querySelectorAll(".btn-venn-type");
    vennTypeBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            vennTypeBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentVennType = btn.dataset.type;

            // Reset circles to sensible defaults for this mode
            if (currentVennType === "artist_artist") {
                activeVennCircles = [
                    { value: "Pink Floyd", color: VENN_COLORS[0] },
                    { value: "Dire Straits", color: VENN_COLORS[1] }
                ];
            } else if (currentVennType === "genre_decade") {
                activeVennCircles = [
                    { value: "Classic Rock", color: VENN_COLORS[0] },
                    { value: "1970", color: VENN_COLORS[1] }
                ];
            } else {
                activeVennCircles = [
                    { value: "Rock", color: VENN_COLORS[0] },
                    { value: "Blues", color: VENN_COLORS[1] }
                ];
            }
            renderVennCircleCards();
            updateVennStats();
        });
    });



    // 3. AI Vibe Preset Chips
    document.querySelectorAll(".btn-prompt-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const promptInput = document.getElementById("playlist-ai-prompt");
            if (promptInput) {
                promptInput.value = chip.dataset.prompt;
                promptInput.focus();
            }
        });
    });

    // 4. Clean & Deduplicate + Tag Genres Buttons
    const btnSanitize = document.getElementById("btn-sanitize-library");
    if (btnSanitize) {
        btnSanitize.addEventListener("click", sanitizeLibrary);
    }

    const btnTagGenres = document.getElementById("btn-tag-genres");
    if (btnTagGenres) {
        btnTagGenres.addEventListener("click", tagAllLibraryGenres);
    }

    // 5. Generate Playlist Button
    const btnGen = document.getElementById("btn-generate-playlist");
    if (btnGen) {
        btnGen.addEventListener("click", generatePlaylist);
    }

    // Title Input live sync with Preview Header
    const playlistTitleInput = document.getElementById("playlist-title-input");
    if (playlistTitleInput) {
        playlistTitleInput.addEventListener("input", () => {
            const titleEl = document.getElementById("preview-playlist-title");
            if (titleEl) {
                titleEl.textContent = playlistTitleInput.value.trim() || "My Playlist";
            }
        });
    }

    // Title Reroll / Suggestion Button
    const btnRerollTitle = document.getElementById("btn-reroll-playlist-title");
    if (btnRerollTitle) {
        btnRerollTitle.addEventListener("click", async () => {
            if (!currentPlaylistTracks || currentPlaylistTracks.length === 0) {
                showToast("Generate a playlist first to get title suggestions", "info");
                return;
            }
            const origHtml = btnRerollTitle.innerHTML;
            btnRerollTitle.disabled = true;
            btnRerollTitle.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i>`;
            try {
                const activeSysBtn = document.querySelector(".btn-system.active");
                const mode = activeSysBtn ? activeSysBtn.dataset.system : "random";
                const params = { mode };
                if (mode === "genre_combo") {
                    params.genres = Array.from(document.querySelectorAll("#playlist-genre-chips .chip-selectable.selected")).map(c => c.dataset.genre);
                } else if (mode === "decade") {
                    params.decades = Array.from(document.querySelectorAll("#playlist-decade-chips .chip-selectable.selected")).map(c => parseInt(c.dataset.decade));
                } else if (mode === "artist_seed") {
                    params.seed_artists = Array.from(document.querySelectorAll("#playlist-seed-artists .chip-selectable.selected")).map(c => c.dataset.artist);
                } else if (mode === "ai") {
                    params.prompt = document.getElementById("playlist-ai-prompt")?.value?.trim() || "";
                } else if (mode === "venn") {
                    params.targets = (typeof activeVennCircles !== 'undefined') ? activeVennCircles.map(c => c.value.trim()).filter(Boolean) : [];
                    params.target_a = (typeof activeVennCircles !== 'undefined' && activeVennCircles[0]) ? activeVennCircles[0].value : "";
                    params.target_b = (typeof activeVennCircles !== 'undefined' && activeVennCircles[1]) ? activeVennCircles[1].value : "";
                }

                const res = await fetch("/api/playlist/suggest-title", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        mode: mode,
                        params: params,
                        tracks: currentPlaylistTracks
                    })
                });
                const data = await res.json();
                if (data.playlist_name) {
                    if (playlistTitleInput) playlistTitleInput.value = data.playlist_name;
                    const titleEl = document.getElementById("preview-playlist-title");
                    if (titleEl) titleEl.textContent = data.playlist_name;
                    showToast(`Suggested: "${data.playlist_name}"`, "success");
                }
            } catch (e) {
                showToast("Error getting playlist name suggestion", "error");
            } finally {
                btnRerollTitle.disabled = false;
                btnRerollTitle.innerHTML = origHtml;
            }
        });
    }

    // 6. Preview Actions (Shuffle, Clear)
    const btnShuffle = document.getElementById("btn-playlist-shuffle");
    if (btnShuffle) {
        btnShuffle.addEventListener("click", () => {
            if (currentPlaylistTracks.length > 1) {
                for (let i = currentPlaylistTracks.length - 1; i > 0; i--) {
                    const j = Math.floor(Math.random() * (i + 1));
                    [currentPlaylistTracks[i], currentPlaylistTracks[j]] = [currentPlaylistTracks[j], currentPlaylistTracks[i]];
                }
                renderPlaylistPreview(currentPlaylistTracks);
                showToast("Tracklist shuffled!", "info");
            }
        });
    }

    const btnClear = document.getElementById("btn-playlist-clear");
    if (btnClear) {
        btnClear.addEventListener("click", () => {
            currentPlaylistTracks = [];
            const previewSection = document.getElementById("playlist-preview-section");
            if (previewSection) previewSection.style.display = "none";
            const btnReroll = document.getElementById("btn-reroll-playlist-title");
            if (btnReroll) btnReroll.style.display = "none";
        });
    }

    // 7. Export Handlers
    const btnM3u8 = document.getElementById("btn-export-m3u8");
    if (btnM3u8) btnM3u8.addEventListener("click", () => exportPlaylist("m3u8"));

    const btnPls = document.getElementById("btn-export-pls");
    if (btnPls) btnPls.addEventListener("click", () => exportPlaylist("pls"));

    const btnJson = document.getElementById("btn-export-json");
    if (btnJson) btnJson.addEventListener("click", () => exportPlaylist("json"));

    const btnZip = document.getElementById("btn-export-zip");
    if (btnZip) btnZip.addEventListener("click", () => exportPlaylist("zip"));
}

async function loadPlaylistMetadata(force = false) {
    if (playlistMetadataLoaded && !force) return;
    try {
        const res = await fetch("/api/playlist/meta");
        const data = await res.json();

        if (data.avg_track_length) {
            libraryAvgSongLengthSec = data.avg_track_length;
            const avgMinEl = document.getElementById("lib-avg-len");
            if (avgMinEl) avgMinEl.textContent = (libraryAvgSongLengthSec / 60).toFixed(1);
        }

        // 1. Populate ALL Detected Genre Chips
        const genreContainer = document.getElementById("playlist-genre-chips");
        if (genreContainer && data.genres) {
            genreContainer.innerHTML = data.genres.map((g, idx) => `
                <div class="chip-selectable ${idx < 2 ? 'selected' : ''}" data-genre="${escapeHtml(g.name)}" data-id="${g.id}">
                    <span>${escapeHtml(g.name)}</span>
                    <span class="chip-count">${g.count}</span>
                </div>
            `).join("");

            genreContainer.querySelectorAll(".chip-selectable").forEach(chip => {
                chip.addEventListener("click", () => chip.classList.toggle("selected"));
            });

            // Live filter for genres
            const genreFilter = document.getElementById("filter-genre-chips");
            if (genreFilter) {
                genreFilter.value = "";
                genreFilter.oninput = (e) => {
                    const q = e.target.value.toLowerCase().trim();
                    genreContainer.querySelectorAll(".chip-selectable").forEach(chip => {
                        const txt = (chip.dataset.genre || "").toLowerCase();
                        chip.style.display = !q || txt.includes(q) ? "" : "none";
                    });
                };
            }
        }

        // 2. Populate Decade Chips
        const decadeContainer = document.getElementById("playlist-decade-chips");
        if (decadeContainer && data.decades) {
            decadeContainer.innerHTML = data.decades.map((d, idx) => `
                <div class="chip-selectable ${idx >= 2 && idx <= 5 ? 'selected' : ''}" data-decade="${d.decade}">
                    <span>${d.label}</span>
                    <span class="chip-count">${d.count}</span>
                </div>
            `).join("");

            decadeContainer.querySelectorAll(".chip-selectable").forEach(chip => {
                chip.addEventListener("click", () => chip.classList.toggle("selected"));
            });
        }

        // 3. Populate ALL Detected Artists
        const seedContainer = document.getElementById("playlist-seed-artists");
        if (seedContainer && data.top_artists) {
            const counts = data.artist_counts || {};
            seedContainer.innerHTML = data.top_artists.map((art, idx) => {
                const name = (typeof art === "object" && art !== null) ? (art.name || "") : String(art || "");
                const count = (typeof art === "object" && art !== null) ? art.count : counts[name];
                return `
                    <div class="chip-selectable ${idx === 0 ? 'selected' : ''}" data-artist="${escapeHtml(name)}">
                        <i class="fa-solid fa-microphone-lines"></i>
                        <span>${escapeHtml(name)}</span>
                        ${count ? `<span class="chip-count">${count}</span>` : ""}
                    </div>
                `;
            }).join("");

            seedContainer.querySelectorAll(".chip-selectable").forEach(chip => {
                chip.addEventListener("click", () => {
                    const selected = seedContainer.querySelectorAll(".chip-selectable.selected");
                    if (!chip.classList.contains("selected") && selected.length >= 6) {
                        showToast("You can choose up to 6 seed artists", "info");
                        return;
                    }
                    chip.classList.toggle("selected");
                });
            });

            // Live filter for artists
            const artistFilter = document.getElementById("filter-artist-chips");
            if (artistFilter) {
                artistFilter.value = "";
                artistFilter.oninput = (e) => {
                    const q = e.target.value.toLowerCase().trim();
                    seedContainer.querySelectorAll(".chip-selectable").forEach(chip => {
                        const txt = (chip.dataset.artist || "").toLowerCase();
                        chip.style.display = !q || txt.includes(q) ? "" : "none";
                    });
                };
            }
        }

        // 4. Populate Venn Diagram Datalists
        populateVennDatalists(data);
        updateVennStats();

        playlistMetadataLoaded = true;
    } catch (e) {
        console.error("Error loading playlist metadata:", e);
    }
}

async function sanitizeLibrary() {
    if (!confirm("Run library cleanup and deduplication? This prunes ghost DB entries, merges duplicate references, and normalizes file paths in the background.")) {
        return;
    }
    try {
        const res = await fetch("/api/library/sanitize", { method: "POST" });
        const data = await res.json();
        showToast("Library cleanup started! Watch live progress in the banner.", "success");
        playlistMetadataLoaded = false;
        setTimeout(() => loadPlaylistMetadata(true), 3000);
    } catch (e) {
        showToast("Error initiating library cleanup", "error");
    }
}

async function tagAllLibraryGenres() {
    if (!confirm("Run full library genre tagging across all songs? This queries Last.fm and seeds your library with rich genre tags and writes them to audio files. It runs smoothly in the background.")) {
        return;
    }

    try {
        const res = await fetch("/api/library/tag-genres", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ force: false })
        });
        const data = await res.json();
        showToast("Full library genre tagging started! Watch live progress in the banner or Live Console.", "success");
        playlistMetadataLoaded = false; // reload metadata after tagging
    } catch (e) {
        showToast("Error initiating library genre tagging", "error");
    }
}

async function generatePlaylist() {
    const btnGen = document.getElementById("btn-generate-playlist");
    const origHtml = btnGen.innerHTML;
    btnGen.disabled = true;
    btnGen.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Curating Playlist...`;

    try {
        const activeSysBtn = document.querySelector(".btn-system.active");
        const mode = activeSysBtn ? activeSysBtn.dataset.system : "random";

        const timeMinutes = parseInt(document.getElementById("playlist-time-input").value) || 60;
        const targetTracks = parseInt(document.getElementById("playlist-songs-input").value) || 15;

        const limitRadio = document.querySelector('input[name="playlist-limit-by"]:checked');
        const limitBy = limitRadio ? limitRadio.value : "time";

        const playlistNameInput = document.getElementById("playlist-title-input");
        const playlistName = (playlistNameInput && playlistNameInput.value.trim()) ? playlistNameInput.value.trim() : "";

        const payload = {
            mode,
            duration_sec: timeMinutes * 60,
            target_tracks: targetTracks,
            limit_by: limitBy,
            playlist_name: playlistName
        };

        if (mode === "genre_combo") {
            const selectedChips = document.querySelectorAll("#playlist-genre-chips .chip-selectable.selected");
            const selectedGenres = Array.from(selectedChips).map(c => c.dataset.genre);
            if (selectedGenres.length === 0) {
                showToast("Please select at least one genre for the combo", "error");
                btnGen.disabled = false;
                btnGen.innerHTML = origHtml;
                return;
            }
            const blendRadio = document.querySelector('input[name="blend-mode"]:checked');
            payload.genres = selectedGenres;
            payload.blend_mode = blendRadio ? blendRadio.value : "interleaved";
        } else if (mode === "random") {
            const divToggle = document.getElementById("shuffle-diversity-toggle");
            payload.smart_shuffle = divToggle ? divToggle.checked : true;
        } else if (mode === "ai") {
            const promptInput = document.getElementById("playlist-ai-prompt");
            const prompt = (promptInput && promptInput.value.trim()) ? promptInput.value.trim() : "Energetic driving road trip rock mix";
            const modelSelect = document.getElementById("ai-model-select");
            payload.prompt = prompt;
            payload.model = modelSelect ? modelSelect.value : null;
        } else if (mode === "decade") {
            const selectedDecades = Array.from(document.querySelectorAll("#playlist-decade-chips .chip-selectable.selected")).map(c => parseInt(c.dataset.decade));
            const chronoToggle = document.getElementById("decade-chrono-toggle");
            payload.decades = selectedDecades.length > 0 ? selectedDecades : [1970, 1980, 1990];
            payload.chronological = chronoToggle ? chronoToggle.checked : true;
        } else if (mode === "artist_seed") {
            const selectedSeeds = Array.from(document.querySelectorAll("#playlist-seed-artists .chip-selectable.selected")).map(c => c.dataset.artist);
            payload.seed_artists = selectedSeeds.length > 0 ? selectedSeeds : ["Pink Floyd"];
        } else if (mode === "venn") {
            const sliceRadio = document.querySelector('input[name="venn-slice"]:checked');
            const vennSlice = sliceRadio ? sliceRadio.value : "overlap_only";

            payload.overlap_type = currentVennType;
            payload.targets = activeVennCircles.map(c => c.value.trim()).filter(Boolean);
            payload.target_a = activeVennCircles[0]?.value || "";
            payload.target_b = activeVennCircles[1]?.value || "";
            payload.venn_slice = vennSlice;
            payload.selected_region = selectedVennRegion;
        }

        const res = await fetch("/api/playlist/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (data.success && data.tracks && data.tracks.length > 0) {
            currentPlaylistTracks = data.tracks;
            const finalPlaylistName = data.playlist_name || playlistName || "My Playlist";
            if (playlistNameInput) {
                playlistNameInput.value = finalPlaylistName;
            }
            const btnRerollTitle = document.getElementById("btn-reroll-playlist-title");
            if (btnRerollTitle) {
                btnRerollTitle.style.display = "inline-flex";
            }
            renderPlaylistPreview(currentPlaylistTracks, finalPlaylistName, data.summary);
            showToast(`Generated playlist with ${data.tracks.length} tracks!`, "success");

            const previewEl = document.getElementById("playlist-preview-section");
            if (previewEl) {
                previewEl.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        } else {
            showToast("Could not find enough tracks matching criteria in library", "error");
        }
    } catch (e) {
        showToast("Error generating playlist: " + e.message, "error");
    } finally {
        btnGen.disabled = false;
        btnGen.innerHTML = origHtml;
    }
}

function renderPlaylistPreview(tracks, title = null, summary = null) {
    const previewSection = document.getElementById("playlist-preview-section");
    const tbody = document.getElementById("playlist-table").querySelector("tbody");
    if (!previewSection || !tbody) return;

    if (title) {
        const titleEl = document.getElementById("preview-playlist-title");
        if (titleEl) titleEl.textContent = title;
    }

    const totalSec = tracks.reduce((acc, t) => acc + (t.length || 0), 0);
    const totalBytes = tracks.reduce((acc, t) => {
        if (t.size_bytes && t.size_bytes > 0) return acc + t.size_bytes;
        if (t.length && t.length > 0) return acc + (t.length * 24000);
        return acc;
    }, 0);
    const hrs = Math.floor(totalSec / 3600);
    const mins = Math.floor((totalSec % 3600) / 60);
    const secStr = totalSec % 60;
    const durFormatted = hrs > 0 ? `${hrs}h ${mins.toString().padStart(2, "0")}m` : `${mins}m ${secStr}s`;

    document.getElementById("preview-track-count").innerHTML = `<i class="fa-solid fa-music"></i> ${tracks.length} Tracks`;
    document.getElementById("preview-duration").innerHTML = `<i class="fa-regular fa-clock"></i> ${durFormatted}`;
    document.getElementById("preview-size").innerHTML = `<i class="fa-solid fa-hard-drive"></i> ${(totalBytes / (1024 * 1024)).toFixed(1)} MB`;

    tbody.innerHTML = tracks.map((t, i) => `
        <tr data-index="${i}" data-track-id="${t.id || ''}">
            <td class="text-muted" style="font-family: var(--font-mono); font-size: 12px;">${(i + 1).toString().padStart(2, "0")}</td>
            <td style="text-align: center;">
                <button type="button" class="btn-track-play btn-playlist-play" data-index="${i}" data-track-id="${t.id || ''}" title="Play Preview">
                    <i class="fa-solid fa-play"></i>
                </button>
            </td>
            <td><strong>${escapeHtml(t.title)}</strong></td>
            <td>${escapeHtml(t.artist)}</td>
            <td class="text-muted">${escapeHtml(t.album || "-")}</td>
            <td><span class="badge" style="font-size: 11px;">${escapeHtml(t.genre || "Rock")}</span></td>
            <td style="font-family: var(--font-mono); font-size: 12px;">${escapeHtml(t.length_str || t.duration || (t.length ? `${Math.floor(t.length / 60)}:${(t.length % 60).toString().padStart(2, "0")}` : "0:00"))}</td>
            <td class="text-right">
                <div style="display: inline-flex; gap: 6px; align-items: center; justify-content: flex-end;">
                    ${t.id ? `<a href="/api/audio/download/${t.id}" download class="btn btn-secondary btn-sm btn-download-song" title="Download &quot;${escapeAttr(t.title)}&quot; directly"><i class="fa-solid fa-download"></i></a>` : ''}
                    <button type="button" class="btn-remove-track" data-index="${i}" title="Remove track from playlist">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join("");

    tbody.querySelectorAll(".btn-playlist-play").forEach(btn => {
        btn.addEventListener("click", () => {
            const idx = parseInt(btn.dataset.index);
            const track = tracks[idx];
            if (track && audioManager) {
                audioManager.playTrack(track, tracks, idx, btn);
            }
        });
    });

    tbody.querySelectorAll(".btn-remove-track").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const idx = parseInt(btn.dataset.index);
            tracks.splice(idx, 1);
            currentPlaylistTracks = tracks;
            renderPlaylistPreview(tracks);
        });
    });

    if (audioManager) audioManager.updatePlayStateUI();

    previewSection.style.display = "block";
}

async function exportPlaylist(format) {
    if (!currentPlaylistTracks || currentPlaylistTracks.length === 0) {
        showToast("No playlist tracks available to export", "error");
        return;
    }

    const titleInput = document.getElementById("playlist-title-input");
    const previewTitleEl = document.getElementById("preview-playlist-title");
    const playlistName = (titleInput && titleInput.value.trim()) ? titleInput.value.trim() : (previewTitleEl?.textContent?.trim() || "My Playlist");
    const safeName = playlistName.replace(/[^a-zA-Z0-9_-]/g, "_") || "playlist";

    const btn = document.getElementById(`btn-export-${format}`);
    const origHtml = btn ? btn.innerHTML : "";
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${format === 'zip' ? 'Packaging ZIP...' : 'Exporting...'}`;
    }

    try {
        const res = await fetch(`/api/playlist/export/${format}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                playlist_name: playlistName,
                tracks: currentPlaylistTracks
            })
        });

        if (!res.ok) {
            throw new Error(`Export failed with HTTP status ${res.status}`);
        }

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.style.display = "none";
        a.href = url;
        a.download = `${safeName}.${format}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();

        showToast(`Downloaded ${safeName}.${format} successfully!`, "success");
    } catch (e) {
        showToast(`Export error: ${e.message}`, "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }
}

let cachedPlaylistMeta = null;

const VENN_COLORS = ["#3b82f6", "#ec4899", "#a855f7", "#10b981"];
let currentVennType = "genre_genre";
let activeVennCircles = [
    { value: "Rock", color: VENN_COLORS[0] },
    { value: "Blues", color: VENN_COLORS[1] }
];
let vennStatsDebounceTimer = null;
let selectedVennRegion = null;
let currentVennRegions = [];

function selectVennRegion(regionId) {
    if (!currentVennRegions || currentVennRegions.length === 0) return;
    const target = currentVennRegions.find(r => r.id === regionId);
    if (!target) return;

    selectedVennRegion = target;

    // 1. Highlight chips
    document.querySelectorAll(".venn-region-chip").forEach(chip => {
        if (chip.dataset.regionId === regionId) {
            chip.classList.add("active");
        } else {
            chip.classList.remove("active");
        }
    });

    // 2. Highlight SVG zones
    document.querySelectorAll(".venn-svg .venn-zone").forEach(zone => {
        if (zone.dataset.regionId === regionId) {
            zone.classList.add("selected-zone");
        } else {
            zone.classList.remove("selected-zone");
        }
    });

    // 3. Update header badge
    const badge = document.getElementById("venn-selected-region-badge");
    if (badge) {
        badge.innerHTML = `<i class="fa-solid fa-check"></i> Target: <strong>${escapeHtml(target.label)}</strong> (${target.count} tracks)`;
    }
}

function populateVennDatalists(data) {
    cachedPlaylistMeta = data;

    // 1. Populate Datalists
    const dlGenres = document.getElementById("venn-datalist-genres");
    if (dlGenres && data.genres) {
        dlGenres.innerHTML = data.genres.map(g => `<option value="${escapeHtml(g.name)}">${escapeHtml(g.name)} (${g.count})</option>`).join("");
    }

    const dlArtists = document.getElementById("venn-datalist-artists");
    if (dlArtists && data.top_artists) {
        const counts = data.artist_counts || {};
        dlArtists.innerHTML = data.top_artists.slice(0, 600).map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a)} (${counts[a] || 1})</option>`).join("");
    }

    const dlDecades = document.getElementById("venn-datalist-decades");
    if (dlDecades && data.decades) {
        dlDecades.innerHTML = data.decades.map(d => `<option value="${d.decade}">${d.label} (${d.count})</option>`).join("");
    }

    renderVennCircleCards();
    updateVennStats();
}

function renderVennCircleCards() {
    const container = document.getElementById("venn-circles-container");
    if (!container) return;

    const countBadge = document.getElementById("venn-circle-count-badge");
    if (countBadge) countBadge.textContent = `${activeVennCircles.length}/4`;

    const btnAdd = document.getElementById("btn-add-venn-circle");
    if (btnAdd) btnAdd.disabled = activeVennCircles.length >= 4;

    const datalistId = currentVennType === "artist_artist" 
        ? "venn-datalist-artists" 
        : (currentVennType === "genre_decade" ? "venn-datalist-decades" : "venn-datalist-genres");

    container.innerHTML = activeVennCircles.map((circle, idx) => {
        let typeLabel = "Genre";
        if (currentVennType === "artist_artist") typeLabel = "Artist";
        else if (currentVennType === "genre_decade") typeLabel = idx === 0 ? "Genre" : "Decade";

        const dl = (currentVennType === "genre_decade" && idx === 0) ? "venn-datalist-genres" : datalistId;

        return `
            <div class="venn-circle-card" style="border-left: 3px solid ${circle.color}">
                <div class="venn-circle-card-header">
                    <span class="venn-circle-tag" style="color: ${circle.color}">
                        <i class="fa-solid fa-circle"></i> Circle ${idx + 1} (${typeLabel})
                    </span>
                    <button type="button" class="btn-remove-circle" data-index="${idx}" ${activeVennCircles.length <= 1 ? 'style="display:none"' : ''} title="Remove this circle">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>
                <div class="input-with-icon-sm">
                    <input type="text" class="venn-circle-input chip-search-input" data-index="${idx}" list="${dl}" value="${escapeHtml(circle.value)}" placeholder="Pick or type ${typeLabel.toLowerCase()}...">
                </div>
            </div>
        `;
    }).join("");

    // Wire input typing
    container.querySelectorAll(".venn-circle-input").forEach(inp => {
        inp.addEventListener("input", (e) => {
            const idx = parseInt(e.target.dataset.index);
            if (activeVennCircles[idx]) {
                activeVennCircles[idx].value = e.target.value.trim();
                clearTimeout(vennStatsDebounceTimer);
                vennStatsDebounceTimer = setTimeout(updateVennStats, 350);
            }
        });
    });

    // Wire remove buttons
    container.querySelectorAll(".btn-remove-circle").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const idx = parseInt(btn.dataset.index);
            if (activeVennCircles.length > 1) {
                activeVennCircles.splice(idx, 1);
                // Re-assign colors
                activeVennCircles.forEach((c, i) => c.color = VENN_COLORS[i % VENN_COLORS.length]);
                renderVennCircleCards();
                updateVennStats();
                showToast("Circle removed from Venn diagram", "info");
            }
        });
    });
}

function addVennCircle() {
    if (activeVennCircles.length >= 4) {
        showToast("Maximum of 4 Venn circles allowed", "info");
        return;
    }

    const nextIdx = activeVennCircles.length;
    let nextVal = "Rock";
    if (currentVennType === "genre_genre") {
        const defaults = ["Rock", "Blues", "Electronic", "Rap"];
        nextVal = defaults[nextIdx] || "Pop";
    } else if (currentVennType === "artist_artist") {
        const defaults = ["Pink Floyd", "Dire Straits", "Led Zeppelin", "Queen"];
        nextVal = defaults[nextIdx] || "Queen";
    } else {
        const defaults = ["Classic Rock", "1970", "1980", "1990"];
        nextVal = defaults[nextIdx] || "1980";
    }

    activeVennCircles.push({
        value: nextVal,
        color: VENN_COLORS[nextIdx % VENN_COLORS.length]
    });

    renderVennCircleCards();
    updateVennStats();
    showToast(`Added Circle ${activeVennCircles.length}`, "success");
}

function renderVennSvg(data) {
    const wrap = document.getElementById("venn-svg-wrap");
    if (!wrap) return;

    const n = activeVennCircles.length;
    const circles = data.circles || [];
    const pairwise = data.pairwise || [];
    const coreCount = data.count_full_overlap || 0;

    let svgInner = "";

    if (n === 1) {
        const c1 = circles[0] || { label: activeVennCircles[0].value, count: 0 };
        svgInner = `
            <svg viewBox="0 0 540 260" class="venn-svg">
                <defs>
                    <radialGradient id="grad-c1" cx="50%" cy="50%" r="65%">
                        <stop offset="0%" stop-color="${activeVennCircles[0].color}" stop-opacity="0.55" />
                        <stop offset="100%" stop-color="${activeVennCircles[0].color}" stop-opacity="0.15" />
                    </radialGradient>
                </defs>
                <circle cx="270" cy="130" r="95" fill="url(#grad-c1)" stroke="${activeVennCircles[0].color}" stroke-width="2.5" class="venn-zone" data-region-id="circle_0" />
                <text x="270" y="122" class="venn-text-label" style="font-size: 15px;">${escapeHtml(c1.label || "")}</text>
                <text x="270" y="148" class="venn-text-count" style="font-size: 13px;">${c1.count || 0} tracks</text>
            </svg>
        `;
    } else if (n === 2) {
        const c1 = circles[0] || { label: activeVennCircles[0].value, count: 0 };
        const c2 = circles[1] || { label: activeVennCircles[1].value, count: 0 };
        const p12 = pairwise[0] || { count: coreCount };

        svgInner = `
            <svg viewBox="0 0 540 280" class="venn-svg">
                <defs>
                    <radialGradient id="grad-c1" cx="35%" cy="50%" r="60%">
                        <stop offset="0%" stop-color="${activeVennCircles[0].color}" stop-opacity="0.5" />
                        <stop offset="100%" stop-color="${activeVennCircles[0].color}" stop-opacity="0.12" />
                    </radialGradient>
                    <radialGradient id="grad-c2" cx="65%" cy="50%" r="60%">
                        <stop offset="0%" stop-color="${activeVennCircles[1].color}" stop-opacity="0.5" />
                        <stop offset="100%" stop-color="${activeVennCircles[1].color}" stop-opacity="0.12" />
                    </radialGradient>
                    <radialGradient id="grad-core" cx="50%" cy="50%" r="60%">
                        <stop offset="0%" stop-color="#c084fc" stop-opacity="0.75" />
                        <stop offset="100%" stop-color="#7c3aed" stop-opacity="0.3" />
                    </radialGradient>
                    <mask id="mask-c2"><circle cx="205" cy="138" r="95" fill="#fff" /></mask>
                </defs>

                <!-- Circles -->
                <circle cx="205" cy="138" r="95" fill="url(#grad-c1)" stroke="${activeVennCircles[0].color}" stroke-width="2.5" class="venn-zone" data-region-id="circle_0" />
                <circle cx="335" cy="138" r="95" fill="url(#grad-c2)" stroke="${activeVennCircles[1].color}" stroke-width="2.5" class="venn-zone" data-region-id="circle_1" />

                <!-- Intersection Zone -->
                <circle cx="335" cy="138" r="95" fill="url(#grad-core)" stroke="#c084fc" stroke-width="1.5" stroke-opacity="0.4" mask="url(#mask-c2)" pointer-events="none" />

                <!-- Left Circle Info -->
                <text x="145" y="132" class="venn-text-label">${escapeHtml((c1.label || "").slice(0, 14))}</text>
                <text x="145" y="154" class="venn-text-count">${c1.count || 0} tracks</text>

                <!-- Center Sweet Spot Info -->
                <g class="venn-zone" data-region-id="overlap_core" style="cursor: pointer;">
                    <rect x="225" y="105" width="90" height="66" rx="10" fill="rgba(15, 23, 42, 0.75)" stroke="#c084fc" stroke-width="1.5" />
                    <text x="270" y="125" class="venn-text-label venn-overlap-label" style="font-size: 11px;">Sweet Spot</text>
                    <text x="270" y="145" class="venn-text-count venn-overlap-count" style="font-size: 13px;">${coreCount} tracks</text>
                    <text x="270" y="160" class="venn-text-sub">1 ∩ 2</text>
                </g>

                <!-- Right Circle Info -->
                <text x="395" y="132" class="venn-text-label">${escapeHtml((c2.label || "").slice(0, 14))}</text>
                <text x="395" y="154" class="venn-text-count">${c2.count || 0} tracks</text>
            </svg>
        `;
    } else if (n === 3) {
        const c1 = circles[0] || { label: activeVennCircles[0].value, count: 0 };
        const c2 = circles[1] || { label: activeVennCircles[1].value, count: 0 };
        const c3 = circles[2] || { label: activeVennCircles[2].value, count: 0 };

        const p01 = pairwise.find(p => (p.indices[0] === 0 && p.indices[1] === 1)) || { count: 0 };
        const p02 = pairwise.find(p => (p.indices[0] === 0 && p.indices[1] === 2)) || { count: 0 };
        const p12 = pairwise.find(p => (p.indices[0] === 1 && p.indices[1] === 2)) || { count: 0 };

        svgInner = `
            <svg viewBox="0 0 540 330" class="venn-svg">
                <!-- Main 3 Circles -->
                <circle cx="270" cy="115" r="85" fill="${activeVennCircles[0].color}" fill-opacity="0.25" stroke="${activeVennCircles[0].color}" stroke-width="2.5" class="venn-zone" data-region-id="circle_0" />
                <circle cx="195" cy="215" r="85" fill="${activeVennCircles[1].color}" fill-opacity="0.25" stroke="${activeVennCircles[1].color}" stroke-width="2.5" class="venn-zone" data-region-id="circle_1" />
                <circle cx="345" cy="215" r="85" fill="${activeVennCircles[2].color}" fill-opacity="0.25" stroke="${activeVennCircles[2].color}" stroke-width="2.5" class="venn-zone" data-region-id="circle_2" />

                <!-- Circle Exclusive Labels -->
                <text x="270" y="65" class="venn-text-label">${escapeHtml((c1.label || "").slice(0, 14))}</text>
                <text x="270" y="82" class="venn-text-count">${c1.count || 0}</text>

                <text x="135" y="220" class="venn-text-label">${escapeHtml((c2.label || "").slice(0, 14))}</text>
                <text x="135" y="238" class="venn-text-count">${c2.count || 0}</text>

                <text x="405" y="220" class="venn-text-label">${escapeHtml((c3.label || "").slice(0, 14))}</text>
                <text x="405" y="238" class="venn-text-count">${c3.count || 0}</text>

                <!-- Pairwise 0 ∩ 1 Crossover Pill -->
                <g class="venn-zone" data-region-id="overlap_0_1" style="cursor: pointer;">
                    <rect x="180" y="140" width="60" height="28" rx="8" fill="rgba(15, 23, 42, 0.85)" stroke="#38bdf8" stroke-width="1.2" />
                    <text x="210" y="153" class="venn-text-label" style="font-size: 10px; fill: #7dd3fc;">1 ∩ 2</text>
                    <text x="210" y="164" class="venn-text-count" style="font-size: 10px;">${p01.count} trk</text>
                </g>

                <!-- Pairwise 0 ∩ 2 Crossover Pill -->
                <g class="venn-zone" data-region-id="overlap_0_2" style="cursor: pointer;">
                    <rect x="300" y="140" width="60" height="28" rx="8" fill="rgba(15, 23, 42, 0.85)" stroke="#38bdf8" stroke-width="1.2" />
                    <text x="330" y="153" class="venn-text-label" style="font-size: 10px; fill: #7dd3fc;">1 ∩ 3</text>
                    <text x="330" y="164" class="venn-text-count" style="font-size: 10px;">${p02.count} trk</text>
                </g>

                <!-- Pairwise 1 ∩ 2 Crossover Pill -->
                <g class="venn-zone" data-region-id="overlap_1_2" style="cursor: pointer;">
                    <rect x="240" y="235" width="60" height="28" rx="8" fill="rgba(15, 23, 42, 0.85)" stroke="#38bdf8" stroke-width="1.2" />
                    <text x="270" y="248" class="venn-text-label" style="font-size: 10px; fill: #7dd3fc;">2 ∩ 3</text>
                    <text x="270" y="259" class="venn-text-count" style="font-size: 10px;">${p12.count} trk</text>
                </g>

                <!-- Core Overlap Sweet Spot -->
                <g class="venn-zone" data-region-id="overlap_core" style="cursor: pointer;">
                    <circle cx="270" cy="180" r="30" fill="#a855f7" fill-opacity="0.8" stroke="#e9d5ff" stroke-width="2" class="core-circle" />
                    <text x="270" y="176" class="venn-text-label venn-overlap-label" style="font-size: 10px;">Core</text>
                    <text x="270" y="190" class="venn-text-count venn-overlap-count" style="font-size: 12px;">${coreCount}</text>
                </g>
            </svg>
        `;
    } else {
        // N = 4 Circles in 2x2 Cluster with pairwise & core
        const c1 = circles[0] || { label: activeVennCircles[0].value, count: 0 };
        const c2 = circles[1] || { label: activeVennCircles[1].value, count: 0 };
        const c3 = circles[2] || { label: activeVennCircles[2].value, count: 0 };
        const c4 = circles[3] || { label: activeVennCircles[3].value, count: 0 };

        const p01 = pairwise.find(p => (p.indices[0] === 0 && p.indices[1] === 1)) || { count: 0 };
        const p23 = pairwise.find(p => (p.indices[0] === 2 && p.indices[1] === 3)) || { count: 0 };

        svgInner = `
            <svg viewBox="0 0 540 330" class="venn-svg">
                <!-- 4 Circles -->
                <circle cx="205" cy="105" r="72" fill="${activeVennCircles[0].color}" fill-opacity="0.25" stroke="${activeVennCircles[0].color}" stroke-width="2" class="venn-zone" data-region-id="circle_0" />
                <circle cx="335" cy="105" r="72" fill="${activeVennCircles[1].color}" fill-opacity="0.25" stroke="${activeVennCircles[1].color}" stroke-width="2" class="venn-zone" data-region-id="circle_1" />
                <circle cx="205" cy="225" r="72" fill="${activeVennCircles[2].color}" fill-opacity="0.25" stroke="${activeVennCircles[2].color}" stroke-width="2" class="venn-zone" data-region-id="circle_2" />
                <circle cx="335" cy="225" r="72" fill="${activeVennCircles[3].color}" fill-opacity="0.25" stroke="${activeVennCircles[3].color}" stroke-width="2" class="venn-zone" data-region-id="circle_3" />

                <!-- Circle Labels -->
                <text x="155" y="75" class="venn-text-label">${escapeHtml((c1.label || "").slice(0, 11))}</text>
                <text x="155" y="90" class="venn-text-count">${c1.count || 0}</text>

                <text x="385" y="75" class="venn-text-label">${escapeHtml((c2.label || "").slice(0, 11))}</text>
                <text x="385" y="90" class="venn-text-count">${c2.count || 0}</text>

                <text x="155" y="240" class="venn-text-label">${escapeHtml((c3.label || "").slice(0, 11))}</text>
                <text x="155" y="255" class="venn-text-count">${c3.count || 0}</text>

                <text x="385" y="240" class="venn-text-label">${escapeHtml((c4.label || "").slice(0, 11))}</text>
                <text x="385" y="255" class="venn-text-count">${c4.count || 0}</text>

                <!-- Top Crossover 0 ∩ 1 -->
                <g class="venn-zone" data-region-id="overlap_0_1" style="cursor: pointer;">
                    <rect x="245" y="90" width="50" height="24" rx="6" fill="rgba(15, 23, 42, 0.85)" stroke="#38bdf8" stroke-width="1" />
                    <text x="270" y="102" class="venn-text-label" style="font-size: 9px; fill: #7dd3fc;">1 ∩ 2</text>
                    <text x="270" y="111" class="venn-text-count" style="font-size: 9px;">${p01.count}</text>
                </g>

                <!-- Bottom Crossover 2 ∩ 3 -->
                <g class="venn-zone" data-region-id="overlap_2_3" style="cursor: pointer;">
                    <rect x="245" y="215" width="50" height="24" rx="6" fill="rgba(15, 23, 42, 0.85)" stroke="#38bdf8" stroke-width="1" />
                    <text x="270" y="227" class="venn-text-label" style="font-size: 9px; fill: #7dd3fc;">3 ∩ 4</text>
                    <text x="270" y="236" class="venn-text-count" style="font-size: 9px;">${p23.count}</text>
                </g>

                <!-- 4-Circle Core Sweet Spot -->
                <g class="venn-zone" data-region-id="overlap_core" style="cursor: pointer;">
                    <circle cx="270" cy="165" r="28" fill="#a855f7" fill-opacity="0.85" stroke="#e9d5ff" stroke-width="2" class="core-circle" />
                    <text x="270" y="161" class="venn-text-label venn-overlap-label" style="font-size: 10px;">Sweet Spot</text>
                    <text x="270" y="175" class="venn-text-count venn-overlap-count" style="font-size: 12px;">${coreCount}</text>
                </g>
            </svg>
        `;
    }

    wrap.innerHTML = svgInner;

    // Attach click handlers to all clickable SVG zones
    wrap.querySelectorAll(".venn-zone").forEach(el => {
        el.addEventListener("click", () => {
            const regId = el.dataset.regionId;
            if (regId) {
                selectVennRegion(regId);
            }
        });
    });
}

async function updateVennStats() {
    const targets = activeVennCircles.map(c => c.value.trim()).filter(Boolean);
    if (targets.length === 0) return;

    try {
        const res = await fetch("/api/playlist/venn-stats", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                overlap_type: currentVennType,
                targets: targets
            })
        });
        if (!res.ok) return;
        const data = await res.json();

        currentVennRegions = data.regions || [];

        // Determine default selection if current is not set or invalid
        if (!selectedVennRegion || !currentVennRegions.some(r => r.id === selectedVennRegion.id)) {
            const coreReg = currentVennRegions.find(r => r.id === "overlap_core" && r.count > 0);
            const firstPair = currentVennRegions.find(r => r.type === "pairwise" && r.count > 0);
            const circleReg = currentVennRegions.find(r => r.type === "circle");
            selectedVennRegion = coreReg || firstPair || circleReg || currentVennRegions[0] || null;
        }

        // Render dynamic SVG
        renderVennSvg(data);

        // Render Interactive Selectable Region Chips
        const regContainer = document.getElementById("venn-regions-container");
        if (regContainer && currentVennRegions.length > 0) {
            regContainer.innerHTML = currentVennRegions.map(r => {
                const isAct = selectedVennRegion && selectedVennRegion.id === r.id;
                return `
                    <div class="venn-region-chip ${isAct ? 'active' : ''} ${r.count === 0 ? 'zero-count' : ''}" data-region-id="${r.id}" title="${escapeHtml(r.label)} - ${r.count} tracks">
                        <div class="chip-main">
                            <i class="fa-solid ${r.icon || 'fa-circle-nodes'}" style="color: ${r.color || '#a855f7'}"></i>
                            <span class="chip-name">${escapeHtml(r.label)}</span>
                        </div>
                        <div class="chip-side">
                            <span class="chip-count">${r.count} trk</span>
                            <span class="chip-select-indicator"><i class="fa-solid fa-check"></i></span>
                        </div>
                    </div>
                `;
            }).join("");

            regContainer.querySelectorAll(".venn-region-chip").forEach(chip => {
                chip.addEventListener("click", () => {
                    selectVennRegion(chip.dataset.regionId);
                });
            });
        }

        // Apply active region styling to SVG, chips, and badge
        if (selectedVennRegion) {
            selectVennRegion(selectedVennRegion.id);
        }

        // Update stats pills
        const coreNum = document.getElementById("venn-core-num");
        const unionNum = document.getElementById("venn-union-num");
        const corePill = document.getElementById("venn-stat-core");

        const coreVal = data.count_full_overlap || 0;
        const unionVal = data.count_any_overlap || 0;

        if (coreNum) coreNum.textContent = `${coreVal} tracks`;
        if (unionNum) unionNum.textContent = `${unionVal} tracks`;

        if (corePill) {
            corePill.classList.remove("zero-overlap", "has-overlap");
            if (coreVal === 0 && targets.length > 1) {
                corePill.classList.add("zero-overlap");
                coreNum.innerHTML = `0 tracks <small style="font-size: 10px; font-weight: normal;">(Select a pairwise overlap below or switch mode)</small>`;
            } else {
                corePill.classList.add("has-overlap");
            }
        }
    } catch (e) {
        console.debug("Venn stats update error:", e);
    }
}


// ============================================================================
// AUDIO MANAGER & PREVIEW CONTROLLER (v1.5.0)
// ============================================================================
class AudioManager {
    constructor() {
        this.audio = new Audio();
        this.currentTrack = null;
        this.queue = [];
        this.queueIndex = -1;
        this.isPlaying = false;
        this.isLoading = false;
        this.activeBtn = null;
        this.prevVolume = 0.8;

        this.initDOM();
        this.bindEvents();
    }

    initDOM() {
        this.barEl = document.getElementById("audio-player-bar");
        this.titleEl = document.getElementById("player-title");
        this.artistEl = document.getElementById("player-artist");
        this.artImg = document.getElementById("player-art");
        this.artPlaceholder = document.getElementById("player-art-placeholder");
        this.typeBadge = document.getElementById("player-type-badge");
        this.btnPlay = document.getElementById("player-btn-play");
        this.btnPrev = document.getElementById("player-btn-prev");
        this.btnNext = document.getElementById("player-btn-next");
        this.scrubber = document.getElementById("player-scrubber");
        this.currentTimeEl = document.getElementById("player-current-time");
        this.durationEl = document.getElementById("player-duration");
        this.volumeSlider = document.getElementById("player-volume");
        this.volumeIcon = document.getElementById("player-volume-icon");
        this.btnClose = document.getElementById("player-btn-close");
    }

    bindEvents() {
        if (!this.barEl) return;

        // Player controls
        this.btnPlay?.addEventListener("click", () => this.togglePlay());
        this.btnPrev?.addEventListener("click", () => this.prevTrack());
        this.btnNext?.addEventListener("click", () => this.nextTrack());
        this.btnClose?.addEventListener("click", () => this.close());

        // Scrubber
        this.scrubber?.addEventListener("input", (e) => {
            if (this.audio.duration && !isNaN(this.audio.duration)) {
                const targetTime = (parseFloat(e.target.value) / 100) * this.audio.duration;
                if (this.currentTimeEl) this.currentTimeEl.textContent = this.formatTime(targetTime);
            }
        });
        this.scrubber?.addEventListener("change", (e) => {
            if (this.audio.duration && !isNaN(this.audio.duration)) {
                this.audio.currentTime = (parseFloat(e.target.value) / 100) * this.audio.duration;
            }
        });

        // Volume
        this.volumeSlider?.addEventListener("input", (e) => {
            const val = parseFloat(e.target.value);
            this.audio.volume = val;
            this.updateVolumeIcon(val);
        });
        this.volumeIcon?.addEventListener("click", () => {
            if (this.audio.volume > 0) {
                this.prevVolume = this.audio.volume;
                this.audio.volume = 0;
                if (this.volumeSlider) this.volumeSlider.value = 0;
            } else {
                this.audio.volume = this.prevVolume || 0.8;
                if (this.volumeSlider) this.volumeSlider.value = this.audio.volume;
            }
            this.updateVolumeIcon(this.audio.volume);
        });

        // Audio element events
        this.audio.addEventListener("timeupdate", () => {
            if (!this.audio.duration || isNaN(this.audio.duration)) return;
            const pct = (this.audio.currentTime / this.audio.duration) * 100;
            if (this.scrubber) this.scrubber.value = pct;
            if (this.currentTimeEl) this.currentTimeEl.textContent = this.formatTime(this.audio.currentTime);
            if (this.durationEl) this.durationEl.textContent = this.formatTime(this.audio.duration);
        });

        this.audio.addEventListener("play", () => {
            this.isPlaying = true;
            this.isLoading = false;
            this.updatePlayStateUI();
        });

        this.audio.addEventListener("pause", () => {
            this.isPlaying = false;
            this.updatePlayStateUI();
        });

        this.audio.addEventListener("ended", () => {
            this.isPlaying = false;
            this.updatePlayStateUI();
            if (this.queue && this.queue.length > 0 && this.queueIndex < this.queue.length - 1) {
                this.nextTrack();
            }
        });

        this.audio.addEventListener("error", (e) => {
            this.isLoading = false;
            this.isPlaying = false;
            this.updatePlayStateUI();
            console.error("Audio playback error:", e);
            showToast("Error streaming audio preview", "error");
        });
    }

    updateVolumeIcon(vol) {
        if (!this.volumeIcon) return;
        if (vol <= 0) {
            this.volumeIcon.innerHTML = '<i class="fa-solid fa-volume-xmark"></i>';
        } else if (vol < 0.5) {
            this.volumeIcon.innerHTML = '<i class="fa-solid fa-volume-low"></i>';
        } else {
            this.volumeIcon.innerHTML = '<i class="fa-solid fa-volume-high"></i>';
        }
    }

    formatTime(sec) {
        if (!sec || isNaN(sec)) return "0:00";
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${m}:${s.toString().padStart(2, "0")}`;
    }

    async playTrack(track, queue = null, index = null, triggerBtn = null) {
        if (queue) {
            this.queue = queue;
            this.queueIndex = index !== null ? index : 0;
        }

        // Check if toggling the currently playing track
        if (this.currentTrack && (
            (track.id && String(this.currentTrack.id) === String(track.id)) ||
            (track.path && this.currentTrack.path === track.path) ||
            (track.artist && track.title && this.currentTrack.artist === track.artist && this.currentTrack.title === track.title)
        )) {
            this.togglePlay();
            return;
        }

        this.currentTrack = track;
        this.activeBtn = triggerBtn;
        this.isLoading = true;
        this.updateTrackInfoUI(track);
        this.updatePlayStateUI();

        try {
            let audioUrl = "";
            if (track.id) {
                audioUrl = `/api/audio/preview/${track.id}`;
            } else if (track.preview_url) {
                audioUrl = track.preview_url;
            } else if (track.artist && track.title) {
                // Fetch preview by query on-demand
                const res = await fetch(`/api/audio/preview-query?artist=${encodeURIComponent(track.artist)}&title=${encodeURIComponent(track.title)}`);
                const data = await res.json();
                if (!data.found || !data.preview_url) {
                    throw new Error("No preview available for this track");
                }
                audioUrl = data.preview_url;
                if (data.artwork_url) {
                    track.artwork_url = data.artwork_url;
                    this.setArtwork(data.artwork_url);
                }
                if (data.source_type) {
                    this.setTypeBadge(data.source_type === 'library' ? 'LIBRARY' : '30s PREVIEW');
                }
            } else if (track.path) {
                audioUrl = `/api/audio/preview-staging?file=${encodeURIComponent(track.path)}`;
            }

            if (!audioUrl) throw new Error("Could not resolve audio preview URL");

            this.audio.src = audioUrl;
            this.audio.load();
            await this.audio.play();
        } catch (err) {
            this.isLoading = false;
            this.isPlaying = false;
            this.updatePlayStateUI();
            showToast(err.message || "Failed to play preview", "error");
        }
    }

    async playQuery(artist, title, triggerBtn = null) {
        await this.playTrack({ artist, title, title_display: title }, null, null, triggerBtn);
    }

    async playStaging(path, name, triggerBtn = null) {
        await this.playTrack({ path, title: name || path, artist: "Staging File", type: "staging" }, null, null, triggerBtn);
    }

    togglePlay() {
        if (!this.audio.src) return;
        if (this.isPlaying) {
            this.audio.pause();
        } else {
            this.audio.play().catch(e => console.error(e));
        }
    }

    nextTrack() {
        if (!this.queue || this.queue.length === 0) return;
        if (this.queueIndex < this.queue.length - 1) {
            this.queueIndex++;
            this.playTrack(this.queue[this.queueIndex], this.queue, this.queueIndex);
        } else {
            showToast("Reached end of playlist", "info");
        }
    }

    prevTrack() {
        if (!this.queue || this.queue.length === 0) return;
        if (this.audio.currentTime > 3) {
            this.audio.currentTime = 0;
        } else if (this.queueIndex > 0) {
            this.queueIndex--;
            this.playTrack(this.queue[this.queueIndex], this.queue, this.queueIndex);
        }
    }

    close() {
        this.audio.pause();
        this.audio.src = "";
        this.isPlaying = false;
        this.isLoading = false;
        this.currentTrack = null;
        this.queue = [];
        this.queueIndex = -1;
        if (this.barEl) this.barEl.style.display = "none";
        this.updatePlayStateUI();
    }

    updateTrackInfoUI(track) {
        if (!this.barEl) return;
        this.barEl.style.display = "flex";

        if (this.titleEl) this.titleEl.textContent = track.title || "Unknown Title";
        if (this.artistEl) this.artistEl.textContent = track.artist || "Unknown Artist";

        this.setArtwork(track.artwork_url);

        const badgeText = track.type === 'staging' ? 'STAGING' : (track.id ? 'LIBRARY' : '30s PREVIEW');
        this.setTypeBadge(badgeText);
    }

    setArtwork(url) {
        if (!this.artImg || !this.artPlaceholder) return;
        if (url) {
            this.artImg.src = url;
            this.artImg.style.display = "block";
            this.artPlaceholder.style.display = "none";
        } else {
            this.artImg.style.display = "none";
            this.artPlaceholder.style.display = "flex";
        }
    }

    setTypeBadge(text) {
        if (this.typeBadge) this.typeBadge.textContent = text;
    }

    updatePlayStateUI() {
        // 1. Update Main Player Bar Play Button
        if (this.btnPlay) {
            if (this.isLoading) {
                this.btnPlay.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
            } else if (this.isPlaying) {
                this.btnPlay.innerHTML = '<i class="fa-solid fa-pause"></i>';
            } else {
                this.btnPlay.innerHTML = '<i class="fa-solid fa-play"></i>';
            }
        }

        // 2. Update all inline play buttons across the page
        document.querySelectorAll(".btn-track-play").forEach(btn => {
            const trackId = btn.dataset.trackId;
            const artist = btn.dataset.artist;
            const title = btn.dataset.title;
            const path = btn.dataset.path;

            const isMatch = this.currentTrack && (
                (trackId && String(trackId) === String(this.currentTrack.id)) ||
                (path && path === this.currentTrack.path) ||
                (artist && title && artist.toLowerCase() === (this.currentTrack.artist || "").toLowerCase() && title.toLowerCase() === (this.currentTrack.title || "").toLowerCase())
            );

            btn.classList.remove("is-playing", "is-loading");

            if (isMatch) {
                if (this.isLoading) {
                    btn.classList.add("is-loading");
                    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
                } else if (this.isPlaying) {
                    btn.classList.add("is-playing");
                    btn.innerHTML = '<i class="fa-solid fa-pause"></i>';
                } else {
                    btn.innerHTML = '<i class="fa-solid fa-play"></i>';
                }
            } else {
                btn.innerHTML = '<i class="fa-solid fa-play"></i>';
            }
        });

        // 3. Update table row highlights
        document.querySelectorAll("tr[data-track-id], tr[data-artist], tr[id^='missing-row-'], tr[id^='staging-row-']").forEach(tr => {
            const trackId = tr.dataset.trackId;
            const artist = tr.dataset.artist;
            const title = tr.dataset.title;
            const path = tr.dataset.path;

            const isMatch = this.currentTrack && (
                (trackId && String(trackId) === String(this.currentTrack.id)) ||
                (path && path === this.currentTrack.path) ||
                (artist && title && artist.toLowerCase() === (this.currentTrack.artist || "").toLowerCase() && title.toLowerCase() === (this.currentTrack.title || "").toLowerCase())
            );

            if (isMatch && this.isPlaying) {
                tr.classList.add("track-playing");
            } else {
                tr.classList.remove("track-playing");
            }
        });
    }
}

// ============================================================================
// LIBRARY BROWSER CONTROLLER (v1.5.0)
// ============================================================================
let librarySearchTimeout = null;
let libraryCurrentPage = 1;
const libraryPageSize = 50;
let libraryTotalTracks = 0;
let librarySortOrder = "asc";
let libraryBrowserLoaded = false;

// Library Hierarchy View State
let libraryViewMode = "hierarchy"; // "hierarchy" (default) or "table"
let libraryHierarchyPage = 1;
const libraryHierarchyPageSize = 25;
let libraryHierarchyTotal = 0;
let currentLibraryArtists = [];

async function initLibraryBrowser() {
    // View Switcher Buttons
    const btnHierarchy = document.getElementById("btn-lib-view-hierarchy");
    const btnTable = document.getElementById("btn-lib-view-table");

    if (btnHierarchy && btnTable) {
        btnHierarchy.addEventListener("click", () => {
            if (libraryViewMode === "hierarchy") return;
            libraryViewMode = "hierarchy";
            btnHierarchy.classList.add("active");
            btnTable.classList.remove("active");
            document.getElementById("library-hierarchy-container").style.display = "block";
            document.getElementById("library-table-container").style.display = "none";
            loadLibraryActiveView();
        });

        btnTable.addEventListener("click", () => {
            if (libraryViewMode === "table") return;
            libraryViewMode = "table";
            btnTable.classList.add("active");
            btnHierarchy.classList.remove("active");
            document.getElementById("library-hierarchy-container").style.display = "none";
            document.getElementById("library-table-container").style.display = "block";
            loadLibraryActiveView();
        });
    }

    // Search input (debounced)
    const searchInput = document.getElementById("library-search");
    if (searchInput) {
        searchInput.addEventListener("input", () => {
            clearTimeout(librarySearchTimeout);
            librarySearchTimeout = setTimeout(() => {
                libraryCurrentPage = 1;
                libraryHierarchyPage = 1;
                loadLibraryActiveView();
            }, 300);
        });
    }

    // Genre filter
    const genreSelect = document.getElementById("library-filter-genre");
    if (genreSelect) {
        genreSelect.addEventListener("change", () => {
            libraryCurrentPage = 1;
            libraryHierarchyPage = 1;
            loadLibraryActiveView();
        });
    }

    // Decade filter
    const decadeSelect = document.getElementById("library-filter-decade");
    if (decadeSelect) {
        decadeSelect.addEventListener("change", () => {
            libraryCurrentPage = 1;
            libraryHierarchyPage = 1;
            loadLibraryActiveView();
        });
    }

    // Sort by
    const sortSelect = document.getElementById("library-sort-by");
    if (sortSelect) {
        sortSelect.addEventListener("change", () => {
            libraryCurrentPage = 1;
            libraryHierarchyPage = 1;
            loadLibraryActiveView();
        });
    }

    // Sort order toggle button
    const sortOrderBtn = document.getElementById("library-sort-order");
    if (sortOrderBtn) {
        sortOrderBtn.addEventListener("click", () => {
            librarySortOrder = librarySortOrder === "asc" ? "desc" : "asc";
            sortOrderBtn.innerHTML = librarySortOrder === "asc"
                ? '<i class="fa-solid fa-arrow-up-a-z"></i>'
                : '<i class="fa-solid fa-arrow-down-z-a"></i>';
            libraryCurrentPage = 1;
            libraryHierarchyPage = 1;
            loadLibraryActiveView();
        });
    }

    // Pagination buttons
    const prevBtn = document.getElementById("library-prev-page");
    if (prevBtn) {
        prevBtn.addEventListener("click", () => {
            if (libraryViewMode === "hierarchy") {
                if (libraryHierarchyPage > 1) {
                    libraryHierarchyPage--;
                    loadLibraryHierarchy();
                }
            } else {
                if (libraryCurrentPage > 1) {
                    libraryCurrentPage--;
                    loadLibraryBrowser();
                }
            }
        });
    }

    const nextBtn = document.getElementById("library-next-page");
    if (nextBtn) {
        nextBtn.addEventListener("click", () => {
            if (libraryViewMode === "hierarchy") {
                const totalPages = Math.max(1, Math.ceil(libraryHierarchyTotal / libraryHierarchyPageSize));
                if (libraryHierarchyPage < totalPages) {
                    libraryHierarchyPage++;
                    loadLibraryHierarchy();
                }
            } else {
                const totalPages = Math.max(1, Math.ceil(libraryTotalTracks / libraryPageSize));
                if (libraryCurrentPage < totalPages) {
                    libraryCurrentPage++;
                    loadLibraryBrowser();
                }
            }
        });
    }

    // Populate genres into dropdown
    await populateLibraryGenres();

    // Initial load of active view
    loadLibraryActiveView();
}

function loadLibraryActiveView() {
    if (libraryViewMode === "hierarchy") {
        loadLibraryHierarchy();
    } else {
        loadLibraryBrowser();
    }
}

// ----------------------------------------------------------------------------
// HIERARCHICAL ARTIST -> ALBUM -> SONGS EXPLORER
// ----------------------------------------------------------------------------
async function loadLibraryHierarchy() {
    const listEl = document.getElementById("library-artists-list");
    const countEl = document.getElementById("library-total-count");
    const pageInfo = document.getElementById("library-page-info");
    const pageBadge = document.getElementById("library-current-page-badge");
    const prevBtn = document.getElementById("library-prev-page");
    const nextBtn = document.getElementById("library-next-page");

    if (!listEl) return;

    listEl.innerHTML = `
        <div class="p-4 text-center text-muted">
            <i class="fa-solid fa-spinner fa-spin fa-2x mb-2" style="color: var(--primary);"></i>
            <div>Loading library artists...</div>
        </div>
    `;

    const search = document.getElementById("library-search")?.value.trim() || "";
    const genre = document.getElementById("library-filter-genre")?.value || "";
    const decade = document.getElementById("library-filter-decade")?.value || "";
    const sortBy = document.getElementById("library-sort-by")?.value || "artist";
    const sortOrder = typeof librarySortOrder !== "undefined" ? librarySortOrder : "asc";

    const params = new URLSearchParams({
        page: libraryHierarchyPage,
        limit: libraryHierarchyPageSize,
        sort_by: sortBy,
        sort_order: sortOrder
    });
    if (search) params.append("query", search);
    if (genre) params.append("genre", genre);
    if (decade) params.append("decade", decade);

    try {
        const res = await fetch(`/api/library/artists?${params.toString()}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            console.error("API error loading artists:", res.status, err);
            listEl.innerHTML = `
                <div class="p-5 text-center text-danger">
                    <i class="fa-solid fa-triangle-exclamation fa-2x mb-2"></i>
                    <p>Failed to load artists (HTTP ${res.status}). Please try again.</p>
                </div>
            `;
            return;
        }
        const data = await res.json();

        libraryHierarchyTotal = data.total || 0;
        currentLibraryArtists = (data.artists || []).map(a => ({
            ...a,
            albums: null
        }));
        const totalPages = Math.max(1, Math.ceil(libraryHierarchyTotal / libraryHierarchyPageSize));

        if (countEl) countEl.textContent = `${libraryHierarchyTotal.toLocaleString()} artists found`;
        if (pageBadge) pageBadge.textContent = `${libraryHierarchyPage} / ${totalPages}`;
        if (pageInfo) {
            const start = libraryHierarchyTotal === 0 ? 0 : (libraryHierarchyPage - 1) * libraryHierarchyPageSize + 1;
            const end = Math.min(libraryHierarchyPage * libraryHierarchyPageSize, libraryHierarchyTotal);
            pageInfo.textContent = `Showing ${start}-${end} of ${libraryHierarchyTotal.toLocaleString()} artists`;
        }

        if (prevBtn) prevBtn.disabled = libraryHierarchyPage <= 1;
        if (nextBtn) nextBtn.disabled = libraryHierarchyPage >= totalPages;

        if (currentLibraryArtists.length === 0) {
            listEl.innerHTML = `
                <div class="p-5 text-center text-muted">
                    <i class="fa-solid fa-users-slash fa-2x mb-2" style="opacity: 0.4;"></i>
                    <p>No artists match your search criteria.</p>
                </div>
            `;
            return;
        }

        listEl.innerHTML = currentLibraryArtists.map((art, idx) => `
            <div class="lib-artist-item" data-index="${idx}" data-artist="${escapeAttr(art.name)}">
                <div class="lib-artist-row" data-index="${idx}">
                    <div class="lib-artist-left">
                        <div class="lib-artist-avatar">
                            <img src="${art.image_url || `/api/library/artist-art?artist=${encodeURIComponent(art.name)}`}" alt="${escapeAttr(art.name)}" loading="lazy" class="lib-artist-img" onload="this.classList.add('loaded')" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                            <i class="fa-solid fa-guitar fallback-icon" style="display: none;"></i>
                        </div>
                        <div class="lib-artist-info">
                            <div class="lib-artist-title-row">
                                <h3>${escapeHtml(art.name)}</h3>
                                <span class="badge" style="font-size: 11px;">${escapeHtml(art.genre || "Music")}</span>
                            </div>
                            <div class="lib-artist-meta">
                                <span><i class="fa-solid fa-compact-disc"></i> ${art.album_count} ${art.album_count === 1 ? 'album' : 'albums'}</span>
                                &bull;
                                <span><i class="fa-solid fa-music"></i> ${art.track_count} songs</span>
                                ${art.year_range ? `&bull; <span><i class="fa-solid fa-calendar"></i> ${art.year_range}</span>` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="lib-artist-right">
                        <button type="button" class="btn btn-secondary btn-sm btn-delete-artist" data-artist="${escapeAttr(art.name)}" title="Delete &quot;${escapeAttr(art.name)}&quot; &amp; all albums from Vault">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                        <button type="button" class="btn btn-secondary btn-sm btn-add-artist-pl" data-artist="${escapeAttr(art.name)}" title="Add all songs by ${escapeAttr(art.name)} to playlist">
                            <i class="fa-solid fa-plus"></i> Playlist
                        </button>
                        <button type="button" class="btn btn-secondary btn-sm btn-toggle-artist-albums" data-index="${idx}">
                            <i class="fa-solid fa-compact-disc"></i>
                            <span>Albums</span>
                            <i class="fa-solid fa-chevron-down toggle-chevron"></i>
                        </button>
                    </div>
                </div>

                <!-- Albums Drawer -->
                <div class="lib-albums-drawer" id="lib-artist-albums-${idx}" style="display: none;">
                    <div class="lib-albums-content" id="lib-artist-albums-content-${idx}">
                        <!-- Albums rendered dynamically -->
                    </div>
                </div>
            </div>
        `).join("");

        // Bind Artist Row Clicks to toggle albums
        listEl.querySelectorAll(".lib-artist-row").forEach((row, idx) => {
            row.addEventListener("click", (e) => {
                if (e.target.closest(".btn-add-artist-pl") || e.target.closest(".btn-toggle-artist-albums") || e.target.closest(".btn-delete-artist")) return;
                toggleArtistAlbums(idx);
            });
        });

        // Bind Toggle Albums button
        listEl.querySelectorAll(".btn-toggle-artist-albums").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const idx = parseInt(btn.dataset.index);
                toggleArtistAlbums(idx);
            });
        });

        // Bind Add Artist to Playlist
        listEl.querySelectorAll(".btn-add-artist-pl").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const artName = btn.dataset.artist;
                addArtistToCurrentPlaylist(artName);
            });
        });

        // Bind Delete Artist button
        listEl.querySelectorAll(".btn-delete-artist").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const artName = btn.dataset.artist;
                openDeleteModal("artist", artName, { artist: artName });
            });
        });

    } catch (err) {
        listEl.innerHTML = `<div class="p-4 text-center text-danger">Error loading artists: ${escapeHtml(err.message)}</div>`;
    }
}

// Toggle artist albums expansion
async function toggleArtistAlbums(artIdx) {
    const art = currentLibraryArtists[artIdx];
    const artistItem = document.querySelector(`.lib-artist-item[data-index="${artIdx}"]`);
    const drawer = document.getElementById(`lib-artist-albums-${artIdx}`);
    const content = document.getElementById(`lib-artist-albums-content-${artIdx}`);

    if (!drawer || !content || !artistItem) return;

    const isExpanded = artistItem.classList.contains("expanded");
    if (isExpanded) {
        artistItem.classList.remove("expanded");
        drawer.style.display = "none";
    } else {
        artistItem.classList.add("expanded");
        drawer.style.display = "block";

        if (!art.albums) {
            content.innerHTML = `
                <div class="p-3 text-center text-muted" style="font-size: 12px;">
                    <i class="fa-solid fa-spinner fa-spin"></i> Loading albums for "${escapeHtml(art.name)}"...
                </div>
            `;
            try {
                const res = await fetch(`/api/library/artist-albums?artist=${encodeURIComponent(art.name)}`);
                const data = await res.json();
                art.albums = (data.albums || []).map(alb => ({
                    ...alb,
                    tracks: null
                }));
                renderArtistAlbums(artIdx);
            } catch (e) {
                content.innerHTML = `<div class="p-2 text-danger text-xs">Error loading albums: ${escapeHtml(e.message)}</div>`;
            }
        } else {
            renderArtistAlbums(artIdx);
        }
    }
}

// Render albums list inside artist drawer
function renderArtistAlbums(artIdx) {
    const art = currentLibraryArtists[artIdx];
    const content = document.getElementById(`lib-artist-albums-content-${artIdx}`);
    if (!content || !art.albums) return;

    if (art.albums.length === 0) {
        content.innerHTML = `<div class="p-3 text-center text-muted text-xs">No albums cataloged for this artist.</div>`;
        return;
    }

    content.innerHTML = `
        <div class="lib-albums-header">
            <span><strong>${escapeHtml(art.name)}</strong> Albums (${art.albums.length})</span>
        </div>
        <div class="lib-albums-list">
            ${art.albums.map((alb, albIdx) => `
                <div class="lib-album-item" data-art-idx="${artIdx}" data-alb-idx="${albIdx}" data-album-id="${alb.id}">
                    <div class="lib-album-row" data-art-idx="${artIdx}" data-alb-idx="${albIdx}">
                        <div class="lib-album-left">
                            <div class="lib-album-art">
                                ${alb.has_art ? `<img src="${alb.art_url}" alt="${escapeAttr(alb.name)}" loading="lazy">` : `<i class="fa-solid fa-record-vinyl"></i>`}
                            </div>
                            <div class="lib-album-info">
                                <span class="lib-album-title" title="${escapeAttr(alb.name)}">${escapeHtml(alb.name)}</span>
                                <div class="lib-album-meta">
                                    <span class="meta-pill year">${alb.year || "Album"}</span>
                                    <span class="meta-pill tracks"><i class="fa-solid fa-music"></i> ${alb.track_count} tracks</span>
                                    ${alb.duration ? `<span class="meta-pill"><i class="fa-solid fa-clock"></i> ${alb.duration}</span>` : ''}
                                </div>
                            </div>
                        </div>
                        <div class="lib-album-right">
                            <button type="button" class="btn btn-secondary btn-sm btn-delete-album" data-album-id="${alb.id}" data-album-name="${escapeAttr(alb.name)}" title="Delete album &amp; songs from Vault">
                                <i class="fa-solid fa-trash-can"></i>
                            </button>
                            <button type="button" class="btn btn-secondary btn-sm btn-add-album-pl" data-album-id="${alb.id}" data-album-name="${escapeAttr(alb.name)}" title="Add all tracks from this album to playlist">
                                <i class="fa-solid fa-plus"></i> Playlist
                            </button>
                            <button type="button" class="btn btn-secondary btn-sm btn-toggle-album-songs" data-art-idx="${artIdx}" data-alb-idx="${albIdx}">
                                <i class="fa-solid fa-list-ul"></i>
                                <span>Songs</span>
                                <i class="fa-solid fa-chevron-down toggle-chevron"></i>
                            </button>
                        </div>
                    </div>

                    <!-- Songs Drawer -->
                    <div class="lib-songs-drawer" id="lib-songs-drawer-${artIdx}-${albIdx}" style="display: none;">
                        <div class="lib-songs-content" id="lib-songs-content-${artIdx}-${albIdx}">
                            <!-- Songs rendered dynamically -->
                        </div>
                    </div>
                </div>
            `).join("")}
        </div>
    `;

    // Bind Album Row Clicks to toggle songs
    content.querySelectorAll(".lib-album-row").forEach(row => {
        row.addEventListener("click", (e) => {
            if (e.target.closest(".btn-add-album-pl") || e.target.closest(".btn-toggle-album-songs") || e.target.closest(".btn-delete-album")) return;
            const aIdx = parseInt(row.dataset.artIdx);
            const alIdx = parseInt(row.dataset.albIdx);
            toggleAlbumSongs(aIdx, alIdx);
        });
    });

    // Bind Toggle Songs button
    content.querySelectorAll(".btn-toggle-album-songs").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const aIdx = parseInt(btn.dataset.artIdx);
            const alIdx = parseInt(btn.dataset.albIdx);
            toggleAlbumSongs(aIdx, alIdx);
        });
    });

    // Bind Add Album to Playlist
    content.querySelectorAll(".btn-add-album-pl").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const albId = parseInt(btn.dataset.albumId);
            const albName = btn.dataset.albumName;
            addAlbumToCurrentPlaylist(albId, albName);
        });
    });

    // Bind Delete Album button
    content.querySelectorAll(".btn-delete-album").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const albId = parseInt(btn.dataset.albumId);
            const albName = btn.dataset.albumName;
            openDeleteModal("album", albId, { albumName: albName });
        });
    });
}

// Toggle album songs expansion
async function toggleAlbumSongs(artIdx, albIdx) {
    const art = currentLibraryArtists[artIdx];
    const alb = art.albums[albIdx];
    const albumItem = document.querySelector(`.lib-album-item[data-art-idx="${artIdx}"][data-alb-idx="${albIdx}"]`);
    const drawer = document.getElementById(`lib-songs-drawer-${artIdx}-${albIdx}`);
    const content = document.getElementById(`lib-songs-content-${artIdx}-${albIdx}`);

    if (!drawer || !content || !albumItem) return;

    const isExpanded = albumItem.classList.contains("expanded");
    if (isExpanded) {
        albumItem.classList.remove("expanded");
        drawer.style.display = "none";
    } else {
        albumItem.classList.add("expanded");
        drawer.style.display = "block";

        if (!alb.tracks) {
            content.innerHTML = `
                <div class="p-2 text-center text-muted" style="font-size: 12px;">
                    <i class="fa-solid fa-spinner fa-spin"></i> Loading songs for "${escapeHtml(alb.name)}"...
                </div>
            `;
            try {
                const res = await fetch(`/api/library/album-tracks?album_id=${alb.id}`);
                const data = await res.json();
                alb.tracks = data.tracks || [];
                renderAlbumSongs(artIdx, albIdx);
            } catch (e) {
                content.innerHTML = `<div class="p-2 text-danger text-xs">Error loading songs: ${escapeHtml(e.message)}</div>`;
            }
        } else {
            renderAlbumSongs(artIdx, albIdx);
        }
    }
}

// Render songs list inside album drawer
function renderAlbumSongs(artIdx, albIdx) {
    const art = currentLibraryArtists[artIdx];
    const alb = art.albums[albIdx];
    const content = document.getElementById(`lib-songs-content-${artIdx}-${albIdx}`);
    if (!content || !alb.tracks) return;

    if (alb.tracks.length === 0) {
        content.innerHTML = `<div class="p-2 text-center text-muted text-xs">No tracks cataloged for this album.</div>`;
        return;
    }

    content.innerHTML = `
        <div class="lib-songs-list">
            ${alb.tracks.map((song, sIdx) => `
                <div class="lib-song-row" data-song-id="${song.id}">
                    <div class="lib-song-left">
                        <button type="button" class="btn-track-play btn-lib-song-play"
                            data-art-idx="${artIdx}"
                            data-alb-idx="${albIdx}"
                            data-song-idx="${sIdx}"
                            data-track-id="${song.id}"
                            title="Play 30s Preview">
                            <i class="fa-solid fa-play"></i>
                        </button>
                        <span class="lib-song-number">${song.number || (sIdx + 1)}</span>
                        <span class="lib-song-title" title="${escapeAttr(song.title)}">${escapeHtml(song.title)}</span>
                    </div>
                    <div class="lib-song-right">
                        <span class="lib-song-duration">${escapeHtml(song.duration || '')}</span>
                        <a href="/api/audio/download/${song.id}" download class="btn btn-secondary btn-sm btn-download-song" title="Download &quot;${escapeAttr(song.title)}&quot; directly" onclick="event.stopPropagation();">
                            <i class="fa-solid fa-download"></i>
                        </a>
                        <button type="button" class="btn btn-secondary btn-sm btn-add-song-pl"
                            data-art-idx="${artIdx}"
                            data-alb-idx="${albIdx}"
                            data-song-idx="${sIdx}"
                            title="Add to playlist">
                            <i class="fa-solid fa-plus"></i> Playlist
                        </button>
                        <button type="button" class="btn btn-secondary btn-sm btn-delete-song"
                            data-art-idx="${artIdx}"
                            data-alb-idx="${albIdx}"
                            data-song-idx="${sIdx}"
                            title="Delete song from Vault">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                </div>
            `).join("")}
        </div>
    `;

    // Bind Song Audio Preview buttons
    content.querySelectorAll(".btn-lib-song-play").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const sIdx = parseInt(btn.dataset.songIdx);
            const song = alb.tracks[sIdx];
            if (song && audioManager) {
                audioManager.playTrack({
                    id: song.id,
                    title: song.title,
                    artist: song.artist || art.name,
                    album: alb.name,
                    artwork_url: alb.art_url,
                    type: "library"
                }, alb.tracks, sIdx, btn);
            }
        });
    });

    // Bind Add Song to Playlist
    content.querySelectorAll(".btn-add-song-pl").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const sIdx = parseInt(btn.dataset.songIdx);
            const song = alb.tracks[sIdx];
            if (song) {
                addTrackToCurrentPlaylist(song);
            }
        });
    });

    // Bind Delete Song button
    content.querySelectorAll(".btn-delete-song").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const sIdx = parseInt(btn.dataset.songIdx);
            const song = alb.tracks[sIdx];
            if (song) {
                openDeleteModal("song", song.id, {
                    songTitle: song.title,
                    artist: song.artist || art.name,
                    album: alb.name
                });
            }
        });
    });

    // Update play state if currently playing
    if (audioManager) audioManager.updatePlayStateUI();
}

// ----------------------------------------------------------------------------
// CLASSIC FLAT TRACK TABLE VIEW
// ----------------------------------------------------------------------------
async function loadLibraryBrowser() {
    const tbody = document.getElementById("library-tbody");
    const countEl = document.getElementById("library-total-count");
    const pageInfo = document.getElementById("library-page-info");
    const pageBadge = document.getElementById("library-current-page-badge");
    const prevBtn = document.getElementById("library-prev-page");
    const nextBtn = document.getElementById("library-next-page");

    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted" style="padding: 24px;">
        <i class="fa-solid fa-spinner fa-spin" style="font-size: 1.5rem; margin-bottom: 8px; display: block;"></i>
        Loading library tracks...
    </td></tr>`;

    const search = document.getElementById("library-search")?.value.trim() || "";
    const genre = document.getElementById("library-filter-genre")?.value || "";
    const decade = document.getElementById("library-filter-decade")?.value || "";
    const sortBy = document.getElementById("library-sort-by")?.value || "artist";

    const params = new URLSearchParams({
        sort_by: sortBy,
        sort_order: librarySortOrder,
        page: libraryCurrentPage,
        limit: libraryPageSize
    });
    if (search) params.append("query", search);
    if (genre) params.append("genre", genre);
    if (decade) params.append("decade", decade);

    try {
        const res = await fetch(`/api/library/tracks?${params.toString()}`);
        const data = await res.json();

        libraryTotalTracks = data.total || 0;
        const tracks = data.tracks || [];
        const totalPages = Math.max(1, Math.ceil(libraryTotalTracks / libraryPageSize));

        if (countEl) countEl.textContent = `${libraryTotalTracks.toLocaleString()} tracks found`;
        if (pageBadge) pageBadge.textContent = `${libraryCurrentPage} / ${totalPages}`;
        if (pageInfo) {
            const start = libraryTotalTracks === 0 ? 0 : (libraryCurrentPage - 1) * libraryPageSize + 1;
            const end = Math.min(libraryCurrentPage * libraryPageSize, libraryTotalTracks);
            pageInfo.textContent = `Showing ${start}-${end} of ${libraryTotalTracks.toLocaleString()} tracks`;
        }

        if (prevBtn) prevBtn.disabled = libraryCurrentPage <= 1;
        if (nextBtn) nextBtn.disabled = libraryCurrentPage >= totalPages;

        if (tracks.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted" style="padding: 30px;">
                <i class="fa-solid fa-record-vinyl fa-2x mb-2" style="opacity: 0.4;"></i><br>
                No tracks match your search criteria.
            </td></tr>`;
            return;
        }

        tbody.innerHTML = tracks.map((t, idx) => `
            <tr data-track-id="${t.id}">
                <td style="text-align: center;">
                    <button type="button" class="btn-track-play btn-lib-play" data-index="${idx}" data-track-id="${t.id}" title="Play Preview">
                        <i class="fa-solid fa-play"></i>
                    </button>
                </td>
                <td><strong>${escapeHtml(t.title)}</strong></td>
                <td>${escapeHtml(t.artist)}</td>
                <td class="text-muted">${escapeHtml(t.album || "-")}</td>
                <td><span class="badge" style="font-size: 11px;">${escapeHtml(t.genre || "Music")}</span></td>
                <td style="text-align: center; font-size: 12px; color: #94a3b8;">${t.year || "-"}</td>
                <td style="text-align: center; font-family: var(--font-mono); font-size: 12px;">${escapeHtml(t.length_str || t.duration || "0:00")}</td>
                <td class="text-right">
                    <div style="display: inline-flex; gap: 6px; align-items: center; justify-content: flex-end;">
                        <a href="/api/audio/download/${t.id}" download class="btn btn-secondary btn-sm btn-download-song" title="Download &quot;${escapeAttr(t.title)}&quot; directly" onclick="event.stopPropagation();">
                            <i class="fa-solid fa-download"></i>
                        </a>
                        <button type="button" class="btn btn-secondary btn-sm btn-add-to-pl" data-index="${idx}" title="Add to current playlist">
                            <i class="fa-solid fa-plus"></i> Playlist
                        </button>
                        <button type="button" class="btn btn-secondary btn-sm btn-delete-track" data-index="${idx}" title="Delete song from Vault">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `).join("");

        // Wire up play buttons
        tbody.querySelectorAll(".btn-lib-play").forEach(btn => {
            btn.addEventListener("click", () => {
                const idx = parseInt(btn.dataset.index);
                const track = tracks[idx];
                if (track && audioManager) {
                    audioManager.playTrack(track, tracks, idx, btn);
                }
            });
        });

        // Wire up "Add to Playlist" buttons
        tbody.querySelectorAll(".btn-add-to-pl").forEach(btn => {
            btn.addEventListener("click", () => {
                const idx = parseInt(btn.dataset.index);
                const track = tracks[idx];
                if (track) {
                    addTrackToCurrentPlaylist(track);
                }
            });
        });

        // Wire up delete track buttons
        tbody.querySelectorAll(".btn-delete-track").forEach(btn => {
            btn.addEventListener("click", () => {
                const idx = parseInt(btn.dataset.index);
                const track = tracks[idx];
                if (track) {
                    openDeleteModal("song", track.id, {
                        songTitle: track.title,
                        artist: track.artist,
                        album: track.album
                    });
                }
            });
        });

        // Update button states if already playing a track in this list
        if (audioManager) audioManager.updatePlayStateUI();

    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">Error loading library tracks: ${escapeHtml(e.message)}</td></tr>`;
    }
}

async function addAlbumToCurrentPlaylist(albumId, albumName) {
    try {
        const res = await fetch(`/api/library/album-tracks?album_id=${albumId}`);
        const data = await res.json();
        const tracks = data.tracks || [];
        if (tracks.length === 0) {
            showToast("No tracks found in this album", "warning");
            return;
        }
        if (typeof currentPlaylistTracks === "undefined" || !currentPlaylistTracks) {
            currentPlaylistTracks = [];
        }
        tracks.forEach(t => {
            if (!t.length_str && t.duration) t.length_str = t.duration;
            if (!t.length_str && t.length) {
                t.length_str = `${Math.floor(t.length / 60)}:${(t.length % 60).toString().padStart(2, "0")}`;
            }
        });
        currentPlaylistTracks.push(...tracks);
        renderPlaylistPreview(currentPlaylistTracks);
        showToast(`Added ${tracks.length} tracks from "${albumName}" to playlist!`, "success");
    } catch (e) {
        showToast("Error adding album to playlist", "error");
    }
}

async function addArtistToCurrentPlaylist(artistName) {
    try {
        const res = await fetch(`/api/library/tracks?query=${encodeURIComponent(artistName)}&limit=100`);
        const data = await res.json();
        const tracks = data.tracks || [];
        if (tracks.length === 0) {
            showToast(`No tracks found for "${artistName}"`, "warning");
            return;
        }
        if (typeof currentPlaylistTracks === "undefined" || !currentPlaylistTracks) {
            currentPlaylistTracks = [];
        }
        tracks.forEach(t => {
            if (!t.length_str && t.duration) t.length_str = t.duration;
            if (!t.length_str && t.length) {
                t.length_str = `${Math.floor(t.length / 60)}:${(t.length % 60).toString().padStart(2, "0")}`;
            }
        });
        currentPlaylistTracks.push(...tracks);
        renderPlaylistPreview(currentPlaylistTracks);
        showToast(`Added ${tracks.length} tracks by "${artistName}" to playlist!`, "success");
    } catch (e) {
        showToast("Error adding artist to playlist", "error");
    }
}

function addTrackToCurrentPlaylist(track) {
    if (typeof currentPlaylistTracks === "undefined" || !currentPlaylistTracks) {
        currentPlaylistTracks = [];
    }
    if (!track.length_str && track.duration) {
        track.length_str = track.duration;
    }
    if (!track.length_str && track.length) {
        track.length_str = `${Math.floor(track.length / 60)}:${(track.length % 60).toString().padStart(2, "0")}`;
    }
    currentPlaylistTracks.push(track);
    renderPlaylistPreview(currentPlaylistTracks);
    showToast(`Added "${track.title}" to playlist!`, "success");
}

async function populateLibraryGenres() {
    const genreSelect = document.getElementById("library-filter-genre");
    if (!genreSelect) return;
    try {
        const res = await fetch("/api/library/stats");
        const data = await res.json();
        const genres = data.genres || [];
        genreSelect.innerHTML = '<option value="">All Genres</option>' +
            genres.map(g => `<option value="${escapeAttr(g.name)}">${escapeHtml(g.name)} (${g.count})</option>`).join("");
    } catch (e) {
        console.error("Error populating library genres:", e);
    }
}

// THEME SELECTOR CONTROLLER (v1.5.1)
// ============================================================================
function initThemeSelector() {
    const themeSelect = document.getElementById("theme-select");
    const savedTheme = localStorage.getItem("music_manager_theme") || "vintage_hifi";

    document.documentElement.dataset.theme = savedTheme;
    if (themeSelect) {
        themeSelect.value = savedTheme;
        themeSelect.addEventListener("change", (e) => {
            const selected = e.target.value;
            document.documentElement.dataset.theme = selected;
            localStorage.setItem("music_manager_theme", selected);
            const themeName = themeSelect.options[themeSelect.selectedIndex].text.trim();
            showToast(`Applied Theme: ${themeName}`, "info");
        });
    }
}


// ============================================================================
// ARTIST DISCOGRAPHY & ALBUM CHECKLIST UI (v1.5.3)
// ============================================================================
let currentChecklistAlbums = [];
let cachedArtistChoices = null;

function renderArtistChoices(artists, query, autoImport, autoComplete) {
    cachedArtistChoices = { artists, query, autoImport, autoComplete };
    const sec = document.getElementById("artist-discography-section");
    if (!sec) return;

    sec.innerHTML = `
        <div class="card glass artist-choice-card">
            <div class="card-header flex-between">
                <div>
                    <h3><i class="fa-solid fa-users" style="color: var(--primary);"></i> Multiple Artists Matching "<strong>${escapeHtml(query)}</strong>"</h3>
                    <p class="subtitle">Select an artist to view and download their complete albums:</p>
                </div>
                <button type="button" class="btn-icon" id="btn-close-artist-choices" title="Close"><i class="fa-solid fa-xmark"></i></button>
            </div>

            <div class="artist-selection-list mt-3">
                ${artists.map(a => `
                    <div class="artist-choice-item" data-artist-id="${a.id}" data-artist-name="${escapeAttr(a.name)}">
                        <div class="artist-choice-left">
                            <div class="artist-choice-avatar">
                                <i class="fa-solid fa-users"></i>
                            </div>
                            <div class="artist-choice-info">
                                <div class="artist-choice-title-row">
                                    <h4 class="artist-name">${escapeHtml(a.name)}</h4>
                                    <span class="badge" style="font-size: 11px;">${escapeHtml(a.genre || "Music")}</span>
                                </div>
                            </div>
                        </div>
                        <div class="artist-choice-action">
                            <button type="button" class="btn btn-secondary btn-sm disc-btn-view-albums">
                                View Albums <i class="fa-solid fa-chevron-right" style="font-size: 11px; margin-left: 4px;"></i>
                            </button>
                        </div>
                    </div>
                `).join("")}
            </div>

            <div class="artist-choice-footer mt-3 flex-between">
                <span class="text-muted text-xs">Not looking for an artist discography?</span>
                <button type="button" class="btn-link text-xs" id="btn-fallback-single-dl">
                    <i class="fa-solid fa-arrow-down"></i> Download "${escapeHtml(query)}" as a single song instead
                </button>
            </div>
        </div>
    `;

    sec.style.display = "block";
    sec.scrollIntoView({ behavior: "smooth", block: "start" });

    // Close button
    document.getElementById("btn-close-artist-choices")?.addEventListener("click", () => {
        sec.style.display = "none";
    });

    // Fallback single download
    document.getElementById("btn-fallback-single-dl")?.addEventListener("click", () => {
        executeDirectDownload(query, autoImport, autoComplete);
    });

    // Selecting an artist
    sec.querySelectorAll(".artist-choice-item").forEach(item => {
        item.addEventListener("click", async () => {
            const artistId = item.dataset.artistId;
            const artistName = item.dataset.artistName;
            item.innerHTML = `<div class="text-center w-100 py-2"><i class="fa-solid fa-spinner fa-spin"></i> Loading albums for ${escapeHtml(artistName)}...</div>`;
            try {
                const res = await fetch(`/api/download/artist-albums?artist_id=${artistId}&artist_name=${encodeURIComponent(artistName)}`);
                const data = await res.json();
                renderAlbumChecklist(data.artist, data.albums || [], query, autoImport, autoComplete, true);
            } catch (e) {
                showToast("Error loading albums", "error");
            }
        });
    });
}

function renderAlbumChecklist(artist, albums, query, autoImport, autoComplete, hasBack = false) {
    const sec = document.getElementById("artist-discography-section");
    if (!sec) return;

    currentChecklistAlbums = (albums || []).map(a => ({
        ...a,
        selected: !a.is_complete,
        tracks: null // loaded on-demand
    }));
    const totalTracks = currentChecklistAlbums.reduce((acc, a) => acc + (a.track_count || 0), 0);

    const libStats = artist.library_stats || { total_tracks: 0, complete_albums: 0 };
    const libBadgeHtml = libStats.total_tracks > 0 
        ? `<span class="meta-pill library-stats" title="${libStats.total_tracks} songs in your Beets library across ${libStats.complete_albums} complete albums"><i class="fa-solid fa-book-bookmark"></i> ${libStats.total_tracks} songs in library &bull; ${libStats.complete_albums} complete album${libStats.complete_albums === 1 ? '' : 's'}</span>`
        : `<span class="meta-pill library-stats" style="color: var(--text-muted); background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.1);"><i class="fa-solid fa-book-bookmark"></i> 0 songs in library</span>`;

    sec.innerHTML = `
        <div class="card glass album-checklist-card">
            <div class="card-header flex-between">
                <div class="disc-artist-header">
                    ${hasBack ? `
                        <button type="button" class="btn btn-secondary btn-sm disc-btn-back" id="btn-back-to-artists" title="Back to matching artists">
                            <i class="fa-solid fa-arrow-left"></i> Back to Artists
                        </button>
                    ` : ''}
                    <div class="disc-artist-avatar"><i class="fa-solid fa-compact-disc"></i></div>
                    <div>
                        <h3><strong>${escapeHtml(artist.name)}</strong> — Complete Discography</h3>
                        <p class="subtitle">
                            ${albums.length} albums found (~${totalTracks} tracks) &bull; 
                            <span class="badge" style="font-size: 11px;">${escapeHtml(artist.genre || "Rock")}</span> &bull; 
                            ${libBadgeHtml}
                        </p>
                    </div>
                </div>
                <div class="disc-header-actions">
                    <button type="button" class="btn btn-secondary btn-sm" id="btn-select-all-albums"><i class="fa-solid fa-check-double"></i> Select All</button>
                    <button type="button" class="btn btn-secondary btn-sm" id="btn-deselect-all-albums"><i class="fa-solid fa-square"></i> Deselect All</button>
                    <button type="button" class="btn-icon" id="btn-close-album-checklist" title="Close"><i class="fa-solid fa-xmark"></i></button>
                </div>
            </div>

            <!-- Albums Checklist List -->
            <div class="albums-checklist-list mt-3">
                ${albums.map((a, i) => {
                    const isChecked = !a.is_complete;
                    let albumPillHtml = '';
                    if (a.is_complete) {
                        albumPillHtml = `<span class="meta-pill pill-complete" title="All tracks owned in library"><i class="fa-solid fa-circle-check"></i> Complete (${a.in_library_count || a.track_count}/${a.track_count})</span>`;
                    } else if (a.in_library_count > 0) {
                        albumPillHtml = `<span class="meta-pill pill-partial" title="Partially owned in library"><i class="fa-solid fa-circle-half-stroke"></i> In Library (${a.in_library_count}/${a.track_count})</span>`;
                    }

                    return `
                    <div class="album-accordion-item ${isChecked ? 'active' : ''}" data-index="${i}" data-album-id="${a.id}">
                        <div class="album-check-row ${isChecked ? 'active' : ''}" data-index="${i}">
                            <div class="album-check-left">
                                <label class="custom-checkbox-wrap" title="${a.is_complete ? 'Album is already complete in library' : 'Select entire album'}">
                                    <input type="checkbox" class="album-checkbox" data-index="${i}" ${isChecked ? 'checked' : ''}>
                                    <span class="custom-checkbox"></span>
                                </label>
                                <div class="album-art-wrap">
                                    ${a.artwork_url ? `<img src="${escapeAttr(a.artwork_url)}" alt="${escapeAttr(a.name)}" loading="lazy">` : `<i class="fa-solid fa-record-vinyl"></i>`}
                                </div>
                                <div class="album-title-info">
                                    <span class="album-name" title="${escapeAttr(a.name)}">${escapeHtml(a.name)}</span>
                                    <div class="album-meta-pills">
                                        <span class="meta-pill year">${escapeHtml(a.year || "Album")}</span>
                                        <span class="meta-pill tracks"><i class="fa-solid fa-music"></i> <span class="album-track-badge" id="album-track-badge-${i}">${a.track_count || 0} tracks</span></span>
                                        ${albumPillHtml}
                                    </div>
                                </div>
                            </div>
                            <div class="album-check-right">
                                <button type="button" class="btn btn-secondary btn-sm btn-toggle-album-tracks" data-index="${i}" data-album-id="${a.id}" title="View & preview songs in this album">
                                    <i class="fa-solid fa-list-ul"></i>
                                    <span class="btn-toggle-text">Songs</span>
                                    <i class="fa-solid fa-chevron-down toggle-chevron"></i>
                                </button>
                            </div>
                        </div>

                        <!-- Dropdown Tracks Drawer -->
                        <div class="album-tracks-dropdown" id="album-tracks-${i}" style="display: none;">
                            <div class="album-tracks-content" id="album-tracks-content-${i}">
                                <!-- Tracks will be rendered dynamically here -->
                            </div>
                        </div>
                    </div>
                `;}).join("")}
            </div>

            <!-- Action Bar -->
            <div class="disc-action-bar mt-3 flex-between">
                <div class="disc-action-summary">
                    <i class="fa-solid fa-circle-check" style="color: var(--primary);"></i>
                    <span id="disc-selected-summary">All ${albums.length} Albums Selected (~${totalTracks} tracks)</span>
                </div>
                <div class="disc-action-buttons">
                    ${hasBack ? `
                        <button type="button" class="btn btn-secondary btn-sm mr-2" id="btn-bottom-back-to-artists">
                            <i class="fa-solid fa-arrow-left"></i> Back to Artists
                        </button>
                    ` : ''}
                    <button type="button" class="btn btn-primary" id="btn-download-albums-now">
                        <i class="fa-solid fa-cloud-arrow-down"></i> Download Selected Music (<span id="disc-btn-album-count">${albums.length}</span> albums)
                    </button>
                </div>
            </div>
        </div>
    `;

    sec.style.display = "block";
    sec.scrollIntoView({ behavior: "smooth", block: "start" });

    // Back to artists navigation
    const goBackToArtists = () => {
        if (cachedArtistChoices) {
            renderArtistChoices(
                cachedArtistChoices.artists,
                cachedArtistChoices.query,
                cachedArtistChoices.autoImport,
                cachedArtistChoices.autoComplete
            );
        }
    };
    document.getElementById("btn-back-to-artists")?.addEventListener("click", goBackToArtists);
    document.getElementById("btn-bottom-back-to-artists")?.addEventListener("click", goBackToArtists);

    // Close button
    document.getElementById("btn-close-album-checklist")?.addEventListener("click", () => {
        sec.style.display = "none";
    });

    const checkboxes = sec.querySelectorAll(".album-checkbox");
    const accordionItems = sec.querySelectorAll(".album-accordion-item");

    // Helper: calculate selected summary
    function updateSelectionStats() {
        let selectedAlbumsCount = 0;
        let totalSelectedSongs = 0;

        currentChecklistAlbums.forEach((alb, idx) => {
            const albumEl = accordionItems[idx];
            const albumCb = checkboxes[idx];

            if (alb.tracks && alb.tracks.length > 0) {
                const checkedTracks = alb.tracks.filter(t => t.selected).length;
                totalSelectedSongs += checkedTracks;

                if (checkedTracks === alb.tracks.length) {
                    selectedAlbumsCount++;
                    albumCb.checked = true;
                    albumCb.indeterminate = false;
                    albumEl.classList.add("active");
                } else if (checkedTracks === 0) {
                    albumCb.checked = false;
                    albumCb.indeterminate = false;
                    albumEl.classList.remove("active");
                } else {
                    selectedAlbumsCount++;
                    albumCb.checked = true;
                    albumCb.indeterminate = true;
                    albumEl.classList.add("active");
                }

                const badge = document.getElementById(`album-track-badge-${idx}`);
                if (badge) badge.textContent = `${checkedTracks}/${alb.tracks.length} songs`;
            } else {
                if (albumCb.checked) {
                    selectedAlbumsCount++;
                    const missingInAlbum = Math.max(0, (alb.track_count || 0) - (alb.in_library_count || 0));
                    totalSelectedSongs += (missingInAlbum || alb.track_count || 0);
                    albumEl.classList.add("active");
                } else {
                    albumEl.classList.remove("active");
                }
            }
        });

        const summaryEl = document.getElementById("disc-selected-summary");
        const btnCountEl = document.getElementById("disc-btn-album-count");
        const dlBtn = document.getElementById("btn-download-albums-now");

        if (summaryEl) {
            if (selectedAlbumsCount === albums.length) {
                summaryEl.textContent = `All ${albums.length} Albums Selected (~${totalSelectedSongs} tracks to download)`;
            } else {
                summaryEl.textContent = `${selectedAlbumsCount} of ${albums.length} Albums Selected (~${totalSelectedSongs} tracks to download)`;
            }
        }
        if (btnCountEl) btnCountEl.textContent = selectedAlbumsCount;
        if (dlBtn) dlBtn.disabled = selectedAlbumsCount === 0 && totalSelectedSongs === 0;
    }

    // Initialize selection stats immediately
    updateSelectionStats();

    // Helper: render tracks for an album
    function renderTracksForAlbum(albIdx) {
        const alb = currentChecklistAlbums[albIdx];
        const contentEl = document.getElementById(`album-tracks-content-${albIdx}`);
        if (!contentEl || !alb.tracks) return;

        contentEl.innerHTML = `
            <div class="album-tracks-header">
                <span><strong>${escapeHtml(alb.name)}</strong> Tracklist (${alb.tracks.length} songs)</span>
                <div class="album-tracks-header-actions">
                    <button type="button" class="btn-track-select-all" data-album-idx="${albIdx}">Select All</button>
                    &bull;
                    <button type="button" class="btn-track-deselect-all" data-album-idx="${albIdx}">Deselect All</button>
                </div>
            </div>
            <div class="album-tracks-list">
                ${alb.tracks.map((t, tIdx) => `
                    <div class="album-track-item ${t.selected ? 'active' : ''} ${t.in_library ? 'in-library' : ''}" data-album-idx="${albIdx}" data-track-idx="${tIdx}">
                        <div class="album-track-left">
                            <label class="custom-checkbox-wrap" title="${t.in_library ? 'Already in your library' : 'Include song in download'}">
                                <input type="checkbox" class="track-checkbox" data-album-idx="${albIdx}" data-track-idx="${tIdx}" ${t.selected ? 'checked' : ''}>
                                <span class="custom-checkbox"></span>
                            </label>
                            <span class="track-number">${t.number || (tIdx + 1)}</span>
                            <span class="track-title" title="${escapeAttr(t.name)}">${escapeHtml(t.name)}</span>
                            ${t.in_library ? `<span class="badge-song-in-library" title="Already owned in library"><i class="fa-solid fa-check"></i> In Library</span>` : ''}
                        </div>
                        <div class="album-track-right">
                            <span class="track-duration">${escapeHtml(t.duration || '')}</span>
                            <button type="button" class="btn-song-preview"
                                data-artist="${escapeAttr(artist.name)}"
                                data-title="${escapeAttr(t.name)}"
                                data-preview="${escapeAttr(t.preview_url || '')}"
                                data-artwork="${escapeAttr(alb.artwork_url || '')}"
                                title="Preview Song">
                                <i class="fa-solid fa-play"></i>
                            </button>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;

        // Bind song preview buttons
        contentEl.querySelectorAll(".btn-song-preview").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const art = btn.dataset.artist;
                const tit = btn.dataset.title;
                const prevUrl = btn.dataset.preview;
                const artUrl = btn.dataset.artwork;
                if (audioManager) {
                    if (prevUrl) {
                        audioManager.playTrack({
                            artist: art,
                            title: tit,
                            title_display: tit,
                            preview_url: prevUrl,
                            artwork_url: artUrl,
                            type: "preview"
                        }, null, null, btn);
                    } else {
                        audioManager.playQuery(art, tit, btn);
                    }
                }
            });
        });

        // Bind track checkboxes
        contentEl.querySelectorAll(".track-checkbox").forEach(cb => {
            cb.addEventListener("change", (e) => {
                e.stopPropagation();
                const tIdx = parseInt(cb.dataset.trackIdx);
                alb.tracks[tIdx].selected = cb.checked;
                const row = cb.closest(".album-track-item");
                if (row) {
                    if (cb.checked) row.classList.add("active");
                    else row.classList.remove("active");
                }
                updateSelectionStats();
            });
        });

        // Track item row click toggles track checkbox
        contentEl.querySelectorAll(".album-track-item").forEach(item => {
            item.addEventListener("click", (e) => {
                if (e.target.closest(".btn-song-preview") || e.target.closest(".custom-checkbox-wrap")) return;
                const cb = item.querySelector(".track-checkbox");
                if (cb) {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event("change"));
                }
            });
        });

        // Select All tracks in album
        contentEl.querySelector(".btn-track-select-all")?.addEventListener("click", (e) => {
            e.stopPropagation();
            alb.tracks.forEach(t => t.selected = true);
            renderTracksForAlbum(albIdx);
            updateSelectionStats();
        });

        // Deselect All tracks in album
        contentEl.querySelector(".btn-track-deselect-all")?.addEventListener("click", (e) => {
            e.stopPropagation();
            alb.tracks.forEach(t => t.selected = false);
            renderTracksForAlbum(albIdx);
            updateSelectionStats();
        });
    }

    // Toggle album tracks expansion
    async function toggleAlbumTracks(albIdx) {
        const item = accordionItems[albIdx];
        const alb = currentChecklistAlbums[albIdx];
        const dropdown = document.getElementById(`album-tracks-${albIdx}`);
        const contentEl = document.getElementById(`album-tracks-content-${albIdx}`);
        if (!dropdown || !contentEl) return;

        const isExpanded = item.classList.contains("expanded");
        if (isExpanded) {
            item.classList.remove("expanded");
            dropdown.style.display = "none";
        } else {
            item.classList.add("expanded");
            dropdown.style.display = "block";

            if (!alb.tracks) {
                contentEl.innerHTML = `<div class="tracks-loading py-3 text-center text-muted" style="font-size: 12px;"><i class="fa-solid fa-spinner fa-spin"></i> Loading tracklist for "${escapeHtml(alb.name)}"...</div>`;
                try {
                    const res = await fetch(`/api/download/album-tracks?album_id=${alb.id}&artist_name=${encodeURIComponent(artist.name)}`);
                    const data = await res.json();
                    const isParentChecked = checkboxes[albIdx].checked;
                    alb.tracks = (data.tracks || []).map(t => ({
                        ...t,
                        selected: t.in_library ? false : isParentChecked
                    }));
                    renderTracksForAlbum(albIdx);
                    updateSelectionStats();
                } catch (err) {
                    contentEl.innerHTML = `<div class="py-2 text-danger text-center text-xs">Failed to load songs: ${escapeHtml(err.message)}</div>`;
                }
            } else {
                renderTracksForAlbum(albIdx);
            }
        }
    }


    // Bind Toggle Buttons
    sec.querySelectorAll(".btn-toggle-album-tracks").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            toggleAlbumTracks(idx);
        });
    });

    // Bind Album Checkboxes
    checkboxes.forEach((cb, idx) => {
        cb.addEventListener("change", () => {
            const alb = currentChecklistAlbums[idx];
            const isChecked = cb.checked;
            cb.indeterminate = false;

            if (alb.tracks) {
                alb.tracks.forEach(t => t.selected = isChecked);
                renderTracksForAlbum(idx);
            }
            updateSelectionStats();
        });
    });

    // Album Row Click (expand/collapse when clicking row, except when clicking checkbox)
    sec.querySelectorAll(".album-check-row").forEach((row, idx) => {
        row.addEventListener("click", (e) => {
            if (e.target.closest(".custom-checkbox-wrap") || e.target.closest(".btn-toggle-album-tracks")) return;
            toggleAlbumTracks(idx);
        });
    });

    // Select All Albums
    document.getElementById("btn-select-all-albums")?.addEventListener("click", () => {
        checkboxes.forEach((cb, idx) => {
            cb.checked = true;
            cb.indeterminate = false;
            const alb = currentChecklistAlbums[idx];
            if (alb.tracks) {
                alb.tracks.forEach(t => t.selected = true);
                renderTracksForAlbum(idx);
            }
        });
        updateSelectionStats();
    });

    // Deselect All Albums
    document.getElementById("btn-deselect-all-albums")?.addEventListener("click", () => {
        checkboxes.forEach((cb, idx) => {
            cb.checked = false;
            cb.indeterminate = false;
            const alb = currentChecklistAlbums[idx];
            if (alb.tracks) {
                alb.tracks.forEach(t => t.selected = false);
                renderTracksForAlbum(idx);
            }
        });
        updateSelectionStats();
    });

    // Download Selected Albums Button
    document.getElementById("btn-download-albums-now")?.addEventListener("click", async () => {
        const selected = [];

        currentChecklistAlbums.forEach((alb, idx) => {
            const cb = checkboxes[idx];
            if (alb.tracks && alb.tracks.length > 0) {
                const selectedTrackNames = alb.tracks.filter(t => t.selected).map(t => t.name);
                if (selectedTrackNames.length > 0) {
                    selected.push({
                        ...alb,
                        selected_tracks: selectedTrackNames
                    });
                }
            } else if (cb.checked) {
                selected.push(alb);
            }
        });

        if (selected.length === 0) {
            showToast("No albums or songs selected to download", "error");
            return;
        }

        const btnDl = document.getElementById("btn-download-albums-now");
        btnDl.disabled = true;
        btnDl.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Queueing Download...`;

        try {
            const res = await fetch("/api/download/batch-albums", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    artist: artist.name,
                    albums: selected,
                    auto_import: autoImport,
                    auto_complete_album: autoComplete
                })
            });

            if (res.ok) {
                showToast(`Started download of selected music for ${artist.name}!`, "success");
                sec.style.display = "none";
                const qInput = document.getElementById("download-query");
                if (qInput) qInput.value = "";
                document.querySelector('[data-tab="terminal"]').click();
            } else {
                const err = await res.json();
                showToast(err.detail || "Error starting album batch download", "error");
                btnDl.disabled = false;
                btnDl.innerHTML = `<i class="fa-solid fa-cloud-arrow-down"></i> Download Selected Music`;
            }
        } catch (e) {
            showToast("Network error starting download", "error");
            btnDl.disabled = false;
        }
    });
}

// ============================================================================
// LIBRARY DELETION IMPACT & RIGHT-TO-LEFT SLIDE LOCKOUT
// ============================================================================
let currentDeleteImpact = null;
let excludedTrackIds = new Set();
let isSlideUnlocked = false;

function resetSlideLockout() {
    isSlideUnlocked = false;
    const track = document.getElementById("slide-lockout-track");
    const thumb = document.getElementById("slide-lockout-thumb");
    const text = document.getElementById("slide-lockout-text");
    const icon = document.getElementById("slide-lockout-icon");
    const btnConfirm = document.getElementById("btn-confirm-delete-unlocked");
    const btnFooter = document.getElementById("btn-confirm-delete-footer");

    if (track) {
        track.classList.remove("unlocked");
        track.style.display = "flex";
        track.style.opacity = "1";
        track.style.pointerEvents = "auto";
    }
    if (thumb) {
        thumb.style.transition = "";
        thumb.style.right = "4px";
    }
    if (text) {
        text.innerHTML = `<i class="fa-solid fa-angles-left"></i> Slide left to unlock deletion`;
    }
    if (icon) {
        icon.className = "fa-solid fa-lock";
    }
    if (btnConfirm) {
        btnConfirm.classList.remove("revealed");
        btnConfirm.style.display = "none";
        btnConfirm.disabled = false;
        btnConfirm.innerHTML = `<i class="fa-solid fa-trash-can"></i> Permanently Delete Selected Items`;
    }
    if (btnFooter) {
        btnFooter.style.display = "none";
        btnFooter.disabled = false;
        btnFooter.innerHTML = `<i class="fa-solid fa-trash-can"></i> Permanently Delete`;
    }
}

function renderDeleteImpactUI() {
    if (!currentDeleteImpact || !currentDeleteImpact.success) return;

    const imp = currentDeleteImpact;
    const titleEl = document.getElementById("delete-modal-target-title");
    const descEl = document.getElementById("delete-modal-target-desc");
    const albumsStatEl = document.getElementById("delete-stat-albums");
    const tracksStatEl = document.getElementById("delete-stat-tracks");
    const sizeStatEl = document.getElementById("delete-stat-size");
    const keptStatEl = document.getElementById("delete-stat-kept");
    const listEl = document.getElementById("delete-exclusion-list");
    const trackLock = document.getElementById("slide-lockout-track");
    const textLock = document.getElementById("slide-lockout-text");
    const confirmBtn = document.getElementById("btn-confirm-delete-unlocked");

    if (titleEl) {
        const typeLabel = imp.target_type.charAt(0).toUpperCase() + imp.target_type.slice(1);
        titleEl.textContent = `${typeLabel}: ${imp.target_name}`;
    }
    if (descEl) {
        descEl.textContent = `Review all items, folders, and disk space that will be permanently removed.`;
    }

    // Calculate active items vs kept items
    let activeTracksCount = 0;
    let activeBytes = 0;
    const activeAlbums = new Set();
    const keptCount = excludedTrackIds.size;

    (imp.albums || []).forEach(alb => {
        (alb.tracks || []).forEach(t => {
            if (!excludedTrackIds.has(t.id)) {
                activeTracksCount++;
                activeBytes += (t.size_bytes || 0);
                activeAlbums.add(alb.album_id);
            }
        });
    });

    let activeSizeStr = "0 B";
    if (activeBytes >= 1024 * 1024 * 1024) {
        activeSizeStr = `${(activeBytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    } else if (activeBytes >= 1024 * 1024) {
        activeSizeStr = `${(activeBytes / (1024 * 1024)).toFixed(1)} MB`;
    } else if (activeBytes > 0) {
        activeSizeStr = `${(activeBytes / 1024).toFixed(1)} KB`;
    }

    if (albumsStatEl) albumsStatEl.textContent = activeAlbums.size;
    if (tracksStatEl) tracksStatEl.textContent = activeTracksCount;
    if (sizeStatEl) sizeStatEl.textContent = activeSizeStr;
    if (keptStatEl) keptStatEl.textContent = keptCount;

    // Render tree
    if (listEl) {
        let html = "";
        (imp.albums || []).forEach((alb, aIdx) => {
            const allAlbTrackIds = (alb.tracks || []).map(t => t.id);
            const albAllExcluded = allAlbTrackIds.length > 0 && allAlbTrackIds.every(id => excludedTrackIds.has(id));

            html += `
                <div class="delete-album-block mb-3">
                    <div class="delete-exclusion-item ${albAllExcluded ? 'is-kept' : ''}" style="background: rgba(255, 255, 255, 0.06); font-weight: 600; margin-bottom: 6px; border-radius: 8px; padding: 10px 14px;">
                        <div class="delete-item-info">
                            <i class="fa-solid fa-compact-disc" style="color: #60a5fa; font-size: 15px;"></i>
                            <span class="item-title" title="${escapeAttr(alb.album_name)}">${escapeHtml(alb.album_name)}</span>
                            <span class="item-sub">(${alb.tracks.length} tracks &bull; ${escapeHtml(alb.size_str)})</span>
                        </div>
                        <button type="button" class="btn-toggle-keep btn-toggle-keep-album" data-album-idx="${aIdx}">
                            <i class="fa-solid ${albAllExcluded ? 'fa-rotate-left' : 'fa-shield-halved'}"></i>
                            ${albAllExcluded ? 'Include Album' : 'Keep Album'}
                        </button>
                    </div>
                    <div class="delete-tracks-sublist" style="padding-left: 14px; display: flex; flex-direction: column; gap: 4px;">
                        ${(alb.tracks || []).map(t => {
                            const isKept = excludedTrackIds.has(t.id);
                            return `
                                <div class="delete-exclusion-item ${isKept ? 'is-kept' : ''}" data-track-id="${t.id}" style="padding: 8px 12px;">
                                    <div class="delete-item-info">
                                        <i class="fa-solid fa-music text-muted" style="font-size: 11px;"></i>
                                        <span class="item-title" title="${escapeAttr(t.title)}">${escapeHtml(t.title)}</span>
                                        <span class="item-sub">${escapeHtml(t.format || 'MP3')} &bull; ${escapeHtml(t.duration || '')} &bull; ${escapeHtml(t.size_str || '')}</span>
                                    </div>
                                    <button type="button" class="btn-toggle-keep btn-toggle-keep-track" data-track-id="${t.id}">
                                        <i class="fa-solid ${isKept ? 'fa-rotate-left' : 'fa-shield-halved'}"></i>
                                        ${isKept ? 'Include' : 'Keep'}
                                    </button>
                                </div>
                            `;
                        }).join("")}
                    </div>
                </div>
            `;
        });

        listEl.innerHTML = html;

        // Bind Keep Album buttons
        listEl.querySelectorAll(".btn-toggle-keep-album").forEach(btn => {
            btn.addEventListener("click", () => {
                const aIdx = parseInt(btn.dataset.albumIdx);
                const alb = imp.albums[aIdx];
                if (!alb) return;
                const allAlbTrackIds = (alb.tracks || []).map(t => t.id);
                const albAllExcluded = allAlbTrackIds.every(id => excludedTrackIds.has(id));
                if (albAllExcluded) {
                    allAlbTrackIds.forEach(id => excludedTrackIds.delete(id));
                } else {
                    allAlbTrackIds.forEach(id => excludedTrackIds.add(id));
                }
                renderDeleteImpactUI();
                resetSlideLockout();
            });
        });

        // Bind Keep Track buttons
        listEl.querySelectorAll(".btn-toggle-keep-track").forEach(btn => {
            btn.addEventListener("click", () => {
                const tId = parseInt(btn.dataset.trackId);
                if (excludedTrackIds.has(tId)) {
                    excludedTrackIds.delete(tId);
                } else {
                    excludedTrackIds.add(tId);
                }
                renderDeleteImpactUI();
                resetSlideLockout();
            });
        });
    }

    // If all tracks are spared/kept, disable deletion lockout
    const btnFooter = document.getElementById("btn-confirm-delete-footer");
    if (activeTracksCount === 0) {
        if (trackLock) {
            trackLock.style.display = "flex";
            trackLock.style.opacity = "0.4";
            trackLock.style.pointerEvents = "none";
        }
        if (textLock) {
            textLock.innerHTML = `<i class="fa-solid fa-circle-check"></i> All items kept — nothing to delete`;
        }
        if (confirmBtn) {
            confirmBtn.classList.remove("revealed");
            confirmBtn.style.display = "none";
        }
        if (btnFooter) {
            btnFooter.style.display = "none";
        }
    } else {
        if (!isSlideUnlocked) {
            if (trackLock) {
                trackLock.style.display = "flex";
                trackLock.style.opacity = "1";
                trackLock.style.pointerEvents = "auto";
            }
            if (textLock) {
                textLock.innerHTML = `<i class="fa-solid fa-angles-left"></i> Slide left to unlock deletion`;
            }
            if (confirmBtn) {
                confirmBtn.classList.remove("revealed");
                confirmBtn.style.display = "none";
            }
            if (btnFooter) {
                btnFooter.style.display = "none";
            }
        }
    }
}

async function openDeleteModal(targetType, targetId, extra = {}) {
    const modal = document.getElementById("delete-impact-modal");
    if (!modal) return;

    resetSlideLockout();
    excludedTrackIds.clear();
    currentDeleteImpact = null;

    const titleEl = document.getElementById("delete-modal-target-title");
    const descEl = document.getElementById("delete-modal-target-desc");
    const albumsStatEl = document.getElementById("delete-stat-albums");
    const tracksStatEl = document.getElementById("delete-stat-tracks");
    const sizeStatEl = document.getElementById("delete-stat-size");
    const keptStatEl = document.getElementById("delete-stat-kept");
    const listEl = document.getElementById("delete-exclusion-list");

    if (titleEl) titleEl.textContent = `Analyzing deletion impact...`;
    if (descEl) descEl.textContent = `Calculating affected songs, albums, and disk footprint...`;
    if (albumsStatEl) albumsStatEl.textContent = "-";
    if (tracksStatEl) tracksStatEl.textContent = "-";
    if (sizeStatEl) sizeStatEl.textContent = "-";
    if (keptStatEl) keptStatEl.textContent = "0";

    if (listEl) {
        listEl.innerHTML = `<div class="p-4 text-center text-muted"><i class="fa-solid fa-spinner fa-spin mr-2"></i> Analyzing impact on Music Vault...</div>`;
    }

    modal.classList.remove("hidden");

    try {
        const payload = {
            target_type: targetType,
            target_id: targetId
        };
        if (targetType === "artist") {
            payload.artist_name = extra.artist || targetId;
        } else if (targetType === "album") {
            payload.album_id = targetId;
        } else if (targetType === "song") {
            payload.song_id = targetId;
        }

        const res = await fetch("/api/library/delete-impact", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            showToast(data.error || "Failed to analyze deletion impact", "error");
            modal.classList.add("hidden");
            return;
        }

        currentDeleteImpact = data;
        renderDeleteImpactUI();

    } catch (e) {
        showToast("Error communicating with server: " + e.message, "error");
        modal.classList.add("hidden");
    }
}

function initSlideLockout() {
    const track = document.getElementById("slide-lockout-track");
    const thumb = document.getElementById("slide-lockout-thumb");
    const text = document.getElementById("slide-lockout-text");
    const icon = document.getElementById("slide-lockout-icon");
    const btnConfirm = document.getElementById("btn-confirm-delete-unlocked");
    const btnFooter = document.getElementById("btn-confirm-delete-footer");
    const modal = document.getElementById("delete-impact-modal");
    const btnClose = document.getElementById("btn-close-delete-modal");
    const btnCancel = document.getElementById("btn-cancel-delete");

    if (btnClose) btnClose.addEventListener("click", () => modal?.classList.add("hidden"));
    if (btnCancel) btnCancel.addEventListener("click", () => modal?.classList.add("hidden"));

    let backdropMouseDown = false;
    let dragJustEnded = false;

    if (modal) {
        modal.addEventListener("mousedown", (e) => {
            backdropMouseDown = (e.target === modal);
        });
        modal.addEventListener("click", (e) => {
            if (isDragging || dragJustEnded) return;
            if (e.target === modal && backdropMouseDown) {
                modal.classList.add("hidden");
            }
            backdropMouseDown = false;
        });
    }

    if (!track || !thumb) return;

    let isDragging = false;
    let startX = 0;
    const initialRight = 4; // css right: 4px

    function startDrag(e) {
        if (isSlideUnlocked) return;
        isDragging = true;
        dragJustEnded = false;
        startX = e.type.includes("touch") ? e.touches[0].clientX : e.clientX;
        thumb.style.transition = "none";
        document.body.style.userSelect = "none";
    }

    function doDrag(e) {
        if (!isDragging || isSlideUnlocked) return;
        const currentX = e.type.includes("touch") ? e.touches[0].clientX : e.clientX;
        // Dragging left: currentX < startX, deltaX > 0
        const deltaX = startX - currentX;
        const trackWidth = track.clientWidth;
        const thumbWidth = thumb.offsetWidth;
        const maxDrag = Math.max(0, trackWidth - thumbWidth - 8);

        const clampedDelta = Math.max(0, Math.min(deltaX, maxDrag));
        thumb.style.right = (initialRight + clampedDelta) + "px";

        if (clampedDelta >= maxDrag * 0.8) {
            track.classList.add("unlocked");
            if (icon) icon.className = "fa-solid fa-lock-open";
        } else {
            track.classList.remove("unlocked");
            if (icon) icon.className = "fa-solid fa-lock";
        }
    }

    function endDrag(e) {
        if (!isDragging || isSlideUnlocked) return;
        isDragging = false;
        dragJustEnded = true;
        setTimeout(() => { dragJustEnded = false; }, 300);
        document.body.style.userSelect = "";

        const trackWidth = track.clientWidth;
        const thumbWidth = thumb.offsetWidth;
        const maxDrag = Math.max(0, trackWidth - thumbWidth - 8);
        const currentRight = parseFloat(thumb.style.right || initialRight);
        const draggedDist = currentRight - initialRight;

        if (draggedDist >= maxDrag * 0.8) {
            isSlideUnlocked = true;
            thumb.style.transition = "right 0.15s ease-out";
            thumb.style.right = (initialRight + maxDrag) + "px";
            track.classList.add("unlocked");
            if (icon) icon.className = "fa-solid fa-lock-open";
            if (text) text.innerHTML = `<i class="fa-solid fa-check"></i> Unlocked for permanent deletion`;

            // Seamless in-place morph: hide track and display delete confirmation buttons
            setTimeout(() => {
                if (track) track.style.display = "none";
                if (btnConfirm) {
                    btnConfirm.style.display = "flex";
                    btnConfirm.classList.add("revealed");
                }
                if (btnFooter) {
                    btnFooter.style.display = "inline-flex";
                }
            }, 180);
        } else {
            thumb.style.transition = "right 0.25s ease-out";
            thumb.style.right = initialRight + "px";
            track.classList.remove("unlocked");
            if (icon) icon.className = "fa-solid fa-lock";
            setTimeout(() => {
                thumb.style.transition = "";
            }, 250);
        }
    }

    // Mouse drag
    thumb.addEventListener("mousedown", startDrag);
    window.addEventListener("mousemove", doDrag);
    window.addEventListener("mouseup", endDrag);

    // Touch drag
    thumb.addEventListener("touchstart", startDrag, { passive: true });
    window.addEventListener("touchmove", doDrag, { passive: true });
    window.addEventListener("touchend", endDrag);

    // Shared execution function
    async function executeDeletion() {
        if (!isSlideUnlocked || !currentDeleteImpact) return;

        const tracksToDelete = [];
        (currentDeleteImpact.albums || []).forEach(alb => {
            (alb.tracks || []).forEach(t => {
                if (!excludedTrackIds.has(t.id)) {
                    tracksToDelete.push(t.id);
                }
            });
        });

        if (tracksToDelete.length === 0) {
            showToast("All items were spared. Nothing to delete.", "info");
            modal?.classList.add("hidden");
            return;
        }

        if (btnConfirm) {
            btnConfirm.disabled = true;
            btnConfirm.innerHTML = `<i class="fa-solid fa-spinner fa-spin mr-2"></i> Permanently Deleting ${tracksToDelete.length} Songs...`;
        }
        if (btnFooter) {
            btnFooter.disabled = true;
            btnFooter.innerHTML = `<i class="fa-solid fa-spinner fa-spin mr-2"></i> Deleting...`;
        }

        try {
            const res = await fetch("/api/library/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    track_ids: tracksToDelete,
                    delete_files: true
                })
            });

            const data = await res.json();
            if (res.ok && data.success) {
                showToast(`Successfully deleted ${data.deleted_tracks} tracks (freed ${data.freed_str})!`, "success");
                modal?.classList.add("hidden");

                // Refresh stats and library view
                loadLibraryStats();
                const activeTab = document.querySelector(".nav-item.active")?.dataset?.tab;
                if (activeTab === "library") {
                    if (typeof currentLibraryViewMode !== "undefined" && currentLibraryViewMode === "artists") {
                        loadArtistsList();
                    } else {
                        loadLibraryBrowser();
                    }
                }
            } else {
                showToast(data.error || "Failed to delete library items", "error");
                if (btnConfirm) {
                    btnConfirm.disabled = false;
                    btnConfirm.innerHTML = `<i class="fa-solid fa-trash-can"></i> Permanently Delete Selected Items`;
                }
                if (btnFooter) {
                    btnFooter.disabled = false;
                    btnFooter.innerHTML = `<i class="fa-solid fa-trash-can"></i> Permanently Delete`;
                }
            }
        } catch (err) {
            showToast("Network error executing deletion: " + err.message, "error");
            if (btnConfirm) {
                btnConfirm.disabled = false;
                btnConfirm.innerHTML = `<i class="fa-solid fa-trash-can"></i> Permanently Delete Selected Items`;
            }
            if (btnFooter) {
                btnFooter.disabled = false;
                btnFooter.innerHTML = `<i class="fa-solid fa-trash-can"></i> Permanently Delete`;
            }
        }
    }

    if (btnConfirm) {
        btnConfirm.addEventListener("click", executeDeletion);
    }
    if (btnFooter) {
        btnFooter.addEventListener("click", executeDeletion);
    }
}
