/**
 * Budget Management Module
 * Handles budget CRUD operations, utilization display, and notifications
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

function getUtilizationClass(pct) {
  if (pct >= 100) return "util-danger";
  if (pct >= 80) return "util-warning";
  return "util-ok";
}

function createProgressBar(pct, budgetName) {
  const clampedPct = Math.min(Math.max(pct, 0), 100);
  const cls = getUtilizationClass(pct);
  return `
    <div class="progress-bar-wrapper" role="progressbar" aria-valuenow="${pct.toFixed(1)}" aria-valuemin="0" aria-valuemax="100" aria-label="${budgetName} budget utilization">
      <div class="progress-bar ${cls}" style="width: ${clampedPct}%"></div>
    </div>
    <span class="progress-label ${cls}">${pct.toFixed(1)}%</span>
  `;
}

function renderBudgetCard(budget, utilization) {
  const isExceeded = utilization.is_exceeded;
  const isWarning = utilization.is_warning && !isExceeded;
  const statusClass = isExceeded ? "status-exceeded" : isWarning ? "status-warning" : "status-ok";
  const statusText = isExceeded ? "Exceeded" : isWarning ? "Warning" : "On Track";
  const statusIcon = isExceeded ? "⚠️" : isWarning ? "⚡" : "✅";

  const spent = moneyCents(utilization.spent_cents);
  const budgetAmt = moneyCents(utilization.budget_amount_cents);
  const remaining = moneyCents(Math.max(utilization.budget_amount_cents - utilization.spent_cents, 0));

  return `
    <article class="budget-card ${statusClass}" data-id="${budget.id}">
      <div class="budget-header">
        <div class="budget-title-row">
          <h4 class="budget-name">${budget.name}</h4>
          <span class="budget-badge ${statusClass}">${statusIcon} ${statusText}</span>
        </div>
        <div class="budget-meta">
          <span class="budget-period">${budget.period.charAt(0).toUpperCase() + budget.period.slice(1)}</span>
          ${budget.category ? `<span class="budget-category">${budget.category}</span>` : `<span class="budget-category overall">Overall</span>`}
        </div>
      </div>

      <div class="budget-progress">
        ${createProgressBar(utilization.utilization_pct, budget.name)}
      </div>

      <div class="budget-amounts">
        <div class="budget-amount">
          <span class="budget-amount-label">Spent</span>
          <span class="budget-amount-value expense">${spent}</span>
        </div>
        <div class="budget-amount">
          <span class="budget-amount-label">Budget</span>
          <span class="budget-amount-value">${budgetAmt}</span>
        </div>
        <div class="budget-amount">
          <span class="budget-amount-label">Remaining</span>
          <span class="budget-amount-value income">${remaining}</span>
        </div>
      </div>

      <div class="budget-dates">
        <span>From: ${formatDate(budget.start_date)}</span>
        ${budget.end_date ? `<span>To: ${formatDate(budget.end_date)}</span>` : `<span class="ongoing">Ongoing</span>`}
      </div>

      <div class="budget-actions">
        <button type="button" class="btn-sm btn-outline btn-view" data-id="${budget.id}" aria-label="View details for ${budget.name}">View</button>
        <button type="button" class="btn-sm btn-outline btn-edit" data-id="${budget.id}" aria-label="Edit ${budget.name}">Edit</button>
        <button type="button" class="btn-sm btn-danger btn-delete" data-id="${budget.id}" aria-label="Delete ${budget.name}">Delete</button>
      </div>
    </article>
  `;
}

function updateBudgetOverview(utilizations) {
  const totalBudgeted = utilizations.reduce((sum, u) => sum + u.budget_amount_cents, 0);
  const totalSpent = utilizations.reduce((sum, u) => sum + u.spent_cents, 0);
  const activeCount = utilizations.length;

  $("#total-budgeted").textContent = moneyCents(totalBudgeted);
  $("#total-spent").textContent = moneyCents(totalSpent);
  $("#total-remaining").textContent = moneyCents(Math.max(totalBudgeted - totalSpent, 0));
  $("#active-budgets-count").textContent = activeCount;
  $("#budget-overview").hidden = false;
}

async function loadBudgets() {
  try {
    const [budgets, utilizations] = await Promise.all([
      api("/budgets"),
      api("/budgets/utilization")
    ]);

    if (!budgets || !utilizations) return;

    const container = $("#budgets-container");
    const empty = $("#budgets-empty");

    if (budgets.length === 0) {
      container.hidden = true;
      empty.hidden = false;
      $("#budget-overview").hidden = true;
      return;
    }

    empty.hidden = true;
    container.hidden = false;

    // Create utilization lookup
    const utilMap = {};
    utilizations.forEach(u => { utilMap[u.budget_id] = u; });

    container.innerHTML = budgets.map(b => renderBudgetCard(b, utilMap[b.id] || {
      spent_cents: 0,
      budget_amount_cents: b.amount_cents,
      utilization_pct: 0,
      is_warning: false,
      is_exceeded: false
    })).join("");

    updateBudgetOverview(utilizations);
    attachBudgetEventListeners();
  } catch (err) {
    say($("#budget-message"), err.message);
  }
}

function attachBudgetEventListeners() {
  // View buttons
  $$(".btn-view").forEach(btn => {
    btn.addEventListener("click", () => openBudgetDetail(btn.dataset.id));
  });

  // Edit buttons
  $$(".btn-edit").forEach(btn => {
    btn.addEventListener("click", () => openBudgetModal(btn.dataset.id));
  });

  // Delete buttons
  $$(".btn-delete").forEach(btn => {
    btn.addEventListener("click", () => deleteBudget(btn.dataset.id));
  });
}

async function openBudgetDetail(budgetId) {
  try {
    const [budget, utilization] = await Promise.all([
      api(`/budgets/${budgetId}`),
      api(`/budgets/utilization`)
    ]);

    if (!budget || !utilization) return;

    const util = utilization.find(u => u.budget_id === budgetId) || {
      spent_cents: 0,
      budget_amount_cents: budget.amount_cents,
      utilization_pct: 0,
      is_warning: false,
      is_exceeded: false
    };

    const isExceeded = util.is_exceeded;
    const isWarning = util.is_warning && !isExceeded;
    const statusClass = isExceeded ? "status-exceeded" : isWarning ? "status-warning" : "status-ok";
    const statusText = isExceeded ? "Exceeded" : isWarning ? "Warning" : "On Track";

    const detailBody = $("#budget-detail-body");
    detailBody.innerHTML = `
      <div class="budget-detail">
        <div class="budget-detail-header ${statusClass}">
          <h4>${budget.name}</h4>
          <span class="detail-badge ${statusClass}">${statusText}</span>
        </div>

        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-label">Period</span>
            <span class="detail-value">${budget.period.charAt(0).toUpperCase() + budget.period.slice(1)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Category</span>
            <span class="detail-value">${budget.category || "Overall (all categories)"}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Warning Threshold</span>
            <span class="detail-value">${budget.warning_threshold}%</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Status</span>
            <span class="detail-value">${budget.is_active ? "Active" : "Inactive"}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Start Date</span>
            <span class="detail-value">${formatDate(budget.start_date)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">End Date</span>
            <span class="detail-value">${budget.end_date ? formatDate(budget.end_date) : "Ongoing"}</span>
          </div>
        </div>

        <div class="detail-progress">
          <h5>Current Period Utilization</h5>
          ${createProgressBar(util.utilization_pct, budget.name)}
        </div>

        <div class="detail-amounts">
          <div class="detail-amount">
            <span class="detail-amount-label">Amount Spent</span>
            <span class="detail-amount-value expense">${moneyCents(util.spent_cents)}</span>
          </div>
          <div class="detail-amount">
            <span class="detail-amount-label">Budget Amount</span>
            <span class="detail-amount-value">${moneyCents(util.budget_amount_cents)}</span>
          </div>
          <div class="detail-amount">
            <span class="detail-amount-label">Remaining</span>
            <span class="detail-amount-value income">${moneyCents(Math.max(util.budget_amount_cents - util.spent_cents, 0))}</span>
          </div>
        </div>

        ${isExceeded ? `<div class="alert alert-error">You have exceeded your budget by ${moneyCents(util.spent_cents - util.budget_amount_cents)}</div>` : ""}
        ${isWarning && !isExceeded ? `<div class="alert alert-warning">You have used ${util.utilization_pct.toFixed(1)}% of your budget (threshold: ${budget.warning_threshold}%)</div>` : ""}
      </div>
    `;

    $("#budget-detail-modal").hidden = false;
  } catch (err) {
    say($("#budget-message"), err.message);
  }
}

function openBudgetModal(budgetId = null) {
  const isEdit = !!budgetId;
  $("#budget-form").reset();
  $("#budget-id").value = budgetId || "";
  $("#budget-modal-title").textContent = isEdit ? "Edit Budget" : "Create Budget";
  $("#btn-submit-budget").textContent = isEdit ? "Update Budget" : "Create Budget";

  // Populate categories
  populateCategorySelect($("#budget-category"));

  if (isEdit) {
    loadBudgetForEdit(budgetId);
  } else {
    // Set default start date to today
    $("#budget-start").value = new Date().toLocaleDateString("en-CA");
  }

  $("#budget-modal").hidden = false;
}

async function loadBudgetForEdit(budgetId) {
  try {
    const budget = await api(`/budgets/${budgetId}`);
    if (!budget) return;

    $("#budget-name").value = budget.name;
    $("#budget-period").value = budget.period;
    $("#budget-category").value = budget.category || "";
    $("#budget-amount").value = (budget.amount_cents / 100).toFixed(2);
    $("#budget-warning").value = budget.warning_threshold;
    $("#budget-start").value = budget.start_date;
    $("#budget-end").value = budget.end_date || "";
  } catch (err) {
    say($("#budget-message"), err.message);
  }
}

function populateCategorySelect(selectEl) {
  // Categories will be loaded from the existing categories API
  // For now, we'll use common categories
  const categories = [
    "Housing", "Food & Dining", "Transportation", "Utilities",
    "Healthcare", "Entertainment", "Shopping", "Education",
    "Personal Care", "Gifts & Donations", "Investments", "Other"
  ];

  const currentValue = selectEl.value;
  selectEl.innerHTML = '<option value="">Overall (all categories)</option>' +
    categories.map(c => `<option value="${c}">${c}</option>`).join("");
  selectEl.value = currentValue;
}

function closeBudgetModal() {
  $("#budget-modal").hidden = true;
  $("#budget-form").reset();
}

function closeDetailModal() {
  $("#budget-detail-modal").hidden = true;
}

async function submitBudget(e) {
  e.preventDefault();
  const form = e.target;
  const budgetId = $("#budget-id").value;
  const isEdit = !!budgetId;

  const data = {
    name: $("#budget-name").value.trim(),
    period: $("#budget-period").value,
    category: $("#budget-category").value || null,
    amount_cents: Math.round(parseFloat($("#budget-amount").value) * 100),
    warning_threshold: parseInt($("#budget-warning").value) || 80,
    start_date: $("#budget-start").value,
    end_date: $("#budget-end").value || null
  };

  try {
    if (isEdit) {
      await api(`/budgets/${budgetId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      say($("#budget-message"), "Budget updated successfully", false);
    } else {
      await api("/budgets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      say($("#budget-message"), "Budget created successfully", false);
    }
    closeBudgetModal();
    loadBudgets();
  } catch (err) {
    say($("#budget-message"), err.message);
  }
}

async function deleteBudget(budgetId) {
  if (!confirm("Are you sure you want to delete this budget? This action cannot be undone.")) return;

  try {
    await api(`/budgets/${budgetId}`, { method: "DELETE" });
    say($("#budget-message"), "Budget deleted successfully", false);
    loadBudgets();
  } catch (err) {
    say($("#budget-message"), err.message);
  }
}

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  // Load categories for selects
  populateCategorySelect($("#budget-category"));
  populateCategorySelect($("#recurring-category"));

  // New budget button
  $("#btn-new-budget")?.addEventListener("click", () => openBudgetModal());
  $("#btn-first-budget")?.addEventListener("click", () => openBudgetModal());

  // Form submission
  $("#budget-form")?.addEventListener("submit", submitBudget);

  // Close buttons
  $("#btn-close-budget-modal")?.addEventListener("click", closeBudgetModal);
  $("#btn-cancel-budget")?.addEventListener("click", closeBudgetModal);
  $("#budget-modal-backdrop")?.addEventListener("click", closeBudgetModal);

  $("#btn-close-detail-modal")?.addEventListener("click", closeDetailModal);
  $("#btn-close-detail")?.addEventListener("click", closeDetailModal);
  $("#budget-detail-backdrop")?.addEventListener("click", closeDetailModal);

  // Initial load
  loadBudgets();
});