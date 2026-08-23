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
    const url = record?.dataset.googleScholarUrl;
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
  showSection("identity");
})();
