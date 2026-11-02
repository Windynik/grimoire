// Shared JSON client for the local API. Every failure throws an Error with the
// server's detail text as the message and the HTTP status as error.status.

const API = "/api";

export async function request(path, options) {
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
    if (typeof detail !== "string" || !detail) {
      detail = response.statusText || `Request failed (${response.status})`;
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return data;
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
