/**
 * look-controller.js - Cue Controller Alpine component.
 * Manual button board for cue playback.
 */

document.addEventListener("alpine:init", () => {
    Alpine.data("lookController", () => ({
        looks: [],
        cues: [],
        currentIndex: -1,
        playing: false,
        elapsed: 0,
        activeLookId: null,
        activeLookIds: [],
        selectedLookIds: [],
        defaultFadeTime: 0,
        crossfadeActive: false,
        crossfadeProgress: 0,
        blackout: false,
        controllerPrepared: false,
        preparingController: false,
        oscStatus: null,
        oscConfig: {
            enabled: true,
            port: 53001,
        },
        oscSaving: false,

        activeCueBoard: null,
        cueBoardModal: false,
        cueBoardMode: 'load',
        savedCueBoards: [],
        cueBoardName: '',
        cueBoardSaving: false,

        cueModal: false,
        cueEditIndex: -1,
        cueModalLooks: [],
        cueModalGroups: [],
        cueForm: {
            number: 1,
            name: 'Cue 1',
            fade_time: 2.0,
            auto_follow: false,
            follow_delay: 5.0,
            assignments: [],
        },
        targetModal: false,
        targetLookId: "",
        targetDeviceIps: [],

        _pollInterval: null,
        _lastOscPoll: 0,
        _looksChangedHandler: null,
        _modeChangedHandler: null,

        async init() {
            await this.loadLooks();
            await this.refresh();
            await this.fetchOscStatus(true);
            this._looksChangedHandler = () => this.loadLooks();
            this._modeChangedHandler = async (event) => {
                if (event?.detail?.mode === "controller") {
                    await this.loadLooks();
                    await this.refresh();
                    await this.fetchOscStatus(true);
                    await this.prepareControllerMode();
                } else {
                    this.controllerPrepared = false;
                }
            };
            document.addEventListener("primus:looks-changed", this._looksChangedHandler);
            document.addEventListener("primus:mode-changed", this._modeChangedHandler);
            this._pollInterval = setInterval(() => this._poll(), 200);
            if (Alpine.store("app").mode === "controller") await this.prepareControllerMode();
        },

        destroy() {
            if (this._looksChangedHandler) document.removeEventListener("primus:looks-changed", this._looksChangedHandler);
            if (this._modeChangedHandler) document.removeEventListener("primus:mode-changed", this._modeChangedHandler);
            if (this._pollInterval) clearInterval(this._pollInterval);
        },

        get playbackInfo() { return Alpine.store("app").playback; },
        get devices() { return Alpine.store("app").state?.devices || []; },
        get deviceGroups() { return Alpine.store("app").state?.device_groups || []; },
        get connectedCount() { return this.devices.filter(device => device.connected).length; },
        get cueFormValid() {
            if (!this.cueForm) return false;
            return this.cueForm.assignments.some(assignment => {
                if (assignment.action === 'blackout') return true;
                return !!assignment.look_id;
            });
        },

        async _poll() {
            if (Alpine.store("app").mode !== "controller") return;
            try {
                const data = await api("GET", "/api/cues");
                this.applyCueState(data);
                const now = Date.now();
                if (now - this._lastOscPoll > 250) {
                    this._lastOscPoll = now;
                    await this.fetchOscStatus(false);
                }
            } catch (e) {}
        },

        async refresh() {
            const data = await api("GET", "/api/cues");
            this.applyCueState(data);
        },

        applyCueState(data) {
            this.cues = (data.cues || []).map((cue, idx) => this.normalizeCue(cue, idx + 1));
            this.currentIndex = data.current_index ?? -1;
            this.playing = data.playing || false;
            this.activeLookId = data.active_look_id || null;
            this.activeLookIds = data.active_look_ids || (this.activeLookId ? [this.activeLookId] : []);
            this.crossfadeActive = data.crossfade_active || false;
            this.crossfadeProgress = data.crossfade_progress ?? 1;
            this.blackout = data.blackout || false;
            this.elapsed = data.elapsed || 0;
        },

        async loadLooks() {
            this.looks = await api("GET", "/api/looks");
        },

        applyOscStatus(data) {
            this.oscStatus = data || null;
        },

        syncOscConfigFromSettings(data) {
            const payload = data || this.oscStatus || {};
            const settings = payload.settings || {};
            this.oscConfig = {
                enabled: settings.enabled ?? payload.enabled ?? true,
                port: settings.port || 53001,
            };
        },

        async fetchOscStatus(syncForm = false) {
            try {
                const data = await api("GET", "/api/integrations/osc");
                this.applyOscStatus(data);
                if (syncForm) {
                    this.syncOscConfigFromSettings(data);
                }
            } catch (e) {
                this.oscStatus = { enabled: false, running: false, last_error: 'OSC status unavailable', history: [] };
            }
        },

        async saveOscConfig() {
            this.oscSaving = true;
            try {
                const port = Number(this.oscConfig.port);
                const data = await api("POST", "/api/integrations/osc", {
                    enabled: !!this.oscConfig.enabled,
                    port: Number.isInteger(port) && port >= 1 && port <= 65535 ? port : 53001,
                });
                this.applyOscStatus(data);
                this.syncOscConfigFromSettings(data);
            } catch (e) {
                Alpine.store("app").showApiError('OSC settings failed', e);
            } finally {
                this.oscSaving = false;
            }
        },

        oscStatusClass() {
            if (!this.oscStatus?.enabled) return 'osc-status-off';
            if (this.oscStatus?.running) return 'osc-status-listening';
            return 'osc-status-error';
        },

        oscStatusLabel() {
            if (!this.oscStatus) return 'Checking';
            if (!this.oscStatus.enabled) return 'Disabled';
            if (this.oscStatus.running) return 'Listening';
            return 'Offline';
        },

        oscEndpointLabel() {
            const bound = this.oscStatus?.bound || {};
            const settings = this.oscStatus?.settings || this.oscConfig;
            const port = bound.port || settings.port || 53001;
            return 'Listening on 0.0.0.0:' + port;
        },

        oscListenAddresses() {
            const addresses = this.oscStatus?.listen_addresses || [];
            if (addresses.length) return addresses;
            const port = this.oscStatus?.bound?.port || this.oscConfig.port || 53001;
            const targets = this.oscStatus?.listen_targets || [];
            return targets.map((target) => `${target.ip}:${port}`);
        },

        oscPacketStatsLabel() {
            const total = this.oscStatus?.packets_received || 0;
            const local = this.oscStatus?.packets_local || 0;
            const remote = this.oscStatus?.packets_remote || 0;
            if (!total) return 'No packets received yet';
            return `${total} total (${local} local, ${remote} LAN)`;
        },

        oscLanDebugHint() {
            const local = this.oscStatus?.packets_local || 0;
            const remote = this.oscStatus?.packets_remote || 0;
            if (!local || remote > 0) return '';
            const addresses = this.oscListenAddresses();
            if (!addresses.length) {
                return 'Only local OSC packets received so far. From another device, send to this Mac\'s LAN IP (not 127.0.0.1). If LAN packets still do not appear, allow incoming network connections for PrimusCentral in macOS Firewall.';
            }
            return `Only local OSC packets received so far. From another device, send to ${addresses.join(' or ')}. If LAN packets still do not appear, allow incoming network connections for PrimusCentral in macOS Firewall.`;
        },

        oscHistorySource(entry) {
            if (!entry) return 'unknown';
            if (entry.local) return 'local ' + (entry.remote || '');
            return entry.remote || 'unknown';
        },

        oscHistoryResult(entry) {
            if (!entry) return '';
            if (entry.ok) {
                return entry.cue_name ? ('OK -> ' + entry.cue_name) : 'OK';
            }
            return entry.error || 'failed';
        },

        formatOscArgs(args) {
            if (!Array.isArray(args) || !args.length) return '';
            return args.map((arg) => {
                if (arg === null || arg === undefined) return ' null';
                if (typeof arg === 'string') return ' ' + JSON.stringify(arg);
                return ' ' + String(arg);
            }).join('');
        },

        oscHistorySummary(entry) {
            if (!entry) return '';
            const args = this.formatOscArgs(entry.args);
            if (entry.ok) {
                const cue = entry.cue_name ? (' -> ' + entry.cue_name) : '';
                return (entry.address || '(packet)') + args + cue;
            }
            return (entry.address || 'Packet') + args + ' — ' + (entry.error || 'failed');
        },

        oscHistoryRows() {
            return this.oscStatus?.history || [];
        },

        cueExternalAddress(cue) {
            const match = (this.oscStatus?.cue_triggers || []).find(item => item.number === cue.number);
            return match?.qlab_address || ('/primus/cue/goto ' + cue.number);
        },

        async prepareControllerMode() {
            if (this.controllerPrepared || this.preparingController) return;
            this.preparingController = true;
            try {
                if (Alpine.store("app").uiProfileKey === "workshop") {
                    await this.applyWorkshopOutputPreset();
                }
                await Alpine.store("conn").connectAll();
                await api("POST", "/api/controller/blackout", { fade_time: 0 });
                this.controllerPrepared = true;
                await this.refresh();
                Alpine.store("app").showNotice("Cue Controller ready: saved devices connected and output blacked out.", "success");
            } catch (e) {
                Alpine.store("app").showApiError("Cue Controller setup failed", e);
            } finally {
                this.preparingController = false;
            }
        },

        async applyWorkshopOutputPreset() {
            const app = Alpine.store("app");
            const defaults = app.uiProfile?.defaultOutputs;
            if (!Array.isArray(defaults)) return;
            for (let oi = 0; oi < defaults.length; oi++) {
                const type = defaults[oi];
                if (!type || type === "none" || !app.isOutputTypeVisible(type)) continue;
                await api("POST", "/api/update", { output: oi, output_type: type });
            }
        },

        cleanTargetMode(value) {
            return ['look', 'all', 'group', 'devices'].includes(value) ? value : 'look';
        },

        normalizeAssignment(raw = {}, cue = {}) {
            const action = raw.action || raw.type || (raw.blackout ? 'blackout' : 'look');
            if (action === 'blackout') return { action: 'blackout' };
            const assignment = {
                action: 'look',
                look_id: String(raw.look_id || ''),
                target_mode: this.cleanTargetMode(raw.target_mode || cue.target_mode || 'look'),
                device_group_id: String(raw.device_group_id || cue.device_group_id || ''),
                device_ips: Array.isArray(raw.device_ips) ? [...raw.device_ips] : (Array.isArray(cue.device_ips) ? [...cue.device_ips] : []),
                note: raw.note || '',
            };
            if (assignment.target_mode !== 'group') assignment.device_group_id = '';
            if (assignment.target_mode !== 'devices') assignment.device_ips = [];
            return assignment;
        },

        normalizeCue(cue = {}, fallbackNumber = 1) {
            let assignments = [];
            if (cue.blackout) assignments.push({ action: 'blackout' });
            if (Array.isArray(cue.assignments)) {
                assignments = assignments.concat(cue.assignments.map(item => this.normalizeAssignment(item, cue)));
            }
            if (!assignments.length && cue.look_id) {
                assignments.push(this.normalizeAssignment({
                    look_id: cue.look_id,
                    target_mode: cue.target_mode || 'look',
                    device_group_id: cue.device_group_id || '',
                    device_ips: cue.device_ips || [],
                }, cue));
            }
            const number = Number.isFinite(Number(cue.number)) ? Number(cue.number) : fallbackNumber;
            return {
                number,
                name: cue.name || ('Cue ' + number),
                fade_time: Number.isFinite(Number(cue.fade_time)) ? Number(cue.fade_time) : 0,
                auto_follow: !!cue.auto_follow,
                follow_delay: Number.isFinite(Number(cue.follow_delay)) ? Number(cue.follow_delay) : 5,
                assignments,
            };
        },

        serializeCue(form) {
            const assignments = form.assignments
                .map(assignment => {
                    if (assignment.action === 'blackout') return { action: 'blackout' };
                    const out = {
                        action: 'look',
                        look_id: assignment.look_id,
                        target_mode: this.cleanTargetMode(assignment.target_mode),
                    };
                    if (assignment.note) out.note = assignment.note;
                    if (out.target_mode === 'group' && assignment.device_group_id) {
                        out.device_group_id = assignment.device_group_id;
                    }
                    if (out.target_mode === 'devices') {
                        out.device_ips = [...(assignment.device_ips || [])];
                    }
                    return out;
                })
                .filter(assignment => assignment.action === 'blackout' || assignment.look_id);
            const cue = {
                number: form.number,
                name: form.name || ('Cue ' + form.number),
                fade_time: Number(form.fade_time) || 0,
                auto_follow: false,
                follow_delay: 0,
                assignments,
            };
            const firstLook = assignments.length === 1 && assignments[0].action === 'look' ? assignments[0] : null;
            if (firstLook) {
                cue.look_id = firstLook.look_id;
                cue.target_mode = firstLook.target_mode;
                if (firstLook.device_group_id) cue.device_group_id = firstLook.device_group_id;
                if (firstLook.device_ips) cue.device_ips = [...firstLook.device_ips];
            }
            if (assignments.length && assignments.every(assignment => assignment.action === 'blackout')) {
                cue.blackout = true;
            }
            return cue;
        },

        lookById(lookId) {
            const id = String(lookId || '');
            return this.looks.find(look => String(look.id) === id) || null;
        },

        lookName(lookId) {
            return this.lookById(lookId)?.name || "(unknown)";
        },

        lookOutputs(look) {
            return (look?.outputs || []).map(output => output.port + ':' + output.type).join(', ');
        },

        lookThumbStyle(look) {
            if (!look) return 'background: var(--bg-secondary)';
            const tracks = look.tracks || [];
            const hasSegments = tracks.some(track => (track.segments || []).length > 0);
            return hasSegments
                ? 'background: linear-gradient(135deg, var(--accent-dim), var(--bg-tertiary))'
                : 'background: var(--bg-secondary)';
        },

        lookDeviceIps(look) {
            if (!Array.isArray(look?.device_ips)) return null;
            const currentIps = this.devices.map(device => device.ip);
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
                const dev = this.devices.find(device => device.ip === ips[0]);
                return dev ? dev.name : ips[0];
            }
            return ips.length + ' target devices';
        },

        lookTargetDevices(look) {
            const ips = this.lookDeviceIps(look);
            if (ips === null) return this.devices;
            return ips.map(ip => this.devices.find(device => device.ip === ip) || {
                ip,
                name: ip,
                connected: false,
            });
        },

        assignmentLook(assignment) {
            return assignment?.action === 'look' ? this.lookById(assignment.look_id) : null;
        },

        assignmentName(assignment) {
            if (assignment?.action === 'blackout') return 'Blackout';
            return this.lookName(assignment?.look_id);
        },

        assignmentTargetLabel(assignment) {
            if (assignment?.action === 'blackout') return 'All devices';
            if (assignment.target_mode === 'all') return 'All devices';
            if (assignment.target_mode === 'group') {
                const group = this.deviceGroups.find(item => String(item.id) === String(assignment.device_group_id));
                return group ? group.name : 'Missing group';
            }
            if (assignment.target_mode === 'devices') {
                const count = (assignment.device_ips || []).length;
                if (!count) return 'No target devices';
                if (count === 1) {
                    const dev = this.devices.find(device => device.ip === assignment.device_ips[0]);
                    return dev ? dev.name : assignment.device_ips[0];
                }
                return count + ' selected devices';
            }
            const look = this.assignmentLook(assignment);
            return look ? this.lookTargetLabel(look) : 'Look target';
        },

        cueAssignments(cue) {
            return this.normalizeCue(cue).assignments;
        },

        cueLookSummary(cue) {
            const assignments = this.cueAssignments(cue);
            if (!assignments.length) return 'No assignments';
            return assignments.map(assignment => this.assignmentName(assignment)).join(' + ');
        },

        cueTargetSummary(cue) {
            const labels = this.cueAssignments(cue).map(assignment => this.assignmentTargetLabel(assignment));
            const unique = [...new Set(labels)];
            if (!unique.length) return 'No targets';
            return unique.join(' / ');
        },

        cueCardClass(idx) {
            return {
                'cue-card-active': this.isActive(idx),
            };
        },

        activeLooksLabel() {
            if (this.blackout) return 'Blackout';
            const count = this.activeLookIds.length;
            if (!count) return 'No Looks live';
            if (count === 1) return this.lookName(this.activeLookIds[0]);
            return count + ' Looks live';
        },

        progressPercent() {
            return Math.round((this.crossfadeProgress || 0) * 100);
        },

        async triggerCue(number) {
            try {
                await api("POST", "/api/cues/goto", { number });
                await this.refresh();
            } catch (e) {
                Alpine.store("app").showApiError('Cue trigger failed', e);
            }
        },

        async doBlackout() {
            try {
                await api("POST", "/api/controller/blackout", { fade_time: this.defaultFadeTime });
                await this.refresh();
            } catch (e) {
                Alpine.store("app").showApiError('Blackout failed', e);
            }
        },

        nextCueNumber() {
            if (!this.cues.length) return 1;
            return Math.max(...this.cues.map(cue => cue.number || 0)) + 1;
        },

        blankCueForm(number = null) {
            const cueNumber = number || this.nextCueNumber();
            return {
                number: cueNumber,
                name: 'Cue ' + cueNumber,
                fade_time: 2.0,
                auto_follow: false,
                follow_delay: 5.0,
                assignments: [],
            };
        },

        snapshotCueModalOptions() {
            this.cueModalLooks = this.looks.map(look => ({ id: String(look.id), name: look.name }));
            this.cueModalGroups = this.deviceGroups.map(group => ({
                id: String(group.id),
                name: group.name,
            }));
        },

        ensureAssignmentKeys(form = this.cueForm) {
            if (!form?.assignments) return;
            form.assignments.forEach((assignment) => {
                if (!assignment._key) assignment._key = crypto.randomUUID();
            });
        },

        setAssignmentTargetMode(assignment, targetMode) {
            assignment.target_mode = this.cleanTargetMode(targetMode);
            if (assignment.target_mode !== 'group') assignment.device_group_id = '';
            if (assignment.target_mode !== 'devices') assignment.device_ips = [];
        },

        reconcileAssignmentOptions() {
            if (!this.cueForm?.assignments) return;
            const sourceCue = this.cueEditIndex >= 0 ? this.cues[this.cueEditIndex] : null;
            for (const assignment of this.cueForm.assignments) {
                if (assignment.action !== 'look') continue;
                let lookId = String(assignment.look_id || '').trim();
                if (!lookId && sourceCue?.look_id) {
                    lookId = String(sourceCue.look_id).trim();
                }
                if (lookId && this.cueModalLooks.some(look => look.id === lookId)) {
                    assignment.look_id = lookId;
                }
                if (assignment.target_mode === 'group') {
                    const groupId = String(assignment.device_group_id || sourceCue?.device_group_id || '').trim();
                    if (groupId && this.cueModalGroups.some(group => group.id === groupId)) {
                        assignment.device_group_id = groupId;
                    }
                }
            }
        },

        openAddCue() {
            this.cueEditIndex = -1;
            this.snapshotCueModalOptions();
            this.cueForm = this.blankCueForm();
            if (this.looks.length) this.addLookAssignment();
            this.ensureAssignmentKeys();
            this.cueModal = true;
        },

        openEditCue(cue, idx) {
            this.cueEditIndex = idx;
            this.snapshotCueModalOptions();
            const source = this.cues[idx] ?? cue;
            this.cueForm = JSON.parse(JSON.stringify(this.normalizeCue(source, idx + 1)));
            this.ensureAssignmentKeys();
            this.reconcileAssignmentOptions();
            this.cueModal = true;
            this.$nextTick(() => this.reconcileAssignmentOptions());
        },

        closeCueModal() {
            this.cueModal = false;
            this.cueEditIndex = -1;
            this.cueForm = this.blankCueForm();
            this.cueModalLooks = [];
            this.cueModalGroups = [];
        },

        addLookAssignment() {
            if (!this.cueForm) this.cueForm = this.blankCueForm();
            this.cueForm.assignments = this.cueForm.assignments.filter(item => item.action !== 'blackout');
            this.cueForm.assignments.push({
                _key: crypto.randomUUID(),
                action: 'look',
                look_id: String(this.cueModalLooks[0]?.id || this.looks[0]?.id || ''),
                target_mode: 'look',
                device_group_id: String(this.cueModalGroups[0]?.id || this.deviceGroups[0]?.id || ''),
                device_ips: [],
                note: '',
            });
        },

        addBlackoutAssignment() {
            if (!this.cueForm) this.cueForm = this.blankCueForm();
            this.cueForm.assignments = [{ _key: crypto.randomUUID(), action: 'blackout' }];
            if (!this.cueForm.name || this.cueForm.name.startsWith('Cue ')) this.cueForm.name = 'Blackout';
        },

        removeAssignment(idx) {
            if (!this.cueForm) return;
            this.cueForm.assignments.splice(idx, 1);
        },

        moveAssignment(idx, dir) {
            const next = idx + dir;
            if (!this.cueForm || next < 0 || next >= this.cueForm.assignments.length) return;
            const item = this.cueForm.assignments[idx];
            this.cueForm.assignments.splice(idx, 1);
            this.cueForm.assignments.splice(next, 0, item);
        },

        toggleAssignmentDevice(assignment, ip) {
            if (!assignment.device_ips) assignment.device_ips = [];
            if (assignment.device_ips.includes(ip)) {
                assignment.device_ips = assignment.device_ips.filter(savedIp => savedIp !== ip);
            } else {
                assignment.device_ips = [...assignment.device_ips, ip];
            }
        },

        async saveCueForm() {
            if (!this.cueFormValid) return;
            const cue = this.serializeCue(this.cueForm);
            if (this.cueEditIndex >= 0) {
                this.cues.splice(this.cueEditIndex, 1, cue);
            } else {
                this.cues.push(cue);
            }
            this.cues.forEach((item, idx) => { item.number = idx + 1; });
            try {
                await this.saveCues();
                this.closeCueModal();
                await this.refresh();
            } catch (e) {
                Alpine.store("app").showApiError('Cue save failed', e);
            }
        },

        async deleteCueFromModal() {
            if (this.cueEditIndex < 0 || !confirm('Delete this cue?')) return;
            await this.removeCue(this.cueEditIndex);
            this.closeCueModal();
        },

        async removeCue(idx) {
            this.cues.splice(idx, 1);
            this.cues.forEach((cue, cueIndex) => { cue.number = cueIndex + 1; });
            await this.saveCues();
            await this.refresh();
        },

        async saveCues() {
            await api("POST", "/api/cues", { cues: this.cues.map(cue => this.serializeCue(this.normalizeCue(cue))) });
        },

        async fetchCueBoards() {
            const data = await api("GET", "/api/cue_boards");
            this.savedCueBoards = data.boards || [];
        },

        openSaveCueBoard() {
            this.cueBoardMode = 'save';
            this.cueBoardName = this.activeCueBoard?.name || '';
            this.cueBoardModal = true;
        },

        async openLoadCueBoard() {
            this.cueBoardMode = 'load';
            this.cueBoardModal = true;
            try {
                await this.fetchCueBoards();
            } catch (e) {
                Alpine.store("app").showApiError('Could not load cue boards', e);
            }
        },

        closeCueBoardModal() {
            this.cueBoardModal = false;
            this.cueBoardName = '';
        },

        async saveCueBoard() {
            const name = String(this.cueBoardName || '').trim();
            if (!name) return;
            this.cueBoardSaving = true;
            try {
                const payload = {
                    name,
                    cues: this.cues.map(cue => this.serializeCue(this.normalizeCue(cue))),
                };
                if (this.activeCueBoard?.id) {
                    payload.id = this.activeCueBoard.id;
                }
                const data = await api("POST", "/api/cue_boards", payload);
                this.activeCueBoard = data.board;
                this.closeCueBoardModal();
            } catch (e) {
                Alpine.store("app").showApiError('Cue board save failed', e);
            } finally {
                this.cueBoardSaving = false;
            }
        },

        async loadCueBoard(boardId) {
            try {
                const data = await api("POST", `/api/cue_boards/${boardId}/load`, {});
                this.applyCueState(data);
                this.activeCueBoard = data.board || null;
                this.closeCueBoardModal();
            } catch (e) {
                Alpine.store("app").showApiError('Cue board load failed', e);
            }
        },

        async deleteCueBoard(boardId) {
            if (!confirm('Delete this saved cue board?')) return;
            try {
                await api("DELETE", `/api/cue_boards/${boardId}`);
                if (this.activeCueBoard?.id === boardId) {
                    this.activeCueBoard = null;
                }
                await this.fetchCueBoards();
            } catch (e) {
                Alpine.store("app").showApiError('Cue board delete failed', e);
            }
        },

        cueBoardSubtitle() {
            if (this.activeCueBoard?.name) {
                return `Loaded board: ${this.activeCueBoard.name}`;
            }
            return 'Unsaved board';
        },

        isActive(idx) { return this.playing && idx === this.currentIndex; },

        targetPillClass(dev) {
            return dev?.connected ? 'look-target-pill-live' : 'look-target-pill-offline';
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

        openTargetEditor(look) {
            this.targetLookId = look.id;
            this.targetDeviceIps = Array.isArray(look.device_ips)
                ? this.lookDeviceIps(look)
                : this.devices.map(device => device.ip);
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
            const currentIps = this.devices.map(device => device.ip);
            const deviceIps = this.targetDeviceIps.filter(ip => currentIps.includes(ip));
            try {
                const saved = await api("POST", "/api/looks/save", {
                    ...look,
                    device_ips: deviceIps,
                });
                const idx = this.looks.findIndex(item => item.id === saved.id);
                if (idx >= 0) this.looks.splice(idx, 1, saved);
                this.targetModal = false;
                document.dispatchEvent(new CustomEvent('primus:looks-changed', { detail: { look: saved } }));
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
    }));
});