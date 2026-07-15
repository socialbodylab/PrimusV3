/**
 * app-devices.js — Device Manager view bootstrap
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
        product: "primus",
        state: null,
        network: null,
        runtime: null,
        polling: null,
        networkPolling: null,
        syncPolling: null,
        notice: null,
        _noticeTimer: null,
        _stateFetchGeneration: 0,
        _stateFetchAppliedGeneration: 0,
        startupScanMessage: "Scanning network for devices…",
        startupScanActive: false,
        filterCharacterName: "",
        filterPrimusCharacter: "",
        filterRadiusCharacter: "",
        filterProductType: null,
        mode: "monitor",
        bulkPanel: null,
        bulkRenamePattern: "Device {n}",
        bulkRenameStart: 1,
        bulkRenamePad: 0,
        bulkRenamePlan: [],
        bulkOutputIndex: 0,
        bulkOutputType: "none",
        bulkPresetId: "",
        bulkApplyResults: [],
        bulkReceiveMode: "split",
        bulkReceiveBase: 0,
        bulkReceiveStep: 2,
        mobileView: false,
        _mobileQrCache: null,
        expandedCards: {},

        get brandLabel() {
            const version = this.runtime?.app_version;
            return version ? `Device Manager v${version}` : "Device Manager";
        },

        get deviceGroups() {
            return this.state?.device_groups || [];
        },

        get onlineDeviceSummary() {
            return this.summaryOnline + "/" + this.summaryTotal + " online";
        },

        get outputTypes() {
            return this.state?.look_output_types || [];
        },

        get mobileAccessUrl() {
            if (!this.runtime?.lan_enabled) return null;
            const iface = this.network?.selected_interface || this.network?.recommended_interface;
            const ip = iface?.source_ip;
            if (!ip) return null;
            return `http://${ip}:${window.location.port}/devices?mode=mobile`;
        },

        get mobileAccessUnavailableReason() {
            if (this.runtime && !this.runtime.lan_enabled) {
                return "This session isn't reachable from other devices. Restart Device Manager from its own launcher (not attached to an already-running PrimusCentral) to enable mobile/tablet access.";
            }
            if (!this.mobileAccessUrl) {
                return "No active network connection was found to share with a phone or tablet.";
            }
            return null;
        },

        get mobileAccessSvg() {
            const url = this.mobileAccessUrl;
            if (!url) return "";
            if (this._mobileQrCache?.url === url) return this._mobileQrCache.svg;
            try {
                const qr = qrcode(0, "M");
                qr.addData(url);
                qr.make();
                const svg = qr.createSvgTag(6, 8);
                this._mobileQrCache = { url, svg };
                return svg;
            } catch (e) {
                return "";
            }
        },

        setMode(m) {
            this.mode = m;
            document.dispatchEvent(new CustomEvent("primus:mode-changed", {
                detail: { mode: m },
            }));
        },

        deviceHasError(dev) {
            return !!dev?.transport_error;
        },

        deviceLowBattery(dev) {
            if (!dev?.capabilities?.battery) return false;
            const mode = dev?.battery_power_mode;
            if (mode === "fault" || mode === "switch_off") return true;
            const pct = dev?.battery_pct;
            return pct != null && pct <= 15;
        },

        deviceNeedsAttention(dev) {
            if (this.isRadiusDevice(dev)) {
                return this.deviceHasError(dev);
            }
            return this.deviceHasError(dev) || this.deviceLowBattery(dev);
        },

        isRadiusDevice(dev) {
            if (!dev) return false;
            if (dev.is_radius) return true;
            const caps = dev.capabilities || {};
            if (caps.device_class === "radius" || caps.profile === "pvrad1") return true;
            const name = `${dev.name || ""} ${caps.hardware_label || ""}`.toLowerCase();
            return name.includes("radius") && !caps.output_config;
        },

        deviceProductType(dev) {
            return this.isRadiusDevice(dev) ? "radius" : "primus";
        },

        get groupedDevices() {
            return this.groupDevicesForProduct(null);
        },

        groupDevicesForProduct(product) {
            const attention = [];
            const online = [];
            const offline = [];
            for (const entry of this.filteredDevices) {
                if (product && this.deviceProductType(entry.dev) !== product) {
                    continue;
                }
                if (this.deviceNeedsAttention(entry.dev)) {
                    entry._section = "attention";
                    attention.push(entry);
                } else if (entry.dev.receiver_online) {
                    entry._section = "online";
                    online.push(entry);
                } else {
                    entry._section = "offline";
                    offline.push(entry);
                }
            }
            return { attention, online, offline };
        },

        get productSectionList() {
            const products = [
                { key: "primus", label: "Primus" },
                { key: "radius", label: "Radius" },
            ];
            return products.map(product => {
                const g = this.groupDevicesForProduct(product.key);
                const sections = [
                    { key: "attention", label: "Attention", entries: g.attention },
                    { key: "online", label: "Online", entries: g.online },
                    { key: "offline", label: "Offline / Unconfirmed", entries: g.offline },
                ];
                const count = g.attention.length + g.online.length + g.offline.length;
                return { ...product, count, sections };
            }).filter(product => product.count > 0);
        },

        get sectionList() {
            const g = this.groupedDevices;
            return [
                { key: "attention", label: "Attention", entries: g.attention },
                { key: "online", label: "Online", entries: g.online },
                { key: "offline", label: "Offline / Unconfirmed", entries: g.offline },
            ];
        },

        get summaryTotal() {
            return (this.state?.devices || []).length;
        },

        get summaryOnline() {
            return (this.state?.devices || []).filter(d => d.receiver_online).length;
        },

        get summaryLowBattery() {
            return (this.state?.devices || []).filter(d => this.deviceLowBattery(d)).length;
        },

        get summaryErrors() {
            return (this.state?.devices || []).filter(d => this.deviceHasError(d)).length;
        },

        get summaryPrimusCount() {
            return (this.state?.devices || []).filter(d => !this.isRadiusDevice(d)).length;
        },

        get summaryRadiusCount() {
            return (this.state?.devices || []).filter(d => this.isRadiusDevice(d)).length;
        },

        get hasPrimusDevices() {
            return this.summaryPrimusCount > 0;
        },

        get hasRadiusDevices() {
            return this.summaryRadiusCount > 0;
        },

        isProductFilterVisible(product) {
            return this.filterProductType === null || this.filterProductType === product;
        },

        setProductFilter(product) {
            this.filterProductType = product || null;
        },

        toggleProductFilter(product) {
            if (this.filterProductType === product) {
                this.filterProductType = null;
                return;
            }
            this.filterProductType = product;
        },

        isProductFilterActive(product) {
            if (product === null) {
                return this.filterProductType === null;
            }
            return this.filterProductType === product;
        },

        get characterFilterOptions() {
            return this.primusCharacterFilterOptions;
        },

        get primusCharacterFilterOptions() {
            return this._characterFilterOptionsFor("primus");
        },

        get radiusCharacterFilterOptions() {
            return this._characterFilterOptionsFor("radius");
        },

        _characterFilterOptionsFor(product) {
            const names = new Set();
            for (const dev of (this.state?.devices || [])) {
                if (this.deviceProductType(dev) !== product) continue;
                const name = (dev.character_name || "").trim();
                if (name) names.add(name);
            }
            return [...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
        },

        get filteredDevices() {
            const devices = this.state?.devices || [];

            return devices.reduce((entries, dev, index) => {
                const product = this.deviceProductType(dev);
                if (this.filterProductType && product !== this.filterProductType) {
                    return entries;
                }
                const filter = product === "radius"
                    ? this.filterRadiusCharacter.trim().toLowerCase()
                    : this.filterPrimusCharacter.trim().toLowerCase();
                if (filter) {
                    const character = (dev.character_name || "").trim().toLowerCase();
                    if (character !== filter) {
                        return entries;
                    }
                }
                entries.push({ dev, _index: index });
                return entries;
            }, []);
        },

        toggleCharacterFilter(name) {
            this.filterCharacterName = this.filterCharacterName === name ? "" : name;
            this.filterPrimusCharacter = this.filterCharacterName;
        },

        togglePrimusCharacterFilter(name) {
            this.filterPrimusCharacter = this.filterPrimusCharacter === name ? "" : name;
            this.filterCharacterName = this.filterPrimusCharacter;
        },

        toggleRadiusCharacterFilter(name) {
            this.filterRadiusCharacter = this.filterRadiusCharacter === name ? "" : name;
        },

        clearCharacterFilter() {
            this.filterCharacterName = "";
            this.filterPrimusCharacter = "";
            this.filterRadiusCharacter = "";
        },

        clearPrimusCharacterFilter() {
            this.filterPrimusCharacter = "";
            if (!this.filterRadiusCharacter) {
                this.filterCharacterName = "";
            }
        },

        clearRadiusCharacterFilter() {
            this.filterRadiusCharacter = "";
        },

        isCardExpanded(index) {
            return !!this.expandedCards[index];
        },

        toggleCardExpanded(index) {
            this.expandedCards[index] = !this.expandedCards[index];
        },

        outputLabel(value, idx = null) {
            const raw = value == null ? "" : String(value);
            const match = raw.match(/^A(\d+)$/i);
            if (match) return "Output " + match[1];
            if (raw) return raw;
            return Number.isInteger(idx) ? "Output " + idx : "Output";
        },

        outputTypeLabel(type) {
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

        async init() {
            const params = new URLSearchParams(window.location.search);
            this.mobileView = params.get("mode") === "mobile";
            try {
                this.runtime = await api("GET", "/api/runtime");
                this.product = this.runtime?.product || "primus";
                if (this.runtime?.app_version) {
                    document.title = `Device Manager v${this.runtime.app_version}`;
                }
            } catch (e) {
                /* ignore */
            }
            await this.fetchNetworkStatus();
            Alpine.store("conn").loadOutputPresets();
            this.networkPolling = setInterval(() => this.fetchNetworkStatus(), 15000);
            try {
                await Alpine.store("conn").syncNetwork({ startup: true });
            } catch (e) {
                // Startup sync may fail while the backend is still coming up; a neutral
                // scanning notice is shown instead of an error. Retry soon, then on
                // the regular 20s auto-sync interval.
                setTimeout(() => Alpine.store("conn").autoSyncNetwork(), 2500);
            }
            this.polling = setInterval(() => this.fetchState(), 1000);
            this.syncPolling = setInterval(() => Alpine.store("conn").autoSyncNetwork(), 20000);
            this.startRuntimeLifecycle();
        },

        async startRuntimeLifecycle() {
            try {
                if (!this.runtime) {
                    this.runtime = await api("GET", "/api/runtime");
                    this.product = this.runtime?.product || "primus";
                }
            } catch (e) {
                return;
            }
            this._lifecycleHeartbeat = window.PrimusUiLifecycle?.install(api, this.runtime) || null;
        },

        async fetchState(shouldApply = null) {
            const generation = ++this._stateFetchGeneration;
            try {
                const nextState = await api("GET", "/api/state");
                if (generation < this._stateFetchAppliedGeneration) {
                    return false;
                }
                if (typeof shouldApply === "function" && !shouldApply()) return false;
                this._stateFetchAppliedGeneration = generation;
                this.state = nextState;
                if (this.state?.product) {
                    this.product = this.state.product;
                }
                Alpine.store("conn").syncShowInfoDrafts();
                Alpine.store("conn").syncReceiveConfigDrafts();
                Alpine.store("conn").syncVirtualConfigDrafts();
                Alpine.store("conn").syncManagementUi();
                if (this.startupScanActive && (this.state?.devices || []).length > 0) {
                    this.clearStartupScanNotice();
                }
                return true;
            } catch (e) {
                return false;
            }
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
            if (!this.network) return "Network status";
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

        showNotice(message, level = "info", timeout = 3200) {
            this.notice = { message, level };
            if (this._noticeTimer) clearTimeout(this._noticeTimer);
            if (timeout > 0) {
                this._noticeTimer = setTimeout(() => {
                    this.notice = null;
                    this._noticeTimer = null;
                }, timeout);
            }
        },

        clearNotice() {
            this.notice = null;
            if (this._noticeTimer) {
                clearTimeout(this._noticeTimer);
                this._noticeTimer = null;
            }
        },

        beginStartupScanNotice() {
            this.startupScanActive = true;
            this.showNotice(this.startupScanMessage, "info", 0);
        },

        clearStartupScanNotice() {
            if (!this.startupScanActive) {
                return;
            }
            this.startupScanActive = false;
            if (this.notice?.message === this.startupScanMessage) {
                this.clearNotice();
            }
        },

        showApiError(action, error) {
            const detail = error?.message ? ": " + error.message : "";
            this.showNotice(action + detail, "error", 5000);
        },

        deviceGroupNames(dev) {
            const groups = this.deviceGroups.filter(group => (group.device_ips || []).includes(dev.ip));
            return groups.map(group => group.name).join(", ");
        },

        // ---- Bulk actions (device group scoped) ----
        currentBulkGroup() {
            return this.deviceGroups.find(g => g.id === this.filterGroupId) || null;
        },

        openBulkRename() {
            this.bulkPanel = "rename";
            this.updateBulkRenamePreview();
        },

        updateBulkRenamePreview() {
            const group = this.currentBulkGroup();
            this.bulkRenamePlan = group
                ? Alpine.store("conn").bulkRenamePreview(
                    group, this.bulkRenamePattern, Number(this.bulkRenameStart) || 1, Number(this.bulkRenamePad) || 0)
                : [];
        },

        async applyBulkRename() {
            await Alpine.store("conn").bulkRenameApply(this.bulkRenamePlan);
            this.bulkPanel = null;
            this.bulkRenamePlan = [];
        },

        openBulkApply() {
            this.bulkPanel = "apply";
            this.bulkApplyResults = [];
            Alpine.store("conn").loadOutputPresets();
        },

        async applyBulkOutputType() {
            const group = this.currentBulkGroup();
            if (!group) return;
            await Alpine.store("conn").bulkApplyOutputType(group, Number(this.bulkOutputIndex) || 0, this.bulkOutputType);
        },

        async applyBulkPreset() {
            const group = this.currentBulkGroup();
            const preset = Alpine.store("conn").outputPresets.find(
                item => item.id === this.bulkPresetId,
            );
            if (!group || !preset) {
                this.showNotice("Choose a group and output preset first.", "warn");
                return;
            }
            const result = await Alpine.store("conn").bulkApplyDescriptor(
                group,
                Number(this.bulkOutputIndex) || 0,
                preset.descriptor,
            );
            this.bulkApplyResults = result.results || [];
        },

        async applyBulkReceiveMode() {
            const group = this.currentBulkGroup();
            if (!group) return;
            await Alpine.store("conn").bulkApplyReceiveMode(
                group, this.bulkReceiveMode, Number(this.bulkReceiveBase) || 0, Number(this.bulkReceiveStep) || 0);
        },

        closeBulkPanel() {
            this.bulkPanel = null;
            this.bulkRenamePlan = [];
            this.bulkApplyResults = [];
        },
    });
});
