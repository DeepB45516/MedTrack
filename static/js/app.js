// MedTrack — small progressive-enhancement helpers (no framework needed
// for the current local phase).

document.addEventListener("DOMContentLoaded", () => {
  // Confirm before destructive actions (cancel appointment).
  document.querySelectorAll("[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const msg = form.getAttribute("data-confirm");
      if (msg && !window.confirm(msg)) {
        e.preventDefault();
      }
    });
  });

  // Auto-dismiss flash alerts after a few seconds.
  document.querySelectorAll(".mt-alert").forEach((alertEl) => {
    setTimeout(() => {
      alertEl.style.transition = "opacity 0.4s ease";
      alertEl.style.opacity = "0";
      setTimeout(() => alertEl.remove(), 400);
    }, 5000);
  });

  // Mobile navigation drawer toggle
  const mobileToggle = document.getElementById("mtMobileMenuBtn");
  const sidebar = document.querySelector(".mt-sidebar");
  const backdrop = document.getElementById("mtSidebarBackdrop");
  const closeBtn = document.getElementById("mtSidebarCloseBtn");

  function openSidebar() {
    if (sidebar) sidebar.classList.add("open");
    if (backdrop) backdrop.classList.add("active");
    document.body.style.overflow = "hidden";
  }

  function closeSidebar() {
    if (sidebar) sidebar.classList.remove("open");
    if (backdrop) backdrop.classList.remove("active");
    document.body.style.overflow = "";
  }

  if (mobileToggle) {
    mobileToggle.addEventListener("click", openSidebar);
  }
  if (closeBtn) {
    closeBtn.addEventListener("click", closeSidebar);
  }
  if (backdrop) {
    backdrop.addEventListener("click", closeSidebar);
  }

  // Close sidebar on navigation click on mobile
  document.querySelectorAll(".mt-sidebar .mt-nav a").forEach((link) => {
    link.addEventListener("click", () => {
      if (window.innerWidth <= 960) {
        closeSidebar();
      }
    });
  });

  // Public navbar mobile menu toggle
  const publicHamburger = document.getElementById("mtSocietyHamburger");
  const publicMenu = document.getElementById("mtSocietyMobileMenu");

  if (publicHamburger && publicMenu) {
    publicHamburger.addEventListener("click", () => {
      publicMenu.classList.toggle("show");
    });

    publicMenu.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        publicMenu.classList.remove("show");
      });
    });
  }
});
