const state = {
    config: {},
    cues: [],
    history: [],
    boards: [],
    activeBoard: null,
    editingIndex: null,
    activeCueNumber: null,
    boardMode: "save",
    oscExamples: [],
};

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
    });
    const payload = await response.json();
    if (!response.ok) {
        throw new Error(payload.error || `Request failed (${response.status})`);
    }
    return payload;
}

function setStatus(el, text, kind) {
    el.textContent = text;
    el.className = "osc-status-pill";
    if (kind === "ok") {
        el.classList.add("osc-status-listening");
    } else if (kind === "error") {
        el.classList.add("osc-status-error");
    } else {
        el.classList.add("osc-status-off");
    }
}

function formatArgs(args) {
    if (!args || !args.length) {
        return "";
    }
    return " " + args.map((value) => JSON.stringify(value)).join(" ");
}

function formatTargetAddress(host, port) {
    const trimmed = String(host || "127.0.0.1").trim() || "127.0.0.1";
    const resolvedPort = Number(port) || 53001;
    if (trimmed.includes(":") && !trimmed.startsWith("[")) {
        return `[${trimmed}]:${resolvedPort}`;
    }
    return `${trimmed}:${resolvedPort}`;
}

function parseTargetAddressClient(text, defaultPort = 53001) {
    const value = String(text || "").trim();
    if (!value) {
        return null;
    }
    const resolvedDefault = Number(defaultPort) || 53001;
    if (value.startsWith("[")) {
        const end = value.indexOf("]");
        if (end > 1) {
            const host = value.slice(1, end);
            const remainder = value.slice(end + 1);
            if (remainder.startsWith(":")) {
                const port = Number(remainder.slice(1));
                if (!Number.isInteger(port) || port < 1 || port > 65535) {
                    return null;
                }
                return { host, port };
            }
            return { host, port: resolvedDefault };
        }
    }
    const colonIndex = value.lastIndexOf(":");
    if (colonIndex > 0) {
        const host = value.slice(0, colonIndex).trim();
        const port = Number(value.slice(colonIndex + 1).trim());
        if (!host || !Number.isInteger(port) || port < 1 || port > 65535) {
            return null;
        }
        return { host, port };
    }
    return { host: value, port: resolvedDefault };
}

function readTargetForSend() {
    const address = document.getElementById("targetAddress").value.trim();
    if (address) {
        return { target_address: address };
    }
    return {
        target_host: document.getElementById("targetHost").value.trim(),
        target_port: Number(document.getElementById("targetPort").value),
    };
}

function readConfigFromForm() {
    const styleButton = document.querySelector("#styleToggle button.active");
    const address = document.getElementById("targetAddress").value.trim();
    const fallbackPort = Number(document.getElementById("targetPort").value) || 53001;
    const parsed = parseTargetAddressClient(address, fallbackPort);
    if (parsed) {
        return {
            target_host: parsed.host,
            target_port: parsed.port,
            message_style: styleButton ? styleButton.dataset.style : "primus",
            central_url: document.getElementById("centralUrl").value.trim(),
        };
    }
    return {
        target_host: document.getElementById("targetHost").value.trim(),
        target_port: Number(document.getElementById("targetPort").value),
        message_style: styleButton ? styleButton.dataset.style : "primus",
        central_url: document.getElementById("centralUrl").value.trim(),
    };
}

function renderTargetLabel() {
    const address = document.getElementById("targetAddress")?.value.trim();
    if (address) {
        document.getElementById("targetLabel").textContent = address;
    } else {
        const host = document.getElementById("targetHost").value.trim() || state.config.target_host || "127.0.0.1";
        const port = document.getElementById("targetPort").value || state.config.target_port || 53001;
        document.getElementById("targetLabel").textContent = `${host}:${port}`;
    }
    const style = (state.config.message_style || "primus").toLowerCase();
    document.getElementById("styleLabel").textContent =
        style === "qlab" ? "QLab-style addresses" : "Primus addresses";
    document.getElementById("boardLabel").textContent = state.activeBoard?.name
        ? `Board: ${state.activeBoard.name}`
        : "Unsaved board";
}

