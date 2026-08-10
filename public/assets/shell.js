(() => {
  const shell = document.querySelector("[data-shell]");
  if (!shell) return;

  const navigation = document.getElementById("application-navigation");
  const toggle = document.querySelector(".app-nav-toggle");
  const backdrop = document.querySelector(".app-nav-backdrop");
  const main = document.querySelector("main");
  const mobileQuery = window.matchMedia("(max-width: 720px)");

  const setDrawer = (open, restoreFocus = true) => {
    const active = Boolean(open);
    navigation.dataset.open = String(active);
    toggle.setAttribute("aria-expanded", String(active));
    toggle.setAttribute("aria-label", active ? "Close application navigation" : "Open application navigation");
    backdrop.hidden = !active;
    if (main) main.inert = active;
    if (!active && restoreFocus && mobileQuery.matches) toggle.focus();
  };

  toggle.addEventListener("click", () => setDrawer(navigation.dataset.open !== "true"));
  backdrop.addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && navigation.dataset.open === "true") setDrawer(false);
  });
  mobileQuery.addEventListener("change", () => {
    if (!mobileQuery.matches) setDrawer(false, false);
  });

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
  document.querySelectorAll("[data-skin-choice]").forEach((button) => {
    button.addEventListener("click", () => {
      preferences.skin = button.dataset.skinChoice;
      window.EHFAppearance.apply(preferences);
      document.querySelectorAll("[data-skin-choice]").forEach((choice) => choice.setAttribute("aria-pressed", String(choice === button)));
    });
  });
  document.querySelectorAll("[data-appearance-flag]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.appearanceFlag;
      preferences[key] = !preferences[key];
      button.setAttribute("aria-pressed", String(preferences[key]));
      window.EHFAppearance.apply(preferences);
    });
  });

  const timestamp = document.querySelector("[data-last-modified]");
  if (timestamp) {
    const modified = new Date(document.lastModified);
    if (!Number.isNaN(modified.getTime())) {
      timestamp.dateTime = modified.toISOString();
      timestamp.textContent = new Intl.DateTimeFormat(undefined, {
        year: "numeric", month: "short", day: "2-digit", hour: "2-digit",
        minute: "2-digit", second: "2-digit", timeZoneName: "short",
      }).format(modified);
    }
  }
})();
