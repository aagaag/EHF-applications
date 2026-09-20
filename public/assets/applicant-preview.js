(() => {
  if (document.documentElement.dataset.applicantPreviewReady === "true") return;
  document.documentElement.dataset.applicantPreviewReady = "true";
  const sections = [...document.querySelectorAll("[data-review-section]")];
  const showSection = (target) => {
    sections.forEach((section) => { section.hidden = section.dataset.reviewSection !== target; });
    document.querySelectorAll("[data-section-target]").forEach((button) => {
      button.setAttribute("aria-current", button.dataset.sectionTarget === target ? "page" : "false");
    });
    const selected = sections.find((section) => section.dataset.reviewSection === target);
    selected?.querySelector("h2")?.focus?.();
    selected?.scrollIntoView({ block: "start" });
  };
  document.addEventListener("click", (event) => {
    const control = event.target.closest("[data-section-target]");
    if (!control) return;
    showSection(control.dataset.sectionTarget);
  });
  const openPublicationRecord = (record) => {
    const url = record?.dataset.publicationUrl;
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  };
  const publicationDoubleClicks = new WeakSet();
  document.addEventListener("dblclick", (event) => {
    const record = event.target.closest("[data-publication-record]");
    if (!record || publicationDoubleClicks.has(record)) return;
    publicationDoubleClicks.add(record);
    window.setTimeout(() => publicationDoubleClicks.delete(record), 500);
    openPublicationRecord(record);
  });
  document.addEventListener("keydown", (event) => {
    const record = event.target.closest("[data-publication-record]");
    if (!record || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    openPublicationRecord(record);
  });
  const loadDocuments = async () => {
    const container = document.querySelector("[data-internal-documents]");
    const applicationId = container?.dataset.applicationId;
    if (!container || !applicationId) return;
    try {
      const response = await fetch(`/api/internal/applicants/${applicationId}/documents`, { credentials: "same-origin" });
      if (!response.ok) throw new Error();
      const payload = await response.json();
      const items = payload.documents || [];
      if (!items.length) {
        container.replaceChildren(Object.assign(document.createElement("p"), { textContent: "No approved submitted documents are available." }));
        return;
      }
      const packageActions = document.createElement("div");
      packageActions.className = "review-actions internal-document-package";
      const viewPackage = document.createElement("a");
      viewPackage.className = "primary-action";
      viewPackage.href = `/api/internal/applicants/${applicationId}/documents/package/view`;
      viewPackage.target = "_blank"; viewPackage.rel = "noopener";
      viewPackage.textContent = "View complete application PDF";
      const downloadPackage = document.createElement("a");
      downloadPackage.className = "secondary-action";
      downloadPackage.href = `/api/internal/applicants/${applicationId}/documents/package/download`;
      downloadPackage.textContent = "Download complete application PDF";
      packageActions.append(viewPackage, downloadPackage);
      const cards = items.map((item) => {
        const card = document.createElement("article"); card.className = "document-slot-card";
        const heading = document.createElement("h3"); heading.textContent = item.label;
        const detail = document.createElement("p"); detail.textContent = `Approved version ${item.versionNumber}`;
        const actions = document.createElement("div"); actions.className = "review-actions document-actions";
        const view = document.createElement("a"); view.className = "primary-action";
        view.href = `/api/internal/applicants/${applicationId}/documents/${item.versionId}/view`;
        view.target = "_blank"; view.rel = "noopener"; view.textContent = `View original ${item.label}`;
        const download = document.createElement("a"); download.className = "secondary-action";
        download.href = `/api/internal/applicants/${applicationId}/documents/${item.versionId}/download`;
        download.textContent = `Download original ${item.label}`;
        actions.append(view, download); card.append(heading, detail, actions); return card;
      });
      container.replaceChildren(packageActions, ...cards);
    } catch (_error) {
      container.replaceChildren(Object.assign(document.createElement("p"), { role: "status", textContent: "Submitted documents could not be loaded." }));
    }
  };
  showSection("identity");
  loadDocuments();
})();
