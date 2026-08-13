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
        filterPrimusCharacter: "",
        filterRadiusCharacter: "",
        filterProductType: null,
        filterAttentionOnly: false,
        mode: "monitor",
        mobileView: false,
        _mobileQrCache: null,
        // Keyed by the stable device key (device_uid → ip → name), never by
        // array index — removing a device must not shift another card's state.
        expandedCards: {},
        // Performer identity editor: { groupKey, character, performer, saving }.
        identityEditor: null,
        // Snapshot of performer-group order taken when the identity editor
        // opens, so a mid-edit save/refresh can't re-sort groups under the
        // operator's cursor.
        _frozenGroupOrder: null,

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
            // Prefer the address this page was actually served from: the
            // Art-Net NIC's IP is not necessarily the HTTP-reachable address
            // (a dedicated backend machine may separate the two). Fall back
            // to the interface IP only when we're browsing via loopback.
            const host = window.location.hostname;
            const isLoopback = host === "127.0.0.1" || host === "localhost" || host === "::1";
            if (!isLoopback) {
                return `http://${host}:${window.location.port}/devices?mode=mobile`;
            }
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

        // Per-card status expressed IN PLACE (border tint + pill) instead of by
        // moving the card between layout sections.
        deviceStatusSection(dev) {
            if (this.deviceNeedsAttention(dev)) return "attention";
            return dev?.receiver_online ? "online" : "offline";
        },

        cardStatusClass(dev) {
            return "dm-card-" + this.deviceStatusSection(dev);
        },

        // Stable ordering for devices within a performer group (and within
        // Unassigned): Primus first, then Radius, tiebreak on the stable device
        // key. Never influenced by battery, online state, errors, or sync order.
        _compareEntries(a, b) {
            const ar = this.isRadiusDevice(a.dev) ? 1 : 0;
            const br = this.isRadiusDevice(b.dev) ? 1 : 0;
            if (ar !== br) return ar - br;
            return String(a.key).localeCompare(String(b.key));
        },

        // Performer grouping. Shape:
        //   [{ key, performerName, characterNames: [..], characterLabel,
        //      devices: [{ dev, _index, key }...],  // Primus first, key tiebreak
        //      hasPrimus, hasRadius, count,
        //      worstStatus: "attention"|"offline"|"online",
        //      onlineCount }]
        // Sorted alphabetically by performer name (localeCompare, sensitivity
        // "base"), tiebreak on normalized key. Order is frozen while the
        // identity editor is open.
        get performerGroups() {
            const conn = Alpine.store("conn");
            const groups = new Map();
            for (const entry of this.filteredDevices) {
                const key = conn.performerKey(entry.dev);
                if (!key) continue;
                let group = groups.get(key);
                if (!group) {
                    group = { key, devices: [] };
                    groups.set(key, group);
                }
                group.devices.push(entry);
            }
            const list = [...groups.values()];
            for (const group of list) {
                group.devices.sort((a, b) => this._compareEntries(a, b));
                // Deterministic display name/characters regardless of the order
                // devices arrived from the backend.
                group.performerName = (group.devices[0].dev.performer_name || "").trim();
                const characters = new Set();
                group.hasPrimus = false;
                group.hasRadius = false;
                group.onlineCount = 0;
                let attention = false;
                let offline = false;
                for (const entry of group.devices) {
                    const dev = entry.dev;
                    const character = (dev.character_name || "").trim();
                    if (character) characters.add(character);
                    if (this.isRadiusDevice(dev)) group.hasRadius = true;
                    else group.hasPrimus = true;
                    if (this.deviceNeedsAttention(dev)) attention = true;
                    if (dev.receiver_online) group.onlineCount++;
                    else offline = true;
                }
                group.characterNames = [...characters].sort(
                    (a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
                group.characterLabel = group.characterNames.join(" / ");
                group.count = group.devices.length;
                group.worstStatus = attention ? "attention" : (offline ? "offline" : "online");
            }
            list.sort((a, b) =>
                a.performerName.localeCompare(b.performerName, undefined, { sensitivity: "base" })
                || String(a.key).localeCompare(String(b.key)));
            if (this.identityEditor && this._frozenGroupOrder) {
                const order = this._frozenGroupOrder;
                const rank = key => {
                    const idx = order.indexOf(key);
                    return idx === -1 ? order.length : idx;
                };
                list.sort((a, b) => rank(a.key) - rank(b.key));
            }
            return list;
        },

        get unassignedEntries() {
            const conn = Alpine.store("conn");
            return this.filteredDevices
                .filter(entry => !conn.hasPerformer(entry.dev))
                .sort((a, b) => this._compareEntries(a, b));
        },

        // Render list for the Monitor tab: one section per performer, then a
        // single Unassigned section. Assigning a performer name moves the card
        // into that performer's group — that move is expected feedback.
        get monitorSections() {
            const sections = this.performerGroups.map(group => ({
                key: "perf:" + group.key,
                type: "performer",
                group,
                entries: group.devices,
            }));
            const unassigned = this.unassignedEntries;
            if (unassigned.length) {
                sections.push({
                    key: "unassigned",
                    type: "unassigned",
                    group: null,
                    entries: unassigned,
                });
            }
            return sections;
        },

        groupRollupLabel(group) {
            if (!group) return "";
            if (group.worstStatus === "attention") return "Attention";
            if (group.worstStatus === "offline") {
                return group.onlineCount + "/" + group.count + " live";
            }
            return "Live";
        },

        groupRollupClass(group) {
            if (!group) return "";
            if (group.worstStatus === "attention") return "dm-status-error";
            if (group.worstStatus === "offline") return "dm-status-nosignal";
            return "dm-status-live";
        },

        // ---- Performer identity editor ----
        get allCharacterNames() {
            const names = new Set();
            for (const dev of (this.state?.devices || [])) {
                const name = (dev.character_name || "").trim();
                if (name) names.add(name);
            }
            return [...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
        },

        get allPerformerNames() {
            const names = new Set();
            for (const dev of (this.state?.devices || [])) {
                const name = (dev.performer_name || "").trim();
                if (name) names.add(name);
            }
            return [...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
        },

        isIdentityEditorOpen(groupKey) {
            return !!this.identityEditor && this.identityEditor.groupKey === groupKey;
        },

        toggleIdentityEditor(group) {
            if (!group) return;
            if (this.isIdentityEditorOpen(group.key)) {
                this.closeIdentityEditor();
                return;
            }
            this._frozenGroupOrder = this.performerGroups.map(g => g.key);
            this.identityEditor = {
                groupKey: group.key,
                character: group.characterNames[0] || "",
                performer: group.performerName,
                saving: false,
            };
        },

        closeIdentityEditor() {
            this.identityEditor = null;
            this._frozenGroupOrder = null;
        },

        async saveIdentityEditor() {
            const editor = this.identityEditor;
            if (!editor || editor.saving) return;
            const conn = Alpine.store("conn");
            const group = this.performerGroups.find(g => g.key === editor.groupKey);
            if (!group) {
                this.closeIdentityEditor();
                return;
            }
            const character = String(editor.character || "").trim().slice(0, 64);
            const performer = String(editor.performer || "").trim().slice(0, 64);
            editor.saving = true;
            let succeeded = 0;
            let failed = 0;
            let skipped = 0;
            for (const entry of group.devices) {
                const dev = entry.dev;
                if (!conn.showInfoEnabled(dev) || !conn.canEditDeviceSettings(dev)) {
                    skipped++;
                    continue;
                }
                try {
                    await api("POST", "/api/device_show_info", {
                        device: entry._index,
                        character_name: character,
                        performer_name: performer,
                    });
                    succeeded++;
                } catch (e) {
                    failed++;
                }
            }
            this.closeIdentityEditor();
            await this.fetchState();
            this.showNotice(
                `Identity saved on ${succeeded} device${succeeded === 1 ? "" : "s"}`
                    + (failed ? `; ${failed} failed` : "")
                    + (skipped ? `; ${skipped} skipped (locked or unsupported)` : "") + ".",
                failed ? "warn" : "success",
                4000,
            );
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
            const conn = Alpine.store("conn");
            const devices = this.state?.devices || [];

            return devices.reduce((entries, dev, index) => {
                const product = this.deviceProductType(dev);
                if (this.filterProductType && product !== this.filterProductType) {
                    return entries;
                }
                if (this.filterAttentionOnly && !this.deviceNeedsAttention(dev)) {
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
                // _index stays on every entry: all device actions still address
                // the backend by array index ({ device: di }).
                entries.push({ dev, _index: index, key: conn.deviceKey(dev) });
                return entries;
            }, []);
        },

        togglePrimusCharacterFilter(name) {
            this.filterPrimusCharacter = this.filterPrimusCharacter === name ? "" : name;
        },

        toggleRadiusCharacterFilter(name) {
            this.filterRadiusCharacter = this.filterRadiusCharacter === name ? "" : name;
        },

        clearPrimusCharacterFilter() {
            this.filterPrimusCharacter = "";
        },

        clearRadiusCharacterFilter() {
            this.filterRadiusCharacter = "";
        },

        toggleAttentionFilter() {
            this.filterAttentionOnly = !this.filterAttentionOnly;
        },

        isCardExpanded(key) {
            return !!this.expandedCards[key];
        },

        toggleCardExpanded(key) {
            this.expandedCards[key] = !this.expandedCards[key];
        },

        // fetchState reconciler: drop expand state for devices that no longer
        // exist. Keys are stable device keys, so surviving devices keep their
        // expand state across removals and re-syncs.
        syncExpandedCards() {
            const conn = Alpine.store("conn");
            if (!conn || typeof conn.deviceKey !== "function") return;
            const valid = new Set(
                (this.state?.devices || []).map(dev => conn.deviceKey(dev)));
            for (const key of Object.keys(this.expandedCards)) {
                if (!valid.has(key)) delete this.expandedCards[key];
            }
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
                this.syncExpandedCards();
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
    });
});
