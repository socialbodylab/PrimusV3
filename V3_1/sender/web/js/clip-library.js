/**
 * clip-library.js — Clip Library Alpine component.
 * Grid view of saved clips with search, filter, and sort.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("clipLibrary", () => ({
        clips: [],
        search: "",
        filterType: "",
        sortBy: "modified",
        loading: false,

        get outputTypes() {
            return Alpine.store("app").state?.look_output_types || [];
        },

        async init() {
            await this.refresh();
        },

        async refresh() {
            this.loading = true;
            try {
                let url = "/api/clips?sort=" + this.sortBy;
                if (this.filterType) url += "&type=" + this.filterType;
                if (this.search) url += "&search=" + encodeURIComponent(this.search);
                this.clips = await api("GET", url);
            } finally {
                this.loading = false;
            }
        },

        setFilter(type) {
            this.filterType = this.filterType === type ? "" : type;
            this.refresh();
        },

        setSort(by) {
            this.sortBy = by;
            this.refresh();
        },

        doSearch() {
            this.refresh();
        },

        thumbStyle(clip) {
            const sc = clip.start_color || [128,0,128];
            const ec = clip.end_color || [0,128,128];
            return `background: linear-gradient(135deg, rgb(${sc}) 0%, rgb(${ec}) 100%)`;
        },

        async loadIntoDesigner(clip) {
            // Find first output slot matching clip type, load settings
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
            Alpine.store("app").setMode("designer");
        },

        async deleteClip(clip) {
            if (!confirm("Delete clip \"" + clip.name + "\"?")) return;
            await fetch("/api/clips/" + clip.id, { method: "DELETE" });
            this.refresh();
        },
    }));
});
