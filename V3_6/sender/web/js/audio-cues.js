/**
 * audio-cues.js — Audio Cue System panel Alpine component for PrimusV3.
 *
 * Manages a sender-side cue sheet: define numbered cues, assign per-device
 * actions (play/loop/stop + file + volume + duration), fire cues to Radius
 * nodes over Art-Net, and sync project WAV files to device SD cards.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("audioCues", () => ({

        // ── State ─────────────────────────────────────────────────────
        cues:         [],   // [{number, note, actions: {ip: {cmd,filename,volume,duration}}}]
        projectFiles: [],   // [{name, size, checksum, sources, local}]
        deviceInventory: {},   // {ip: {name, files, scanned_at}}
        inventoryAge: null,    // seconds since last scan
        _saveTimer:   null,

        // Push sync
        syncModal:    false,
        syncJob:      null,
        _syncTimer:   null,

        // Pull sync
        pullModal:    false,
        pullJob:      null,
        _pullTimer:   null,
        resolutions:  {},   // {filename: {checksum: {action, save_as}}}

        // Rescan
        rescanning:   false,

        // Fire results: cue_number -> {ip -> {status, reason}}
        fireResults:   {},
        _fireFadeTimers: {},

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

        get pendingConflicts() {
            return (this.pullJob?.conflicts || []);
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

        // ── Fire ──────────────────────────────────────────────────────

        async fireCue(cueIdx) {
            const c = this.sortedCues[cueIdx];
            try {
                const res = await api("POST", "/api/audio_cues/fire", { number: c.number });
                const results = res.results || {};
                this.fireResults = { ...this.fireResults, [c.number]: results };

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
                this.projectFiles   = res.files || [];
                this.deviceInventory = res.device_inventory || {};
                this.inventoryAge   = res.inventory_age_seconds ?? null;
            } catch (e) {
                console.error("[audio-cues] project files load failed:", e);
            }
        },

        inventoryAgeLabel() {
            if (this.inventoryAge === null) return "not scanned";
            if (this.inventoryAge < 60)     return "just now";
            if (this.inventoryAge < 3600)   return Math.round(this.inventoryAge / 60) + "m ago";
            return Math.round(this.inventoryAge / 3600) + "h ago";
        },

        deviceNameForIp(ip) {
            return this.deviceInventory[ip]?.name || ip;
        },

        fileSourceLabel(source) {
            if (source === "local") return "Local";
            return this.deviceNameForIp(source);
        },

        fileOnAllDevices(file) {
            const devIps = Object.keys(this.deviceInventory);
            if (!devIps.length) return false;
            return devIps.every(ip => (file.sources || []).includes(ip));
        },

        triggerProjectImport() {
            if (!this._importInput) {
                const el = document.createElement("input");
                el.type     = "file";
                el.accept   = ".wav,.WAV";
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
                method:  "POST",
                headers: { "Content-Type": "application/octet-stream" },
                body:    file,
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
            if (!bytes)             return "—";
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

        // ── Push sync (sender → devices) ──────────────────────────────

        async startSync() {
            if (!confirm("Push missing files to all Radius devices?\n\nThis will stop audio on all connected devices.")) return;
            try {
                const res = await api("POST", "/api/audio_sync");
                if (res.error) { alert(res.error); return; }
                this.syncJob   = { job_id: res.job_id, type: "push", status: "planning", items: [], conflicts: [], errors: [] };
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
                    await this.loadProjectFiles();
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
            return Math.round((item.bytes_sent || 0) / item.bytes_total * 100);
        },

        syncSummary() {
            if (!this.syncJob) return "";
            const items = this.syncJob.items || [];
            const done  = items.filter(i => i.status === "done").length;
            const total = items.filter(i => i.status !== "skipped").length;
            return `${done} / ${total} uploaded`;
        },

        syncStatusLabel() {
            switch (this.syncJob?.status) {
                case "planning":  return "Planning…";
                case "stopping":  return "Stopping audio…";
                case "running":   return "Syncing…";
                case "done":      return "Sync complete";
                case "error":     return "Sync error";
                default:          return "Sync";
            }
        },

        // ── Pull sync (devices → sender) ──────────────────────────────

        async startPull() {
            if (!confirm("Pull files from all Radius devices to project library?\n\nThis will stop audio on all connected devices.")) return;
            try {
                const res = await api("POST", "/api/audio_sync/pull");
                if (res.error) { alert(res.error); return; }
                this.pullJob      = { job_id: res.job_id, type: "pull", status: "planning", items: [], conflicts: [], errors: [] };
                this.resolutions  = {};
                this.pullModal    = true;
                this._pullTimer   = setInterval(() => this.pollPull(), 500);
            } catch (e) {
                alert(`Pull failed: ${e.message}`);
            }
        },

        async pollPull() {
            try {
                const job = await api("GET", "/api/audio_sync/status");
                this.pullJob = job;
                if (job.status === "done" || job.status === "error") {
                    clearInterval(this._pullTimer);
                    this._pullTimer = null;
                    await this.loadProjectFiles();
                    this._initResolutions();
                }
            } catch (_) { /* ignore */ }
        },

        _initResolutions() {
            const r = {};
            for (const conflict of (this.pullJob?.conflicts || [])) {
                r[conflict.filename] = {};
                for (const group of conflict.groups) {
                    r[conflict.filename][group.checksum] = {
                        action:  "save",
                        save_as: group.suggested_name,
                    };
                }
            }
            this.resolutions = r;
        },

        closePullModal() {
            clearInterval(this._pullTimer);
            this._pullTimer = null;
            this.pullModal  = false;
        },

        pullItemClass(item) {
            switch (item.status) {
                case "done":         return "sync-done";
                case "confirmed":    return "sync-done";
                case "error":        return "sync-error";
                case "skipped":      return "sync-skipped";
                case "downloading":
                case "checksumming": return "sync-uploading";
                default:             return "sync-pending";
            }
        },

        pullItemIcon(item) {
            switch (item.status) {
                case "done":         return "✓";
                case "confirmed":    return "=";
                case "error":        return "✗";
                case "skipped":      return "—";
                case "downloading":  return "↓";
                case "checksumming": return "⊙";
                default:             return "·";
            }
        },

        pullProgress(item) {
            if (!item.bytes_total) return 0;
            return Math.round((item.bytes_received || 0) / item.bytes_total * 100);
        },

        pullSummary() {
            if (!this.pullJob) return "";
            const items     = this.pullJob.items || [];
            const pulled    = items.filter(i => i.status === "done").length;
            const confirmed = items.filter(i => i.status === "confirmed").length;
            const conflicts = (this.pullJob.conflicts || []).length;
            const errors    = (this.pullJob.errors || []).length;
            let parts = [];
            if (pulled)    parts.push(`${pulled} saved`);
            if (confirmed) parts.push(`${confirmed} already synced`);
            if (conflicts) parts.push(`${conflicts} conflict${conflicts !== 1 ? "s" : ""}`);
            if (errors)    parts.push(`${errors} error${errors !== 1 ? "s" : ""}`);
            return parts.join(", ") || "done";
        },

        pullStatusLabel() {
            switch (this.pullJob?.status) {
                case "planning":  return "Planning…";
                case "stopping":  return "Stopping audio…";
                case "running":   return "Pulling files…";
                case "done":      return (this.pullJob.conflicts || []).length
                                       ? "Pull complete — resolve conflicts below"
                                       : "Pull complete";
                case "error":     return "Pull error";
                default:          return "Pull";
            }
        },

        // ── Conflict resolution ───────────────────────────────────────

        setResolutionAction(filename, checksum, action) {
            const f = this.resolutions[filename] || {};
            this.resolutions = {
                ...this.resolutions,
                [filename]: { ...f, [checksum]: { ...f[checksum], action } },
            };
        },

        setResolutionSaveAs(filename, checksum, saveAs) {
            const f = this.resolutions[filename] || {};
            this.resolutions = {
                ...this.resolutions,
                [filename]: { ...f, [checksum]: { ...f[checksum], save_as: saveAs } },
            };
        },

        resolutionFor(filename, checksum) {
            return this.resolutions[filename]?.[checksum] || { action: "save", save_as: "" };
        },

        async resolveConflict(filename) {
            const conflict = (this.pullJob?.conflicts || []).find(c => c.filename === filename);
            if (!conflict) return;
            const resolutions = conflict.groups.map(g => ({
                checksum: g.checksum,
                action:   this.resolutionFor(filename, g.checksum).action,
                save_as:  this.resolutionFor(filename, g.checksum).save_as || g.suggested_name,
            }));
            try {
                await api("POST", "/api/audio_sync/resolve", { filename, resolutions });
                this.pullJob = {
                    ...this.pullJob,
                    conflicts: (this.pullJob.conflicts || []).filter(c => c.filename !== filename),
                };
                await this.loadProjectFiles();
            } catch (e) {
                let msg = e.message;
                try { msg = (await e.response?.json())?.error || msg; } catch (_) {}
                alert(`Resolve failed: ${msg}`);
            }
        },

        async resolveAll() {
            for (const conflict of [...(this.pullJob?.conflicts || [])]) {
                await this.resolveConflict(conflict.filename);
            }
        },

        checksumShort(checksum) {
            return (checksum || "").replace("sha256:", "").slice(0, 8) + "…";
        },

        // ── Rescan ────────────────────────────────────────────────────

        async rescan() {
            this.rescanning = true;
            try {
                await api("POST", "/api/audio_sync/rescan");
                await this.loadProjectFiles();
            } catch (e) {
                console.error("[audio-cues] rescan failed:", e);
            } finally {
                this.rescanning = false;
            }
        },

    }));

});
