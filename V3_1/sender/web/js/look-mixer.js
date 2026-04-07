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
        loadModal: false,
        savedLooks: [],
        pixelsPerSecond: 80,
        editModal: false,
        editTrack: -1,
        editSeg: -1,
        editData: null,
        // Drag state
        _drag: null,
        previewing: false,

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
                id: crypto.randomUUID(),
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

        openEditSegment(trackIdx, segIdx) {
            const seg = this.look.tracks[trackIdx]?.segments[segIdx];
            if (!seg) return;
            this.editTrack = trackIdx;
            this.editSeg = segIdx;
            this.editData = {
                start_time: seg.start_time,
                duration: seg.duration,
                fade_in: seg.fade_in,
                fade_out: seg.fade_out,
            };
            this.editModal = true;
        },

        applyEditSegment() {
            const seg = this.look.tracks[this.editTrack]?.segments[this.editSeg];
            if (!seg || !this.editData) return;
            seg.start_time = Math.max(0, this.editData.start_time);
            seg.duration = Math.max(0.1, this.editData.duration);
            seg.fade_in = Math.max(0, Math.min(this.editData.fade_in, seg.duration / 2));
            seg.fade_out = Math.max(0, Math.min(this.editData.fade_out, seg.duration / 2));
            this.editModal = false;
        },

        // ── Drag to move/resize segments ──
        startDrag(event, trackIdx, segIdx, mode) {
            // mode: 'move' or 'resize-end'
            event.preventDefault();
            const seg = this.look.tracks[trackIdx]?.segments[segIdx];
            if (!seg) return;
            this._drag = {
                trackIdx, segIdx, mode,
                startX: event.clientX,
                origStart: seg.start_time,
                origDuration: seg.duration,
            };
            const onMove = (e) => this._onDragMove(e);
            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                this._drag = null;
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        },

        _onDragMove(event) {
            if (!this._drag) return;
            const dx = event.clientX - this._drag.startX;
            const dtSec = dx / this.pixelsPerSecond;
            const seg = this.look.tracks[this._drag.trackIdx]?.segments[this._drag.segIdx];
            if (!seg) return;
            if (this._drag.mode === 'move') {
                seg.start_time = Math.max(0, this._drag.origStart + dtSec);
            } else if (this._drag.mode === 'resize-end') {
                seg.duration = Math.max(0.5, this._drag.origDuration + dtSec);
            }
        },

        // ── Preview on devices ──
        async previewOnDevices() {
            if (!this.look) return;
            await api("POST", "/api/mixer/preview", this.look);
            this.previewing = true;
            this.play();
        },

        async stopPreview() {
            await api("POST", "/api/mixer/stop_preview");
            this.previewing = false;
            this.stop();
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

        async openLoad() {
            this.savedLooks = await api("GET", "/api/looks");
            this.loadModal = true;
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