function syncTargetAddressFromParts() {
    const host = document.getElementById("targetHost").value.trim();
    const port = document.getElementById("targetPort").value;
    if (!host) {
        return;
    }
    document.getElementById("targetAddress").value = formatTargetAddress(host, port);
    renderTargetLabel();
}

function syncPartsFromTargetAddress() {
    const parsed = parseTargetAddressClient(
        document.getElementById("targetAddress").value.trim(),
        Number(document.getElementById("targetPort").value) || 53001
    );
    if (!parsed) {
        renderTargetLabel();
        return;
    }
    document.getElementById("targetHost").value = parsed.host;
    document.getElementById("targetPort").value = parsed.port;
    renderTargetLabel();
}

function renderConfigForm() {
    document.getElementById("targetHost").value = state.config.target_host || "127.0.0.1";
    document.getElementById("targetPort").value = state.config.target_port || 53001;
    document.getElementById("targetAddress").value = formatTargetAddress(
        state.config.target_host || "127.0.0.1",
        state.config.target_port || 53001
    );
    document.getElementById("centralUrl").value = state.config.central_url || "http://127.0.0.1:8080";
    const style = (state.config.message_style || "primus").toLowerCase();
    document.querySelectorAll("#styleToggle button").forEach((button) => {
        button.classList.toggle("active", button.dataset.style === style);
    });
    renderTargetLabel();
}

function renderCues() {
    const grid = document.getElementById("cueGrid");
    const empty = document.getElementById("cueEmpty");
    grid.innerHTML = "";
    document.getElementById("cueCount").textContent = `${state.cues.length} cue${state.cues.length === 1 ? "" : "s"}`;
    if (!state.cues.length) {
        empty.classList.remove("hidden");
        return;
    }
    empty.classList.add("hidden");

    state.cues.forEach((cue, index) => {
        const card = document.createElement("div");
        card.className = "cue-card";
        card.tabIndex = 0;
        card.dataset.number = String(cue.number);
        if (state.activeCueNumber === cue.number) {
            card.classList.add("cue-card-active");
        }

        const address = cue.address || "";
        const argsText = formatArgs(cue.args);

        card.innerHTML = `
            <div class="cue-card-topline">
                <span class="cue-card-number">${cue.number}</span>
                <button type="button" class="btn btn-sm cue-card-edit" data-index="${index}">Edit</button>
            </div>
            <div class="cue-card-main">
                <span class="cue-card-name">${escapeHtml(cue.name)}</span>
                <span class="cue-card-summary">${escapeHtml(address + argsText)}</span>
            </div>
        `;

        card.addEventListener("click", (event) => {
            if (event.target.closest(".cue-card-edit")) {
                return;
            }
            fireCue(cue.number);
        });
        card.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                fireCue(cue.number);
            }
        });
        card.querySelector(".cue-card-edit").addEventListener("click", (event) => {
            event.stopPropagation();
            openEditModal(index);
        });
        grid.appendChild(card);
    });
}

function renderHistory() {
    const list = document.getElementById("historyList");
    list.innerHTML = "";
    if (!state.history.length) {
        list.innerHTML = '<div class="cue-empty-state">No messages sent yet.</div>';
        return;
    }
    state.history.forEach((entry) => {
        const row = document.createElement("div");
        row.className = "history-row" + (entry.ok ? "" : " error");
        row.innerHTML = `
            <span class="history-time">${escapeHtml(entry.time || "")}</span>
            <span class="history-address">${escapeHtml(entry.address || "")}${escapeHtml(formatArgs(entry.args))}</span>
            <span class="history-target">${escapeHtml(entry.target || "")}</span>
        `;
        list.appendChild(row);
    });
}

