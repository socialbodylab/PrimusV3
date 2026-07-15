/**
 * ui-lifecycle.js — Per-window keepalive for packaged Central server shutdown.
 *
 * Each app window registers its own session so PrimusCentral, Device Manager,
 * and other frontends can share one backend without closing each other.
 */
window.PrimusUiLifecycle = {
    sessionId() {
        const key = "primusUiSessionId";
        try {
            let id = sessionStorage.getItem(key);
            if (!id) {
                id = (crypto.randomUUID && crypto.randomUUID()) || ("session-" + Date.now());
                sessionStorage.setItem(key, id);
            }
            return id;
        } catch (e) {
            return "session-" + Date.now();
        }
    },

    install(api, runtime) {
        if (!runtime?.ui_lifecycle) return null;

        const sessionId = this.sessionId();
        const heartbeat = () => {
            api("POST", "/api/ui/heartbeat", { session_id: sessionId }).catch(() => {});
        };

        heartbeat();
        const timer = setInterval(heartbeat, 2000);

        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) heartbeat();
        });

        window.addEventListener("pagehide", () => {
            clearInterval(timer);
            const payload = JSON.stringify({ session_id: sessionId, reason: "pagehide" });
            if (navigator.sendBeacon) {
                navigator.sendBeacon("/api/ui/closed", new Blob([payload], { type: "application/json" }));
            } else {
                fetch("/api/ui/closed", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: payload,
                    keepalive: true,
                }).catch(() => {});
            }
        }, { once: true });

        return timer;
    },
};
