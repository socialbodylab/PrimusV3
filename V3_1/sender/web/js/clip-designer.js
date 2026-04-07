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
        drawPreview(oi) {
            const canvas = this.$refs["preview_" + oi];
            if (!canvas) return;
            const pixels = this.outputs[oi]?.pixels || [];
            const grid = this.outputs[oi]?.grid;
            const ctx = canvas.getContext("2d");

            if (grid) {
                const [cols, rows] = grid;
                canvas.width = cols;
                canvas.height = rows;
                ctx.clearRect(0, 0, cols, rows);
                for (let i = 0; i < pixels.length; i++) {
                    const x = i % cols, y = Math.floor(i / cols);
                    const p = pixels[i] || [0,0,0];
                    ctx.fillStyle = `rgb(${p[0]},${p[1]},${p[2]})`;
                    ctx.fillRect(x, y, 1, 1);
                }
            } else {
                const count = pixels.length || 1;
                canvas.width = count;
                canvas.height = 1;
                ctx.clearRect(0, 0, count, 1);
                for (let i = 0; i < pixels.length; i++) {
                    const p = pixels[i] || [0,0,0];
                    ctx.fillStyle = `rgb(${p[0]},${p[1]},${p[2]})`;
                    ctx.fillRect(i, 0, 1, 1);
                }
            }
        },

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
