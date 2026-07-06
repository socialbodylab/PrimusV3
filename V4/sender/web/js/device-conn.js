/**
 * device-conn.js — Shared Alpine store for device management (Primus, Radius, Device Manager)
 */

function connProduct() {
    return Alpine.store("app")?.product || "primus";
}

function connProductLabel() {
    return connProduct() === "radius" ? "Radius Central" : "Primus";
}

document.addEventListener("alpine:init", () => {
    Alpine.store("conn", {
        discovering: false,
        syncing: false,
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
        configFeedback: {},
        _ipRediscoveryTimer: null,
        _ipRediscoveryUntil: 0,
        sidebarCollapsed: false,
        showInfoDrafts: {},
        showInfoFocus: null,
        receiveConfigDrafts: {},
        receiveConfigFocus: null,
        editingShowInfo: null,
        showInfoEditValue: "",

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

        canConfigureOutputs(dev) {
            return connProduct() === "primus" && !!dev?.capabilities?.output_config;
        },

        canConfigureReceiveMode(dev) {
            return connProduct() === "primus" && !!dev?.capabilities?.receive_config;
        },

        receiveModeLabel(dev) {
            const mode = dev?.receive_mode || "split";
            const base = dev?.base_universe ?? 0;
            if (mode === "combined") {
                return `Combined · U${base}`;
            }
            return `Split · U${base}/${base + 1}`;
        },

        receiveModeHint(dev) {
            if (this.canConfigureReceiveMode(dev)) {
                return "Receive mode and base universe are stored on the receiver (NVS)";
            }
            if (dev?.receive_mode) {
                return "Receive mode reported from device discovery";
            }
            return "Flash firmware v3.8+ to change receive mode remotely";
        },

        initReceiveConfigDrafts(di) {
            if (this.receiveConfigDrafts[di]) {
                return;
            }
            const dev = this.devices[di];
            this.receiveConfigDrafts[di] = {
                receive_mode: dev?.receive_mode || "split",
                base_universe: dev?.base_universe ?? 0,
            };
        },

        syncReceiveConfigDrafts() {
            if (connProduct() !== "primus") {
                return;
            }
            const focusParts = (this.receiveConfigFocus || "").split(":");
            const focusDi = focusParts[0] !== "" ? Number(focusParts[0]) : null;
            const focusField = focusParts[1] || null;
            const validIndices = new Set(this.devices.map((_, di) => String(di)));
            for (const key of Object.keys(this.receiveConfigDrafts)) {
                if (!validIndices.has(String(key))) {
                    delete this.receiveConfigDrafts[key];
                }
            }
            this.devices.forEach((dev, di) => {
                if (!this.receiveConfigDrafts[di]) {
                    this.receiveConfigDrafts[di] = {
                        receive_mode: dev.receive_mode || "split",
                        base_universe: dev.base_universe ?? 0,
                    };
                    return;
                }
                const draft = this.receiveConfigDrafts[di];
                if (!(focusDi === di && focusField === "receive_mode")) {
                    draft.receive_mode = dev.receive_mode || "split";
                }
                if (!(focusDi === di && focusField === "base_universe")) {
                    draft.base_universe = dev.base_universe ?? 0;
                }
            });
        },

        finishReceiveConfigBaseEdit(di) {
            this.receiveConfigFocus = null;
            this.initReceiveConfigDrafts(di);
            const draft = this.receiveConfigDrafts[di];
            if (!draft) {
                return;
            }
            this.setDeviceBaseUniverse(di, draft.base_universe);
        },

        combinedPixelTotal(dev) {
            return (dev?.outputs || []).reduce(
                (sum, output) => sum + (output?.count || 0), 0);
        },

        canUseCombinedMode(dev) {
            return this.combinedPixelTotal(dev) <= 170;
        },

        deviceOutputTypes() {
            if (connProduct() !== "primus") return [];
            const app = Alpine.store("app");
            const types = app.outputTypes;
            if (Array.isArray(types)) return types;
            return app.state?.look_output_types || [];
        },

        deviceOutputTypesFor(dev, oi) {
            const types = [...this.deviceOutputTypes()];
            const current = dev?.outputs?.[oi]?.type;
            if (current && !types.includes(current)) {
                types.push(current);
            }
            return types;
        },

        outputConfigHint(dev) {
            return this.canConfigureOutputs(dev)
                ? "Configure physical output types on this receiver"
                : "Remote output configuration is not advertised for this node";
        },

        configFeedbackKey(di, kind, oi) {
            if (kind === "output") return `${di}:output:${oi}`;
            return `${di}:receive:${kind}`;
        },

        showInfoFeedbackKey(di, field) {
            return `${di}:show:${field}`;
        },

        setConfigFeedback(key, state, message) {
            this.configFeedback[key] = { state, message };
            if (state === "ok" || state === "error") {
                setTimeout(() => {
                    if (this.configFeedback[key]?.state === state) {
                        delete this.configFeedback[key];
                    }
                }, 3000);
            }
        },

        configFeedbackClass(key) {
            const fb = this.configFeedback[key];
            if (!fb) return "";
            return `device-config-${fb.state}`;
        },

        configFeedbackMessage(key) {
            return this.configFeedback[key]?.message || "";
        },

        isConfigPending(key) {
            return this.configFeedback[key]?.state === "pending";
        },

        receiveModeSelectLabel(mode) {
            return mode === "combined" ? "Combined" : "Split";
        },

        hardwareLabel(entity) {
            const fallback = connProduct() === "radius" ? "Radius V1" : "Unknown hardware";
            const label = entity?.hardware_label || entity?.hardware_profile || fallback;
            return String(label).replace("V3.1", "V3");
        },

        capabilityItems(entity) {
            const caps = entity?.capabilities || {};
            const items = [
                { key: "rename", label: "Rename", supported: !!caps.rename },
                { key: "ip_config", label: "IP", supported: !!caps.ip_config },
            ];
            if (connProduct() === "primus") {
                items.splice(1, 0,
                    { key: "hello", label: "Hello", supported: !!caps.hello },
                    { key: "output_config", label: "Outputs", supported: !!caps.output_config },
                    { key: "receive_config", label: "Receive", supported: !!caps.receive_config },
                    { key: "battery", label: "Battery", supported: !!caps.battery },
                );
            }
            return items;
        },

        showBattery(dev) {
            return connProduct() === "primus" && !!dev?.capabilities?.battery && !!dev?.connected;
        },

        receiverFpsLabel(dev) {
            if (!dev?.connected) {
                return "";
            }
            if (dev?.receiver_online) {
                if (dev?.receiver_fps != null) {
                    return `${dev.receiver_fps} fps · live`;
                }
                return "live";
            }
            return "waiting for receiver";
        },

        receiverLiveClass(dev) {
            if (!dev?.connected) {
                return "";
            }
            return dev?.receiver_online ? "device-live-ok" : "device-live-warn";
        },

        showInfoEnabled() {
            return connProduct() === "primus";
        },

        initShowInfoDrafts(di) {
            if (this.showInfoDrafts[di]) {
                return;
            }
            const dev = this.devices[di];
            this.showInfoDrafts[di] = {
                character_name: dev?.character_name || "",
                performer_name: dev?.performer_name || "",
            };
        },

        syncShowInfoDrafts() {
            if (!this.showInfoEnabled()) {
                return;
            }
            const focusParts = (this.showInfoFocus || "").split(":");
            const focusDi = focusParts[0] !== "" ? Number(focusParts[0]) : null;
            const focusField = focusParts[1] || null;
            const validIndices = new Set(this.devices.map((_, di) => String(di)));
            for (const key of Object.keys(this.showInfoDrafts)) {
                if (!validIndices.has(String(key))) {
                    delete this.showInfoDrafts[key];
                }
            }
            this.devices.forEach((dev, di) => {
                if (!this.showInfoDrafts[di]) {
                    this.showInfoDrafts[di] = {
                        character_name: dev.character_name || "",
                        performer_name: dev.performer_name || "",
                    };
                    return;
                }
                const draft = this.showInfoDrafts[di];
                if (!(focusDi === di && focusField === "character_name")) {
                    draft.character_name = dev.character_name || "";
                }
                if (!(focusDi === di && focusField === "performer_name")) {
                    draft.performer_name = dev.performer_name || "";
                }
            });
        },

        showInfoEditKey(di, field) {
            return `${di}:${field}`;
        },

        isEditingShowInfo(di, field) {
            return this.editingShowInfo === this.showInfoEditKey(di, field);
        },

        showInfoDisplay(dev, field) {
            const value = field === "character_name" ? dev?.character_name : dev?.performer_name;
            return value || "Add…";
        },

        showInfoHint(field) {
            if (field === "character_name") {
                return "Click to set character name";
            }
            return "Click to set performer name";
        },

        showInfoStorageHint(dev) {
            if (dev?.capabilities?.show_info) {
                return "Stored on receiver";
            }
            return "Saved on this computer only — flash firmware v3.10+ to store on receiver";
        },

        startShowInfoEdit(di, field) {
            const dev = this.devices[di];
            if (!dev) {
                return;
            }
            this.editingShowInfo = this.showInfoEditKey(di, field);
            this.showInfoEditValue = field === "character_name"
                ? (dev.character_name || "")
                : (dev.performer_name || "");
        },

        async finishShowInfoEdit(di, field) {
            const key = this.showInfoEditKey(di, field);
            if (this.editingShowInfo !== key) {
                return;
            }
            const trimmed = this.showInfoEditValue.trim().slice(0, 64);
            this.editingShowInfo = null;
            this.showInfoEditValue = "";
            this.initShowInfoDrafts(di);
            this.showInfoDrafts[di][field] = trimmed;
            await this.saveShowInfoField(di, field);
        },

        cancelShowInfoEdit() {
            this.editingShowInfo = null;
            this.showInfoEditValue = "";
        },

        async saveShowInfoField(di, field) {
            if (!this.showInfoEnabled()) {
                return;
            }
            const dev = this.devices[di];
            if (!dev) {
                return;
            }
            this.initShowInfoDrafts(di);
            const trimmed = String(this.showInfoDrafts[di]?.[field] || "").trim().slice(0, 64);
            const current = field === "character_name"
                ? (dev.character_name || "")
                : (dev.performer_name || "");
            const feedbackField = field === "character_name" ? "character" : "performer";
            const feedbackKey = this.showInfoFeedbackKey(di, feedbackField);
            if (trimmed === current) {
                this.showInfoDrafts[di][field] = trimmed;
                return;
            }
            const body = {
                device: di,
                character_name: dev.character_name || "",
                performer_name: dev.performer_name || "",
            };
            body[field] = trimmed;
            this.setConfigFeedback(feedbackKey, "pending", "");
            try {
                const result = await api("POST", "/api/device_show_info", body);
                this.showInfoDrafts[di][field] = trimmed;
                this.setConfigFeedback(feedbackKey, "ok", "Saved");
                await Alpine.store("app").fetchState();
                const label = feedbackField === "character" ? "Character" : "Performer";
                const name = this.devices[di]?.name || "device";
                const storage = result?.applied_to_device
                    ? "saved on receiver"
                    : "saved on this computer (upgrade firmware v3.10+ for receiver storage)";
                Alpine.store("app").showNotice(
                    trimmed
                        ? `${label} for ${name} ${storage}.`
                        : `${label} cleared for ${name}.`,
                    "success",
                    2800,
                );
            } catch (e) {
                this.setConfigFeedback(feedbackKey, "error", "Save failed");
                Alpine.store("app").showApiError("Could not save show info", e);
            }
        },

        firmwareLabel(dev) {
            const version = dev?.live_firmware_version || dev?.firmware_version;
            if (!version) return "—";
            return version.startsWith("v") ? version : `v${version}`;
        },

        batteryLabel(dev) {
            const mode = dev?.battery_power_mode;
            if (mode === "switch_off") return "Off";
            if (mode === "fault") return "—";
            if (mode === "unavailable" || mode == null) return "…";
            const pct = dev?.battery_pct;
            if (pct == null) return "…";
            return `${pct}%`;
        },

        batteryClass(dev) {
            const mode = dev?.battery_power_mode;
            if (mode === "switch_off" || mode === "fault") {
                return "device-battery device-battery-alert";
            }
            if (mode == null) return "device-battery device-battery-pending";
            const pct = dev?.battery_pct;
            if (pct == null) return "device-battery device-battery-pending";
            if (pct <= 15) return "device-battery device-battery-critical";
            if (pct <= 30) return "device-battery device-battery-warn";
            return "device-battery device-battery-ok";
        },

        batteryTitle(dev) {
            if (dev?.battery_warning) return dev.battery_warning;
            const pct = dev?.battery_pct;
            const mv = dev?.battery_mv;
            if (pct == null || mv == null) return "Waiting for battery telemetry…";
            const volts = (mv / 1000).toFixed(2);
            return `${pct}% · ${volts} V`;
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

        helloHint(dev) {
            return this.canHelloDevice(dev)
                ? "Send identify flash"
                : "Identify flash is not advertised for this node";
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
            const label = connProductLabel();
            if (dev?.ip_config_pending === "static") {
                return `Restart this receiver; ${label} will automatically pick up the static IP when it comes back online.`;
            }
            if (dev?.ip_config_pending === "dhcp") {
                return `Restart this receiver; ${label} will automatically pick up the DHCP address when it comes back online.`;
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

        async syncNetwork() {
            this.syncing = true;
            try {
                const result = await api("POST", "/api/devices/sync");
                await Alpine.store("app").fetchState();
                const added = result?.added?.length || 0;
                const connected = result?.connected?.length || 0;
                Alpine.store("app").showNotice(
                    added
                        ? `Synced network: added ${added} device${added === 1 ? "" : "s"}, connected ${connected}.`
                        : `Synced network: connected ${connected} device${connected === 1 ? "" : "s"}.`,
                    "success",
                );
                return result;
            } catch (e) {
                Alpine.store("app").showApiError("Network sync failed", e);
                throw e;
            } finally {
                this.syncing = false;
            }
        },

        async helloDevice(di) {
            try {
                const body = { device: di };
                if (connProduct() === "radius") {
                    body.volume = Alpine.store("audio")?.getVolume?.(di) ?? 80;
                }
                await api("POST", "/api/hello_device", body);
                const name = this.devices[di]?.name || "device";
                Alpine.store("app").showNotice("Identify flash sent to " + name + ".", "success", 2200);
            } catch (e) {
                Alpine.store("app").showApiError("Hello failed", e);
            }
        },

        async setDeviceOutputType(di, oi, outputType) {
            const dev = this.devices[di];
            const priorType = dev?.outputs?.[oi]?.type;
            if (!priorType || priorType === outputType) return;
            const key = this.configFeedbackKey(di, "output", oi);
            this.setConfigFeedback(key, "pending", "");
            try {
                const result = await api("POST", "/api/set_device_output", {
                    device: di,
                    output: oi,
                    output_type: outputType,
                });
                this.setConfigFeedback(key, "ok", result?.message || "Applied");
            } catch (e) {
                this.setConfigFeedback(key, "error", e.message || "Update failed");
                Alpine.store("app").showApiError("Output update failed", e);
            } finally {
                await Alpine.store("app").fetchState();
            }
        },

        async setDeviceReceiveModeValue(di, receiveMode) {
            const dev = this.devices[di];
            if (!dev) return;
            this.initReceiveConfigDrafts(di);
            const mode = receiveMode || this.receiveConfigDrafts[di]?.receive_mode || "split";
            const priorMode = dev.receive_mode || "split";
            if (priorMode === mode) return;
            if (mode === "combined" && !this.canUseCombinedMode(dev)) {
                Alpine.store("app").showNotice(
                    "Combined mode requires at most 170 pixels across outputs", "error");
                this.receiveConfigDrafts[di].receive_mode = priorMode;
                return;
            }
            await this._applyReceiveMode(
                di,
                mode,
                this.receiveConfigDrafts[di]?.base_universe ?? dev.base_universe ?? 0,
                "mode",
            );
        },

        async setDeviceBaseUniverse(di, baseUniverse) {
            const dev = this.devices[di];
            if (!dev) return;
            this.initReceiveConfigDrafts(di);
            const base = Number(
                baseUniverse ?? this.receiveConfigDrafts[di]?.base_universe ?? dev.base_universe ?? 0,
            );
            if (!Number.isFinite(base) || base < 0 || base > 32767) {
                Alpine.store("app").showNotice("Base universe must be 0–32767", "error");
                this.receiveConfigDrafts[di].base_universe = dev.base_universe ?? 0;
                return;
            }
            if ((dev.base_universe ?? 0) === base) return;
            const mode = this.receiveConfigDrafts[di]?.receive_mode || dev.receive_mode || "split";
            if (mode === "combined" && !this.canUseCombinedMode(dev)) {
                Alpine.store("app").showNotice(
                    "Combined mode requires at most 170 pixels across outputs", "error");
                this.receiveConfigDrafts[di].base_universe = dev.base_universe ?? 0;
                return;
            }
            await this._applyReceiveMode(di, mode, base, "base");
        },

        async _applyReceiveMode(di, receiveMode, baseUniverse, feedbackKind) {
            const key = this.configFeedbackKey(di, feedbackKind);
            this.setConfigFeedback(key, "pending", "");
            try {
                const result = await api("POST", "/api/set_device_receive_mode", {
                    device: di,
                    receive_mode: receiveMode,
                    base_universe: baseUniverse,
                });
                this.setConfigFeedback(key, "ok", result?.message || "Applied");
                this.initReceiveConfigDrafts(di);
                this.receiveConfigDrafts[di].receive_mode = receiveMode;
                this.receiveConfigDrafts[di].base_universe = baseUniverse;
            } catch (e) {
                this.setConfigFeedback(key, "error", e.message || "Update failed");
                Alpine.store("app").showApiError("Receive mode update failed", e);
                this.syncReceiveConfigDrafts();
            } finally {
                await Alpine.store("app").fetchState();
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
                        ? "Discovery found " + count + " new device" + (count === 1 ? "" : "s") + "."
                        : total
                        ? "Discovery refreshed " + total + " known device" + (total === 1 ? "" : "s") + "."
                        : "Discovery finished with no devices found.",
                    count ? "success" : "info",
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
                    result?.connect_error ? "warn" : (added ? "success" : "info"),
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
                    result?.connect_error ? "warn" : (result?.status === "added" ? "success" : "info"),
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
            const label = connProductLabel();
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
                    "Restart " + name + "; " + label + " will pick up static IP " + ip + " automatically when it comes back online.",
                    "warn",
                    7000,
                );
                this.ipConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError("Static IP update failed", e);
            }
        },

        async revertDhcp(di) {
            const name = this.devices[di]?.name || "device";
            const label = connProductLabel();
            try {
                await api("POST", "/api/revert_device_dhcp", { device: di });
                Alpine.store("app").showNotice(
                    "Restart " + name + "; " + label + " will pick up its DHCP address automatically when it comes back online.",
                    "warn",
                    7000,
                );
                this.ipConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError("DHCP revert failed", e);
            }
        },

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
            await Alpine.store("app").fetchState();
            this.groupModal = false;
        },

        async deleteGroup(gid) {
            await api("DELETE", "/api/device_groups/" + gid);
            await Alpine.store("app").fetchState();
        },

        async connectGroup(group) {
            for (let di = 0; di < this.devices.length; di++) {
                if (group.device_ips.includes(this.devices[di].ip) && !this.devices[di].connected) {
                    await api("POST", "/api/connect", { device: di });
                }
            }
            await Alpine.store("app").fetchState();
        },

        async disconnectGroup(group) {
            for (let di = 0; di < this.devices.length; di++) {
                if (group.device_ips.includes(this.devices[di].ip) && this.devices[di].connected) {
                    await api("POST", "/api/disconnect", { device: di });
                }
            }
            await Alpine.store("app").fetchState();
        },
    });
});
