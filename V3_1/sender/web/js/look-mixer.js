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
        _dropIndicator: null,  // { trackIdx, time } while dragging clip over timeline

        // ── Designer state ──
        clipSaveModal: false,
        clipSaveOi: -1,
        clipSaveName: "",
        clipSaveDuration: 5.0,
        loadedClips: {},   // oi -> {id, name} of clip loaded in that output

        // ── Mixer preview rendering ──
        _mixerPreviewInterval: null,
        _mixerPreviewPending: false,
        _lastMixerFrameTime: null,
        _mixerFrameDirty: true,
        _mixerUpdateSeq: 0,

        // ── Library state ──
        libSearch: "",
        libFilterType: "",
        libSortBy: "modified",
        libLoading: false,

        get outputTypes() {
            return Alpine.store("app").state?.look_output_types || [];
        },

        get playbackInfo() {
            return Alpine.store("app").playback;
        },

        mixerPanelStateClass() {
            if (this.subMode === 'designer') {
                return this.playbackInfo.source === 'designer'
                    ? 'panel-owner-live'
                    : 'panel-owner-idle';
            }
            if (this.previewing && this.playbackInfo.source === 'mixer') {
                return 'panel-owner-live';
            }
            if (this.previewing || this.playbackInfo.source === 'mixer') {
                return 'panel-owner-warn';
            }
            return 'panel-owner-idle';
        },

        mixerPanelTitle() {
            if (this.subMode === 'designer') {
                return this.playbackInfo.source === 'designer'
                    ? 'Designer owns output'
                    : 'Designer is editing only';
            }
            if (this.previewing && this.playbackInfo.source === 'mixer') {
                return 'Timeline preview owns output';
            }
            if (this.previewing) {
                return 'Timeline preview is armed';
            }
            return 'Timeline is editing only';
        },

        mixerPanelDetail() {
            if (this.subMode === 'designer') {
                if (this.playbackInfo.source === 'designer') {
                    return 'Designer edits are live on ' + this.playbackInfo.target_label.toLowerCase() + '.';
                }
                return 'Designer changes are local while output is owned by ' + this.playbackInfo.label.toLowerCase() + '.';
            }
            if (this.previewing && this.playbackInfo.source === 'mixer') {
                return 'Timeline preview is ' + this.playbackInfo.activity.toLowerCase() + ' on ' + this.playbackInfo.target_label.toLowerCase() + '.';
            }
            if (this.previewing) {
                return 'Preview is enabled, but output is currently owned by ' + this.playbackInfo.label.toLowerCase() + '.';
            }
            return 'Enable Preview to put the timeline live. Output is currently owned by ' + this.playbackInfo.label.toLowerCase() + '.';
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
            if (!Alpine.store("app").state) {
                await Alpine.store("app").fetchState();
            }
            this.newLook();
            this._startMixerPreviewLoop();
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
        async setSubMode(m) {
            if (m === 'designer' && this.previewing) {
                this.stop();
                await this.stopPreview();
            }
            this.subMode = m;
            if (m === 'timeline') {
                this._startMixerPreviewLoop();
            } else {
                this._stopMixerPreviewLoop();
            }
            await api("POST", "/api/set_playback_source", {
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

        openSaveClip(oi) {
            const loaded = this.loadedClips[oi];
            this.clipSaveOi = oi;
            this.clipSaveName = loaded?.name || "";
            this.clipSaveDuration = loaded?.duration || 5.0;
            this.clipSaveModal = true;
        },

        async doSaveClip() {
            if (!this.clipSaveName.trim()) return;
            const oi = this.clipSaveOi;
            const out = this.outputs[oi];
            if (!out || out.type === 'none') return;
            const loaded = this.loadedClips[oi];
            const clip = {
                id: loaded?.id || undefined,
                name: this.clipSaveName.trim(),
                group: this.clipSaveName.trim(),
                output_type: out.type,
                effect: out.effect,
                start_color: out.start_color,
                end_color: out.end_color,
                speed: out.speed,
                playback: out.playback,
                angle: out.angle || 0,
                highlight_width: out.highlight_width || 5,
                chase_origin: out.chase_origin || "start",
                duration: this.clipSaveDuration,
            };
            const saved = await api("POST", "/api/clips/save_single", clip);
            this.loadedClips[oi] = { id: saved.id, name: saved.name, duration: saved.duration };
            this.clipSaveModal = false;
            await this.loadClips();
        },

        clearLoadedClip(oi) {
            delete this.loadedClips[oi];
        },

        openSaveNewClip(oi) {
            this.clipSaveOi = oi;
            this.clipSaveName = "";
            this.clipSaveDuration = this.loadedClips[oi]?.duration || 5.0;
            delete this.loadedClips[oi];
            this.clipSaveModal = true;
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
            this.loadedClips[targetIdx] = {
                id: clip.id, name: clip.name, duration: clip.duration || 5.0,
            };
            await this.setSubMode("designer");
        },

        async deleteClip(clip) {
            if (!confirm("Delete clip \"" + clip.name + "\"?")) return;
            this.stopClipPreview();
            await fetch("/api/clips/" + clip.id, { method: "DELETE" });
            await this.loadClips();
        },

        // ══════════════════════════════════════════════════
        //  CLIP HOVER PREVIEW
        // ══════════════════════════════════════════════════

        _clipPreviewInterval: null,
        _clipPreviewT: 0,
        _clipPreviewId: null,
        _clipPreviewCanvas: null,

        startClipPreview(clip, el) {
            this.stopClipPreview();
            this._clipPreviewId = clip.id;
            this._clipPreviewT = 0;
            this._clipPreviewCanvas = el.querySelector('canvas');
            const dt = 0.066;
            const fetchFrame = async () => {
                if (this._clipPreviewId !== clip.id) return;
                try {
                    const res = await api("POST", "/api/clip/preview", {
                        clip_id: clip.id, t: this._clipPreviewT,
                    });
                    this._drawClipPreview(res);
                    this._clipPreviewT += dt;
                } catch (e) { /* ignore */ }
            };
            fetchFrame();
            this._clipPreviewInterval = setInterval(fetchFrame, 66);
        },

        stopClipPreview() {
            if (this._clipPreviewInterval) {
                clearInterval(this._clipPreviewInterval);
                this._clipPreviewInterval = null;
            }
            this._clipPreviewId = null;
            this._clipPreviewCanvas = null;
        },

        _drawClipPreview(data) {
            const canvas = this._clipPreviewCanvas;
            if (!canvas) return;
            const pixels = data.pixels || [];
            const grid = data.grid;
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
            } else if (pixels.length > 0) {
                canvas.width = pixels.length;
                canvas.height = 1;
                ctx.clearRect(0, 0, pixels.length, 1);
                for (let i = 0; i < pixels.length; i++) {
                    const p = pixels[i] || [0,0,0];
                    ctx.fillStyle = `rgb(${p[0]},${p[1]},${p[2]})`;
                    ctx.fillRect(i, 0, 1, 1);
                }
            }
        },

        // ══════════════════════════════════════════════════
        //  MIXER PREVIEW RENDERING
        // ══════════════════════════════════════════════════

        _startMixerPreviewLoop() {
            if (this._mixerPreviewInterval) return;
            this._mixerPreviewInterval = setInterval(() => this._fetchMixerFrame(), 66);
            this._fetchMixerFrame();
        },

        _stopMixerPreviewLoop() {
            if (this._mixerPreviewInterval) {
                clearInterval(this._mixerPreviewInterval);
                this._mixerPreviewInterval = null;
            }
        },

        async _fetchMixerFrame() {
            if (!this.look || this._mixerPreviewPending) return;
            if (this.subMode !== 'timeline') return;
            if (Alpine.store('app').mode !== 'mixer') return;
            // Skip refetch if playTime hasn't changed and look hasn't been modified
            if (this.playTime === this._lastMixerFrameTime && !this._mixerFrameDirty) return;
            this._mixerPreviewPending = true;
            try {
                const res = await api("POST", "/api/mixer/frame", {
                    look: this.look,
                    t: this.playTime,
                });
                this._lastMixerFrameTime = this.playTime;
                this._mixerFrameDirty = false;
                this._drawMixerPreviews(res.outputs || []);
            } catch (e) { /* ignore */ }
            this._mixerPreviewPending = false;
        },

        _drawMixerPreviews(outputs) {
            for (let oi = 0; oi < outputs.length; oi++) {
                const out = outputs[oi];
                const pixels = out.pixels || [];
                const grid = out.grid;
                const canvas = document.getElementById("mixer_preview_" + oi);
                if (!canvas) continue;
                const ctx = canvas.getContext("2d");
                if (grid) {
                    const [cols, rows] = grid;
                    canvas.width = cols;
                    canvas.height = rows;
                    const img = ctx.createImageData(cols, rows);
                    const d = img.data;
                    for (let i = 0; i < pixels.length; i++) {
                        const p = pixels[i] || [0,0,0];
                        const off = i * 4;
                        d[off] = p[0]; d[off+1] = p[1]; d[off+2] = p[2]; d[off+3] = 255;
                    }
                    ctx.putImageData(img, 0, 0);
                } else if (pixels.length > 0) {
                    canvas.width = pixels.length;
                    canvas.height = 1;
                    const img = ctx.createImageData(pixels.length, 1);
                    const d = img.data;
                    for (let i = 0; i < pixels.length; i++) {
                        const p = pixels[i] || [0,0,0];
                        const off = i * 4;
                        d[off] = p[0]; d[off+1] = p[1]; d[off+2] = p[2]; d[off+3] = 255;
                    }
                    ctx.putImageData(img, 0, 0);
                }
            }
        },

        // ══════════════════════════════════════════════════
        //  TIMELINE METHODS
        // ══════════════════════════════════════════════════

        newLook() {
            const backendOutputs = Alpine.store("app").state?.look?.outputs || [];
            if (this.previewing) {
                api("POST", "/api/mixer/stop_preview");
                this.previewing = false;
            }
            if (this.playing) {
                this.playing = false;
                if (this._playInterval) {
                    clearInterval(this._playInterval);
                    this._playInterval = null;
                }
            }
            this.look = {
                id: "",
                name: "New Look",
                description: "",
                outputs: [
                    { port: "A0", type: backendOutputs[0]?.type || "short_strip" },
                    { port: "A1", type: backendOutputs[1]?.type || "long_strip" },
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
            this._mixerFrameDirty = true;
        },

        setTrackOutputType(trackIdx, type) {
            if (this.look.outputs[trackIdx]) {
                this.look.outputs[trackIdx].type = type;
            }
            this._mixerFrameDirty = true;
            api("POST", "/api/update", { output: trackIdx, output_type: type });
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
            this._mixerFrameDirty = true;
            if (this.previewing) this._sendPreview();
        },

        removeSegment(trackIdx, segIdx) {
            this.look.tracks[trackIdx]?.segments.splice(segIdx, 1);
            this._mixerFrameDirty = true;
            if (this.previewing) this._sendPreview();
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
            this._mixerFrameDirty = true;
            this.editModal = false;
            if (this.previewing) this._sendPreview();
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
            this._mixerFrameDirty = true;
            this.editModal = false;
            if (this.previewing) this._sendPreview();
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
                if (this.previewing) this._sendPreview();
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
                this._mixerFrameDirty = true;
            } else if (this._drag.mode === 'resize-end') {
                let endTime = seg.start_time + this._drag.origDuration + dtSec;
                endTime = this._snap(endTime, snaps);
                const newDur = endTime - seg.start_time;
                seg.duration = Math.max(0.5, Math.min(newDur, dur - seg.start_time));
                this._mixerFrameDirty = true;
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
            const threshold = Math.max(0.05, Math.min(0.5, 5 / this.pixelsPerSecond));
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
            } else {
                this._updateMixerTime(this.playTime, false);
            }
        },

        _playheadDrag: null,

        startPlayheadDrag(event) {
            event.preventDefault();
            const container = event.currentTarget.closest('.timeline-container');
            if (!container) return;
            const wasPlaying = this.playing;
            if (wasPlaying) {
                this.playing = false;
                if (this._playInterval) {
                    clearInterval(this._playInterval);
                    this._playInterval = null;
                }
            }
            this._playheadDrag = { container, wasPlaying };
            const onMove = (e) => {
                const rect = this._playheadDrag.container.getBoundingClientRect();
                const x = e.clientX - rect.left + this._playheadDrag.container.scrollLeft;
                const dur = this.look?.total_duration || 10;
                this.playTime = Math.max(0, Math.min(x / this.pixelsPerSecond, dur));
                this._updateMixerTime(this.playTime, false);
            };
            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                if (this._playheadDrag?.wasPlaying) this.play();
                this._playheadDrag = null;
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        },

        async togglePreview() {
            if (this.previewing) {
                this.stop();
                await api("POST", "/api/mixer/stop_preview");
                this.previewing = false;
            } else {
                if (!this.look) return;
                this.previewing = true;
                this._sendPreview();
            }
        },

        async stopPreview() {
            if (!this.previewing) return;
            this.stop();
            await api("POST", "/api/mixer/stop_preview");
            this.previewing = false;
        },

        _sendPreview() {
            if (!this.previewing || !this.look) return;
            // Reset sequence counter — start_mixer_preview on the server resets
            // its own counter, so subsequent update calls start fresh.
            this._mixerUpdateSeq = 0;
            const payload = { ...this.look };
            payload.play_time = this.playTime;
            payload.playing = this.playing;
            const filter = Alpine.store("app").mixerPreviewDevices;
            if (filter) payload.device_filter = filter;
            api("POST", "/api/mixer/preview", payload);
        },

        _updateMixerTime(playTime, playing) {
            if (!this.previewing) return;
            const seq = ++this._mixerUpdateSeq;
            const body = {};
            if (playTime !== undefined) body.play_time = playTime;
            if (playing !== undefined) body.playing = playing;
            body.seq = seq;
            api("POST", "/api/mixer/update", body);
        },

        segmentStyle(seg) {
            const left = seg.start_time * this.pixelsPerSecond;
            const width = Math.max(seg.duration * this.pixelsPerSecond, 20);
            const sc = seg.start_color ?? [80, 80, 200];
            const ec = seg.end_color ?? [200, 80, 80];
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
            this._updateMixerTime(this.playTime, true);
        },

        stop() {
            if (!this.playing) return;
            this.playing = false;
            if (this._playInterval) {
                clearInterval(this._playInterval);
                this._playInterval = null;
            }
            this._updateMixerTime(this.playTime, false);
        },

        reset() {
            const wasPlaying = this.playing;
            if (wasPlaying) {
                this.playing = false;
                if (this._playInterval) {
                    clearInterval(this._playInterval);
                    this._playInterval = null;
                }
            }
            this.playTime = 0;
            this._updateMixerTime(0, false);
        },

        formatTime(t) {
            const m = Math.floor(t / 60);
            const s = (t % 60).toFixed(1);
            return m > 0 ? m + ":" + s.padStart(4, "0") : s + "s";
        },

        // ══════════════════════════════════════════════════
        //  CLIP-TO-TIMELINE DRAG & DROP
        // ══════════════════════════════════════════════════

        onClipDragStart(event, clip, trackIdx) {
            event.dataTransfer.effectAllowed = 'copy';
            event.dataTransfer.setData('application/json', JSON.stringify({
                clip_id: clip.id,
                clip_name: clip.name,
                start_color: clip.start_color,
                end_color: clip.end_color,
                duration: clip.duration || 5.0,
                output_type: clip.output_type,
                trackIdx,
            }));
        },

        onTrackDragOver(event, trackIdx) {
            // Accept drops only if dragging a clip
            const types = event.dataTransfer.types;
            if (!types.includes('application/json')) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = 'copy';

            // Calculate time position for drop indicator
            const container = event.currentTarget.closest('.timeline-container');
            if (!container) return;
            const rect = container.getBoundingClientRect();
            const x = event.clientX - rect.left + container.scrollLeft;
            const t = Math.max(0, x / this.pixelsPerSecond);
            this._dropIndicator = { trackIdx, time: t };
        },

        onTrackDragLeave(event, trackIdx) {
            // Only clear if actually leaving the track (not entering a child)
            if (!event.currentTarget.contains(event.relatedTarget)) {
                if (this._dropIndicator?.trackIdx === trackIdx) {
                    this._dropIndicator = null;
                }
            }
        },

        onTrackDrop(event, trackIdx) {
            event.preventDefault();
            this._dropIndicator = null;
            let data;
            try {
                data = JSON.parse(event.dataTransfer.getData('application/json'));
            } catch { return; }
            if (!data?.clip_id) return;

            // Reject if clip output type doesn't match the track
            const trackType = this.look?.outputs[trackIdx]?.type;
            if (trackType && data.output_type && data.output_type !== trackType) {
                const track = event.currentTarget;
                track.classList.add('drag-type-mismatch');
                setTimeout(() => track.classList.remove('drag-type-mismatch'), 600);
                return;
            }

            // Calculate drop time from mouse position
            const container = event.currentTarget.closest('.timeline-container');
            if (!container) return;
            const rect = container.getBoundingClientRect();
            const x = event.clientX - rect.left + container.scrollLeft;
            const dur = this.look?.total_duration || 10;
            let dropTime = Math.max(0, x / this.pixelsPerSecond);

            // Snap to existing segment edges
            const snaps = this._getSnapPoints(trackIdx, -1);
            dropTime = this._snap(dropTime, snaps);

            const segDuration = data.duration || 5.0;
            // Clamp so segment doesn't exceed total_duration
            dropTime = Math.min(dropTime, dur - Math.min(segDuration, dur));

            const track = this.look?.tracks[trackIdx];
            if (!track) return;

            track.segments.push({
                id: crypto.randomUUID(),
                clip_id: data.clip_id,
                clip_name: data.clip_name,
                start_color: data.start_color,
                end_color: data.end_color,
                start_time: Math.max(0, dropTime),
                duration: segDuration,
                fade_in: 0.5,
                fade_out: 0.5,
                speed_override: null,
            });

            // Extend total duration if segment overflows
            const newEnd = dropTime + segDuration;
            if (newEnd > this.look.total_duration) {
                this.look.total_duration = Math.ceil(newEnd);
            }
            this._mixerFrameDirty = true;
            if (this.previewing) this._sendPreview();
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
            try {
                const saved = await api("POST", "/api/looks/save", this.look);
                if (saved?.id) {
                    this.look.id = saved.id;
                    this.saveModal = false;
                }
            } catch (e) {
                console.error("Save failed:", e);
            }
        },

        async openLoad() {
            this.savedLooks = await api("GET", "/api/looks");
            this.loadModal = true;
        },

        async loadLook(id) {
            const look = await api("GET", "/api/looks/" + id);
            if (look) {
                if (this.previewing) {
                    api("POST", "/api/mixer/stop_preview");
                    this.previewing = false;
                }
                if (this.playing) {
                    this.playing = false;
                    if (this._playInterval) {
                        clearInterval(this._playInterval);
                        this._playInterval = null;
                    }
                }
                this.look = look;
                this.playTime = 0;
                this._mixerFrameDirty = true;
            }
        },
    }));
});
