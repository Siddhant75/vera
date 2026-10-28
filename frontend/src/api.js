const BASE = "http://localhost:8000";

export async function getProfile() {
  return (await fetch(`${BASE}/api/profile`)).json();
}

export async function saveProfile(p) {
  return (await fetch(`${BASE}/api/profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(p),
  })).json();
}

export async function runResearch({ brief, topic, persona, delta }) {
  const r = await fetch(`${BASE}/api/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief, topic: topic || "", persona: persona || "", delta: !!delta }),
  });
  return (await r.json()).run_id;
}

export function openEventStream(runId, onEvent) {
  const es = new EventSource(`${BASE}/api/runs/${runId}/events`);
  es.onmessage = (m) => onEvent(JSON.parse(m.data));
  es.onerror = () => es.close();
  return es;
}

export async function getReport(runId) {
  return (await fetch(`${BASE}/api/report/${runId}`)).json();
}

export async function getTelemetry() {
  return (await fetch(`${BASE}/api/telemetry`)).json();
}

export async function sendFeedback(runId, claimId, helpful, claimText) {
  return (await fetch(`${BASE}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, claim_id: claimId, helpful, claim_text: claimText || "" }),
  })).json();
}

export async function addWatch(topic, brief, persona, intervalHours = 6) {
  return (await fetch(`${BASE}/api/watch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, brief, persona, interval_hours: intervalHours }),
  })).json();
}

export async function listWatches() {
  return (await fetch(`${BASE}/api/watch`)).json();
}

export async function removeWatch(id) {
  return (await fetch(`${BASE}/api/watch/${id}`, { method: "DELETE" })).json();
}

export async function listSkills() {
  return (await fetch(`${BASE}/api/skills`)).json();
}

export async function saveSkill(skill) {
  return (await fetch(`${BASE}/api/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(skill),
  })).json();
}

export async function deleteSkill(name) {
  return (await fetch(`${BASE}/api/skills/${encodeURIComponent(name)}`, { method: "DELETE" })).json();
}

export async function runSkill(name) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(name)}/run`, { method: "POST" });
  return (await r.json()).run_id;
}
