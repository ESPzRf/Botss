(() => {
  "use strict";

  // Подтверждение опасных действий.
  document.addEventListener("click", (event) => {
    const confirmButton = event.target.closest("[data-confirm]");
    if (confirmButton && !window.confirm(confirmButton.dataset.confirm || "Вы уверены?")) {
      event.preventDefault();
      return;
    }

    const addEscalation = event.target.closest("[data-add-escalation]");
    if (addEscalation) {
      const template = document.getElementById("esc-template");
      const list = document.getElementById("esc-list");
      if (template && list) {
        list.appendChild(template.content.cloneNode(true));
      }
      return;
    }

    const addLevelRole = event.target.closest("[data-add-level-role]");
    if (addLevelRole) {
      const template = document.getElementById("lr-template");
      const list = document.getElementById("lr-list");
      if (template && list) {
        list.appendChild(template.content.cloneNode(true));
      }
      return;
    }

    const removeButton = event.target.closest("[data-remove-row]");
    if (removeButton) {
      const row = removeButton.closest(".esc-row, .lr-row");
      if (row) {
        row.remove();
      }
    }
  });

  // Поиск по списку ролей.
  document.querySelectorAll("[data-role-search]").forEach((input) => {
    const list = document.querySelector(input.dataset.roleSearch);
    if (!list) return;
    input.addEventListener("input", () => {
      const query = input.value.trim().toLowerCase();
      list.querySelectorAll(".role-option").forEach((option) => {
        const name = (option.dataset.name || "").toLowerCase();
        option.style.display = !query || name.includes(query) ? "" : "none";
      });
    });
  });

  // Показываем даты в часовом поясе браузера.
  document.querySelectorAll("time[data-local]").forEach((element) => {
    const value = element.getAttribute("datetime");
    if (!value) return;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return;
    element.textContent = date.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    element.title = date.toLocaleString("ru-RU");
  });
})();
