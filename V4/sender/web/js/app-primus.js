/**
 * app.js — Main Alpine.js stores and shared utilities for Primus Central
 */

// ── API helper ──────────────────────────────────────────
function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(async r => {
        const text = await r.text();
        let parsed = null;
        if (text) {
            try {
                parsed = JSON.parse(text);
            } catch {
                parsed = null;
            }
        }
        if (!r.ok) {
            throw new Error(parsed?.error || `API ${r.status}: ${r.statusText}`);
        }
        return parsed;
    });
}

const PRIMUS_UI_PROFILES = {
    workshop: {
        name: "Workshop",
        outputTypes: ["none", "small_grid", "long_strip", "extra_long_strip"],
        defaultOutputs: ["small_grid", "long_strip"],
        outputTypeLabels: {
            none: "None",
            small_grid: "Badge",
            long_strip: "Collar",
            extra_long_strip: "Belt",
        },
        // Existing Collar clips may still be saved as short_strip (30 px).
        clipOutputTypeAliases: {
            long_strip: ["short_strip"],
        },
    },
    full: {
        name: "Full",
        outputTypes: null,
        defaultOutputs: ["short_strip", "long_strip"],
        outputTypeLabels: {},
    },
};

function initialUiProfileKey() {
    const fallback = "workshop";
    try {
        const params = new URLSearchParams(window.location.search);
        const requested = (params.get("ui") || params.get("profile") || "").toLowerCase();
        if (PRIMUS_UI_PROFILES[requested]) {
            window.localStorage.setItem("primusUiProfile", requested);
            return requested;
        }
        const stored = (window.localStorage.getItem("primusUiProfile") || "").toLowerCase();
        if (PRIMUS_UI_PROFILES[stored]) return stored;
    } catch {
        return fallback;
    }
    return fallback;
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
        modes: ["mixer", "controller", "firmware", "settings"],
        modeLabels: {
            mixer: "Look Designer",
            controller: "Cue Controller",
            firmware: "Firmware",
            settings: "Settings",
        },
        state: null,
        network: null,
        polling: null,
        networkPolling: null,
        mixerPreviewDevices: null,
        notice: null,
        _noticeTimer: null,
        runtime: null,
        _lifecycleHeartbeat: null,
        uiProfileKey: initialUiProfileKey(),
        product: "primus",

        get uiProfile() {
            return PRIMUS_UI_PROFILES[this.uiProfileKey] || PRIMUS_UI_PROFILES.workshop;
        },

        get outputTypes() {
            return this.visibleOutputTypes(this.state?.look_output_types || []);
        },

        visibleOutputTypes(types) {
            const source = Array.isArray(types) ? types : [];
            const allowed = this.uiProfile.outputTypes;
            if (!Array.isArray(allowed)) return source;
            return source.filter(type => allowed.includes(type));
        },

        isOutputTypeVisible(type) {
            const allowed = this.uiProfile.outputTypes;
            return !Array.isArray(allowed) || allowed.includes(type);
        },

        clipOutputTypesFor(type) {
            const aliases = this.uiProfile.clipOutputTypeAliases?.[type];
            if (!Array.isArray(aliases) || !aliases.length) return [type];
            return [type, ...aliases.filter(item => item !== type)];
        },

        clipMatchesOutputType(clipType, type) {
            if (!clipType || !type) return false;
            return this.clipOutputTypesFor(type).includes(clipType);
        },

        defaultOutputType(index, currentType = null) {
            if (currentType && this.isOutputTypeVisible(currentType)) return currentType;
            const preferred = this.uiProfile.defaultOutputs?.[index];
            if (preferred && this.isOutputTypeVisible(preferred)) return preferred;
            return this.outputTypes.find(type => type !== "none") || "none";
        },

        setUiProfile(key) {
            if (!PRIMUS_UI_PROFILES[key]) return;
            this.uiProfileKey = key;
            try {
                window.localStorage.setItem("primusUiProfile", key);
            } catch { /* ignore */ }
            document.dispatchEvent(new CustomEvent("primus:ui-profile-changed", {
                detail: { profile: key },
            }));
        },

        get playback() {
            return this.state?.playback || {
                source: "idle",
                label: "Idle",
                activity: "No output",
                target_label: "No output",
                summary: "No output",
                detail: "No live source currently owns output.",
            };
        },

        get connectedDeviceSummary() {
            const devices = this.state?.devices || [];
            const connected = devices.filter(d => d.connected).length;
            return connected + "/" + devices.length + " devices";
        },

        outputLabel(value, idx = null) {
            const raw = value == null ? "" : String(value);
            const match = raw.match(/^A(\d+)$/i);
            if (match) return "Output " + match[1];
            if (raw) return raw;
            return Number.isInteger(idx) ? "Output " + idx : "Output";
        },

        outputTypeLabel(type) {
            const profileLabel = this.uiProfile.outputTypeLabels?.[type];
            if (profileLabel) return profileLabel;
            const labels = {
                none: "None",
                short_strip: "Short Strip",
                long_strip: "Long Strip",
                grid: "Grid",
                small_grid: "Small Grid",
                extra_long_strip: "Extra Long Strip",
            };
            if (labels[type]) return labels[type];
            if (!type) return "None";
            return String(type).split("_")
                .map(part => part.charAt(0).toUpperCase() + part.slice(1))
                .join(" ");
        },

        get mixerPreviewTarget() {
            const devices = this.state?.devices || [];
            const total = devices.length;
            const connectedTotal = devices.filter(d => d.connected).length;
            if (!total) {
                return {
                    scope: 'none',
                    selectedCount: 0,
                    connectedCount: 0,
                    label: 'No devices available',
                };
            }
            if (!this.mixerPreviewDevices) {
                return {
                    scope: 'all',
                    selectedCount: total,
                    connectedCount: connectedTotal,
                    label: connectedTotal === total
                        ? 'All devices'
                        : 'All devices (' + connectedTotal + '/' + total + ' connected)',
                };
            }
            const selected = this.mixerPreviewDevices
                .filter(i => i >= 0 && i < total);
            const connected = selected.filter(i => devices[i]?.connected).length;
            if (!selected.length) {
                return {
                    scope: 'none',
                    selectedCount: 0,
                    connectedCount: 0,
                    label: 'No preview targets selected',
                };
            }
            const base = selected.length === 1
                ? '1 selected device'
                : selected.length + ' selected devices';
            return {
                scope: 'selected',
                selectedCount: selected.length,
                connectedCount: connected,
                label: connected === selected.length
                    ? base
                    : base + ' (' + connected + '/' + selected.length + ' connected)',
            };
        },

        init() {
            this.fetchState();
            this.fetchNetworkStatus();
            this.polling = setInterval(() => this.fetchState(), 100);
            this.networkPolling = setInterval(() => this.fetchNetworkStatus(), 15000);
            document.addEventListener('visibilitychange', () => {
                clearInterval(this.polling);
                const interval = document.hidden ? 1000 : 100;
                this.polling = setInterval(() => this.fetchState(), interval);
            });
            this.startRuntimeLifecycle();
        },

        async startRuntimeLifecycle() {
            try {
                this.runtime = await api("GET", "/api/runtime");
                this.product = this.runtime?.product || "primus";
            } catch (e) {
                return;
            }
            if (!this.runtime?.ui_lifecycle) return;

            const heartbeat = () => {
                api("POST", "/api/ui/heartbeat", {}).catch(() => {});
            };
            heartbeat();
            this._lifecycleHeartbeat = setInterval(heartbeat, 2000);

            document.addEventListener('visibilitychange', () => {
                if (!document.hidden) heartbeat();
            });

            window.addEventListener('pagehide', () => {
                if (this._lifecycleHeartbeat) {
                    clearInterval(this._lifecycleHeartbeat);
                    this._lifecycleHeartbeat = null;
                }
                const payload = JSON.stringify({ reason: 'pagehide' });
                if (navigator.sendBeacon) {
                    const body = new Blob([payload], { type: 'application/json' });
                    navigator.sendBeacon('/api/ui/closed', body);
                } else {
                    fetch('/api/ui/closed', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: payload,
                        keepalive: true,
                    }).catch(() => {});
                }
            }, { once: true });
        },

        async fetchState() {
            try {
                this.state = await api("GET", "/api/state");
                this._drawPreviews();
            } catch (e) { /* ignore */ }
        },

        async fetchNetworkStatus() {
            try {
                this.network = await api("GET", "/api/network/status");
                return this.network;
            } catch (e) {
                return this.network;
            }
        },

        networkPrimaryInterface() {
            const net = this.network || {};
            return net.selected_interface
                || (net.interfaces || []).find(item => item.is_default)
                || (net.interfaces || []).find(item => item.connected)
                || null;
        },

        networkChipLabel() {
            if (!this.network) return "Network";
            if (!this.network.supported) return "Network unsupported";
            const iface = this.networkPrimaryInterface();
            if (!iface) return "No sender IP";
            const method = iface.type === 'wifi' ? (iface.ssid || 'WiFi')
                : iface.type === 'ethernet' ? 'Ethernet'
                : (iface.service || iface.device || 'Network');
            const prefix = iface.is_controller ? 'Controller ' : '';
            return prefix + method + (iface.source_ip ? ' ' + iface.source_ip : '');
        },

        networkChipTitle() {
            const iface = this.networkPrimaryInterface();
            if (!this.network) return "Open network settings";
            if (!this.network.supported) return this.network.warnings?.[0] || "Host network switching is unavailable.";
            if (!iface) return "No active sender connection found.";
            const parts = [iface.service || iface.device || "Network"];
            if (iface.ssid) parts.push("SSID " + iface.ssid);
            if (iface.source_ip) parts.push("IP " + iface.source_ip);
            if (iface.is_controller) parts.push("controller network");
            if (iface.is_preferred) parts.push("preferred for Art-Net");
            else if (iface.is_default) parts.push("default route");
            return parts.join(" · ");
        },

        networkChipClass() {
            const iface = this.networkPrimaryInterface();
            return {
                'network-chip-unavailable': !this.network?.supported || !iface,
                'network-chip-preferred': !!iface?.is_preferred || !!iface?.is_controller,
            };
        },

        showNotice(message, level = 'info', timeout = 3200) {
            if (this._noticeTimer) {
                clearTimeout(this._noticeTimer);
                this._noticeTimer = null;
            }
            this.notice = { message, level };
            if (timeout > 0) {
                this._noticeTimer = setTimeout(() => {
                    this.notice = null;
                    this._noticeTimer = null;
                }, timeout);
            }
        },

        clearNotice() {
            if (this._noticeTimer) {
                clearTimeout(this._noticeTimer);
                this._noticeTimer = null;
            }
            this.notice = null;
        },

        showApiError(action, error) {
            const detail = error?.message ? ': ' + error.message : '';
            this.showNotice(action + detail, 'error', 5000);
        },

        _drawPreviews() {
            const outputs = this.state?.look?.outputs;
            if (!outputs) return;
            for (let oi = 0; oi < outputs.length; oi++) {
                const out = outputs[oi];
                const pixels = out.pixels || [];
                const grid = out.grid;
                const canvas = document.getElementById("preview_" + oi);
                if (!canvas) continue;
                if (pixels.length === 0) continue;
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
            document.dispatchEvent(new CustomEvent('primus:mode-changed', {
                detail: { mode: m },
            }));
        },

        playbackClass() {
            switch (this.playback.source) {
            case 'designer':
                return 'playback-chip-designer';
            case 'mixer':
                return 'playback-chip-mixer';
            case 'controller':
                return 'playback-chip-controller';
            default:
                return 'playback-chip-idle';
            }
        },

        async toggleMixerDevice(di) {
            if (!this.mixerPreviewDevices) {
                const count = (this.state?.devices || []).length;
                const all = Array.from({length: count}, (_, i) => i);
                this.mixerPreviewDevices = all.filter(i => i !== di);
            } else if (this.mixerPreviewDevices.includes(di)) {
                this.mixerPreviewDevices = this.mixerPreviewDevices.filter(i => i !== di);
            } else {
                this.mixerPreviewDevices = [...this.mixerPreviewDevices, di];
            }
            if (this.playback.source === 'mixer') {
                try {
                    await api("POST", "/api/mixer/update", {
                        device_filter: this.mixerPreviewDevices,
                    });
                } catch (e) {
                    this.showApiError('Preview target update failed', e);
                    return;
                }
            }
            this.showNotice('Preview target: ' + this.mixerPreviewTarget.label, 'info', 2000);
        },

        async setMixerPreviewAll() {
            this.mixerPreviewDevices = null;
            if (this.playback.source === 'mixer') {
                try {
                    await api("POST", "/api/mixer/update", {
                        device_filter: null,
                    });
                } catch (e) {
                    this.showApiError('Preview target update failed', e);
                    return;
                }
            }
            this.showNotice('Preview target: ' + this.mixerPreviewTarget.label, 'info', 2000);
        },

        requestLookPreviewFromHello(di) {
            if (this.mode !== 'mixer') return;
            document.dispatchEvent(new CustomEvent('primus:hello-preview', {
                detail: { device: di },
            }));
        },
    });
});
