"use strict";

(() => {
  const trace = window.CAIRNKIT_DEMO;
  const $ = (id) => document.getElementById(id);
  if (!trace?.events?.length) {
    $("step-title").textContent = "Generate the demo trace first.";
    $("step-caption").textContent = "Run examples/approval.py --decision approve --export examples/approval-demo/trace.js";
    $("play").disabled = true;
    $("next").disabled = true;
    return;
  }
  const copy = {
    request: ["Request", "A change starts with a source.", "The host selects the ticket and supplies Sam’s identity and role."],
    read: ["Read", "The agent reads within its scope.", "read_ticket returns the selected request. The saved record stays unchanged."],
    draft: ["Propose", "A proposal is not a saved change.", "propose_invoice_email creates a pending draft, linked to its source and proposer."],
    review: ["Review", "The human decision belongs to the host.", "Alex reviews the before and after. This agent has no approval or save tool."],
    saved: ["Save", "Approved by a person. Saved by the app.", "The host checks the reviewer and record version, then applies the exact proposed change."],
    rejected: ["Reject", "Rejected means the record stays unchanged.", "The host closes the draft without applying the proposed change."],
  };
  let index = 0;
  let timer = null;
  $("ticket-id").textContent = trace.ticket_id;
  $("source-text").textContent = `“${trace.source_text}”`;
  $("decision-source").textContent = trace.decision_source;

  const buttons = trace.events.map((event, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${String(i + 1).padStart(2, "0")} ${copy[event.stage][0]}`;
    button.addEventListener("click", () => { pause(); render(i); });
    $("steps").append(button);
    return button;
  });

  function render(i) {
    index = i;
    const event = trace.events[i];
    const draft = event.draft;
    const changed = event.stage === "saved";
    $("step-count").textContent = `${String(i + 1).padStart(2, "0")} / ${String(trace.events.length).padStart(2, "0")}`;
    $("step-title").textContent = copy[event.stage][1];
    $("step-caption").textContent = copy[event.stage][2];
    $("draft-placeholder").hidden = Boolean(draft);
    $("draft-detail").hidden = !draft;
    $("draft-status").textContent = draft ? ({pending: "Pending review", approved: "Approved by Alex", rejected: "Rejected by Alex"})[draft.status] : "Not created";
    $("draft-status").className = `badge ${draft?.status || ""}`;
    if (draft) {
      $("before").textContent = draft.before;
      $("after").textContent = draft.after;
      $("draft-source").textContent = `${draft.id} · from ${draft.source}`;
      $("reviewer").textContent = draft.reviewed_by ? `Reviewer: ${draft.reviewed_by}` : `Proposer: ${draft.proposed_by}`;
    }
    $("saved-email").textContent = event.record.invoice_email;
    $("version").textContent = `Record version ${event.record.version}`;
    $("record-state").textContent = changed ? "Updated after approval" : "Unchanged";
    $("record-state").className = `badge ${changed ? "approved" : ""}`;
    $("save-note").textContent = changed ? "Written by the host." : "No write has happened.";
    $("record-panel").className = `record panel ${changed ? "saved" : ""}`;
    $("proposal-panel").className = `proposal panel ${["draft", "review"].includes(event.stage) ? "active" : ""}`;
    buttons.forEach((button, n) => {
      if (n === i) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
    $("next").disabled = i === trace.events.length - 1;
  }

  function pause() {
    clearInterval(timer);
    timer = null;
    $("play").textContent = "Play 35-second replay";
    $("play").setAttribute("aria-pressed", "false");
  }
  $("play").addEventListener("click", () => {
    if (timer) { pause(); return; }
    render(0);
    $("play").textContent = "Pause replay";
    $("play").setAttribute("aria-pressed", "true");
    timer = setInterval(() => {
      if (index === trace.events.length - 1) pause();
      else render(index + 1);
    }, 7000);
  });
  $("next").addEventListener("click", () => { pause(); render(Math.min(index + 1, trace.events.length - 1)); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) pause(); });
  render(0);
})();
