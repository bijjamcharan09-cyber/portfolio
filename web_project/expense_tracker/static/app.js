const $ = (sel) => document.querySelector(sel);
const state = { period: "month", categories: {}, editingId: null };
const isGuest = document.body.dataset.guest === "true";
const apiBase = isGuest ? "/api/guest" : "/api";

const money = (n) => Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

async function api(path, options = {}) {
  options.credentials = "same-origin";
  const res = await fetch(apiBase + path, options);
  if (res.status === 401) {
    window.location.href = isGuest ? "/login?trial_expired=1" : "/login?next=" + encodeURIComponent(window.location.pathname);
    return null;
  }
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong");
  return data;
}

function say(text) { $("#message").textContent = text; }

function query() {
  const q = new URLSearchParams({ period: state.period, date: $("#anchor").value });
  if (state.period === "days") q.set("days", $("#days").value);
  return q.toString();
}

function fillCategories() {
  const checked = document.querySelector("input[name=type]:checked");
  if (!checked || !state.categories[checked.value]) return;
  const type = checked.value;
  $("#category").replaceChildren(...state.categories[type].map((c) => new Option(c, c)));
}

function startEdit(t) {
  state.editingId = t.id;
  const form = $("#tx-form");
  const radio = form.querySelector(`input[name=type][value="${t.type}"]`);
  if (radio) {
    radio.checked = true;
    fillCategories();
  }
  form.amount.value = t.amount;
  form.category.value = t.category;
  form.date.value = t.date;
  form.note.value = t.note || "";
  $("#add-h").textContent = "Edit transaction";
  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn.textContent = "Update transaction";

  if (!$("#btn-cancel-edit")) {
    const cancelBtn = Object.assign(document.createElement("button"), {
      type: "button",
      id: "btn-cancel-edit",
      textContent: "Cancel edit",
      className: "btn-outline",
    });
    cancelBtn.style.marginTop = "0.25rem";
    cancelBtn.addEventListener("click", cancelEdit);
    submitBtn.after(cancelBtn);
  }
}

function cancelEdit() {
  state.editingId = null;
  $("#add-h").textContent = "Add a transaction";
  const form = $("#tx-form");
  form.amount.value = "";
  form.note.value = "";
  const submitBtn = form.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.textContent = "Save transaction";
  const cancelBtn = $("#btn-cancel-edit");
  if (cancelBtn) cancelBtn.remove();
}

function renderRows(items) {
  const body = $("#rows");
  body.replaceChildren();
  $("#empty").hidden = items.length > 0;
  for (const t of items) {  // textContent (never innerHTML) keeps user text harmless
    const tr = document.createElement("tr");
    for (const text of [t.date, t.category, t.note]) {
      tr.append(Object.assign(document.createElement("td"), { textContent: text }));
    }
    const amount = Object.assign(document.createElement("td"), {
      className: "num " + t.type,
      textContent: (t.type === "expense" ? "-" : "+") + money(t.amount),
    });

    const editBtn = Object.assign(document.createElement("button"), {
      textContent: "Edit",
      type: "button",
      className: "btn-edit",
    });
    editBtn.setAttribute("aria-label", `Edit ${t.category} ${t.date}`);
    editBtn.addEventListener("click", () => startEdit(t));

    const del = Object.assign(document.createElement("button"), {
      textContent: "Delete",
      type: "button",
      className: "btn-delete",
    });
    del.setAttribute("aria-label", `Delete ${t.category} ${t.date}`);
    del.addEventListener("click", async () => {
      await api("/transactions/" + t.id, { method: "DELETE" });
      if (state.editingId === t.id) cancelEdit();
      refresh();
    });

    const last = document.createElement("td");
    last.style.whiteSpace = "nowrap";
    last.append(editBtn, del);
    tr.append(amount, last);
    body.append(tr);
  }
}

async function refresh() {
  try {
    const q = query();
    const [summary, items] = await Promise.all([api("/reports/summary?" + q), api("/transactions?" + q)]);
    if (!summary || !items) return;
    $("#income").textContent = money(summary.income);
    $("#expense").textContent = money(summary.expense);
    $("#balance").textContent = money(summary.balance);
    $("#chart").src = apiBase + "/reports/chart.png?" + q + "&_=" + Date.now();
    $("#converted").textContent = "";
    renderRows(items);
  } catch (err) { say(err.message); }
}

$("#tx-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const body = Object.fromEntries(new FormData(form));
  try {
    if (state.editingId) {
      await api("/transactions/" + state.editingId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      cancelEdit();
    } else {
      await api("/transactions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      form.amount.value = "";
      form.note.value = "";
    }
    say("");
    refresh();
  } catch (err) { say(err.message); }
});

$("#convert-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api(`/convert?to=${encodeURIComponent($("#to").value)}&${query()}`);
    if (r) {
      $("#converted").textContent = `${money(r.converted)} ${r.to} (1 ${r.base} = ${r.rate} ${r.to})`;
    }
  } catch (err) { $("#converted").textContent = err.message; }
});

