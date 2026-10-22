const $ = (id) => document.getElementById(id);
const esc = (value) =>
    String(value ?? "—").replace(
        /[&<>"']/g,
        (s) =>
            ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[s],
    );
const money = (value) =>
    value == null
        ? "—"
        : new Intl.NumberFormat("en-IN", {
              style: "currency",
              currency: "INR",
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
          }).format(Number(value));
const time = (value) =>
    value
        ? new Intl.DateTimeFormat("en-IN", {
              timeZone: "Asia/Kolkata",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
          }).format(new Date(value))
        : "—";
const readable = (value) => String(value || "waiting").replaceAll("_", " ");
let state = null,
    token = null,
    preview = false,
    connected = false,
    selectedStage = "strategy",
    selectedFilter = "all";
let toastTimer,
    historySymbol = "NSE:DEMO";
function toast(message) {
    $("toast").textContent = message;
    $("toast").classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $("toast").classList.remove("show"), 4500);
}
function openDialog(id) {
    $(id).showModal();
}
document
    .querySelectorAll(".close-dialog")
    .forEach((button) =>
        button.addEventListener("click", () =>
            button.closest("dialog").close(),
        ),
    );
document.querySelectorAll("dialog").forEach((dialog) =>
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
            const box = dialog.getBoundingClientRect();
            if (
                event.clientX < box.left ||
                event.clientX > box.right ||
                event.clientY < box.top ||
                event.clientY > box.bottom
            )
                dialog.close();
        }
    }),
);
$("history-symbol").addEventListener("change", () => {
    historySymbol = $("history-symbol").value;
    renderHistory();
});
$("history-details").addEventListener("click", () => {
    const history =
        (state?.histories || []).find(
            (item) => item.symbol === historySymbol,
        ) ||
        state?.history ||
        {};
    showDetails("Historical coverage", history);
});
$("help").addEventListener("click", () => openDialog("help-dialog"));
$("run-button").addEventListener("click", () => {
    if (preview || !connected) openDialog("help-dialog");
    else {
        $("run-error").textContent = "";
        openDialog("run-dialog");
    }
});
document.querySelectorAll("[data-nav]").forEach((link) =>
    link.addEventListener("click", () => {
        document
            .querySelectorAll("[data-nav]")
            .forEach((item) => item.classList.toggle("active", item === link));
    }),
);
for (const [id, flat] of [
    ["view-3d", false],
    ["view-flat", true],
])
    $(id).addEventListener("click", () => {
        $("flow-scene").classList.toggle("flat", flat);
        $("view-flat").classList.toggle("selected", flat);
        $("view-3d").classList.toggle("selected", !flat);
        $("view-flat").setAttribute("aria-pressed", String(flat));
        $("view-3d").setAttribute("aria-pressed", String(!flat));
    });
