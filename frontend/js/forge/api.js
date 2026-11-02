// Forge API client: JSON calls and the server-sent event stream.

const API = "/api";

// Event names the server sends. "error" is also the browser's name for a
// connection fault, so openEvents tells the two apart by the data field.
export const EVENT_TYPES = [
  "stage", "status", "thought", "cards", "graph", "question", "answered",
  "placed", "review", "explanation", "done", "error", "cancelled",
];
export const TERMINAL = ["done", "error", "cancelled"];

async function request(path, options) {
  const response = await fetch(`${API}${path}`, options);
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = null;
  }
  if (!response.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function post(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

export function getFormats() {
  return request("/forge/formats");
}

export function getCommanders(jobId, format) {
  return request(`/forge/commanders/${encodeURIComponent(jobId)}?format=${encodeURIComponent(format)}`);
}

export function getAiStatus() {
  return request("/ai/status");
}

export function getCollections() {
  return request("/collections");
}

export function getDeck(deckId) {
  return request(`/decks/${encodeURIComponent(deckId)}`);
}

export function startForge(params) {
  return post("/forge", params);
}

export function answer(forgeId, questionId, option) {
  return post(`/forge/${encodeURIComponent(forgeId)}/answer`, { question_id: questionId, option });
}

export function cancel(forgeId) {
  return post(`/forge/${encodeURIComponent(forgeId)}/cancel`);
}

/**
 * Open the event stream of a forge run.
 *
 * EventSource reconnects by itself and sends Last-Event-ID, so the server
 * resumes where the stream stopped. The stream closes after a terminal event.
 *
 * @param {string} forgeId
 * @param {Object<string, function>} handlers Map of event type to handler. The
 *   handler gets the parsed data object and the event id (a number).
 *   The special key "connection" gets true or false when the link changes.
 * @returns {EventSource}
 */
export function openEvents(forgeId, handlers) {
  const source = new EventSource(`${API}/forge/${encodeURIComponent(forgeId)}/events`);
  const call = (type, ...args) => {
    if (handlers && typeof handlers[type] === "function") handlers[type](...args);
  };
  EVENT_TYPES.forEach((type) => {
    source.addEventListener(type, (event) => {
      if (type === "error" && event.data === undefined) {
        call("connection", false);
        return;
      }
      let data = {};
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        data = {};
      }
      call(type, data, Number(event.lastEventId));
      if (TERMINAL.includes(type)) source.close();
    });
  });
  source.addEventListener("open", () => call("connection", true));
  return source;
}
