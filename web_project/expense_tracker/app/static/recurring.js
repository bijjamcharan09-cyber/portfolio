/**
 * Recurring Transactions Module
 * Handles recurring transaction CRUD, pause/resume, and processing
 */

const apiBase = document.body.dataset.guest === "true" ? "/api/guest" : "/api";
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const money = (n) => Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const moneyCents = (cents) => money(cents / 100);

function say(el, text, isError = true) {
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
  if (isError) {
    el.className = "message error";
  } else {
    el.className = "message success";
  }
}

async function api(path, options = {}) {
  options.credentials = "same-origin";
  const res = await fetch(apiBase + path, options);
  if (res.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
    return null;
  }
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong");
  return data;
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function getFrequencyLabel(freq) {
  const labels = {
    daily: "Daily",
    weekly: "Weekly",
    monthly: "Monthly",
    yearly: "Yearly"
  };
  return labels[freq] || freq;
}

function getStatusBadge(isActive, isPaused) {
  if (!isActive) return '<span class="status-badge status-inactive">Inactive</span>';
  if (isPaused) return '<span class="status-badge status-paused">Paused</span>';
  return '<span class="status-badge status-active">Active</span>';
}

function renderRecurringCard(rt) {
  const nextDue = formatDate(rt.next_due_date);
  const startDate = formatDate(rt.start_date);
  const endDate = rt.end_date ? formatDate(rt.end_date) : "No end date";
  const statusBadge = getStatusBadge(rt.is_active, rt.is_paused);

  return `
    <article class="recurring-card" data-id="${rt.id}">
      <div class="recurring-header">
        <div class="recurring-title-row">
          <h4 class="recurring-category">${rt.category}</h4>
          <span class="recurring-type ${rt.type}">${rt.type === "income" ? "+" : "−"}${moneyCents(rt.amount_cents)}</span>
        </div>
        <div class="recurring-meta">
          <span class="recurring-frequency">${getFrequencyLabel(rt.frequency)}</span>
          ${statusBadge}
        </div>
      </div>

      <div class="recurring-details">
        <div class="detail-row">
          <span class="detail-label">Next Due</span>
          <span class="detail-value next-due">${nextDue}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Started</span>
          <span class="detail-value">${startDate}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Ends</span>
          <span class="detail-value">${endDate}</span>
        </div>
        ${rt.note ? `<div class="detail-row"><span class="detail-label">Note</span><span class="detail-value">${rt.note}</span></div>` : ""}
        ${rt.payment_method ? `<div class="detail-row"><span class="detail-label">Payment</span><span class="detail-value">${rt.payment_method}</span></div>` : ""}
      </div>

      <div class="recurring-actions">
        ${rt.is_active && !rt.is_paused ? `
          <button type="button" class="btn-sm btn-outline btn-pause" data-id="${rt.id}" aria-label="Pause ${rt.category}">Pause</button>
        ` : rt.is_paused ? `
          <button type="button" class="btn-sm btn-primary btn-resume" data-id="${rt.id}" aria-label="Resume ${rt.category}">Resume</button>
        ` : ''}
        <button type="button" class="btn-sm btn-outline btn-edit" data-id="${rt.id}" aria-label="Edit ${rt.category}">Edit</button>
        <button type="button" class="btn-sm btn-danger btn-delete" data-id="${rt.id}" aria-label="Delete ${rt.category}">Delete</button>
      </div>
    </article>
  `;
}

async function loadRecurring() {
  try {
    const recurring = await api("/recurring");
    if (!recurring) return;

    const container = $("#recurring-container");
    const empty = $("#recurring-empty");

    if (recurring.length === 0) {
      container.hidden = true;
      empty.hidden = false;
      return;
    }

    empty.hidden = true;
    container.hidden = false;
    container.innerHTML = recurring.map(renderRecurringCard).join("");
    attachRecurringEventListeners();
  } catch (err) {
    say($("#recurring-message"), err.message);
  }
}

function attachRecurringEventListeners() {
  // Pause buttons
  $$(".btn-pause").forEach(btn => {
    btn.addEventListener("click", () => pauseRecurring(btn.dataset.id));
  });

  // Resume buttons
  $$(".btn-resume").forEach(btn => {
    btn.addEventListener("click", () => resumeRecurring(btn.dataset.id));
  });

  // Edit buttons
  $$(".btn-edit").forEach(btn => {
    btn.addEventListener("click", () => openRecurringModal(btn.dataset.id));
  });

  // Delete buttons
  $$(".btn-delete").forEach(btn => {
    btn.addEventListener("click", () => deleteRecurring(btn.dataset.id));
  });
}

function openRecurringModal(recurringId = null) {
  const isEdit = !!recurringId;
  $("#recurring-form").reset();
  $("#recurring-id").value = recurringId || "";
  $("#recurring-modal-title").textContent = isEdit ? "Edit Recurring Transaction" : "Create Recurring Transaction";
  $("#btn-submit-recurring").textContent = isEdit ? "Update" : "Create";

  // Set default start date to today
  if (!isEdit) {
    $("#recurring-start").value = new Date().toLocaleDateString("en-CA");
  }

  if (isEdit) {
    loadRecurringForEdit(recurringId);
  }

  $("#recurring-modal").hidden = false;
}

async function loadRecurringForEdit(rtId) {
  try {
    const rt = await api(`/recurring/${rtId}`);
    if (!rt) return;

    $("#recurring-type").value = rt.type;
    $("#recurring-amount").value = (rt.amount_cents / 100).toFixed(2);
    $("#recurring-category").value = rt.category;
    $("#recurring-frequency").value = rt.frequency;
    $("#recurring-note").value = rt.note || "";
    $("#recurring-payment").value = rt.payment_method || "";
    $("#recurring-start").value = rt.start_date;
    $("#recurring-end").value = rt.end_date || "";
  } catch (err) {
    say($("#recurring-message"), err.message);
  }
}

function closeRecurringModal() {
  $("#recurring-modal").hidden = true;
  $("#recurring-form").reset();
}

async function submitRecurring(e) {
  e.preventDefault();
  const form = e.target;
  const rtId = $("#recurring-id").value;
  const isEdit = !!rtId;

  const data = {
    type: $("#recurring-type").value,
    amount_cents: Math.round(parseFloat($("#recurring-amount").value) * 100),
    category: $("#recurring-category").value,
    frequency: $("#recurring-frequency").value,
    note: $("#recurring-note").value.trim(),
    payment_method: $("#recurring-payment").value,
    start_date: $("#recurring-start").value,
    end_date: $("#recurring-end").value || null
  };

  try {
    if (isEdit) {
      await api(`/recurring/${rtId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      say($("#recurring-message"), "Recurring transaction updated successfully", false);
    } else {
      await api("/recurring", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      say($("#recurring-message"), "Recurring transaction created successfully", false);
    }
    closeRecurringModal();
    loadRecurring();
  } catch (err) {
    say($("#recurring-message"), err.message);
  }
}

async function pauseRecurring(rtId) {
  try {
    await api(`/recurring/${rtId}/pause`, { method: "POST" });
    say($("#recurring-message"), "Recurring transaction paused", false);
    loadRecurring();
  } catch (err) {
    say($("#recurring-message"), err.message);
  }
}

async function resumeRecurring(rtId) {
  try {
    await api(`/recurring/${rtId}/resume`, { method: "POST" });
    say($("#recurring-message"), "Recurring transaction resumed", false);
    loadRecurring();
  } catch (err) {
    say($("#recurring-message"), err.message);
  }
}

async function deleteRecurring(rtId) {
  if (!confirm("Are you sure you want to delete this recurring transaction? This action cannot be undone.")) return;

  try {
    await api(`/recurring/${rtId}`, { method: "DELETE" });
    say($("#recurring-message"), "Recurring transaction deleted successfully", false);
    loadRecurring();
  } catch (err) {
    say($("#recurring-message"), err.message);
  }
}

async function processRecurring() {
  const btn = $("#btn-process-recurring");
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Processing...";

  try {
    const result = await api("/recurring/process", { method: "POST" });
    if (result) {
      say($("#recurring-message"), `Generated ${result.count} transaction(s)`, false);
      loadRecurring();
    }
  } catch (err) {
    say($("#recurring-message"), err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  // New recurring button
  $("#btn-new-recurring")?.addEventListener("click", () => openRecurringModal());
  $("#btn-first-recurring")?.addEventListener("click", () => openRecurringModal());

  // Form submission
  $("#recurring-form")?.addEventListener("submit", submitRecurring);

  // Close buttons
  $("#btn-close-recurring-modal")?.addEventListener("click", closeRecurringModal);
  $("#btn-cancel-recurring")?.addEventListener("click", closeRecurringModal);
  $("#recurring-modal-backdrop")?.addEventListener("click", closeRecurringModal);

  // Process button
  $("#btn-process-recurring")?.addEventListener("click", processRecurring);

  // Initial load
  loadRecurring();
});