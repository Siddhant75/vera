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

export async function sendFeedback(runId, claimId, helpful) {
  return (await fetch(`${BASE}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, claim_id: claimId, helpful }),
  })).json();
}
