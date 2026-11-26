/**
 * Financial Forecasting Module
 * Displays forecast results with inline SVG chart, category breakdown, and confidence indicators
 */

const $ = window.EtUtils.$;
const $$ = window.EtUtils.$$;
const apiBase = window.EtUtils.apiBase;
const money = window.EtUtils.money;
const escapeHtml = window.EtUtils.escapeHtml;

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

function getConfidenceClass(confidence) {
  switch (confidence) {
    case "high": return "confidence-high";
    case "medium": return "confidence-medium";
    case "low": return "confidence-low";
    default: return "";
  }
}

function formatCurrency(val) {
  const bodyCurrency = (document.body.dataset.currency || "").toUpperCase();
  if (bodyCurrency.includes("USD")) return "$" + money(val);
  if (bodyCurrency.includes("EUR")) return "€" + money(val);
  if (bodyCurrency.includes("GBP")) return "£" + money(val);
  return "₹" + money(val);
}

function renderCategoryForecasts(categoryForecasts) {
  if (!categoryForecasts || Object.keys(categoryForecasts).length === 0) {
    return "";
  }

  return Object.entries(categoryForecasts).map(([cat, val]) => `
    <div class="category-forecast-item">
      <span class="category-name">${escapeHtml(cat)}</span>
      <span class="category-value">${formatCurrency(val)}</span>
    </div>
  `).join("");
}

function renderForecastChart(forecast) {
  const container = $("#forecast-chart");
  if (!container) return;

  const history = Array.isArray(forecast.history) ? forecast.history : [];
  const points = [
    ...history.map(h => ({ label: h.month, income: h.income, expense: h.expense, isForecast: false })),
    {
      label: "Next Mo (Est.)",
      income: Math.max(0, forecast.predicted_income || 0),
      expense: Math.max(0, forecast.predicted_expense || 0),
      isForecast: true
    }
  ];

  if (points.length === 0) {
    container.innerHTML = '<p class="text-muted">No chart data available.</p>';
    return;
  }

  const maxVal = Math.max(1, ...points.flatMap(p => [p.income, p.expense]));
  const width = Math.max(520, points.length * 90);
  const height = 220;
  const padLeft = 50;
  const padBottom = 35;
  const padTop = 20;
  const chartH = height - padTop - padBottom;
  const groupW = (width - padLeft - 20) / points.length;
  const barW = Math.min(24, groupW * 0.32);

  const bars = points.map((p, idx) => {
    const cx = padLeft + idx * groupW + groupW / 2;
    const incH = (p.income / maxVal) * chartH;
    const expH = (p.expense / maxVal) * chartH;
    const incY = padTop + chartH - incH;
    const expY = padTop + chartH - expH;
    const opacity = p.isForecast ? "0.7" : "1";
    const dash = p.isForecast ? 'stroke="#0F172A" stroke-dasharray="3,2" stroke-width="1"' : "";

    return `
      <g>
        <rect x="${cx - barW - 2}" y="${incY}" width="${barW}" height="${incH}" fill="#15803D" opacity="${opacity}" rx="3" ${dash}>
          <title>${escapeHtml(p.label)} Income: ${formatCurrency(p.income)}</title>
        </rect>
        <rect x="${cx + 2}" y="${expY}" width="${barW}" height="${expH}" fill="#DC2626" opacity="${opacity}" rx="3" ${dash}>
          <title>${escapeHtml(p.label)} Expense: ${formatCurrency(p.expense)}</title>
        </rect>
        <text x="${cx}" y="${height - 12}" text-anchor="middle" font-size="11" fill="#475569" font-weight="${p.isForecast ? "700" : "400"}">${escapeHtml(p.label)}</text>
      </g>
    `;
  }).join("");

  container.innerHTML = `
    <div class="chart-legend" style="display:flex;gap:1rem;margin-bottom:0.5rem;font-size:0.85rem;color:#475569;">
      <span><span style="display:inline-block;width:10px;height:10px;background:#15803D;border-radius:2px;margin-right:4px;"></span>Income</span>
      <span><span style="display:inline-block;width:10px;height:10px;background:#DC2626;border-radius:2px;margin-right:4px;"></span>Expenses</span>
      <span>(Dashed = Predicted)</span>
    </div>
    <div style="overflow-x:auto;">
      <svg viewBox="0 0 ${width} ${height}" style="width:100%;max-width:${width}px;height:auto;" role="img" aria-label="Actual versus predicted monthly income and expenses">
        <line x1="${padLeft}" y1="${padTop + chartH}" x2="${width - 10}" y2="${padTop + chartH}" stroke="#CBD5E1" stroke-width="1"/>
        ${bars}
      </svg>
    </div>
  `;
}