$("#tabs").addEventListener("click", (e) => {
  if (!e.target.dataset.period) return;
  state.period = e.target.dataset.period;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === e.target));
  $("#days-wrap").hidden = state.period !== "days";
  refresh();
});

document.querySelectorAll("input[name=type]").forEach((r) => r.addEventListener("change", fillCategories));
$("#anchor").addEventListener("change", refresh);
$("#days").addEventListener("change", refresh);

// ============================================================================
// Excel Export & Import Handlers
// ============================================================================

$("#btn-export-excel")?.addEventListener("click", () => {
  window.location.href = `${apiBase}/excel/export?${query()}`;
});

const modal = $("#import-modal");
const fileInput = $("#excel-file");
const dropZone = $("#drop-zone");
const preview = $("#file-preview");
const previewName = $("#file-preview-name");
const importSummary = $("#import-summary");
const importForm = $("#import-form");

function openImportModal() {
  if (!modal) return;
  modal.hidden = false;
  if (importSummary) {
    importSummary.hidden = true;
    importSummary.replaceChildren();
  }
  resetFileInput();
}

function closeImportModal() {
  if (!modal) return;
  modal.hidden = true;
  resetFileInput();
}

function resetFileInput() {
  if (fileInput) fileInput.value = "";
  if (preview) preview.hidden = true;
  if (dropZone) dropZone.classList.remove("dragover");
}

$("#btn-open-import")?.addEventListener("click", openImportModal);
$("#btn-close-modal")?.addEventListener("click", closeImportModal);
$("#btn-cancel-import")?.addEventListener("click", closeImportModal);
$("#modal-backdrop")?.addEventListener("click", closeImportModal);

$("#btn-clear-file")?.addEventListener("click", (e) => {
  e.stopPropagation();
  resetFileInput();
});

$("#link-download-template")?.addEventListener("click", (e) => {
  e.preventDefault();
  window.location.href = `${apiBase}/excel/template`;
});

fileInput?.addEventListener("change", () => {
  if (fileInput.files && fileInput.files.length > 0) {
    previewName.textContent = fileInput.files[0].name;
    preview.hidden = false;
  } else {
    preview.hidden = true;
  }
});

if (dropZone) {
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", (e) => {
    const dt = e.dataTransfer;
    if (dt && dt.files.length > 0) {
      fileInput.files = dt.files;
      previewName.textContent = dt.files[0].name;
      preview.hidden = false;
    }
  });

  dropZone.addEventListener("click", (e) => {
    if (e.target.id !== "btn-clear-file") {
      fileInput.click();
    }
  });
}

function renderImportSummary(result) {
  const { success_count, rejected_count, errors } = result;
  const isErr = success_count === 0 && rejected_count > 0;
  let html = `
    <div class="summary-card ${isErr ? 'summary-card-error' : 'summary-card-success'}">
      <div class="summary-stats">
        <span class="badge badge-success">✓ ${success_count} Added</span>
        ${rejected_count > 0 ? `<span class="badge badge-warning">⚠ ${rejected_count} Rejected</span>` : ""}
      </div>
      <p class="summary-msg">${result.message || "Import completed."}</p>
  `;
  if (errors && errors.length > 0) {
    html += `
      <details class="summary-details">
        <summary>View ${errors.length} rejected row(s)</summary>
        <ul class="error-list">
          ${errors.map((e) => `<li><strong>Row ${e.row}:</strong> ${e.error}</li>`).join("")}
        </ul>
      </details>
    `;
  }
  html += `</div>`;
  importSummary.innerHTML = html;
}

importForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!fileInput.files || !fileInput.files.length) {
    alert("Please select an .xlsx file first.");
    return;
  }

  const submitBtn = $("#btn-submit-import");
  const origText = submitBtn.textContent;
  submitBtn.disabled = true;
  submitBtn.textContent = "Importing...";
  importSummary.hidden = true;

  try {
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    const res = await fetch(`${apiBase}/excel/import`, {
      method: "POST",
      credentials: "same-origin",
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "Import failed.");
    }

    importSummary.hidden = false;
    renderImportSummary(data);
    refresh();
  } catch (err) {
    importSummary.hidden = false;
    importSummary.innerHTML = `<div class="alert alert-error">${err.message}</div>`;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = origText;
  }
});

// ============================================================================
// Initialization
// ============================================================================

(async function init() {
  const today = new Date().toLocaleDateString("en-CA");  // YYYY-MM-DD in local time
  $("#anchor").value = today;
  $("#tx-date").value = today;
  state.categories = await api("/categories") || {};
  fillCategories();
  refresh();
})();
