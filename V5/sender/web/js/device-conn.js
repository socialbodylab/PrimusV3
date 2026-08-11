/**
 * device-conn.js — Shared Alpine store for device management (Primus, Radius, Device Manager)
 */

function connProduct() {
    return Alpine.store("app")?.product || "primus";
}

function connProductLabel() {
    return connProduct() === "radius" ? "Radius Central" : "Primus";
}

function isRadiusDevice(dev) {
    if (!dev) return false;
    if (dev.is_radius) return true;
    const caps = dev.capabilities || {};
    if (caps.device_class === "radius" || caps.profile === "pvrad1") return true;
    const name = `${dev.name || ""} ${caps.hardware_label || ""}`.toLowerCase();
    return name.includes("radius") && !caps.output_config;
}

document.addEventListener("alpine:init", () => {
    Alpine.store("conn", {
        discovering: false,
        syncing: false,
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
        lanePortsConfigDevice: -1,
        lanePortsShow: "",
        lanePortsSetup: "",
        lanePortsWatch: "",
        configFeedback: {},
        _ipRediscoveryTimer: null,
        _ipRediscoveryUntil: 0,
        sidebarCollapsed: false,
        showInfoDrafts: {},
        showInfoFocus: null,
        receiveConfigDrafts: {},
        receiveConfigFocus: null,
        virtualConfigDrafts: {},
        virtualConfigFocus: null,
        editingShowInfo: null,
        showInfoEditValue: "",
        descriptorEditor: null,
        descriptorDrafts: {},
        outputPresets: [],
        outputPresetsLoaded: false,
        outputPresetsLoading: false,
        presetSelection: {},
        presetNameDrafts: {},
        telemetryTargetDrafts: {},
        telemetryTargetDirty: {},
        telemetryTargetDeviceIps: {},
        telemetryTargetRevisions: {},
        telemetryTargetPending: {},
        telemetryTargetFocus: null,

        get devices() {
            return Alpine.store("app").state?.devices || [];
        },

        get deviceGroups() {
            return Alpine.store("app").state?.device_groups || [];
        },

        get anyConnected() {
            return this.devices.some(d => d.connected);
        },

        isPrimusManagementDevice(dev) {
            return !isRadiusDevice(dev) && !!dev?.management_supported;
        },

        deviceSettingsLocked(dev) {
            return this.isPrimusManagementDevice(dev) && !!dev?.management_locked;
        },

        canEditDeviceSettings(dev) {
            return !this.deviceSettingsLocked(dev);
        },

        canRenameDevice(dev) {
            return !!dev?.capabilities?.rename && this.canEditDeviceSettings(dev);
        },

        canHelloDevice(dev) {
            if (isRadiusDevice(dev)) {
                return !!dev?.capabilities?.hello || !!dev?.capabilities?.audio;
            }
            return !!dev?.capabilities?.hello;
        },

        canConfigureIp(dev) {
            return !!dev?.capabilities?.ip_config && this.canEditDeviceSettings(dev);
        },

        // Lane ports (Show/Setup/Watch) are part of the Primus management
        // protocol for Primus receivers, and a standalone opcode for Radius
        // nodes — either way they're gated the same way IP config is.
        canConfigureLanePorts(dev) {
            if (!dev) return false;
            if (isRadiusDevice(dev)) return this.canEditDeviceSettings(dev);
            return this.isPrimusManagementDevice(dev) && this.canEditDeviceSettings(dev);
        },

        lanePortsHint(dev) {
            if (!dev) return "";
            if (this.canConfigureLanePorts(dev)) return "Configure this device's Show/Setup/Watch UDP ports.";
            if (this.deviceSettingsLocked(dev)) return "Production-locked; unlock to change lane ports.";
            if (isRadiusDevice(dev)) return "Lane port configuration unavailable for this device.";
            return "This device does not advertise Primus management support, so lane ports cannot be changed remotely.";
        },

        devicePortShow(dev) {
            return dev?.port_show ?? (isRadiusDevice(dev) ? 6456 : 6454);
        },

        devicePortSetup(dev) {
            return dev?.port_setup ?? this.devicePortShow(dev);
        },

        devicePortWatch(dev) {
            return dev?.port_watch ?? 6455;
        },

        // Stock Eos (and any other console that only speaks vanilla Art-Net)
        // sends ArtDmx to UDP 6454. A Primus node whose Show lane has been
        // moved off that default will silently miss that traffic, so flag it
        // in the monitoring view rather than let it look mysteriously dark.
        lanePortsWarning(dev) {
            if (!dev || isRadiusDevice(dev)) return "";
            return this.devicePortShow(dev) !== 6454
                ? "custom Art-Net — stock Eos will not hit this node."
                : "";
        },

        openLanePortsConfig(di) {
            const dev = this.devices[di];
            if (!this.canConfigureLanePorts(dev)) {
                Alpine.store("app").showNotice(this.lanePortsHint(dev), "info");
                return;
            }
            this.lanePortsConfigDevice = di;
            this.lanePortsShow = this.devicePortShow(dev);
            this.lanePortsSetup = this.devicePortSetup(dev);
            this.lanePortsWatch = this.devicePortWatch(dev);
        },

        closeLanePortsConfig() {
            this.lanePortsConfigDevice = -1;
        },

        async setDeviceLanePorts(di) {
            const show = Number(this.lanePortsShow);
            const setup = Number(this.lanePortsSetup);
            const watch = Number(this.lanePortsWatch);
            const name = this.devices[di]?.name || "device";
            const ports = [show, setup, watch];
            if (!ports.every(v => Number.isInteger(v) && v >= 1 && v <= 65535)) {
                Alpine.store("app").showNotice("Show, Setup, and Watch ports must be whole numbers 1-65535.", "warn");
                return;
            }
            if (setup === show || setup === watch) {
                Alpine.store("app").showNotice("Setup port must differ from Show and Watch.", "warn");
                return;
            }
            try {
                await api("POST", "/api/device_lane_ports", {
                    device: di, port_show: show, port_setup: setup, port_watch: watch,
                });
                Alpine.store("app").showNotice("Lane ports updated for " + name + ".", "success");
                this.lanePortsConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError("Lane port update failed", e);
            }
        },

        canConfigureOutputs(dev) {
            return !isRadiusDevice(dev)
                && !!dev?.capabilities?.output_config
                && this.canEditDeviceSettings(dev);
        },

        canConfigureReceiveMode(dev) {
            return !isRadiusDevice(dev)
                && !!dev?.capabilities?.receive_config
                && this.canEditDeviceSettings(dev);
        },

        physicalOutputs(dev) {
            const source = Array.isArray(dev?.outputs) ? dev.outputs : [];
            return [0, 1].map(oi => source[oi] || {
                name: `A${oi}`,
                type: "none",
                enabled: false,
                count: 0,
                physical_pixels: 0,
                virtual_pixels: 0,
                descriptor_layout: "off",
                layout: "off",
                rows: 0,
                columns: 0,
                traversal_axis: "row_major",
                scan_pattern: "progressive",
                start_corner: "top_left",
            });
        },

        receiveModeLabel(dev) {
            const mode = dev?.receive_mode || "split";
            const base = dev?.base_universe ?? 0;
            if (mode === "combined") {
                return `Combined · U${base}`;
            }
            return `Split · U${base}/${base + 1}`;
        },

        receiveModeHint(dev) {
            if (this.deviceSettingsLocked(dev)) {
                return "Receive mode is locked in production; Hello and monitoring remain available";
            }
            if (this.canConfigureReceiveMode(dev)) {
                return "Receive mode and base universe are stored on the receiver (NVS)";
            }
            if (dev?.receive_mode) {
                return "Receive mode reported from device discovery";
            }
            return "Flash firmware v3.8+ to change receive mode remotely";
        },

        initReceiveConfigDrafts(di) {
            if (this.receiveConfigDrafts[di]) {
                return;
            }
            const dev = this.devices[di];
            this.receiveConfigDrafts[di] = {
                receive_mode: dev?.receive_mode || "split",
                base_universe: dev?.base_universe ?? 0,
            };
        },

        syncReceiveConfigDrafts() {
            if (connProduct() !== "primus") {
                return;
            }
            const focusParts = (this.receiveConfigFocus || "").split(":");
            const focusDi = focusParts[0] !== "" ? Number(focusParts[0]) : null;
            const focusField = focusParts[1] || null;
            const validIndices = new Set(this.devices.map((_, di) => String(di)));
            for (const key of Object.keys(this.receiveConfigDrafts)) {
                if (!validIndices.has(String(key))) {
                    delete this.receiveConfigDrafts[key];
                }
            }
            this.devices.forEach((dev, di) => {
                if (!this.receiveConfigDrafts[di]) {
                    this.receiveConfigDrafts[di] = {
                        receive_mode: dev.receive_mode || "split",
                        base_universe: dev.base_universe ?? 0,
                    };
                    return;
                }
                const draft = this.receiveConfigDrafts[di];
                if (!(focusDi === di && focusField === "receive_mode")) {
                    draft.receive_mode = dev.receive_mode || "split";
                }
                if (!(focusDi === di && focusField === "base_universe")) {
                    draft.base_universe = dev.base_universe ?? 0;
                }
            });
        },

        finishReceiveConfigBaseEdit(di) {
            this.receiveConfigFocus = null;
            this.initReceiveConfigDrafts(di);
            const draft = this.receiveConfigDrafts[di];
            if (!draft) {
                return;
            }
            this.setDeviceBaseUniverse(di, draft.base_universe);
        },

        combinedPixelTotal(dev) {
            return (dev?.outputs || []).reduce(
                (sum, output) => sum + this.resolveVirtualPixels(output), 0);
        },

        resolveVirtualPixels(output) {
            const physical = Number(output?.count) || 0;
            if (physical <= 0 || output?.type === "none") {
                return 0;
            }
            const stored = output?.virtual_pixels;
            if (stored == null) {
                return output?.type === "small_grid" ? 1 : physical;
            }
            const virtual = Number(stored) || 0;
            return Math.max(1, Math.min(physical, virtual));
        },

        clampVirtualPixels(output, value) {
            const physical = Number(output?.count) || 0;
            if (physical <= 0) {
                return 0;
            }
            let virtual = Math.round(Number(value));
            if (!Number.isFinite(virtual) || virtual < 1) {
                virtual = 1;
            }
            if (virtual > physical) {
                virtual = physical;
            }
            return virtual;
        },

        virtualTransportReadout(output, draftValue) {
            const physical = Number(output?.count) || 0;
            if (physical <= 0 || output?.type === "none") {
                return "";
            }
            const virtual = draftValue === undefined || draftValue === null || draftValue === ""
                ? this.resolveVirtualPixels(output)
                : this.clampVirtualPixels(output, draftValue);
            if (virtual <= 0) {
                return "";
            }
            const rgbValues = virtual * 3;
            const noun = rgbValues === 1 ? "value" : "values";
            return `${rgbValues} RGB ${noun} · ${physical} LEDs`;
        },

        initVirtualConfigDrafts(di) {
            if (!this.virtualConfigDrafts[di]) {
                this.virtualConfigDrafts[di] = {};
            }
            const dev = this.devices[di];
            (dev?.outputs || []).forEach((output, oi) => {
                if (this.virtualConfigDrafts[di][oi] === undefined) {
                    this.virtualConfigDrafts[di][oi] = this.resolveVirtualPixels(output);
                }
            });
        },

        syncVirtualConfigDrafts() {
            if (connProduct() !== "primus") {
                return;
            }
            const focusParts = (this.virtualConfigFocus || "").split(":");
            const focusDi = focusParts[0] !== "" ? Number(focusParts[0]) : null;
            const focusOi = focusParts[1] !== "" ? Number(focusParts[1]) : null;
            const validIndices = new Set(this.devices.map((_, di) => String(di)));
            for (const key of Object.keys(this.virtualConfigDrafts)) {
                if (!validIndices.has(String(key))) {
                    delete this.virtualConfigDrafts[key];
                }
            }
            this.devices.forEach((dev, di) => {
                if (!this.virtualConfigDrafts[di]) {
                    this.virtualConfigDrafts[di] = {};
                }
                (dev.outputs || []).forEach((output, oi) => {
                    if (focusDi === di && focusOi === oi) {
                        return;
                    }
                    this.virtualConfigDrafts[di][oi] = this.resolveVirtualPixels(output);
                });
            });
        },

        finishVirtualConfigEdit(di, oi) {
            this.virtualConfigFocus = null;
            this.initVirtualConfigDrafts(di);
            const dev = this.devices[di];
            const output = dev?.outputs?.[oi];
            if (!output || output.type === "none") {
                return;
            }
            const draft = this.virtualConfigDrafts[di]?.[oi];
            const virtual = this.clampVirtualPixels(output, draft);
            if (virtual <= 0) {
                this.virtualConfigDrafts[di][oi] = this.resolveVirtualPixels(output);
                return;
            }
            this.virtualConfigDrafts[di][oi] = virtual;
            const prior = this.resolveVirtualPixels(output);
            if (prior === virtual) {
                return;
            }
            this.setDeviceVirtualResolution(di, oi, virtual);
        },

        descriptorKey(di, oi) {
            return `${di}:${oi}`;
        },

        descriptorFromOutput(output) {
            const enabled = output?.enabled !== false
                && output?.type !== "none"
                && Number(output?.physical_pixels ?? output?.count) > 0;
            const layout = enabled
                ? (output?.descriptor_layout || output?.layout || "linear")
                : "off";
            const physical = enabled
                ? Number(output?.physical_pixels ?? output?.count) || 1
                : 0;
            return {
                enabled,
                layout,
                physical_pixels: physical,
                rows: layout === "grid" ? Number(output?.rows) || 1 : 0,
                columns: layout === "grid" ? Number(output?.columns) || physical : 0,
                traversal_axis: output?.traversal_axis || "row_major",
                scan_pattern: output?.scan_pattern || "progressive",
                start_corner: output?.start_corner || "top_left",
                virtual_pixels: enabled
                    ? Number(output?.virtual_pixels) || Math.max(1, physical)
                    : 0,
            };
        },

        normalizedDescriptorDraft(draft) {
            const enabled = draft?.enabled !== false && draft?.layout !== "off";
            if (!enabled) {
                return {
                    enabled: false,
                    layout: "off",
                    physical_pixels: 0,
                    rows: 0,
                    columns: 0,
                    traversal_axis: "row_major",
                    scan_pattern: "progressive",
                    start_corner: "top_left",
                    virtual_pixels: 0,
                };
            }
            const layout = draft?.layout === "grid" ? "grid" : "linear";
            const rows = layout === "grid" ? Number(draft?.rows) : 0;
            const columns = layout === "grid" ? Number(draft?.columns) : 0;
            const physical = layout === "grid"
                ? rows * columns
                : Number(draft?.physical_pixels);
            return {
                enabled: true,
                layout,
                physical_pixels: physical,
                rows,
                columns,
                traversal_axis: ["row_major", "column_major"].includes(draft?.traversal_axis)
                    ? draft.traversal_axis
                    : "row_major",
                scan_pattern: ["progressive", "serpentine"].includes(draft?.scan_pattern)
                    ? draft.scan_pattern
                    : "progressive",
                start_corner: [
                    "top_left",
                    "top_right",
                    "bottom_left",
                    "bottom_right",
                ].includes(draft?.start_corner) ? draft.start_corner : "top_left",
                virtual_pixels: Number(draft?.virtual_pixels),
            };
        },

        validateDescriptorDraft(draft) {
            const enabled = draft?.enabled !== false && draft?.layout !== "off";
            const layout = draft?.layout === "grid" ? "grid" : "linear";
            if (enabled && layout === "linear") {
                const physical = Number(draft?.physical_pixels);
                if (!Number.isFinite(physical) || !Number.isInteger(physical)) {
                    return {
                        valid: false,
                        descriptor: this.normalizedDescriptorDraft(draft),
                        error: "Strip length must be a finite whole number from 1 to 170.",
                    };
                }
            }
            if (enabled && layout === "grid") {
                const rows = Number(draft?.rows);
                const columns = Number(draft?.columns);
                if (!Number.isFinite(rows)
                    || !Number.isFinite(columns)
                    || !Number.isInteger(rows)
                    || !Number.isInteger(columns)) {
                    return {
                        valid: false,
                        descriptor: this.normalizedDescriptorDraft(draft),
                        error: "Grid rows and columns must be finite whole numbers.",
                    };
                }
            }
            if (enabled) {
                const virtual = Number(draft?.virtual_pixels);
                if (!Number.isFinite(virtual) || !Number.isInteger(virtual)) {
                    return {
                        valid: false,
                        descriptor: this.normalizedDescriptorDraft(draft),
                        error: "Virtual pixels must be a finite whole number.",
                    };
                }
            }
            const descriptor = this.normalizedDescriptorDraft(draft);
            if (!descriptor.enabled) return { valid: true, descriptor, error: "" };
            if (descriptor.layout === "linear") {
                if (!Number.isInteger(descriptor.physical_pixels)
                    || descriptor.physical_pixels < 1
                    || descriptor.physical_pixels > 170) {
                    return {
                        valid: false,
                        descriptor,
                        error: "Strip length must be a whole number from 1 to 170.",
                    };
                }
            } else if (!Number.isInteger(descriptor.rows)
                || !Number.isInteger(descriptor.columns)
                || descriptor.rows < 1
                || descriptor.columns < 1
                || descriptor.physical_pixels > 170) {
                return {
                    valid: false,
                    descriptor,
                    error: "Grid rows and columns must be positive whole numbers with a product of 1 to 170.",
                };
            }
            if (!Number.isInteger(descriptor.virtual_pixels)
                || descriptor.virtual_pixels < 1
                || descriptor.virtual_pixels > descriptor.physical_pixels) {
                return {
                    valid: false,
                    descriptor,
                    error: `Virtual pixels must be a whole number from 1 to ${descriptor.physical_pixels}.`,
                };
            }
            return { valid: true, descriptor, error: "" };
        },

        descriptorValidation(di, oi) {
            return this.validateDescriptorDraft(this.descriptorDrafts[this.descriptorKey(di, oi)]);
        },

        descriptorValid(di, oi) {
            return this.descriptorValidation(di, oi).valid;
        },

        descriptorError(di, oi) {
            return this.descriptorValidation(di, oi).error;
        },

        descriptorSummary(draft) {
            const checked = this.validateDescriptorDraft(draft);
            if (!checked.valid) return checked.error;
            const descriptor = checked.descriptor;
            if (!descriptor.enabled) return "Off: no ArtDmx bytes are consumed for this physical slot.";
            if (descriptor.layout === "linear") {
                return `${descriptor.physical_pixels}-pixel strip; ${descriptor.virtual_pixels} RGB triplets sent. ArtDmx remains physical-wire order.`;
            }
            const traversal = descriptor.traversal_axis === "column_major"
                ? "column-major"
                : "row-major";
            return `${descriptor.rows}×${descriptor.columns} grid, ${traversal} ${descriptor.scan_pattern} from ${descriptor.start_corner.replaceAll("_", " ")}; ${descriptor.virtual_pixels} RGB triplets sent. ArtDmx remains physical-wire order.`;
        },

        descriptorOrderPreview(draft) {
            const checked = this.validateDescriptorDraft(draft);
            if (!checked.valid || checked.descriptor.layout !== "grid") return [];
            const descriptor = checked.descriptor;
            const coordinates = [];
            const rowOrder = [...Array(descriptor.rows).keys()];
            const colOrder = [...Array(descriptor.columns).keys()];
            const startsBottom = descriptor.start_corner.startsWith("bottom");
            const startsRight = descriptor.start_corner.endsWith("right");
            if (startsBottom) rowOrder.reverse();
            if (startsRight) colOrder.reverse();
            const major = descriptor.traversal_axis === "column_major" ? colOrder : rowOrder;
            const minorBase = descriptor.traversal_axis === "column_major" ? rowOrder : colOrder;
            major.forEach((majorValue, majorIndex) => {
                const minor = [...minorBase];
                if (descriptor.scan_pattern === "serpentine" && majorIndex % 2 === 1) {
                    minor.reverse();
                }
                minor.forEach(minorValue => {
                    const row = descriptor.traversal_axis === "column_major"
                        ? minorValue
                        : majorValue;
                    const column = descriptor.traversal_axis === "column_major"
                        ? majorValue
                        : minorValue;
                    coordinates.push(`r${row + 1}c${column + 1}`);
                });
            });
            const preview = coordinates.slice(0, 12).map((coordinate, index) => `${index + 1}:${coordinate}`);
            if (coordinates.length > preview.length) preview.push("…");
            return preview;
        },

        openDescriptorEditor(di, oi) {
            const dev = this.devices[di];
            if (!this.isPrimusManagementDevice(dev)) {
                Alpine.store("app").showNotice(
                    "Custom descriptors require Primus management firmware.",
                    "info",
                );
                return;
            }
            const key = this.descriptorKey(di, oi);
            this.descriptorDrafts[key] = this.descriptorFromOutput(
                this.physicalOutputs(dev)[oi],
            );
            this.presetNameDrafts[key] = this.presetNameDrafts[key] || "";
            this.presetSelection[key] = this.presetSelection[key] || "";
            this.descriptorEditor = { di, oi };
            this.loadOutputPresets();
        },

        descriptorEditorOpen(di, oi) {
            return this.descriptorEditor?.di === di && this.descriptorEditor?.oi === oi;
        },

        closeDescriptorEditor() {
            this.descriptorEditor = null;
        },

        setDescriptorLayout(di, oi, layout) {
            const key = this.descriptorKey(di, oi);
            const prior = this.descriptorDrafts[key]
                || this.descriptorFromOutput(this.physicalOutputs(this.devices[di])[oi]);
            if (layout === "off") {
                this.descriptorDrafts[key] = this.normalizedDescriptorDraft({
                    ...prior,
                    enabled: false,
                    layout: "off",
                });
                return;
            }
            const physical = Math.max(1, Number(prior.physical_pixels) || 1);
            this.descriptorDrafts[key] = {
                ...prior,
                enabled: true,
                layout,
                physical_pixels: physical,
                rows: layout === "grid" ? Math.max(1, Number(prior.rows) || 1) : 0,
                columns: layout === "grid"
                    ? Math.max(1, Number(prior.columns) || physical)
                    : 0,
                virtual_pixels: Math.max(1, Math.min(
                    physical,
                    Number(prior.virtual_pixels) || physical,
                )),
            };
        },

        async applyDescriptorDraft(di, oi) {
            const key = this.descriptorKey(di, oi);
            const checked = this.validateDescriptorDraft(this.descriptorDrafts[key]);
            if (!checked.valid) {
                this.setConfigFeedback(
                    this.managementFeedbackKey(di, "descriptor", oi),
                    "error",
                    checked.error,
                );
                return null;
            }
            return this.managementRequest(
                "POST",
                "/api/apply_device_output_descriptor",
                { device: di, output: oi, descriptor: checked.descriptor },
                {
                    di,
                    feedbackKey: this.managementFeedbackKey(di, "descriptor", oi),
                    successMessage: "Descriptor applied",
                    errorLabel: "Descriptor update failed",
                },
            );
        },

        async loadOutputPresets(force = false) {
            if (connProduct() !== "primus" || this.outputPresetsLoading) return this.outputPresets;
            if (this.outputPresetsLoaded && !force) return this.outputPresets;
            this.outputPresetsLoading = true;
            try {
                const result = await api("GET", "/api/output_presets");
                this.outputPresets = Array.isArray(result?.presets) ? result.presets : [];
                this.outputPresetsLoaded = true;
                return this.outputPresets;
            } catch (error) {
                Alpine.store("app").showApiError("Could not load output presets", error);
                return this.outputPresets;
            } finally {
                this.outputPresetsLoading = false;
            }
        },

        selectedPreset(di, oi) {
            const id = this.presetSelection[this.descriptorKey(di, oi)];
            return this.outputPresets.find(preset => preset.id === id) || null;
        },

        loadSelectedPresetDraft(di, oi) {
            const preset = this.selectedPreset(di, oi);
            if (!preset) return;
            this.descriptorDrafts[this.descriptorKey(di, oi)] = this.normalizedDescriptorDraft(
                preset.descriptor,
            );
        },

        async applySelectedPreset(di, oi) {
            const preset = this.selectedPreset(di, oi);
            if (!preset) {
                Alpine.store("app").showNotice("Choose an output preset first.", "warn");
                return null;
            }
            this.descriptorDrafts[this.descriptorKey(di, oi)] = this.normalizedDescriptorDraft(
                preset.descriptor,
            );
            return this.applyDescriptorDraft(di, oi);
        },

        async createOutputPreset(di, oi) {
            const key = this.descriptorKey(di, oi);
            const name = String(this.presetNameDrafts[key] || "").trim();
            const checked = this.validateDescriptorDraft(this.descriptorDrafts[key]);
            if (!name) {
                Alpine.store("app").showNotice("Enter a preset name.", "warn");
                return null;
            }
            if (!checked.valid) {
                Alpine.store("app").showNotice(checked.error, "warn");
                return null;
            }
            try {
                const result = await api("POST", "/api/output_presets", {
                    name,
                    descriptor: checked.descriptor,
                });
                await this.loadOutputPresets(true);
                this.presetSelection[key] = result?.preset?.id || "";
                Alpine.store("app").showNotice(`Saved output preset “${name}”.`, "success");
                return result?.preset || null;
            } catch (error) {
                Alpine.store("app").showApiError("Could not save output preset", error);
                return null;
            }
        },

        async updateSelectedPreset(di, oi) {
            const key = this.descriptorKey(di, oi);
            const preset = this.selectedPreset(di, oi);
            if (!preset || preset.built_in || !preset.editable) return null;
            const checked = this.validateDescriptorDraft(this.descriptorDrafts[key]);
            const name = String(this.presetNameDrafts[key] || preset.name).trim();
            if (!name || !checked.valid) {
                Alpine.store("app").showNotice(
                    checked.valid ? "Enter a preset name." : checked.error,
                    "warn",
                );
                return null;
            }
            try {
                const result = await api("POST", "/api/output_presets", {
                    id: preset.id,
                    name,
                    descriptor: checked.descriptor,
                });
                await this.loadOutputPresets(true);
                Alpine.store("app").showNotice(`Updated output preset “${name}”.`, "success");
                return result?.preset || null;
            } catch (error) {
                Alpine.store("app").showApiError("Could not update output preset", error);
                return null;
            }
        },

        async deleteSelectedPreset(di, oi) {
            const key = this.descriptorKey(di, oi);
            const preset = this.selectedPreset(di, oi);
            if (!preset || preset.built_in || !preset.deletable) return false;
            if (!window.confirm(`Delete output preset “${preset.name}”? This cannot be undone.`)) {
                return false;
            }
            try {
                await api("DELETE", `/api/output_presets/${encodeURIComponent(preset.id)}`);
                this.presetSelection[key] = "";
                await this.loadOutputPresets(true);
                Alpine.store("app").showNotice(`Deleted output preset “${preset.name}”.`, "success");
                return true;
            } catch (error) {
                Alpine.store("app").showApiError("Could not delete output preset", error);
                return false;
            }
        },

        canUseCombinedMode(dev) {
            return this.combinedPixelTotal(dev) <= 170;
        },

        deviceOutputTypes() {
            if (connProduct() !== "primus") return [];
            const app = Alpine.store("app");
            const types = app.outputTypes;
            if (Array.isArray(types)) return types;
            return app.state?.look_output_types || [];
        },

        deviceOutputTypesFor(dev, oi) {
            const types = [...this.deviceOutputTypes()];
            const current = dev?.outputs?.[oi]?.type;
            if (current && !types.includes(current)) {
                types.push(current);
            }
            return types;
        },

        outputConfigHint(dev) {
            if (this.deviceSettingsLocked(dev)) {
                return "Output setup is locked in production; recover prototype mode before editing";
            }
            if (this.canConfigureOutputs(dev)) {
                return "Output type and virtual send resolution are stored on this receiver (NVS)";
            }
            return "Remote output configuration is not advertised for this node";
        },

        virtualResolutionHint(dev) {
            if (this.canConfigureOutputs(dev)) {
                return "Send pixels controls how many RGB triplets Primus sends on Art-Net; the receiver upscales to all physical LEDs";
            }
            if (dev?.outputs?.some((output) => output?.virtual_pixels != null)) {
                return "Virtual send resolution reported from device discovery";
            }
            return "Flash firmware v3.11+ to configure virtual send resolution remotely";
        },

        configFeedbackKey(di, kind, oi) {
            if (kind === "output") return `${di}:output:${oi}`;
            if (kind === "virtual") return `${di}:virtual:${oi}`;
            return `${di}:receive:${kind}`;
        },

        showInfoFeedbackKey(di, field) {
            return `${di}:show:${field}`;
        },

        setConfigFeedback(key, state, message) {
            this.configFeedback[key] = { state, message };
            if (state === "ok" || state === "warn" || state === "error") {
                setTimeout(() => {
                    if (this.configFeedback[key]?.state === state) {
                        delete this.configFeedback[key];
                    }
                }, 3000);
            }
        },

        configFeedbackClass(key) {
            const fb = this.configFeedback[key];
            if (!fb) return "";
            return `device-config-${fb.state}`;
        },

        configFeedbackMessage(key) {
            return this.configFeedback[key]?.message || "";
        },

        isConfigPending(key) {
            return this.configFeedback[key]?.state === "pending";
        },

        managementFeedbackKey(di, kind, oi = null) {
            return oi == null ? `${di}:management:${kind}` : `${di}:management:${kind}:${oi}`;
        },

        managementResultMessage(result, fallback = "Applied") {
            if (result?.readback_pending) {
                return "Applied; awaiting refresh";
            }
            return result?.message || result?.warning || fallback;
        },

        async managementRequest(method, path, body, options = {}) {
            const di = options.di;
            const dev = Number.isInteger(di) ? this.devices[di] : null;
            const key = options.feedbackKey;
            if (key) this.setConfigFeedback(key, "pending", "");
            try {
                if (dev && !this.isPrimusManagementDevice(dev)) {
                    const error = new Error("Primus management is not available for this device");
                    error.status = 409;
                    error.errorCode = "NotAvailable";
                    throw error;
                }
                const result = await api(method, path, body);
                if (key) {
                    this.setConfigFeedback(
                        key,
                        result?.readback_pending ? "warn" : "ok",
                        this.managementResultMessage(result, options.successMessage),
                    );
                }
                if (options.fetchState !== false) {
                    await Alpine.store("app").fetchState();
                }
                return result;
            } catch (error) {
                const message = error?.status === 409 && error?.errorCode === "Locked"
                    ? "Locked in production"
                    : (error?.message || "Request failed");
                if (key) this.setConfigFeedback(key, "error", message);
                Alpine.store("app").showApiError(options.errorLabel || "Device setup failed", error);
                return null;
            }
        },

        syncManagementUi() {
            if (connProduct() !== "primus") return;
            const valid = new Set(this.devices.map((_, di) => String(di)));
            for (const collection of [
                this.telemetryTargetDrafts,
                this.telemetryTargetDirty,
                this.telemetryTargetDeviceIps,
                this.telemetryTargetRevisions,
                this.telemetryTargetPending,
                this.presetSelection,
                this.presetNameDrafts,
            ]) {
                for (const key of Object.keys(collection)) {
                    if (!valid.has(String(key).split(":")[0])) delete collection[key];
                }
            }
            this.devices.forEach((dev, di) => {
                if (!this.isPrimusManagementDevice(dev)) return;
                const deviceChanged = this.telemetryTargetDeviceIps[di] !== dev.ip;
                if (deviceChanged) {
                    this.telemetryTargetDeviceIps[di] = dev.ip;
                    this.telemetryTargetRevisions[di] =
                        (this.telemetryTargetRevisions[di] || 0) + 1;
                    delete this.telemetryTargetPending[di];
                    this.telemetryTargetDirty[di] = false;
                    this.telemetryTargetDrafts[di] = this.telemetryTargetValue(dev);
                    return;
                }
                if (this.telemetryTargetFocus !== di
                    && !this.telemetryTargetDirty[di]
                    && !this.telemetryTargetPending[di]) {
                    this.telemetryTargetDrafts[di] = this.telemetryTargetValue(dev);
                }
            });
        },

        async queryDeviceFullConfig(di) {
            const key = this.managementFeedbackKey(di, "refresh");
            return this.managementRequest(
                "GET",
                `/api/device_full_config?device=${encodeURIComponent(di)}`,
                undefined,
                {
                    di,
                    feedbackKey: key,
                    successMessage: "Loaded saved state",
                    errorLabel: "Could not load device config",
                },
            );
        },

        async refreshDeviceFullConfig(di) {
            const key = this.managementFeedbackKey(di, "refresh");
            return this.managementRequest(
                "POST",
                "/api/refresh_device_full_config",
                { device: di },
                {
                    di,
                    feedbackKey: key,
                    successMessage: "Refreshed from receiver",
                    errorLabel: "Config refresh failed",
                },
            );
        },

        receiveModeSelectLabel(mode) {
            return mode === "combined" ? "Combined" : "Split";
        },

        hardwareLabel(entity) {
            const fallback = connProduct() === "radius" ? "Radius V1" : "Unknown hardware";
            const label = entity?.hardware_label || entity?.hardware_profile || fallback;
            return String(label).replace("V3.1", "V3");
        },

        // Device Manager only: the backend guesses a specific board (e.g. "V3.1 Reverse
        // TFT") for older-firmware nodes that never returned a real board-code capability
        // tag — profile "pv3cap1-legacy"/"primus-legacy" (see parse_node_capabilities in
        // artnet.py). Showing that guess as fact is misleading in a monitoring view, so
        // this reports it honestly instead of asserting an unconfirmed board.
        monitorHardwareLabel(entity) {
            const profile = entity?.capabilities?.profile;
            if (profile === "pv3cap1-legacy" || profile === "primus-legacy") {
                return "Unconfirmed hardware";
            }
            return this.hardwareLabel(entity);
        },

        // Device Manager card footer only: a stage manager scanning the grid cares
        // whether a node is a Primus (LED) or Radius (audio) receiver, not its exact
        // board/firmware version — that detail is one tap away in the expanded card.
        monitorProductLabel(dev) {
            return isRadiusDevice(dev) ? "Radius" : "Primus";
        },

        capabilityItems(entity) {
            const caps = entity?.capabilities || {};
            const items = [
                { key: "rename", label: "Rename", supported: !!caps.rename },
                { key: "ip_config", label: "IP", supported: !!caps.ip_config },
            ];
            if (!isRadiusDevice(entity)) {
                items.splice(1, 0,
                    { key: "hello", label: "Hello", supported: !!caps.hello },
                    { key: "output_config", label: "Outputs", supported: !!caps.output_config },
                    { key: "receive_config", label: "Receive", supported: !!caps.receive_config },
                    { key: "battery", label: "Battery", supported: !!caps.battery },
                );
            } else {
                items.splice(1, 0,
                    { key: "hello", label: "Hello", supported: !!caps.hello || !!caps.audio },
                );
            }
            return items;
        },

        showBattery(dev) {
            return connProduct() === "primus" && !!dev?.capabilities?.battery && !!dev?.connected;
        },

        receiverFpsLabel(dev) {
            if (!dev?.connected) {
                return "";
            }
            if (dev?.receiver_online) {
                if (dev?.receiver_fps != null) {
                    return `${dev.receiver_fps} fps · live`;
                }
                return "live";
            }
            return "waiting for receiver";
        },

        receiverLiveClass(dev) {
            if (!dev?.connected) {
                return "";
            }
            return dev?.receiver_online ? "device-live-ok" : "device-live-warn";
        },

        // Connection-status readout for Device Manager's monitoring view — independent
        // of the internal "connected" (DMX output) flag, which Device Manager no longer
        // surfaces or lets the user toggle.
        monitorStatusLabel(dev) {
            if (dev?.transport_error) return "Error";
            if (dev?.receiver_online) return "Live";
            return "No Signal";
        },

        monitorStatusClass(dev) {
            if (dev?.transport_error) return "dm-status-error";
            if (dev?.receiver_online) return "dm-status-live";
            return "dm-status-nosignal";
        },

        // FPS/battery counterparts of receiverFpsLabel/receiverLiveClass/showBattery
        // for Device Manager's monitoring view — telemetry comes from the UDP 6455
        // listener regardless of connect state, so these don't gate on dev.connected.
        monitorFpsLabel(dev) {
            if (isRadiusDevice(dev)) return "";
            if (dev?.receiver_online) {
                if (dev?.receiver_fps != null) {
                    return `${dev.receiver_fps} fps · live`;
                }
                return "live";
            }
            return "waiting for receiver";
        },

        monitorLiveClass(dev) {
            return dev?.receiver_online ? "device-live-ok" : "device-live-warn";
        },

        monitorShowFps(dev) {
            return !isRadiusDevice(dev) && !!this.monitorFpsLabel(dev);
        },

        monitorCanHello(dev) {
            if (isRadiusDevice(dev)) return true;
            return this.canHelloDevice(dev);
        },

        monitorShowBattery(dev) {
            return !isRadiusDevice(dev) && !!dev?.capabilities?.battery;
        },

        showInfoEnabled(dev) {
            if (dev) {
                return isRadiusDevice(dev) || !!dev?.capabilities?.show_info;
            }
            return connProduct() === "primus" || connProduct() === "radius";
        },

        initShowInfoDrafts(di) {
            if (this.showInfoDrafts[di]) {
                return;
            }
            const dev = this.devices[di];
            this.showInfoDrafts[di] = {
                character_name: dev?.character_name || "",
                performer_name: dev?.performer_name || "",
            };
        },

        syncShowInfoDrafts() {
            const enabled = (dev) => this.showInfoEnabled(dev);
            const focusParts = (this.showInfoFocus || "").split(":");
            const focusDi = focusParts[0] !== "" ? Number(focusParts[0]) : null;
            const focusField = focusParts[1] || null;
            const validIndices = new Set(this.devices.map((_, di) => String(di)));
            for (const key of Object.keys(this.showInfoDrafts)) {
                if (!validIndices.has(String(key))) {
                    delete this.showInfoDrafts[key];
                }
            }
            this.devices.forEach((dev, di) => {
                if (!enabled(dev)) {
                    delete this.showInfoDrafts[di];
                    return;
                }
                if (!this.showInfoDrafts[di]) {
                    this.showInfoDrafts[di] = {
                        character_name: dev.character_name || "",
                        performer_name: dev.performer_name || "",
                    };
                    return;
                }
                const draft = this.showInfoDrafts[di];
                if (!(focusDi === di && focusField === "character_name")) {
                    draft.character_name = dev.character_name || "";
                }
                if (!(focusDi === di && focusField === "performer_name")) {
                    draft.performer_name = dev.performer_name || "";
                }
            });
        },

        showInfoEditKey(di, field) {
            return `${di}:${field}`;
        },

        isEditingShowInfo(di, field) {
            return this.editingShowInfo === this.showInfoEditKey(di, field);
        },

        showInfoDisplay(dev, field) {
            const value = field === "character_name" ? dev?.character_name : dev?.performer_name;
            return value || "Add…";
        },

        showInfoHint(field) {
            if (field === "character_name") {
                return "Click to set character name";
            }
            return "Click to set performer name";
        },

        showInfoStorageHint(dev) {
            if (dev?.capabilities?.show_info) {
                return "Stored on receiver";
            }
            return "Saved on this computer only — flash firmware v3.10+ to store on receiver";
        },

        startShowInfoEdit(di, field) {
            const dev = this.devices[di];
            if (!dev) {
                return;
            }
            if (!this.canEditDeviceSettings(dev)) {
                Alpine.store("app").showNotice(
                    "Show metadata is locked in production mode.",
                    "info",
                );
                return;
            }
            this.editingShowInfo = this.showInfoEditKey(di, field);
            this.showInfoEditValue = field === "character_name"
                ? (dev.character_name || "")
                : (dev.performer_name || "");
        },

        async finishShowInfoEdit(di, field) {
            const key = this.showInfoEditKey(di, field);
            if (this.editingShowInfo !== key) {
                return;
            }
            const trimmed = this.showInfoEditValue.trim().slice(0, 64);
            this.editingShowInfo = null;
            this.showInfoEditValue = "";
            this.initShowInfoDrafts(di);
            this.showInfoDrafts[di][field] = trimmed;
            await this.saveShowInfoField(di, field);
        },

        cancelShowInfoEdit() {
            this.editingShowInfo = null;
            this.showInfoEditValue = "";
        },

        async saveShowInfoField(di, field) {
            const dev = this.devices[di];
            if (!dev || !this.showInfoEnabled(dev) || !this.canEditDeviceSettings(dev)) {
                return;
            }
            this.initShowInfoDrafts(di);
            const trimmed = String(this.showInfoDrafts[di]?.[field] || "").trim().slice(0, 64);
            const current = field === "character_name"
                ? (dev.character_name || "")
                : (dev.performer_name || "");
            const feedbackField = field === "character_name" ? "character" : "performer";
            const feedbackKey = this.showInfoFeedbackKey(di, feedbackField);
            if (trimmed === current) {
                this.showInfoDrafts[di][field] = trimmed;
                return;
            }
            const body = {
                device: di,
                character_name: dev.character_name || "",
                performer_name: dev.performer_name || "",
            };
            body[field] = trimmed;
            this.setConfigFeedback(feedbackKey, "pending", "");
            try {
                const result = await api("POST", "/api/device_show_info", body);
                this.showInfoDrafts[di][field] = trimmed;
                this.setConfigFeedback(feedbackKey, "ok", "Saved");
                await Alpine.store("app").fetchState();
                const label = feedbackField === "character" ? "Character" : "Performer";
                const name = this.devices[di]?.name || "device";
                const storage = result?.applied_to_device
                    ? "saved on receiver"
                    : "saved on this computer (upgrade firmware v3.10+ for receiver storage)";
                Alpine.store("app").showNotice(
                    trimmed
                        ? `${label} for ${name} ${storage}.`
                        : `${label} cleared for ${name}.`,
                    "success",
                    2800,
                );
            } catch (e) {
                this.setConfigFeedback(feedbackKey, "error", "Save failed");
                Alpine.store("app").showApiError("Could not save show info", e);
            }
        },

        firmwareLabel(dev) {
            const version = dev?.live_firmware_version || dev?.firmware_version;
            if (!version) return "—";
            return version.startsWith("v") ? version : `v${version}`;
        },

        batteryLabel(dev) {
            const mode = dev?.battery_power_mode;
            if (mode === "switch_off") return "Off";
            if (mode === "fault") return "—";
            if (mode === "unavailable" || mode == null) return "…";
            const pct = dev?.battery_pct;
            if (pct == null) return "…";
            return `${pct}%`;
        },

        batteryClass(dev) {
            const mode = dev?.battery_power_mode;
            if (mode === "switch_off" || mode === "fault") {
                return "device-battery device-battery-alert";
            }
            if (mode == null) return "device-battery device-battery-pending";
            const pct = dev?.battery_pct;
            if (pct == null) return "device-battery device-battery-pending";
            if (pct <= 15) return "device-battery device-battery-critical";
            if (pct <= 30) return "device-battery device-battery-warn";
            return "device-battery device-battery-ok";
        },

        batteryTitle(dev) {
            if (dev?.battery_warning) return dev.battery_warning;
            const pct = dev?.battery_pct;
            const mv = dev?.battery_mv;
            if (pct == null || mv == null) return "Waiting for battery telemetry…";
            const volts = (mv / 1000).toFixed(2);
            return `${pct}% · ${volts} V`;
        },

        telemetryTargetValue(dev) {
            const target = String(dev?.telemetry_target || "0.0.0.0");
            return target === "0.0.0.0" ? "" : target;
        },

        telemetryTargetLabel(dev) {
            return this.telemetryTargetValue(dev) || "Unset — no telemetry";
        },

        telemetryHealthLabel(dev) {
            if (!dev?.telemetry_configured) return "Off";
            const age = Number(dev?.heartbeat_age_seconds ?? dev?.telemetry_age_seconds);
            if (!Number.isFinite(age)) return "Waiting";
            if (age <= 3) return "Healthy";
            if (age <= 12) return "Stale";
            return "Offline";
        },

        telemetryHealthClass(dev) {
            const label = this.telemetryHealthLabel(dev);
            if (label === "Healthy") return "device-telemetry-healthy";
            if (label === "Stale" || label === "Waiting") return "device-telemetry-stale";
            return "device-telemetry-offline";
        },

        telemetryAgeLabel(dev) {
            const age = Number(dev?.heartbeat_age_seconds ?? dev?.telemetry_age_seconds);
            if (!Number.isFinite(age)) return "no heartbeat";
            if (age < 1) return "just now";
            return `${age.toFixed(age < 10 ? 1 : 0)}s ago`;
        },

        telemetryProtocolLabel(dev) {
            const version = dev?.protocol_version;
            return version == null ? "PST waiting" : `PST v${version}`;
        },

        telemetryDiagnostics(dev) {
            const sequence = dev?.sequence;
            const lost = Number(dev?.telemetry_packets_lost) || 0;
            const reordered = Number(dev?.telemetry_out_of_order_packets) || 0;
            const reboots = Number(dev?.telemetry_reboot_count) || 0;
            const lossRate = Number(dev?.telemetry_packet_loss_rate);
            const loss = Number.isFinite(lossRate) ? ` (${(lossRate * 100).toFixed(1)}%)` : "";
            return `Seq ${sequence ?? "—"} · lost ${lost}${loss} · reordered ${reordered} · reboots ${reboots}`;
        },

        telemetryBatterySummary(dev) {
            const profile = String(
                dev?.capabilities?.hardware_profile
                || dev?.capabilities?.profile
                || dev?.hardware_profile
                || "",
            ).toLowerCase();
            if (profile.includes("v2")) return "V2: battery telemetry unavailable";
            if (dev?.battery_power_mode === "unavailable") return "Battery unavailable";
            if (dev?.battery_power_mode === "switch_off") return "Battery rail switched off";
            if (dev?.battery_power_mode === "fault") return "Battery reading fault";
            if (dev?.battery_pct != null && dev?.battery_mv != null) {
                const source = profile.includes("v3") || profile.includes("v31")
                    ? "V3 regulated rail"
                    : "V1 LiPo";
                return `${source}: ${dev.battery_pct}% · ${(dev.battery_mv / 1000).toFixed(2)} V`;
            }
            return profile.includes("v3") || profile.includes("v31")
                ? "V3 regulated-rail battery telemetry waiting"
                : "V1 LiPo battery telemetry waiting";
        },

        selectedSenderIp() {
            const app = Alpine.store("app");
            const iface = app?.networkPrimaryInterface?.()
                || app?.network?.selected_interface
                || app?.network?.recommended_interface;
            return iface?.source_ip || "";
        },

        useSelectedSenderTelemetryTarget(di) {
            const address = this.selectedSenderIp();
            if (!address) {
                Alpine.store("app").showNotice(
                    "No selected sender/interface IPv4 address is available.",
                    "warn",
                );
                return;
            }
            this.telemetryTargetDrafts[di] = address;
            this.markTelemetryTargetDirty(di);
        },

        markTelemetryTargetDirty(di) {
            this.telemetryTargetDirty[di] = true;
            this.telemetryTargetRevisions[di] =
                (this.telemetryTargetRevisions[di] || 0) + 1;
        },

        resetTelemetryTargetDraft(di) {
            const dev = this.devices[di];
            this.telemetryTargetFocus = null;
            this.telemetryTargetRevisions[di] =
                (this.telemetryTargetRevisions[di] || 0) + 1;
            this.telemetryTargetDirty[di] = false;
            this.telemetryTargetDeviceIps[di] = dev?.ip;
            this.telemetryTargetDrafts[di] = this.telemetryTargetValue(dev);
        },

        telemetrySubmissionCurrent(di, submission) {
            return this.telemetryTargetPending[di] === submission
                && this.devices[di]?.ip === submission.deviceIp
                && (this.telemetryTargetRevisions[di] || 0) === submission.revision
                && String(this.telemetryTargetDrafts[di] || "") === submission.draft;
        },

        async refreshTelemetrySubmission(di, submission) {
            if (!this.telemetrySubmissionCurrent(di, submission)) return false;
            return Alpine.store("app").fetchState(
                () => this.telemetrySubmissionCurrent(di, submission),
            );
        },

        async setTelemetryTarget(di) {
            const target = String(this.telemetryTargetDrafts[di] || "").trim();
            if (!this.isIpv4(target) || target === "0.0.0.0") {
                Alpine.store("app").showNotice(
                    "Telemetry target must be a unicast IPv4 address; use Clear to unset it.",
                    "warn",
                );
                return null;
            }
            this.telemetryTargetFocus = null;
            const submission = {
                deviceIp: this.devices[di]?.ip,
                draft: String(this.telemetryTargetDrafts[di] || ""),
                revision: this.telemetryTargetRevisions[di] || 0,
            };
            this.telemetryTargetPending[di] = submission;
            const result = await this.managementRequest(
                "POST",
                "/api/set_device_telemetry_target",
                { device: di, telemetry_target: target },
                {
                    di,
                    feedbackKey: this.managementFeedbackKey(di, "telemetry"),
                    successMessage: "Telemetry target applied",
                    errorLabel: "Telemetry target update failed",
                    fetchState: false,
                },
            );
            if (result) {
                await this.refreshTelemetrySubmission(di, submission);
            }
            const stillCurrent = this.telemetrySubmissionCurrent(di, submission);
            if (this.telemetryTargetPending[di] === submission) {
                delete this.telemetryTargetPending[di];
            }
            if (result && stillCurrent) {
                this.telemetryTargetDirty[di] = false;
                this.telemetryTargetDeviceIps[di] = submission.deviceIp;
                this.telemetryTargetDrafts[di] = target;
            }
            return result;
        },

        async clearTelemetryTarget(di) {
            this.telemetryTargetFocus = null;
            const submission = {
                deviceIp: this.devices[di]?.ip,
                draft: String(this.telemetryTargetDrafts[di] || ""),
                revision: this.telemetryTargetRevisions[di] || 0,
            };
            this.telemetryTargetPending[di] = submission;
            const result = await this.managementRequest(
                "POST",
                "/api/set_device_telemetry_target",
                { device: di, telemetry_target: null },
                {
                    di,
                    feedbackKey: this.managementFeedbackKey(di, "telemetry"),
                    successMessage: "Telemetry disabled",
                    errorLabel: "Could not clear telemetry target",
                    fetchState: false,
                },
            );
            if (result) {
                await this.refreshTelemetrySubmission(di, submission);
            }
            const stillCurrent = this.telemetrySubmissionCurrent(di, submission);
            if (this.telemetryTargetPending[di] === submission) {
                delete this.telemetryTargetPending[di];
            }
            if (result && stillCurrent) {
                this.telemetryTargetDirty[di] = false;
                this.telemetryTargetDeviceIps[di] = submission.deviceIp;
                this.telemetryTargetDrafts[di] = "";
            }
            return result;
        },

        operatingModeLabel(dev) {
            return dev?.production_mode || dev?.operating_mode === "production"
                ? "Production · Locked"
                : "Prototype · Editable";
        },

        operatingModeClass(dev) {
            return this.deviceSettingsLocked(dev)
                ? "device-mode-production"
                : "device-mode-prototype";
        },

        isV3Hardware(dev) {
            const profile = String(
                dev?.capabilities?.hardware_profile
                || dev?.capabilities?.profile
                || dev?.hardware_profile
                || "",
            ).toLowerCase();
            return profile === "v3"
                || profile === "v31"
                || profile.includes("reverse")
                || profile.includes("tft");
        },

        productionRecoveryText(dev) {
            if (!this.deviceSettingsLocked(dev)) {
                return "Prototype mode permits remote setup changes.";
            }
            if (this.isV3Hardware(dev)) {
                return "V3 recovery: hold D1 on the receiver to return to prototype mode.";
            }
            if (dev?.unlock_window_open) {
                return `V1/V2 boot recovery window open for ${Number(dev.unlock_remaining_seconds) || 0}s.`;
            }
            return "V1/V2 recovery: reboot the receiver, then request unlock during its first 60 seconds.";
        },

        async enterProductionMode(di) {
            const dev = this.devices[di];
            if (!this.isPrimusManagementDevice(dev) || this.deviceSettingsLocked(dev)) return null;
            const confirmed = window.confirm(
                "Enter production mode? This locks technical name, show metadata, IP, outputs, receive mode, and telemetry target. Hello, ArtDmx, discovery, and monitoring remain active.",
            );
            if (!confirmed) return null;
            return this.managementRequest(
                "POST",
                "/api/enter_device_production_mode",
                { device: di },
                {
                    di,
                    feedbackKey: this.managementFeedbackKey(di, "mode"),
                    successMessage: "Production lock enabled",
                    errorLabel: "Could not enter production mode",
                },
            );
        },

        async requestBootWindowUnlock(di) {
            const dev = this.devices[di];
            if (!this.isPrimusManagementDevice(dev)
                || this.isV3Hardware(dev)
                || !dev?.unlock_window_open) {
                return null;
            }
            const confirmed = window.confirm(
                "Return this receiver to prototype mode while its boot recovery window is open?",
            );
            if (!confirmed) return null;
            return this.managementRequest(
                "POST",
                "/api/unlock_device_boot_window",
                { device: di },
                {
                    di,
                    feedbackKey: this.managementFeedbackKey(di, "mode"),
                    successMessage: "Prototype mode restored",
                    errorLabel: "Boot-window unlock failed",
                },
            );
        },

        capabilityStatusLabel(entity) {
            const caps = entity?.capabilities || {};
            const supportedCount = this.capabilityItems(entity).filter(item => item.supported).length;
            if (caps.known) return "Advertised";
            if (supportedCount > 0) return "Legacy fallback";
            return "Not advertised";
        },

        capabilityStatusClass(entity) {
            const caps = entity?.capabilities || {};
            const supportedCount = this.capabilityItems(entity).filter(item => item.supported).length;
            if (caps.known) return "device-capability-status-advertised";
            if (supportedCount > 0) return "device-capability-status-legacy";
            return "device-capability-status-missing";
        },

        renameHint(dev) {
            if (this.deviceSettingsLocked(dev)) {
                return "Technical name is locked in production mode";
            }
            return this.canRenameDevice(dev)
                ? "Click to rename"
                : "Remote rename is not advertised for this node";
        },

        helloHint(dev) {
            if (isRadiusDevice(dev)) {
                return this.canHelloDevice(dev)
                    ? "Send test tone"
                    : "Test tone is not advertised for this node";
            }
            return this.canHelloDevice(dev)
                ? "Send identify flash"
                : "Identify flash is not advertised for this node";
        },

        ipConfigHint(dev) {
            if (this.deviceSettingsLocked(dev)) {
                return "IP settings are locked in production mode";
            }
            return this.canConfigureIp(dev)
                ? "Configure static or DHCP IP settings"
                : "Remote IP configuration is not advertised for this node";
        },

        networkModeLabel(dev) {
            if (dev?.ip_config_pending === "static") return "Restart for static";
            if (dev?.ip_config_pending === "dhcp") return "Restart for DHCP";
            if (dev?.ip_mode === "static") return "Static";
            if (dev?.ip_mode === "dhcp") return "DHCP";
            return "IP Unknown";
        },

        networkModeClass(dev) {
            return {
                "device-network-static": dev?.ip_mode === "static" && !dev?.ip_config_pending,
                "device-network-dhcp": dev?.ip_mode === "dhcp" && !dev?.ip_config_pending,
                "device-network-pending": !!dev?.ip_config_pending,
                "device-network-unknown": !dev?.ip_config_pending && dev?.ip_mode !== "static" && dev?.ip_mode !== "dhcp",
            };
        },

        networkModeTitle(dev) {
            const label = connProductLabel();
            if (dev?.ip_config_pending === "static") {
                return `Restart this receiver; ${label} will automatically pick up the static IP when it comes back online.`;
            }
            if (dev?.ip_config_pending === "dhcp") {
                return `Restart this receiver; ${label} will automatically pick up the DHCP address when it comes back online.`;
            }
            if (dev?.ip_mode === "static") return "Static IP" + (dev.static_ip ? ": " + dev.static_ip : "");
            if (dev?.ip_mode === "dhcp") return "DHCP assigned address";
            return "This receiver has not reported DHCP/static mode yet.";
        },

        hasPendingIpConfig() {
            return this.devices.some(dev => !!dev.ip_config_pending);
        },

        isKnownDiscoveryNode(node) {
            return this.devices.some(dev => dev.ip === node.ip);
        },

        filterNewDiscoveryNodes(nodes) {
            return (nodes || []).filter(node => !this.isKnownDiscoveryNode(node));
        },

        isIpv4(value) {
            const parts = String(value || "").trim().split(".");
            return parts.length === 4 && parts.every(part => {
                if (!/^\d+$/.test(part)) return false;
                const octet = Number(part);
                return octet >= 0 && octet <= 255;
            });
        },

        scheduleRediscovery() {
            if (this._ipRediscoveryTimer) clearTimeout(this._ipRediscoveryTimer);
            this._ipRediscoveryUntil = Date.now() + 90000;
            this.queueIpRediscovery(3000);
        },

        queueIpRediscovery(delay = 4000) {
            if (this._ipRediscoveryTimer) clearTimeout(this._ipRediscoveryTimer);
            this._ipRediscoveryTimer = setTimeout(() => this.runIpRediscovery(), delay);
        },

        async runIpRediscovery() {
            this._ipRediscoveryTimer = null;
            if (!this.hasPendingIpConfig()) return;
            try {
                const nodes = await api("POST", "/api/discover");
                await Alpine.store("app").fetchState();
                this.discovered = this.filterNewDiscoveryNodes(nodes);
                if (this.hasPendingIpConfig() && Date.now() < this._ipRediscoveryUntil) {
                    this.queueIpRediscovery(4000);
                    return;
                }
                if (!this.hasPendingIpConfig()) {
                    Alpine.store("app").showNotice("Network settings refreshed from receiver discovery.", "success", 3200);
                } else {
                    Alpine.store("app").showNotice("Still waiting for the receiver to restart and report its new IP settings.", "warn", 5000);
                }
            } catch (e) {
                if (Date.now() < this._ipRediscoveryUntil) {
                    this.queueIpRediscovery(5000);
                }
            }
        },

        async connect(di) {
            try {
                await api("POST", "/api/connect", { device: di });
                await Alpine.store("app").fetchState();
            } catch (e) {
                Alpine.store("app").showApiError("Connect failed", e);
            }
        },

        async disconnect(di) {
            await api("POST", "/api/disconnect", { device: di });
            await Alpine.store("app").fetchState();
        },

        async connectAll() {
            try {
                await api("POST", "/api/connect_all");
                await Alpine.store("app").fetchState();
            } catch (e) {
                Alpine.store("app").showApiError("Connect all failed", e);
            }
        },

        async disconnectAll() {
            await api("POST", "/api/disconnect_all");
            await Alpine.store("app").fetchState();
        },

        async syncNetwork(options = {}) {
            const startup = !!options?.startup;
            this.syncing = true;
            try {
                const result = await api("POST", "/api/devices/sync");
                await Alpine.store("app").fetchState();
                const added = result?.added?.length || 0;
                const connected = result?.connected?.length || 0;
                Alpine.store("app").clearStartupScanNotice();
                if (!startup) {
                    Alpine.store("app").showNotice(
                        added
                            ? `Synced network: added ${added} device${added === 1 ? "" : "s"}, connected ${connected}.`
                            : `Synced network: connected ${connected} device${connected === 1 ? "" : "s"}.`,
                        "success",
                    );
                }
                return result;
            } catch (e) {
                if (startup) {
                    Alpine.store("app").beginStartupScanNotice();
                } else {
                    Alpine.store("app").showApiError("Network sync failed", e);
                }
                throw e;
            } finally {
                this.syncing = false;
            }
        },

        // Background heartbeat sync for Device Manager's automatic polling — does not
        // toggle `syncing` (so the manual "Sync now" button doesn't flicker) and only
        // surfaces a notice when something actually changed, since it fires every ~20s.
        async autoSyncNetwork() {
            try {
                const result = await api("POST", "/api/devices/sync");
                await Alpine.store("app").fetchState();
                Alpine.store("app").clearStartupScanNotice();
                const added = result?.added?.length || 0;
                if (added) {
                    Alpine.store("app").showNotice(
                        `Discovered ${added} new device${added === 1 ? "" : "s"} on the network.`,
                        "success",
                    );
                }
                return result;
            } catch (e) {
                return null;
            }
        },

        async helloDevice(di) {
            try {
                const dev = this.devices[di];
                const body = { device: di };
                if (isRadiusDevice(dev)) {
                    body.volume = Alpine.store("audio")?.getVolume?.(di) ?? 80;
                }
                await api("POST", "/api/hello_device", body);
                const name = this.devices[di]?.name || "device";
                Alpine.store("app").showNotice("Identify flash sent to " + name + ".", "success", 2200);
            } catch (e) {
                Alpine.store("app").showApiError("Hello failed", e);
            }
        },

        async setDeviceOutputType(di, oi, outputType) {
            const dev = this.devices[di];
            const priorType = dev?.outputs?.[oi]?.type;
            if (!priorType || priorType === outputType) return;
            const key = this.configFeedbackKey(di, "output", oi);
            this.setConfigFeedback(key, "pending", "");
            try {
                const result = await api("POST", "/api/set_device_output", {
                    device: di,
                    output: oi,
                    output_type: outputType,
                });
                this.setConfigFeedback(key, "ok", result?.message || "Applied");
            } catch (e) {
                this.setConfigFeedback(key, "error", e.message || "Update failed");
                Alpine.store("app").showApiError("Output update failed", e);
            } finally {
                await Alpine.store("app").fetchState();
            }
        },

        async setDeviceVirtualResolution(di, oi, virtualPixels) {
            const dev = this.devices[di];
            const output = dev?.outputs?.[oi];
            if (!output || output.type === "none") {
                return;
            }
            const virtual = this.clampVirtualPixels(output, virtualPixels);
            if (virtual <= 0) {
                return;
            }
            const prior = this.resolveVirtualPixels(output);
            if (prior === virtual) {
                return;
            }
            const key = this.configFeedbackKey(di, "virtual", oi);
            this.setConfigFeedback(key, "pending", "");
            try {
                const result = await api("POST", "/api/set_device_virtual_resolution", {
                    device: di,
                    output: oi,
                    virtual_pixels: virtual,
                });
                this.setConfigFeedback(key, "ok", result?.message || "Applied");
            } catch (e) {
                this.setConfigFeedback(key, "error", e.message || "Update failed");
                this.virtualConfigDrafts[di][oi] = prior;
                Alpine.store("app").showApiError("Virtual resolution update failed", e);
            } finally {
                await Alpine.store("app").fetchState();
            }
        },

        async setDeviceReceiveModeValue(di, receiveMode) {
            const dev = this.devices[di];
            if (!dev) return;
            this.initReceiveConfigDrafts(di);
            const mode = receiveMode || this.receiveConfigDrafts[di]?.receive_mode || "split";
            const priorMode = dev.receive_mode || "split";
            if (priorMode === mode) return;
            if (mode === "combined" && !this.canUseCombinedMode(dev)) {
                Alpine.store("app").showNotice(
                    "Combined mode requires at most 170 pixels across outputs", "error");
                this.receiveConfigDrafts[di].receive_mode = priorMode;
                return;
            }
            await this._applyReceiveMode(
                di,
                mode,
                this.receiveConfigDrafts[di]?.base_universe ?? dev.base_universe ?? 0,
                "mode",
            );
        },

        async setDeviceBaseUniverse(di, baseUniverse) {
            const dev = this.devices[di];
            if (!dev) return;
            this.initReceiveConfigDrafts(di);
            const base = Number(
                baseUniverse ?? this.receiveConfigDrafts[di]?.base_universe ?? dev.base_universe ?? 0,
            );
            if (!Number.isFinite(base) || base < 0 || base > 32767) {
                Alpine.store("app").showNotice("Base universe must be 0–32767", "error");
                this.receiveConfigDrafts[di].base_universe = dev.base_universe ?? 0;
                return;
            }
            if ((dev.base_universe ?? 0) === base) return;
            const mode = this.receiveConfigDrafts[di]?.receive_mode || dev.receive_mode || "split";
            if (mode === "combined" && !this.canUseCombinedMode(dev)) {
                Alpine.store("app").showNotice(
                    "Combined mode requires at most 170 pixels across outputs", "error");
                this.receiveConfigDrafts[di].base_universe = dev.base_universe ?? 0;
                return;
            }
            await this._applyReceiveMode(di, mode, base, "base");
        },

        async _applyReceiveMode(di, receiveMode, baseUniverse, feedbackKind) {
            const key = this.configFeedbackKey(di, feedbackKind);
            this.setConfigFeedback(key, "pending", "");
            try {
                const result = await api("POST", "/api/set_device_receive_mode", {
                    device: di,
                    receive_mode: receiveMode,
                    base_universe: baseUniverse,
                });
                this.setConfigFeedback(key, "ok", result?.message || "Applied");
                this.initReceiveConfigDrafts(di);
                this.receiveConfigDrafts[di].receive_mode = receiveMode;
                this.receiveConfigDrafts[di].base_universe = baseUniverse;
            } catch (e) {
                this.setConfigFeedback(key, "error", e.message || "Update failed");
                Alpine.store("app").showApiError("Receive mode update failed", e);
                this.syncReceiveConfigDrafts();
            } finally {
                await Alpine.store("app").fetchState();
            }
        },

        async discover() {
            this.discovering = true;
            try {
                const nodes = await api("POST", "/api/discover");
                await Alpine.store("app").fetchState();
                this.discovered = this.filterNewDiscoveryNodes(nodes);
                const count = this.discovered.length;
                const total = nodes.length;
                Alpine.store("app").showNotice(
                    count
                        ? "Discovery found " + count + " new device" + (count === 1 ? "" : "s") + "."
                        : total
                        ? "Discovery refreshed " + total + " known device" + (total === 1 ? "" : "s") + "."
                        : "Discovery finished with no devices found.",
                    count ? "success" : "info",
                );
            } catch (e) {
                Alpine.store("app").showApiError("Discovery failed", e);
            } finally {
                this.discovering = false;
            }
        },

        async addDiscovered(node) {
            try {
                const result = await api("POST", "/api/add_discovered", node);
                this.discovered = this.discovered.filter(n => n.ip !== node.ip);
                await Alpine.store("app").fetchState();
                const added = result?.status === "added";
                Alpine.store("app").showNotice(
                    result?.connect_error
                        ? "Added " + (node.short_name || node.ip) + ", but connect failed: " + result.connect_error
                        : added
                        ? "Added " + (node.short_name || node.ip) + "."
                        : (node.short_name || node.ip) + " is already in the device list.",
                    result?.connect_error ? "warn" : (added ? "success" : "info"),
                );
            } catch (e) {
                Alpine.store("app").showApiError("Could not add discovered device", e);
            }
        },

        async addManualIp() {
            const ip = this.manualIp.trim();
            if (!ip) return;
            try {
                const result = await api("POST", "/api/add_manual", { ip });
                await Alpine.store("app").fetchState();
                Alpine.store("app").showNotice(
                    result?.connect_error
                        ? "Added device at " + ip + ", but connect failed: " + result.connect_error
                        : result?.status === "added"
                        ? "Added device at " + ip + "."
                        : "Device " + ip + " is already in the list.",
                    result?.connect_error ? "warn" : (result?.status === "added" ? "success" : "info"),
                );
                this.manualIp = "";
            } catch (e) {
                Alpine.store("app").showApiError("Could not add manual device", e);
            }
        },

        async removeDevice(di) {
            await api("POST", "/api/remove_device", { device: di });
            await Alpine.store("app").fetchState();
        },

        startRename(di) {
            const dev = this.devices[di];
            if (!this.canRenameDevice(dev)) {
                Alpine.store("app").showNotice(this.renameHint(dev), "info");
                return;
            }
            this.renamingDevice = di;
            this.renameValue = dev?.name || "";
        },

        async finishRename(di) {
            const name = this.renameValue.trim();
            const oldName = this.devices[di]?.name || "device";
            if (name && name !== oldName) {
                try {
                    await api("POST", "/api/rename_node", { device: di, name });
                    await Alpine.store("app").fetchState();
                    Alpine.store("app").showNotice("Renamed " + oldName + " to " + name + ".", "success");
                } catch (e) {
                    Alpine.store("app").showApiError("Rename failed", e);
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

        openIpConfig(di) {
            const dev = this.devices[di];
            if (!this.canConfigureIp(dev)) {
                Alpine.store("app").showNotice(this.ipConfigHint(dev), "info");
                return;
            }
            this.ipConfigDevice = di;
            this.ipConfigIp = dev?.static_ip || dev?.ip || "";
            this.ipConfigGateway = dev?.gateway || (dev?.ip ? dev.ip.replace(/\.\d+$/, ".1") : "");
            this.ipConfigSubnet = dev?.subnet || "255.255.255.0";
        },

        closeIpConfig() {
            this.ipConfigDevice = -1;
        },

        async setStaticIp(di) {
            const ip = this.ipConfigIp.trim();
            const gw = this.ipConfigGateway.trim();
            const sn = this.ipConfigSubnet.trim();
            const name = this.devices[di]?.name || "device";
            const label = connProductLabel();
            if (!ip || !gw || !sn) {
                Alpine.store("app").showNotice("Enter IP, gateway, and subnet before applying a static IP.", "warn");
                return;
            }
            if (!this.isIpv4(ip) || !this.isIpv4(gw) || !this.isIpv4(sn)) {
                Alpine.store("app").showNotice("Static IP, gateway, and subnet must be valid IPv4 addresses.", "warn");
                return;
            }
            try {
                await api("POST", "/api/set_device_ip", { device: di, ip, gateway: gw, subnet: sn });
                Alpine.store("app").showNotice(
                    "Restart " + name + "; " + label + " will pick up static IP " + ip + " automatically when it comes back online.",
                    "warn",
                    7000,
                );
                this.ipConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError("Static IP update failed", e);
            }
        },

        async revertDhcp(di) {
            const name = this.devices[di]?.name || "device";
            const label = connProductLabel();
            try {
                await api("POST", "/api/revert_device_dhcp", { device: di });
                Alpine.store("app").showNotice(
                    "Restart " + name + "; " + label + " will pick up its DHCP address automatically when it comes back online.",
                    "warn",
                    7000,
                );
                this.ipConfigDevice = -1;
                this.scheduleRediscovery();
            } catch (e) {
                Alpine.store("app").showApiError("DHCP revert failed", e);
            }
        },

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
            await Alpine.store("app").fetchState();
            this.groupModal = false;
        },

        async deleteGroup(gid) {
            await api("DELETE", "/api/device_groups/" + gid);
            await Alpine.store("app").fetchState();
        },

        async connectGroup(group) {
            for (let di = 0; di < this.devices.length; di++) {
                if (group.device_ips.includes(this.devices[di].ip) && !this.devices[di].connected) {
                    await api("POST", "/api/connect", { device: di });
                }
            }
            await Alpine.store("app").fetchState();
        },

        async disconnectGroup(group) {
            for (let di = 0; di < this.devices.length; di++) {
                if (group.device_ips.includes(this.devices[di].ip) && this.devices[di].connected) {
                    await api("POST", "/api/disconnect", { device: di });
                }
            }
            await Alpine.store("app").fetchState();
        },

        // ---- Device Manager bulk actions ----
        // Additive only: client-side loops over the existing single-device endpoints
        // above (rename_node, set_device_output, set_device_receive_mode). Not called
        // from Primus/Radius markup — safe to extend without touching shared behavior.
        groupDeviceIndices(group) {
            const ips = group?.device_ips || [];
            return ips
                .map(ip => this.devices.findIndex(dev => dev.ip === ip))
                .filter(di => di !== -1);
        },

        formatBulkName(pattern, n, padWidth) {
            const num = padWidth > 0 ? String(n).padStart(padWidth, "0") : String(n);
            return String(pattern || "").replace(/\{n\}/g, num).trim().slice(0, 17);
        },

        bulkRenamePreview(group, pattern, startNum, padWidth = 0) {
            const indices = this.groupDeviceIndices(group);
            return indices.map((di, i) => {
                const dev = this.devices[di];
                return {
                    di,
                    ip: dev?.ip,
                    oldName: dev?.name || "",
                    newName: this.formatBulkName(pattern, (startNum ?? 1) + i, padWidth),
                    canRename: this.canRenameDevice(dev),
                };
            });
        },

        async bulkRenameApply(plan) {
            let succeeded = 0;
            let failed = 0;
            for (const item of plan || []) {
                if (!item.canRename || !item.newName || item.newName === item.oldName) continue;
                try {
                    await api("POST", "/api/rename_node", { device: item.di, name: item.newName });
                    succeeded++;
                } catch (e) {
                    failed++;
                }
            }
            await Alpine.store("app").fetchState();
            const total = succeeded + failed;
            Alpine.store("app").showNotice(
                failed
                    ? `Renamed ${succeeded}/${total} devices; ${failed} failed.`
                    : `Renamed ${succeeded} device${succeeded === 1 ? "" : "s"}.`,
                failed ? "warn" : "success",
                4000,
            );
            return { succeeded, failed };
        },

        async bulkApplyOutputType(group, outputIndex, outputType) {
            const indices = this.groupDeviceIndices(group);
            let succeeded = 0;
            let failed = 0;
            let skipped = 0;
            for (const di of indices) {
                const dev = this.devices[di];
                const output = dev?.outputs?.[outputIndex];
                if (!this.canConfigureOutputs(dev) || !output) {
                    skipped++;
                    continue;
                }
                if (output.type === outputType) {
                    succeeded++;
                    continue;
                }
                try {
                    await api("POST", "/api/set_device_output", {
                        device: di,
                        output: outputIndex,
                        output_type: outputType,
                    });
                    succeeded++;
                } catch (e) {
                    failed++;
                }
            }
            await Alpine.store("app").fetchState();
            Alpine.store("app").showNotice(
                `Output update applied to ${succeeded} device${succeeded === 1 ? "" : "s"}`
                    + (failed ? `; ${failed} failed` : "")
                    + (skipped ? `; ${skipped} skipped (unsupported)` : "") + ".",
                failed ? "warn" : "success",
                4000,
            );
            return { succeeded, failed, skipped };
        },

        async bulkApplyDescriptor(group, outputIndex, descriptorTemplate) {
            const checked = this.validateDescriptorDraft(descriptorTemplate);
            if (!checked.valid) {
                Alpine.store("app").showNotice(checked.error, "error");
                return { succeeded: 0, failed: 0, skipped: 0, results: [] };
            }
            const indices = this.groupDeviceIndices(group);
            let succeeded = 0;
            let failed = 0;
            let skipped = 0;
            const results = [];
            for (const di of indices) {
                const dev = this.devices[di];
                if (!this.isPrimusManagementDevice(dev)
                    || this.deviceSettingsLocked(dev)
                    || !this.physicalOutputs(dev)[outputIndex]) {
                    skipped++;
                    results.push({
                        device: dev?.name || dev?.ip || `Device ${di}`,
                        status: "skipped",
                        error: this.deviceSettingsLocked(dev)
                            ? "locked in production"
                            : "management descriptor setup unsupported",
                    });
                    continue;
                }
                try {
                    const result = await api("POST", "/api/apply_device_output_descriptor", {
                        device: di,
                        output: outputIndex,
                        descriptor: checked.descriptor,
                    });
                    succeeded++;
                    results.push({
                        device: dev?.name || dev?.ip || `Device ${di}`,
                        status: result?.readback_pending ? "refresh_pending" : "applied",
                    });
                } catch (error) {
                    failed++;
                    results.push({
                        device: dev?.name || dev?.ip || `Device ${di}`,
                        status: "failed",
                        error: error?.message || "request failed",
                    });
                }
            }
            await Alpine.store("app").fetchState();
            Alpine.store("app").showNotice(
                `Descriptor applied to ${succeeded} device${succeeded === 1 ? "" : "s"}`
                    + (failed ? `; ${failed} failed` : "")
                    + (skipped ? `; ${skipped} skipped` : "") + ".",
                failed ? "warn" : "success",
                4500,
            );
            return { succeeded, failed, skipped, results };
        },

        async bulkApplyReceiveMode(group, mode, baseStart, baseStep = 0) {
            const indices = this.groupDeviceIndices(group);
            let succeeded = 0;
            let failed = 0;
            let skipped = 0;
            for (let i = 0; i < indices.length; i++) {
                const di = indices[i];
                const dev = this.devices[di];
                const base = Number(baseStart || 0) + i * Number(baseStep || 0);
                if (!this.canConfigureReceiveMode(dev)) {
                    skipped++;
                    continue;
                }
                if (mode === "combined" && !this.canUseCombinedMode(dev)) {
                    skipped++;
                    continue;
                }
                try {
                    await api("POST", "/api/set_device_receive_mode", {
                        device: di,
                        receive_mode: mode,
                        base_universe: base,
                    });
                    succeeded++;
                } catch (e) {
                    failed++;
                }
            }
            await Alpine.store("app").fetchState();
            Alpine.store("app").showNotice(
                `Receive mode applied to ${succeeded} device${succeeded === 1 ? "" : "s"}`
                    + (failed ? `; ${failed} failed` : "")
                    + (skipped ? `; ${skipped} skipped (unsupported or over pixel budget)` : "") + ".",
                failed ? "warn" : "success",
                4000,
            );
            return { succeeded, failed, skipped };
        },
    });
});
