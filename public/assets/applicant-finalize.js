(() => {
  const summary = document.querySelector("[data-final-summary]");
  const items = document.querySelector("[data-final-items]");
  const submit = document.querySelector("[data-final-submit]");
  const status = document.querySelector("[data-final-status]");
  const application = document.querySelector("[data-final-application]");
  const csrf = () => document.cookie.split("; ").find((item) => item.startsWith("__Host-ehf_applicant_csrf="))?.split("=")[1] || "";

  const label = (value) => value
    .replace(/^section:/, "Application section: ")
    .replace(/^document:/, "Required document: ")
    .replaceAll("_", " ");

  const formatValue = (field, value) => {
    if (value === null || value === undefined || value === "") return "Not provided";
    if (field.kind === "boolean") return value === true ? "Yes" : value === false ? "No" : String(value);
    if (field.kind === "degree_list" && Array.isArray(value)) {
      return value.length
        ? value.map((row) => `${row.degreeType || "Degree"} — ${row.conferralDate || "date not provided"}`).join("; ")
        : "None listed";
    }
    if (field.kind === "publication_list" && Array.isArray(value)) {
      return value.length ? value.map((row) => row.doi).filter(Boolean).join("; ") : "None listed";
    }
    if (Array.isArray(value) || typeof value === "object") return JSON.stringify(value);
    return String(value);
  };

  const render = ({ ready, unresolved }) => {
    if (!summary || !items || !submit) return;
    items.replaceChildren();
    if (ready) {
      summary.textContent = "Your application is complete and ready to submit.";
      const item = document.createElement("li");
      item.textContent = "All required sections and documents are complete.";
      items.append(item);
      submit.disabled = false;
      return;
    }
    summary.textContent = "Complete the following items before submission:";
    (unresolved || []).forEach((entry) => {
      const item = document.createElement("li");
      item.textContent = label(entry);
      items.append(item);
    });
    submit.disabled = true;
  };

  const renderApplication = (fields, values, visibleDocuments) => {
    if (!application) return;
    application.replaceChildren();
    const sections = [...new Set(fields.map((field) => field.section))];
    sections.forEach((sectionCode) => {
      const section = document.createElement("section");
      const heading = document.createElement("h3");
      heading.textContent = sectionCode.replaceAll("_", " ");
      const list = document.createElement("dl");
      fields.filter((field) => field.section === sectionCode).forEach((field) => {
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = field.label;
        const value = values[field.code];
        detail.textContent = formatValue(field, value);
        list.append(term, detail);
      });
      section.append(heading, list);
      application.append(section);
    });
    const documentSection = document.createElement("section");
    const documentHeading = document.createElement("h3");
    documentHeading.textContent = "Applicant-visible documents";
    const documentList = document.createElement("ul");
    (visibleDocuments || []).forEach((visibleDocument) => {
      const item = document.createElement("li");
      item.textContent = visibleDocument.displayName || visibleDocument.slotCode || "Application document";
      documentList.append(item);
    });
    if (!documentList.children.length) {
      const item = document.createElement("li");
      item.textContent = "No applicant-visible document is currently available.";
      documentList.append(item);
    }
    documentSection.append(documentHeading, documentList);
    application.append(documentSection);
  };

  const loadApplication = async () => {
    const [fieldResponse, applicationResponse] = await Promise.all([
      fetch("/api/applicant/review/fields", { credentials: "same-origin" }),
      fetch("/api/applicant/application", { credentials: "same-origin" }),
    ]);
    if (!fieldResponse.ok || !applicationResponse.ok) throw new Error("application unavailable");
    const fields = (await fieldResponse.json()).fields || [];
    const projection = await applicationResponse.json();
    const values = { ...(projection.applicant || {}) };
    const sections = [...new Set(fields.map((field) => field.section))];
    await Promise.all(sections.map(async (section) => {
      const response = await fetch(`/api/applicant/review/${section}`, { credentials: "same-origin" });
      if (!response.ok) throw new Error("review section unavailable");
      const snapshot = await response.json();
      Object.assign(values, snapshot.values || {});
    }));
    renderApplication(fields, values, projection.documents || []);
  };

  const load = async () => {
    try {
      const [response] = await Promise.all([
        fetch("/api/applicant/finalization", { credentials: "same-origin" }),
        loadApplication(),
      ]);
      if (!response.ok) throw new Error("request failed");
      render(await response.json());
    } catch (error) {
      console.error("Applicant final review load failed", error);
      if (summary) summary.textContent = "Your completion status could not be loaded. Please try again.";
      if (application) application.textContent = "Your reviewed application could not be loaded. Please try again.";
    }
  };

  submit?.addEventListener("click", async () => {
    submit.disabled = true;
    if (status) status.textContent = "Submitting…";
    try {
      const response = await fetch("/api/applicant/finalization", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf() },
      });
      const body = await response.json();
      if (!response.ok) {
        render({ ready: false, unresolved: body.unresolved || [] });
        if (status) status.textContent = "Your application is not yet complete.";
        return;
      }
      if (status) status.textContent = "Your completed application has been submitted.";
      if (summary) summary.textContent = "Submission complete.";
    } catch (_error) {
      if (status) status.textContent = "Submission could not be completed. Please try again.";
      submit.disabled = false;
    }
  });

  load();
})();
