const map = L.map("map", { zoomControl: false }).setView([50.827, 15.521], 11);
L.control.zoom({ position: "bottomright" }).addTo(map);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
}).addTo(map);

const elements = {
  message: document.getElementById("map-message"),
  count: document.getElementById("count"),
  search: document.getElementById("search"),
  searchResults: document.getElementById("search-results"),
  scan: document.getElementById("scan"),
  scanStatus: document.getElementById("scan-status"),
  detail: document.getElementById("detail"),
  detailContent: document.getElementById("detail-content"),
  detailClose: document.getElementById("detail-close"),
  filterAll: document.getElementById("filter-all"),
  filterActive: document.getElementById("filter-active"),
};

const markers = L.layerGroup().addTo(map);
const markerByCode = new Map();
let visiblePoints = [];
let selectedCode = null;
let selectionVersion = 0;
let filter = "all";
let loadingVersion = 0;
let scanning = false;
let visibleTruncated = false;
const labels = {
  PM1: ["PM 1", "µg/m³"], PM25: ["PM 2,5", "µg/m³"],
  PM10: ["PM 10", "µg/m³"], PM4: ["PM 4", "µg/m³"],
  NO2: ["NO₂", "µg/m³"], O3: ["O₃", "µg/m³"],
  TEMPERATURE: ["Temperatura", "°C"], HUMIDITY: ["Wilgotność", "%"],
  PRESSURE: ["Ciśnienie", "hPa"],
};
const statusLabels = {
  active: "Aktualne pomiary", stale: "Starszy pomiar", unknown: "Nie sprawdzono",
  no_data: "Brak pomiarów w odpowiedzi", error: "Błąd sprawdzenia",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function jsonRequest(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

function markerIcon(status, selected) {
  return L.divIcon({
    className: "locker-icon",
    html: `<span class="marker-pin ${status} ${selected ? "selected" : ""}"></span>`,
    iconSize: selected ? [31, 31] : [24, 24],
    iconAnchor: selected ? [15, 15] : [12, 12],
  });
}

function renderMarkers() {
  markers.clearLayers();
  markerByCode.clear();
  for (const point of visiblePoints) {
    if (filter === "active" && point.status !== "active") continue;
    const marker = L.marker([point.lat, point.lon], {
      icon: markerIcon(point.status, selectedCode === point.n),
      title: `${point.n}, ${point.city} — ${statusLabels[point.status] || "Nie sprawdzono"}`,
    });
    marker.on("click", () => selectPoint(point.n));
    marker.addTo(markers);
    markerByCode.set(point.n, marker);
  }
}

function setMessage(message, show = true) {
  elements.message.textContent = message;
  elements.message.hidden = !show;
}

async function loadVisible() {
  const version = ++loadingVersion;
  const bounds = map.getBounds();
  const params = new URLSearchParams({
    west: bounds.getWest(), south: bounds.getSouth(),
    east: bounds.getEast(), north: bounds.getNorth(),
  });
  setMessage("Wczytywanie paczkomatów…");
  try {
    const data = await jsonRequest(`/api/points?${params}`);
    if (version !== loadingVersion) return;
    visiblePoints = data.points;
    visibleTruncated = data.truncated;
    elements.count.textContent = `${data.total} w obszarze`;
    renderMarkers();
    if (data.truncated) {
      setMessage(`W obszarze jest ${data.total} punktów. Zbliż mapę, aby zobaczyć wszystkie.`);
      elements.scanStatus.textContent = "Zbliż mapę przed sprawdzaniem punktów.";
    } else {
      setMessage("", false);
      elements.scanStatus.textContent = `Widoczne punkty: ${data.total}. Sprawdź maksymalnie 30 na raz.`;
    }
  } catch (error) {
    if (version === loadingVersion) setMessage(error.message);
  }
}

function timeLabel(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("pl-PL", { dateStyle: "medium", timeStyle: "short" });
}

function measurementsHtml(measurements) {
  const entries = Object.entries(measurements || {});
  if (!entries.length) return "";
  const order = ["PM25", "PM10", "NO2", "O3", "PM1", "PM4", "TEMPERATURE", "HUMIDITY", "PRESSURE"];
  entries.sort(([a], [b]) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib) || a.localeCompare(b);
  });
  return `<div class="measurement-list">${entries.map(([key, item]) => {
    const [name, unit] = labels[key] || [key, ""];
    return `<div class="measurement"><span class="measurement-label">${escapeHtml(name)}</span><div><div class="measurement-value">${escapeHtml(item.value)} <small>${escapeHtml(unit)}</small></div>${item.norm == null ? "" : `<div class="measurement-norm">Norma: ${escapeHtml(item.norm)}</div>`}</div></div>`;
  }).join("")}</div>`;
}