$("call-filters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter]");
    if (!button) return;
    selectedFilter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((item) => {
        item.classList.toggle("selected", item === button);
        item.setAttribute("aria-pressed", String(item === button));
    });
    renderCalls();
});
$("event-filter").addEventListener("change", renderActivity);
async function request(path, payload) {
    const response = await fetch(path, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Session-Token": token,
        },
        body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Request failed");
    state = result;
    render();
}
$("replay-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("start-replay").disabled = true;
    try {
        await request("/api/replay", { scenario: $("scenario").value });
        $("run-dialog").close();
        toast("Paper replay started. Follow each recorded stage.");
    } catch (error) {
        $("run-error").textContent = error.message;
    } finally {
        $("start-replay").disabled = false;
    }
});
$("pause-button").addEventListener("click", async () => {
    try {
        await request("/api/control", {
            action: state?.status === "paused" ? "resume" : "pause",
        });
    } catch (error) {
        toast(error.message);
    }
});
$("halt-button").addEventListener("click", async () => {
    try {
        await request("/api/control", { action: "halt" });
        toast(
            "Entry halt requested. Paper exits continue as replay observations arrive.",
        );
    } catch (error) {
        toast(error.message);
    }
});
function showDetails(title, event, call = false) {
    $("detail-title").textContent = title;
    const container = $("detail-content");
    container.replaceChildren();
    if (call) {
        const facts = document.createElement("dl");
        facts.className = "detail-facts";
        facts.innerHTML = [
            ["Instrument", event.symbol],
            ["Time (IST)", time(event.at)],
            ["Side", event.side?.toUpperCase()],
            ["Whole shares", event.qty],
            ["Assumed fill", money(event.fill_inr)],
            ["Configured stop", money(event.stop)],
            ["Configured target", money(event.target)],
            ["Status", event.status],
        ]
            .map(
                ([key, value]) =>
                    `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`,
            )
            .join("");
        container.append(facts);
        const trail = document.createElement("div");
        trail.className = "detail-timeline";
        const related = (state?.events || [])
            .filter(
                (item) =>
                    item.symbol === event.symbol &&
                    item.seq <= event.seq &&
                    [
                        "decision",
                        "risk_passed",
                        "entry_blocked",
                        "order",
                    ].includes(item.kind),
            )
            .slice(-4);
        trail.innerHTML = related
            .map(
                (item) =>
                    `<div><strong>${esc(readable(item.kind).toUpperCase())} · ${esc(time(item.at))} IST</strong><p>${esc(item.detail || item.reason)}</p></div>`,
            )
            .join("");
        container.append(trail);
    }
    const label = document.createElement("p");
    label.textContent = "Persisted event payload";
    container.append(label);
    const raw = document.createElement("pre");
    raw.textContent = JSON.stringify(event, null, 2);
    container.append(raw);
    openDialog("detail-dialog");
}
function renderStages() {
    const agents = state?.agents?.slice(0, 5) || [];
    const throughput = {
        data: state?.metrics?.quotes || 0,
        strategy: state?.metrics?.proposals || 0,
        risk: (state?.events || []).filter((e) => e.kind === "risk_passed")
            .length,
        execution: (state?.calls || []).filter((e) => e.status === "filled")
            .length,
        journal: state?.metrics?.fills || 0,
    };
    const captions = {
        data: "Validated candles",
        strategy: "Entry proposals",
        risk: "Gate passes",
        execution: "Virtual fills",
        journal: "Journal entries",
    };
    $("stages").innerHTML = agents.length
        ? agents
              .map(
                  (agent, index) =>
                      `<button class="stage ${agent.id === selectedStage ? "selected" : ""} ${agent.status === "blocked" ? "blocked" : ""}" data-stage="${esc(agent.id)}" aria-pressed="${agent.id === selectedStage}"><span class="stage-number">0${index + 1}</span><span><span class="stage-label">${esc(agent.name)}</span><span class="stage-caption">${captions[agent.id]}</span></span><span class="stage-count">${throughput[agent.id]}</span><span class="stage-arrow">↗</span></button>`,
              )
              .join("")
        : '<p class="empty">Your next session starts here.<br>Run a synthetic paper replay to follow the full funnel.</p>';
    $("stages")
        .querySelectorAll("[data-stage]")
        .forEach((button) =>
            button.addEventListener("click", () => {
                selectedStage = button.dataset.stage;
                renderStages();
                renderInspector();
            }),
        );
}
function renderInspector() {
    const agent = state?.agents?.find((item) => item.id === selectedStage);
    if (!agent) {
        $("inspector-content").innerHTML =
            '<p class="empty">No recorded activity yet.</p>';
        return;
    }
    const event = agent.latest || {};
    const fallback =
        selectedStage === "data"
            ? `Validated bid ${money(event.bid)} / ask ${money(event.ask)} from a timestamped synthetic candle.`
            : "No event recorded for this stage.";
    $("inspector-content").innerHTML =
        `<div class="inspector-stage">${esc(agent.name)}<span>${esc(agent.status.toUpperCase())}</span></div><div class="reason-box"><div class="reason-title">Recorded explanation</div>${esc(event.detail || event.reason || fallback)}</div><dl class="inspector-meta"><div><dt>Instrument</dt><dd>${esc(event.symbol || "NSE:DEMO")}</dd></div><div><dt>Observed at</dt><dd>${esc(time(event.at))} IST</dd></div><div><dt>Implementation</dt><dd>Python rules</dd></div><div><dt>Events recorded</dt><dd>${agent.count}</dd></div></dl><button class="inspect-link" id="inspect-event" ${event.kind ? "" : "disabled"}>Inspect recorded payload ↗</button>`;
    $("inspect-event").addEventListener("click", () =>
        showDetails(agent.name, event),
    );
}
function renderCalls() {
    let calls = state?.calls || [];
    if (selectedFilter === "blocked")
        calls = [
            ...calls.filter((e) => e.status === "rejected"),
            ...(state?.events || [])
                .filter((e) => e.kind === "entry_blocked")
                .map((e) => ({ ...e, status: "rejected", side: "blocked" })),
        ];
    else if (selectedFilter !== "all")
        calls = calls.filter((e) => e.side === selectedFilter);
    $("call-count").textContent = String(state?.calls?.length || 0);
    $("call-rows").innerHTML = calls.length
        ? [...calls]
              .reverse()
              .map(
                  (call, index) =>
                      `<tr><td><div class="instrument"><span class="instrument-icon">D</span><span><strong>${esc(call.symbol)}</strong><small>${esc(time(call.at))} IST · synthetic</small></span></div></td><td><span class="call-side ${esc(call.side)}">${esc(call.side?.toUpperCase())}</span></td><td>${esc(call.qty)}</td><td>${money(call.fill_inr)}</td><td class="reason-label">${esc(readable(call.reason))}</td><td><span class="result-badge ${esc(call.status)}">${esc(call.status === "filled" ? "PAPER FILLED" : call.status?.toUpperCase())}</span></td><td><button class="row-button" data-call="${index}" aria-label="Inspect ${esc(call.side)} call for ${esc(call.symbol)}">↗</button></td></tr>`,
              )
              .join("")
        : '<tr><td colspan="7" class="empty">No calls in this view. Waiting is a valid decision.</td></tr>';
    const reversed = [...calls].reverse();
    $("call-rows")
        .querySelectorAll("[data-call]")
        .forEach((button) =>
            button.addEventListener("click", () =>
                showDetails(
                    "Paper call detail",
                    reversed[Number(button.dataset.call)],
                    true,
                ),
            ),
        );
}
function renderActivity() {
    const filter = $("event-filter").value;
    const decisionKinds = [
        "decision",
        "order",
        "entry_blocked",
        "quote_rejected",
        "strategy_blocked",
        "halt",
        "run_started",
    ];
    const blockKinds = [
        "entry_blocked",
        "quote_rejected",
        "strategy_blocked",
        "halt",
        "reconcile_mismatch",
        "manual_attention",
    ];
    let events = (state?.events || []).filter(
        (event) =>
            filter === "all" ||
            (filter === "blocks"
                ? blockKinds.includes(event.kind) || event.status === "rejected"
                : decisionKinds.includes(event.kind)),
    );
    events = events.slice(-35).reverse();
    $("activity-list").innerHTML = events.length
        ? events
              .map(
                  (event, index) =>
                      `<div class="activity-row"><button class="activity-dot" data-event="${index}" aria-label="Inspect ${esc(readable(event.kind))} event">${event.kind === "order" ? "↗" : event.kind === "halt" ? "■" : "·"}</button><div class="activity-text"><strong>${esc(readable(event.kind))}${event.symbol ? " · " + esc(event.symbol) : ""}</strong><p>${esc(event.detail || event.reason || event.source || event.phase)}</p></div><time>${esc(time(event.at))}</time></div>`,
              )
              .join("")
        : '<p class="empty">No matching events recorded.</p>';
    $("activity-list")
        .querySelectorAll("[data-event]")
        .forEach((button) =>
            button.addEventListener("click", () =>
                showDetails(
                    "Engine event",
                    events[Number(button.dataset.event)],
                ),
            ),
        );
}
function renderRisk() {
    const limits = state?.limits || {};
    const rows = [
        ["Risk per trade", money(limits.risk)],
        ["Daily planned-loss limit", money(limits.daily_loss)],
        ["Position value cap", money(limits.position_limit)],
        ["Entry halt", state?.halt_reason ? "ACTIVE" : "Not active"],
        ["Exchange execution", "Not connected"],
    ];
    $("risk-content").innerHTML =
        rows
            .map(
                ([label, value]) =>
                    `<div class="risk-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`,
            )
            .join("") +
        '<div class="risk-connections"><span>NSE · synthetic replay</span><span>Binance · not connected</span><span>Other exchanges · not connected</span></div>';
    $("specialists").innerHTML = (
        state?.agents?.slice(5) || [
            { name: "News analyst" },
            { name: "Company analyst" },
            { name: "Independent reviewer" },
        ]
    )
        .map(
            (agent) =>
                `<div class="specialist"><span></span>${esc(agent.name)} · idle</div>`,
        )
        .join("");
}
function renderHistory() {
    const histories =
        state?.histories || (state?.history ? [state.history] : []);
    const history =
        histories.find((item) => item.symbol === historySymbol) ||
        histories[0] ||
        {};
    $("history-symbol").innerHTML = (
        histories.length ? histories : [{ symbol: "NSE:DEMO" }]
    )
        .map(
            (item) =>
                `<option value="${esc(item.symbol)}" ${item.symbol === history.symbol ? "selected" : ""}>${esc(item.symbol)}</option>`,
        )
        .join("");
    const minimum = history.minimum_sessions || 50,
        count = history.completed_sessions || 0;
    $("history-count").innerHTML =
        `${count} <span>/ ${minimum} sessions</span>`;
    $("history-fill").style.width =
        `${Math.min(100, (count / minimum) * 100)}%`;
    $("history-summary").textContent =
        `${history.synthetic_sessions || 0} synthetic session(s) stored separately · history retained until archived`;
    $("history-status").textContent = history.history_ready
        ? "COVERAGE MET"
        : "DATA BLOCK";
}
function renderWatchlist() {
    const watchlist = state?.watchlist || {},
        candidates = watchlist.candidates || [];
    $("watchlist-content").innerHTML = candidates.length
        ? '<div class="watchlist-grid">' +
          candidates
              .map(
                  (item) =>
                      `<article><span class="watchlist-rank">0${esc(item.rank)}</span><div><strong>${esc(item.symbol)}</strong><small>${esc(item.history_sessions)} complete sessions · ${esc(item.last_session)}</small><p>${esc(item.reason)}</p></div><span class="watchlist-wait">WAIT FOR SETUP</span></article>`,
              )
              .join("") +
          "</div>"
        : `<div class="watchlist-empty"><span>◎</span><div><strong>Market inputs needed</strong><p>${esc(watchlist.reason || "No instruments passed the current history and liquidity checks.")}</p><small>${watchlist.blocked?.length || 0} instruments blocked · no stock picks invented</small></div></div>`;
}
function render() {
    const metrics = state?.metrics || {};
    $("equity").textContent = money(metrics.equity_inr);
    $("initial").textContent = money(metrics.initial_cash_inr);
    $("pnl").textContent = money(metrics.realized_inr);
    $("pnl").className =
        Number(metrics.realized_inr) > 0
            ? "positive"
            : Number(metrics.realized_inr) < 0
              ? "negative"
              : "";
    $("proposals").textContent = metrics.proposals ?? "—";
    $("positions-count").textContent = metrics.open_positions ?? "—";
    $("proposal-detail").textContent =
        metrics.quotes == null
            ? "Awaiting observations"
            : `${metrics.quotes} candles validated · ${metrics.blocked} blocks`;
    $("fill-detail").textContent =
        metrics.fills == null
            ? "No exchange account connected"
            : `${metrics.fills} assumed fills · virtual INR`;
    $("source-title").textContent = preview
        ? "Synthetic session · archived preview"
        : connected
          ? "Local paper engine connected"
          : "Engine connection interrupted";
    $("source-detail").textContent = preview
        ? "Exported replay, not a live market feed. Connect locally to run."
        : connected
          ? "Backend events update every second · synthetic replay"
          : "Last recorded state shown. Controls disabled until reconnection.";
    $("connection").textContent = preview
        ? "ARCHIVED"
        : connected
          ? "CONNECTED"
          : "OFFLINE";
    $("run-state").textContent = readable(
        state?.status === "idle" ? "waiting for a run" : state?.status,
    );
    $("run-state").classList.toggle(
        "halted",
        Boolean(state?.halt_reason || state?.status === "error"),
    );
    $("clock").textContent = time(state?.clock) + " IST";
    $("run-id").textContent = state?.run_id
        ? `RUN / ${state.run_id.replace("run-", "").slice(0, 8).toUpperCase()}`
        : "No run selected";
    $("pause-button").textContent =
        state?.status === "paused" ? "▶ Resume" : "Ⅱ Pause";
    const active =
        connected && !preview && ["running", "paused"].includes(state?.status);
    $("pause-button").disabled = !active;
    $("halt-button").disabled = !active;
    $("run-button").disabled =
        connected && ["running", "paused", "halting"].includes(state?.status);
    $("run-button").innerHTML = preview
        ? "<span>↗</span> Connect your engine"
        : "<span>▶</span> Run paper replay";
    $("mascot-message").textContent = state?.halt_reason
        ? "Entries are halted. Check the recorded reason before your next run."
        : state?.status === "running"
          ? "A session is unfolding. Pick any stage to see its recorded decision."
          : metrics.blocked
            ? "A boundary held. Open the activity log to see what was blocked."
            : state?.run_id
              ? "The session is recorded. Explore each call and the reasons behind it."
              : "Ready when you are. Start a paper replay to bring the funnel to life.";
    renderStages();
    renderInspector();
    renderCalls();
    renderActivity();
    renderRisk();
    renderHistory();
    renderWatchlist();
}
async function initialize() {
    try {
        const response = await fetch("/api/session", { cache: "no-store" });
        if (!response.ok) throw new Error("No local backend");
        const session = await response.json();
        token = session.token;
        if (!token) throw new Error("No session token");
        const data = await fetch("/api/state", { cache: "no-store" });
        if (!data.ok) throw new Error("No engine state");
        state = await data.json();
        connected = true;
    } catch {
        try {
            const response = await fetch("preview.json");
            if (!response.ok) throw new Error("No preview");
            state = await response.json();
            preview = true;
        } catch {
            state = { status: "idle", events: [], agents: [], calls: [] };
        }
    }
    render();
    if (!preview)
        setInterval(async () => {
            try {
                const response = await fetch("/api/state", {
                    cache: "no-store",
                });
                if (!response.ok) throw new Error("Unavailable");
                state = await response.json();
                if (!token) {
                    const session = await fetch("/api/session");
                    token = (await session.json()).token;
                }
                connected = true;
            } catch {
                connected = false;
            }
            render();
        }, 1000);
}
initialize();
