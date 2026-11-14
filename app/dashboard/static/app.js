(() => {
  "use strict";

  // Подтверждение опасных действий и динамические строки форм.
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

  // Мультивыбор каналов и ролей с поиском и чипами.
  function initPicker(picker) {
    const trigger = picker.querySelector("[data-picker-trigger]");
    const menu = picker.querySelector("[data-picker-menu]");
    const search = picker.querySelector("[data-picker-search]");
    const summary = picker.querySelector("[data-picker-summary]");
    const count = picker.querySelector("[data-picker-count]");
    const selectedBox = picker.querySelector("[data-picker-selected]");
    const noResults = picker.querySelector("[data-picker-no-results]");
    const options = Array.from(picker.querySelectorAll("[data-picker-option]"));
    const maxItems = Number(picker.dataset.pickerMax || 0);
    if (!trigger || !menu) return;

    const boxes = () => Array.from(picker.querySelectorAll('input[type="checkbox"][name]'));

    function optionLabel(box) {
      const option = box.closest("[data-picker-option]");
      return option?.dataset.label || box.value;
    }

    function render() {
      const checked = boxes().filter((box) => box.checked);
      if (summary) {
        summary.textContent =
          checked.length === 0
            ? "Не выбрано"
            : checked.length === 1
              ? optionLabel(checked[0])
              : `Выбрано: ${checked.length}`;
      }
      if (count) {
        count.textContent = String(checked.length);
        count.hidden = checked.length === 0;
      }
      picker.classList.toggle("has-value", checked.length > 0);

      if (!selectedBox) return;
      selectedBox.innerHTML = "";
      checked.forEach((box) => {
        const option = box.closest("[data-picker-option]");
        const chip = document.createElement("span");
        chip.className = "picker-chip";

        if (option?.dataset.color) {
          const dot = document.createElement("span");
          dot.className = "picker-chip-dot";
          dot.style.background = option.dataset.color;
          chip.appendChild(dot);
        }

        const label = document.createElement("span");
        label.textContent = optionLabel(box);
        chip.appendChild(label);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.setAttribute("aria-label", `Убрать ${optionLabel(box)}`);
        remove.innerHTML = "&times;";
        remove.addEventListener("click", () => {
          box.checked = false;
          render();
        });
        chip.appendChild(remove);
        selectedBox.appendChild(chip);
      });
    }

    function setOpen(next) {
      picker.classList.toggle("open", next);
      menu.hidden = !next;
      trigger.setAttribute("aria-expanded", String(next));
    }

    function applyFilter() {
      const query = (search?.value || "").trim().toLowerCase();
      let visible = 0;
      options.forEach((option) => {
        const matches = !query || (option.dataset.name || "").includes(query);
        option.hidden = !matches;
        if (matches) visible += 1;
      });
      if (noResults) noResults.hidden = visible !== 0;
    }

    trigger.addEventListener("click", () => {
      const next = !picker.classList.contains("open");
      setOpen(next);
      if (next) {
        applyFilter();
        search?.focus();
      }
    });

    search?.addEventListener("input", applyFilter);
    search?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });

    picker.addEventListener("change", (event) => {
      if (!event.target.matches('input[type="checkbox"][name]')) return;
      if (maxItems > 0 && event.target.checked) {
        const selected = boxes().filter((box) => box.checked);
        if (selected.length > maxItems) event.target.checked = false;
      }
      render();
    });

    picker.querySelector("[data-picker-select-all]")?.addEventListener("click", () => {
      let selected = boxes().filter((box) => box.checked).length;
      options.forEach((option) => {
        if (option.hidden) return;
        const box = option.querySelector('input[type="checkbox"]');
        if (box && !box.checked && (maxItems === 0 || selected < maxItems)) {
          box.checked = true;
          selected += 1;
        }
      });
      render();
    });

    picker.querySelector("[data-picker-clear]")?.addEventListener("click", () => {
      boxes().forEach((box) => {
        box.checked = false;
      });
      render();
    });

    document.addEventListener("click", (event) => {
      if (!picker.contains(event.target)) setOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && picker.classList.contains("open")) {
        setOpen(false);
        trigger.focus();
      }
    });

    render();
  }

  document.querySelectorAll("[data-picker]").forEach(initPicker);

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
