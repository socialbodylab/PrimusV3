/**
 * audio-panel.js — Audio Panel Alpine component for PrimusV3.1
 * Manages WAV playback on V3.2 audio nodes via /api/audio/cmd and /api/audio/files.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("audioPanel", () => ({
        fileCache:    {},   // { di: ["cue01.wav", ...] }  undefined = not loaded
        loadingFiles: {},   // { di: true/false }
        playing:      {},   // { di: { file, cmd } }  optimistic
        volume:       {},   // { di: 0-100 }  default 80
        _lastVolSent: {},

        get audioDevices() {
            const devices = Alpine.store("app").state?.devices || [];
            return devices.map((d, i) => ({ ...d, di: i })).filter(d => d.is_audio);
        },

        getVolume(di) {
            return this.volume[di] ?? 80;
        },

        async loadFiles(di) {
            this.loadingFiles = { ...this.loadingFiles, [di]: true };
            try {
                const result = await api("POST", "/api/audio/files", { device: di });
                this.fileCache = { ...this.fileCache, [di]: result.files };
            } catch(e) {
                console.error("[audio] failed to load files:", e);
            } finally {
                this.loadingFiles = { ...this.loadingFiles, [di]: false };
            }
        },

        async refreshFiles(di) {
            const cache = { ...this.fileCache };
            delete cache[di];
            this.fileCache = cache;
            await this.loadFiles(di);
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
            this.volume = { ...this.volume, [di]: vol };
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
    }));

});
