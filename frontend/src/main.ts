// Loaded by every page (webapp/templates/base.html). Page-specific scripts
// will sit beside it, one file per page; there is no bundler.

const status = document.getElementById("js-status");
if (status) {
  status.textContent = "TypeScript loaded.";
}
