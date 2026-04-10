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
    return fetch(path, opts).then(r => {
        if (!r.ok) throw new Error(`API ${r.status}: ${r.statusText}`);
        return r.json();
    });
}

// ── Color utilities ─────────────────────────────────────
function rgbToHex(c) {
    return "#" + c.map(v => v.toString(16).padStart(2, "0")).join("");
}
function hexToRgb(hex) {
    let h = hex.replace(/^#/, '');
    if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    const m = h.match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [0, 0, 0];
}

// ── Alpine stores ───────────────────────────────────────
document.addEventListener("alpine:init", () => {

    // --- App store: mode, polling ---
    Alpine.store("app", {
        mode: "mixer",
        modes: ["mixer", "controller"],
        modeLabels: {
            mixer: "Look Mixer",
            controller: "Look Controller",
        },
        state: null,
        polling: null,
        mixerPreviewDevices: null,

        init() {
            this.fetchState();
            this.polling = setInterval(() => this.fetchState(), 100);
            document.addEventListener('visibilitychange', () => {
                clearInterval(this.polling);
                const interval = document.hidden ? 1000 : 100;
                this.polling = setInterval(() => this.fetchState(), interval);
            });
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
                    const img = ctx.createImageData(cols, rows);
                    const d = img.data;
                    for (let i = 0; i < pixels.length; i++) {
                        const p = pixels[i] || [0,0,0];
                        const off = i * 4;
                        d[off] = p[0]; d[off+1] = p[1]; d[off+2] = p[2]; d[off+3] = 255;
                    }
                    ctx.putImageData(img, 0, 0);
                } else if (pixels.length > 0) {
                    canvas.width = pixels.length;
                    canvas.height = 1;
                    const img = ctx.createImageData(pixels.length, 1);
                    const d = img.data;
                    for (let i = 0; i < pixels.length; i++) {
                        const p = pixels[i] || [0,0,0];
                        const off = i * 4;
                        d[off] = p[0]; d[off+1] = p[1]; d[off+2] = p[2]; d[off+3] = 255;
                    }
                    ctx.putImageData(img, 0, 0);
                }
            }
        },

        async setMode(m) {
            if (this.mode === 'mixer' && m !== 'mixer') {
                await api("POST", "/api/mixer/stop_preview");
                await api("POST", "/api/set_playback_source", { source: "idle" });
            }
            this.mode = m;
        },

        toggleMixerDevice(di) {
            if (!this.mixerPreviewDevices) {
                const count = (this.state?.devices || []).length;
                const all = Array.from({length: count}, (_, i) => i);
                this.mixerPreviewDevices = all.filter(i => i !== di);
            } else if (this.mixerPreviewDevices.includes(di)) {
                this.mixerPreviewDevices = this.mixerPreviewDevices.filter(i => i !== di);
            } else {
                this.mixerPreviewDevices = [...this.mixerPreviewDevices, di];
            }
        },
    });

    // --- Connection store: device management ---
    Alpine.store("conn", {
        discovering: false,
        discovered: [],
        manualIp: "",
        renamingDevice: -1,
        renameValue: "",
        groupModal: false,
        editGroup: null,
        editGroupName: "",
        editGroupIps: [],

        get devices() {
            return Alpine.store("app").state?.devices || [];
        },

        get deviceGroups() {
            return Alpine.store("app").state?.device_groups || [];
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

        startRename(di) {
            this.renamingDevice = di;
            this.renameValue = this.devices[di]?.name || "";
        },

        async finishRename(di) {
            const name = this.renameValue.trim();
            if (name && name !== this.devices[di]?.name) {
                await api("POST", "/api/rename_node", { device: di, name });
            }
            this.renamingDevice = -1;
            this.renameValue = "";
        },

        cancelRename() {
            this.renamingDevice = -1;
            this.renameValue = "";
        },

        async renameDevice(di, name) {
            await api("POST", "/api/rename_node", { device: di, name });
        },

        // -- Device groups --
        openNewGroup() {
            this.editGroup = null;
            this.editGroupName = "";
            this.editGroupIps = [];
            this.groupModal = true;
        },

        openEditGroup(group) {
            this.editGroup = group;
            this.editGroupName = group.name;
            this.editGroupIps = [...group.device_ips];
            this.groupModal = true;
        },

        toggleGroupIp(ip) {
            if (this.editGroupIps.includes(ip)) {
                this.editGroupIps = this.editGroupIps.filter(i => i !== ip);
            } else {
                this.editGroupIps.push(ip);
            }
        },

        async saveGroup() {
            const group = {
                id: this.editGroup?.id || crypto.randomUUID(),
                name: this.editGroupName.trim() || "Untitled Group",
                device_ips: this.editGroupIps,
            };
            await api("POST", "/api/device_groups", group);
            this.groupModal = false;
        },

        async deleteGroup(gid) {
            await api("DELETE", "/api/device_groups/" + gid);
        },

        async connectGroup(group) {
            for (let di = 0; di < this.devices.length; di++) {
                if (group.device_ips.includes(this.devices[di].ip) && !this.devices[di].connected) {
                    await api("POST", "/api/connect", { device: di });
                }
            }
        },

        async disconnectGroup(group) {
            for (let di = 0; di < this.devices.length; di++) {
                if (group.device_ips.includes(this.devices[di].ip) && this.devices[di].connected) {
                    await api("POST", "/api/disconnect", { device: di });
                }
            }
        },
    });
});
