const supported = new Set([
  "constellation-light", "constellation-dark", "high-contrast", "anaxigraph",
]);

try {
  const saved = window.localStorage.getItem("anaxigraph.theme");
  if (supported.has(saved)) document.documentElement.dataset.theme = saved;
} catch (_) {
  // Storage can be unavailable in privacy-restricted browser contexts.
}
