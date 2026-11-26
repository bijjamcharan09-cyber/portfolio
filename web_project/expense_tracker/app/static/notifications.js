/**
 * Notifications Module
 * Handles notification listing, read/unread status, mark all read, filtering
 */

const apiBase = document.body.dataset.guest === "true" ? "/api/guest" : "/api";
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const money = (n) => Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const moneyCents = (cents) => money(cents / 100);

let currentPage = 1;
const PER_PAGE = 20;
let currentFilter = "all";

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
  const d = new Date(dateStr);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function getNotificationIcon(type) {
  const icons = {
    budget_warning: "⚡",
    budget_exceeded: "⚠️",
    recurring_due: "🔄",
    subscription_renewal: "📱",
    goal_milestone: "🎯",
    goal_completed: "✅"
  };
  return icons[type] || "🔔";
}

function getNotificationTypeLabel(type) {
  const labels = {
    budget_warning: "Budget Warning",
    budget_exceeded: "Budget Exceeded",
    recurring_due: "Recurring Due",
    subscription_renewal: "Subscription Renewal",
    goal_milestone: "Goal Milestone",
    goal_completed: "Goal Completed"
  };
  return labels[type] || type;
}

function renderNotification(notif) {
  const icon = getNotificationIcon(notif.type);
  const typeLabel = getNotificationTypeLabel(notif.type);
  const date = formatDate(notif.created_at);
  const isRead = notif.is_read;

  return `
    <article class="notification-item ${isRead ? "read" : "unread"}" data-id="${notif.id}">
      <div class="notification-icon" aria-hidden="true">${icon}</div>
      <div class="notification-content">
        <div class="notification-header">
          <h4 class="notification-title">${notif.title}</h4>
          <span class="notification-type">${typeLabel}</span>
        </div>
        <p class="notification-message">${notif.message}</p>
        <div class="notification-meta">
          <span class="notification-date">${date}</span>
          ${notif.entity_type ? `<span class="notification-entity">${notif.entity_type}: ${notif.entity_id}</span>` : ""}
        </div>
      </div>
      <div class="notification-actions">
        ${!isRead ? `
          <button type="button" class="btn-sm btn-primary btn-mark-read" data-id="${notif.id}" aria-label="Mark as read">Mark Read</button>
        ` : `
          <span class="read-indicator" aria-label="Read">✓</span>
        `}
        <button type="button" class="btn-sm btn-outline btn-delete-notif" data-id="${notif.id}" aria-label="Delete notification">Delete</button>
      </div>
    </article>
  `;
}

function updateUnreadCount(count) {
  const badge = $("#notif-badge");
  if (count > 0) {
    badge.textContent = count > 99 ? "99+" : count;
    badge.hidden = false;
  } else {
    badge.hidden = true;
  }
}

function renderPagination(pagination) {
  const container = $("#notifications-pagination");
  const prevBtn = $("#btn-notif-prev");
  const nextBtn = $("#btn-notif-next");
  const pageInfo = $("#notif-page-info");

  if (!container || !prevBtn || !nextBtn || !pageInfo) return;

  const current = pagination.current_page || 1;
  const total = pagination.total_pages || 1;
  const hasNext = pagination.has_next || false;
  const hasPrev = pagination.has_previous || false;

  if (total <= 1) {
    container.hidden = true;
    return;
  }

  container.hidden = false;
  pageInfo.textContent = `Page ${current} of ${total}`;
  prevBtn.disabled = !hasPrev;
  nextBtn.disabled = !hasNext;
}

async function loadNotifications(filter = "all", page = 1) {
  currentFilter = filter;
  currentPage = page;

  try {
    const isRead = filter === "unread" ? 0 : filter === "read" ? 1 : null;
    const params = new URLSearchParams({
      page: page,
      per_page: PER_PAGE
    });
    if (isRead !== null) params.set("is_read", isRead);

    const [notifications, unreadCount] = await Promise.all([
      api(`/notifications?${params.toString()}`),
      api("/notifications/unread-count")
    ]);

    if (!notifications) return;

    const container = $("#notifications-container");
    const empty = $("#notifications-empty");
    const markAllBtn = $("#btn-mark-all-read");

    updateUnreadCount(unreadCount?.count || 0);

    // Show mark all read button only for unread filter
    if (filter === "unread" && unreadCount?.count > 0) {
      markAllBtn.hidden = false;
    } else {
      markAllBtn.hidden = true;
    }

    if (notifications.length === 0) {
      container.hidden = true;
      empty.hidden = false;
      $("#notifications-pagination").hidden = true;
      return;
    }

    empty.hidden = true;
    container.hidden = false;
    container.innerHTML = notifications.map(renderNotification).join("");

    // Check if pagination info is available
    if (notifications.pagination) {
      renderPagination(notifications.pagination);
    } else {
      $("#notifications-pagination").hidden = true;
    }

    attachNotificationEventListeners();
  } catch (err) {
    say($("#notifications-message"), err.message);
  }
}

function attachNotificationEventListeners() {
  // Mark read buttons
  $$(".btn-mark-read").forEach(btn => {
    btn.addEventListener("click", () => markNotificationRead(btn.dataset.id));
  });

  // Delete buttons
  $$(".btn-delete-notif").forEach(btn => {
    btn.addEventListener("click", () => deleteNotification(btn.dataset.id));
  });

  // Filter tabs
  $$(".notifications-filter .filter-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      $$(".notifications-filter .filter-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentPage = 1;
      loadNotifications(tab.dataset.filter, 1);
    });
  });

  // Pagination
  $("#btn-notif-prev")?.addEventListener("click", () => {
    if (currentPage > 1) {
      loadNotifications(currentFilter, currentPage - 1);
    }
  });

  $("#btn-notif-next")?.addEventListener("click", () => {
    loadNotifications(currentFilter, currentPage + 1);
  });
}

async function markNotificationRead(notifId) {
  try {
    await api(`/notifications/${notifId}/read`, { method: "POST" });
    say($("#notifications-message"), "Notification marked as read", false);
    loadNotifications(currentFilter, currentPage);
  } catch (err) {
    say($("#notifications-message"), err.message);
  }
}

async function markAllRead() {
  try {
    await api("/notifications/read-all", { method: "POST" });
    say($("#notifications-message"), "All notifications marked as read", false);
    loadNotifications(currentFilter, currentPage);
  } catch (err) {
    say($("#notifications-message"), err.message);
  }
}

async function checkNotifications() {
  const btn = $("#btn-check-notifications");
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Checking...";

  try {
    const result = await api("/notifications/check", { method: "POST" });
    if (result) {
      say($("#notifications-message"), "Notifications checked and created", false);
      loadNotifications(currentFilter, currentPage);
    }
  } catch (err) {
    say($("#notifications-message"), err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

async function deleteNotification(notifId) {
  if (!confirm("Are you sure you want to delete this notification?")) return;

  try {
    await api(`/notifications/${notifId}`, { method: "DELETE" });
    say($("#notifications-message"), "Notification deleted", false);
    loadNotifications(currentFilter, currentPage);
  } catch (err) {
    say($("#notifications-message"), err.message);
  }
}

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  // Mark all read
  $("#btn-mark-all-read")?.addEventListener("click", markAllRead);

  // Check notifications
  $("#btn-check-notifications")?.addEventListener("click", checkNotifications);
  $("#btn-check-first")?.addEventListener("click", checkNotifications);

  // Initial load
  loadNotifications();
});