function escapeHtml(value) {
    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

async function loadAll() {
    const [configPayload, cuesPayload, historyPayload, boardsPayload, examplesPayload] = await Promise.all([
        api("/api/config"),
        api("/api/cues"),
        api("/api/history"),
        api("/api/cue_boards"),
        api("/api/osc/examples"),
    ]);
    state.config = configPayload.config || {};
    state.cues = cuesPayload.cues || [];
    state.history = historyPayload.history || [];
    state.boards = boardsPayload.boards || [];
    state.activeBoard = boardsPayload.active_board || null;
    state.oscExamples = examplesPayload.examples || [];
    renderConfigForm();
    renderCues();
    renderHistory();
    renderDebugExamples();
}

async function saveConfig() {
    const saveStatus = document.getElementById("saveStatus");
    try {
        const payload = await api("/api/config", {
            method: "POST",
            body: JSON.stringify(readConfigFromForm()),
        });
        state.config = payload.config;
        renderConfigForm();
        const cuesPayload = await api("/api/cues");
        state.cues = cuesPayload.cues || [];
        renderCues();
        setStatus(saveStatus, "Saved", "ok");
    } catch (error) {
        setStatus(saveStatus, error.message, "error");
    }
}

async function syncCues() {
    const syncStatus = document.getElementById("syncStatus");
    setStatus(syncStatus, "Syncing", "off");
    try {
        await saveConfig();
        const payload = await api("/api/cues/sync", {
            method: "POST",
            body: JSON.stringify({
                central_url: document.getElementById("centralUrl").value.trim(),
            }),
        });
        state.cues = payload.cues || [];
        renderCues();
        setStatus(syncStatus, "Synced", "ok");
    } catch (error) {
        setStatus(syncStatus, error.message, "error");
    }
}

async function sendTransport(path, body = {}) {
    const payload = await api(path, {
        method: "POST",
        body: JSON.stringify({ ...readTargetForSend(), ...body }),
    });
    if (payload.entry) {
        state.history.unshift(payload.entry);
        state.history = state.history.slice(0, 20);
        renderHistory();
    }
    return payload;
}

function formatDebugArgs(args) {
    if (!args || !args.length) {
        return "";
    }
    return JSON.stringify(args);
}

function renderDebugExamples() {
    const container = document.getElementById("debugExamples");
    if (!container) {
        return;
    }
    container.innerHTML = "";
    if (!state.oscExamples.length) {
        return;
    }
    state.oscExamples.forEach((example) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "debug-example-btn";
        button.title = example.description || example.address;
        button.textContent = example.address + formatArgs(example.args);
        button.addEventListener("click", () => {
            document.getElementById("debugAddress").value = example.address || "";
            document.getElementById("debugArgs").value = formatDebugArgs(example.args);
        });
        container.appendChild(button);
    });
}

async function sendDebugMessage() {
    const debugStatus = document.getElementById("debugStatus");
    const address = document.getElementById("debugAddress").value.trim();
    const argsText = document.getElementById("debugArgs").value.trim();
    if (!address) {
        setStatus(debugStatus, "Address required", "error");
        return;
    }
    setStatus(debugStatus, "Sending", "off");
    try {
        const body = { address };
        if (argsText) {
            body.args = argsText;
        }
        const payload = await sendTransport("/api/send/raw", body);
        setStatus(debugStatus, payload.ok ? "Sent" : "Failed", payload.ok ? "ok" : "error");
    } catch (error) {
        setStatus(debugStatus, error.message, "error");
    }
}

async function fireCue(number) {
    state.activeCueNumber = number;
    renderCues();
    try {
        await sendTransport("/api/send/cue", { number });
    } finally {
        window.setTimeout(() => {
            state.activeCueNumber = null;
            renderCues();
        }, 350);
    }
}

function openEditModal(index) {
    state.editingIndex = index;
    const modal = document.getElementById("editModal");
    const deleteBtn = document.getElementById("deleteCueBtn");
    if (index === null) {
        document.getElementById("editModalTitle").textContent = "Add Cue";
        document.getElementById("editNumber").value = nextCueNumber();
        document.getElementById("editName").value = "";
        deleteBtn.classList.add("hidden");
    } else {
        const cue = state.cues[index];
        document.getElementById("editModalTitle").textContent = "Edit Cue";
        document.getElementById("editNumber").value = cue.number;
        document.getElementById("editName").value = cue.name;
        deleteBtn.classList.remove("hidden");
    }
    modal.classList.remove("hidden");
}

