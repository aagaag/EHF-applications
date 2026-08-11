(() => {
  const container = document.querySelector("[data-document-slots]");
  const csrf = () => document.cookie.split("; ").find((item) => item.startsWith("__Host-ehf_applicant_csrf="))?.split("=")[1] || "";

  const renderSlot = (slot) => {
    const card = document.createElement("article");
    card.className = "document-slot-card";
    const title = document.createElement("h3");
    title.textContent = slot.label;
    const status = document.createElement("p");
    status.textContent = slot.status;
    card.append(title, status);
    if (slot.downloadAvailable) {
      const download = document.createElement("a");
      download.className = "secondary-action document-download";
      download.href = `/api/applicant/documents/${slot.slotId}/download`;
      download.textContent = `Download ${slot.label}`;
      card.append(download);
    }
    if (slot.uploadMode === "MISSING" || slot.uploadMode === "REPLACEMENT") {
      const form = document.createElement("form");
      form.className = "document-upload-form";
      const id = `upload-${slot.slotId}`;
      const label = document.createElement("label");
      label.htmlFor = id;
      label.textContent = `Choose PDF for ${slot.label}`;
      const input = document.createElement("input");
      input.id = id; input.type = "file"; input.accept = "application/pdf,.pdf"; input.required = true;
      const button = document.createElement("button");
      button.type = "submit"; button.className = "primary-action"; button.textContent = "Upload PDF";
      const result = document.createElement("p");
      result.role = "status"; result.className = "form-status";
      form.append(label, input, button, result);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = input.files?.[0]; if (!file) return;
        const data = new FormData(); data.append("file", file); data.append("expectedRowVersion", String(slot.rowVersion));
        result.textContent = "Uploading and checking the PDF…";
        try {
          const response = await fetch(`/api/applicant/documents/${slot.slotId}/upload`, { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrf() }, body: data });
          result.textContent = response.ok ? "Uploaded for Foundation review." : "The PDF could not be accepted. Your existing document is unchanged.";
        } catch (_error) { result.textContent = "The upload could not be completed. Your existing document is unchanged."; }
      });
      card.append(form);
    }
    return card;
  };

  const load = async () => {
    if (!container) return;
    try {
      const response = await fetch("/api/applicant/documents", { credentials: "same-origin" });
      if (!response.ok) throw new Error();
      const body = await response.json();
      container.replaceChildren(...body.slots.map(renderSlot));
    } catch (_error) {
      container.innerHTML = '<p role="status">The document checklist could not be loaded. Please try again.</p>';
    }
  };
  load();
})();
