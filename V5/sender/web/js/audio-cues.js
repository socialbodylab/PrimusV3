/**
 * audio-cues.js — Audio Cue System panel Alpine component for PrimusV3.1
 *
 * Manages a sender-side cue sheet: define numbered cues, assign per-device
 * actions (play/loop/stop + file + volume + duration), fire cues to Radius
 * nodes over Art-Net, and sync project WAV files to device SD cards.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("audioCues", () => ({

        // ── State ─────────────────────────────────────────────────────
        cues:         [],   // [{number, note, actions: {ip: {cmd,filename,volume,duration}}}]
        projectFiles: [],   // [{name, size}]
        _saveTimer:   null,

        // Sync
        syncModal:     false,
        syncJob:       null,  // job dict from server
        _syncTimer:    null,

        // Fire results: cue_number -> {ip -> {status, reason}}
        fireResults:   {},
        _fireFadeTimers: {},

        // Cue Maps (push this sheet to each device's on-SD /cues.json)
        cueMapsModal:      false,
        cueMapsPreview:    null,   // [{ip, name, connected, cue_count, cues}]
        cueMapsLoading:    false,
        cueMapsUploading:  false,
        cueMapsResults:    null,   // {ip: {status, cue_count, name, error}}
        cueMapsError:      null,

        // Import
        _importInput:  null,

        // ── Computed ──────────────────────────────────────────────────

        get audioDevices() {
            return (Alpine.store("app").state?.devices || [])
                .map((d, i) => ({ ...d, di: i }))
                .filter(d => d.is_audio);
        },

        get sortedCues() {
            return [...this.cues].sort((a, b) => (a.number || 0) - (b.number || 0));
        },

        // ── Lifecycle ─────────────────────────────────────────────────

        async init() {
            await this.load();
            await this.loadProjectFiles();
        },

        // ── Cue sheet persistence ─────────────────────────────────────

        async load() {
            try {
                const data = await api("GET", "/api/audio_cues");
                this.cues = data.cues || [];
            } catch (e) {
                console.error("[audio-cues] load failed:", e);
            }
        },

        scheduleSave() {
            clearTimeout(this._saveTimer);
            this._saveTimer = setTimeout(() => this.save(), 500);
        },

        async save() {
            try {
                await api("POST", "/api/audio_cues", { cues: this.cues });
            } catch (e) {
                console.error("[audio-cues] save failed:", e);
            }
        },

        // ── Cue operations ────────────────────────────────────────────

        addCue() {
            const nums = this.cues.map(c => c.number || 0);
            const next = nums.length ? Math.max(...nums) + 1 : 1;
            this.cues = [...this.cues, {
                number:  next,
                note:    "",
                actions: {},
            }];
            this.scheduleSave();
        },

        removeCue(idx) {
            const c = this.sortedCues[idx];
            if (!confirm(`Remove cue ${c.number}?`)) return;
            this.cues = this.cues.filter(x => x !== c);
            this.scheduleSave();
        },

        updateCueField(idx, field, value) {
            const c = this.sortedCues[idx];
            const i = this.cues.indexOf(c);
            if (i === -1) return;
            this.cues = this.cues.map((x, j) =>
                j === i ? { ...x, [field]: value } : x
            );
            this.scheduleSave();
        },

        // ── Per-device actions ────────────────────────────────────────

        getAction(cueIdx, ip) {
            const c = this.sortedCues[cueIdx];
            return c?.actions?.[ip] || { cmd: "none", filename: "", volume: 80, duration: 0 };
        },

        setActionField(cueIdx, ip, field, value) {
            const c  = this.sortedCues[cueIdx];
            const i  = this.cues.indexOf(c);
            if (i === -1) return;
            const cue = { ...this.cues[i] };
            cue.actions = { ...cue.actions };
            cue.actions[ip] = { ...this.getAction(cueIdx, ip), [field]: value };
            this.cues = this.cues.map((x, j) => j === i ? cue : x);
            this.scheduleSave();
        },

        actionIsActive(cueIdx, ip) {
            return this.getAction(cueIdx, ip).cmd !== "none";
        },

        // ── Cue Maps (push sheet → each device's SD /cues.json) ───────

        async openCueMaps() {
            this.cueMapsModal     = true;
            this.cueMapsPreview   = null;
            this.cueMapsResults   = null;
            this.cueMapsError     = null;
            this.cueMapsLoading   = true;
            this.cueMapsUploading = false;
            try {
                const data = await api("POST", "/api/audio_cues/preview_cue_maps");
                this.cueMapsPreview = data.devices || [];
            } catch (e) {
                this.cueMapsError = e.message;
            } finally {
                this.cueMapsLoading = false;
            }
        },

        closeCueMaps() {
            this.cueMapsModal = false;
        },

        async uploadCueMaps() {
            this.cueMapsUploading = true;
            this.cueMapsResults   = null;
            this.cueMapsError     = null;
            try {
                const data = await api("POST", "/api/audio_cues/push_cue_maps");
                this.cueMapsResults = data.results || {};
                if (data.message) this.cueMapsError = data.message;
            } catch (e) {
                this.cueMapsError = e.message;
            } finally {
                this.cueMapsUploading = false;
            }
        },

        cueMapsConnectedCount() {
            return (this.cueMapsPreview || []).filter(d => d.connected).length;
        },

        // ── Fire ──────────────────────────────────────────────────────

        async fireCue(cueIdx) {
            const c = this.sortedCues[cueIdx];
            try {
                const res = await api("POST", "/api/audio_cues/fire", { number: c.number });
                const results = res.results || {};
                this.fireResults = { ...this.fireResults, [c.number]: results };

                // Auto-clear after 3 seconds
                clearTimeout(this._fireFadeTimers[c.number]);
                this._fireFadeTimers[c.number] = setTimeout(() => {
                    const r = { ...this.fireResults };
                    delete r[c.number];
                    this.fireResults = r;
                }, 3000);
            } catch (e) {
                console.error("[audio-cues] fire failed:", e);
            }
        },

        fireStatusForDevice(cueNumber, ip) {
            return this.fireResults[cueNumber]?.[ip] || null;
        },

        fireStatusClass(result) {
            if (!result) return "";
            if (result.status === "sent")    return "fire-sent";
            if (result.status === "skipped") return "fire-skipped";
            if (result.status === "error")   return "fire-error";
            return "";
        },

        fireStatusIcon(result) {
            if (!result) return "";
            if (result.status === "sent")    return "✓";
            if (result.status === "skipped") return "○";
            if (result.status === "error")   return "✗";
            return "";
        },

        // ── Project audio library ─────────────────────────────────────

        async loadProjectFiles() {
            try {
                const res = await api("GET", "/api/project_audio");
                this.projectFiles = res.files || [];
            } catch (e) {
                console.error("[audio-cues] project files load failed:", e);
            }
        },

        triggerProjectImport() {
            if (!this._importInput) {
                const el = document.createElement("input");
                el.type   = "file";
                el.accept = ".wav,.WAV";
                el.multiple = true;
                el.style.display = "none";
                document.body.appendChild(el);
                el.addEventListener("change", async (ev) => {
                    const files = Array.from(ev.target.files || []);
                    ev.target.value = "";
                    for (const f of files) await this.uploadProjectFile(f);
                    await this.loadProjectFiles();
                });
                this._importInput = el;
            }
            this._importInput.click();
        },

        async uploadProjectFile(file) {
            // Check RIFF+WAVE header
            const hdr  = await file.slice(0, 12).arrayBuffer();
            const magic = new Uint8Array(hdr);
            const isRiff = magic[0]===0x52 && magic[1]===0x49 && magic[2]===0x46 && magic[3]===0x46;
            const isWave = magic[8]===0x57 && magic[9]===0x41 && magic[10]===0x56 && magic[11]===0x45;
            if (!isRiff || !isWave) {
                alert(`"${file.name}" is not a valid WAV file.\n\nProject library requires PCM WAV format.`);
                return;
            }
            const params = new URLSearchParams({ filename: file.name });
            const resp = await fetch(`/api/project_audio?${params}`, {
                method: "POST",
                headers: { "Content-Type": "application/octet-stream" },
                body: file,
            });
            if (!resp.ok) {
                let msg = `Upload failed (${resp.status})`;
                try { msg = (await resp.json()).error || msg; } catch (_) {}
                alert(msg);
            }
        },

        async deleteProjectFile(name) {
            if (!confirm(`Remove "${name}" from project library?`)) return;
            try {
                await fetch(`/api/project_audio/${encodeURIComponent(name)}`,
                            { method: "DELETE" });
                await this.loadProjectFiles();
            } catch (e) {
                console.error("[audio-cues] delete project file failed:", e);
            }
        },

        formatSize(bytes) {
            if (bytes < 1024)       return bytes + " B";
            if (bytes < 1048576)    return (bytes / 1024).toFixed(1) + " KB";
            return (bytes / 1048576).toFixed(1) + " MB";
        },

        // ── Import / Export cue sheet ─────────────────────────────────

        exportCueSheet() {
            window.location.href = "/api/audio_cues/export";
        },

        triggerCueImport() {
            const el = document.createElement("input");
            el.type   = "file";
            el.accept = ".json";
            el.style.display = "none";
            document.body.appendChild(el);
            el.addEventListener("change", async (ev) => {
                const file = ev.target.files?.[0];
                if (!file) return;
                try {
                    const text = await file.text();
                    const data = JSON.parse(text);
                    await fetch("/api/audio_cues/import", {
                        method:  "POST",
                        headers: { "Content-Type": "application/json" },
                        body:    JSON.stringify(data),
                    });
                    await this.load();
                } catch (e) {
                    alert(`Import failed: ${e.message}`);
                }
                document.body.removeChild(el);
            });
            el.click();
        },

        // ── Sync ──────────────────────────────────────────────────────

        async startSync() {
            try {
                const res = await api("POST", "/api/audio_sync");
                if (res.error) {
                    alert(res.error);
                    return;
                }
                this.syncJob   = { job_id: res.job_id, status: "planning", items: [] };
                this.syncModal = true;
                this._syncTimer = setInterval(() => this.pollSync(), 500);
            } catch (e) {
                alert(`Sync failed: ${e.message}`);
            }
        },

        async pollSync() {
            try {
                const job = await api("GET", "/api/audio_sync/status");
                this.syncJob = job;
                if (job.status === "done" || job.status === "error") {
                    clearInterval(this._syncTimer);
                    this._syncTimer = null;
                }
            } catch (_) { /* ignore */ }
        },

        closeSyncModal() {
            clearInterval(this._syncTimer);
            this._syncTimer = null;
            this.syncModal  = false;
        },

        syncItemClass(item) {
            switch (item.status) {
                case "done":      return "sync-done";
                case "error":     return "sync-error";
                case "skipped":   return "sync-skipped";
                case "uploading": return "sync-uploading";
                default:          return "sync-pending";
            }
        },

        syncItemIcon(item) {
            switch (item.status) {
                case "done":      return "✓";
                case "error":     return "✗";
                case "skipped":   return "—";
                case "uploading": return "↑";
                default:          return "·";
            }
        },

        syncProgress(item) {
            if (!item.bytes_total) return 0;
            return Math.round(item.bytes_sent / item.bytes_total * 100);
        },

        syncSummary() {
            if (!this.syncJob) return "";
            const items = this.syncJob.items || [];
            const done  = items.filter(i => i.status === "done").length;
            const total = items.filter(i => i.status !== "skipped" ||
                                            i.error === "already on device").length;
            return `${done} / ${total} uploaded`;
        },
    }));

});