function closeEditModal() {
    state.editingIndex = null;
    document.getElementById("editModal").classList.add("hidden");
}

function nextCueNumber() {
    if (!state.cues.length) {
        return 1;
    }
    return Math.max(...state.cues.map((cue) => cue.number)) + 1;
}

async function saveCueFromModal() {
    const number = Number(document.getElementById("editNumber").value);
    const name = document.getElementById("editName").value.trim();
    if (!Number.isInteger(number) || number < 1 || !name) {
        return;
    }
    const cues = state.cues.map((cue) => ({ number: cue.number, name: cue.name }));
    if (state.editingIndex === null) {
        cues.push({ number, name });
    } else {
        cues[state.editingIndex] = { number, name };
    }
    cues.sort((a, b) => a.number - b.number);
    const payload = await api("/api/cues", {
        method: "POST",
        body: JSON.stringify({ cues }),
    });
    state.cues = payload.cues || [];
    const refreshed = await api("/api/cues");
    state.cues = refreshed.cues || [];
    renderCues();
    closeEditModal();
}

async function deleteCueFromModal() {
    if (state.editingIndex === null) {
        return;
    }
    const cues = state.cues
        .filter((_, index) => index !== state.editingIndex)
        .map((cue) => ({ number: cue.number, name: cue.name }));
    const payload = await api("/api/cues", {
        method: "POST",
        body: JSON.stringify({ cues }),
    });
    state.cues = payload.cues || [];
    const refreshed = await api("/api/cues");
    state.cues = refreshed.cues || [];
    renderCues();
    closeEditModal();
}

async function importCuesFile(file) {
    const text = await file.text();
    const data = JSON.parse(text);
    const payload = await api("/api/cues/import", {
        method: "POST",
        body: JSON.stringify(data),
    });
    const refreshed = await api("/api/cues");
    state.cues = refreshed.cues || payload.cues || [];
    renderCues();
}

function openBoardModal(mode) {
    state.boardMode = mode;
    const modal = document.getElementById("boardModal");
    const savePanel = document.getElementById("boardSavePanel");
    const loadPanel = document.getElementById("boardLoadPanel");
    document.getElementById("boardModalTitle").textContent =
        mode === "save" ? "Save Cue Board" : "Load Cue Board";
    savePanel.classList.toggle("hidden", mode !== "save");
    loadPanel.classList.toggle("hidden", mode !== "load");
    if (mode === "save") {
        document.getElementById("boardName").value = state.activeBoard?.name || "";
        document.getElementById("boardSaveHint").textContent =
            `Save ${state.cues.length} cue${state.cues.length === 1 ? "" : "s"} to a named board.`;
        document.getElementById("confirmBoardBtn").textContent =
            state.activeBoard ? "Update Board" : "Save Board";
    } else {
        renderBoardList();
    }
    modal.classList.remove("hidden");
}

function closeBoardModal() {
    document.getElementById("boardModal").classList.add("hidden");
}

function renderBoardList() {
    const list = document.getElementById("boardList");
    list.innerHTML = "";
    if (!state.boards.length) {
        list.innerHTML = '<div class="cue-empty-state">No saved cue boards yet.</div>';
        return;
    }
    state.boards.forEach((board) => {
        const row = document.createElement("div");
        row.className = "history-row";
        row.style.cursor = "pointer";
        row.innerHTML = `
            <span class="history-time">${escapeHtml(board.cue_count)} cues</span>
            <span class="history-address">${escapeHtml(board.name)}</span>
            <button type="button" class="btn btn-sm btn-danger board-delete-btn">Delete</button>
        `;
        row.addEventListener("click", (event) => {
            if (event.target.closest(".board-delete-btn")) {
                return;
            }
            loadBoard(board.id);
        });
        row.querySelector(".board-delete-btn").addEventListener("click", (event) => {
            event.stopPropagation();
            deleteBoard(board.id);
        });
        list.appendChild(row);
    });
}

