/**
 * cue-map.js — Cue Map editor for Radius nodes.
 *
 * Reads and writes /cues.json on the SD card via FTP.
 * Supports the full cues.h schema: cmd, file, volume, duration.
 */

function cueMap() {
    return {
        deviceIdx: null,
        loading: false,
        saving: false,
        rows: [],          // [{ number, cmd, file, volume, duration }]
        deviceFiles: [],   // WAV filenames available on selected device
        error: null,
        success: null,

        get audioDevices() {
            return Alpine.store("conn").devices
                .map((d, i) => ({ ...d, _di: i }))
                .filter(d => d.is_audio);
        },

        needsFile(cmd) {
            return cmd === "play" || cmd === "loop";
        },

        async selectDevice(di) {
            this.deviceIdx = di;
            this.rows = [];
            this.deviceFiles = [];
            this.error = null;
            this.success = null;
            await this.load();
        },

        async load() {
            if (this.deviceIdx === null) return;
            this.loading = true;
            this.error = null;
            try {
                const [mapData, filesData] = await Promise.all([
                    api("GET", `/api/audio/cue_map?device=${this.deviceIdx}`),
                    api("POST", "/api/audio/files", { device: this.deviceIdx, path: "/" })
                        .catch(() => ({ entries: [] })),
                ]);
                this.rows = Object.entries(mapData)
                    .map(([num, val]) => {
                        if (typeof val === "string") {
                            return { number: parseInt(num), cmd: "play", file: val,
                                     volume: null, duration: 0 };
                        }
                        return {
                            number:   parseInt(num),
                            cmd:      val.cmd || "play",
                            file:     val.file || "",
                            volume:   val.volume != null ? val.volume : null,
                            duration: val.duration || 0,
                        };
                    })
                    .sort((a, b) => a.number - b.number);
                this.deviceFiles = (filesData.entries || [])
                    .filter(e => !e.is_dir && e.name.toLowerCase().endsWith(".wav"))
                    .map(e => e.name)
                    .sort((a, b) => a.localeCompare(b));
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },

        addRow() {
            const maxNum = this.rows.reduce((m, r) => Math.max(m, r.number), 0);
            this.rows.push({ number: Math.min(maxNum + 1, 255), cmd: "play",
                             file: "", volume: null, duration: 0 });
        },

        removeRow(idx) {
            this.rows.splice(idx, 1);
        },

        moveRow(idx, dir) {
            const to = idx + dir;
            if (to < 0 || to >= this.rows.length) return;
            [this.rows[idx], this.rows[to]] = [this.rows[to], this.rows[idx]];
        },

        async save() {
            if (this.deviceIdx === null) return;
            this.saving = true;
            this.error = null;
            this.success = null;
            try {
                const cues = {};
                for (const row of this.rows) {
                    if (!row.number) continue;
                    const cmd = row.cmd || "play";
                    if (this.needsFile(cmd) && !row.file) continue;
                    const n = String(parseInt(row.number));
                    const entry = { cmd };
                    if (this.needsFile(cmd)) entry.file = row.file;
                    if (row.volume != null && row.volume !== "") entry.volume = parseInt(row.volume);
                    if (row.duration > 0) entry.duration = parseInt(row.duration);
                    cues[n] = entry;
                }
                await api("POST", "/api/audio/cue_map", { device: this.deviceIdx, cues });
                this.success = "Saved to SD card — will take effect after device reboot";
                setTimeout(() => this.success = null, 5000);
            } catch (e) {
                this.error = e.message;
            } finally {
                this.saving = false;
            }
        },
    };
}
