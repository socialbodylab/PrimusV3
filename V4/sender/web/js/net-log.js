/**
 * net-log.js — Network Log panel Alpine component for PrimusV3.1
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("netLog", () => ({

        entries:    [],   // newest-first
        lastId:     0,
        showFps:    true,
        _timer:     null,
        _polling:   false,

        get visibleEntries() {
            if (this.showFps) return this.entries;
            return this.entries.filter(e => e.type !== "fps_telemetry");
        },

        TYPE_LABELS: {
            artpoll:       "Poll",
            pollreply:     "Reply",
            art_address:   "Rename",
            output_config: "OutCfg",
            audio_cmd:     "Audio",
            ftp_cmd:       "FTP Ctrl",
            ftp_upload:    "Upload",
            ftp_rename:    "Rename",
            ftp_delete:    "Delete",
            ftp_mkdir:     "Mkdir",
            ftp_sync:      "Sync",
            fps_telemetry: "FPS",
        },

        init() {
            this.poll();
            this._timer = setInterval(() => this.poll(), 500);
        },

        destroy() {
            clearInterval(this._timer);
        },

        async poll() {
            if (this._polling) return;
            this._polling = true;
            try {
                const res = await fetch(`/api/netlog?since=${this.lastId}`).then(r => r.json());
                const fresh = res.entries || [];
                if (fresh.length > 0) {
                    this.entries = [...fresh.slice().reverse(), ...this.entries];
                    if (this.entries.length > 1000) this.entries = this.entries.slice(0, 1000);
                    this.lastId = fresh[fresh.length - 1].id;
                }
            } catch (_) { /* ignore */ }
            finally {
                this._polling = false;
            }
        },

        async clear() {
            await api("POST", "/api/netlog/clear");
            this.entries = [];
            this.lastId  = 0;
        },

        download() {
            const chronological = [...this.entries].reverse();
            const blob = new Blob([JSON.stringify(chronological, null, 2)],
                                  { type: "application/json" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
            a.download = `primus-netlog-${ts}.json`;
            a.click();
            URL.revokeObjectURL(a.href);
        },

        formatTime(ts) {
            const d = new Date(ts * 1000);
            const hh = String(d.getHours()).padStart(2, "0");
            const mm = String(d.getMinutes()).padStart(2, "0");
            const ss = String(d.getSeconds()).padStart(2, "0");
            const ms = String(d.getMilliseconds()).padStart(3, "0");
            return `${hh}:${mm}:${ss}.${ms}`;
        },

        typeLabel(type) {
            return this.TYPE_LABELS[type] || type;
        },

        dirClass(dir) {
            return dir === "IN" ? "log-dir-in" : "log-dir-out";
        },

        typeClass(type) {
            if (type === "audio_cmd")   return "log-type-audio";
            if (type.startsWith("ftp")) return "log-type-ftp";
            if (type === "fps_telemetry") return "log-type-fps";
            return "log-type-default";
        },
    }));

});
