/* The navigation is built here so that every page keeps one list of links.
   A page declares which one it is with <body data-page="methodology">. */

(function () {
  "use strict";

  var GROUPS = [
    {
      title: "Getting started",
      pages: [
        { id: "index", label: "Overview", href: "index.html" },
        { id: "quickstart", label: "Quick start", href: "quickstart.html" },
        { id: "interface", label: "The interface", href: "interface.html" }
      ]
    },
    {
      title: "The model",
      pages: [
        { id: "methodology", label: "Methodology", href: "methodology.html" },
        { id: "sensitivity", label: "Sensitivity (WACC x g)", href: "sensitivity.html" },
        { id: "analyst", label: "The analyst fallback", href: "analyst.html" }
      ]
    },
    {
      title: "Reference",
      pages: [
        { id: "api", label: "API", href: "api.html" },
        { id: "architecture", label: "Architecture", href: "architecture.html" },
        { id: "limits", label: "What it cannot do", href: "limits.html" }
      ]
    }
  ];

  var current = document.body.getAttribute("data-page") || "index";

  function build() {
    var sidebar = document.getElementById("sidebar");
    if (!sidebar) return;

    GROUPS.forEach(function (group) {
      var heading = document.createElement("h2");
      heading.textContent = group.title;
      sidebar.appendChild(heading);

      var list = document.createElement("ul");
      group.pages.forEach(function (page) {
        var item = document.createElement("li");
        var link = document.createElement("a");
        link.href = page.href;
        link.textContent = page.label;
        if (page.id === current) {
          link.className = "current";
          link.setAttribute("aria-current", "page");
        }
        item.appendChild(link);
        list.appendChild(item);
      });
      sidebar.appendChild(list);
    });
  }

  function markVersion() {
    var node = document.getElementById("version");
    if (node) node.textContent = "v" + (window.WIKI_VERSION || "1.0.0");
  }

  function wireMenu() {
    var button = document.getElementById("menu");
    var sidebar = document.getElementById("sidebar");
    if (!button || !sidebar) return;
    button.addEventListener("click", function () {
      sidebar.classList.toggle("open");
    });
  }

  build();
  markVersion();
  wireMenu();
})();
