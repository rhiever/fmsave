// Sets the colour theme before the page paints. It follows the system setting until the
// toggle picks one, and that choice is remembered in this browser only.
(function () {
  var root = document.documentElement;
  var system = window.matchMedia("(prefers-color-scheme: dark)");
  var chosen = null;
  try { chosen = localStorage.getItem("fmsave-theme"); } catch (e) { chosen = null; }
  function apply() { root.setAttribute("data-theme", chosen || (system.matches ? "dark" : "light")); }
  apply();
  system.addEventListener("change", function () { if (!chosen) apply(); });
  window.fmsaveTheme = {
    toggle: function () {
      chosen = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      try { localStorage.setItem("fmsave-theme", chosen); } catch (e) { /* storage blocked */ }
      apply();
      return chosen;
    },
    current: function () { return root.getAttribute("data-theme"); },
  };
})();
