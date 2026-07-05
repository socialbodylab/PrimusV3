/**
 * audio-panel.js — Audio Panel Alpine component for PrimusV3.1
 * Playback controls + full SD card file manager for Radius nodes.
 */

document.addEventListener("alpine:init", () => {

    Alpine.store("audio", { volume: {} });

    Alpine.data("audioPanel", () => ({

        // ── Playback ────────────────────────────────────────────────────
        playing:        {},   // { di: { file, cmd } }
        _playingExpiry: {},   // { di: timestamp } — optimistic state expires after 3s without device confirmation
        lastPlayed:     {},   // { di: filename } — last file played per device
        volume:       {},   // { di: 0-100 }
        _lastVolSent: {},
        _spaceHandler: null,

        // ── File manager ────────────────────────────────────────────────
        cwd:     {},        // { di: "/" }
        entries: {},        // { di: [{name, is_dir, size}] }
        loading: {},        // { di: bool }

        // ── Upload ──────────────────────────────────────────────────────
        uploadStatus: {},   // { di: {name, progress} | null }
        dragOver:     {},   // { di: bool }

        // ── Rename ──────────────────────────────────────────────────────
        renaming: {},       // { di: {name, value} | null }

        // ── New folder ──────────────────────────────────────────────────
        newFolderMode: {},  // { di: bool }
        newFolderName: {},  // { di: string }

        // ── Computed ────────────────────────────────────────────────────

        get audioDevices() {
            const devices = Alpine.store("app").state?.devices || [];
            return devices.map((d, i) => ({ ...d, di: i })).filter(d => d.is_audio);
        },

        // ── Lifecycle ───────────────────────────────────────────────────

        init() {
            this._spaceHandler = (e) => {
                if (e.code !== "Space") return;
                if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
                if (Alpine.store("app").mode !== "audio") return;
                e.preventDefault();
                this.spacebarToggle();
            };
            window.addEventListener("keydown", this._spaceHandler);
        },

        destroy() {
            if (this._spaceHandler) window.removeEventListener("keydown", this._spaceHandler);
        },

        spacebarToggle() {
            // Stop the first playing device
            for (const dev of this.audioDevices) {
                if (this.nowPlaying(dev.di)) {
                    this.stop(dev.di);
                    return;
                }
            }
            // Nothing playing — play last file or first WAV on first device
            const dev = this.audioDevices[0];
            if (!dev) return;
            const filename = this.lastPlayed[dev.di] || this.wavFiles(dev.di)[0]?.name;
            if (filename) this.play(dev.di, filename);
        },

        initDevice(di) {
            if (this.cwd[di] === undefined) {
                this.cwd = { ...this.cwd, [di]: "/" };
            }
            if (this.entries[di] === undefined) {
                this.loadDir(di);
            }
        },

        // ── Directory navigation ─────────────────────────────────────────

        async loadDir(di) {
            this.cwd = { ...this.cwd, [di]: "/" };
            this.loading = { ...this.loading, [di]: true };
            try {
                const result = await api("POST", "/api/audio/files", { device: di, path: "/" });
                this.entries = { ...this.entries, [di]: result.entries || [] };
            } catch (e) {
                console.error("[audio] dir list failed:", e);
                this.entries = { ...this.entries, [di]: [] };
            } finally {
                this.loading = { ...this.loading, [di]: false };
            }
        },

        wavFiles(di) {
            return (this.entries[di] || []).filter(e =>
                !e.is_dir &&
                e.name.toLowerCase().endsWith(".wav") &&
                !e.name.startsWith("._")
            );
        },

        navigateInto(di, name) {
            const cwd = this.cwd[di] || "/";
            const next = cwd.endsWith("/") ? cwd + name : cwd + "/" + name;
            this.cwd = { ...this.cwd, [di]: next };
            this.entries = { ...this.entries, [di]: undefined };
            this.loadDir(di);
        },

        navigateTo(di, path) {
            this.cwd = { ...this.cwd, [di]: path };
            this.entries = { ...this.entries, [di]: undefined };
            this.loadDir(di);
        },

        breadcrumbs(di) {
            const cwd = this.cwd[di] || "/";
            return cwd.split("/").filter(s => s.length > 0);
        },

        crumbPath(di, idx) {
            const segs = this.breadcrumbs(di);
            return "/" + segs.slice(0, idx + 1).join("/");
        },

        // ── Playback ─────────────────────────────────────────────────────

        getVolume(di) {
            return this.volume[di] ?? 80;
        },

        async play(di, filename, cmd = "play") {
            const devices = Alpine.store("app").state?.devices || [];
            const isConnected = !!devices[di]?.connected;
            await api("POST", "/api/audio/cmd", {
                device: di, cmd, filename, volume: this.getVolume(di),
            });
            this.playing    = { ...this.playing,    [di]: { file: filename, cmd } };
            this.lastPlayed = { ...this.lastPlayed, [di]: filename };
            if (isConnected) {
                // Hold optimistic state while waiting for first AudioStatus reply (~3s).
                // Once the device reports "playing", nowPlaying() switches to device-driven
                // and will stay lit until the device reports "stopped".
                this._playingExpiry = { ...this._playingExpiry, [di]: Date.now() + 3000 };
            } else {
                // Not connected: command is still sent and logged, but button returns to rest immediately.
                const expiry = { ...this._playingExpiry };
                delete expiry[di];
                this._playingExpiry = expiry;
            }
        },

        async stop(di) {
            await api("POST", "/api/audio/cmd", { device: di, cmd: "stop", filename: "" });
            const p = { ...this.playing };
            delete p[di];
            this.playing = p;
            const expiry = { ...this._playingExpiry };
            delete expiry[di];
            this._playingExpiry = expiry;
        },

        async pause(di) {
            await api("POST", "/api/audio/cmd", { device: di, cmd: "pause", filename: "" });
        },

        onVolumeInput(di, value) {
            const vol = parseInt(value);
            this.volume = { ...this.volume, [di]: vol };
            Alpine.store("audio").volume[di] = vol;
            const now = Date.now();
            if (!this._lastVolSent[di] || now - this._lastVolSent[di] > 50) {
                this._lastVolSent[di] = now;
                api("POST", "/api/audio/cmd", { device: di, cmd: "volume", filename: "", volume: vol });
            }
        },

        // Authoritative playback state: device report takes priority.
        // "stopped" from device clears immediately. "unknown" (no report yet) allows
        // a 3-second optimistic window after a play command so the UI doesn't flash.
        nowPlaying(di) {
            const devices = Alpine.store("app").state?.devices || [];
            const dev = devices[di];
            if (dev?.audio_status === "stopped") return null;
            if (dev?.audio_status === "playing" && dev?.now_playing) {
                return { file: dev.now_playing, cmd: this.playing[di]?.cmd || "play" };
            }
            // Unknown status (no report yet) — use optimistic state within 3s of play command
            if ((this._playingExpiry[di] || 0) > Date.now()) return this.playing[di] || null;
            return null;
        },

        isPlaying(di, filename) {
            return this.nowPlaying(di)?.file === filename;
        },

        isLooping(di, filename) {
            const np = this.nowPlaying(di);
            return np?.file === filename && np?.cmd === "loop";
        },

        // ── File operations ───────────────────────────────────────────────

        joinPath(cwd, name) {
            return (cwd.endsWith("/") ? cwd : cwd + "/") + name;
        },

        async deleteEntry(di, entry) {
            if (!confirm(`Delete "${entry.name}"?`)) return;
            const path = this.joinPath(this.cwd[di] || "/", entry.name);
            try {
                await api("POST", "/api/audio/delete", { device: di, path, is_dir: entry.is_dir });
                await this.loadDir(di);
            } catch (e) {
                console.error("[audio] delete failed:", e);
                alert(`Delete failed: ${e.message}`);
            }
        },

        // ── Rename ───────────────────────────────────────────────────────

        startRename(di, name) {
            this.renaming = { ...this.renaming, [di]: { name, value: name } };
        },

        cancelRename(di) {
            const r = { ...this.renaming };
            delete r[di];
            this.renaming = r;
        },

        async commitRename(di, oldName) {
            const newName = (this.renaming[di]?.value || "").trim();
            this.cancelRename(di);
            if (!newName || newName === oldName) return;
            const cwd = this.cwd[di] || "/";
            const src = this.joinPath(cwd, oldName);
            const dst = this.joinPath(cwd, newName);
            try {
                await api("POST", "/api/audio/rename", { device: di, src, dst });
                await this.loadDir(di);
            } catch (e) {
                console.error("[audio] rename failed:", e);
                alert(`Rename failed: ${e.message}`);
            }
        },

        isRenaming(di, name) {
            return this.renaming[di]?.name === name;
        },

        // ── New folder ────────────────────────────────────────────────────

        async startNewFolder(di) {
            this.newFolderMode = { ...this.newFolderMode, [di]: true };
            this.newFolderName = { ...this.newFolderName, [di]: "" };
            await this.$nextTick();
            document.getElementById(`new-folder-input-${di}`)?.focus();
        },

        cancelNewFolder(di) {
            const m = { ...this.newFolderMode };
            delete m[di];
            this.newFolderMode = m;
        },

        async commitNewFolder(di) {
            const name = (this.newFolderName[di] || "").trim();
            this.cancelNewFolder(di);
            if (!name) return;
            const path = this.joinPath(this.cwd[di] || "/", name);
            try {
                await api("POST", "/api/audio/mkdir", { device: di, path });
                await this.loadDir(di);
            } catch (e) {
                console.error("[audio] mkdir failed:", e);
                alert(`Create folder failed: ${e.message}`);
            }
        },

        // ── Upload ────────────────────────────────────────────────────────

        triggerFileInput(di) {
            document.getElementById(`file-input-${di}`)?.click();
        },

        onFileInput(di, event) {
            const files = Array.from(event.target.files || []);
            event.target.value = "";
            if (files.length) this.uploadFiles(di, files);
        },

        onDrop(di, event) {
            this.dragOver = { ...this.dragOver, [di]: false };
            const files = Array.from(event.dataTransfer?.files || []);
            if (files.length) this.uploadFiles(di, files);
        },

        async uploadFiles(di, files) {
            for (const file of files) {
                try {
                    await this._uploadFile(di, file);
                } catch (e) {
                    console.error(`[audio] upload failed (${file.name}):`, e);
                }
            }
            this.uploadStatus = { ...this.uploadStatus, [di]: null };
            await this.loadDir(di);
        },

        async _uploadFile(di, file) {
            // Check RIFF+WAVE header before sending anything
            const header = await file.slice(0, 12).arrayBuffer();
            const magic = new Uint8Array(header);
            const isRiff = magic[0]===0x52 && magic[1]===0x49 && magic[2]===0x46 && magic[3]===0x46;
            const isWave = magic[8]===0x57 && magic[9]===0x41 && magic[10]===0x56 && magic[11]===0x45;
            if (!isRiff || !isWave) {
                alert(`"${file.name}" is not a valid WAV file.\n\nThe device requires PCM WAV format. AIFF, MP3, and other formats are not supported.\n\nConvert with: afconvert -f WAVE -d LEI16@44100 input.aif output.wav`);
                return;
            }

            const cwd = this.cwd[di] || "/";
            const path = this.joinPath(cwd, file.name);
            const setStatus = (progress) => {
                this.uploadStatus = { ...this.uploadStatus, [di]: { name: file.name, progress } };
            };
            setStatus(0);

            // Poll server-side FTP progress while the XHR is in flight.
            let pollId = null;
            const startPolling = () => {
                pollId = setInterval(async () => {
                    try {
                        const r = await fetch(`/api/audio/upload_progress?device=${di}`);
                        const p = await r.json();
                        if (p.active && p.bytes_total > 0) {
                            setStatus(Math.round(p.bytes_sent / p.bytes_total * 100));
                        } else if (!p.active) {
                            setStatus(null);
                        }
                    } catch (_) {}
                }, 250);
            };
            const stopPolling = () => { if (pollId !== null) { clearInterval(pollId); pollId = null; } };

            await new Promise((resolve, reject) => {
                const params = new URLSearchParams({ device: di, path });
                const xhr = new XMLHttpRequest();
                xhr.onload = () => {
                    stopPolling();
                    if (xhr.status === 200) {
                        resolve();
                    } else {
                        let msg = `Upload failed (${xhr.status})`;
                        try { msg = JSON.parse(xhr.responseText).error || msg; } catch (_) {}
                        reject(new Error(msg));
                    }
                };
                xhr.onerror = () => { stopPolling(); reject(new Error("network error")); };
                xhr.open("POST", `/api/audio/upload?${params}`);
                xhr.setRequestHeader("Content-Type", "application/octet-stream");
                xhr.send(file);
                startPolling();
            });
        },

        // ── Display helpers ───────────────────────────────────────────────

        entryIcon(di, entry) {
            if (entry.is_dir) return "📁";
            if (this.isLooping(di, entry.name)) return "↺";
            if (this.isPlaying(di, entry.name)) return "▶";
            return "🎵";
        },

        formatSize(bytes) {
            if (bytes < 1024) return bytes + " B";
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
            return (bytes / (1024 * 1024)).toFixed(1) + " MB";
        },
    }));

});
