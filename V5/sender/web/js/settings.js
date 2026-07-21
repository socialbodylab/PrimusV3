document.addEventListener("alpine:init", () => {
    Alpine.data("settingsPanel", () => ({
        status: null,
        loading: false,
        saving: false,
        applying: false,
        selectedId: "",
        mode: "static",
        staticIp: "",
        gateway: "",
        subnet: "255.255.255.0",
        scope: "service",
        controllerSsid: "",
        lanePorts: { port_show_primus: 6454, port_show_radius: 6456, port_setup: 6457, port_watch: 6455 },
        lanePortsLoading: false,
        lanePortsSaving: false,

        init() {
            this.refresh();
            this.loadLanePorts();
            document.addEventListener("primus:mode-changed", event => {
                if (event.detail?.mode === "settings") this.refresh();
            });
        },

        get interfaces() {
            return this.status?.interfaces || [];
        },

        get visibleInterfaces() {
            return this.interfaces.filter(item => item.connected);
        },

        get recommendedInterface() {
            return this.status?.recommended_interface
                || this.visibleInterfaces.find(item => item.type === "ethernet")
                || null;
        },

        get selectedInterface() {
            return this.interfaces.find(item => item.id === this.selectedId)
                || this.status?.selected_interface
                || this.recommendedInterface
                || this.interfaces.find(item => item.is_controller)
                || this.interfaces.find(item => item.is_default)
                || this.visibleInterfaces[0]
                || null;
        },

        get hiddenInterfaceCount() {
            return Math.max(0, this.interfaces.length - this.visibleInterfaces.length);
        },

        get controllerConnection() {
            return this.status?.controller_connection || {};
        },

        get currentWifi() {
            return this.visibleInterfaces.find(item => item.type === "wifi" && item.ssid)
                || this.visibleInterfaces.find(item => item.type === "wifi")
                || null;
        },

        get controllerSsidValue() {
            return String(this.controllerSsid || "").trim();
        },

        get profileSsid() {
            if (this.selectedInterface?.type !== "wifi") return "";
            return this.controllerSsidValue || this.selectedInterface?.ssid || "";
        },

        get controllerNetworkActive() {
            return !!(
                this.controllerSsidValue
                && this.currentWifi?.ssid
                && this.currentWifi.ssid === this.controllerSsidValue
            );
        },

        get controllerNetworkStatusLabel() {
            if (!this.controllerSsidValue) return "Not Set";
            return this.controllerNetworkActive ? "Active" : "Named";
        },

        get canSaveControllerNetwork() {
            return !!this.controllerSsidValue && !this.applying;
        },

        get canTagControllerWifi() {
            return this.selectedInterface?.type === "wifi" && !!this.selectedInterface?.ssid && !this.applying;
        },

        get warnings() {
            const items = [...(this.status?.warnings || [])];
            const iface = this.selectedInterface;
            if (iface?.warnings?.length) items.push(...iface.warnings);
            return items;
        },

        get validationMessage() {
            if (this.mode !== "static") return "";
            if (!this.selectedInterface) return "Choose a connection first.";
            if (!this.staticIp || !this.gateway || !this.subnet) return "Static IP needs IP, gateway, and subnet.";
            if (!this.isIpv4(this.staticIp)) return "Static IP is not a valid IPv4 address.";
            if (!this.isIpv4(this.gateway)) return "Gateway is not a valid IPv4 address.";
            if (!this.isIpv4(this.subnet)) return "Subnet is not a valid IPv4 address.";
            if (!this.isContiguousSubnet(this.subnet)) return "Subnet mask must be contiguous.";
            if (!this.isUsableHost(this.staticIp, this.subnet)) return "Static IP must be a usable host address.";
            if (!this.ipInSubnet(this.gateway, this.staticIp, this.subnet)) return "Gateway must be in the same subnet as Static IP.";
            return "";
        },

        get canSaveProfile() {
            return !!this.selectedInterface && !this.validationMessage && !this.saving && !this.applying;
        },

        get canApplyStatic() {
            if (!(this.status?.supported && this.mode === "static" && this.canSaveProfile)) return false;
            if (this.selectedInterface?.type === "wifi" && this.profileSsid) {
                return this.selectedInterface.ssid === this.profileSsid;
            }
            return true;
        },

        get canRevertDhcp() {
            return this.status?.supported && !!this.selectedInterface && !this.applying;
        },

        get routerStatusLabel() {
            const iface = this.selectedInterface;
            if (!iface) return "No Route";
            if (iface.type === "ethernet") return iface.is_preferred ? "Ethernet Ready" : "Ethernet";
            if (iface.type === "wifi") return "WiFi";
            return "Active";
        },

        get hostPlatformLabel() {
            const platform = String(this.status?.platform || "").toLowerCase();
            if (platform.startsWith("win")) return "Windows";
            if (platform === "darwin") return "macOS";
            return "Host";
        },

        get hostConfigLabel() {
            return this.hostPlatformLabel + " Config";
        },

        get applyStaticLabel() {
            return "Apply to " + this.hostPlatformLabel;
        },

        get profileNetwork() {
            return this.networkSummary(this.staticIp, this.subnet);
        },

        get profileNetworkLabel() {
            return this.profileNetwork?.cidr || "No network";
        },

        get profileUsableRange() {
            return this.profileNetwork?.usableRange || "No usable range";
        },

        get receiverRangeCounts() {
            const counts = { inRange: 0, outOfRange: 0, unknown: 0, pending: 0 };
            for (const dev of Alpine.store("conn")?.devices || []) {
                const state = this.receiverRangeState(dev);
                if (state.pending) counts.pending += 1;
                if (state.key === "in") counts.inRange += 1;
                else if (state.key === "out") counts.outOfRange += 1;
                else counts.unknown += 1;
            }
            return counts;
        },

        async refresh() {
            this.loading = true;
            try {
                this.status = await Alpine.store("app").fetchNetworkStatus();
                this.syncFromStatus();
            } catch (e) {
                Alpine.store("app").showApiError("Network status unavailable", e);
            } finally {
                this.loading = false;
            }
        },

        syncFromStatus() {
            const preferred = this.status?.selected_interface;
            const current = this.selectedId ? this.interfaces.find(item => item.id === this.selectedId) : null;
            const iface = current
                || preferred
                || this.recommendedInterface
                || this.interfaces.find(item => item.is_controller)
                || this.interfaces.find(item => item.is_default)
                || this.visibleInterfaces[0];
            this.selectedId = iface?.id || "";
            this.controllerSsid = this.controllerConnection?.ssid || "";
            this.loadProfile();
        },

        loadProfile() {
            const iface = this.selectedInterface;
            if (!iface) return;
            const ssidKey = this.profileSsid;
            const ssidProfile = ssidKey ? (this.status?.ssid_profiles || {})[ssidKey] : null;
            const serviceProfile = (this.status?.service_profiles || {})[iface.service] || (this.status?.service_profiles || {})[iface.device];
            const profile = ssidProfile || serviceProfile || null;
            this.scope = iface.type === "wifi" ? "ssid" : "service";
            this.mode = profile?.mode || "static";
            this.staticIp = profile?.ip || iface.source_ip || "";
            this.gateway = profile?.gateway || iface.gateway || this.defaultGateway(iface.source_ip);
            this.subnet = profile?.subnet || iface.subnet || "255.255.255.0";
        },

        async selectInterface(iface) {
            if (!iface?.id || this.applying) return;
            this.selectedId = iface.id;
            try {
                const result = await api("POST", "/api/network/preferred_interface", {
                    id: iface.id,
                    service: iface.service,
                    device: iface.device,
                });
                this.status = result;
                Alpine.store("app").network = result;
                this.syncFromStatus();
                Alpine.store("app").showNotice("Art-Net connection set to " + this.interfaceLabel(iface) + ".", "success");
            } catch (e) {
                Alpine.store("app").showApiError("Connection selection failed", e);
            }
        },

        async clearPreferred() {
            try {
                const result = await api("POST", "/api/network/preferred_interface", { mode: "auto" });
                this.status = result;
                Alpine.store("app").network = result;
                this.syncFromStatus();
                Alpine.store("app").showNotice("Art-Net routing set to automatic.", "info");
            } catch (e) {
                Alpine.store("app").showApiError("Could not clear connection preference", e);
            }
        },

        async tagControllerWifi() {
            if (!this.canTagControllerWifi) return;
            const iface = this.selectedInterface;
            this.controllerSsid = iface.ssid;
            return this.saveControllerNetwork();
        },

        async useCurrentWifiAsController() {
            if (!this.currentWifi?.ssid || this.applying) return;
            this.controllerSsid = this.currentWifi.ssid;
            return this.saveControllerNetwork();
        },

        async saveControllerNetwork() {
            if (!this.canSaveControllerNetwork) return;
            const iface = this.selectedInterface?.type === "wifi" ? this.selectedInterface : this.currentWifi;
            try {
                const result = await api("POST", "/api/network/controller_connection", {
                    id: iface?.id || "",
                    service: iface?.service || "",
                    device: iface?.device || "",
                    ssid: this.controllerSsidValue,
                });
                this.status = result;
                Alpine.store("app").network = result;
                this.syncFromStatus();
                Alpine.store("app").showNotice("Controller network set to " + this.controllerConnection.ssid + ".", "success");
            } catch (e) {
                Alpine.store("app").showApiError("Controller network save failed", e);
            }
        },

        async clearControllerWifi() {
            try {
                const result = await api("POST", "/api/network/controller_connection", { mode: "clear" });
                this.status = result;
                Alpine.store("app").network = result;
                this.controllerSsid = "";
                this.syncFromStatus();
                Alpine.store("app").showNotice("Controller network cleared.", "info");
            } catch (e) {
                Alpine.store("app").showApiError("Could not clear controller WiFi tag", e);
            }
        },

        profilePayload() {
            const iface = this.selectedInterface || {};
            const ssid = iface.type === "wifi" ? this.profileSsid : iface.ssid;
            const payload = {
                scope: this.scope,
                mode: this.mode,
                id: iface.id,
                service: iface.service,
                device: iface.device,
                ssid: ssid,
            };
            if (this.mode === "static") {
                payload.ip = this.staticIp.trim();
                payload.gateway = this.gateway.trim();
                payload.subnet = this.subnet.trim();
            }
            return payload;
        },

        async saveProfile() {
            if (!this.canSaveProfile) return;
            this.saving = true;
            try {
                const result = await api("POST", "/api/network/ssid_profile", this.profilePayload());
                this.status = result;
                Alpine.store("app").network = result;
                Alpine.store("app").showNotice("Network profile saved.", "success");
            } catch (e) {
                Alpine.store("app").showApiError("Could not save network profile", e);
            } finally {
                this.saving = false;
            }
        },

        async applyStaticIp() {
            if (!this.canApplyStatic) return;
            this.applying = true;
            try {
                const result = await api("POST", "/api/network/apply_static_ip", this.profilePayload());
                this.status = result;
                Alpine.store("app").network = result;
                this.syncFromStatus();
                Alpine.store("app").showNotice("Static IP applied to " + this.hostPlatformLabel + ".", "success");
            } catch (e) {
                Alpine.store("app").showApiError("Static IP apply failed", e);
            } finally {
                this.applying = false;
            }
        },

        async revertDhcp() {
            if (!this.canRevertDhcp) return;
            this.applying = true;
            try {
                const iface = this.selectedInterface;
                const result = await api("POST", "/api/network/set_dhcp", {
                    id: iface.id,
                    service: iface.service,
                    device: iface.device,
                    ssid: iface.ssid,
                });
                this.status = result;
                Alpine.store("app").network = result;
                this.syncFromStatus();
                Alpine.store("app").showNotice(this.hostPlatformLabel + " connection reverted to DHCP.", "success");
            } catch (e) {
                Alpine.store("app").showApiError("DHCP revert failed", e);
            } finally {
                this.applying = false;
            }
        },

        async loadLanePorts() {
            this.lanePortsLoading = true;
            try {
                this.lanePorts = await api("GET", "/api/network/lane_ports");
            } catch (e) {
                Alpine.store("app").showApiError("UDP lane ports unavailable", e);
            } finally {
                this.lanePortsLoading = false;
            }
        },

        get lanePortsValidationMessage() {
            const keys = ["port_show_primus", "port_show_radius", "port_setup", "port_watch"];
            const values = keys.map(key => Number(this.lanePorts?.[key]));
            if (values.some(v => !Number.isInteger(v) || v < 1024 || v > 65535)) {
                return "Ports must be whole numbers from 1024-65535.";
            }
            const [showPrimus, showRadius, setup, watch] = values;
            if (setup === showPrimus || setup === showRadius || setup === watch) {
                return "Setup must differ from both Show ports and from Watch.";
            }
            if (watch === setup) {
                return "Watch must differ from Setup.";
            }
            return "";
        },

        get canSaveLanePorts() {
            return !this.lanePortsSaving && !this.lanePortsLoading && !this.lanePortsValidationMessage;
        },

        async saveLanePorts() {
            if (!this.canSaveLanePorts) return;
            this.lanePortsSaving = true;
            try {
                this.lanePorts = await api("POST", "/api/network/lane_ports", {
                    port_show_primus: Number(this.lanePorts.port_show_primus),
                    port_show_radius: Number(this.lanePorts.port_show_radius),
                    port_setup: Number(this.lanePorts.port_setup),
                    port_watch: Number(this.lanePorts.port_watch),
                });
                Alpine.store("app").showNotice("UDP lane port defaults saved.", "success");
            } catch (e) {
                Alpine.store("app").showApiError("UDP lane ports save failed", e);
            } finally {
                this.lanePortsSaving = false;
            }
        },

        isIpv4(value) {
            const parts = String(value || "").trim().split(".");
            return parts.length === 4 && parts.every(part => {
                if (!/^\d+$/.test(part)) return false;
                const octet = Number(part);
                return octet >= 0 && octet <= 255;
            });
        },

        defaultGateway(ip) {
            return ip ? String(ip).replace(/\.\d+$/, ".1") : "";
        },

        routerSetupSummary() {
            const iface = this.selectedInterface;
            if (!iface) return "Choose an active Ethernet connection.";
            const type = iface.type === "ethernet" ? "Ethernet" : this.typeLabel(iface);
            const network = iface.network?.cidr || this.networkSummary(iface.source_ip, iface.subnet)?.cidr || "unknown range";
            return type + " sender IP " + (iface.source_ip || "none") + " on " + network;
        },

        profileModeNote() {
            if (this.mode === "dhcp") return "DHCP profile saved; static is recommended for routers without DHCP.";
            if (!this.profileNetwork) return "Enter a valid sender IP and subnet.";
            return "Sender range " + this.profileNetworkLabel + " · usable " + this.profileUsableRange;
        },

        ipv4Parts(value) {
            const parts = String(value || "").trim().split(".");
            if (parts.length !== 4) return null;
            const out = [];
            for (const part of parts) {
                if (!/^\d+$/.test(part)) return null;
                const octet = Number(part);
                if (octet < 0 || octet > 255) return null;
                out.push(octet);
            }
            return out;
        },

        ipv4ToNumber(value) {
            const parts = this.ipv4Parts(value);
            if (!parts) return null;
            return parts.reduce((acc, octet) => ((acc << 8) + octet) >>> 0, 0);
        },

        numberToIpv4(value) {
            const num = Number(value) >>> 0;
            return [24, 16, 8, 0].map(shift => (num >>> shift) & 255).join(".");
        },

        isContiguousSubnet(value) {
            const mask = this.ipv4ToNumber(value);
            if (mask === null) return false;
            const inverted = (~mask) >>> 0;
            return ((inverted & ((inverted + 1) >>> 0)) >>> 0) === 0;
        },

        prefixLength(value) {
            const mask = this.ipv4ToNumber(value);
            if (mask === null || !this.isContiguousSubnet(value)) return null;
            let prefix = 0;
            for (let bit = 31; bit >= 0; bit -= 1) {
                if (((mask >>> bit) & 1) === 1) prefix += 1;
            }
            return prefix;
        },

        networkSummary(ip, subnet) {
            const ipNum = this.ipv4ToNumber(ip);
            const maskNum = this.ipv4ToNumber(subnet);
            const prefix = this.prefixLength(subnet);
            if (ipNum === null || maskNum === null || prefix === null) return null;
            const network = (ipNum & maskNum) >>> 0;
            const broadcast = (network | ((~maskNum) >>> 0)) >>> 0;
            const usableFirst = broadcast - network > 1 ? (network + 1) >>> 0 : network;
            const usableLast = broadcast - network > 1 ? (broadcast - 1) >>> 0 : broadcast;
            return {
                cidr: this.numberToIpv4(network) + "/" + prefix,
                network: this.numberToIpv4(network),
                broadcast: this.numberToIpv4(broadcast),
                usableFirst: this.numberToIpv4(usableFirst),
                usableLast: this.numberToIpv4(usableLast),
                usableRange: this.numberToIpv4(usableFirst) + " - " + this.numberToIpv4(usableLast),
            };
        },

        isUsableHost(ip, subnet) {
            const ipNum = this.ipv4ToNumber(ip);
            const summary = this.networkSummary(ip, subnet);
            if (ipNum === null || !summary) return false;
            const network = this.ipv4ToNumber(summary.network);
            const broadcast = this.ipv4ToNumber(summary.broadcast);
            if (network === null || broadcast === null) return false;
            if (broadcast - network <= 1) return ipNum >= network && ipNum <= broadcast;
            return ipNum > network && ipNum < broadcast;
        },

        ipInSubnet(ip, referenceIp, subnet) {
            const ipNum = this.ipv4ToNumber(ip);
            const summary = this.networkSummary(referenceIp, subnet);
            if (ipNum === null || !summary) return false;
            const network = this.ipv4ToNumber(summary.network);
            const broadcast = this.ipv4ToNumber(summary.broadcast);
            return network !== null && broadcast !== null && ipNum >= network && ipNum <= broadcast;
        },

        interfaceLabel(iface) {
            if (!iface) return "No connection";
            if (iface.type === "wifi") return (iface.ssid || iface.service || "WiFi") + " (WiFi)";
            if (iface.type === "ethernet") return iface.service || iface.device || "Ethernet";
            return iface.service || iface.device || "Network";
        },

        typeLabel(iface) {
            if (!iface) return "Unknown";
            if (iface.type === "wifi") return "WiFi";
            if (iface.type === "ethernet") return "Ethernet";
            return "Network";
        },

        interfaceMeta(iface) {
            if (!iface) return "";
            const parts = [];
            if (iface.device) parts.push(iface.device);
            if (iface.source_ip) parts.push(iface.source_ip);
            if (iface.configured_ip && iface.configured_ip !== iface.source_ip) parts.push('configured ' + iface.configured_ip);
            if (iface.broadcast) parts.push("broadcast " + iface.broadcast);
            return parts.join(" · ");
        },

        configuredSummary(iface) {
            if (!iface) return "None";
            if (iface.configured_mode === "static" && iface.configured_ip) {
                const parts = [iface.configured_ip];
                if (iface.configured_subnet) parts.push(iface.configured_subnet);
                if (iface.configured_gateway) parts.push("gateway " + iface.configured_gateway);
                return parts.join(" · ");
            }
            if (iface.configured_mode === "dhcp") return "DHCP";
            return "Unknown";
        },

        currentWifiLabel() {
            if (!this.currentWifi) return "No active WiFi";
            return this.currentWifi.ssid || this.currentWifi.service || "WiFi active";
        },

        profileSummary() {
            if (this.validationMessage) return this.validationMessage;
            if (this.mode === "dhcp") return "DHCP profile ready.";
            if (this.selectedInterface?.type === "wifi" && this.profileSsid && this.selectedInterface?.ssid !== this.profileSsid) {
                return "Saved for " + this.profileSsid + "; connect to that SSID to apply.";
            }
            if (this.profileSsid) return "Static profile ready for " + this.profileSsid + ".";
            return "Static profile ready.";
        },

        receiverRangeIp(dev) {
            if (dev?.ip_config_pending === "static" && dev?.static_ip) return dev.static_ip;
            return dev?.static_ip || dev?.ip || "";
        },

        receiverRangeState(dev) {
            const pending = !!dev?.ip_config_pending;
            const ip = this.receiverRangeIp(dev);
            if (!this.profileNetwork || !this.isIpv4(ip)) {
                return { key: "unknown", label: pending ? "Pending" : "Unknown", pending };
            }
            const inRange = this.ipInSubnet(ip, this.staticIp, this.subnet);
            if (pending) return { key: inRange ? "in" : "out", label: inRange ? "Pending In Range" : "Pending Different Range", pending };
            return { key: inRange ? "in" : "out", label: inRange ? "In Range" : "Different Range", pending };
        },

        receiverRangeClass(dev) {
            const state = this.receiverRangeState(dev);
            return {
                "settings-pill-on": state.key === "in" && !state.pending,
                "settings-pill-warning": state.pending,
                "settings-pill-danger": state.key === "out" && !state.pending,
                "settings-pill-muted": state.key === "unknown",
            };
        },

        receiverRangeLabel(dev) {
            return this.receiverRangeState(dev).label;
        },

        interfaceRowClass(iface) {
            return {
                "settings-interface-selected": this.selectedInterface?.id === iface.id,
                "settings-interface-inactive": !iface.connected,
                "settings-interface-controller": !!iface.is_controller,
                "settings-interface-router": iface.type === "ethernet",
            };
        },

        statusPillClass(iface) {
            return {
                "settings-pill-on": !!iface?.connected,
                "settings-pill-preferred": !!iface?.is_preferred,
                "settings-pill-controller": !!iface?.is_controller,
                "settings-pill-muted": !iface?.connected,
            };
        },

        receiverSummary(dev) {
            const mode = dev.ip_config_pending === "static" ? "Restart for static"
                : dev.ip_config_pending === "dhcp" ? "Restart for DHCP"
                : dev.ip_mode === "static" ? "Static"
                : dev.ip_mode === "dhcp" ? "DHCP"
                : "Unknown";
            const parts = [dev.ip, mode];
            if (dev.static_ip && dev.static_ip !== dev.ip) parts.push("saved " + dev.static_ip);
            return parts.join(" · ");
        },
    }));
});