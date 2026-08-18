(() => {
  const form = document.querySelector("[data-access-request-form]");
  const submit = form?.querySelector('button[type="submit"]');
  const status = document.querySelector("[data-access-status]");
  const widget = document.querySelector("[data-turnstile-widget]");
  let token = "";
  const show = (message) => { if (status) status.textContent = message; };
  window.ehfAccessTurnstileVerified = (value) => { token = value || ""; if (submit) submit.disabled = !token; };
  window.ehfAccessTurnstileExpired = () => { token = ""; if (submit) submit.disabled = true; };
  window.ehfAccessTurnstileError = () => { token = ""; if (submit) submit.disabled = true; show("The security check could not be completed. Please refresh the page."); };
  const siteKey = widget?.dataset.sitekey || "";
  if (siteKey && !siteKey.startsWith("__EHF_")) {
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    script.async = true;
    script.defer = true;
    script.onerror = window.ehfAccessTurnstileError;
    document.head.append(script);
  }
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit) submit.disabled = true;
    show("Submitting your request…");
    const data = new FormData(form);
    try {
      const response = await fetch("/api/applicant-access-requests", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          displayName: String(data.get("displayName") || ""),
          email: String(data.get("email") || ""),
          turnstileToken: token,
        }),
      });
      const body = await response.json();
      show(body.message || "The request could not be completed.");
      if (response.ok) form.reset();
    } catch (_error) { show("The request could not be completed. Please try again."); }
    token = "";
    if (window.turnstile) window.turnstile.reset();
  });
})();
