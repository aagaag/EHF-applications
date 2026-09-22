(() => {
  const root = document.querySelector("[data-pending-publications]");
  const value = (item) => item || "Not recorded";
  const node = (tag, text, className = "") => {
    const result = document.createElement(tag);
    result.textContent = text;
    result.className = className;
    return result;
  };
  const citation = (item) => [item.authors, item.title,
    [item.journal, item.year, item.volume, item.pages].filter(Boolean).join(" ")]
    .filter(Boolean).join(". ") || value(item.rawCitation);
  const render = (items) => root.replaceChildren(...items.map((item) => {
    const card = node("article", "", "pending-paper-card");
    card.dataset.publicationId = item.publicationId;
    card.append(node("h2", value(item.applicantName)));
    card.append(node("p", citation(item), "pending-paper-citation"));
    card.append(node("p", item.doi ? `DOI: ${item.doi}` : value(item.rawCitation)));
    const actions = node("div", "", "pending-paper-actions");
    for (const [decision, label] of [["published", "Published"], ["preprint", "Preprint"], ["remove", "Remove"]]) {
      const button = node("button", label);
      button.type = "button";
      button.dataset.decision = decision;
      actions.append(button);
    }
    card.append(actions);
    const error = node("p", "", "pending-paper-error");
    error.dataset.error = "";
    error.hidden = true;
    card.append(error);
    return card;
  }));
  root.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-decision]");
    if (!button) return;
    const card = button.closest("[data-publication-id]");
    const controls = card.querySelectorAll("button");
    const error = card.querySelector("[data-error]");
    controls.forEach((control) => { control.disabled = true; });
    try {
      const response = await fetch(`/api/internal/pending-publications/${card.dataset.publicationId}/${button.dataset.decision}`, {method: "POST", credentials: "same-origin"});
      if (!response.ok) throw new Error((await response.json()).message);
      card.remove();
    } catch (reason) {
      error.textContent = reason.message || "Could not save this review.";
      error.hidden = false;
      controls.forEach((control) => { control.disabled = false; });
    }
  });
  fetch("/api/internal/pending-publications", {credentials: "same-origin"})
    .then((response) => response.json()).then(({publications}) => render(publications))
    .catch(() => { root.textContent = "The pending-paper queue is unavailable."; });
})();
