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
        notice: null,
        _noticeTimer: null,

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
            this.showNotice('Mixer preview target: ' + this.mixerPreviewTarget.label, 'info', 2000);
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
                ? 'Double-click to rename'
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

        async connect(di) { await api("POST", "/api/connect", { device: di }); },
        async disconnect(di) { await api("POST", "/api/disconnect", { device: di }); },
        async connectAll() { await api("POST", "/api/connect_all"); },
        async disconnectAll() { await api("POST", "/api/disconnect_all"); },

        async discover() {
            this.discovering = true;
            try {
                this.discovered = await api("POST", "/api/discover");
                const count = this.discovered.length;
                Alpine.store("app").showNotice(
                    count
                        ? 'Discovery found ' + count + ' device' + (count === 1 ? '' : 's') + '.'
                        : 'Discovery finished with no new devices found.',
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
                    added
                        ? 'Added ' + (node.short_name || node.ip) + '.'
                        : (node.short_name || node.ip) + ' is already in the device list.',
                    added ? 'success' : 'info'
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
                    result?.status === 'added'
                        ? 'Added device at ' + ip + '.'
                        : 'Device ' + ip + ' is already in the list.',
                    result?.status === 'added' ? 'success' : 'info'
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
            this.ipConfigIp = dev?.ip || "";
            this.ipConfigGateway = dev?.ip ? dev.ip.replace(/\.\d+$/, ".1") : "";
            this.ipConfigSubnet = "255.255.255.0";
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
            try {
                await api("POST", "/api/set_device_ip", { device: di, ip: ip, gateway: gw, subnet: sn });
                Alpine.store("app").showNotice(name + ' is rebooting with static IP ' + ip + '.', 'warn', 4500);
                this.ipConfigDevice = -1;
            } catch (e) {
                Alpine.store("app").showApiError('Static IP update failed', e);
            }
        },

        async revertDhcp(di) {
            const name = this.devices[di]?.name || 'device';
            try {
                await api("POST", "/api/revert_device_dhcp", { device: di });
                Alpine.store("app").showNotice(name + ' is rebooting and returning to DHCP.', 'warn', 4500);
                this.ipConfigDevice = -1;
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
