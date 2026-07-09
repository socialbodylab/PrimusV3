/**
 * cue-map.js — Cue Map editor for Radius nodes.
 *
 * Reads and writes /cues.json on the SD card via FTP.
 * Supports the full cues.h schema: cmd, file, volume, duration, delay.
 */

function cueMap() {
    return {
        deviceIdx: null,
        loading: false,
        loadingFiles: false,
        saving: false,
        oscTarget: "selected",  // "selected" | "all"
        oscFired: {},           // { rowIdx: "sent"|"error" } transient feedback
        rows: [],          // [{ number, cmd, file, volume, duration, delay }]
        deviceFiles: [],   // WAV filenames available on selected device
        error: null,
        success: null,
        audioDevices: [],  // snapshot taken once on init; never reactively updated

        init() {
            this._syncDevices();
            this.$watch("$store.app.mode", (mode) => {
                if (mode === "cue-map") this._syncDevices();
            });
        },

        _syncDevices() {
            this.audioDevices = (Alpine.store("conn").devices || [])
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

        // Only the cue map is fetched on load. The device file listing is a
        // second FTP session — running it in parallel breaks the single-client
        // FTP server on the device (each session also stops the other's
        // server). It is opt-in via loadDeviceFiles(); without it the file
        // column is a free-text input.
        async load() {
            if (this.deviceIdx === null) return;
            this.loading = true;
            this.error = null;
            try {
                const mapData = await api("GET", `/api/audio/cue_map?device=${this.deviceIdx}`);
                this.rows = Object.entries(mapData)
                    .map(([num, val]) => {
                        if (typeof val === "string") {
                            return { number: parseInt(num), cmd: "play", file: val,
                                     volume: null, duration: 0, delay: 0 };
                        }
                        return {
                            number:   parseInt(num),
                            cmd:      val.cmd || "play",
                            file:     val.file || "",
                            volume:   val.volume != null ? val.volume : null,
                            duration: val.duration || 0,
                            delay:    val.delay || 0,
                        };
                    })
                    .sort((a, b) => a.number - b.number);
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },

        async loadDeviceFiles() {
            if (this.deviceIdx === null) return;
            this.loadingFiles = true;
            this.error = null;
            try {
                const filesData = await api("POST", "/api/audio/files",
                                            { device: this.deviceIdx, path: "/" });
                this.deviceFiles = (filesData.entries || [])
                    .filter(e => !e.is_dir && e.name.toLowerCase().endsWith(".wav")
                                          && !e.name.startsWith("._"))
                    .map(e => e.name)
                    .sort((a, b) => a.localeCompare(b));
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loadingFiles = false;
            }
        },

        // Fire the cue over OSC (/cue/N to UDP 53001) — exercises the
        // device's boot-loaded cue map exactly like an external OSC
        // controller would. Note: the device fires what it loaded at boot;
        // a cue map saved since then needs a device reboot first.
        async fireOsc(idx) {
            const row = this.rows[idx];
            if (!row || !row.number) return;
            const device = this.oscTarget === "all" ? "all" : this.deviceIdx;
            this.error = null;
            try {
                await api("POST", "/api/audio/osc_cue",
                          { device, number: parseInt(row.number) });
                this.oscFired = { ...this.oscFired, [idx]: "sent" };
            } catch (e) {
                this.error = e.message;
                this.oscFired = { ...this.oscFired, [idx]: "error" };
            }
            setTimeout(() => {
                const f = { ...this.oscFired };
                delete f[idx];
                this.oscFired = f;
            }, 1500);
        },

        addRow() {
            const maxNum = this.rows.reduce((m, r) => Math.max(m, r.number), 0);
            this.rows.push({ number: Math.min(maxNum + 1, 64), cmd: "play",
                             file: "", volume: null, duration: 0, delay: 0 });
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
                    if (row.delay > 0) entry.delay = parseInt(row.delay);
                    cues[n] = entry;
                }
                await api("POST", "/api/audio/cue_map", { device: this.deviceIdx, cues });
                this.success = "Saved to SD card — device reloads its cue map automatically";
                setTimeout(() => this.success = null, 5000);
            } catch (e) {
                this.error = e.message;
            } finally {
                this.saving = false;
            }
        },
    };
}
