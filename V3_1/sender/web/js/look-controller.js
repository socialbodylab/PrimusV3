/**
 * look-controller.js — Look Controller Alpine component.
 * Theatre-style cue list with GO / STOP controls.
 */

document.addEventListener("alpine:init", () => {

    Alpine.data("lookController", () => ({
        cues: [],
        currentIndex: -1,
        playing: false,
        looks: [],
        addModal: false,
        addLookId: "",

        async init() {
            await this.refresh();
            await this.loadLooks();
        },

        async refresh() {
            const data = await api("GET", "/api/cues");
            this.cues = data.cues || [];
            this.currentIndex = data.current_index ?? -1;
            this.playing = data.playing || false;
        },

        async loadLooks() {
            this.looks = await api("GET", "/api/looks");
        },

        lookName(lookId) {
            const l = this.looks.find(l => l.id === lookId);
            return l ? l.name : "(unknown)";
        },

        // ── Transport ──
        async go() {
            await api("POST", "/api/cues/go");
            this.refresh();
        },

        async stop() {
            await api("POST", "/api/cues/stop");
            this.refresh();
        },

        async goToCue(number) {
            await api("POST", "/api/cues/goto", { number });
            this.refresh();
        },

        // ── Cue management ──
        nextCueNumber() {
            if (this.cues.length === 0) return 1;
            return Math.max(...this.cues.map(c => c.number)) + 1;
        },

        openAddCue() {
            this.addLookId = this.looks.length ? this.looks[0].id : "";
            this.addModal = true;
        },

        async addCue() {
            if (!this.addLookId) return;
            const look = this.looks.find(l => l.id === this.addLookId);
            this.cues.push({
                number: this.nextCueNumber(),
                look_id: this.addLookId,
                name: look ? look.name : "Cue",
                description: "",
                auto_follow: false,
                follow_delay: 0,
            });
            await this.saveCues();
            this.addModal = false;
        },

        async removeCue(idx) {
            this.cues.splice(idx, 1);
            // Renumber
            this.cues.forEach((c, i) => c.number = i + 1);
            await this.saveCues();
        },

        async moveCue(idx, dir) {
            const newIdx = idx + dir;
            if (newIdx < 0 || newIdx >= this.cues.length) return;
            const temp = this.cues[idx];
            this.cues[idx] = this.cues[newIdx];
            this.cues[newIdx] = temp;
            this.cues.forEach((c, i) => c.number = i + 1);
            await this.saveCues();
        },

        async saveCues() {
            await api("POST", "/api/cues", { cues: this.cues });
        },

        isActive(idx) { return this.playing && idx === this.currentIndex; },
        isStandby(idx) {
            if (!this.playing) return idx === 0;
            return idx === this.currentIndex + 1;
        },
    }));
});
