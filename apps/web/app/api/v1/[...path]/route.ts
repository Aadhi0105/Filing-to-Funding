const publicRead = /^(?:datasets|companies|overview|peers|funding\/curve|companies\/[0-9]{10}\/(?:periods|analysis|filings|export\.csv))$/;
const providerResource = /^projects\/[0-9]+\/locations\/global\/workloadIdentityPools\/[a-z0-9-]+\/providers\/[a-z0-9-]+$/;
const serviceAccount = /^[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com$/;
const maxBodySize = 4096;

let cached: { token: string; refreshAt: number } | undefined;
let pending: Promise<string> | undefined;

async function exchangeToken(subject: string, provider: string, account: string, audience: string) {
  const exchange = await fetch("https://sts.googleapis.com/v1/token", {
    method: "POST",
    body: new URLSearchParams({
      audience: `//iam.googleapis.com/${provider}`,
      grant_type: "urn:ietf:params:oauth:grant-type:token-exchange",
      requested_token_type: "urn:ietf:params:oauth:token-type:access_token",
      subject_token_type: "urn:ietf:params:oauth:token-type:jwt",
      scope: "https://www.googleapis.com/auth/cloud-platform",
      subject_token: subject,
    }),
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(5000),
  });
  if (!exchange.ok) throw new Error("Vercel identity exchange failed");
  const { access_token: access } = await exchange.json();
  if (typeof access !== "string") throw new Error("Missing exchange token");
  const identity = await fetch(
    `https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${account}:generateIdToken`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${access}`, "Content-Type": "application/json" },
      body: JSON.stringify({ audience, includeEmail: true }),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    },
  );
  if (!identity.ok) throw new Error("Cloud Run identity request failed");
  const { token } = await identity.json();
  if (typeof token !== "string") throw new Error("Missing Cloud Run identity");
  // Google service account ID tokens last one hour.
  cached = { token, refreshAt: Date.now() + 50 * 60 * 1000 };
  return token;
}

function cloudIdentity(subject: string, provider: string, account: string, audience: string) {
  if (cached && cached.refreshAt > Date.now()) return Promise.resolve(cached.token);
  pending ??= exchangeToken(subject, provider, account, audience).finally(() => { pending = undefined; });
  return pending;
}

async function requestBody(request: Request) {
  const reader = request.body?.getReader();
  if (!reader) return new Uint8Array();
  const data = new Uint8Array(maxBodySize);
  let offset = 0;
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) return data.subarray(0, offset);
      if (offset + chunk.value.length > data.length) {
        await reader.cancel();
        return null;
      }
      data.set(chunk.value, offset);
      offset += chunk.value.length;
    }
  } finally {
    reader.releaseLock();
  }
}

async function forward(request: Request) {
  const incoming = new URL(request.url);
  const path = incoming.pathname.slice("/api/v1/".length);
  if (request.method === "POST" ? path !== "funding/scenario" : !publicRead.test(path)) {
    return Response.json({ detail: "Unknown API route" }, { status: 404 });
  }
  const provider = process.env.FILING_GCP_WIF_PROVIDER ?? "";
  const account = process.env.FILING_GCP_INVOKER_ACCOUNT ?? "";
  const subject = request.headers.get("x-vercel-oidc-token");
  const origin = process.env.FILING_API_ORIGIN ?? "";
  const environment = process.env.VERCEL_ENV;
  if ((environment !== "preview" && environment !== "production") || !subject || !providerResource.test(provider) ||
      !serviceAccount.test(account) || !/^https:\/\/[a-z0-9.-]+\.run\.app\/?$/.test(origin)) {
    return Response.json({ detail: "API identity unavailable" }, { status: 503 });
  }

  try {
    const headers = new Headers();
    let body: Uint8Array<ArrayBuffer> | undefined;
    if (request.method === "POST") {
      const type = request.headers.get("content-type") ?? "";
      if (type.split(";")[0].trim().toLowerCase() !== "application/json") {
        return Response.json({ detail: "Expected application/json" }, { status: 415 });
      }
      const bounded = await requestBody(request);
      if (!bounded) return Response.json({ detail: "Request too large" }, { status: 413 });
      body = bounded;
      headers.set("Content-Type", "application/json");
    }
    const base = new URL(origin).origin;
    headers.set("Authorization", `Bearer ${await cloudIdentity(subject, provider, account, base)}`);
    const upstream = await fetch(`${base}/api/v1/${path}${incoming.search}`, {
      method: request.method, headers, body, redirect: "error",
      cache: "no-store", signal: AbortSignal.timeout(15000),
    });
    const outgoing = new Headers({ "Cache-Control": "private, no-store" });
    for (const key of ["Content-Type", "Content-Disposition", "Retry-After"]) {
      const value = upstream.headers.get(key);
      if (value) outgoing.set(key, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch {
    return Response.json({ detail: "The API is unavailable" }, { status: 503 });
  }
}

export const GET = forward;
export const POST = forward;
