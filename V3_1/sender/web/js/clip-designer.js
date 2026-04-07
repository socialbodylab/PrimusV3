/**
 * clip-designer.js — Clip Designer Alpine component.
 * Ports the V3.0 UI controls for effect editing with 2 outputs (A0 + A1).
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("clipDesigner", () => ({
        saveModal: false,
        saveName: "",
        saveDuration: 5.0,

        get state() { return Alpine.store("app").state; },
        get look() { return this.state?.look; },
        get outputs() { return this.look?.outputs || []; },
        get outputTypes() { return this.state?.look_output_types || []; },
        get effects() {
            return ["none","solid","pulse","linear","constrainbow","rainbow",
                    "knight_rider","chase","radial","spiral"];
        },

        // ── Update helpers ──
        updateOutput(oi, field, value) {
            const body = { output: oi };
            body[field] = value;
            api("POST", "/api/update", body);
        },

        updateOutputType(oi, type) {
            api("POST", "/api/update", { output: oi, output_type: type });
        },

        updateColor(oi, which, hex) {
            const rgb = hexToRgb(hex);
            api("POST", "/api/update", { output: oi, [which]: rgb });
        },

        updateFps(fps) {
            api("POST", "/api/update", { fps: parseInt(fps) });
        },

        // ── Color hex getters ──
        startHex(oi) {
            const c = this.outputs[oi]?.start_color;
            return c ? rgbToHex(c) : "#ff00ff";
        },
        endHex(oi) {
            const c = this.outputs[oi]?.end_color;
            return c ? rgbToHex(c) : "#00ffff";
        },

        // ── Preview drawing ──
        // Preview is drawn centrally by app.js _drawPreviews() after each poll

        // ── Save ──
        openSave() { this.saveName = ""; this.saveDuration = 5.0; this.saveModal = true; },

        async doSave() {
            if (!this.saveName.trim()) return;
            const outs = this.outputs.map(o => ({
                type: o.type,
                effect: o.effect,
                start_color: o.start_color,
                end_color: o.end_color,
                speed: o.speed,
                playback: o.playback,
                angle: o.angle,
                highlight_width: o.highlight_width,
                chase_origin: o.chase_origin,
                duration: this.saveDuration,
            }));
            await api("POST", "/api/clips/save", {
                name: this.saveName.trim(),
                outputs: outs,
            });
            this.saveModal = false;
        },

        // ── Effect needs helpers ──
        needsColors(effect) {
            return !["none", "rainbow"].includes(effect);
        },
        needsAngle(effect) {
            return ["linear", "chase"].includes(effect);
        },
        needsHighlight(effect) {
            return effect === "knight_rider";
        },
        needsChaseOrigin(effect) {
            return effect === "chase";
        },
    }));
});
