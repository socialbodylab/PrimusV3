/**
 * audio-panel.js — Audio Panel Alpine component for PrimusV3.1
 * Playback controls + full SD card file manager for Radius nodes.
 */

document.addEventListener("alpine:init", () => {

    Alpine.store("audio", {
        volume: {},
        getVolume(di) {
            return this.volume[di] ?? 80;
        },
        setVolume(di, vol) {
            this.volume = { ...this.volume, [di]: vol };
        },
    });

    Alpine.data("audioPanel", () => ({

        // ── Playback ────────────────────────────────────────────────────
        // Optimistic overlay only: holds the local play/pause/stop intent
        // briefly until the next telemetry poll confirms it. The source of
        // truth for now-playing is dev.current_track + dev.playback_state
        // (0 stopped / 1 playing / 2 paused) from the state poll.
        _optimistic:  {},   // { di: { file, cmd, at } }
        _lastVolSent: {},
        OPTIMISTIC_HOLD_MS: 4000,

        // ── File manager ────────────────────────────────────────────────
        cwd:     {},        // { di: "/" }
        entries: {},        // { di: [{name, is_dir, size}] }
        loading: {},        // { di: bool }
        fmOpen:  {},        // { di: bool } SD file browser expanded

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
            return devices.map((d, i) => ({ ...d, di: i })).filter(d => d.is_radius || d.is_audio);
        },

        // ── Lifecycle ───────────────────────────────────────────────────

        initDevice(di) {
            if (this.cwd[di] === undefined) {
                this.cwd = { ...this.cwd, [di]: "/" };
            }
            // Deliberately no automatic loadDir() here: an FTP directory
            // listing per node at page load starves the browser connection
            // pool (each listing is an enable/handshake/disable FTP cycle).
            // The listing loads when the SD Files section is first expanded
            // or the Refresh button is pressed.
        },

        toggleFm(di) {
            const open = !this.fmOpen[di];
            this.fmOpen = { ...this.fmOpen, [di]: open };
            if (open && this.entries[di] === undefined && !this.loading[di]) {
                this.loadDir(di);
            }
        },

        // ── Directory navigation ─────────────────────────────────────────

        async loadDir(di) {
            const path = this.cwd[di] || "/";
            this.loading = { ...this.loading, [di]: true };
            try {
                const result = await api("POST", "/api/audio/files", { device: di, path });
                // Hide dotfiles: SD cards loaded from a Mac accumulate
                // .Spotlight-V100 / .Trashes dirs and "._foo.wav"
                // AppleDouble files that are not real audio.
                const entries = (result.entries || []).filter(e => !e.name.startsWith("."));
                this.entries = { ...this.entries, [di]: entries };
            } catch (e) {
                console.error("[audio] dir list failed:", e);
                this.entries = { ...this.entries, [di]: [] };
            } finally {
                this.loading = { ...this.loading, [di]: false };
            }
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
            return Alpine.store("audio").getVolume(di);
        },

        _setOptimistic(di, file, cmd) {
            this._optimistic = { ...this._optimistic, [di]: { file, cmd, at: Date.now() } };
        },

        _device(di) {
            return (Alpine.store("app").state?.devices || [])[di];
        },

        // Current playback for a device: recent local intent wins briefly,
        // then telemetry (playback_state + current_track) takes over.
        nowPlaying(di) {
            const opt = this._optimistic[di];
            if (opt && (Date.now() - opt.at) < this.OPTIMISTIC_HOLD_MS) {
                if (opt.cmd === "stop") return null;
                return {
                    file: opt.file,
                    state: opt.cmd === "pause" ? 2 : 1,
                    looping: opt.cmd === "loop",
                    optimistic: true,
                };
            }
            const dev = this._device(di);
            if (!dev || !dev.receiver_online) return null;
            const state = dev.playback_state;
            if (state !== 1 && state !== 2) return null;
            return {
                file: dev.current_track || "",
                state,
                looping: !!dev.audio_looping,
            };
        },

        nowPlayingIcon(di) {
            const np = this.nowPlaying(di);
            if (!np) return "";
            if (np.state === 2) return "‖";       // pause bars
            if (np.looping) return "↺";           // loop arrow
            return "▶";                            // play triangle
        },

        nowPlayingStateLabel(di) {
            const np = this.nowPlaying(di);
            if (!np) return "";
            if (np.state === 2) return "paused";
            return np.looping ? "looping" : "playing";
        },

        async play(di, filename, cmd = "play") {
            try {
                await api("POST", "/api/audio/cmd", {
                    device: di, cmd, filename, volume: this.getVolume(di),
                });
                this._setOptimistic(di, filename, cmd);
            } catch (e) {
                Alpine.store("app").showApiError("Play failed", e);
            }
        },

        async stop(di) {
            try {
                await api("POST", "/api/audio/cmd", { device: di, cmd: "stop", filename: "" });
                this._setOptimistic(di, "", "stop");
            } catch (e) {
                Alpine.store("app").showApiError("Stop failed", e);
            }
        },

        async pause(di) {
            try {
                await api("POST", "/api/audio/cmd", { device: di, cmd: "pause", filename: "" });
                const current = this.nowPlaying(di);
                this._setOptimistic(di, current?.file || this._device(di)?.current_track || "", "pause");
            } catch (e) {
                Alpine.store("app").showApiError("Pause failed", e);
            }
        },

        onVolumeInput(di, value) {
            const vol = parseInt(value);
            Alpine.store("audio").setVolume(di, vol);
            const now = Date.now();
            if (!this._lastVolSent[di] || now - this._lastVolSent[di] > 50) {
                this._lastVolSent[di] = now;
                api("POST", "/api/audio/cmd", { device: di, cmd: "volume", filename: "", volume: vol });
            }
        },

        isPlaying(di, filename) {
            const np = this.nowPlaying(di);
            return !!np && np.file === filename;
        },

        isLooping(di, filename) {
            const np = this.nowPlaying(di);
            return !!np && np.file === filename && np.looping;
        },

        // ── File operations ───────────────────────────────────────────────

        joinPath(cwd, name) {
            return (cwd.endsWith("/") ? cwd : cwd + "/") + name;
        },

        deleteKey(di, name) {
            return `audio-del-${di}:${name}`;
        },

        async deleteEntry(di, entry) {
            if (!Alpine.store("app").requestConfirm(this.deleteKey(di, entry.name))) return;
            const path = this.joinPath(this.cwd[di] || "/", entry.name);
            try {
                await api("POST", "/api/audio/delete", { device: di, path, is_dir: entry.is_dir });
                Alpine.store("app").showNotice(`Deleted "${entry.name}".`, "success");
                await this.loadDir(di);
            } catch (e) {
                Alpine.store("app").showApiError(`Delete of "${entry.name}" failed`, e);
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
                Alpine.store("app").showApiError("Rename failed", e);
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
                Alpine.store("app").showApiError("Create folder failed", e);
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
                    Alpine.store("app").showApiError(`Upload of "${file.name}" failed`, e);
                }
            }
            this.uploadStatus = { ...this.uploadStatus, [di]: null };
            await this.loadDir(di);
        },

        async _uploadFile(di, file) {
            const cwd = this.cwd[di] || "/";
            const path = this.joinPath(cwd, file.name);
            const setStatus = (progress) => {
                this.uploadStatus = { ...this.uploadStatus, [di]: { name: file.name, progress } };
            };
            setStatus(0);
            await new Promise((resolve, reject) => {
                const params = new URLSearchParams({ device: di, path });
                const xhr = new XMLHttpRequest();
                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) setStatus(Math.round(e.loaded / e.total * 100));
                };
                xhr.onload = () => xhr.status === 200 ? resolve() : reject(new Error(`${xhr.status}: ${xhr.statusText}`));
                xhr.onerror = () => reject(new Error("network error"));
                xhr.open("POST", `/api/audio/upload?${params}`);
                xhr.setRequestHeader("Content-Type", "application/octet-stream");
                xhr.send(file);
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