async function loadForecast() {
  const months = $("#forecast-months").value;

  $("#forecast-loading").hidden = false;
  $("#forecast-insufficient").hidden = true;
  $("#forecast-results").hidden = true;
  $("#forecast-message").hidden = true;

  try {
    const result = await api(`/forecast?months=${months}`);
    if (!result) return;

    if (!result.forecast) {
      $("#forecast-loading").hidden = true;
      $("#forecast-insufficient").hidden = false;
      return;
    }

    const forecast = result.forecast;
    $("#forecast-loading").hidden = true;
    $("#forecast-results").hidden = false;

    $("#predicted-income").textContent = formatCurrency(forecast.predicted_income);
    $("#predicted-expense").textContent = formatCurrency(forecast.predicted_expense);
    $("#predicted-savings").textContent = formatCurrency(forecast.predicted_savings);

    const incomeTrendEl = $("#income-trend");
    const incomeTrendVal = Number(forecast.income_trend) || 0;
    incomeTrendEl.innerHTML = `
      <span class="trend-icon">${incomeTrendVal >= 0 ? "📈" : "📉"}</span>
      <span class="trend-text ${incomeTrendVal >= 0 ? "positive" : "negative"}">
        ${incomeTrendVal >= 0 ? "+" : "-"}${formatCurrency(Math.abs(incomeTrendVal))} vs avg
      </span>
    `;

    const expenseTrendEl = $("#expense-trend");
    const expenseTrendVal = Number(forecast.expense_trend) || 0;
    expenseTrendEl.innerHTML = `
      <span class="trend-icon">${expenseTrendVal >= 0 ? "📈" : "📉"}</span>
      <span class="trend-text ${expenseTrendVal >= 0 ? "negative" : "positive"}">
        ${expenseTrendVal >= 0 ? "+" : "-"}${formatCurrency(Math.abs(expenseTrendVal))} vs avg
      </span>
    `;

    const incomeConf = forecast.data_quality?.income_cv <= 0.3 ? "high" : forecast.data_quality?.income_cv <= 0.5 ? "medium" : "low";
    const expenseConf = forecast.data_quality?.expense_cv <= 0.3 ? "high" : forecast.data_quality?.expense_cv <= 0.5 ? "medium" : "low";

    $("#income-confidence").textContent = incomeConf.charAt(0).toUpperCase() + incomeConf.slice(1);
    $("#income-confidence").className = "confidence-badge " + getConfidenceClass(incomeConf);
    $("#expense-confidence").textContent = expenseConf.charAt(0).toUpperCase() + expenseConf.slice(1);
    $("#expense-confidence").className = "confidence-badge " + getConfidenceClass(expenseConf);

    renderForecastChart(forecast);

    const catContainer = $("#category-forecasts");
    if (forecast.category_forecasts && Object.keys(forecast.category_forecasts).length > 0) {
      catContainer.innerHTML = renderCategoryForecasts(forecast.category_forecasts);
      $("#no-category-forecasts").hidden = true;
      catContainer.hidden = false;
    } else {
      catContainer.hidden = true;
      $("#no-category-forecasts").hidden = false;
    }

    $("#forecast-disclaimer-text").textContent = forecast.disclaimer || "Forecasts are estimates based on historical data and simple statistical methods. They are not guaranteed financial outcomes.";

    $("#data-points").textContent = forecast.based_on_months || 0;
    $("#income-cv").textContent = forecast.data_quality?.income_cv !== undefined ? (forecast.data_quality.income_cv * 100).toFixed(1) + "%" : "N/A";
    $("#expense-cv").textContent = forecast.data_quality?.expense_cv !== undefined ? (forecast.data_quality.expense_cv * 100).toFixed(1) + "%" : "N/A";
    const overallConf = forecast.confidence || "medium";
    $("#overall-confidence").textContent = overallConf.charAt(0).toUpperCase() + overallConf.slice(1);
    $("#overall-confidence").className = getConfidenceClass(overallConf);
  } catch (err) {
    $("#forecast-loading").hidden = true;
    say($("#forecast-message"), err.message);
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
  $("#forecast-months")?.addEventListener("change", loadForecast);
  $("#btn-refresh-forecast")?.addEventListener("click", loadForecast);

  loadUnreadBadge();
  loadForecast();
});
