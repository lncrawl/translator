// When embedded behind an auth proxy, the host passes an admin token in the URL
// fragment (never sent to the server). Capture it once, send it as a Bearer
// header, and clear it from the URL so it doesn't linger in history.
const AUTH_TOKEN = new URLSearchParams(location.hash.slice(1)).get("token");
if (AUTH_TOKEN) {
  history.replaceState(null, "", location.pathname + location.search);
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (AUTH_TOKEN) headers["Authorization"] = "Bearer " + AUTH_TOKEN;
  let res;
  // Relative to the document base so the app works under a reverse-proxy prefix
  // (lncrawl injects a <base href>); the leading slash would defeat that.
  const url = path.replace(/^\/+/, "");
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw Object.assign(new Error("service unreachable"), { code: "network" });
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (data && data.error) || {};
    throw Object.assign(new Error(detail.message || `HTTP ${res.status}`), {
      code: detail.code || `http_${res.status}`,
      status: res.status,
      retryAfter: detail.retry_after_seconds,
    });
  }
  return data;
}
