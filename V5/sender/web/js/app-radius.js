/**
 * app.js — Alpine.js stores and shared utilities for Radius Central
 */

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
            const error = new Error(parsed?.error || `API ${r.status}: ${r.statusText}`);
            error.status = r.status;
            error.errorCode = parsed?.error_code || null;
            error.payload = parsed;
            throw error;
        }
        return parsed;
    });
}

document.addEventListener("alpine:init", () => {

    Alpine.store("app", {
        mode: "audio",
        modes: ["audio", "cues", "cue-map", "log", "firmware", "settings"],
        modeLabels: {
            audio: "Audio",
            cues: "Audio Cues",
            "cue-map": "Cue Map",
            log: "Net Log",
            firmware: "Firmware",
            settings: "Settings",
        },
        state: null,
        network: null,
        polling: null,
        networkPolling: null,
        notice: null,
        _noticeTimer: null,
        runtime: null,
        _lifecycleHeartbeat: null,
        product: "radius",
        productMismatch: false,
        _stateFetchGeneration: 0,

        get radiusDevices() {
            // On the shared backend /api/state?product=radius returns the
            // whole unified device list (indices stay aligned); only the
            // is_radius entries belong to this app.
            return (this.state?.devices || []).filter(d => d.is_radius);
        },

        get connectedDeviceSummary() {
            const devices = this.radiusDevices;
            const connected = devices.filter(d => d.connected).length;
            return connected + "/" + devices.length + " nodes";
        },

        get audioStatus() {
            const devices = this.radiusDevices;
            const connected = devices.filter(d => d.connected).length;
            const playing = devices.filter(d => d.connected && d.current_track).length;
            return {
                connected,
                total: devices.length,
                playing,
            };
        },

        init() {
            this.fetchState();
            this.fetchNetworkStatus();
            this.polling = setInterval(() => this.fetchState(), 500);
            this.networkPolling = setInterval(() => this.fetchNetworkStatus(), 15000);
            document.addEventListener("visibilitychange", () => {
                clearInterval(this.polling);
                const interval = document.hidden ? 2000 : 500;
                this.polling = setInterval(() => this.fetchState(), interval);
            });
            this.startRuntimeLifecycle();
        },

        async startRuntimeLifecycle() {
            try {
                if (!this.runtime) {
                    this.runtime = await api("GET", "/api/runtime");
                    this.product = this.runtime?.product || "radius";
                }
            } catch (e) {
                return;
            }
            this._lifecycleHeartbeat = window.PrimusUiLifecycle?.install(api, this.runtime) || null;
        },

        async fetchState() {
            const generation = ++this._stateFetchGeneration;
            try {
                const next = await api("GET", "/api/state?product=radius");
                if (generation !== this._stateFetchGeneration) return;
                this.state = next;
                if (next?.product) this.product = next.product;
                // A backend that does not answer with the radius shape is the
                // silent-attach failure: surface it instead of looking healthy.
                this.productMismatch = !(next && next.product === "radius");
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
            const method = iface.type === "wifi" ? (iface.ssid || "WiFi")
                : iface.type === "ethernet" ? "Ethernet"
                : (iface.service || iface.device || "Network");
            const prefix = iface.is_controller ? "Controller " : "";
            return prefix + method + (iface.source_ip ? " " + iface.source_ip : "");
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
                "network-chip-unavailable": !this.network?.supported || !iface,
                "network-chip-preferred": !!iface?.is_preferred || !!iface?.is_controller,
            };
        },

        audioChipLabel() {
            const status = this.audioStatus;
            if (!status.total) return "No nodes";
            if (status.playing) {
                return status.playing + " playing";
            }
            return status.connected + "/" + status.total + " connected";
        },

        audioChipTitle() {
            const status = this.audioStatus;
            if (!status.total) return "Add Radius nodes from the device sidebar.";
            if (status.playing) {
                return status.playing + " node" + (status.playing === 1 ? "" : "s") + " playing audio.";
            }
            return status.connected + " of " + status.total + " nodes connected.";
        },

        audioChipClass() {
            const status = this.audioStatus;
            return {
                "playback-chip-idle": !status.playing,
                "playback-chip-controller": status.playing > 0,
            };
        },

        showNotice(message, level = "info", timeout = 3200) {
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
            const detail = error?.message ? ": " + error.message : "";
            this.showNotice(action + detail, "error", 5000);
        },

        setMode(m) {
            this.mode = m;
            document.dispatchEvent(new CustomEvent("primus:mode-changed", {
                detail: { mode: m },
            }));
        },
    });
});
