(() => {
  const state = new Map();
  const customFields = new Map();
  let controlSequence = 0;
  const nextControlId = (prefix) => `${prefix}-${++controlSequence}`;
  const sections = [...document.querySelectorAll("[data-review-section]")];
  const syntheticBanner = document.querySelector("[data-synthetic-banner]");
  const markSessionUnverified = () => {
    if (!syntheticBanner) return;
    syntheticBanner.textContent = "Session type could not be verified — protected controls remain unavailable.";
    syntheticBanner.hidden = false;
  };
  const csrf = () => {
    try { return document.cookie.split("; ").find((item) => item.startsWith("__Host-ehf_applicant_csrf="))?.split("=")[1] || ""; }
    catch (_error) { return ""; }
  };
  const statusFor = (section) => document.querySelector(`[data-section-status="${section}"]`);
  const showStatus = (section, message) => { const target = statusFor(section); if (target) target.textContent = message; };
  const showReturnNotice = (section, returned, confirmed = false) => {
    const container = document.querySelector(`[data-review-section="${section}"] .section-heading`);
    if (!container) return;
    let notice = container.querySelector("[data-returned-for-correction]");
    if (!returned?.reason) { notice?.remove(); return; }
    if (!notice) {
      notice = document.createElement("p");
      notice.className = "correction-notice";
      notice.dataset.returnedForCorrection = "";
      notice.setAttribute("role", "note");
      container.append(notice);
    }
    const instruction = confirmed
      ? "The requested correction has been saved and confirmed."
      : "Save and confirm this section again.";
    notice.textContent = `Returned for correction: ${returned.reason} ${instruction}`;
  };
  const loadSessionKind = async () => {
    try {
      const response = await fetch("/api/applicant/session", { credentials: "same-origin" });
      if (!response.ok) { markSessionUnverified(); return; }
      const session = await response.json();
      if (session.authenticated !== true || typeof session.syntheticAdmin !== "boolean") {
        markSessionUnverified();
        return;
      }
      if (session.syntheticAdmin && syntheticBanner) {
        syntheticBanner.hidden = false;
      }
    } catch (_error) { markSessionUnverified(); }
  };
  const notifyChanged = (node) => node.dispatchEvent(new Event("input", { bubbles: true }));
  const syncProgress = () => {
    const confirmed = [...state.values()].filter((item) => item.confirmed).length;
    const progress = document.querySelector("[data-progress]");
    const progressText = document.querySelector("[data-progress-text]");
    if (progress) progress.value = confirmed;
    if (progressText) progressText.textContent = `${confirmed} of ${state.size} sections confirmed`;
  };

  const showSection = (section) => {
    sections.forEach((node) => { node.hidden = node.dataset.reviewSection !== section; });
    document.querySelectorAll("[data-section-target]").forEach((button) => {
      button.setAttribute("aria-current", button.dataset.sectionTarget === section ? "page" : "false");
    });
    document.querySelector(`[data-review-section="${section}"] h2`)?.focus?.();
  };
  document.querySelectorAll("[data-section-target]").forEach((button) => {
    button.addEventListener("click", () => showSection(button.dataset.sectionTarget));
  });

  const helpText = (definition) => {
    if (!definition.help) return null;
    const help = document.createElement("span");
    help.className = "field-help";
    help.textContent = definition.help;
    return help;
  };

  const createStandardField = (definition) => {
    const wrapper = document.createElement("div");
    wrapper.className = `review-field review-field-${definition.code}`;
    wrapper.dataset.fieldCode = definition.code;
    const id = `applicant-field-${definition.code}`;
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = definition.label;
    let input;
    if (definition.kind === "choice") {
      input = document.createElement("select");
      input.append(new Option("Select…", ""));
      (definition.options || []).forEach((option) => input.append(new Option(option, option)));
    } else if (definition.kind === "boolean") {
      input = document.createElement("select");
      input.append(new Option("Select…", ""), new Option("Yes", "true"), new Option("No", "false"));
    } else {
      input = document.createElement("input");
      input.type = definition.kind === "date" ? "date" : definition.kind === "email" ? "email" : definition.kind === "integer" || definition.kind === "number" ? "number" : definition.kind === "scholar_url" ? "url" : "text";
      if (definition.kind === "number") { input.min = "0"; input.max = "100"; input.step = "0.01"; }
      if (definition.kind === "integer") { input.min = "0"; input.step = "1"; }
    }
    input.id = id;
    input.name = definition.code;
    input.required = Boolean(definition.required);
    wrapper.append(label, input);
    const help = helpText(definition);
    if (help) wrapper.append(help);
    return wrapper;
  };

  const createDegreeField = (definition) => {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "review-field review-field-wide repeatable-field degree-list";
    fieldset.dataset.fieldCode = definition.code;
    const legend = document.createElement("legend");
    legend.textContent = definition.label;
    const help = helpText(definition);
    const rows = document.createElement("div");
    rows.className = "repeatable-rows";
    rows.dataset.degreeRows = "";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "secondary-action add-row-action";
    add.textContent = "Add degree";

    const appendRow = (value = {}, announce = true) => {
      const row = document.createElement("div");
      row.className = "degree-row";
      row.dataset.degreeRow = "";
      const typeGroup = document.createElement("div");
      typeGroup.className = "review-field";
      const typeId = nextControlId("degree-type");
      const typeLabel = document.createElement("label");
      typeLabel.htmlFor = typeId;
      typeLabel.textContent = "Degree type";
      const select = document.createElement("select");
      select.id = typeId;
      select.append(new Option("Select…", ""));
      (definition.options || []).forEach((option) => select.append(new Option(option, option)));
      select.value = value.degreeType || "";
      typeGroup.append(typeLabel, select);

      const dateGroup = document.createElement("div");
      dateGroup.className = "review-field";
      const dateId = nextControlId("degree-date");
      const dateLabel = document.createElement("label");
      dateLabel.htmlFor = dateId;
      dateLabel.textContent = "Date of conferral";
      const dateInput = document.createElement("input");
      dateInput.id = dateId;
      dateInput.type = "date";
      dateInput.value = value.conferralDate || "";
      dateGroup.append(dateLabel, dateInput);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "secondary-action remove-row-action";
      remove.textContent = "Remove degree";
      remove.addEventListener("click", () => {
        row.remove();
        notifyChanged(fieldset);
        add.focus();
      });
      row.append(typeGroup, dateGroup, remove);
      rows.append(row);
      if (announce) notifyChanged(fieldset);
    };
    add.addEventListener("click", () => appendRow());
    fieldset.append(legend);
    if (help) fieldset.append(help);
    fieldset.append(rows, add);
    customFields.set("qualifications:degrees", {
      get: () => [...rows.querySelectorAll("[data-degree-row]")].map((row) => ({
        degreeType: row.querySelector("select").value,
        conferralDate: row.querySelector('input[type="date"]').value,
      })),
      set: (values) => {
        rows.replaceChildren();
        (Array.isArray(values) ? values : []).forEach((value) => appendRow(value, false));
      },
    });
    return fieldset;
  };

  const lookupPublication = async (doi) => {
    const response = await fetch("/api/applicant/review/publications/lookup", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
      body: JSON.stringify({ doi }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || "The publication could not be found.");
    return body.publication;
  };

  const publicationSummary = (metadata) => {
    const summary = document.createElement("div");
    summary.className = "publication-summary";
    const title = document.createElement("strong");
    title.textContent = metadata.title || metadata.doi;
    const details = document.createElement("span");
    details.textContent = [
      (metadata.authors || []).join(", "), metadata.journal,
      metadata.publicationDate, metadata.doi,
    ].filter(Boolean).join(" · ");
    summary.append(title, details);
    return summary;
  };

  const createPublicationField = (definition) => {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "review-field review-field-wide repeatable-field publication-list";
    fieldset.dataset.fieldCode = definition.code;
    const legend = document.createElement("legend");
    legend.textContent = definition.label;
    const help = helpText(definition);
    const lookupRow = document.createElement("div");
    lookupRow.className = "doi-lookup-row";
    const inputGroup = document.createElement("div");
    inputGroup.className = "review-field";
    const doiLabel = document.createElement("label");
    doiLabel.htmlFor = "publication-doi";
    doiLabel.textContent = "Publication DOI";
    const doiInput = document.createElement("input");
    doiInput.id = "publication-doi";
    doiInput.type = "text";
    doiInput.autocomplete = "off";
    doiInput.placeholder = "10.1234/example";
    inputGroup.append(doiLabel, doiInput);
    const lookup = document.createElement("button");
    lookup.type = "button";
    lookup.className = "secondary-action";
    lookup.textContent = "Look up DOI";
    lookupRow.append(inputGroup, lookup);

    const lookupStatus = document.createElement("p");
    lookupStatus.className = "field-help";
    lookupStatus.setAttribute("role", "status");
    lookupStatus.setAttribute("aria-live", "polite");
    const preview = document.createElement("div");
    preview.className = "publication-preview";
    preview.hidden = true;
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "primary-action";
    confirm.textContent = "Confirm and add publication";
    const rows = document.createElement("div");
    rows.className = "repeatable-rows publication-rows";
    let pending = null;

    const entries = new Map();
    const appendPublication = (value, metadata = null, announce = true) => {
      if (!value?.doi || entries.has(value.doi)) return;
      const row = document.createElement("div");
      row.className = "publication-row";
      row.dataset.publicationRow = "";
      row.dataset.doi = value.doi;
      row.append(publicationSummary(metadata || { doi: value.doi }));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "secondary-action remove-row-action";
      remove.textContent = "Remove publication";
      remove.addEventListener("click", () => {
        entries.delete(value.doi);
        row.remove();
        notifyChanged(fieldset);
        lookupStatus.textContent = "Publication removed.";
        doiInput.focus();
      });
      row.append(remove);
      rows.append(row);
      entries.set(value.doi, {
        doi: value.doi,
        confirmed: true,
        ...(value.lookupReceipt ? { lookupReceipt: value.lookupReceipt } : {}),
      });
      if (announce) notifyChanged(fieldset);
      if (!metadata) {
        lookupPublication(value.doi).then((resolved) => {
          row.querySelector(".publication-summary")?.replaceWith(publicationSummary(resolved));
        }).catch(() => {});
      }
    };

    lookup.addEventListener("click", async () => {
      pending = null;
      preview.hidden = true;
      lookupStatus.textContent = "Looking up publication…";
      lookup.disabled = true;
      try {
        pending = await lookupPublication(doiInput.value);
        preview.replaceChildren(publicationSummary(pending), confirm);
        preview.hidden = false;
        lookupStatus.textContent = "Check the publication below before adding it.";
      } catch (error) {
        lookupStatus.textContent = error.message || "The publication could not be found.";
      } finally {
        lookup.disabled = false;
      }
    });
    confirm.addEventListener("click", () => {
      if (!pending) return;
      appendPublication({
        doi: pending.doi,
        confirmed: true,
        lookupReceipt: pending.lookupReceipt,
      }, pending);
      doiInput.value = "";
      pending = null;
      preview.hidden = true;
      lookupStatus.textContent = "Publication confirmed and added.";
      doiInput.focus();
    });

    fieldset.append(legend);
    if (help) fieldset.append(help);
    fieldset.append(lookupRow, lookupStatus, preview, rows);
    customFields.set("publications:publications", {
      get: () => [...entries.values()],
      set: (values) => {
        entries.clear();
        rows.replaceChildren();
        (Array.isArray(values) ? values : []).forEach((value) => appendPublication(value, null, false));
      },
    });
    return fieldset;
  };

  const createField = (definition) => {
    if (definition.kind === "degree_list") return createDegreeField(definition);
    if (definition.kind === "publication_list") return createPublicationField(definition);
    return createStandardField(definition);
  };

  const syncScholarVisibility = () => {
    const answer = document.querySelector('[name="hasGoogleScholarProfile"]');
    const url = document.querySelector('[data-field-code="googleScholarProfileUrl"]');
    if (!answer || !url) return;
    const visible = answer.value === "true";
    url.hidden = !visible;
    const input = url.querySelector("input");
    if (input) {
      input.required = visible;
      input.setAttribute("aria-required", visible ? "true" : "false");
      if (!visible) input.value = "";
    }
  };

  const loadMetadata = async () => {
    const response = await fetch("/api/applicant/review/fields", { credentials: "same-origin" });
    if (!response.ok) throw new Error("field metadata unavailable");
    const { fields } = await response.json();
    fields.filter((field) => field.section !== "contribution").forEach((field) => {
      const container = document.querySelector(`[data-generated-fields="${field.section}"]`);
      if (!container) return;
      container.classList.add(`review-fields-${field.section}`);
      container.append(createField(field));
    });
    document.querySelector('[name="hasGoogleScholarProfile"]')?.addEventListener("change", syncScholarVisibility);
    syncScholarVisibility();
    return fields;
  };

  const setValues = (section, values) => {
    const form = document.querySelector(`[data-review-form="${section}"]`);
    if (!form) return;
    Object.entries(values || {}).forEach(([name, value]) => {
      const custom = customFields.get(`${section}:${name}`);
      if (custom) custom.set(value);
      else {
        const input = form.elements.namedItem(name);
        if (input && value !== null && value !== undefined) input.value = String(value);
      }
    });
    if (section === "publications") syncScholarVisibility();
  };

  const loadInitialData = async () => {
    try {
      await loadMetadata();
      const applicationResponse = await fetch("/api/applicant/application", { credentials: "same-origin" });
      const imported = applicationResponse.ok ? (await applicationResponse.json()).applicant || {} : {};
      await Promise.all([...state.keys()].map(async (section) => {
        const response = await fetch(`/api/applicant/review/${section}`, { credentials: "same-origin" });
        if (!response.ok) return;
        const snapshot = await response.json();
        const values = snapshot.rowVersion === null ? imported : snapshot.values;
        setValues(section, values);
        state.set(section, {
          rowVersion: snapshot.rowVersion,
          confirmed: snapshot.confirmed,
          returnedForCorrection: snapshot.returnedForCorrection || null,
          correctionSaved: false,
        });
        showReturnNotice(section, snapshot.returnedForCorrection, snapshot.confirmed);
        if (snapshot.returnedForCorrection && !snapshot.confirmed) {
          document.querySelector(`[data-review-form="${section}"] [data-confirm]`)?.setAttribute("disabled", "");
        }
        if (snapshot.confirmed) showStatus(section, "Confirmed");
        else if (snapshot.returnedForCorrection) showStatus(section, "Correction requested — save and confirm this section again.");
      }));
      syncProgress();
      updateCounter();
    } catch (_error) {
      showStatus("identity", "Your saved application data could not be loaded. Please refresh the page.");
    }
  };

  const formValues = (form) => {
    const values = Object.fromEntries([...new FormData(form).entries()].map(([key, value]) => [key, value]));
    const section = form.dataset.reviewForm;
    customFields.forEach((control, key) => {
      const [controlSection, name] = key.split(":");
      if (controlSection === section) values[name] = control.get();
    });
    return values;
  };
  document.querySelectorAll("[data-review-form]").forEach((form) => {
    const section = form.dataset.reviewForm;
    let autosaveTimer = null;
    form.noValidate = true;
    state.set(section, { rowVersion: null, confirmed: false });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (autosaveTimer !== null) { window.clearTimeout(autosaveTimer); autosaveTimer = null; }
      showStatus(section, "Saving…");
      try {
        const response = await fetch(`/api/applicant/review/${section}`, {
          method: "PUT", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
          body: JSON.stringify({ values: formValues(form), expectedRowVersion: state.get(section).rowVersion }),
        });
        const body = await response.json();
        if (!response.ok) {
          if (response.status === 409 && body.current) {
            setValues(section, body.current.values);
            state.set(section, { rowVersion: body.current.rowVersion, confirmed: body.current.confirmed });
            showStatus(section, "This section changed elsewhere. The current saved values are now shown; review them before trying again.");
          } else {
            showStatus(section, "Please correct the highlighted information.");
          }
          return;
        }
        const current = state.get(section);
        const returnedForCorrection = body.returnedForCorrection || current.returnedForCorrection || null;
        state.set(section, {
          rowVersion: body.rowVersion,
          confirmed: body.confirmed,
          returnedForCorrection,
          correctionSaved: true,
        });
        showReturnNotice(section, returnedForCorrection, body.confirmed);
        form.querySelector("[data-confirm]")?.removeAttribute("disabled");
        showStatus(section, "Saved");
      } catch (error) { console.error("Applicant autosave failed", error); showStatus(section, "Your changes could not be saved. They remain on this page; please try again."); }
    });
    form.addEventListener("input", () => {
      const current = state.get(section);
      state.set(section, { ...current, correctionSaved: false });
      showReturnNotice(section, current.returnedForCorrection, false);
      form.querySelector("[data-confirm]")?.setAttribute("disabled", "");
      showStatus(section, "Unsaved changes…");
      if (autosaveTimer !== null) window.clearTimeout(autosaveTimer);
      autosaveTimer = window.setTimeout(() => form.requestSubmit(), 800);
    });
    form.querySelector("[data-confirm]")?.addEventListener("click", async () => {
      const current = state.get(section);
      if (current.rowVersion === null) { showStatus(section, "Save this section before confirming it."); return; }
      showStatus(section, "Confirming…");
      try {
        const response = await fetch(`/api/applicant/review/${section}/confirm`, {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
          body: JSON.stringify({ rowVersion: current.rowVersion }),
        });
        const body = await response.json();
        if (!response.ok) { showStatus(section, body.message || "Complete every required field before confirming this section."); return; }
        state.set(section, { ...current, confirmed: true });
        showReturnNotice(section, current.returnedForCorrection, true);
        syncProgress();
        showStatus(section, "Confirmed");
      } catch (_error) { showStatus(section, "The section could not be confirmed. Please try again."); }
    });
    form.querySelector("[data-correct]")?.addEventListener("click", () => form.querySelector("input, select, textarea")?.focus());
  });

  const contribution = document.querySelector("[data-contribution]");
  const counter = document.querySelector("[data-character-counter]");
  const updateCounter = () => { if (counter && contribution) counter.textContent = `${1000 - Array.from(contribution.value).length} characters remaining`; };
  contribution?.addEventListener("input", updateCounter);
  updateCounter();
  showSection("identity");
  loadSessionKind();
  loadInitialData();
})();
