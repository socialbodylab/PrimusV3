/**
 * look-controller.js — Look Controller Alpine component.
 * Control Panel (look palette with instant activation) +
 * Theatre-style cue list with GO / STOP, crossfade, and auto-follow.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("lookController", () => ({
        // -- Control Panel --
        looks: [],
        activeLookId: null,
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

        // -- Modals --
        addModal: false,
        addLookId: "",
        addFadeTime: 2.0,
        addAutoFollow: false,
        addFollowDelay: 5.0,
        addTargetMode: "all",       // "all", "group", "devices"
        addGroupId: "",
        addDeviceIps: [],

        async init() {
            await this.loadLooks();
            await this.refresh();
            // Keyboard shortcuts: Space=GO, Escape=STOP
            this._keyHandler = (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
                if (Alpine.store("app").mode !== "controller") return;
                if (e.code === "Space") { e.preventDefault(); this.go(); }
                if (e.code === "Escape") { e.preventDefault(); this.stop(); }
            };
            document.addEventListener("keydown", this._keyHandler);
            this._pollInterval = setInterval(() => this._poll(), 200);
        },

        destroy() {
            if (this._keyHandler) document.removeEventListener("keydown", this._keyHandler);
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
                return 'Cue playback is live on ' + this.playbackInfo.target_label.toLowerCase() + '.';
            }
            if (this.playing || this.activeLookId) {
                return 'Controller state exists, but output is currently owned by ' + this.playbackInfo.label.toLowerCase() + '.';
            }
            return 'Use GO or activate a look to take output ownership from idle.';
        },

        lookOutputs(look) {
            return (look.outputs || []).map(o => o.port + ':' + o.type).join(', ');
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
            const result = await api("POST", "/api/controller/activate", {
                look_id: lookId,
                fade_time: this.defaultFadeTime,
            });
            if (result?.ok) {
                await this.refresh();
            }
        },

        async doBlackout() {
            await api("POST", "/api/controller/blackout", {
                fade_time: this.defaultFadeTime,
            });
        },

        isLookActive(lookId) {
            return this.activeLookId === lookId && !this.blackout;
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
            this.addTargetMode = "all";
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
            };
            if (this.addTargetMode === "group" && this.addGroupId) {
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
            if (cue.device_group_id) {
                const g = this.deviceGroups.find(g => g.id === cue.device_group_id);
                return g ? g.name : '(deleted group)';
            }
            if (cue.device_ips && cue.device_ips.length) {
                return cue.device_ips.length + ' device' + (cue.device_ips.length > 1 ? 's' : '');
            }
            return 'All';
        },

        addTargetSummary() {
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
