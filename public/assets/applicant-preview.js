(() => {
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
  showSection("identity");
})();
