(function () {
  function qs(id) { return document.getElementById(id); }

  document.addEventListener("DOMContentLoaded", () => {
    // Mobile menu
    const menuToggle = qs("menuToggle");
    const navbar = qs("navbar");
    if (menuToggle && navbar) {
      menuToggle.addEventListener("click", () => {
        navbar.classList.toggle("open");
      });
    }

    // Dropdown user
    const userDropdown = qs("userDropdown");
    if (userDropdown) {
      const btn = userDropdown.querySelector(".dropdown-btn");
      btn?.addEventListener("click", (e) => {
        e.stopPropagation();
        userDropdown.classList.toggle("open");
        btn.setAttribute("aria-expanded", userDropdown.classList.contains("open") ? "true" : "false");
      });

      document.addEventListener("click", () => {
        userDropdown.classList.remove("open");
        btn?.setAttribute("aria-expanded", "false");
      });
    }

    // Theme toggle (persist in localStorage)
    const themeToggle = qs("themeToggle");
    const root = document.documentElement;

    const saved = localStorage.getItem("bookora_theme");
    if (saved === "dark" || saved === "light") {
      root.setAttribute("data-theme", saved);
    }

    function setTheme(next) {
      root.setAttribute("data-theme", next);
      localStorage.setItem("bookora_theme", next);
      const icon = themeToggle?.querySelector("i");
      if (icon) {
        icon.className = next === "dark" ? "fas fa-sun" : "fas fa-moon";
      }
    }

    // set initial icon
    const current = root.getAttribute("data-theme") || "light";
    setTheme(current);

    themeToggle?.addEventListener("click", () => {
      const now = root.getAttribute("data-theme") || "light";
      setTheme(now === "dark" ? "light" : "dark");
    });
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
