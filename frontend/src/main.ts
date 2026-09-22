// Loaded by every page (webapp/templates/base.html). Page-specific scripts
// will sit beside it, one file per page; there is no bundler.

// Theme: follows the system until toggled; the choice is remembered. The
// inline script in base.html applies a saved choice before first paint.
const toggle = document.getElementById("theme-toggle");
toggle?.addEventListener("click", () => {
  const root = document.documentElement;
  const current =
    root.dataset.theme ??
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  localStorage.setItem("theme", next);
});

// <form data-confirm="Send 27 invitations?"> asks before submitting.
document.addEventListener("submit", (event) => {
  const form = event.target as HTMLFormElement;
  const message = form.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

// Going Back can show a page restored from the browser's memory, with data
// that has since changed (a course that just gained an offering). The
// server sends no-store, but not every browser honors it for Back; reload
// any restored page.
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    window.location.reload();
  }
});
