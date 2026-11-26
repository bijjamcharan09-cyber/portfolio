/**
 * Subscription Manager Module
 * Handles subscription CRUD, cancel/pause, upcoming renewals, and cost totals
 */

const $ = window.EtUtils.$;
const $$ = window.EtUtils.$$;
const apiBase = window.EtUtils.apiBase;
const money = window.EtUtils.money;
const escapeHtml = window.EtUtils.escapeHtml;
const moneyCents = (cents) => money((cents || 0) / 100);

let currentSubStatus = "active";

function say(el, text, isError = true) {
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
  el.className = isError ? "message error" : "message success";
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

function getDaysUntil(dateStr) {
  if (!dateStr) return null;
  const target = new Date(dateStr + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = target - today;
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

function getStatusBadge(status) {
  const badges = {
    active: '<span class="status-badge status-active">Active</span>',
    paused: '<span class="status-badge status-paused">Paused</span>',
    cancelled: '<span class="status-badge status-cancelled">Cancelled</span>',
    expired: '<span class="status-badge status-expired">Expired</span>'
  };
  return badges[status] || `<span class="status-badge">${escapeHtml(status)}</span>`;
}

function getCycleLabel(cycle) {
  const labels = {
    monthly: "Monthly",
    quarterly: "Quarterly",
    yearly: "Yearly",
    custom: "Custom"
  };
  return labels[cycle] || cycle;
}

function renderSubscriptionCard(sub) {
  const renewal = formatDate(sub.renewal_date);
  const daysUntil = getDaysUntil(sub.renewal_date);
  const statusBadge = getStatusBadge(sub.status);
  const cycleLabel = getCycleLabel(sub.billing_cycle);
  const isSoon = sub.status === "active" && daysUntil !== null && daysUntil <= 7 && daysUntil >= 0;

  let dueSoonClass = "";
  let dueSoonText = "";
  if (isSoon) {
    dueSoonClass = "due-soon";
    dueSoonText = daysUntil === 0 ? "Due today!" : `${daysUntil} day${daysUntil === 1 ? "" : "s"}`;
  } else if (sub.status === "active" && daysUntil !== null && daysUntil < 0) {
    dueSoonClass = "overdue";
    dueSoonText = `${Math.abs(daysUntil)} day${Math.abs(daysUntil) === 1 ? "" : "s"} overdue`;
  }

  const safeName = escapeHtml(sub.name);

  return `
    <article class="subscription-card ${dueSoonClass}" data-id="${sub.id}">
      <div class="subscription-header">
        <div class="subscription-title-row">
          <h4 class="subscription-name">${safeName}</h4>
          ${statusBadge}
        </div>
        <div class="subscription-amount">${escapeHtml(sub.currency || "INR")} ${moneyCents(sub.amount_cents)}</div>
      </div>

      <div class="subscription-details">
        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-label">Billing Cycle</span>
            <span class="detail-value">${cycleLabel}${sub.billing_cycle === "custom" && sub.custom_cycle_days ? ` (${sub.custom_cycle_days} days)` : ""}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Renewal Date</span>
            <span class="detail-value renewal-date">${renewal} ${dueSoonText ? `<span class="due-badge">${dueSoonText}</span>` : ""}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Category</span>
            <span class="detail-value">${escapeHtml(sub.category)}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Payment Method</span>
            <span class="detail-value">${sub.payment_method ? escapeHtml(sub.payment_method) : "Not specified"}</span>
          </div>
        </div>
        ${sub.notes ? `<div class="sub-notes">${escapeHtml(sub.notes)}</div>` : ""}
      </div>

      <div class="subscription-actions">
        <button type="button" class="btn-sm btn-outline btn-edit" data-id="${sub.id}" aria-label="Edit ${safeName}">Edit</button>
        ${sub.status !== "cancelled" ? `
          <button type="button" class="btn-sm btn-outline btn-cancel-sub" data-id="${sub.id}" aria-label="Cancel ${safeName}">Cancel</button>
        ` : ""}
        <button type="button" class="btn-sm btn-danger btn-delete" data-id="${sub.id}" aria-label="Delete ${safeName}">Delete</button>
      </div>
    </article>
  `;
}

function renderRenewalItem(sub) {
  const renewal = formatDate(sub.renewal_date);
  const daysUntil = getDaysUntil(sub.renewal_date);
  const isSoon = daysUntil !== null && daysUntil <= 7 && daysUntil >= 0;
  const isOverdue = daysUntil !== null && daysUntil < 0;

  let badgeClass = "upcoming";
  let badgeText = "";
  if (isSoon) {
    badgeClass = "due-soon";
    badgeText = daysUntil === 0 ? "Today" : `${daysUntil}d`;
  } else if (isOverdue) {
    badgeClass = "overdue";
    badgeText = `${Math.abs(daysUntil)}d late`;
  } else if (daysUntil !== null) {
    badgeText = `${daysUntil}d`;
  }

  return `
    <div class="renewal-item ${badgeClass}" data-id="${sub.id}">
      <div class="renewal-info">
        <span class="renewal-name">${escapeHtml(sub.name)}</span>
        <span class="renewal-details">${getCycleLabel(sub.billing_cycle)} · ${escapeHtml(sub.currency || "INR")} ${moneyCents(sub.amount_cents)}</span>
      </div>
      <div class="renewal-due">
        <span class="renewal-date">${renewal}</span>
        <span class="renewal-badge ${badgeClass}">${badgeText}</span>
      </div>
    </div>
  `;
}

function updateSubscriptionTotals(totals) {
  const cur = totals.currency ? `${totals.currency} ` : "";
  $("#monthly-total").textContent = cur + money(totals.monthly_total || 0);
  $("#annual-total").textContent = cur + money(totals.yearly_total || 0);
  $("#active-sub-count").textContent = totals.subscription_count ?? 0;
  $("#subscription-totals").hidden = false;
}

async function loadSubscriptions(status = currentSubStatus) {
  currentSubStatus = status;
  try {
    const [subsResp, totals, upcomingResp] = await Promise.all([
      api(`/subscriptions${status !== "all" ? `?status=${encodeURIComponent(status)}` : ""}`),
      api("/subscriptions/totals"),
      api("/subscriptions/upcoming?days=30")
    ]);

    if (!subsResp) return;

    const subs = subsResp.subscriptions || [];
    const upcoming = upcomingResp ? (upcomingResp.subscriptions || []) : [];

    const container = $("#subscriptions-container");
    const empty = $("#subscriptions-empty");
    const renewalsSection = $("#upcoming-renewals");
    const renewalsContainer = $("#renewals-container");
    const renewalsEmpty = $("#renewals-empty");

    if (totals) {
      updateSubscriptionTotals(totals);
    }

    if (renewalsSection) {
      renewalsSection.hidden = false;
    }
    if (upcoming.length > 0) {
      renewalsEmpty.hidden = true;
      renewalsContainer.hidden = false;
      renewalsContainer.innerHTML = upcoming.map(renderRenewalItem).join("");
    } else {
      renewalsEmpty.hidden = false;
      renewalsContainer.hidden = true;
    }

    const filteredSubs = status === "all" ? subs : subs.filter(s => s.status === status);

    if (filteredSubs.length === 0) {
      container.hidden = true;
      empty.hidden = false;
      return;
    }

    empty.hidden = true;
    container.hidden = false;
    container.innerHTML = filteredSubs.map(renderSubscriptionCard).join("");
    attachSubscriptionEventListeners();
  } catch (err) {
    say($("#subscriptions-message"), err.message);
  }
}

function attachSubscriptionEventListeners() {
  $$(".btn-edit").forEach(btn => {
    btn.addEventListener("click", () => openSubscriptionModal(btn.dataset.id));
  });

  $$(".btn-cancel-sub").forEach(btn => {
    btn.addEventListener("click", () => cancelSubscription(btn.dataset.id));
  });

  $$(".btn-delete").forEach(btn => {
    btn.addEventListener("click", () => deleteSubscription(btn.dataset.id));
  });
}

function openSubscriptionModal(subId = null) {
  const isEdit = !!subId;
  $("#subscription-form").reset();
  $("#subscription-id").value = subId || "";
  $("#subscription-modal-title").textContent = isEdit ? "Edit Subscription" : "Add Subscription";
  $("#btn-submit-subscription").textContent = isEdit ? "Update Subscription" : "Add Subscription";

  const statusRow = $("#sub-status-row");
  if (statusRow) statusRow.hidden = !isEdit;

  toggleCustomCycle();

  if (isEdit) {
    loadSubscriptionForEdit(subId);
  } else {
    $("#sub-renewal").value = new Date().toLocaleDateString("en-CA");
  }

  $("#subscription-modal").hidden = false;
}

function toggleCustomCycle() {
  const cycle = $("#sub-cycle").value;
  const customRow = $("#custom-cycle-row");
  if (cycle === "custom") {
    customRow.hidden = false;
  } else {
    customRow.hidden = true;
    $("#sub-custom-days").value = "";
  }
}

async function loadSubscriptionForEdit(subId) {
  try {
    const sub = await api(`/subscriptions/${subId}`);
    if (!sub) return;

    $("#sub-name").value = sub.name;
    $("#sub-amount").value = (sub.amount_cents / 100).toFixed(2);
    $("#sub-currency").value = sub.currency || "INR";
    $("#sub-cycle").value = sub.billing_cycle;
    $("#sub-custom-days").value = sub.custom_cycle_days || "";
    $("#sub-renewal").value = sub.renewal_date;
    $("#sub-category").value = sub.category;
    $("#sub-payment").value = sub.payment_method || "";
    $("#sub-notes").value = sub.notes || "";
    if ($("#sub-status")) {
      $("#sub-status").value = sub.status || "active";
    }

    toggleCustomCycle();
  } catch (err) {
    say($("#subscriptions-message"), err.message);
  }
}

function closeSubscriptionModal() {
  $("#subscription-modal").hidden = true;
  $("#subscription-form").reset();
  $("#custom-cycle-row").hidden = true;
}

async function submitSubscription(e) {
  e.preventDefault();
  const subId = $("#subscription-id").value;
  const isEdit = !!subId;

  const data = {
    name: $("#sub-name").value.trim(),
    amount: $("#sub-amount").value,
    currency: $("#sub-currency").value,
    billing_cycle: $("#sub-cycle").value,
    custom_cycle_days: $("#sub-cycle").value === "custom" ? parseInt($("#sub-custom-days").value, 10) : null,
    renewal_date: $("#sub-renewal").value,
    category: $("#sub-category").value,
    payment_method: $("#sub-payment").value,
    notes: $("#sub-notes").value.trim()
  };

  if (isEdit && $("#sub-status")) {
    data.status = $("#sub-status").value;
  }

  try {
    if (isEdit) {
      await api(`/subscriptions/${subId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      say($("#subscriptions-message"), "Subscription updated successfully", false);
    } else {
      await api("/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
      say($("#subscriptions-message"), "Subscription added successfully", false);
    }
    closeSubscriptionModal();
    loadSubscriptions(currentSubStatus);
  } catch (err) {
    say($("#subscriptions-message"), err.message);
  }
}

async function cancelSubscription(subId) {
  if (!confirm("Are you sure you want to cancel this subscription?")) return;

  try {
    const sub = await api(`/subscriptions/${subId}`);
    if (!sub) return;

    await api(`/subscriptions/${subId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: sub.name,
        amount: (sub.amount_cents / 100).toFixed(2),
        currency: sub.currency || "INR",
        billing_cycle: sub.billing_cycle,
        custom_cycle_days: sub.custom_cycle_days,
        renewal_date: sub.renewal_date,
        status: "cancelled",
        category: sub.category,
        payment_method: sub.payment_method || "",
        notes: sub.notes || ""
      })
    });
    say($("#subscriptions-message"), "Subscription cancelled", false);
    loadSubscriptions(currentSubStatus);
  } catch (err) {
    say($("#subscriptions-message"), err.message);
  }
}

async function deleteSubscription(subId) {
  if (!confirm("Are you sure you want to delete this subscription? This action cannot be undone.")) return;

  try {
    await api(`/subscriptions/${subId}`, { method: "DELETE" });
    say($("#subscriptions-message"), "Subscription deleted successfully", false);
    loadSubscriptions(currentSubStatus);
  } catch (err) {
    say($("#subscriptions-message"), err.message);
  }
}

async function loadUnreadBadge() {
  try {
    const unread = await api("/notifications/unread-count").catch(() => null);
    const count = unread?.unread_count ?? 0;
    const badge = $("#notif-badge");
    if (badge) {
      badge.textContent = count > 99 ? "99+" : count;
      badge.hidden = count <= 0;
    }
  } catch (_) {}
}

document.addEventListener("DOMContentLoaded", () => {
  $("#btn-new-subscription")?.addEventListener("click", () => openSubscriptionModal());
  $("#btn-first-subscription")?.addEventListener("click", () => openSubscriptionModal());
  $("#sub-cycle")?.addEventListener("change", toggleCustomCycle);
  $("#subscription-form")?.addEventListener("submit", submitSubscription);

  $("#btn-close-subscription-modal")?.addEventListener("click", closeSubscriptionModal);
  $("#btn-cancel-subscription")?.addEventListener("click", closeSubscriptionModal);
  $("#subscription-modal-backdrop")?.addEventListener("click", closeSubscriptionModal);

  $$(".subscriptions-filter .filter-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      $$(".subscriptions-filter .filter-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      loadSubscriptions(tab.dataset.status);
    });
  });

  loadUnreadBadge();
  loadSubscriptions();
});
