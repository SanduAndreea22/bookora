(function () {
  const html = document.documentElement;

  // Theme
  const themeToggle = document.getElementById("themeToggle");
  const savedTheme = localStorage.getItem("bookora_theme");
  if (savedTheme) html.setAttribute("data-theme", savedTheme);

  function setTheme(next) {
    html.setAttribute("data-theme", next);
    localStorage.setItem("bookora_theme", next);
  }

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const current = html.getAttribute("data-theme") || "light";
      setTheme(current === "light" ? "dark" : "light");
    });
  }

  // Mobile nav
  const menuToggle = document.getElementById("menuToggle");
  const navbar = document.getElementById("navbar");
  if (menuToggle && navbar) {
    menuToggle.addEventListener("click", () => {
      navbar.classList.toggle("open");
    });
  }

  // Dropdown
  const dropdown = document.getElementById("userDropdown");
  if (dropdown) {
    const btn = dropdown.querySelector(".dropdown-btn");
    btn?.addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.classList.toggle("open");
      btn.setAttribute("aria-expanded", dropdown.classList.contains("open") ? "true" : "false");
    });
  }

  // Close menus on outside click
  document.addEventListener("click", () => {
    navbar?.classList.remove("open");
    if (dropdown) {
      dropdown.classList.remove("open");
      const btn = dropdown.querySelector(".dropdown-btn");
      btn?.setAttribute("aria-expanded", "false");
    }
  });
})();


// Password toggle buttons: <button data-toggle-password="#id_password">
document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const selector = btn.getAttribute("data-toggle-password");
    const input = document.querySelector(selector);
    if (!input) return;

    const icon = btn.querySelector("i");
    if (input.type === "password") {
      input.type = "text";
      if (icon) icon.className = "fa-solid fa-eye-slash";
    } else {
      input.type = "password";
      if (icon) icon.className = "fa-solid fa-eye";
    }
  });
});
