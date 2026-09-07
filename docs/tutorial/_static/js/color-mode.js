/* Light/dark toggle for the Pepper Developer Tutorial. Filename must not
   be theme.js -- that would shadow the RTD theme's own script. */
(function () {
  function apply(theme) {
    if (theme) {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  function currentStored() {
    try {
      return localStorage.getItem("pdt-theme");
    } catch (e) {
      return null;
    }
  }

  function store(theme) {
    try {
      if (theme) {
        localStorage.setItem("pdt-theme", theme);
      } else {
        localStorage.removeItem("pdt-theme");
      }
    } catch (e) {
      /* private browsing / storage blocked: toggle still works for this
         page load, just does not persist. */
    }
  }

  apply(currentStored());

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.createElement("button");
    btn.id = "pdt-theme-toggle";
    btn.type = "button";
    btn.setAttribute("aria-label", "Toggle light/dark theme");
    btn.textContent = "Toggle theme";
    btn.addEventListener("click", function () {
      var current = document.documentElement.getAttribute("data-theme");
      var next;
      if (current === "dark") {
        next = "light";
      } else if (current === "light") {
        next = null;
      } else {
        next = "dark";
      }
      apply(next);
      store(next);
    });
    document.body.appendChild(btn);
  });
})();
