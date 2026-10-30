const $ = (sel) => document.querySelector(sel);
const state = { period: "month", categories: {} };
const money = (n) => Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

async function api(path, options) {
  const res = await fetch("/api" + path, options);
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
  const type = document.querySelector("input[name=type]:checked").value;
  $("#category").replaceChildren(...state.categories[type].map((c) => new Option(c, c)));
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
    const del = Object.assign(document.createElement("button"), { textContent: "Delete", type: "button" });
    del.setAttribute("aria-label", `Delete ${t.category} ${t.date}`);
    del.addEventListener("click", async () => {
      await api("/transactions/" + t.id, { method: "DELETE" });
      refresh();
    });
    const last = document.createElement("td");
    last.append(del);
    tr.append(amount, last);
    body.append(tr);
  }
}

async function refresh() {
  try {
    const q = query();
    const [summary, items] = await Promise.all([api("/reports/summary?" + q), api("/transactions?" + q)]);
    $("#income").textContent = money(summary.income);
    $("#expense").textContent = money(summary.expense);
    $("#balance").textContent = money(summary.balance);
    $("#chart").src = "/api/reports/chart.png?" + q + "&_=" + Date.now();
    $("#converted").textContent = "";
    renderRows(items);
  } catch (err) { say(err.message); }
}

$("#tx-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const body = Object.fromEntries(new FormData(form));
  try {
    await api("/transactions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    say("");
    form.amount.value = "";
    form.note.value = "";
    refresh();
  } catch (err) { say(err.message); }
});

$("#convert-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api(`/convert?to=${encodeURIComponent($("#to").value)}&${query()}`);
    $("#converted").textContent = `${money(r.converted)} ${r.to} (1 ${r.base} = ${r.rate} ${r.to})`;
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

(async function init() {
  const today = new Date().toLocaleDateString("en-CA");  // YYYY-MM-DD in local time
  $("#anchor").value = today;
  $("#tx-date").value = today;
  state.categories = await api("/categories");
  fillCategories();
  refresh();
})();
