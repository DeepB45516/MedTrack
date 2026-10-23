// MedTrack — Performance-optimized progressive-enhancement helpers

document.addEventListener("DOMContentLoaded", () => {
  // Confirm before destructive actions (e.g. cancel appointment).
  document.querySelectorAll("[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const msg = form.getAttribute("data-confirm");
      if (msg && !window.confirm(msg)) {
        e.preventDefault();
      }
    });
  });

  // Prevent duplicate submissions and rapid repeated execution
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (e.defaultPrevented) return;
      if (form.hasAttribute("data-submitting")) {
        e.preventDefault();
        return;
      }
      const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
      if (submitBtn) {
        form.setAttribute("data-submitting", "true");
        // Re-enable after 5s safety timeout
        setTimeout(() => {
          form.removeAttribute("data-submitting");
        }, 5000);
      }
    });
  });

  // Auto-dismiss flash alerts smoothly
  document.querySelectorAll(".mt-alert").forEach((alertEl) => {
    setTimeout(() => {
      alertEl.style.transition = "opacity 0.3s ease";
      alertEl.style.opacity = "0";
      setTimeout(() => alertEl.remove(), 300);
    }, 4500);
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

  // Live date display for dashboard headers
  const dateElements = document.querySelectorAll(".mt-live-date");
  if (dateElements.length > 0) {
    const now = new Date();
    const options = { weekday: "short", month: "short", day: "numeric", year: "numeric" };
    const formattedDate = now.toLocaleDateString("en-US", options);
    dateElements.forEach((el) => {
      el.textContent = formattedDate;
    });
  }

  // Interactive client-side table search filter (debounced with requestAnimationFrame)
  document.querySelectorAll("[data-table-filter]").forEach((input) => {
    let rafId = null;
    input.addEventListener("input", () => {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        const targetSelector = input.getAttribute("data-table-filter");
        const targetTable = document.querySelector(targetSelector);
        if (!targetTable) return;

        const filterVal = input.value.toLowerCase().trim();
        const rows = targetTable.querySelectorAll("tbody tr");

        rows.forEach((row) => {
          const text = row.textContent.toLowerCase();
          row.style.display = text.includes(filterVal) ? "" : "none";
        });
      });
    });
  });

  // Direct File-Preview Cleaner & Resolver (runs when double-clicked in File Explorer)
  if (window.location.protocol === "file:") {
    document.querySelectorAll("img").forEach((img) => {
      const src = img.getAttribute("src") || "";
      if (src.includes("url_for") || src.startsWith("{{")) {
        const match = src.match(/filename=['"]([^'"]+)['"]/);
        if (match) {
          img.src = "../static/" + match[1];
        }
      }
    });

    document.querySelectorAll("a").forEach((a) => {
      const href = a.getAttribute("href") || "";
      if (href.includes("url_for") || href.startsWith("{{")) {
        if (href.includes("login")) a.href = "login.html";
        else if (href.includes("signup")) a.href = "signup.html";
        else if (href.includes("index")) a.href = "index.html";
        else if (href.includes("book_appointment")) a.href = "book_appointment.html";
        else if (href.includes("patient_dashboard")) a.href = "patient_dashboard.html";
        else if (href.includes("doctor_dashboard")) a.href = "doctor_dashboard.html";
        else if (href.includes("admin_dashboard") || href.includes("admin_")) a.href = "admin_dashboard.html";
        else if (href.includes("appointments")) a.href = "appointments.html";
        else if (href.includes("diagnosis_history")) a.href = "diagnosis_history.html";
        else if (href.includes("submit_diagnosis")) a.href = "submit_diagnosis.html";
        else if (href.includes("profile")) a.href = "profile.html";
        else if (href.includes("search")) a.href = "search_results.html";
        else if (href.includes("notifications")) a.href = "notifications.html";
        else a.href = "#";
      }
    });

    const walker = document.createTreeWalker(
      document.body || document.documentElement,
      NodeFilter.SHOW_TEXT,
      null,
      false
    );
    const nodesToClean = [];
    let textNode;
    while ((textNode = walker.nextNode())) {
      if (
        textNode.nodeValue &&
        (textNode.nodeValue.includes("{%") ||
          textNode.nodeValue.includes("{{") ||
          textNode.nodeValue.includes("%}") ||
          textNode.nodeValue.includes("}}"))
      ) {
        nodesToClean.push(textNode);
      }
    }
    nodesToClean.forEach((n) => {
      n.nodeValue = n.nodeValue
        .replace(/\{%[\s\S]*?%\}/g, "")
        .replace(/\{\{[\s\S]*?\}\}/g, "")
        .trim();
      if (!n.nodeValue && n.parentNode && n.parentNode.childNodes.length === 1) {
        n.parentNode.style.display = "none";
      }
    });
  }
});
