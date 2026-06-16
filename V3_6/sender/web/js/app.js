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

    const _cfg = window.PAGE_CONFIG || {};
    const _defaultModes = ["mixer", "controller", "firmware", "settings"];
    const _defaultLabels = {
        mixer: "Look Designer",
        controller: "Cue Controller",
        firmware: "Firmware",
        settings: "Settings",
    };

    // --- App store: mode, polling ---
    Alpine.store("app", {
        mode: (_cfg.modes || _defaultModes)[0],
        modes: _cfg.modes || _defaultModes,
        modeLabels: _cfg.modeLabels || _defaultLabels,
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
            } catch (e) {
                return;
            }
            if (!this.runtime?.ui_lifecycle) return;

            const heartbeat = () => {
                // #region agent log
                fetch('http://127.0.0.1:7695/ingest/abbd0204-dcc0-4721-9f61-f71dfdc607c5', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'f67d00' },
                    body: JSON.stringify({
                        sessionId: 'f67d00',
                        location: 'app.js:heartbeat',
                        message: 'ui heartbeat sent',
                        data: { hidden: document.hidden },
                        timestamp: Date.now(),
                        hypothesisId: 'H5',
                    }),
                }).catch(() => {});
                // #endregion
                api("POST", "/api/ui/heartbeat", {}).catch(() => {});
            };
            heartbeat();
            this._lifecycleHeartbeat = setInterval(heartbeat, 2000);

            document.addEventListener('visibilitychange', () => {
                // #region agent log
                fetch('http://127.0.0.1:7695/ingest/abbd0204-dcc0-4721-9f61-f71dfdc607c5', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'f67d00' },
                    body: JSON.stringify({
                        sessionId: 'f67d00',
                        location: 'app.js:visibilitychange',
                        message: 'visibility changed',
                        data: { hidden: document.hidden },
                        timestamp: Date.now(),
                        hypothesisId: 'H5',
                    }),
                }).catch(() => {});
                // #endregion
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
        ipConfigDevice: -1,
        ipConfigIp: "",
        ipConfigGateway: "",
        ipConfigSubnet: "255.255.255.0",
        _ipRediscoveryTimer: null,
        _ipRediscoveryUntil: 0,
        sidebarCollapsed: false,

        get devices() {
            return Alpine.store("app").state?.devices || [];
        },

        get deviceGroups() {
            return Alpine.store("app").state?.device_groups || [];
        },

        get anyConnected() {
            return this.devices.some(d => d.connected);
        },

        canRenameDevice(dev) {
            return !!dev?.capabilities?.rename;
        },

        canHelloDevice(dev) {
            return !!dev?.capabilities?.hello;
        },

        canConfigureIp(dev) {
            return !!dev?.capabilities?.ip_config;
        },

        hardwareLabel(entity) {
            const label = entity?.hardware_label || entity?.hardware_profile || 'Unknown hardware';
            return String(label).replace('V3.1', 'V3');
        },

        capabilityItems(entity) {
            const caps = entity?.capabilities || {};
            return [
                { key: 'rename', label: 'Rename', supported: !!caps.rename },
                { key: 'hello', label: 'Hello', supported: !!caps.hello },
                { key: 'ip_config', label: 'IP', supported: !!caps.ip_config },
                { key: 'output_config', label: 'Outputs', supported: !!caps.output_config },
            ];
        },

        capabilityStatusLabel(entity) {
            const caps = entity?.capabilities || {};
            const supportedCount = this.capabilityItems(entity).filter(item => item.supported).length;
            if (caps.known) return 'Advertised';
            if (supportedCount > 0) return 'Legacy fallback';
            return 'Not advertised';
        },

        capabilityStatusClass(entity) {
            const caps = entity?.capabilities || {};
            const supportedCount = this.capabilityItems(entity).filter(item => item.supported).length;
            if (caps.known) return 'device-capability-status-advertised';
            if (supportedCount > 0) return 'device-capability-status-legacy';
            return 'device-capability-status-missing';
        },

        renameHint(dev) {
            return this.canRenameDevice(dev)
                ? 'Click to rename'
                : 'Remote rename is not advertised for this node';
        },

        helloHint(dev) {
            return this.canHelloDevice(dev)
                ? 'Send identify flash'
                : 'Identify flash is not advertised for this node';
        },

        ipConfigHint(dev) {
            return this.canConfigureIp(dev)
                ? 'Configure static or DHCP IP settings'
                : 'Remote IP configuration is not advertised for this node';
        },

        networkModeLabel(dev) {
            if (dev?.ip_config_pending === 'static') return 'Restart for static';
            if (dev?.ip_config_pending === 'dhcp') return 'Restart for DHCP';
            if (dev?.ip_mode === 'static') return 'Static';
            if (dev?.ip_mode === 'dhcp') return 'DHCP';
            return 'IP Unknown';
        },

        networkModeClass(dev) {
            return {
                'device-network-static': dev?.ip_mode === 'static' && !dev?.ip_config_pending,
                'device-network-dhcp': dev?.ip_mode === 'dhcp' && !dev?.ip_config_pending,
                'device-network-pending': !!dev?.ip_config_pending,
                'device-network-unknown': !dev?.ip_config_pending && dev?.ip_mode !== 'static' && dev?.ip_mode !== 'dhcp',
            };
        },

        networkModeTitle(dev) {
            if (dev?.ip_config_pending === 'static') return 'Restart this receiver; Primus will automatically pick up the static IP when it comes back online.';
            if (dev?.ip_config_pending === 'dhcp') return 'Restart this receiver; Primus will automatically pick up the DHCP address when it comes back online.';
            if (dev?.ip_mode === 'static') return 'Static IP' + (dev.static_ip ? ': ' + dev.static_ip : '');
            if (dev?.ip_mode === 'dhcp') return 'DHCP assigned address';
            return 'This receiver has not reported DHCP/static mode yet.';
        },

        hasPendingIpConfig() {
            return this.devices.some(dev => !!dev.ip_config_pending);
        },

        isKnownDiscoveryNode(node) {
            return this.devices.some(dev => dev.ip === node.ip);
        },

        filterNewDiscoveryNodes(nodes) {
            return (nodes || []).filter(node => !this.isKnownDiscoveryNode(node));
        },

        isIpv4(value) {
            const parts = String(value || '').trim().split('.');
            return parts.length === 4 && parts.every(part => {
                if (!/^\d+$/.test(part)) return false;
                const octet = Number(part);
                return octet >= 0 && octet <= 255;
            });
        },

        scheduleRediscovery() {
            if (this._ipRediscoveryTimer) clearTimeout(this._ipRediscoveryTimer);
            this._ipRediscoveryUntil = Date.now() + 90000;
            this.queueIpRediscovery(3000);
        },

        queueIpRediscovery(delay = 4000) {
            if (this._ipRediscoveryTimer) clearTimeout(this._ipRediscoveryTimer);
            this._ipRediscoveryTimer = setTimeout(() => this.runIpRediscovery(), delay);
        },

        async runIpRediscovery() {
            this._ipRediscoveryTimer = null;
            if (!this.hasPendingIpConfig()) return;
            try {
                const nodes = await api("POST", "/api/discover");
                await Alpine.store("app").fetchState();
                this.discovered = this.filterNewDiscoveryNodes(nodes);
                if (this.hasPendingIpConfig() && Date.now() < this._ipRediscoveryUntil) {
                    this.queueIpRediscovery(4000);
                    return;
                }
                if (!this.hasPendingIpConfig()) {
                    Alpine.store("app").showNotice('Network settings refreshed from receiver discovery.', 'success', 3200);
                } else {
                    Alpine.store("app").showNotice('Still waiting for the receiver to restart and report its new IP settings.', 'warn', 5000);
                }
            } catch (e) {
                if (Date.now() < this._ipRediscoveryUntil) {
                    this.queueIpRediscovery(5000);
                }
            }
        },

        async connect(di) {
            try {
                await api("POST", "/api/connect", { device: di });
            } catch (e) {
                Alpine.store("app").showApiError('Connect failed', e);
            }
        },
        async disconnect(di) { await api("POST", "/api/disconnect", { device: di }); },
        async connectAll() {
            try {
                await api("POST", "/api/connect_all");
            } catch (e) {
                Alpine.store("app").showApiError('Connect all failed', e);
            }
        },
        async disconnectAll() { await api("POST", "/api/disconnect_all"); },

        async helloDevice(di) {
            try {
                await api("POST", "/api/hello_device", { device: di });
                Alpine.store("app").requestLookPreviewFromHello(di);
            } catch (e) {
                Alpine.store("app").showApiError('Hello failed', e);
            }
        },

        async discover() {
            this.discovering = true;
            try {
                const nodes = await api("POST", "/api/discover");
                await Alpine.store("app").fetchState();
                this.discovered = this.filterNewDiscoveryNodes(nodes);
                const count = this.discovered.length;
                const total = nodes.length;
                Alpine.store("app").showNotice(
                    count
                        ? 'Discovery found ' + count + ' new device' + (count === 1 ? '' : 's') + '.'
                        : total
                        ? 'Discovery refreshed ' + total + ' known device' + (total === 1 ? '' : 's') + '.'
                        : 'Discovery finished with no devices found.',
                    count ? 'success' : 'info'
                );
            } catch (e) {
                Alpine.store("app").showApiError('Discovery failed', e);
            } finally {
                this.discovering = false;
            }
        },

        async addDiscovered(node) {
            try {
                const result = await api("POST", "/api/add_discovered", node);
                this.discovered = this.discovered.filter(n => n.ip !== node.ip);
                const added = result?.status === 'added';
                Alpine.store("app").showNotice(
                    result?.connect_error
                        ? 'Added ' + (node.short_name || node.ip) + ', but connect failed: ' + result.connect_error
                        : added
                        ? 'Added ' + (node.short_name || node.ip) + '.'
                        : (node.short_name || node.ip) + ' is already in the device list.',
                    result?.connect_error ? 'warn' : (added ? 'success' : 'info')
                );
            } catch (e) {
                Alpine.store("app").showApiError('Could not add discovered device', e);
            }
        },

        async addManualIp() {
            const ip = this.manualIp.trim();
            if (!ip) return;
            try {
                const result = await api("POST", "/api/add_manual", { ip });
                Alpine.store("app").showNotice(
                    result?.connect_error
                        ? 'Added device at ' + ip + ', but connect failed: ' + result.connect_error
                        : result?.status === 'added'
                        ? 'Added device at ' + ip + '.'
                        : 'Device ' + ip + ' is already in the list.',
                    result?.connect_error ? 'warn' : (result?.status === 'added' ? 'success' : 'info')
                );
                this.manualIp = "";
            } catch (e) {
                Alpine.store("app").showApiError('Could not add manual device', e);
            }
        },

        async removeDevice(di) {
            await api("POST", "/api/remove_device", { device: di });
        },

        startRename(di) {
            const dev = this.devices[di];
            if (!this.canRenameDevice(dev)) {
                Alpine.store("app").showNotice(this.renameHint(dev), 'info');
                return;
            }
            this.renamingDevice = di;
            this.renameValue = dev?.name || "";
        },

        async finishRename(di) {
            const name = this.renameValue.trim();
            const oldName = this.devices[di]?.name || 'device';
            if (name && name !== oldName) {
                try {
                    await api("POST", "/api/rename_node", { device: di, name });
                    Alpine.store("app").showNotice('Renamed ' + oldName + ' to ' + name + '.', 'success');
                } catch (e) {
                    Alpine.store("app").showApiError('Rename failed', e);
                    return;
                }
            }
            this.renamingDevice = -1;
            this.renameValue = "";
        },

        cancelRename() {
            this.renamingDevice = -1;
            this.renameValue = "";
        },

        async renameDevice(di, name) {
            try {
                await api("POST", "/api/rename_node", { device: di, name });
                Alpine.store("app").showNotice('Renamed device to ' + name + '.', 'success');
            } catch (e) {
                Alpine.store("app").showApiError('Rename failed', e);
            }
        },

        // -- Static IP config --
        openIpConfig(di) {
            const dev = this.devices[di];
            if (!this.canConfigureIp(dev)) {
                Alpine.store("app").showNotice(this.ipConfigHint(dev), 'info');
                return;
            }
            this.ipConfigDevice = di;
            this.ipConfigIp = dev?.static_ip || dev?.ip || "";
            this.ipConfigGateway = dev?.gateway || (dev?.ip ? dev.ip.replace(/\.\d+$/, ".1") : "");
            this.ipConfigSubnet = dev?.subnet || "255.255.255.0";
        },

        closeIpConfig() {
            this.ipConfigDevice = -1;
        },

        async setStaticIp(di) {
            const ip = this.ipConfigIp.trim();
            const gw = this.ipConfigGateway.trim();
            const sn = this.ipConfigSubnet.trim();
            const name = this.devices[di]?.name || 'device';
            if (!ip || !gw || !sn) {
                Alpine.store("app").showNotice('Enter IP, gateway, and subnet before applying a static IP.', 'warn');
                return;
            }
            if (!this.isIpv4(ip) || !this.isIpv4(gw) || !this.isIpv4(sn)) {
                Alpine.store("app").showNotice('Static IP, gateway, and subnet must be valid IPv4 addresses.', 'warn');
                return;
            }
            try {
                await api("POST", "/api/set_device_ip", { device: di, ip: ip, gateway: gw, subnet: sn });
                Alpine.store("app").showNotice('Restart ' + name + '; Primus will pick up static IP ' + ip + ' automatically when it comes back online.', 'warn', 7000);
                this.ipConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError('Static IP update failed', e);
            }
        },

        async revertDhcp(di) {
            const name = this.devices[di]?.name || 'device';
            try {
                await api("POST", "/api/revert_device_dhcp", { device: di });
                Alpine.store("app").showNotice('Restart ' + name + '; Primus will pick up its DHCP address automatically when it comes back online.', 'warn', 7000);
                this.ipConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError('DHCP revert failed', e);
            }
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
