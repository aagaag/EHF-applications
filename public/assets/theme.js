(() => {
  const allowedSkins = new Set(["default", "high-contrast", "soft-earth", "blue"]);
  const apply = (preference = {}) => {
    document.documentElement.dataset.skin = allowedSkins.has(preference.skin) ? preference.skin : "default";
    document.documentElement.dataset.invert = preference.invert ? "true" : "false";
    document.documentElement.dataset.density = preference.compact ? "compact" : "comfortable";
    document.documentElement.dataset.motion = preference.reduceMotion ? "reduced" : "system";
  };

  window.EHFAppearance = Object.freeze({ apply, allowedSkins: [...allowedSkins] });
  apply();
})();
