/* marius.js — Marius BLE editor panel for Radius Central */

function mariusEditor() {
    return {
        deviceIdx:      0,
        puckName:       '',
        pressActions:   [],
        releaseActions: [],
        status:         null,   // {ok: bool|null, msg: string}

        get audioDevices() {
            return $store.conn.devices
                .map((d, i) => ({ ...d, _di: i }))
                .filter(d => d.is_audio);
        },

        get selectedDevice() {
            const devs = this.audioDevices;
            return this.deviceIdx < devs.length ? devs[this.deviceIdx] : null;
        },

        emptyAction() {
            return {
                type: 'audio_play',
                // audio_play / artnet_audio
                file: '', volume: '', loop: false,
                // osc
                osc_addr: '', target_ip: '', target_port: '',
                // artnet_audio
                cmd: 1,
                // artnet_dmx
                universe: 0, channel: 1, value: 255,
            };
        },

        addAction(event) {
            (event === 'press' ? this.pressActions : this.releaseActions)
                .push(this.emptyAction());
        },

        removeAction(event, idx) {
            (event === 'press' ? this.pressActions : this.releaseActions)
                .splice(idx, 1);
        },

        moveAction(event, idx, dir) {
            const list = event === 'press' ? this.pressActions : this.releaseActions;
            const to = idx + dir;
            if (to < 0 || to >= list.length) return;
            [list[idx], list[to]] = [list[to], list[idx]];
        },

        needsFile(a)    { return a.type === 'audio_play' || (a.type === 'artnet_audio' && (a.cmd == 1 || a.cmd == 2)); },
        needsVolume(a)  { return a.type === 'audio_play' || a.type === 'artnet_audio'; },
        needsLoop(a)    { return a.type === 'audio_play'; },
        needsOsc(a)     { return a.type === 'osc'; },
        needsArtCmd(a)  { return a.type === 'artnet_audio'; },
        needsDmx(a)     { return a.type === 'artnet_dmx'; },
        hasTarget(a)    { return ['osc','artnet_audio','artnet_dmx'].includes(a.type); },

        _actionTypeLabel(t) {
            return { audio_play: 'Audio Play', audio_stop: 'Audio Stop',
                     osc: 'OSC', artnet_audio: 'Art-Net Audio',
                     artnet_dmx: 'Art-Net DMX' }[t] || t;
        },

        _buildJson() {
            const toObj = (a) => {
                const obj = { type: a.type };
                if (a.type === 'audio_play') {
                    obj.file = a.file;
                    if (a.volume !== '' && a.volume !== null) obj.volume = parseInt(a.volume);
                    if (a.loop) obj.loop = true;
                } else if (a.type === 'osc') {
                    obj.address = a.osc_addr;
                    if (a.target_ip)   obj.target_ip   = a.target_ip;
                    if (a.target_port) obj.target_port = parseInt(a.target_port);
                } else if (a.type === 'artnet_audio') {
                    obj.cmd = parseInt(a.cmd);
                    if (a.file)        obj.file   = a.file;
                    if (a.volume !== '' && a.volume !== null) obj.volume = parseInt(a.volume);
                    if (a.target_ip)   obj.target_ip = a.target_ip;
                } else if (a.type === 'artnet_dmx') {
                    obj.universe = parseInt(a.universe);
                    obj.channel  = parseInt(a.channel);
                    obj.value    = parseInt(a.value);
                    if (a.target_ip) obj.target_ip = a.target_ip;
                }
                return obj;
            };
            return {
                puck_name: this.puckName,
                actions: {
                    press:   this.pressActions.map(toObj),
                    release: this.releaseActions.map(toObj),
                }
            };
        },

        _fromJson(obj) {
            this.puckName = obj.puck_name || '';
            const toAction = (o) => {
                const a = this.emptyAction();
                a.type = o.type || 'audio_play';
                if (o.file        !== undefined) a.file        = o.file;
                if (o.volume      !== undefined) a.volume      = o.volume;
                if (o.loop)                      a.loop        = true;
                if (o.address     !== undefined) a.osc_addr    = o.address;
                if (o.target_ip   !== undefined) a.target_ip   = o.target_ip;
                if (o.target_port !== undefined) a.target_port = o.target_port;
                if (o.cmd         !== undefined) a.cmd         = o.cmd;
                if (o.universe    !== undefined) a.universe    = o.universe;
                if (o.channel     !== undefined) a.channel     = o.channel;
                if (o.value       !== undefined) a.value       = o.value;
                return a;
            };
            this.pressActions   = (obj.actions?.press   || []).map(toAction);
            this.releaseActions = (obj.actions?.release || []).map(toAction);
        },

        async saveToDevice() {
            const dev = this.selectedDevice;
            if (!dev) return;
            this.status = { ok: null, msg: 'Saving...' };
            try {
                const r = await fetch('/api/marius/push', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip: dev.ip, content: this._buildJson() })
                });
                if (r.ok) {
                    this.status = { ok: true, msg: 'Saved to device — reload device to apply.' };
                } else {
                    const j = await r.json().catch(() => ({}));
                    this.status = { ok: false, msg: j.error || 'Save failed.' };
                }
            } catch { this.status = { ok: false, msg: 'Network error.' }; }
            setTimeout(() => this.status = null, 6000);
        },

        async loadFromDevice() {
            const dev = this.selectedDevice;
            if (!dev) return;
            this.status = { ok: null, msg: 'Loading from device...' };
            try {
                const r = await fetch('/api/marius?ip=' + encodeURIComponent(dev.ip));
                if (r.ok) {
                    this._fromJson(await r.json());
                    this.status = { ok: true, msg: 'Loaded.' };
                } else {
                    const j = await r.json().catch(() => ({}));
                    this.status = { ok: false, msg: j.error || 'Load failed.' };
                }
            } catch { this.status = { ok: false, msg: 'Network error.' }; }
            setTimeout(() => this.status = null, 6000);
        },

        exportJson() {
            const blob = new Blob([JSON.stringify(this._buildJson(), null, 2)],
                                  { type: 'application/json' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'marius.json';
            a.click();
        },

        importJson() {
            const inp = document.createElement('input');
            inp.type = 'file'; inp.accept = '.json';
            inp.onchange = async () => {
                try { this._fromJson(JSON.parse(await inp.files[0].text())); }
                catch { this.status = { ok: false, msg: 'Invalid JSON.' }; }
            };
            inp.click();
        },
    };
}
