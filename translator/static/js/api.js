export async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
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
