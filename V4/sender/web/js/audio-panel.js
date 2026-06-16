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
        playing:      {},   // { di: { file, cmd } }
        _lastVolSent: {},

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
            return devices.map((d, i) => ({ ...d, di: i })).filter(d => d.is_radius || d.is_audio);
        },

        // ── Lifecycle ───────────────────────────────────────────────────

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
            const path = this.cwd[di] || "/";
            this.loading = { ...this.loading, [di]: true };
            try {
                const result = await api("POST", "/api/audio/files", { device: di, path });
                this.entries = { ...this.entries, [di]: result.entries || [] };
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

        async play(di, filename, cmd = "play") {
            await api("POST", "/api/audio/cmd", {
                device: di, cmd, filename, volume: this.getVolume(di),
            });
            this.playing = { ...this.playing, [di]: { file: filename, cmd } };
        },

        async stop(di) {
            await api("POST", "/api/audio/cmd", { device: di, cmd: "stop", filename: "" });
            const p = { ...this.playing };
            delete p[di];
            this.playing = p;
        },

        async pause(di) {
            await api("POST", "/api/audio/cmd", { device: di, cmd: "pause", filename: "" });
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
            return this.playing[di]?.file === filename;
        },

        isLooping(di, filename) {
            return this.playing[di]?.file === filename && this.playing[di]?.cmd === "loop";
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
