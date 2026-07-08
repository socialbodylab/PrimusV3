document.addEventListener("alpine:init", () => {
    const FIRMWARE_UPDATE_INTERVAL_MS = 30 * 60 * 1000;

    Alpine.data("firmwareUploader", () => ({
        profile: "radius_v1",
        profiles: [
            { id: "radius_v1", label: "Radius V1", family: "radius", detail: "Feather HUZZAH32 + Music Maker FeatherWing" },
        ],
        multiFamily: false,
        family: "primus",
        families: { primus: [], radius: [] },
        available: false,
        availabilityMessage: "Checking firmware tools...",
        sourceOnly: true,
        toolStatus: "unknown",
        canInstallTools: false,
        toolsDir: "",
        ports: [],
        portMode: "selected",
        selectedPort: "",
        nameEnabled: false,
        deviceName: "",
        characterNameEnabled: false,
        characterName: "",
        performerNameEnabled: false,
        performerName: "",
        wifiEnabled: false,
        wifiSsid: "",
        wifiPassword: "",
        ipMode: "keep",
        staticIp: "",
        gateway: "",
        subnet: "255.255.255.0",
        receiveModeMode: "keep",
        receiveBaseUniverse: 0,
        activeJob: null,
        polling: null,
        notifiedJobId: null,
        serialActive: false,
        serialPort: "",
        serialOutput: [],
        serialPolling: null,
        monitorPort: "",
        firmwareVersion: null,
        firmwareSource: "bundled",
        updateInfo: null,
        checkingUpdates: false,
        updateCheckInterval: null,
        firmwareTabActive: false,

        init() {
            this.nameEnabled = false;
            this.characterNameEnabled = false;
            this.performerNameEnabled = false;
            this.wifiEnabled = false;
            this.wifiSsid = "";
            this.wifiPassword = "";
            this.deviceName = "";
            this.characterName = "";
            this.performerName = "";
            this.ipMode = "keep";
            this.staticIp = "";
            this.gateway = "";
            this.subnet = "255.255.255.0";
            this.receiveModeMode = "keep";
            this.receiveBaseUniverse = 0;
            this.refreshStatus();
            this.refreshSerialStatus();
            document.addEventListener("primus:mode-changed", event => {
                const isFirmware = event.detail?.mode === "firmware";
                this.firmwareTabActive = isFirmware;
                if (isFirmware) {
                    this.refreshStatus();
                    this.refreshSerialStatus();
                    this.startUpdatePolling();
                } else {
                    this.stopUpdatePolling();
                }
            });
            if (Alpine.store("app")?.mode === "firmware") {
                this.firmwareTabActive = true;
                this.startUpdatePolling();
            }
        },

        get showPrimusFirmwareUpdates() {
            return !this.multiFamily || this.family === "primus";
        },

        get activeFamilyLabel() {
            if (!this.multiFamily) {
                const prof = this.profiles.find(item => item.id === this.profile);
                return prof?.family === "radius" ? "Radius" : "Primus";
            }
            return this.family === "radius" ? "Radius" : "Primus";
        },

        get firmwareScope() {
            return this.multiFamily ? "mixed" : "product";
        },

        get familyProfiles() {
            if (this.multiFamily) {
                return this.families?.[this.family] || [];
            }
            return this.profiles;
        },

        get showReceiveModeOverrides() {
            if (this.multiFamily) {
                return this.family === "primus";
            }
            const prof = this.profiles.find(item => item.id === this.profile);
            return prof?.family === "primus";
        },

        get deviceNamePlaceholder() {
            if (this.multiFamily) {
                return this.family === "primus" ? "PrimusV3" : "Radius";
            }
            const prof = this.profiles.find(item => item.id === this.profile);
            return prof?.family === "radius" ? "Radius" : "PrimusV3";
        },

        get updateAvailable() {
            return !!this.updateInfo?.update_available;
        },

        get updateError() {
            return this.updateInfo?.error || "";
        },

        get serialMonitorActive() {
            return this.serialActive;
        },

        get running() {
            return ["queued", "running"].includes(this.activeJob?.status);
        },

        get installingTools() {
            return this.running && this.activeJob?.action === "setup_tools";
        },

        get showInstallTools() {
            return !this.available && !this.running && this.canInstallTools;
        },

        get terminal() {
            return ["succeeded", "failed"].includes(this.activeJob?.status);
        },

        get outputLines() {
            return this.activeJob?.output || [];
        },

        get showJobWaitingPlaceholder() {
            return this.running && this.outputLines.length <= 2;
        },

        get serialOutputLines() {
            return this.serialOutput || [];
        },

        get monitorPortLabel() {
            if (this.monitorPort) return this.monitorPort;
            return this.selectedPort || "No device selected";
        },

        get canStartSerial() {
            return this.available && !this.running && !this.serialActive && !!this.monitorPort;
        },

        get candidatePorts() {
            return this.ports.filter(port => port.candidate);
        },

        get selectedPortLabel() {
            if (this.portMode === "all") return "All available devices";
            const port = this.ports.find(item => item.address === this.selectedPort);
            return port ? port.address : (this.selectedPort || "No device selected");
        },

        get canUpload() {
            if (!this.available || this.running || this.serialMonitorActive) return false;
            if (!this.overridesValid) return false;
            if (this.portMode === "all") return this.candidatePorts.length > 0;
            return !!this.selectedPort;
        },

        get canCompile() {
            return this.available && !this.running && !this.serialMonitorActive && this.overridesValid;
        },

        get deviceNameOverride() {
            if (!this.nameEnabled) return "";
            return (this.deviceName || "").trim();
        },

        get characterNameOverride() {
            if (!this.characterNameEnabled) return "";
            return (this.characterName || "").trim();
        },

        get performerNameOverride() {
            if (!this.performerNameEnabled) return "";
            return (this.performerName || "").trim();
        },

        get wifiSsidOverride() {
            if (!this.wifiEnabled) return "";
            return (this.wifiSsid || "").trim();
        },

        get wifiPasswordOverrideSet() {
            return this.wifiEnabled && !!this.wifiPassword;
        },

        get staticIpOverride() {
            return (this.staticIp || "").trim();
        },

        get gatewayOverride() {
            return (this.gateway || "").trim();
        },

        get subnetOverride() {
            return (this.subnet || "").trim();
        },

        get overrideValidationMessage() {
            if (this.nameEnabled && !this.deviceNameOverride) return "Custom name is enabled but empty.";
            if (this.characterNameEnabled && !this.characterNameOverride) return "Character name is enabled but empty.";
            if (this.performerNameEnabled && !this.performerNameOverride) return "Performer name is enabled but empty.";
            if (this.characterNameOverride.length > 64) return "Character name must be 64 characters or fewer.";
            if (this.performerNameOverride.length > 64) return "Performer name must be 64 characters or fewer.";
            if (this.wifiEnabled && !this.wifiSsidOverride && !this.wifiPassword) return "Custom credentials are enabled but empty.";
            if (this.wifiEnabled && !this.wifiSsidOverride) return "Custom credentials need an SSID.";
            if (this.wifiEnabled && !this.wifiPassword) return "Custom credentials need a password.";
            if (this.ipMode === "static") {
                if (!this.staticIpOverride || !this.gatewayOverride || !this.subnetOverride) return "Static IP needs IP, gateway, and subnet.";
                if (!this.isIpv4(this.staticIpOverride)) return "Static IP is not a valid IPv4 address.";
                if (!this.isIpv4(this.gatewayOverride)) return "Gateway is not a valid IPv4 address.";
                if (!this.isIpv4(this.subnetOverride)) return "Subnet is not a valid IPv4 address.";
            }
            if (this.showReceiveModeOverrides && this.receiveModeMode !== "keep") {
                const base = Number(this.receiveBaseUniverse);
                if (!Number.isFinite(base) || base < 0 || base > 32767) {
                    return "Base universe must be 0–32767.";
                }
            }
            return "";
        },

        get overridesValid() {
            return !this.overrideValidationMessage;
        },

        get overrideSummaryClass() {
            return {
                "firmware-override-summary-error": !!this.overrideValidationMessage,
                "firmware-override-summary-active": !this.overrideValidationMessage && (this.nameEnabled || this.characterNameEnabled || this.performerNameEnabled || this.wifiEnabled || this.ipMode !== "keep" || this.receiveModeMode !== "keep"),
            };
        },

        isIpv4(value) {
            const parts = String(value || "").trim().split(".");
            return parts.length === 4 && parts.every(part => {
                if (!/^\d+$/.test(part)) return false;
                const octet = Number(part);
                return octet >= 0 && octet <= 255;
            });
        },

        overrideSummary() {
            if (this.overrideValidationMessage) return this.overrideValidationMessage;
            const parts = [];
            if (this.deviceNameOverride) parts.push("Name: " + this.deviceNameOverride);
            if (this.characterNameOverride) parts.push("Character: " + this.characterNameOverride);
            if (this.performerNameOverride) parts.push("Performer: " + this.performerNameOverride);
            if (this.wifiSsidOverride) parts.push("SSID: " + this.wifiSsidOverride);
            if (this.wifiPasswordOverrideSet) parts.push("Password: set");
            if (this.ipMode === "static") {
                parts.push("Static IP: " + this.staticIpOverride + " / " + this.gatewayOverride + " / " + this.subnetOverride);
            } else if (this.ipMode === "dhcp") {
                parts.push("IP: DHCP");
            }
            if (this.showReceiveModeOverrides && this.receiveModeMode === "split") {
                parts.push("Receive: Split · U" + this.receiveBaseUniverse + "/" + (Number(this.receiveBaseUniverse) + 1));
            } else if (this.showReceiveModeOverrides && this.receiveModeMode === "combined") {
                parts.push("Receive: Combined · U" + this.receiveBaseUniverse);
            }
            return parts.length ? "This job will use " + parts.join("; ") + "." : "Using firmware defaults from config.h.";
        },

        jobOverrideSummary() {
            const metadata = this.activeJob?.metadata || {};
            const overrides = metadata.overrides || {};
            const parts = [];
            if (overrides.device_name) parts.push("Name: " + overrides.device_name);
            if (overrides.character_name) parts.push("Character: " + overrides.character_name);
            if (overrides.performer_name) parts.push("Performer: " + overrides.performer_name);
            if (overrides.wifi_ssid) parts.push("SSID: " + overrides.wifi_ssid);
            if (overrides.wifi_password_set) parts.push("Password: set");
            if (overrides.ip_mode === "static") {
                parts.push("Static IP: " + overrides.static_ip + " / " + overrides.gateway + " / " + overrides.subnet);
            } else if (overrides.ip_mode === "dhcp") {
                parts.push("IP: DHCP");
            }
            if (overrides.receive_mode_mode === "split") {
                parts.push("Receive: Split · U" + (overrides.base_universe ?? 0));
            } else if (overrides.receive_mode_mode === "combined") {
                parts.push("Receive: Combined · U" + (overrides.base_universe ?? 0));
            }
            return parts.length ? "Overrides used: " + parts.join("; ") : "Overrides used: firmware defaults";
        },

        async refreshStatus() {
            try {
                const status = await api("GET", "/api/firmware/status?scope=" + encodeURIComponent(this.firmwareScope));
                this.syncProfilesFromStatus(status);
                this.available = !!status.available;
                this.availabilityMessage = status.message || "Firmware upload status unknown.";
                this.sourceOnly = status.source_only !== false;
                this.toolStatus = status.tool_status || "unknown";
                this.canInstallTools = !!status.can_install_tools;
                this.toolsDir = status.tools_dir || "";
                this.syncFirmwareUpdateFromStatus(status);
                if (status.current_job) {
                    this.activeJob = status.current_job;
                    this.startPolling();
                } else if (!this.activeJob && status.last_job) {
                    this.activeJob = status.last_job;
                    this.consumeJobResult(status.last_job);
                }
            } catch (e) {
                this.available = false;
                this.availabilityMessage = e.message || "Firmware status unavailable.";
                this.canInstallTools = false;
            }
        },

        syncFirmwareUpdateFromStatus(status) {
            const firmware = status?.firmware || {};
            this.firmwareVersion = firmware.version || null;
            this.firmwareSource = firmware.source || "bundled";
            if (status?.update) {
                this.updateInfo = status.update;
            }
        },

        installedFirmwareLabel() {
            if (!this.firmwareVersion) return "Unknown";
            const source = this.firmwareSource === "downloaded" ? "downloaded" : "bundled";
            return "v" + this.firmwareVersion + " (" + source + ")";
        },

        remoteFirmwareLabel() {
            if (this.checkingUpdates) return "Checking…";
            const version = this.updateInfo?.remote_version;
            if (!version) return this.updateInfo?.error ? "Unavailable" : "—";
            return "v" + version;
        },

        updateStatusLabel() {
            if (this.checkingUpdates) return "Checking";
            if (this.updateInfo?.error) return "Check failed";
            if (this.updateAvailable) return "Update available";
            if (this.updateInfo?.remote_version) return "Up to date";
            return "Unknown";
        },

        updateStatusClass() {
            if (this.checkingUpdates) return "firmware-status-running";
            if (this.updateInfo?.error) return "firmware-status-error";
            if (this.updateAvailable) return "firmware-status-running";
            if (this.updateInfo?.remote_version) return "firmware-status-success";
            return "firmware-status-idle";
        },

        async checkForUpdates(force = true) {
            if (this.running || this.checkingUpdates) return;
            this.checkingUpdates = true;
            try {
                const update = await api("POST", "/api/firmware/updates/check", { force: !!force });
                this.updateInfo = update;
            } catch (e) {
                this.updateInfo = {
                    ...(this.updateInfo || {}),
                    error: e.message || "Firmware update check failed.",
                };
                Alpine.store("app").showApiError("Firmware update check failed", e);
            } finally {
                this.checkingUpdates = false;
            }
        },

        downloadFirmware() {
            return this.startJob("download_firmware");
        },

        startUpdatePolling() {
            this.stopUpdatePolling();
            this.updateCheckInterval = setInterval(() => {
                if (!this.firmwareTabActive || this.running) return;
                this.checkForUpdates(false);
            }, FIRMWARE_UPDATE_INTERVAL_MS);
        },

        stopUpdatePolling() {
            if (this.updateCheckInterval) {
                clearInterval(this.updateCheckInterval);
                this.updateCheckInterval = null;
            }
        },

        setFamily(family) {
            if (this.running || !this.multiFamily || this.family === family) return;
            this.family = family;
            this.receiveModeMode = "keep";
            const profiles = this.families?.[family] || [];
            const preferred = family === "radius"
                ? (profiles.find(item => item.id === "radius_v1") || profiles[0])
                : (profiles.find(item => item.id === "v3") || profiles[0]);
            if (preferred) {
                this.setProfile(preferred.id);
            }
        },

        setProfile(profile) {
            if (this.running) return;
            this.profile = profile;
            const item = this.profiles.find(entry => entry.id === profile);
            if (item?.family && this.multiFamily) {
                this.family = item.family;
            }
            this.ports = [];
            this.selectedPort = "";
            this.portMode = "selected";
        },

        profileDetail() {
            return this.profiles.find(item => item.id === this.profile)?.detail || "Receiver";
        },

        syncProfilesFromStatus(status) {
            if (status?.families) {
                this.families = status.families;
            }
            if (!Array.isArray(status?.profiles) || !status.profiles.length) return;
            this.profiles = status.profiles;
            const visible = this.multiFamily ? this.familyProfiles : this.profiles;
            if (!visible.some(item => item.id === this.profile)) {
                const next = visible[0] || this.profiles[0];
                if (next) {
                    this.profile = next.id;
                    if (next.family && this.multiFamily) {
                        this.family = next.family;
                    }
                }
            } else if (this.multiFamily && this.family === "radius" && this.profile.startsWith("v")) {
                const preferred = (this.families?.radius || []).find(item => item.id === "radius_v1");
                if (preferred) {
                    this.profile = preferred.id;
                }
            }
        },

        profileLabel() {
            return this.profiles.find(item => item.id === this.profile)?.label || "Receiver";
        },

        selectPort(port) {
            if (this.running || !port?.address || !port.candidate) return;
            this.selectedPort = port.address;
            this.portMode = "selected";
        },

        selectAllDevices() {
            if (this.running || this.candidatePorts.length === 0) return;
            this.selectedPort = "";
            this.portMode = "all";
        },

        portRowClass(port) {
            return {
                "firmware-port-candidate": !!port.candidate,
                "firmware-port-selected": this.selectedPort === port.address,
            };
        },

        portBadge(port) {
            if (port.target_match) return "Profile match";
            if (port.candidate) return "Candidate";
            return "Other";
        },

        statusClass() {
            if (this.running) return "firmware-status-running";
            if (this.activeJob?.status === "failed" || !this.available) return "firmware-status-error";
            if (this.activeJob?.status === "succeeded") return "firmware-status-success";
            return "firmware-status-idle";
        },

        jobLabel() {
            if (!this.activeJob) return "Ready";
            if (this.activeJob.action === "setup_tools") return "Firmware tools - " + this.activeJob.status;
            if (this.activeJob.action === "download_firmware") return "Firmware download - " + this.activeJob.status;
            const action = this.activeJob.action.replace("_", " ");
            return action + " - " + this.activeJob.status;
        },

        targetSummary() {
            if (this.running) return "Firmware job is running.";
            if (!this.available) return "Install firmware tools before scanning devices.";
            if (!this.candidatePorts.length) return "Connect a receiver, then refresh devices.";
            if (this.portMode === "all") return "All " + this.candidatePorts.length + " available device" + (this.candidatePorts.length === 1 ? "" : "s") + " selected.";
            return this.selectedPort ? this.selectedPort + " selected." : "Choose a device or All Available Devices.";
        },

        scanPorts() {
            return this.startJob("list_ports");
        },

        installTools() {
            return this.startJob("setup_tools");
        },

        async startJob(action) {
            if (this.running) return;
            if ((action === "compile" || action === "upload") && !this.overridesValid) {
                Alpine.store("app").showNotice(this.overrideValidationMessage, "error", 4000);
                return;
            }
            const body = { action, profile: this.profile, scope: this.firmwareScope };
            if (action === "compile" || action === "upload") {
                this.addDeviceNameField(body);
                this.addShowInfoFields(body);
                this.addWifiFields(body);
                this.addIpFields(body);
                if (this.showReceiveModeOverrides) {
                    this.addReceiveModeFields(body);
                }
            }
            if (action === "upload") {
                body.port_mode = this.portMode;
                if (this.portMode !== "all") {
                    body.port = this.selectedPort;
                }
            }
            try {
                this.activeJob = await api("POST", "/api/firmware/jobs", body);
                this.notifiedJobId = null;
                this.startPolling();
                await this.pollJob();
            } catch (e) {
                Alpine.store("app").showApiError("Firmware job failed", e);
            }
        },

        addWifiFields(body) {
            if (!this.wifiEnabled) return;
            const ssid = this.wifiSsidOverride;
            if (ssid) body.wifi_ssid = ssid;
            if (this.wifiPassword) body.wifi_password = this.wifiPassword;
        },

        addDeviceNameField(body) {
            if (!this.nameEnabled) return;
            const name = this.deviceName.trim();
            if (name) body.device_name = name;
        },

        addShowInfoFields(body) {
            if (this.characterNameEnabled) {
                const character = this.characterName.trim();
                if (character) body.character_name = character;
            }
            if (this.performerNameEnabled) {
                const performer = this.performerName.trim();
                if (performer) body.performer_name = performer;
            }
        },

        addIpFields(body) {
            if (this.ipMode === "keep") return;
            body.ip_mode = this.ipMode;
            if (this.ipMode === "static") {
                body.static_ip = this.staticIpOverride;
                body.gateway = this.gatewayOverride;
                body.subnet = this.subnetOverride;
            }
        },

        addReceiveModeFields(body) {
            body.receive_mode_mode = this.receiveModeMode || "keep";
            if (this.receiveModeMode === "keep") return;
            body.base_universe = Number(this.receiveBaseUniverse) || 0;
        },

        startPolling() {
            if (this.polling || !this.activeJob) return;
            this.polling = setInterval(() => this.pollJob(), 250);
        },

        stopPolling() {
            if (this.polling) {
                clearInterval(this.polling);
                this.polling = null;
            }
        },

        async pollJob() {
            if (!this.activeJob?.id) return;
            try {
                const job = await api("GET", "/api/firmware/jobs/" + this.activeJob.id);
                this.activeJob = job;
                this.consumeJobResult(job);
                this.$nextTick(() => this.scrollFirmwareLog());
                if (["succeeded", "failed"].includes(job.status)) {
                    this.stopPolling();
                    this.notifyFinished(job);
                }
            } catch (e) {
                this.stopPolling();
                Alpine.store("app").showApiError("Firmware status failed", e);
            }
        },

        consumeJobResult(job) {
            if (job?.action !== "list_ports" || job.status !== "succeeded") return;
            const ports = job.result?.ports || [];
            this.ports = ports;
            const selectedStillAvailable = this.candidatePorts.some(port => port.address === this.selectedPort);
            if (this.portMode !== "all" && !selectedStillAvailable) {
                this.selectedPort = this.candidatePorts[0]?.address || "";
                this.portMode = "selected";
            }
            if (this.portMode === "all" && this.candidatePorts.length === 0) {
                this.portMode = "selected";
            }
            if (!this.monitorPort && this.selectedPort) {
                this.monitorPort = this.selectedPort;
            }
        },

        notifyFinished(job) {
            if (!job || this.notifiedJobId === job.id) return;
            this.notifiedJobId = job.id;
            if (job.status === "succeeded") {
                const label = job.action === "list_ports"
                    ? "Port scan"
                    : (job.action === "setup_tools"
                        ? "Firmware tools setup"
                        : (job.action === "download_firmware"
                            ? "Firmware download"
                            : "Firmware job"));
                Alpine.store("app").showNotice(label + " complete.", "success");
                if (job.action === "setup_tools" || job.action === "download_firmware") {
                    this.refreshStatus();
                }
            } else {
                Alpine.store("app").showNotice(job.error || "Firmware job failed.", "error", 5000);
            }
        },

        scrollFirmwareLog() {
            const log = this.$refs.firmwareLog;
            if (log) log.scrollTop = log.scrollHeight;
        },

        scrollSerialLog() {
            const log = this.$refs.serialLog;
            if (log) log.scrollTop = log.scrollHeight;
        },

        async refreshSerialStatus() {
            try {
                const status = await api("GET", "/api/serial/status");
                this.serialActive = !!status.active;
                this.serialPort = status.port || "";
                this.serialOutput = status.output || [];
                if (this.serialActive) {
                    this.startSerialPolling();
                } else {
                    this.stopSerialPolling();
                }
                this.$nextTick(() => this.scrollSerialLog());
            } catch (e) {
                this.serialActive = false;
            }
        },

        startSerialPolling() {
            if (this.serialPolling) return;
            this.serialPolling = setInterval(() => this.pollSerial(), 250);
        },

        stopSerialPolling() {
            if (this.serialPolling) {
                clearInterval(this.serialPolling);
                this.serialPolling = null;
            }
        },

        async pollSerial() {
            try {
                const status = await api("GET", "/api/serial/status");
                this.serialActive = !!status.active;
                this.serialPort = status.port || "";
                this.serialOutput = status.output || [];
                this.$nextTick(() => this.scrollSerialLog());
                if (!this.serialActive) {
                    this.stopSerialPolling();
                }
            } catch (e) {
                this.stopSerialPolling();
            }
        },

        async startSerialMonitor() {
            const port = (this.monitorPort || this.selectedPort || "").trim();
            if (!port) {
                Alpine.store("app").showNotice("Select a serial port for the monitor.", "warn");
                return;
            }
            try {
                const status = await api("POST", "/api/serial/monitor/start", { port });
                this.serialActive = !!status.active;
                this.serialPort = status.port || port;
                this.serialOutput = status.output || [];
                this.monitorPort = port;
                this.startSerialPolling();
                this.$nextTick(() => this.scrollSerialLog());
            } catch (e) {
                Alpine.store("app").showApiError("Serial monitor failed", e);
            }
        },

        async stopSerialMonitor() {
            try {
                const status = await api("POST", "/api/serial/monitor/stop");
                this.serialActive = !!status.active;
                this.serialPort = status.port || "";
                this.serialOutput = status.output || [];
                this.stopSerialPolling();
            } catch (e) {
                Alpine.store("app").showApiError("Serial monitor stop failed", e);
            }
        },
    }));
});