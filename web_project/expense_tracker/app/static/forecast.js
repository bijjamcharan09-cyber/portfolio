/**
 * Financial Forecasting Module
 * Displays forecast results with charts, category breakdown, and confidence indicators
 */

const apiBase = document.body.dataset.guest === "true" ? "/api/guest" : "/api";
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const money = (n) => Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

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

function getConfidenceClass(confidence) {
  switch (confidence) {
    case "high": return "confidence-high";
    case "medium": return "confidence-medium";
    case "low": return "confidence-low";
    default: return "";
  }
}

function getConfidenceIcon(confidence) {
  switch (confidence) {
    case "high": return "✅";
    case "medium": return "⚠️";
    case "low": return "❓";
    default: return "";
  }
}

function formatCurrency(val, currency = "INR") {
  if (currency === "INR") return "₹" + money(val);
  if (currency === "USD") return "$" + money(val);
  if (currency === "EUR") return "€" + money(val);
  if (currency === "GBP") return "£" + money(val);
  return money(val);
}

function renderCategoryForecasts(categoryForecasts) {
  if (!categoryForecasts || Object.keys(categoryForecasts).length === 0) {
    return "";
  }

  return Object.entries(categoryForecasts).map(([cat, val]) => `
    <div class="category-forecast-item">
      <span class="category-name">${cat}</span>
      <span class="category-value">${formatCurrency(val)}</span>
    </div>
  `).join("");
}

async function loadForecast() {
  const months = $("#forecast-months").value;

  // Show loading state
  $("#forecast-loading").hidden = false;
  $("#forecast-insufficient").hidden = true;
  $("#forecast-results").hidden = true;
  $("#forecast-message").hidden = true;

  try {
    const result = await api(`/forecast?months=${months}`);
    if (!result) return;

    if (!result.forecast) {
      // Insufficient data
      $("#forecast-loading").hidden = true;
      $("#forecast-insufficient").hidden = false;
      return;
    }

    const forecast = result.forecast;
    $("#forecast-loading").hidden = true;
    $("#forecast-results").hidden = false;

    // Update summary cards
    $("#predicted-income").textContent = formatCurrency(forecast.predicted_income);
    $("#predicted-expense").textContent = formatCurrency(forecast.predicted_expense);
    $("#predicted-savings").textContent = formatCurrency(forecast.predicted_savings);

    // Income trend
    const incomeTrendEl = $("#income-trend");
    const incomeTrendVal = forecast.income_trend;
    incomeTrendEl.innerHTML = `
      <span class="trend-icon">${incomeTrendVal >= 0 ? "📈" : "📉"}</span>
      <span class="trend-text ${incomeTrendVal >= 0 ? "positive" : "negative"}">
        ${incomeTrendVal >= 0 ? "+" : ""}${formatCurrency(Math.abs(incomeTrendVal))} vs avg
      </span>
    `;

    // Expense trend
    const expenseTrendEl = $("#expense-trend");
    const expenseTrendVal = forecast.expense_trend;
    expenseTrendEl.innerHTML = `
      <span class="trend-icon">${expenseTrendVal >= 0 ? "📈" : "📉"}</span>
      <span class="trend-text ${expenseTrendVal >= 0 ? "negative" : "positive"}">
        ${expenseTrendVal >= 0 ? "+" : ""}${formatCurrency(Math.abs(expenseTrendVal))} vs avg
      </span>
    `;

    // Confidence badges
    const incomeConf = forecast.data_quality?.income_cv <= 0.3 ? "high" : forecast.data_quality?.income_cv <= 0.5 ? "medium" : "low";
    const expenseConf = forecast.data_quality?.expense_cv <= 0.3 ? "high" : forecast.data_quality?.expense_cv <= 0.5 ? "medium" : "low";

    $("#income-confidence").textContent = incomeConf.charAt(0).toUpperCase() + incomeConf.slice(1);
    $("#income-confidence").className = "confidence-badge " + getConfidenceClass(incomeConf);
    $("#expense-confidence").textContent = expenseConf.charAt(0).toUpperCase() + expenseConf.slice(1);
    $("#expense-confidence").className = "confidence-badge " + getConfidenceClass(expenseConf);

    // Category forecasts
    const catContainer = $("#category-forecasts");
    if (forecast.category_forecasts && Object.keys(forecast.category_forecasts).length > 0) {
      catContainer.innerHTML = renderCategoryForecasts(forecast.category_forecasts);
      $("#no-category-forecasts").hidden = true;
      catContainer.hidden = false;
    } else {
      catContainer.hidden = true;
      $("#no-category-forecasts").hidden = false;
    }

    // Disclaimer
    $("#forecast-disclaimer-text").textContent = forecast.disclaimer || "Forecasts are estimates based on historical data and simple statistical methods. They are not guaranteed financial outcomes.";

    // Data quality details
    $("#data-points").textContent = forecast.based_on_months || 0;
    $("#income-cv").textContent = forecast.data_quality?.income_cv ? (forecast.data_quality.income_cv * 100).toFixed(1) + "%" : "N/A";
    $("#expense-cv").textContent = forecast.data_quality?.expense_cv ? (forecast.data_quality.expense_cv * 100).toFixed(1) + "%" : "N/A";
    $("#overall-confidence").textContent = forecast.confidence?.charAt(0).toUpperCase() + forecast.confidence?.slice(1) || "Medium";
    $("#overall-confidence").className = getConfidenceClass(forecast.confidence);

  } catch (err) {
    $("#forecast-loading").hidden = true;
    say($("#forecast-message"), err.message);
  }
}

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  // Months selector change
  $("#forecast-months")?.addEventListener("change", loadForecast);

  // Refresh button
  $("#btn-refresh-forecast")?.addEventListener("click", loadForecast);

  // Initial load
  loadForecast();
});