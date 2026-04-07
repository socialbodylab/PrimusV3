/**
 * app.js — Main Alpine.js stores and shared utilities for PrimusV3.1
 */

// ── API helper ──────────────────────────────────────────
function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(r => r.json());
}

// ── Color utilities ─────────────────────────────────────
function rgbToHex(c) {
    return "#" + c.map(v => v.toString(16).padStart(2, "0")).join("");
}
function hexToRgb(hex) {
    const m = hex.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [0, 0, 0];
}

// ── Alpine stores ───────────────────────────────────────
document.addEventListener("alpine:init", () => {

    // --- App store: mode, polling ---
    Alpine.store("app", {
        mode: "designer",
        modes: ["designer", "library", "mixer", "controller"],
        modeLabels: {
            designer: "Clip Designer",
            library: "Clip Library",
            mixer: "Look Mixer",
            controller: "Look Controller",
        },
        state: null,
        polling: null,

        init() {
            this.fetchState();
            this.polling = setInterval(() => this.fetchState(), 66);
        },

        async fetchState() {
            try {
                this.state = await api("GET", "/api/state");
                this._drawPreviews();
            } catch (e) { /* ignore */ }
        },

        _drawPreviews() {
            const outputs = this.state?.look?.outputs;
            if (!outputs) return;
            for (let oi = 0; oi < outputs.length; oi++) {
                const canvas = document.getElementById("preview_" + oi);
                if (!canvas) continue;
                const out = outputs[oi];
                const pixels = out.pixels || [];
                const grid = out.grid;
                const ctx = canvas.getContext("2d");
                if (grid) {
                    const [cols, rows] = grid;
                    canvas.width = cols;
                    canvas.height = rows;
                    ctx.clearRect(0, 0, cols, rows);
                    for (let i = 0; i < pixels.length; i++) {
                        const x = i % cols, y = Math.floor(i / cols);
                        const p = pixels[i] || [0,0,0];
                        ctx.fillStyle = `rgb(${p[0]},${p[1]},${p[2]})`;
                        ctx.fillRect(x, y, 1, 1);
                    }
                } else if (pixels.length > 0) {
                    canvas.width = pixels.length;
                    canvas.height = 1;
                    ctx.clearRect(0, 0, pixels.length, 1);
                    for (let i = 0; i < pixels.length; i++) {
                        const p = pixels[i] || [0,0,0];
                        ctx.fillStyle = `rgb(${p[0]},${p[1]},${p[2]})`;
                        ctx.fillRect(i, 0, 1, 1);
                    }
                }
            }
        },

        setMode(m) {
            this.mode = m;
        },
    });

    // --- Connection store: device management ---
    Alpine.store("conn", {
        discovering: false,
        discovered: [],
        manualIp: "",

        get devices() {
            return Alpine.store("app").state?.devices || [];
        },

        get anyConnected() {
            return this.devices.some(d => d.connected);
        },

        async connect(di) { await api("POST", "/api/connect", { device: di }); },
        async disconnect(di) { await api("POST", "/api/disconnect", { device: di }); },
        async connectAll() { await api("POST", "/api/connect_all"); },
        async disconnectAll() { await api("POST", "/api/disconnect_all"); },

        async discover() {
            this.discovering = true;
            try {
                this.discovered = await api("POST", "/api/discover");
            } finally {
                this.discovering = false;
            }
        },

        async addDiscovered(node) {
            await api("POST", "/api/add_discovered", node);
            this.discovered = this.discovered.filter(n => n.ip !== node.ip);
        },

        async addManualIp() {
            const ip = this.manualIp.trim();
            if (!ip) return;
            await api("POST", "/api/add_manual", { ip });
            this.manualIp = "";
        },

        async removeDevice(di) {
            await api("POST", "/api/remove_device", { device: di });
        },

        async renameDevice(di, name) {
            await api("POST", "/api/rename_node", { device: di, name });
        },
    });
});
