(() => {
  const requestButton = document.querySelector("[data-request-code]");
  const form = document.querySelector("[data-verification-form]");
  const status = document.querySelector("[data-auth-status]");
  const widget = document.querySelector("[data-turnstile-widget]");

  const show = (message) => {
    if (status) status.textContent = message;
  };

  window.ehfApplicantTurnstileVerified = (token) => {
    if (!requestButton || typeof token !== "string" || !token) return;
    requestButton.dataset.turnstileToken = token;
    requestButton.disabled = false;
    if (form?.dataset.turnstileRequired === "true") {
      form.dataset.turnstileToken = token;
      form.querySelector('button[type="submit"]')?.removeAttribute("disabled");
    }
    show("Security check complete. You can request your verification code.");
  };
  window.ehfApplicantTurnstileExpired = () => {
    if (!requestButton) return;
    delete requestButton.dataset.turnstileToken;
    requestButton.disabled = true;
    show("The security check expired. Please complete it again.");
  };
  window.ehfApplicantTurnstileError = () => {
    if (requestButton) requestButton.disabled = true;
    show("The security check could not be completed. Please refresh the page.");
  };

  const siteKey = widget?.dataset.sitekey || "";
  if (siteKey && !siteKey.startsWith("__EHF_")) {
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    script.async = true;
    script.defer = true;
    script.onerror = window.ehfApplicantTurnstileError;
    document.head.append(script);
  }

  requestButton?.addEventListener("click", async () => {
    requestButton.disabled = true;
    show("Requesting a verification code…");
    try {
      const response = await fetch("/api/applicant/auth/code", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turnstileToken: requestButton.dataset.turnstileToken || "" }),
      });
      const body = await response.json();
      show(body.message || "The request could not be completed.");
      delete requestButton.dataset.turnstileToken;
      if (window.turnstile) window.turnstile.reset();
    } catch (_error) {
      show("The request could not be completed. Please try again.");
    } finally {
      requestButton.disabled = !requestButton.dataset.turnstileToken;
    }
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    show("Verifying the code…");
    try {
      const data = new FormData(form);
      const response = await fetch("/api/applicant/auth/verify", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: String(data.get("code") || ""),
          turnstileToken: form.dataset.turnstileToken || "",
        }),
      });
      const body = await response.json();
      if (response.ok && body.next) {
        window.location.assign(body.next);
        return;
      }
      if (body.turnstileRequired) {
        form.dataset.turnstileRequired = "true";
        delete form.dataset.turnstileToken;
        if (window.turnstile) window.turnstile.reset();
      }
      show(body.message || "The code could not be verified.");
    } catch (_error) {
      show("The code could not be verified. Please try again.");
    } finally {
      if (submit) submit.disabled = form.dataset.turnstileRequired === "true" && !form.dataset.turnstileToken;
    }
  });
})();
