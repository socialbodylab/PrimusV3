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
            throw new Error(parsed?.error || `API ${r.status}: ${r.statusText}`);
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

        get connectedDeviceSummary() {
            const devices = this.state?.devices || [];
            const connected = devices.filter(d => d.connected).length;
            return connected + "/" + devices.length + " nodes";
        },

        get audioStatus() {
            const devices = this.state?.devices || [];
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
                }
            } catch (e) {
                return;
            }
            this._lifecycleHeartbeat = window.PrimusUiLifecycle?.install(api, this.runtime) || null;
        },

        async fetchState() {
            try {
                this.state = await api("GET", "/api/state");
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

    Alpine.store("conn", {
        discovering: false,
        discovered: [],
        manualIp: "",
        renamingDevice: -1,
        renameValue: "",
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

        get anyConnected() {
            return this.devices.some(d => d.connected);
        },

        canRenameDevice(dev) {
            return !!dev?.capabilities?.rename;
        },

        canConfigureIp(dev) {
            return !!dev?.capabilities?.ip_config;
        },

        hardwareLabel(entity) {
            return entity?.hardware_label || entity?.hardware_profile || "Radius V1";
        },

        capabilityItems(entity) {
            const caps = entity?.capabilities || {};
            return [
                { key: "rename", label: "Rename", supported: !!caps.rename },
                { key: "ip_config", label: "IP", supported: !!caps.ip_config },
            ];
        },

        capabilityStatusLabel(entity) {
            const caps = entity?.capabilities || {};
            const supportedCount = this.capabilityItems(entity).filter(item => item.supported).length;
            if (caps.known) return "Advertised";
            if (supportedCount > 0) return "Legacy fallback";
            return "Not advertised";
        },

        capabilityStatusClass(entity) {
            const caps = entity?.capabilities || {};
            const supportedCount = this.capabilityItems(entity).filter(item => item.supported).length;
            if (caps.known) return "device-capability-status-advertised";
            if (supportedCount > 0) return "device-capability-status-legacy";
            return "device-capability-status-missing";
        },

        renameHint(dev) {
            return this.canRenameDevice(dev)
                ? "Click to rename"
                : "Remote rename is not advertised for this node";
        },

        ipConfigHint(dev) {
            return this.canConfigureIp(dev)
                ? "Configure static or DHCP IP settings"
                : "Remote IP configuration is not advertised for this node";
        },

        networkModeLabel(dev) {
            if (dev?.ip_config_pending === "static") return "Restart for static";
            if (dev?.ip_config_pending === "dhcp") return "Restart for DHCP";
            if (dev?.ip_mode === "static") return "Static";
            if (dev?.ip_mode === "dhcp") return "DHCP";
            return "IP Unknown";
        },

        networkModeClass(dev) {
            return {
                "device-network-static": dev?.ip_mode === "static" && !dev?.ip_config_pending,
                "device-network-dhcp": dev?.ip_mode === "dhcp" && !dev?.ip_config_pending,
                "device-network-pending": !!dev?.ip_config_pending,
                "device-network-unknown": !dev?.ip_config_pending && dev?.ip_mode !== "static" && dev?.ip_mode !== "dhcp",
            };
        },

        networkModeTitle(dev) {
            if (dev?.ip_config_pending === "static") {
                return "Restart this receiver; Radius Central will automatically pick up the static IP when it comes back online.";
            }
            if (dev?.ip_config_pending === "dhcp") {
                return "Restart this receiver; Radius Central will automatically pick up the DHCP address when it comes back online.";
            }
            if (dev?.ip_mode === "static") return "Static IP" + (dev.static_ip ? ": " + dev.static_ip : "");
            if (dev?.ip_mode === "dhcp") return "DHCP assigned address";
            return "This receiver has not reported DHCP/static mode yet.";
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
            const parts = String(value || "").trim().split(".");
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
                    Alpine.store("app").showNotice("Network settings refreshed from receiver discovery.", "success", 3200);
                } else {
                    Alpine.store("app").showNotice("Still waiting for the receiver to restart and report its new IP settings.", "warn", 5000);
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
                await Alpine.store("app").fetchState();
            } catch (e) {
                Alpine.store("app").showApiError("Connect failed", e);
            }
        },

        async disconnect(di) {
            await api("POST", "/api/disconnect", { device: di });
            await Alpine.store("app").fetchState();
        },

        async connectAll() {
            try {
                await api("POST", "/api/connect_all");
                await Alpine.store("app").fetchState();
            } catch (e) {
                Alpine.store("app").showApiError("Connect all failed", e);
            }
        },

        async disconnectAll() {
            await api("POST", "/api/disconnect_all");
            await Alpine.store("app").fetchState();
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
                        ? "Discovery found " + count + " new node" + (count === 1 ? "" : "s") + "."
                        : total
                        ? "Discovery refreshed " + total + " known node" + (total === 1 ? "" : "s") + "."
                        : "Discovery finished with no nodes found.",
                    count ? "success" : "info"
                );
            } catch (e) {
                Alpine.store("app").showApiError("Discovery failed", e);
            } finally {
                this.discovering = false;
            }
        },

        async addDiscovered(node) {
            try {
                const result = await api("POST", "/api/add_discovered", node);
                this.discovered = this.discovered.filter(n => n.ip !== node.ip);
                await Alpine.store("app").fetchState();
                const added = result?.status === "added";
                Alpine.store("app").showNotice(
                    result?.connect_error
                        ? "Added " + (node.short_name || node.ip) + ", but connect failed: " + result.connect_error
                        : added
                        ? "Added " + (node.short_name || node.ip) + "."
                        : (node.short_name || node.ip) + " is already in the device list.",
                    result?.connect_error ? "warn" : (added ? "success" : "info")
                );
            } catch (e) {
                Alpine.store("app").showApiError("Could not add discovered device", e);
            }
        },

        async addManualIp() {
            const ip = this.manualIp.trim();
            if (!ip) return;
            try {
                const result = await api("POST", "/api/add_manual", { ip });
                await Alpine.store("app").fetchState();
                Alpine.store("app").showNotice(
                    result?.connect_error
                        ? "Added device at " + ip + ", but connect failed: " + result.connect_error
                        : result?.status === "added"
                        ? "Added device at " + ip + "."
                        : "Device " + ip + " is already in the list.",
                    result?.connect_error ? "warn" : (result?.status === "added" ? "success" : "info")
                );
                this.manualIp = "";
            } catch (e) {
                Alpine.store("app").showApiError("Could not add manual device", e);
            }
        },

        async removeDevice(di) {
            await api("POST", "/api/remove_device", { device: di });
            await Alpine.store("app").fetchState();
        },

        startRename(di) {
            const dev = this.devices[di];
            if (!this.canRenameDevice(dev)) {
                Alpine.store("app").showNotice(this.renameHint(dev), "info");
                return;
            }
            this.renamingDevice = di;
            this.renameValue = dev?.name || "";
        },

        async finishRename(di) {
            const name = this.renameValue.trim();
            const oldName = this.devices[di]?.name || "device";
            if (name && name !== oldName) {
                try {
                    await api("POST", "/api/rename_node", { device: di, name });
                    await Alpine.store("app").fetchState();
                    Alpine.store("app").showNotice("Renamed " + oldName + " to " + name + ".", "success");
                } catch (e) {
                    Alpine.store("app").showApiError("Rename failed", e);
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

        openIpConfig(di) {
            const dev = this.devices[di];
            if (!this.canConfigureIp(dev)) {
                Alpine.store("app").showNotice(this.ipConfigHint(dev), "info");
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
            const name = this.devices[di]?.name || "device";
            if (!ip || !gw || !sn) {
                Alpine.store("app").showNotice("Enter IP, gateway, and subnet before applying a static IP.", "warn");
                return;
            }
            if (!this.isIpv4(ip) || !this.isIpv4(gw) || !this.isIpv4(sn)) {
                Alpine.store("app").showNotice("Static IP, gateway, and subnet must be valid IPv4 addresses.", "warn");
                return;
            }
            try {
                await api("POST", "/api/set_device_ip", { device: di, ip, gateway: gw, subnet: sn });
                Alpine.store("app").showNotice(
                    "Restart " + name + "; Radius Central will pick up static IP " + ip + " automatically when it comes back online.",
                    "warn",
                    7000
                );
                this.ipConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError("Static IP update failed", e);
            }
        },

        async revertDhcp(di) {
            const name = this.devices[di]?.name || "device";
            try {
                await api("POST", "/api/revert_device_dhcp", { device: di });
                Alpine.store("app").showNotice(
                    "Restart " + name + "; Radius Central will pick up its DHCP address automatically when it comes back online.",
                    "warn",
                    7000
                );
                this.ipConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError("DHCP revert failed", e);
            }
        },
    });
});
