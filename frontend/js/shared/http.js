// Shared JSON client for the local API. Every failure throws an Error with the
// server's detail text as the message and the HTTP status as error.status.

const API = "/api";

// The detail of an error body: a string, or the messages of a list. "" when it has none.
function detailText(data) {
  let detail = data && data.detail;
  if (Array.isArray(detail)) detail = detail.map((d) => d && d.msg).filter(Boolean).join("; ");
  return typeof detail === "string" ? detail : "";
}

/**
 * The reason of a refused Response, for code that reads the response itself:
 * the detail of the server, else the short text and the HTTP status.
 */
export async function refusalText(response, text) {
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = null; // The body is not JSON: the status is the reason.
  }
  return detailText(data) || `${text} Grimoire answered ${response.status}.`;
}

export async function request(path, options) {
  const response = await fetch(`${API}${path}`, options);
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = null;
  }
  if (!response.ok) {
    let detail = detailText(data);
    if (!detail) {
      detail = response.statusText || `Request failed (${response.status})`;
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return data;
}

/**
 * A failure line for the owner: the short text, then the reason of the server
 * when the error has one. An error from request() has the HTTP status. Other
 * errors (a script error, no connection) add nothing, so no raw error text shows.
 */
export function failureText(text, error) {
  const reason = error && error.status ? String(error.message || "").trim() : "";
  return reason ? `${text}: ${reason}` : `${text}.`;
}

function withBody(method, path, body, options) {
  return request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body === undefined ? {} : body),
    ...(options || {}),
  });
}

export function getJSON(path) {
  return request(path);
}

export function postJSON(path, body, options) {
  return withBody("POST", path, body, options);
}

export function putJSON(path, body, options) {
  return withBody("PUT", path, body, options);
}

export function del(path) {
  return request(path, { method: "DELETE" });
}
