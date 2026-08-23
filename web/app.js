const OCEAN_LAYER_URL = "./data/ocean_conditions.json";

const chatThread = document.querySelector("#chat-thread");
const statusPill = document.querySelector("#status-pill");
const waveChart = document.querySelector("#wave-chart");

let map;
let oceanLayerGroup;

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json();
}

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

function initMap() {
  map = L.map("map", {
    zoomControl: false,
    scrollWheelZoom: true,
  }).setView([39.55, 2.75], 8);

  L.control.zoom({ position: "bottomleft" }).addTo(map);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 12,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  oceanLayerGroup = L.layerGroup().addTo(map);
}

function waveColor(value) {
  if (value < 0.6) return "#49d8d1";
  if (value < 1.0) return "#67d785";
  if (value < 1.5) return "#d7c85b";
  if (value < 2.0) return "#e88a48";
  return "#ef5f5f";
}

function waveOpacity(value) {
  return Math.min(0.66, Math.max(0.25, 0.18 + value * 0.22));
}

function renderWaveField(layer) {
  const cellLat = 0.08;
  const cellLon = 0.084;
  for (const point of layer.wave_points) {
    const bounds = [
      [point.lat - cellLat / 2, point.lon - cellLon / 2],
      [point.lat + cellLat / 2, point.lon + cellLon / 2],
    ];
    L.rectangle(bounds, {
      stroke: false,
      fillColor: waveColor(point.wave_m),
      fillOpacity: waveOpacity(point.wave_m),
      interactive: true,
    })
      .bindTooltip(`${point.wave_m.toFixed(2)} m wave height`, {
        direction: "top",
        opacity: 0.92,
      })
      .addTo(oceanLayerGroup);
  }
}

function renderCurrentVectors(layer) {
  for (const point of layer.current_points) {
    const size = Math.max(22, Math.min(42, 18 + point.speed_kn * 42));
    const icon = L.divIcon({
      className: "current-vector",
      html: `<span style="--rotation:${point.direction_deg}deg; --size:${size}px;">&#8594;</span>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    });
    L.marker([point.lat, point.lon], { icon, interactive: true })
      .bindTooltip(`${point.speed_kn.toFixed(2)} kn current`, {
        direction: "top",
        opacity: 0.92,
      })
      .addTo(oceanLayerGroup);
  }
}

function renderOceanLayer(layer) {
  oceanLayerGroup.clearLayers();
  renderWaveField(layer);
  renderCurrentVectors(layer);
  map.fitBounds(
    [
      [layer.bounds.south, layer.bounds.west],
      [layer.bounds.north, layer.bounds.east],
    ],
    { padding: [34, 34] },
  );
}

function updateMetrics(layer) {
  const summary = layer.summary;
  setText("#run-date", `Model slice ${layer.time}`);
  setText("#hero-route", "Balearic sea-state layer");
  setText("#metric-now", `${summary.wave_mean_m.toFixed(2)} m`);
  setText("#metric-peak", `${summary.wave_max_m.toFixed(2)} m`);
  setText("#metric-current", `${summary.current_max_kn.toFixed(2)} kn`);
  setText("#metric-confidence", "Model field");
  setText("#wave-range", `${summary.wave_min_m.toFixed(2)} to ${summary.wave_max_m.toFixed(2)} m`);

  const label = summary.wave_max_m >= 1.5 ? "Watch" : "Manageable";
  statusPill.textContent = label;
  statusPill.className = `status-pill ${summary.wave_max_m >= 1.5 ? "caution" : ""}`;
}

function renderChat(layer) {
  const summary = layer.summary;
  const messages = [
    {
      speaker: "captain",
      text: "Show me the sea state around the Balearics.",
    },
    {
      speaker: "predsea",
      text: `This map is showing significant wave height as the sea color layer and surface currents as arrows.`,
    },
    {
      speaker: "predsea",
      text: `For this model slice, waves range from ${summary.wave_min_m.toFixed(2)} m to ${summary.wave_max_m.toFixed(2)} m, with mean current around ${summary.current_mean_kn.toFixed(2)} kn.`,
    },
    {
      speaker: "predsea",
      text: "The captain's job is no longer to decode raw data. PredSea turns the field into operational evidence before the go/no-go decision.",
    },
  ];

  chatThread.replaceChildren();
  for (const message of messages) {
    const bubble = document.createElement("div");
    bubble.className = `message ${message.speaker}`;
    bubble.textContent = message.text;
    chatThread.appendChild(bubble);
  }
}

function renderWaveChart(layer) {
  waveChart.replaceChildren();
  const buckets = [0, 0, 0, 0, 0];
  for (const point of layer.wave_points) {
    const index = Math.min(4, Math.floor(point.wave_m / 0.5));
    buckets[index] += 1;
  }
  const maxBucket = Math.max(...buckets);
  const width = 420;
  const height = 88;
  const gap = 10;
  const barWidth = (width - gap * 6) / 5;

  buckets.forEach((value, index) => {
    const barHeight = maxBucket === 0 ? 0 : (value / maxBucket) * 54;
    const x = gap + index * (barWidth + gap);
    const y = height - 22 - barHeight;
    const color = waveColor(index * 0.5 + 0.25);
    waveChart.insertAdjacentHTML(
      "beforeend",
      `<rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="4" fill="${color}" opacity="0.82"></rect>`,
    );
  });

  waveChart.insertAdjacentHTML(
    "beforeend",
    `
      <text x="10" y="18" fill="#a9b6b2" font-size="11">Wave-height distribution</text>
      <text x="10" y="82" fill="#a9b6b2" font-size="11">0m</text>
      <text x="350" y="82" fill="#a9b6b2" font-size="11">2m+</text>
    `,
  );
}

async function main() {
  initMap();
  const oceanLayer = await loadJson(OCEAN_LAYER_URL);
  renderOceanLayer(oceanLayer);
  updateMetrics(oceanLayer);
  renderChat(oceanLayer);
  renderWaveChart(oceanLayer);
}

main().catch((error) => {
  console.error(error);
  document.body.classList.add("has-error");
  chatThread.innerHTML = `<div class="message predsea">Ocean layer could not be loaded. Serve this page from the repository root so it can read web/data/ocean_conditions.json.</div>`;
});
