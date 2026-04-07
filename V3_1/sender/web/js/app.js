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
            this.polling = setInterval(() => this.fetchState(), 200);
        },

        async fetchState() {
            try {
                this.state = await api("GET", "/api/state");
            } catch (e) { /* ignore */ }
        },

        setMode(m) {
            this.mode = m;
        },
    });

    // --- Connection store: device management ---
    Alpine.store("conn", {
        discovering: false,
        discovered: [],

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

        async removeDevice(di) {
            await api("POST", "/api/remove_device", { device: di });
        },

        async renameDevice(di, name) {
            await api("POST", "/api/rename_node", { device: di, name });
        },
    });
});
