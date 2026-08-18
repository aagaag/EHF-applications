(() => {
  const accessQueue = document.querySelector("[data-access-queue]");
  const previewSection = document.querySelector("#viewpoints");
  const previewList = document.querySelector("[data-preview-list]");
  const changeQueue = document.querySelector("[data-change-queue]");
  const documentQueue = document.querySelector("[data-document-queue]");
  const detail = document.querySelector("[data-change-detail]");
  const status = document.querySelector("[data-review-status]");
  let canReturnForCorrection = false;
  const show = (message) => { if (status) status.textContent = message; };
  const legacyFields = new Set(["genderSelfDescription", "degreeCategory", "phdDate", "noGoogleScholarProfile", "googleScholarCitationTotal"]);
  const formatValue = (field, value) => {
    if (value === null || value === undefined || value === "") return "Missing";
    if (field === "degrees" && Array.isArray(value)) return value.length ? value.map((row) => `${row.degreeType || "Degree"} — ${row.conferralDate || "date not provided"}`).join("; ") : "None listed";
    if (field === "publications" && Array.isArray(value)) return value.length ? value.map((row) => row.doi).filter(Boolean).join("; ") : "None listed";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (Array.isArray(value) || typeof value === "object") return JSON.stringify(value);
    return String(value);
  };
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
  const loadPreviews = async () => {
    const response = await fetch("/api/internal/applicant-previews", { credentials: "same-origin" });
    if (response.status === 404) return;
    if (!response.ok) throw new Error("preview list unavailable");
    const items = (await response.json()).applications || [];
    previewSection.hidden = false;
    document.querySelectorAll("[data-preview-nav]").forEach((link) => { link.hidden = false; });
    if (!items.length) { empty(previewList, "No existing portal applications are available."); return; }
    previewList.replaceChildren(...items.map((item) => {
      const link = document.createElement("a");
      link.className = "shell-card";
      link.href = item.href;
      const name = document.createElement("strong"); name.textContent = item.applicantName;
      const state = document.createElement("span"); state.textContent = `Application status: ${item.applicationStatus}`;
      link.append(name, state);
      return link;
    }));
  };
  const load = async () => {
    const [access, changes, documents] = await Promise.all([
      fetch("/api/internal/applicant-access-requests", { credentials: "same-origin" }),
      fetch("/api/internal/applicant-submissions", { credentials: "same-origin" }),
      fetch("/api/internal/applicant-document-submissions", { credentials: "same-origin" }),
    ]);
    if (!access.ok || !changes.ok || !documents.ok) throw new Error("queue unavailable");
    const accessItems = (await access.json()).requests || [];
    const changePayload = await changes.json();
    const changeItems = changePayload.submissions || [];
    canReturnForCorrection = Boolean(changePayload.capabilities?.returnForCorrection);
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
        const lines = Object.entries(bundle.drafts || {}).flatMap(([section, values]) => Object.entries(values || {}).filter(([field]) => !legacyFields.has(field)).map(([field, proposed]) => `${section} — ${field}: ${formatValue(field, original[field])} → ${formatValue(field, proposed)}`));
        const actions = [button("Approve complete change set", "change-approve", value, "primary-action")];
        if (canReturnForCorrection) actions.push(button("Return one section for correction", "change-return", value, "secondary-action"));
        detail.replaceChildren(card("Proposed application record", lines, actions)); detail.scrollIntoView({ behavior: "smooth", block: "start" }); return;
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
      if (action === "change-approve") {
        response = await postEmpty(`/api/internal/applicant-submissions/${value}/approve`);
        if (response.status === 409) {
          const blocked = await response.json();
          show(blocked.message || "One section must be returned to the applicant before approval.");
          return;
        }
      }
      if (action === "change-return") {
        const section = (window.prompt("Section to return: identity, employment, qualifications, publications, or contribution", "employment") || "").trim().toLowerCase();
        if (!["identity", "employment", "qualifications", "publications", "contribution"].includes(section)) { show("Choose one of the listed application sections."); return; }
        const reason = (window.prompt("Explain what the applicant must correct") || "").trim();
        if (!reason) return;
        response = await fetch(`/api/internal/applicant-submissions/${value}/return-for-correction`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section, reason }) });
      }
      if (action === "document-accept") response = await postEmpty(`/api/internal/applicant-document-submissions/${value}/accept`);
      if (action === "document-reject") { const reason = window.prompt("Reason for rejection"); if (!reason) return; response = await fetch(`/api/internal/applicant-document-submissions/${value}/reject`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }); }
      if (!response?.ok) throw new Error(); show("Review decision recorded."); await load();
    } catch (_error) { show("The review decision could not be recorded. Please refresh and try again."); }
    finally { control.disabled = false; }
  });
  load().catch(() => show("The review queues could not be loaded."));
  loadPreviews().catch(() => show("The applicant viewpoint list could not be loaded."));
})();
