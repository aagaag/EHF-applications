(() => {
  const shell = document.querySelector("[data-shell]");
  if (!shell) return;

  const navigation = document.getElementById("application-navigation");
  const toggle = document.querySelector(".app-nav-toggle");
  const backdrop = document.querySelector(".app-nav-backdrop");
  const main = document.querySelector("main");
  const mobileQuery = window.matchMedia("(max-width: 720px)");
  const focusDrawer = () => navigation.querySelector("a, button")?.focus();

  const setDrawer = (open, restoreFocus = true) => {
    const active = Boolean(open) && mobileQuery.matches;
    navigation.dataset.open = String(active);
    navigation.inert = !active && mobileQuery.matches;
    toggle.setAttribute("aria-expanded", String(active));
    toggle.setAttribute("aria-label", active ? "Close application navigation" : "Open application navigation");
    backdrop.hidden = !active;
    if (main) main.inert = active;
    if (active) focusDrawer();
    if (!active && restoreFocus && mobileQuery.matches) toggle.focus();
  };

  setDrawer(false, false);
  toggle.addEventListener("click", () => setDrawer(navigation.dataset.open !== "true"));
  backdrop.addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && navigation.dataset.open === "true") setDrawer(false);
  });
  mobileQuery.addEventListener("change", () => setDrawer(false, false));

  document.querySelectorAll("[data-disclosure]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = document.getElementById(button.getAttribute("aria-controls"));
      const opening = button.getAttribute("aria-expanded") !== "true";
      document.querySelectorAll("[data-disclosure]").forEach((other) => {
        other.setAttribute("aria-expanded", "false");
        document.getElementById(other.getAttribute("aria-controls")).hidden = true;
      });
      button.setAttribute("aria-expanded", String(opening));
      target.hidden = !opening;
    });
  });

  const preferences = { skin: "default", invert: false, compact: false, reduceMotion: false };
  const apply = () => window.EHFAppearance.apply(preferences);
  const syncButtons = () => {
    document.querySelectorAll("[data-skin-choice]").forEach((choice) => choice.setAttribute("aria-pressed", String(choice.dataset.skinChoice === preferences.skin)));
    document.querySelectorAll("[data-appearance-flag]").forEach((choice) => choice.setAttribute("aria-pressed", String(Boolean(preferences[choice.dataset.appearanceFlag]))));
  };
  const csrf = () => document.cookie.split("; ").find((item) => item.startsWith("__Host-ehf_applicant_csrf="))?.split("=")[1] || "";
  const save = () => fetch("/api/preferences", {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() }, body: JSON.stringify(preferences),
  }).then((response) => response.ok ? response.json() : null).then((stored) => {
    if (stored) Object.assign(preferences, stored);
    syncButtons(); apply();
  }).catch(() => undefined);
  fetch("/api/preferences", { credentials: "same-origin" }).then((response) => response.ok ? response.json() : null).then((stored) => {
    if (stored) Object.assign(preferences, stored);
    syncButtons(); apply();
  }).catch(() => undefined).finally(() => {
    document.documentElement.dataset.preferencesReady = "true";
  });

  document.querySelectorAll("[data-skin-choice]").forEach((button) => {
    button.addEventListener("click", () => { preferences.skin = button.dataset.skinChoice; syncButtons(); apply(); save(); });
  });
  document.querySelectorAll("[data-appearance-flag]").forEach((button) => {
    button.addEventListener("click", () => { const key = button.dataset.appearanceFlag; preferences[key] = !preferences[key]; syncButtons(); apply(); save(); });
  });

  const reportModal = document.querySelector("[data-report-modal]");
  const reportDetails = reportModal?.querySelector("[data-report-details]");
  const reportTitle = reportModal?.querySelector("[data-report-details-title]");
  const reportArtifactLinks = [...(reportModal?.querySelectorAll("[data-report-artifact]") || [])];
  const reportArtifactStatus = reportModal?.querySelector("[data-report-artifact-status]");
  let activeReportRow = null;
  let artifactRequest = 0;
  const resetReportArtifacts = (message = "Checking document availability…") => {
    reportArtifactLinks.forEach((link) => {
      link.removeAttribute("href");
      link.setAttribute("aria-disabled", "true");
    });
    if (reportArtifactStatus) reportArtifactStatus.textContent = message;
  };
  reportArtifactLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
    });
  });
  const loadReportArtifacts = async (applicationId) => {
    const request = ++artifactRequest;
    resetReportArtifacts();
    if (!applicationId) {
      resetReportArtifacts("No reviewed PDFs are available for this applicant.");
      return;
    }
    try {
      const response = await fetch(`/api/internal/applicants/${encodeURIComponent(applicationId)}/review-artifacts`, { credentials: "same-origin" });
      if (!response.ok) throw new Error("Artifact availability unavailable");
      const payload = await response.json();
      if (request !== artifactRequest) return;
      const available = new Set(Array.isArray(payload.available) ? payload.available : []);
      reportArtifactLinks.forEach((link) => {
        const category = link.dataset.reportArtifact;
        if (!available.has(category)) return;
        link.href = `/api/internal/applicants/${encodeURIComponent(applicationId)}/review-artifacts/${encodeURIComponent(category)}/view`;
        link.setAttribute("aria-disabled", "false");
      });
      const count = reportArtifactLinks.filter((link) => link.getAttribute("aria-disabled") === "false").length;
      if (reportArtifactStatus) reportArtifactStatus.textContent = count
        ? `${count} reviewed PDF${count === 1 ? " is" : "s are"} available. Unavailable buttons are dimmed.`
        : "No reviewed PDFs are available for this applicant.";
    } catch (_error) {
      if (request !== artifactRequest) return;
      resetReportArtifacts("Document availability could not be loaded. Please try again.");
    }
  };
  const fallbackReportDetails = (row) => {
    const cells = [...row.querySelectorAll('[role="cell"]')];
    const list = document.createElement("dl");
    list.className = "report-details-list";
    list.append(...cells.map((cell) => {
      const item = document.createElement("div");
      item.className = "report-details-item";
      const term = document.createElement("dt");
      term.textContent = cell.dataset.label || "Detail";
      const description = document.createElement("dd");
      description.textContent = cell.textContent.trim();
      if (cell.querySelector(".missing-value")) description.className = "missing-value";
      item.append(term, description);
      return item;
    }));
    reportDetails.replaceChildren(list);
  };
  const openReportDetails = async (row) => {
    if (!reportModal || !reportDetails || !reportTitle) return;
    const cells = [...row.querySelectorAll('[role="cell"]')];
    reportTitle.textContent = cells[0]?.textContent.trim() || "Application details";
    activeReportRow = row;
    loadReportArtifacts(row.dataset.applicationId);
    reportModal.showModal();
    const url = row.dataset.reportDetailsUrl;
    if (!url) {
      fallbackReportDetails(row);
      return;
    }
    reportDetails.innerHTML = '<p role="status">Loading complete publication history…</p>';
    try {
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) throw new Error("Applicant detail unavailable");
      reportDetails.innerHTML = await response.text();
      const publications = [...reportDetails.querySelectorAll("[data-publication-row]")];
      publications.forEach((publication, index) => {
        publication.dataset.publicationOrder = String(index);
        const openPublication = () => {
          const target = publication.dataset.publicationUrl;
          if (target) window.open(target, "_blank", "noopener,noreferrer");
        };
        publication.addEventListener("dblclick", () => {
          openPublication();
        });
        publication.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          openPublication();
        });
      });
      reportDetails.querySelectorAll("[data-publication-sort]").forEach((button) => {
        button.addEventListener("click", () => {
          const table = button.closest("[data-publication-table]");
          const body = table?.querySelector(".applicant-publication-body");
          if (!body) return;
          const direction = button.dataset.publicationSortDirection;
          const ordered = [...body.querySelectorAll("[data-publication-row]")];
          ordered.sort((left, right) => {
            const leftValue = left.dataset.publicationCitations;
            const rightValue = right.dataset.publicationCitations;
            const leftMissing = leftValue === "";
            const rightMissing = rightValue === "";
            if (leftMissing || rightMissing) {
              if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
            } else {
              const comparison = Number(leftValue) - Number(rightValue);
              if (comparison) return direction === "descending" ? -comparison : comparison;
            }
            return Number(left.dataset.publicationOrder) - Number(right.dataset.publicationOrder);
          });
          body.append(...ordered);
          table.querySelectorAll("[data-publication-sort]").forEach((control) => control.setAttribute("aria-pressed", "false"));
          button.setAttribute("aria-pressed", "true");
          table.querySelector("[data-publication-citation-header]")?.setAttribute("aria-sort", direction);
        });
      });
    } catch (_error) {
      reportDetails.innerHTML = '<p class="report-detail-error" role="alert">The complete applicant detail could not be loaded. Please try again.</p>';
    }
  };
  document.querySelectorAll("[data-report-row]").forEach((row) => {
    row.addEventListener("dblclick", () => openReportDetails(row));
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openReportDetails(row);
    });
  });
  reportModal?.querySelector("[data-report-modal-close]")?.addEventListener("click", () => reportModal.close());
  reportModal?.addEventListener("close", () => {
    artifactRequest += 1;
    resetReportArtifacts("Document availability loads when an applicant is opened.");
    activeReportRow?.focus();
    activeReportRow = null;
  });

  const reportCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  document.querySelectorAll("[data-report-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const table = button.closest(".report-table");
      const data = table?.querySelector(".report-data");
      const index = Number(button.dataset.reportSortIndex);
      const kind = button.dataset.reportSortKind;
      const direction = button.dataset.reportSortDirection;
      if (!data || !Number.isInteger(index)) return;
      const rows = [...data.children].filter((row) => row.matches("[data-report-row]"));
      rows.sort((leftRow, rightRow) => {
        const left = leftRow.querySelectorAll('[role="cell"]')[index];
        const right = rightRow.querySelectorAll('[role="cell"]')[index];
        const leftMissing = Boolean(left?.querySelector(".missing-value"));
        const rightMissing = Boolean(right?.querySelector(".missing-value"));
        if (leftMissing || rightMissing) {
          if (leftMissing === rightMissing) return 0;
          return leftMissing ? 1 : -1;
        }
        const leftText = left?.dataset.reportSortValue || left?.textContent.trim() || "";
        const rightText = right?.dataset.reportSortValue || right?.textContent.trim() || "";
        const comparison = kind === "number"
          ? Number(leftText.replaceAll(",", "")) - Number(rightText.replaceAll(",", ""))
          : reportCollator.compare(leftText, rightText);
        return direction === "descending" ? -comparison : comparison;
      });
      data.append(...rows);
      table.querySelectorAll("[data-report-sort]").forEach((control) => control.setAttribute("aria-pressed", "false"));
      table.querySelectorAll('[role="columnheader"]').forEach((header) => header.removeAttribute("aria-sort"));
      button.setAttribute("aria-pressed", "true");
      button.closest('[role="columnheader"]')?.setAttribute("aria-sort", direction);
    });
  });

  const reportFilter = document.querySelector("[data-report-filter]");
  const reportFilterEmpty = document.querySelector("[data-report-filter-empty]");
  reportFilter?.addEventListener("change", () => {
    const rows = [...document.querySelectorAll("[data-report-row]")];
    rows.forEach((row) => { row.hidden = row.dataset.reportStatus !== reportFilter.value; });
    if (reportFilterEmpty) reportFilterEmpty.hidden = rows.some((row) => !row.hidden);
  });

  const timestamp = document.querySelector("[data-last-modified]");
  if (timestamp) {
    const modified = new Date(document.lastModified);
    if (!Number.isNaN(modified.getTime())) {
      timestamp.dateTime = modified.toISOString();
      timestamp.textContent = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short" }).format(modified);
    }
  }
})();
