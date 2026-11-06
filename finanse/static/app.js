"use strict";

document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

function parseNumber(text) {
  const cleaned = text.replace(/\s/g, "").replace(",", ".");
  return /^[0-9]+(\.[0-9]+)?$/.test(cleaned) ? Number(cleaned) : 0;
}

function setupProductForm() {
  const rows = document.querySelector("[data-product-rows]");
  if (!rows) return;

  const template = document.querySelector("[data-product-template]");
  const total = document.querySelector("[data-total]");
  const formatter = new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  function updateTotal() {
    let cents = 0;
    rows.querySelectorAll("[data-product-row]").forEach((row) => {
      const milli = Math.round(parseNumber(row.querySelector("[data-quantity]").value) * 1000);
      const price = Math.round(parseNumber(row.querySelector("[data-price]").value) * 100);
      cents += Math.floor((milli * price + 500) / 1000);
    });
    total.textContent = `${formatter.format(cents / 100)} ${total.dataset.currency}`;
  }

  document.querySelector("[data-add-row]").addEventListener("click", () => {
    rows.append(template.content.cloneNode(true));
    rows.lastElementChild.querySelector("input").focus();
    updateTotal();
  });

  rows.addEventListener("click", (event) => {
    if (!event.target.matches("[data-remove-row]")) return;
    const row = event.target.closest("[data-product-row]");
    if (rows.children.length > 1) {
      row.remove();
    } else {
      row.querySelector("[data-quantity]").value = "1";
      row.querySelector("[data-price]").value = "";
      row.querySelector("input").value = "";
      row.querySelector("select").value = "";
    }
    updateTotal();
  });

  rows.addEventListener("input", updateTotal);
  updateTotal();
}

function setupTooltips() {
  if (!document.querySelector("[data-tip]")) return;

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip";
  tooltip.hidden = true;
  document.body.append(tooltip);

  function show(target) {
    tooltip.textContent = target.dataset.tip;
    tooltip.hidden = false;
    const box = target.getBoundingClientRect();
    const width = tooltip.offsetWidth;
    const left = Math.min(
      Math.max(8, box.left + box.width / 2 - width / 2),
      document.documentElement.clientWidth - width - 8,
    );
    const above = box.top - tooltip.offsetHeight - 8;
    tooltip.style.left = `${left + window.scrollX}px`;
    tooltip.style.top = `${(above >= 0 ? above : box.bottom + 8) + window.scrollY}px`;
  }

  function hide() {
    tooltip.hidden = true;
  }

  for (const [showEvent, hideEvent] of [["pointerover", "pointerout"], ["focusin", "focusout"]]) {
    document.addEventListener(showEvent, (event) => {
      const target = event.target.closest("[data-tip]");
      if (target) show(target);
    });
    document.addEventListener(hideEvent, hide);
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hide();
  });
}

setupProductForm();
setupTooltips();
