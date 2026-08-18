(() => {
  const accessQueue = document.querySelector("[data-access-queue]");
  const changeQueue = document.querySelector("[data-change-queue]");
  const documentQueue = document.querySelector("[data-document-queue]");
  const detail = document.querySelector("[data-change-detail]");
  const status = document.querySelector("[data-review-status]");
  const show = (message) => { if (status) status.textContent = message; };
  const button = (label, action, value, className = "secondary-action") => {
    const item = document.createElement("button"); item.type = "button"; item.className = className; item.textContent = label; item.dataset.action = action; item.dataset.value = value; return item;
  };
  const card = (title, lines, actions = []) => {
    const article = document.createElement("article"); article.className = "shell-card review-queue-card";
    const heading = document.createElement("strong"); heading.textContent = title; article.append(heading);
    lines.forEach((line) => { const text = document.createElement("span"); text.textContent = line; article.append(text); });
    const controls = document.createElement("div"); controls.className = "review-actions"; actions.forEach((action) => controls.append(action)); article.append(controls); return article;
  };
  const empty = (target, message) => { target.replaceChildren(Object.assign(document.createElement("p"), { textContent: message })); };
  const load = async () => {
    const [access, changes, documents] = await Promise.all([
      fetch("/api/internal/applicant-access-requests", { credentials: "same-origin" }),
      fetch("/api/internal/applicant-submissions", { credentials: "same-origin" }),
      fetch("/api/internal/applicant-document-submissions", { credentials: "same-origin" }),
    ]);
    if (!access.ok || !changes.ok || !documents.ok) throw new Error("queue unavailable");
    const accessItems = (await access.json()).requests || [];
    const changeItems = (await changes.json()).submissions || [];
    const documentItems = (await documents.json()).submissions || [];
    if (!accessItems.length) empty(accessQueue, "No access requests await action."); else accessQueue.replaceChildren(...accessItems.map((item) => card(item.displayName, [item.email, `Requested ${item.requestedAtUtc}`, `Status: ${item.status}`], item.status === "APPROVED" ? [button("Bind approved Entra identity", "access-provision", item.requestId, "primary-action")] : [button("Approve access", "access-approve", item.requestId, "primary-action"), button("Reject access", "access-reject", item.requestId, "secondary-action")])));
    if (!changeItems.length) empty(changeQueue, "No application changes await approval."); else changeQueue.replaceChildren(...changeItems.map((item) => card(`Application ${item.applicationId}`, [`Submitted ${item.submittedAtUtc}`], [button("Inspect changes", "change-open", item.confirmationId, "primary-action")])));
    if (!documentItems.length) empty(documentQueue, "No uploaded documents await review."); else documentQueue.replaceChildren(...documentItems.map((item) => card(item.displayName, [`Application ${item.applicationId}`, `Submitted ${item.submittedAtUtc}`], [button("Accept document", "document-accept", item.submissionId, "primary-action"), button("Reject document", "document-reject", item.submissionId, "secondary-action")])));
  };
  const postEmpty = (url) => fetch(url, { method: "POST", credentials: "same-origin" });
  document.addEventListener("click", async (event) => {
    const control = event.target.closest("[data-action]"); if (!control) return;
    control.disabled = true;
    try {
      const action = control.dataset.action; const value = control.dataset.value;
      if (action === "change-open") {
        const response = await fetch(`/api/internal/applicant-submissions/${value}`, { credentials: "same-origin" }); if (!response.ok) throw new Error();
        const bundle = await response.json();
        const original = bundle.baseline?.applicant || {};
        const lines = Object.entries(bundle.drafts || {}).flatMap(([section, values]) => Object.entries(values || {}).map(([field, proposed]) => `${section} — ${field}: ${String(original[field] ?? "Missing")} → ${String(proposed ?? "Missing")}`));
        detail.replaceChildren(card("Proposed application record", lines, [button("Approve complete change set", "change-approve", value, "primary-action")])); detail.scrollIntoView({ behavior: "smooth", block: "start" }); return;
      }
      let response;
      if (action === "access-approve" || action === "access-reject") response = await postEmpty(`/api/internal/applicant-access-requests/${value}/review/${action.endsWith("approve") ? "approve" : "reject"}`);
      if (action === "access-provision") {
        const applicationId = window.prompt("Application ID to bind");
        if (!applicationId) return;
        const entraObjectId = window.prompt("Entra object ID to bind");
        if (!entraObjectId) return;
        response = await fetch(`/api/internal/applicant-access-requests/${value}/provision`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ applicationId, entraObjectId }) });
      }
      if (action === "change-approve") response = await postEmpty(`/api/internal/applicant-submissions/${value}/approve`);
      if (action === "document-accept") response = await postEmpty(`/api/internal/applicant-document-submissions/${value}/accept`);
      if (action === "document-reject") { const reason = window.prompt("Reason for rejection"); if (!reason) return; response = await fetch(`/api/internal/applicant-document-submissions/${value}/reject`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }); }
      if (!response?.ok) throw new Error(); show("Review decision recorded."); await load();
    } catch (_error) { show("The review decision could not be recorded. Please refresh and try again."); }
    finally { control.disabled = false; }
  });
  load().catch(() => show("The review queues could not be loaded."));
})();