async function refreshBoards() {
    const payload = await api("/api/cue_boards");
    state.boards = payload.boards || [];
    state.activeBoard = payload.active_board || null;
    renderTargetLabel();
    if (state.boardMode === "load") {
        renderBoardList();
    }
}

async function saveBoard() {
    const name = document.getElementById("boardName").value.trim();
    if (!name) {
        return;
    }
    const body = {
        name,
        cues: state.cues.map((cue) => ({ number: cue.number, name: cue.name })),
    };
    if (state.activeBoard?.id) {
        body.id = state.activeBoard.id;
    }
    const payload = await api("/api/cue_boards", {
        method: "POST",
        body: JSON.stringify(body),
    });
    state.activeBoard = payload.board;
    await refreshBoards();
    closeBoardModal();
}

async function loadBoard(boardId) {
    const payload = await api(`/api/cue_boards/${boardId}/load`, {
        method: "POST",
        body: JSON.stringify({}),
    });
    state.activeBoard = payload.board || null;
    const refreshed = await api("/api/cues");
    state.cues = refreshed.cues || [];
    renderCues();
    await refreshBoards();
    closeBoardModal();
}

async function deleteBoard(boardId) {
    if (!confirm("Delete this saved cue board?")) {
        return;
    }
    await api(`/api/cue_boards/${boardId}`, { method: "DELETE" });
    if (state.activeBoard?.id === boardId) {
        state.activeBoard = null;
    }
    await refreshBoards();
}

document.getElementById("saveConfigBtn").addEventListener("click", saveConfig);
document.getElementById("syncCuesBtn").addEventListener("click", syncCues);
document.getElementById("targetAddress").addEventListener("input", syncPartsFromTargetAddress);
document.getElementById("targetHost").addEventListener("input", syncTargetAddressFromParts);
document.getElementById("targetPort").addEventListener("input", syncTargetAddressFromParts);
document.getElementById("goBtn").addEventListener("click", () => sendTransport("/api/send/go"));
document.getElementById("stopBtn").addEventListener("click", () => sendTransport("/api/send/stop"));
document.getElementById("blackoutBtn").addEventListener("click", () =>
    sendTransport("/api/send/blackout", { fade_time: Number(document.getElementById("fadeTime").value || 0) })
);
document.getElementById("debugSendBtn").addEventListener("click", () => {
    sendDebugMessage().catch((error) => alert(error.message));
});
document.getElementById("debugAddress").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
        event.preventDefault();
        sendDebugMessage().catch((error) => alert(error.message));
    }
});
document.getElementById("addCueBtn").addEventListener("click", () => openEditModal(null));
document.getElementById("saveBoardBtn").addEventListener("click", () => openBoardModal("save"));
document.getElementById("loadBoardBtn").addEventListener("click", async () => {
    await refreshBoards();
    openBoardModal("load");
});
document.getElementById("cancelBoardBtn").addEventListener("click", closeBoardModal);
document.getElementById("cancelBoardLoadBtn").addEventListener("click", closeBoardModal);
document.getElementById("confirmBoardBtn").addEventListener("click", () => {
    saveBoard().catch((error) => alert(error.message));
});
document.getElementById("boardModal").addEventListener("click", (event) => {
    if (event.target.id === "boardModal") {
        closeBoardModal();
    }
});
document.getElementById("cancelEditBtn").addEventListener("click", closeEditModal);
document.getElementById("saveCueBtn").addEventListener("click", saveCueFromModal);
document.getElementById("deleteCueBtn").addEventListener("click", deleteCueFromModal);
document.getElementById("importFile").addEventListener("change", async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) {
        return;
    }
    try {
        await importCuesFile(file);
    } catch (error) {
        alert(error.message);
    }
});
document.querySelectorAll("#styleToggle button").forEach((button) => {
    button.addEventListener("click", () => {
        document.querySelectorAll("#styleToggle button").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
    });
});
document.getElementById("editModal").addEventListener("click", (event) => {
    if (event.target.id === "editModal") {
        closeEditModal();
    }
});

loadAll().catch((error) => {
    document.getElementById("saveStatus").textContent = error.message;
    document.getElementById("saveStatus").className = "osc-status-pill osc-status-error";
});
