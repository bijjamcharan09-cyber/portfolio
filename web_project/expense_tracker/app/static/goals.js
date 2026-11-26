/**
 * Financial Goals Module
 * Handles goals CRUD, contributions, progress tracking, and milestones
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

function getStatusBadge(isCompleted) {
  if (isCompleted) return '<span class="status-badge status-completed">Completed</span>';
  return '<span class="status-badge status-active">In Progress</span>';
}

function createProgressBar(pct, label) {
  const clampedPct = Math.min(Math.max(pct, 0), 100);
  let cls = "progress-ok";
  if (pct >= 100) cls = "progress-complete";
  else if (pct >= 75) cls = "progress-good";
  else if (pct >= 50) cls = "progress-moderate";

  return `
    <div class="progress-bar-wrapper" role="progressbar" aria-valuenow="${pct.toFixed(1)}" aria-valuemin="0" aria-valuemax="100" aria-label="${label} progress">
      <div class="progress-bar ${cls}" style="width: ${clampedPct}%"></div>
    </div>
    <span class="progress-label">${pct.toFixed(1)}%</span>
  `;
}

function getEstimatedCompletion(goal, progress) {
  if (goal.is_completed || !goal.target_date) return null;

  const targetDate = new Date(goal.target_date + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  if (targetDate <= today) return "Overdue";

  // Simple estimation based on current progress rate
  // This is a placeholder - a real implementation would use contribution history
  const remaining = goal.target_amount_cents - (goal.current_amount_cents || 0);
  if (remaining <= 0) return "Target reached!";

  return formatDate(goal.target_date);
}

function renderGoalCard(goal, progress) {
  const pct = progress ? progress.progress_pct : 0;
  const current = progress ? progress.current_amount : (goal.current_amount_cents / 100);
  const target = goal.target_amount_cents / 100;
  const remaining = Math.max(target - current, 0);
  const estimatedDate = getEstimatedCompletion(goal, progress);

  return `
    <article class="goal-card" data-id="${goal.id}">
      <div class="goal-header">
        <div class="goal-title-row">
          <h4 class="goal-name">${goal.name}</h4>
          ${getStatusBadge(goal.is_completed)}
        </div>
      </div>

      <div class="goal-progress">
        ${createProgressBar(pct, goal.name)}
      </div>

      <div class="goal-amounts">
        <div class="goal-amount">
          <span class="goal-amount-label">Saved</span>
          <span class="goal-amount-value income">${money(current)}</span>
        </div>
        <div class="goal-amount">
          <span class="goal-amount-label">Target</span>
          <span class="goal-amount-value">${money(target)}</span>
        </div>
        <div class="goal-amount">
          <span class="goal-amount-label">Remaining</span>
          <span class="goal-amount-value">${money(remaining)}</span>
        </div>
      </div>

      ${goal.target_date ? `
        <div class="goal-dates">
          <span>Target: ${formatDate(goal.target_date)}</span>
          ${estimatedDate && estimatedDate !== formatDate(goal.target_date) ? `<span class="estimated">Est. completion: ${estimatedDate}</span>` : ""}
        </div>
      ` : ""}

      ${goal.description ? `<div class="goal-description">${goal.description}</div>` : ""}

      <div class="goal-actions">
        <button type="button" class="btn-sm btn-primary btn-contribute" data-id="${goal.id}" ${goal.is_completed ? "disabled" : ""} aria-label="Add contribution to ${goal.name}">
          ${goal.is_completed ? "Completed" : "Add Contribution"}
        </button>
        <button type="button" class="btn-sm btn-outline btn-view" data-id="${goal.id}" aria-label="View ${goal.name} details">View</button>
        <button type="button" class="btn-sm btn-outline btn-edit" data-id="${goal.id}" aria-label="Edit ${goal.name}">Edit</button>
        <button type="button" class="btn-sm btn-danger btn-delete" data-id="${goal.id}" aria-label="Delete ${goal.name}">Delete</button>
      </div>
    </article>
  `;
}

function updateGoalsOverview(goals, progresses) {
  const progressMap = {};
  progresses.forEach(p => { progressMap[p.goal_id] = p; });

  const activeGoals = goals.filter(g => !g.is_completed);
  const totalTarget = activeGoals.reduce((sum, g) => sum + g.target_amount_cents, 0);
  let totalSaved = 0;

  activeGoals.forEach(g => {
    const p = progressMap[g.id];
    if (p) totalSaved += p.current_amount * 100;
    else totalSaved += g.current_amount_cents || 0;
  });

  const overallPct = totalTarget > 0 ? (totalSaved / totalTarget) * 100 : 0;

  $("#total-target").textContent = moneyCents(totalTarget);
  $("#total-saved").textContent = moneyCents(totalSaved);
  $("#overall-progress").textContent = overallPct.toFixed(1) + "%";
  $("#active-goals-count").textContent = activeGoals.length;
  $("#goals-overview").hidden = false;
}

async function loadGoals(filter = "active") {
  try {
    const isCompleted = filter === "completed" ? 1 : filter === "active" ? 0 : null;
    const [goals, progresses] = await Promise.all([
      api(`/goals${isCompleted !== null ? `?is_completed=${isCompleted}` : ""}`),
      api("/goals") // Get all to calculate progress
    ]);

    if (!goals) return;

    const container = $("#goals-container");
    const empty = $("#goals-empty");

    if (goals.length === 0) {
      container.hidden = true;
      empty.hidden = false;
      $("#goals-overview").hidden = true;
      return;
    }

    empty.hidden = true;
    container.hidden = false;

    // Create progress lookup
    const progressMap = {};
    if (progresses) {
      progresses.forEach(g => {
        // We'll fetch individual progress for each goal
      });
    }

    // Fetch progress for each goal
    const goalsWithProgress = await Promise.all(
      goals.map(async (goal) => {
        const progress = await api(`/goals/${goal.id}`);
        return { goal, progress };
      })
    );

    container.innerHTML = goalsWithProgress.map(({ goal, progress }) => renderGoalCard(goal, progress)).join("");

    // Update overview with all goals
    const allProgresses = goalsWithProgress.map(({ progress }) => progress).filter(Boolean);
    updateGoalsOverview(goals, allProgresses);

    attachGoalEventListeners();
  } catch (err) {
    say($("#goals-message"), err.message);
  }
}

function attachGoalEventListeners() {
  // Contribute buttons
  $$(".btn-contribute").forEach(btn => {
    btn.addEventListener("click", () => openContributionModal(btn.dataset.id));
  });

  // View buttons
  $$(".btn-view").forEach(btn => {
    btn.addEventListener("click", () => openGoalDetail(btn.dataset.id));
  });

  // Edit buttons
  $$(".btn-edit").forEach(btn => {
    btn.addEventListener("click", () => openGoalModal(btn.dataset.id));
  });

  // Delete buttons
  $$(".btn-delete").forEach(btn => {
    btn.addEventListener("click", () => deleteGoal(btn.dataset.id));
  });

  // Filter tabs
  $$(".goals-filter .filter-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      $$(".goals-filter .filter-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      loadGoals(tab.dataset.filter);
    });
  });
}

async function openGoalDetail(goalId) {
  try {
    const [goal, progress, contributions] = await Promise.all([
      api(`/goals/${goalId}`),
      api(`/goals/${goalId}`),
      api(`/goals/${goalId}/contributions`)
    ]);

    if (!goal) return;

    const pct = progress ? progress.progress_pct : 0;
    const current = progress ? progress.current_amount : (goal.current_amount_cents / 100);
    const target = goal.target_amount_cents / 100;
    const remaining = Math.max(target - current, 0);
    const estimatedDate = getEstimatedCompletion(goal, progress);

    const detailBody = $("#goal-detail-body");
    detailBody.innerHTML = `
      <div class="goal-detail">
        <div class="goal-detail-header">
          <h4>${goal.name}</h4>
          ${getStatusBadge(goal.is_completed)}
        </div>

        <div class="detail-progress">
          ${createProgressBar(pct, goal.name)}
        </div>

        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-label">Target Amount</span>
            <span class="detail-value">${money(target)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Current Amount</span>
            <span class="detail-value income">${money(current)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Remaining</span>
            <span class="detail-value">${money(remaining)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Progress</span>
            <span class="detail-value">${pct.toFixed(1)}%</span>
          </div>
          ${goal.target_date ? `
            <div class="detail-item">
              <span class="detail-label">Target Date</span>
              <span class="detail-value">${formatDate(goal.target_date)}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Est. Completion</span>
              <span class="detail-value">${estimatedDate || "Calculating..."}</span>
            </div>
          ` : ""}
          <div class="detail-item">
            <span class="detail-label">Status</span>
            <span class="detail-value">${goal.is_completed ? "Completed" : "In Progress"}</span>
          </div>
        </div>

        ${goal.description ? `<div class="detail-description"><strong>Description:</strong> ${goal.description}</div>` : ""}

        <div class="detail-section">
          <h5>Contributions</h5>
          ${contributions && contributions.length > 0 ? `
            <div class="contributions-list">
              ${contributions.slice(0, 10).map(c => `
                <div class="contribution-item">
                  <span class="contrib-date">${formatDate(c.date)}</span>
                  <span class="contrib-amount income">+${moneyCents(c.amount_cents)}</span>
                  ${c.note ? `<span class="contrib-note">${c.note}</span>` : ""}
                </div>
              `).join("")}
              ${contributions.length > 10 ? `<p class="text-muted">... and ${contributions.length - 10} more</p>` : ""}
            </div>
          ` : `<p class="text-muted">No contributions yet</p>`}
        </div>
      </div>
    `;

    $("#goal-detail-modal").hidden = false;
  } catch (err) {
    say($("#goals-message"), err.message);
  }
}

function openGoalModal(goalId = null) {
  const isEdit = !!goalId;
  $("#goal-form").reset();
  $("#goal-id").value = goalId || "";
  $("#goal-modal-title").textContent = isEdit ? "Edit Goal" : "Create Goal";
  $("#btn-submit-goal").textContent = isEdit ? "Update Goal" : "Create Goal";

  if (isEdit) {
    loadGoalForEdit(goalId);
  }

  $("#goal-modal").hidden = false;
}

async function loadGoalForEdit(goalId) {
  try {
    const goal = await api(`/goals/${goalId}`);
    if (!goal) return;

    $("#goal-name").value = goal.name;
    $("#goal-target").value = (goal.target_amount_cents / 100).toFixed(2);
    $("#goal-current").value = ((goal.current_amount_cents || 0) / 100).toFixed(2);
    $("#goal-target-date").value = goal.target_date || "";
    $("#goal-description").value = goal.description || "";
  } catch (err) {
    say($("#goals-message"), err.message);
  }
}

function closeGoalModal() {
  $("#goal-modal").hidden = true;
  $("#goal-form").reset();
}

function closeGoalDetailModal() {
  $("#goal-detail-modal").hidden = true;
}

async function submitGoal(e) {
  e.preventDefault();
  const form = e.target;
  const goalId = $("#goal-id").value;
  const isEdit = !!goalId;

  const data = {
    name: $("#goal-name").value.trim(),
    target_amount_cents: Math.round(parseFloat($("#goal-target").value) * 100),
    current_amount_cents: Math.round(parseFloat($("#goal-current").value || 0) * 100),
    target_date: $("#goal-target-date").value || null,
    description: $("#goal-description").value.trim()
  };

  try {
    if (isEdit) {
      await api(`/goals/${goalId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      say($("#goals-message"), "Goal updated successfully", false);
    } else {
      await api("/goals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      say($("#goals-message"), "Goal created successfully", false);
    }
    closeGoalModal();
    loadGoals($$(".goals-filter .filter-tab.active")[0]?.dataset.filter || "active");
  } catch (err) {
    say($("#goals-message"), err.message);
  }
}

async function deleteGoal(goalId) {
  if (!confirm("Are you sure you want to delete this goal? This action cannot be undone.")) return;

  try {
    await api(`/goals/${goalId}`, { method: "DELETE" });
    say($("#goals-message"), "Goal deleted successfully", false);
    loadGoals($$(".goals-filter .filter-tab.active")[0]?.dataset.filter || "active");
  } catch (err) {
    say($("#goals-message"), err.message);
  }
}

// Contribution Modal
function openContributionModal(goalId) {
  $("#contribution-form").reset();
  $("#contribution-goal-id").value = goalId;
  $("#contribution-date").value = new Date().toLocaleDateString("en-CA");
  $("#contribution-modal").hidden = false;
}

function closeContributionModal() {
  $("#contribution-modal").hidden = true;
  $("#contribution-form").reset();
}

async function submitContribution(e) {
  e.preventDefault();
  const goalId = $("#contribution-goal-id").value;

  const data = {
    amount_cents: Math.round(parseFloat($("#contribution-amount").value) * 100),
    note: $("#contribution-note").value.trim(),
    date: $("#contribution-date").value
  };

  try {
    await api(`/goals/${goalId}/contributions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
    say($("#goals-message"), "Contribution added successfully", false);
    closeContributionModal();
    loadGoals($$(".goals-filter .filter-tab.active")[0]?.dataset.filter || "active");
  } catch (err) {
    say($("#goals-message"), err.message);
  }
}

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  // New goal button
  $("#btn-new-goal")?.addEventListener("click", () => openGoalModal());
  $("#btn-first-goal")?.addEventListener("click", () => openGoalModal());

  // Form submissions
  $("#goal-form")?.addEventListener("submit", submitGoal);
  $("#contribution-form")?.addEventListener("submit", submitContribution);

  // Close buttons
  $("#btn-close-goal-modal")?.addEventListener("click", closeGoalModal);
  $("#btn-cancel-goal")?.addEventListener("click", closeGoalModal);
  $("#goal-modal-backdrop")?.addEventListener("click", closeGoalModal);

  $("#btn-close-goal-detail")?.addEventListener("click", closeGoalDetailModal);
  $("#btn-close-goal-detail-footer")?.addEventListener("click", closeGoalDetailModal);
  $("#goal-detail-backdrop")?.addEventListener("click", closeGoalDetailModal);

  $("#btn-close-contribution-modal")?.addEventListener("click", closeContributionModal);
  $("#btn-cancel-contribution")?.addEventListener("click", closeContributionModal);
  $("#contribution-modal-backdrop")?.addEventListener("click", closeContributionModal);

  // Initial load
  loadGoals();
});