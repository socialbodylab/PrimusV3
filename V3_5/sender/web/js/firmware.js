document.addEventListener("alpine:init", () => {
    Alpine.data("firmwareUploader", () => ({
        profile: "v3",
        profiles: [
            { id: "v1", label: "V1", detail: "2022 Original RUR performance. Device Types A/B/C/D/E" },
            { id: "v2", label: "V2", detail: "2025 Make Magazine Device" },
            { id: "v3", label: "V3", detail: "2026 Custom PCB Device" },
        ],
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
        wifiEnabled: false,
        wifiSsid: "",
        wifiPassword: "",
        ipMode: "keep",
        staticIp: "",
        gateway: "",
        subnet: "255.255.255.0",
        activeJob: null,
        polling: null,
        notifiedJobId: null,

        init() {
            this.nameEnabled = false;
            this.wifiEnabled = false;
            this.wifiSsid = "";
            this.wifiPassword = "";
            this.deviceName = "";
            this.ipMode = "keep";
            this.staticIp = "";
            this.gateway = "";
            this.subnet = "255.255.255.0";
            this.refreshStatus();
            document.addEventListener("primus:mode-changed", event => {
                if (event.detail?.mode === "firmware") {
                    this.refreshStatus();
                }
            });
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

        get candidatePorts() {
            return this.ports.filter(port => port.candidate);
        },

        get selectedPortLabel() {
            if (this.portMode === "all") return "All available devices";
            const port = this.ports.find(item => item.address === this.selectedPort);
            return port ? port.address : (this.selectedPort || "No device selected");
        },

        get canUpload() {
            if (!this.available || this.running) return false;
            if (!this.overridesValid) return false;
            if (this.portMode === "all") return this.candidatePorts.length > 0;
            return !!this.selectedPort;
        },

        get canCompile() {
            return this.available && !this.running && this.overridesValid;
        },

        get deviceNameOverride() {
            if (!this.nameEnabled) return "";
            return (this.deviceName || "").trim();
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
            if (this.wifiEnabled && !this.wifiSsidOverride && !this.wifiPassword) return "Custom credentials are enabled but empty.";
            if (this.wifiEnabled && !this.wifiSsidOverride) return "Custom credentials need an SSID.";
            if (this.wifiEnabled && !this.wifiPassword) return "Custom credentials need a password.";
            if (this.ipMode === "static") {
                if (!this.staticIpOverride || !this.gatewayOverride || !this.subnetOverride) return "Static IP needs IP, gateway, and subnet.";
                if (!this.isIpv4(this.staticIpOverride)) return "Static IP is not a valid IPv4 address.";
                if (!this.isIpv4(this.gatewayOverride)) return "Gateway is not a valid IPv4 address.";
                if (!this.isIpv4(this.subnetOverride)) return "Subnet is not a valid IPv4 address.";
            }
            return "";
        },

        get overridesValid() {
            return !this.overrideValidationMessage;
        },

        get overrideSummaryClass() {
            return {
                "firmware-override-summary-error": !!this.overrideValidationMessage,
                "firmware-override-summary-active": !this.overrideValidationMessage && (this.nameEnabled || this.wifiEnabled || this.ipMode !== "keep"),
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
            if (this.wifiSsidOverride) parts.push("SSID: " + this.wifiSsidOverride);
            if (this.wifiPasswordOverrideSet) parts.push("Password: set");
            if (this.ipMode === "static") {
                parts.push("Static IP: " + this.staticIpOverride + " / " + this.gatewayOverride + " / " + this.subnetOverride);
            } else if (this.ipMode === "dhcp") {
                parts.push("IP: DHCP");
            }
            return parts.length ? "This job will use " + parts.join("; ") + "." : "Using firmware defaults from config.h.";
        },

        jobOverrideSummary() {
            const metadata = this.activeJob?.metadata || {};
            const overrides = metadata.overrides || {};
            const parts = [];
            if (overrides.device_name) parts.push("Name: " + overrides.device_name);
            if (overrides.wifi_ssid) parts.push("SSID: " + overrides.wifi_ssid);
            if (overrides.wifi_password_set) parts.push("Password: set");
            if (overrides.ip_mode === "static") {
                parts.push("Static IP: " + overrides.static_ip + " / " + overrides.gateway + " / " + overrides.subnet);
            } else if (overrides.ip_mode === "dhcp") {
                parts.push("IP: DHCP");
            }
            return parts.length ? "Overrides used: " + parts.join("; ") : "Overrides used: firmware defaults";
        },

        async refreshStatus() {
            try {
                const status = await api("GET", "/api/firmware/status");
                this.available = !!status.available;
                this.availabilityMessage = status.message || "Firmware upload status unknown.";
                this.sourceOnly = status.source_only !== false;
                this.toolStatus = status.tool_status || "unknown";
                this.canInstallTools = !!status.can_install_tools;
                this.toolsDir = status.tools_dir || "";
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

        setProfile(profile) {
            if (this.running) return;
            this.profile = profile;
            this.ports = [];
            this.selectedPort = "";
            this.portMode = "selected";
        },

        profileDetail() {
            return this.profiles.find(item => item.id === this.profile)?.detail || "Receiver";
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
            const body = { action, profile: this.profile };
            if (action === "compile" || action === "upload") {
                this.addDeviceNameField(body);
                this.addWifiFields(body);
                this.addIpFields(body);
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

        addIpFields(body) {
            if (this.ipMode === "keep") return;
            body.ip_mode = this.ipMode;
            if (this.ipMode === "static") {
                body.static_ip = this.staticIpOverride;
                body.gateway = this.gatewayOverride;
                body.subnet = this.subnetOverride;
            }
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
        },

        notifyFinished(job) {
            if (!job || this.notifiedJobId === job.id) return;
            this.notifiedJobId = job.id;
            if (job.status === "succeeded") {
                const label = job.action === "list_ports"
                    ? "Port scan"
                    : (job.action === "setup_tools" ? "Firmware tools setup" : "Firmware job");
                Alpine.store("app").showNotice(label + " complete.", "success");
                if (job.action === "setup_tools") this.refreshStatus();
            } else {
                Alpine.store("app").showNotice(job.error || "Firmware job failed.", "error", 5000);
            }
        },
    }));
});