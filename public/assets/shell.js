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
  let activeReportRow = null;
  const openReportDetails = (row) => {
    if (!reportModal || !reportDetails || !reportTitle) return;
    const cells = [...row.querySelectorAll('[role="cell"]')];
    reportTitle.textContent = cells[0]?.textContent.trim() || "Application details";
    reportDetails.replaceChildren(...cells.map((cell) => {
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
    activeReportRow = row;
    reportModal.showModal();
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
        const leftText = left?.textContent.trim() || "";
        const rightText = right?.textContent.trim() || "";
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
