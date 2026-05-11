/**
 * look-controller.js — Look Controller Alpine component.
 * Control board for saved Looks and target-device playback.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("lookController", () => ({
        // -- Control Panel --
        looks: [],
        activeLookId: null,
        activeLookIds: [],
        selectedLookIds: [],
        defaultFadeTime: 0,

        // -- Crossfade state --
        crossfadeActive: false,
        crossfadeProgress: 0,
        blackout: false,

        // -- Cue list --
        cues: [],
        currentIndex: -1,
        playing: false,
        elapsed: 0,
        _pollInterval: null,
        _looksChangedHandler: null,
        _modeChangedHandler: null,

        // -- Modals --
        addModal: false,
        addLookId: "",
        addFadeTime: 2.0,
        addAutoFollow: false,
        addFollowDelay: 5.0,
        addTargetMode: "look",       // "look", "all", "group", "devices"
        addGroupId: "",
        addDeviceIps: [],
        targetModal: false,
        targetLookId: "",
        targetDeviceIps: [],

        async init() {
            await this.loadLooks();
            await this.refresh();
            // Keyboard shortcuts for the visible control board only.
            this._keyHandler = (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
                if (Alpine.store("app").mode !== "controller") return;
                if (e.code === "Space") { e.preventDefault(); this.triggerSelectedLooks(); }
                if (e.code === "Escape") { e.preventDefault(); this.stop(); }
            };
            document.addEventListener("keydown", this._keyHandler);
            this._looksChangedHandler = () => this.loadLooks();
            this._modeChangedHandler = (event) => {
                if (event?.detail?.mode === "controller") this.loadLooks();
            };
            document.addEventListener("primus:looks-changed", this._looksChangedHandler);
            document.addEventListener("primus:mode-changed", this._modeChangedHandler);
            this._pollInterval = setInterval(() => this._poll(), 200);
        },

        destroy() {
            if (this._keyHandler) document.removeEventListener("keydown", this._keyHandler);
            if (this._looksChangedHandler) {
                document.removeEventListener("primus:looks-changed", this._looksChangedHandler);
            }
            if (this._modeChangedHandler) {
                document.removeEventListener("primus:mode-changed", this._modeChangedHandler);
            }
            if (this._pollInterval) clearInterval(this._pollInterval);
        },

        async _poll() {
            if (Alpine.store("app").mode !== "controller") return;
            try {
                const data = await api("GET", "/api/cues");
                this.elapsed = data.elapsed || 0;
                this.currentIndex = data.current_index ?? -1;
                this.playing = data.playing || false;
                this.activeLookId = data.active_look_id || null;
                this.activeLookIds = data.active_look_ids || (this.activeLookId ? [this.activeLookId] : []);
                this.crossfadeActive = data.crossfade_active || false;
                this.crossfadeProgress = data.crossfade_progress ?? 1;
                this.blackout = data.blackout || false;
            } catch(e) {}
        },

        async refresh() {
            const data = await api("GET", "/api/cues");
            this.cues = data.cues || [];
            this.currentIndex = data.current_index ?? -1;
            this.playing = data.playing || false;
            this.activeLookId = data.active_look_id || null;
            this.activeLookIds = data.active_look_ids || (this.activeLookId ? [this.activeLookId] : []);
            this.crossfadeActive = data.crossfade_active || false;
            this.crossfadeProgress = data.crossfade_progress ?? 1;
            this.blackout = data.blackout || false;
        },

        async loadLooks() {
            this.looks = await api("GET", "/api/looks");
        },

        lookName(lookId) {
            const l = this.looks.find(l => l.id === lookId);
            return l ? l.name : "(unknown)";
        },

        activeLooksLabel() {
            const count = this.activeLookIds.length;
            if (!count) return 'No Looks live';
            if (count === 1) return this.lookName(this.activeLookIds[0]);
            return count + ' Looks live';
        },

        get playbackInfo() { return Alpine.store("app").playback; },
        get devices() { return Alpine.store("app").state?.devices || []; },
        get deviceGroups() { return Alpine.store("app").state?.device_groups || []; },

        controllerPanelStateClass() {
            if (this.playbackInfo.source === 'controller') {
                return 'panel-owner-live';
            }
            if (this.playing || this.activeLookId) {
                return 'panel-owner-warn';
            }
            return 'panel-owner-idle';
        },

        controllerPanelTitle() {
            if (this.playbackInfo.source === 'controller') {
                return 'Controller owns output';
            }
            if (this.playing || this.activeLookId) {
                return 'Controller is queued but not live';
            }
            return 'Controller is standing by';
        },

        controllerPanelDetail() {
            if (this.playbackInfo.source === 'controller') {
                return 'Control board output is live on ' + this.playbackInfo.target_label.toLowerCase() + '.';
            }
            if (this.playing || this.activeLookId) {
                return 'Controller state exists, but output is currently owned by ' + this.playbackInfo.label.toLowerCase() + '.';
            }
            return 'Trigger a Look to take output ownership from idle.';
        },

        lookOutputs(look) {
            return (look.outputs || []).map(o => o.port + ':' + o.type).join(', ');
        },

        lookDeviceIps(look) {
            if (!Array.isArray(look?.device_ips)) return null;
            const currentIps = this.devices.map(d => d.ip);
            const ips = [];
            for (const ip of look.device_ips) {
                if (currentIps.includes(ip) && !ips.includes(ip)) ips.push(ip);
            }
            return ips;
        },

        lookTargetLabel(look) {
            const ips = this.lookDeviceIps(look);
            if (ips === null) return 'All devices';
            if (!ips.length) return 'No target devices';
            if (ips.length === 1) {
                const dev = this.devices.find(d => d.ip === ips[0]);
                return dev ? dev.name : ips[0];
            }
            return ips.length + ' target devices';
        },

        lookTargetDevices(look) {
            const ips = this.lookDeviceIps(look);
            if (ips === null) return this.devices;
            return ips.map(ip => this.devices.find(d => d.ip === ip) || {
                ip,
                name: ip,
                connected: false,
            });
        },

        targetPillClass(dev) {
            return dev?.connected ? 'look-target-pill-live' : 'look-target-pill-offline';
        },

        selectedAddLook() {
            return this.looks.find(l => l.id === this.addLookId) || null;
        },

        lookThumbStyle(look) {
            // Gradient from first track's first segment colors, or fallback
            const tracks = look.tracks || [];
            const colors = [];
            for (const t of tracks) {
                for (const seg of (t.segments || [])) {
                    return `background:linear-gradient(135deg, var(--accent-dim), var(--bg-tertiary))`;
                }
            }
            return `background: var(--bg-tertiary)`;
        },

        // ── Control Panel ──
        async activateLook(lookId) {
            try {
                const result = await api("POST", "/api/controller/activate", {
                    look_id: lookId,
                    fade_time: this.defaultFadeTime,
                });
                if (result?.ok) await this.refresh();
            } catch (e) {
                Alpine.store("app").showApiError('Look trigger failed', e);
            }
        },

        async triggerSelectedLooks() {
            if (!this.selectedLookIds.length) {
                Alpine.store("app").showNotice('Select one or more Looks first.', 'info');
                return;
            }
            try {
                const result = await api("POST", "/api/controller/activate_many", {
                    look_ids: this.selectedLookIds,
                    fade_time: this.defaultFadeTime,
                });
                if (result?.ok) await this.refresh();
            } catch (e) {
                Alpine.store("app").showApiError('Look trigger failed', e);
            }
        },

        async deactivateLook(lookId) {
            try {
                await api("POST", "/api/controller/deactivate_look", { look_id: lookId });
                await this.refresh();
            } catch (e) {
                Alpine.store("app").showApiError('Look stop failed', e);
            }
        },

        async doBlackout() {
            await api("POST", "/api/controller/blackout", {
                fade_time: this.defaultFadeTime,
            });
            await this.refresh();
        },

        isLookActive(lookId) {
            return this.activeLookIds.includes(lookId) && !this.blackout;
        },

        isLookSelected(lookId) {
            return this.selectedLookIds.includes(lookId);
        },

        toggleLookSelection(lookId) {
            if (this.isLookSelected(lookId)) {
                this.selectedLookIds = this.selectedLookIds.filter(id => id !== lookId);
            } else {
                this.selectedLookIds = [...this.selectedLookIds, lookId];
            }
        },

        clearSelectedLooks() {
            this.selectedLookIds = [];
        },

        openTargetEditor(look) {
            this.targetLookId = look.id;
            this.targetDeviceIps = Array.isArray(look.device_ips)
                ? this.lookDeviceIps(look)
                : this.devices.map(d => d.ip);
            this.targetModal = true;
        },

        targetEditLook() {
            return this.looks.find(look => look.id === this.targetLookId) || null;
        },

        toggleTargetDevice(ip) {
            if (this.targetDeviceIps.includes(ip)) {
                this.targetDeviceIps = this.targetDeviceIps.filter(savedIp => savedIp !== ip);
            } else {
                this.targetDeviceIps = [...this.targetDeviceIps, ip];
            }
        },

        async saveTargetEditor() {
            const look = this.targetEditLook();
            if (!look) return;
            const currentIps = this.devices.map(d => d.ip);
            const deviceIps = this.targetDeviceIps.filter(ip => currentIps.includes(ip));
            try {
                const saved = await api("POST", "/api/looks/save", {
                    ...look,
                    device_ips: deviceIps,
                });
                const idx = this.looks.findIndex(item => item.id === saved.id);
                if (idx >= 0) this.looks.splice(idx, 1, saved);
                this.targetModal = false;
                document.dispatchEvent(new CustomEvent('primus:looks-changed', {
                    detail: { look: saved },
                }));
            } catch (e) {
                Alpine.store("app").showApiError('Target update failed', e);
            }
        },

        async deleteLook(look) {
            if (!look || !confirm('Delete Look "' + look.name + '"?')) return;
            try {
                await api("DELETE", "/api/looks/" + look.id);
                this.selectedLookIds = this.selectedLookIds.filter(id => id !== look.id);
                this.activeLookIds = this.activeLookIds.filter(id => id !== look.id);
                await this.loadLooks();
                await this.refresh();
                document.dispatchEvent(new CustomEvent('primus:looks-changed'));
            } catch (e) {
                Alpine.store("app").showApiError('Delete Look failed', e);
            }
        },

        // ── Transport ──
        async go() {
            await api("POST", "/api/cues/go");
            await this.refresh();
        },

        async stop() {
            await api("POST", "/api/cues/stop");
            await this.refresh();
        },

        async goToCue(number) {
            await api("POST", "/api/cues/goto", { number });
            await this.refresh();
        },

        // ── Cue management ──
        nextCueNumber() {
            if (this.cues.length === 0) return 1;
            return Math.max(...this.cues.map(c => c.number)) + 1;
        },

        openAddCue() {
            this.addLookId = this.looks.length ? this.looks[0].id : "";
            this.addFadeTime = 2.0;
            this.addAutoFollow = false;
            this.addFollowDelay = 5.0;
            this.addTargetMode = "look";
            this.addGroupId = this.deviceGroups.length ? this.deviceGroups[0].id : "";
            this.addDeviceIps = [];
            this.addModal = true;
        },

        async addCue() {
            if (!this.addLookId) return;
            const look = this.looks.find(l => l.id === this.addLookId);
            const cue = {
                number: this.nextCueNumber(),
                look_id: this.addLookId,
                name: look ? look.name : "Cue",
                fade_time: this.addFadeTime,
                auto_follow: this.addAutoFollow,
                follow_delay: this.addFollowDelay,
                target_mode: this.addTargetMode,
            };
            if (this.addTargetMode === "all") {
                cue.target_mode = "all";
            } else if (this.addTargetMode === "group" && this.addGroupId) {
                cue.device_group_id = this.addGroupId;
            } else if (this.addTargetMode === "devices" && this.addDeviceIps.length) {
                cue.device_ips = [...this.addDeviceIps];
            }
            this.cues.push(cue);
            try {
                await this.saveCues();
            } catch (e) {
                this.cues.pop();
                console.error("Failed to save cue:", e);
                return;
            }
            this.addModal = false;
        },

        async removeCue(idx) {
            this.cues.splice(idx, 1);
            this.cues.forEach((c, i) => c.number = i + 1);
            await this.saveCues();
        },

        async moveCue(idx, dir) {
            const newIdx = idx + dir;
            if (newIdx < 0 || newIdx >= this.cues.length) return;
            const temp = this.cues[idx];
            this.cues[idx] = this.cues[newIdx];
            this.cues[newIdx] = temp;
            this.cues.forEach((c, i) => c.number = i + 1);
            await this.saveCues();
        },

        async updateCueField(idx, field, value) {
            this.cues[idx][field] = value;
            await this.saveCues();
        },

        async saveCues() {
            await api("POST", "/api/cues", { cues: this.cues });
        },

        isActive(idx) { return this.playing && idx === this.currentIndex; },
        isStandby(idx) {
            if (!this.playing) return idx === 0;
            return idx === this.currentIndex + 1;
        },

        cueTargetLabel(cue) {
            if (cue.target_mode === 'all') return 'All';
            if (cue.device_group_id) {
                const g = this.deviceGroups.find(g => g.id === cue.device_group_id);
                return g ? g.name : '(deleted group)';
            }
            if (cue.device_ips && cue.device_ips.length) {
                return cue.device_ips.length + ' device' + (cue.device_ips.length > 1 ? 's' : '');
            }
            const look = this.looks.find(l => l.id === cue.look_id);
            return look ? this.lookTargetLabel(look) : 'Look target';
        },

        addTargetSummary() {
            if (this.addTargetMode === 'look') {
                const look = this.selectedAddLook();
                if (!look) return 'No Look selected.';
                return 'Cue will use this Look target: ' + this.lookTargetLabel(look) + '.';
            }
            if (this.addTargetMode === 'group') {
                const group = this.deviceGroups.find(g => g.id === this.addGroupId);
                if (!group) return 'No group selected.';
                const count = (group.device_ips || []).length;
                return 'Cue will target group ' + group.name + ' (' + count + ' device' + (count === 1 ? '' : 's') + ').';
            }
            if (this.addTargetMode === 'devices') {
                const count = this.addDeviceIps.length;
                if (!count) return 'No devices selected yet.';
                return 'Cue will target ' + count + ' selected device' + (count === 1 ? '' : 's') + '.';
            }
            return 'Cue will target all available devices.';
        },

        toggleDeviceIp(ip) {
            const idx = this.addDeviceIps.indexOf(ip);
            if (idx >= 0) {
                this.addDeviceIps.splice(idx, 1);
            } else {
                this.addDeviceIps.push(ip);
            }
        },

        nextCueName() {
            let nextIdx;
            if (!this.playing) {
                nextIdx = 0;
            } else {
                nextIdx = this.currentIndex + 1;
                if (nextIdx >= this.cues.length) nextIdx = 0;
            }
            return this.cues[nextIdx] ? this.cues[nextIdx].name : '-';
        },
    }));
});
