(() => {
  const accessQueue = document.querySelector("[data-access-queue]");
  const previewSection = document.querySelector("#viewpoints");
  const previewList = document.querySelector("[data-preview-list]");
  const previewSearch = document.querySelector("[data-preview-search]");
  const previewStatus = document.querySelector("[data-preview-status]");
  const syntheticWorkspace = document.querySelector("[data-synthetic-workspace]");
  const changeQueue = document.querySelector("[data-change-queue]");
  const documentQueue = document.querySelector("[data-document-queue]");
  const detail = document.querySelector("[data-change-detail]");
  const status = document.querySelector("[data-review-status]");
  const reviewDialog = document.querySelector("[data-review-dialog]");
  const reviewDialogForm = document.querySelector("[data-review-dialog-form]");
  const reviewDialogTitle = document.querySelector("[data-review-dialog-title]");
  const reviewDialogFields = document.querySelector("[data-review-dialog-fields]");
  const reviewDialogSubmit = document.querySelector("[data-review-dialog-submit]");
  let canReturnForCorrection = false;
  let previewItems = [];
  let dialogAction = null;
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
  const actionLink = (label, href) => {
    const item = document.createElement("a"); item.className = "secondary-action"; item.textContent = label; item.href = href; item.target = "_blank"; item.rel = "noopener"; return item;
  };
  const card = (title, lines, actions = []) => {
    const article = document.createElement("article"); article.className = "shell-card review-queue-card";
    const heading = document.createElement("strong"); heading.textContent = title; article.append(heading);
    lines.forEach((line) => { const text = document.createElement("span"); text.textContent = line; article.append(text); });
    const controls = document.createElement("div"); controls.className = "review-actions"; actions.forEach((action) => controls.append(action)); article.append(controls); return article;
  };
  const empty = (target, message) => { target.replaceChildren(Object.assign(document.createElement("p"), { textContent: message })); };
  const listReturnUrl = () => {
    const params = new URLSearchParams();
    const query = previewSearch?.value.trim() || "";
    const applicationStatus = previewStatus?.value || "";
    if (query) params.set("q", query);
    if (applicationStatus) params.set("status", applicationStatus);
    return `/internal/applicants${params.size ? `?${params}` : ""}`;
  };
  const renderPreviews = () => {
    const query = previewSearch?.value.trim().toLocaleLowerCase() || "";
    const applicationStatus = previewStatus?.value || "";
    const filtered = previewItems.filter((item) => (
      (!query || item.applicantName.toLocaleLowerCase().includes(query))
      && (!applicationStatus || item.applicationStatus === applicationStatus)
    ));
    if (!filtered.length) {
      empty(previewList, previewItems.length ? "No applicants match these filters." : "No existing portal applications are available.");
      return;
    }
    const returnUrl = listReturnUrl();
    previewList.replaceChildren(...filtered.map((item) => {
      const link = document.createElement("a");
      link.className = "shell-card";
      link.href = returnUrl === "/internal/applicants" ? item.href : `${item.href}?return=${encodeURIComponent(returnUrl)}`;
      const name = document.createElement("strong"); name.textContent = item.applicantName;
      const state = document.createElement("span"); state.textContent = `Application status: ${item.applicationStatus}`;
      link.append(name, state);
      return link;
    }));
  };
  const updatePreviewFilters = () => {
    const returnUrl = listReturnUrl();
    try { window.history.replaceState({}, "", returnUrl); } catch (_error) { /* static browser fixture */ }
    renderPreviews();
  };
  const loadPreviews = async () => {
    const response = await fetch("/api/internal/applicant-previews", { credentials: "same-origin" });
    if (response.status === 404) return;
    if (!response.ok) throw new Error("preview list unavailable");
    const payload = await response.json();
    if (!Array.isArray(payload.applications)) return;
    previewItems = payload.applications;
    previewSection.hidden = false;
    if (syntheticWorkspace) syntheticWorkspace.hidden = false;
    document.querySelectorAll("[data-preview-nav]").forEach((link) => { link.hidden = false; });
    if (previewStatus) {
      [...new Set(previewItems.map((item) => item.applicationStatus))].sort().forEach((value) => {
        const option = document.createElement("option"); option.value = value; option.textContent = value; previewStatus.append(option);
      });
      previewStatus.value = new URLSearchParams(window.location.search).get("status") || "";
    }
    if (previewSearch) previewSearch.value = new URLSearchParams(window.location.search).get("q") || "";
    renderPreviews();
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
    if (!documentItems.length) empty(documentQueue, "No uploaded documents await review."); else documentQueue.replaceChildren(...documentItems.map((item) => card(item.displayName, [`Application ${item.applicationId}`, `Submitted ${item.submittedAtUtc}`], [actionLink("View submitted PDF", `/api/internal/applicants/${item.applicationId}/documents/${item.versionId}/view`), button("Accept document", "document-accept", item.submissionId, "primary-action"), button("Reject document", "document-reject", item.submissionId, "secondary-action")])));
  };
  const postEmpty = (url) => fetch(url, { method: "POST", credentials: "same-origin" });
  const field = (labelText, name, control) => {
    const label = document.createElement("label"); label.textContent = labelText; control.name = name; control.required = true; label.append(control); return label;
  };
  const textInput = () => { const control = document.createElement("input"); control.type = "text"; return control; };
  const openReviewDialog = (action, value) => {
    if (!reviewDialog || !reviewDialogFields || !reviewDialogTitle || !reviewDialogSubmit) return;
    dialogAction = { action, value };
    reviewDialogFields.replaceChildren();
    if (action === "access-provision") {
      reviewDialogTitle.textContent = "Bind approved Entra identity";
      reviewDialogSubmit.textContent = "Bind identity";
      reviewDialogFields.append(field("Application ID", "applicationId", textInput()), field("Entra object ID", "entraObjectId", textInput()));
    }
    if (action === "change-return") {
      reviewDialogTitle.textContent = "Return section for correction";
      reviewDialogSubmit.textContent = "Return for correction";
      const select = document.createElement("select");
      [["identity", "Identity and contact"], ["employment", "UZH employment and eligibility"], ["qualifications", "Qualifications and academic age"], ["publications", "Publications and identifiers"], ["contribution", "Scientific contribution"]].forEach(([value, label]) => { const option = document.createElement("option"); option.value = value; option.textContent = label; select.append(option); });
      select.value = "employment";
      const reason = document.createElement("textarea"); reason.rows = 5;
      reviewDialogFields.append(field("Application section", "section", select), field("Correction requested", "reason", reason));
    }
    if (action === "document-reject") {
      reviewDialogTitle.textContent = "Reject submitted document";
      reviewDialogSubmit.textContent = "Reject document";
      const reason = document.createElement("textarea"); reason.rows = 5;
      reviewDialogFields.append(field("Reason for rejection", "reason", reason));
    }
    reviewDialog.showModal();
    reviewDialogFields.querySelector("input, select, textarea")?.focus();
  };
  document.querySelectorAll("[data-review-dialog-cancel]").forEach((control) => control.addEventListener("click", () => { reviewDialog?.close(); dialogAction = null; }));
  if (reviewDialogForm) reviewDialogForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!dialogAction || !reviewDialogSubmit) return;
    reviewDialogSubmit.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(reviewDialogForm));
      let response;
      if (dialogAction.action === "access-provision") response = await fetch(`/api/internal/applicant-access-requests/${dialogAction.value}/provision`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ applicationId: String(values.applicationId).trim(), entraObjectId: String(values.entraObjectId).trim() }) });
      if (dialogAction.action === "change-return") response = await fetch(`/api/internal/applicant-submissions/${dialogAction.value}/return-for-correction`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section: values.section, reason: String(values.reason).trim() }) });
      if (dialogAction.action === "document-reject") response = await fetch(`/api/internal/applicant-document-submissions/${dialogAction.value}/reject`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: String(values.reason).trim() }) });
      if (!response?.ok) throw new Error();
      reviewDialog.close(); dialogAction = null; show("Review decision recorded."); await load();
    } catch (_error) { show("The review decision could not be recorded. Please check the entered values and try again."); }
    finally { reviewDialogSubmit.disabled = false; }
  });
  previewSearch?.addEventListener("input", updatePreviewFilters);
  previewStatus?.addEventListener("change", updatePreviewFilters);
  document.querySelector("[data-preview-filter]")?.addEventListener("submit", (event) => { event.preventDefault(); updatePreviewFilters(); });
  if (syntheticWorkspace) syntheticWorkspace.addEventListener("submit", async (event) => {
    event.preventDefault();
    const control = syntheticWorkspace.querySelector('button[type="submit"]');
    if (control) control.disabled = true;
    try {
      const response = await fetch(syntheticWorkspace.action, { method: "POST", credentials: "same-origin", redirect: "manual" });
      if (response.type !== "opaqueredirect") throw new Error();
      window.location.assign(new URL("/applicant/review", syntheticWorkspace.action).href);
    } catch (_error) {
      show("The synthetic applicant could not be created. Please refresh and try again.");
      if (control) control.disabled = false;
    }
  });
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
      if (action === "access-provision") { openReviewDialog(action, value); return; }
      if (action === "change-approve") {
        response = await postEmpty(`/api/internal/applicant-submissions/${value}/approve`);
        if (response.status === 409) {
          const blocked = await response.json();
          show(blocked.message || "One section must be returned to the applicant before approval.");
          return;
        }
      }
      if (action === "change-return") { openReviewDialog(action, value); return; }
      if (action === "document-accept") response = await postEmpty(`/api/internal/applicant-document-submissions/${value}/accept`);
      if (action === "document-reject") { openReviewDialog(action, value); return; }
      if (!response?.ok) throw new Error(); show("Review decision recorded."); await load();
    } catch (_error) { show("The review decision could not be recorded. Please refresh and try again."); }
    finally { control.disabled = false; }
  });
  load().catch(() => show("The review queues could not be loaded."));
  loadPreviews().catch(() => show("The applicant viewpoint list could not be loaded."));
})();
