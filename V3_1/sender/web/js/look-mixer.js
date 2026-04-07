/**
 * look-mixer.js — Look Mixer Alpine component.
 * Timeline-based look editor with clip segments on per-output tracks.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("lookMixer", () => ({
        look: null,
        clips: [],
        playing: false,
        playTime: 0,
        _playInterval: null,
        saveModal: false,
        saveName: "",
        saveDesc: "",
        pixelsPerSecond: 80,

        get outputTypes() {
            return Alpine.store("app").state?.look_output_types || [];
        },

        async init() {
            await this.loadClips();
            this.newLook();
        },

        async loadClips() {
            this.clips = await api("GET", "/api/clips");
        },

        newLook() {
            this.look = {
                id: "",
                name: "New Look",
                description: "",
                outputs: [
                    { port: "A0", type: "short_strip" },
                    { port: "A1", type: "long_strip" },
                ],
                tracks: [
                    { port: "A0", segments: [] },
                    { port: "A1", segments: [] },
                ],
                playback: "loop",
                total_duration: 10.0,
            };
            this.playTime = 0;
            this.stop();
        },

        // ── Track output type ──
        setOutputType(trackIdx, type) {
            if (this.look.outputs[trackIdx]) {
                this.look.outputs[trackIdx].type = type;
            }
        },

        // ── Add segment ──
        addSegment(trackIdx, clip) {
            const track = this.look.tracks[trackIdx];
            if (!track) return;
            const lastEnd = track.segments.reduce(
                (max, s) => Math.max(max, s.start_time + s.duration), 0);
            track.segments.push({
                clip_id: clip.id,
                clip_name: clip.name,
                start_color: clip.start_color,
                end_color: clip.end_color,
                start_time: lastEnd,
                duration: clip.duration || 5.0,
                fade_in: 0.5,
                fade_out: 0.5,
            });
            // Extend total_duration if needed
            const newEnd = lastEnd + (clip.duration || 5.0);
            if (newEnd > this.look.total_duration) {
                this.look.total_duration = Math.ceil(newEnd);
            }
        },

        removeSegment(trackIdx, segIdx) {
            this.look.tracks[trackIdx]?.segments.splice(segIdx, 1);
        },

        // ── Segment positioning (CSS) ──
        segmentStyle(seg) {
            const left = seg.start_time * this.pixelsPerSecond;
            const width = Math.max(seg.duration * this.pixelsPerSecond, 20);
            const sc = seg.start_color || [80, 80, 200];
            const ec = seg.end_color || [200, 80, 80];
            return `left:${left}px;width:${width}px;`
                + `background:linear-gradient(90deg, rgb(${sc}), rgb(${ec}))`;
        },

        timelineWidth() {
            return (this.look?.total_duration || 10) * this.pixelsPerSecond;
        },

        // ── Ruler ticks ──
        rulerTicks() {
            const dur = this.look?.total_duration || 10;
            const ticks = [];
            for (let t = 0; t <= dur; t++) {
                ticks.push({ t, left: t * this.pixelsPerSecond });
            }
            return ticks;
        },

        playheadLeft() {
            return this.playTime * this.pixelsPerSecond;
        },

        // ── Transport ──
        play() {
            if (this.playing) return;
            this.playing = true;
            const start = performance.now() - this.playTime * 1000;
            this._playInterval = setInterval(() => {
                const elapsed = (performance.now() - start) / 1000;
                const dur = this.look?.total_duration || 10;
                if (this.look?.playback === "loop") {
                    this.playTime = elapsed % dur;
                } else if (this.look?.playback === "boomerang") {
                    const cyc = elapsed % (dur * 2);
                    this.playTime = cyc <= dur ? cyc : dur * 2 - cyc;
                } else {
                    this.playTime = Math.min(elapsed, dur);
                    if (elapsed >= dur) this.stop();
                }
            }, 33);
        },

        stop() {
            this.playing = false;
            if (this._playInterval) {
                clearInterval(this._playInterval);
                this._playInterval = null;
            }
        },

        reset() {
            this.stop();
            this.playTime = 0;
        },

        formatTime(t) {
            const m = Math.floor(t / 60);
            const s = (t % 60).toFixed(1);
            return m > 0 ? m + ":" + s.padStart(4, "0") : s + "s";
        },

        // ── Clip palette (filtered by track type) ──
        clipsForTrack(trackIdx) {
            const otype = this.look?.outputs[trackIdx]?.type;
            if (!otype || otype === "none") return [];
            return this.clips.filter(c => c.output_type === otype);
        },

        // ── Save ──
        openSave() {
            this.saveName = this.look?.name || "";
            this.saveDesc = this.look?.description || "";
            this.saveModal = true;
        },

        async doSave() {
            if (!this.saveName.trim()) return;
            this.look.name = this.saveName.trim();
            this.look.description = this.saveDesc.trim();
            const saved = await api("POST", "/api/looks/save", this.look);
            this.look.id = saved.id;
            this.saveModal = false;
        },

        // ── Load existing ──
        async loadLook(id) {
            const look = await api("GET", "/api/looks/" + id);
            if (look) {
                this.look = look;
                this.playTime = 0;
                this.stop();
            }
        },
    }));
});
