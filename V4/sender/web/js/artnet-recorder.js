function artnetRecorder() {
    return {
        mode: "standin",
        deviceIp: "192.168.8.190",
        interface: "",
        durationS: 0,
        fullPayload: false,
        recording: false,
        busy: false,
        error: "",
        interfaces: [],
        stats: null,
        showSetup: {
            layout: "per_device_universe",
            start_ip: "192.168.8.190",
            start_universe: 1,
            device_count: 20,
            devices: [],
        },
        recentEvents: [],
        lastEventId: 0,
        pollTimer: null,
        packetSummary: "",

        get expectedUniverse() {
            const dev = (this.showSetup.devices || []).find((d) => d.ip === this.deviceIp);
            return dev ? dev.universe : null;
        },

        get setupHint() {
            if (this.mode === "sniff") {
                return " — sniffing all setup devices";
            }
            return " — stand-in target";
        },

        async init() {
            await this.refreshRuntime();
            this.pollTimer = setInterval(() => this.poll(), 500);
        },

        deviceOptionLabel(dev) {
            return `${dev.label || dev.ip} — U${dev.universe}`;
        },

        devicePacketCount(ip) {
            const row = (this.stats?.devices || []).find((d) => d.ip === ip);
            return row ? row.packets : 0;
        },

        devicePacketRate(ip) {
            const row = (this.stats?.devices || []).find((d) => d.ip === ip);
            return row && row.packets_per_second ? row.packets_per_second : "—";
        },

        regenerateSetup() {
            const startIp = this.showSetup.start_ip || "192.168.8.190";
            const startUni = Number(this.showSetup.start_universe) || 1;
            const count = Math.max(1, Number(this.showSetup.device_count) || 1);
            const parts = startIp.split(".").map((p) => parseInt(p, 10));
            if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) {
                return;
            }
            const base = ((parts[0] << 24) >>> 0) + (parts[1] << 16) + (parts[2] << 8) + parts[3];
            const devices = [];
            for (let i = 0; i < count; i += 1) {
                const n = (base + i) >>> 0;
                const ip = [
                    (n >>> 24) & 255,
                    (n >>> 16) & 255,
                    (n >>> 8) & 255,
                    n & 255,
                ].join(".");
                devices.push({
                    ip,
                    universe: startUni + i,
                    label: `Device ${i + 1}`,
                });
            }
            this.showSetup.devices = devices;
            if (!devices.some((d) => d.ip === this.deviceIp)) {
                this.deviceIp = devices[0]?.ip || this.deviceIp;
            }
        },

        ifaceLabel(iface) {
            const ip = iface.source_ip ? ` — ${iface.source_ip}` : "";
            return `${iface.label || iface.device}${ip}`;
        },

        rateSummary() {
            const rates = this.stats?.packets_per_second || {};
            const parts = Object.entries(rates).map(([u, r]) => `U${u}: ${r}`);
            return parts.length ? parts.join(", ") : "—";
        },

        formatEvent(ev) {
            const ts = new Date((ev.ts || 0) * 1000).toISOString().slice(11, 23);
            const uni = ev.universe != null ? ` U${ev.universe}` : "";
            const expected = ev.expected_universe != null ? ` exp U${ev.expected_universe}` : "";
            const seq = ev.sequence != null ? ` seq=${ev.sequence}` : "";
            const delta = ev.delta_ms != null ? ` Δ${ev.delta_ms}ms` : "";
            return `${ts} ${ev.src || "?"} → ${ev.dst || "?"} ${ev.opcode_name || ""}${uni}${expected}${seq}${delta}`;
        },

        async api(method, path, body) {
            const opts = { method, headers: {} };
            if (body != null) {
                opts.headers["Content-Type"] = "application/json";
                opts.body = JSON.stringify(body);
            }
            const res = await fetch(path, opts);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.error || `HTTP ${res.status}`);
            }
            return data;
        },

        async refreshRuntime() {
            const data = await this.api("GET", "/api/runtime");
            const capture = data.capture || {};
            this.recording = !!capture.recording;
            if (data.show_setup) {
                this.showSetup = data.show_setup;
            }
            if (!this.showSetup.devices?.length) {
                this.regenerateSetup();
            }
            this.deviceIp = capture.device_ip || this.deviceIp || data.device_ip_default;
            this.mode = capture.mode || this.mode;
            this.interface = capture.interface || this.interface;
            const net = data.network || {};
            this.interfaces = net.interfaces || [];
            if (!this.interface && net.recommended) {
                this.interface = net.recommended;
            }
            const count = capture.session?.packet_count || 0;
            this.packetSummary = this.recording ? `${count} packets` : "";
        },

        async saveSetup() {
            this.busy = true;
            this.error = "";
            try {
                const data = await this.api("POST", "/api/capture/setup", {
                    show_setup: this.showSetup,
                });
                this.showSetup = data.show_setup || this.showSetup;
            } catch (err) {
                this.error = err.message || String(err);
            } finally {
                this.busy = false;
            }
        },

        async poll() {
            try {
                if (this.recording) {
                    const evData = await this.api("GET", `/api/capture/events?since=${this.lastEventId}`);
                    const events = evData.events || [];
                    for (const ev of events) {
                        this.recentEvents.push(ev);
                        this.lastEventId = Math.max(this.lastEventId, ev.id || 0);
                    }
                    if (this.recentEvents.length > 200) {
                        this.recentEvents = this.recentEvents.slice(-200);
                    }
                }
                this.stats = await this.api("GET", "/api/capture/stats");
                await this.refreshRuntime();
            } catch (_) {
                /* ignore transient poll errors */
            }
        },

        async startCapture() {
            this.busy = true;
            this.error = "";
            try {
                await this.saveSetup();
                const body = {
                    mode: this.mode,
                    device_ip: this.deviceIp,
                    interface: this.interface,
                    full_payload: this.fullPayload,
                    show_setup: this.showSetup,
                };
                if (this.durationS > 0) {
                    body.duration_s = this.durationS;
                }
                await this.api("POST", "/api/capture/start", body);
                this.recording = true;
                this.recentEvents = [];
                this.lastEventId = 0;
            } catch (err) {
                this.error = err.message || String(err);
            } finally {
                this.busy = false;
            }
        },

        async stopCapture() {
            this.busy = true;
            this.error = "";
            try {
                await this.api("POST", "/api/capture/stop", {});
                this.recording = false;
            } catch (err) {
                this.error = err.message || String(err);
            } finally {
                this.busy = false;
            }
        },

        async exportCapture() {
            this.busy = true;
            this.error = "";
            try {
                const data = await this.api("GET", "/api/capture/export");
                const ts = new Date().toISOString().replace(/[:.]/g, "-");
                const jsonlName = data.filename || `capture-${ts}.jsonl`;
                const blob = new Blob([data.jsonl || ""], { type: "application/jsonl" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = jsonlName;
                a.click();
                URL.revokeObjectURL(a.href);

                const summaryBlob = new Blob(
                    [JSON.stringify(data.summary || {}, null, 2)],
                    { type: "application/json" }
                );
                const b = document.createElement("a");
                b.href = URL.createObjectURL(summaryBlob);
                b.download = jsonlName.replace(".jsonl", "-summary.json");
                b.click();
                URL.revokeObjectURL(b.href);
            } catch (err) {
                this.error = err.message || String(err);
            } finally {
                this.busy = false;
            }
        },
    };
}
