(() => {
  const state = new Map();
  const sections = [...document.querySelectorAll("[data-review-section]")];
  const csrf = () => {
    try { return document.cookie.split("; ").find((item) => item.startsWith("__Host-ehf_applicant_csrf="))?.split("=")[1] || ""; }
    catch (_error) { return ""; }
  };
  const statusFor = (section) => document.querySelector(`[data-section-status="${section}"]`);
  const showStatus = (section, message) => { const target = statusFor(section); if (target) target.textContent = message; };
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

  const createField = (definition) => {
    const wrapper = document.createElement("div");
    wrapper.className = "review-field";
    const id = `applicant-field-${definition.code}`;
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = definition.label;
    let input;
    if (definition.kind === "choice") {
      input = document.createElement("select");
      input.append(new Option("Select…", ""));
      (definition.options || []).forEach((option) => input.append(new Option(option.replaceAll("_", "/"), option)));
    } else if (definition.kind === "boolean") {
      input = document.createElement("select");
      input.append(new Option("Select…", ""), new Option("Yes", "true"), new Option("No", "false"));
    } else {
      input = document.createElement("input");
      input.type = definition.kind === "date" ? "date" : definition.kind === "email" ? "email" : definition.kind === "integer" || definition.kind === "number" ? "number" : "text";
      if (definition.kind === "number") { input.min = "0"; input.max = "100"; input.step = "0.01"; }
      if (definition.kind === "integer") { input.min = "0"; input.step = "1"; }
    }
    input.id = id;
    input.name = definition.code;
    input.required = Boolean(definition.required);
    wrapper.append(label, input);
    if (definition.help) { const help = document.createElement("span"); help.className = "field-help"; help.textContent = definition.help; wrapper.append(help); }
    return wrapper;
  };

  const loadMetadata = async () => {
    const response = await fetch("/api/applicant/review/fields", { credentials: "same-origin" });
    if (!response.ok) throw new Error("field metadata unavailable");
    const { fields } = await response.json();
    fields.filter((field) => field.section !== "contribution").forEach((field) => {
      document.querySelector(`[data-generated-fields="${field.section}"]`)?.append(createField(field));
    });
    return fields;
  };

  const setValues = (section, values) => {
    const form = document.querySelector(`[data-review-form="${section}"]`);
    if (!form) return;
    Object.entries(values || {}).forEach(([name, value]) => {
      const input = form.elements.namedItem(name);
      if (input && value !== null && value !== undefined) input.value = String(value);
    });
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
        state.set(section, { rowVersion: snapshot.rowVersion, confirmed: snapshot.confirmed });
        if (snapshot.confirmed) showStatus(section, "Confirmed");
      }));
      syncProgress();
      updateCounter();
    } catch (_error) {
      showStatus("identity", "Your saved application data could not be loaded. Please refresh the page.");
    }
  };

  const formValues = (form) => Object.fromEntries([...new FormData(form).entries()].map(([key, value]) => [key, value]));
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
        state.set(section, { rowVersion: body.rowVersion, confirmed: body.confirmed });
        form.querySelector("[data-confirm]")?.removeAttribute("disabled");
        showStatus(section, "Saved");
      } catch (error) { console.error("Applicant autosave failed", error); showStatus(section, "Your changes could not be saved. They remain on this page; please try again."); }
    });
    form.addEventListener("input", () => {
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
        if (!response.ok) { showStatus(section, "Complete every required field before confirming this section."); return; }
        state.set(section, { ...current, confirmed: true });
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
  loadInitialData();
})();