function renderDetail(point, checking = false) {
  const status = point.status || "unknown";
  const hasMeasurements = Object.keys(point.measurements || {}).length > 0;
  const safeUrl = point.page_url || point.url;
  const detailText = status === "no_data"
    ? "Nie znaleziono aktualnej liczbowej wartości czujnika. To nie potwierdza awarii samego urządzenia."
    : status === "unknown"
      ? "Ten paczkomat nie był jeszcze sprawdzany. Kliknij „Sprawdź teraz”, aby pobrać pomiary."
      : status === "error"
        ? `Nie udało się odczytać danych: ${escapeHtml(point.error || "Nieznany błąd")}. Spróbuj ponownie później.`
        : status === "stale"
          ? "Te pomiary mają ponad 15 minut. Sprawdź ponownie przed użyciem ich jako aktualnych."
          : "";
  elements.detailContent.innerHTML = `
    <span class="detail-kicker">PACZKOMAT INPOST</span>
    <h2>${escapeHtml(point.n)}</h2>
    <p class="detail-address">${escapeHtml(point.street)} ${escapeHtml(point.building)}<br />${escapeHtml(point.city)}</p>
    <span class="status-pill ${escapeHtml(status)}">${escapeHtml(statusLabels[status] || status)}</span>
    ${hasMeasurements ? measurementsHtml(point.measurements) : ""}
    ${detailText ? `<p class="detail-muted ${status === "error" ? "detail-error" : ""}">${detailText}</p>` : ""}
    <div class="detail-meta">Ostatnie sprawdzenie: ${timeLabel(point.checked_at)}${point.air_index_level == null ? "" : `<br />Indeks InPost: ${escapeHtml(point.air_index_level)}`}</div>
    <div class="detail-actions"><button id="detail-check" type="button" ${checking ? "disabled" : ""}>${checking ? "Sprawdzanie…" : "Sprawdź teraz"}</button><a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">Strona InPost ↗</a></div>
  `;
  document.getElementById("detail-check").addEventListener("click", () => { checkPoint(point.n).catch(() => {}); });
}

async function selectPoint(code) {
  const version = ++selectionVersion;
  selectedCode = code;
  elements.detail.hidden = false;
  elements.detailContent.innerHTML = "<p class='detail-muted'>Wczytywanie danych…</p>";
  renderMarkers();
  try {
    const point = await jsonRequest(`/api/points/${encodeURIComponent(code)}`);
    if (version !== selectionVersion) return;
    renderDetail(point);
    if (point.status === "unknown" || point.status === "stale") checkPoint(code).catch(() => {});
  } catch (error) {
    if (version === selectionVersion) elements.detailContent.textContent = error.message;
  }
}

async function checkPoint(code) {
  const version = selectionVersion;
  if (selectedCode === code) {
    const cached = await jsonRequest(`/api/points/${encodeURIComponent(code)}`);
    if (version === selectionVersion) renderDetail(cached, true);
  }
  try {
    const point = await jsonRequest(`/api/points/${encodeURIComponent(code)}/check`, { method: "POST" });
    const visible = visiblePoints.find((item) => item.n === code);
    if (visible) visible.status = point.status;
    renderMarkers();
    if (selectedCode === code && version === selectionVersion) renderDetail(point);
    return point;
  } catch (error) {
    if (selectedCode === code && version === selectionVersion) {
      elements.detailContent.innerHTML = `<p class="detail-muted detail-error">${escapeHtml(error.message)}</p>`;
    }
    throw error;
  }
}

async function scanVisible() {
  if (scanning) return;
  if (visibleTruncated) {
    elements.scanStatus.textContent = "Zbliż mapę, aby ograniczyć liczbę punktów.";
    return;
  }
  const candidates = visiblePoints.filter((point) => point.status !== "active").slice(0, 30);
  if (!candidates.length) {
    elements.scanStatus.textContent = "Wszystkie widoczne punkty mają świeże pomiary albo nie ma punktów w obszarze.";
    return;
  }
  scanning = true;
  elements.scan.disabled = true;
  let done = 0;
  for (const point of candidates) {
    try { await checkPoint(point.n); } catch (_) { /* The point remains marked as an error. */ }
    done += 1;
    elements.scanStatus.textContent = `Sprawdzono ${done} z ${candidates.length} punktów…`;
  }
  elements.scanStatus.textContent = `Sprawdzono ${done} punktów. Zielone znaczniki mają aktualne pomiary.`;
  elements.scan.disabled = false;
  scanning = false;
}

let searchTimer;
elements.search.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const query = elements.search.value.trim();
  if (query.length < 2) {
    elements.searchResults.hidden = true;
    return;
  }
  searchTimer = setTimeout(async () => {
    try {
      const data = await jsonRequest(`/api/search?q=${encodeURIComponent(query)}`);
      if (elements.search.value.trim() !== query) return;
      elements.searchResults.innerHTML = data.points.map((point) => `<button class="search-result" data-code="${escapeHtml(point.n)}" type="button"><strong>${escapeHtml(point.n)}</strong><span>${escapeHtml(point.city)} · ${escapeHtml(point.street)} ${escapeHtml(point.building)}</span></button>`).join("") || '<div class="search-result">Brak wyników</div>';
      elements.searchResults.hidden = false;
      elements.searchResults.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
        const point = data.points.find((item) => item.n === button.dataset.code);
        elements.searchResults.hidden = true;
        elements.search.value = point.n;
        map.setView([point.lat, point.lon], 15);
        selectPoint(point.n);
      }));
    } catch (error) { setMessage(error.message); }
  }, 280);
});

elements.filterAll.addEventListener("click", () => {
  filter = "all"; elements.filterAll.classList.add("active"); elements.filterActive.classList.remove("active"); renderMarkers();
});
elements.filterActive.addEventListener("click", () => {
  filter = "active"; elements.filterActive.classList.add("active"); elements.filterAll.classList.remove("active"); renderMarkers();
});
elements.scan.addEventListener("click", scanVisible);
elements.detailClose.addEventListener("click", () => {
  elements.detail.hidden = true; selectedCode = null; selectionVersion += 1; renderMarkers();
});
map.on("moveend", loadVisible);
loadVisible();
