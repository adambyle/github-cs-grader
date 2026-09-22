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
