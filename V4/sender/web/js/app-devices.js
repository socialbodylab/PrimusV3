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
            throw new Error(parsed?.error || `API ${r.status}: ${r.statusText}`);
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
        filterText: "",
        filterGroupId: "",
        mode: "monitor",
        bulkPanel: null,
        bulkRenamePattern: "Device {n}",
        bulkRenameStart: 1,
        bulkRenamePad: 0,
        bulkRenamePlan: [],
        bulkOutputIndex: 0,
        bulkOutputType: "none",
        bulkReceiveMode: "split",
        bulkReceiveBase: 0,
        bulkReceiveStep: 2,

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
            return this.deviceHasError(dev) || this.deviceLowBattery(dev);
        },

        get groupedDevices() {
            const attention = [];
            const online = [];
            const offline = [];
            for (const entry of this.filteredDevices) {
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

        get filteredDevices() {
            const devices = this.state?.devices || [];
            const query = this.filterText.trim().toLowerCase();
            const group = this.deviceGroups.find(item => item.id === this.filterGroupId);
            const groupIps = group ? new Set(group.device_ips || []) : null;

            return devices.reduce((entries, dev, index) => {
                if (groupIps && !groupIps.has(dev.ip)) {
                    return entries;
                }
                if (query) {
                    const haystack = [
                        dev.name,
                        dev.ip,
                        dev.static_ip,
                    ].filter(Boolean).join(" ").toLowerCase();
                    if (!haystack.includes(query)) {
                        return entries;
                    }
                }
                entries.push({ dev, _index: index });
                return entries;
            }, []);
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
            this.networkPolling = setInterval(() => this.fetchNetworkStatus(), 15000);
            try {
                await Alpine.store("conn").syncNetwork();
            } catch (e) {
                // Already surfaced to the user via showApiError inside syncNetwork();
                // a failed first sync must not prevent monitoring from starting —
                // the recurring autoSyncNetwork timer below will retry every 20s.
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

        async fetchState() {
            try {
                this.state = await api("GET", "/api/state");
                if (this.state?.product) {
                    this.product = this.state.product;
                }
                Alpine.store("conn").syncShowInfoDrafts();
                Alpine.store("conn").syncReceiveConfigDrafts();
                Alpine.store("conn").syncVirtualConfigDrafts();
            } catch (e) {
                /* ignore */
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
        },

        async applyBulkOutputType() {
            const group = this.currentBulkGroup();
            if (!group) return;
            await Alpine.store("conn").bulkApplyOutputType(group, Number(this.bulkOutputIndex) || 0, this.bulkOutputType);
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
        },
    });
});
