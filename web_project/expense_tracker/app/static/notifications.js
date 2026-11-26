/**
 * Notifications Module
 * Handles notification listing, read/unread status, mark all read, filtering
 */

const $ = window.EtUtils.$;
const $$ = window.EtUtils.$$;
const apiBase = window.EtUtils.apiBase;
const escapeHtml = window.EtUtils.escapeHtml;

let currentPage = 1;
const PER_PAGE = 20;
let currentFilter = "all";

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
  const isRead = Boolean(notif.is_read);

  return `
    <article class="notification-item ${isRead ? "read" : "unread"}" data-id="${notif.id}">
      <div class="notification-icon" aria-hidden="true">${icon}</div>
      <div class="notification-content">
        <div class="notification-header">
          <h4 class="notification-title">${escapeHtml(notif.title)}</h4>
          <span class="notification-type">${escapeHtml(typeLabel)}</span>
        </div>
        <p class="notification-message">${escapeHtml(notif.message)}</p>
        <div class="notification-meta">
          <span class="notification-date">${date}</span>
          ${notif.entity_type ? `<span class="notification-entity">${escapeHtml(notif.entity_type)}: ${escapeHtml(notif.entity_id)}</span>` : ""}
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
  if (!badge) return;
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

async function loadNotifications(filter = currentFilter, page = currentPage) {
  currentFilter = filter;
  currentPage = page;

  try {
    const isRead = filter === "unread" ? 0 : filter === "read" ? 1 : null;
    const params = new URLSearchParams({
      page: page,
      per_page: PER_PAGE
    });
    if (isRead !== null) params.set("is_read", isRead);

    const [notifResp, unreadResp] = await Promise.all([
      api(`/notifications?${params.toString()}`),
      api("/notifications/unread-count")
    ]);

    if (!notifResp) return;

    const notifications = notifResp.notifications || [];
    const pagination = notifResp.pagination;
    const unreadCount = unreadResp?.unread_count ?? unreadResp?.count ?? 0;

    const container = $("#notifications-container");
    const empty = $("#notifications-empty");
    const markAllBtn = $("#btn-mark-all-read");

    updateUnreadCount(unreadCount);

    if (markAllBtn) {
      markAllBtn.hidden = unreadCount <= 0;
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

    if (pagination) {
      renderPagination(pagination);
    } else {
      $("#notifications-pagination").hidden = true;
    }

    attachNotificationItemListeners();
  } catch (err) {
    say($("#notifications-message"), err.message);
  }
}

function attachNotificationItemListeners() {
  $$(".btn-mark-read").forEach(btn => {
    btn.addEventListener("click", () => markNotificationRead(btn.dataset.id));
  });

  $$(".btn-delete-notif").forEach(btn => {
    btn.addEventListener("click", () => deleteNotification(btn.dataset.id));
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
  const originalText = btn ? btn.textContent : "Check Now";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Checking...";
  }

  try {
    const result = await api("/notifications/check", { method: "POST" });
    if (result) {
      const totalCreated =
        (result.budget_notifications?.length || 0) +
        (result.recurring_notifications?.length || 0) +
        (result.subscription_notifications?.length || 0) +
        (result.goal_notifications?.length || 0);
      say($("#notifications-message"), `Checked notifications (${totalCreated} new)`, false);
      loadNotifications(currentFilter, 1);
    }
  } catch (err) {
    say($("#notifications-message"), err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
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

document.addEventListener("DOMContentLoaded", () => {
  $("#btn-mark-all-read")?.addEventListener("click", markAllRead);
  $("#btn-check-notifications")?.addEventListener("click", checkNotifications);
  $("#btn-check-first")?.addEventListener("click", checkNotifications);

  $$(".notifications-filter .filter-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      $$(".notifications-filter .filter-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentPage = 1;
      loadNotifications(tab.dataset.filter, 1);
    });
  });

  $("#btn-notif-prev")?.addEventListener("click", () => {
    if (currentPage > 1) {
      loadNotifications(currentFilter, currentPage - 1);
    }
  });

  $("#btn-notif-next")?.addEventListener("click", () => {
    loadNotifications(currentFilter, currentPage + 1);
  });

  loadNotifications();
});
