/**
 * look-mixer.js — Look Mixer Alpine component.
 * Unified view: Designer sub-mode (clip editing) + Timeline sub-mode (look composition).
 * Incorporates clip designer controls, inline clip library, and timeline editor.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("lookMixer", () => ({
        // ── Sub-mode toggle ──
        subMode: "timeline",   // "designer" or "timeline"

        // ── Timeline state ──
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
        editOverlapBefore: 0,
        editOverlapAfter: 0,
        _drag: null,
        previewing: false,

        // ── Designer state ──
        clipSaveModal: false,
        clipSaveName: "",
        clipSaveDuration: 5.0,

        // ── Library state ──
        libSearch: "",
        libFilterType: "",
        libSortBy: "modified",
        libLoading: false,

        get outputTypes() {
            return Alpine.store("app").state?.look_output_types || [];
        },

        // ── Designer getters ──
        get state() { return Alpine.store("app").state; },
        get designerLook() { return this.state?.look; },
        get outputs() { return this.designerLook?.outputs || []; },
        get effects() {
            return ["none","solid","pulse","linear","constrainbow","rainbow",
                    "knight_rider","chase","radial","spiral"];
        },

        async init() {
            await this.loadClips();
            this.newLook();
            document.addEventListener('keydown', (e) => {
                if (Alpine.store('app').mode !== 'mixer') return;
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
                if (this.subMode === 'timeline') {
                    if (e.code === 'Space') {
                        e.preventDefault();
                        this.playing ? this.stop() : this.play();
                    } else if (e.code === 'Home') {
                        e.preventDefault();
                        this.reset();
                    } else if ((e.code === 'Delete' || e.code === 'Backspace') && this.editModal) {
                        this.removeSegment(this.editTrack, this.editSeg);
                        this.editModal = false;
                    }
                }
            });
        },

        // ── Sub-mode switching ──
        setSubMode(m) {
            if (m === 'designer' && this.previewing) {
                this.stopPreview();
            }
            this.subMode = m;
            api("POST", "/api/set_playback_source", {
                source: m === "designer" ? "designer" : "idle"
            });
        },

        // ── Clip loading (shared by timeline palette + designer library) ──
        async loadClips() {
            this.clips = await api("GET", "/api/clips");
        },

        // ══════════════════════════════════════════════════
        //  DESIGNER METHODS
        // ══════════════════════════════════════════════════

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

        startHex(oi) {
            const c = this.outputs[oi]?.start_color;
            return c ? rgbToHex(c) : "#ff00ff";
        },
        endHex(oi) {
            const c = this.outputs[oi]?.end_color;
            return c ? rgbToHex(c) : "#00ffff";
        },

        openSaveClip() {
            this.clipSaveName = "";
            this.clipSaveDuration = 5.0;
            this.clipSaveModal = true;
        },

        async doSaveClip() {
            if (!this.clipSaveName.trim()) return;
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
                duration: this.clipSaveDuration,
            }));
            await api("POST", "/api/clips/save", {
                name: this.clipSaveName.trim(),
                outputs: outs,
            });
            this.clipSaveModal = false;
            await this.loadClips();
        },

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

        // ══════════════════════════════════════════════════
        //  LIBRARY METHODS (inline in designer sub-mode)
        // ══════════════════════════════════════════════════

        async refreshLibrary() {
            this.libLoading = true;
            try {
                let url = "/api/clips?sort=" + this.libSortBy;
                if (this.libFilterType) url += "&type=" + this.libFilterType;
                if (this.libSearch) url += "&search=" + encodeURIComponent(this.libSearch);
                this.clips = await api("GET", url);
            } finally {
                this.libLoading = false;
            }
        },

        setLibFilter(type) {
            this.libFilterType = this.libFilterType === type ? "" : type;
            this.refreshLibrary();
        },

        setLibSort(by) {
            this.libSortBy = by;
            this.refreshLibrary();
        },

        doLibSearch() {
            this.refreshLibrary();
        },

        thumbStyle(clip) {
            const sc = clip.start_color || [128,0,128];
            const ec = clip.end_color || [0,128,128];
            return `background: linear-gradient(135deg, rgb(${sc}) 0%, rgb(${ec}) 100%)`;
        },

        async loadIntoDesigner(clip) {
            const state = Alpine.store("app").state;
            if (!state) return;
            const outputs = state.look?.outputs || [];
            let targetIdx = outputs.findIndex(o => o.type === clip.output_type);
            if (targetIdx < 0) targetIdx = 0;

            await api("POST", "/api/update", { output: targetIdx, output_type: clip.output_type });
            await api("POST", "/api/update", {
                output: targetIdx,
                effect: clip.effect,
                start_color: clip.start_color,
                end_color: clip.end_color,
                speed: clip.speed,
                playback: clip.playback,
                angle: clip.angle || 0,
                highlight_width: clip.highlight_width || 5,
                chase_origin: clip.chase_origin || "start",
            });
            this.subMode = "designer";
        },

        async deleteClip(clip) {
            if (!confirm("Delete clip \"" + clip.name + "\"?")) return;
            await fetch("/api/clips/" + clip.id, { method: "DELETE" });
            await this.loadClips();
        },

        // ══════════════════════════════════════════════════
        //  TIMELINE METHODS
        // ══════════════════════════════════════════════════

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
                speed: 1.0,
            };
            this.playTime = 0;
            this.stop();
        },

        setTrackOutputType(trackIdx, type) {
            if (this.look.outputs[trackIdx]) {
                this.look.outputs[trackIdx].type = type;
            }
        },

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
                speed_override: null,
            });
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
                speed_override: seg.speed_override,
            };
            const track = this.look.tracks[trackIdx];
            const sorted = track.segments.slice().sort((a, b) => a.start_time - b.start_time);
            const myIdx = sorted.findIndex(s => s.id === seg.id);
            this.editOverlapBefore = 0;
            this.editOverlapAfter = 0;
            if (myIdx > 0) {
                const prev = sorted[myIdx - 1];
                const prevEnd = prev.start_time + prev.duration;
                if (prevEnd > seg.start_time) {
                    this.editOverlapBefore = parseFloat((prevEnd - seg.start_time).toFixed(2));
                }
            }
            if (myIdx >= 0 && myIdx < sorted.length - 1) {
                const next = sorted[myIdx + 1];
                const myEnd = seg.start_time + seg.duration;
                if (myEnd > next.start_time) {
                    this.editOverlapAfter = parseFloat((myEnd - next.start_time).toFixed(2));
                }
            }
            this.editModal = true;
        },

        applyEditSegment() {
            const seg = this.look.tracks[this.editTrack]?.segments[this.editSeg];
            if (!seg || !this.editData) return;
            const dur = this.look?.total_duration || 10;
            seg.start_time = Math.max(0, Math.min(this.editData.start_time, dur - 0.1));
            seg.duration = Math.max(0.1, Math.min(this.editData.duration, dur - seg.start_time));
            seg.fade_in = Math.max(0, Math.min(this.editData.fade_in, seg.duration / 2));
            seg.fade_out = Math.max(0, Math.min(this.editData.fade_out, seg.duration / 2));
            seg.speed_override = this.editData.speed_override;
            this.editModal = false;
        },

        duplicateSegment() {
            const seg = this.look.tracks[this.editTrack]?.segments[this.editSeg];
            if (!seg) return;
            const dur = this.look?.total_duration || 10;
            const dup = {
                id: crypto.randomUUID(),
                clip_id: seg.clip_id,
                clip_name: seg.clip_name,
                start_color: seg.start_color ? [...seg.start_color] : null,
                end_color: seg.end_color ? [...seg.end_color] : null,
                start_time: seg.start_time + seg.duration,
                duration: seg.duration,
                fade_in: seg.fade_in,
                fade_out: seg.fade_out,
                speed_override: seg.speed_override,
            };
            if (dup.start_time + dup.duration > dur) {
                dup.duration = Math.max(0.1, dur - dup.start_time);
            }
            if (dup.start_time < dur) {
                this.look.tracks[this.editTrack].segments.push(dup);
            }
            this.editModal = false;
        },

        startDrag(event, trackIdx, segIdx, mode) {
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
            const dur = this.look?.total_duration || 10;
            const snaps = this._getSnapPoints(this._drag.trackIdx, this._drag.segIdx);
            if (this._drag.mode === 'move') {
                let newStart = this._drag.origStart + dtSec;
                const snappedStart = this._snap(newStart, snaps);
                const snappedEnd = this._snap(newStart + seg.duration, snaps);
                const dStart = Math.abs(snappedStart - newStart);
                const dEnd = Math.abs(snappedEnd - (newStart + seg.duration));
                newStart = dEnd < dStart ? snappedEnd - seg.duration : snappedStart;
                seg.start_time = Math.max(0, Math.min(newStart, dur - seg.duration));
            } else if (this._drag.mode === 'resize-end') {
                let endTime = seg.start_time + this._drag.origDuration + dtSec;
                endTime = this._snap(endTime, snaps);
                const newDur = endTime - seg.start_time;
                seg.duration = Math.max(0.5, Math.min(newDur, dur - seg.start_time));
            }
        },

        _getSnapPoints(trackIdx, excludeSegIdx) {
            const points = [];
            const dur = this.look?.total_duration || 10;
            for (let t = 0; t <= dur; t++) points.push(t);
            const track = this.look?.tracks[trackIdx];
            if (track) {
                track.segments.forEach((seg, si) => {
                    if (si === excludeSegIdx) return;
                    points.push(seg.start_time);
                    points.push(seg.start_time + seg.duration);
                });
            }
            return points;
        },

        _snap(value, points) {
            const threshold = 5 / this.pixelsPerSecond;
            let best = value;
            let bestDist = threshold;
            for (const p of points) {
                const d = Math.abs(value - p);
                if (d < bestDist) { bestDist = d; best = p; }
            }
            return best;
        },

        clickTimeline(event) {
            const container = event.currentTarget.closest('.timeline-container');
            if (!container) return;
            const rect = container.getBoundingClientRect();
            const x = event.clientX - rect.left + container.scrollLeft;
            const t = x / this.pixelsPerSecond;
            const dur = this.look?.total_duration || 10;
            this.playTime = Math.max(0, Math.min(t, dur));
            if (this.playing) {
                this.stop();
                this.play();
            }
        },

        async previewOnDevices() {
            if (!this.look) return;
            const payload = { ...this.look };
            const filter = Alpine.store("app").mixerPreviewDevices;
            if (filter) payload.device_filter = filter;
            await api("POST", "/api/mixer/preview", payload);
            this.previewing = true;
            this.play();
        },

        async stopPreview() {
            await api("POST", "/api/mixer/stop_preview");
            this.previewing = false;
            this.stop();
        },

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

        crossfadeZones(trackIdx) {
            const track = this.look?.tracks[trackIdx];
            if (!track) return [];
            const segs = track.segments.slice().sort((a, b) => a.start_time - b.start_time);
            const zones = [];
            for (let i = 0; i < segs.length - 1; i++) {
                const aEnd = segs[i].start_time + segs[i].duration;
                const bStart = segs[i + 1].start_time;
                if (aEnd > bStart) {
                    const overlapEnd = Math.min(aEnd, segs[i + 1].start_time + segs[i + 1].duration);
                    zones.push({
                        left: bStart * this.pixelsPerSecond,
                        width: (overlapEnd - bStart) * this.pixelsPerSecond,
                    });
                }
            }
            return zones;
        },

        rulerTicks() {
            const dur = this.look?.total_duration || 10;
            const pps = this.pixelsPerSecond;
            const ticks = [];
            const step = 0.25;
            for (let t = 0; t <= dur + 0.001; t += step) {
                const rounded = parseFloat(t.toFixed(2));
                const major = Math.abs(rounded - Math.round(rounded)) < 0.001;
                ticks.push({ t: rounded, left: rounded * pps, major });
            }
            return ticks;
        },

        playheadLeft() {
            return this.playTime * this.pixelsPerSecond;
        },

        transportStatus() {
            if (!this.look) return '';
            const t = this.playTime;
            for (const track of this.look.tracks) {
                for (const seg of track.segments) {
                    if (t >= seg.start_time && t < seg.start_time + seg.duration) {
                        return '';
                    }
                }
            }
            return 'BLACK';
        },

        play() {
            if (this.playing) return;
            this.playing = true;
            const start = performance.now() - this.playTime * 1000 / (this.look?.speed || 1);
            this._playInterval = setInterval(() => {
                const globalSpeed = this.look?.speed || 1;
                const elapsed = (performance.now() - start) / 1000 * globalSpeed;
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

        clipsForTrack(trackIdx) {
            const otype = this.look?.outputs[trackIdx]?.type;
            if (!otype || otype === "none") return [];
            return this.clips.filter(c => c.output_type === otype);
        },

        // ── Look Save/Load ──
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
