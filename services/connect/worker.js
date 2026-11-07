// STARK Connect: the Nexonic token server behind "Log in with ..." in STARK OS.
// Holds each platform's app secret, so the desktop app never ships one. It only relays the sign-in back to
// the user's own computer (http://127.0.0.1:<port>) and exchanges codes for tokens; it stores nothing.
// Deploy: see docs/CONNECT_APPS.md.

const META = "https://graph.facebook.com/v23.0";
export const PROVIDERS = {
  facebook: {
    auth: "https://www.facebook.com/v23.0/dialog/oauth",
    token: `${META}/oauth/access_token`,
    scope: "pages_show_list,pages_manage_posts,pages_read_engagement,business_management",
    sep: ",",
  },
  instagram: {
    auth: "https://www.instagram.com/oauth/authorize",
    token: "https://api.instagram.com/oauth/access_token",
    scope: "instagram_business_basic,instagram_business_content_publish",
    sep: ",",
  },
  threads: {
    auth: "https://threads.net/oauth/authorize",
    token: "https://graph.threads.net/oauth/access_token",
    scope: "threads_basic,threads_content_publish,threads_manage_insights",
    sep: ",",
  },
  linkedin: {
    auth: "https://www.linkedin.com/oauth/v2/authorization",
    token: "https://www.linkedin.com/oauth/v2/accessToken",
    scope: "openid profile w_member_social",
    sep: " ",
  },
  tiktok: {
    auth: "https://www.tiktok.com/v2/auth/authorize/",
    token: "https://open.tiktokapis.com/v2/oauth/token/",
    scope: "user.info.basic,video.upload,video.publish",
    sep: ",",
    idParam: "client_key",
    pkce: true,
  },
  youtube: {
    auth: "https://accounts.google.com/o/oauth2/v2/auth",
    token: "https://oauth2.googleapis.com/token",
    scope: "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
    sep: " ",
    pkce: true,
    extra: { access_type: "offline", prompt: "consent" },
  },
  pinterest: {
    auth: "https://www.pinterest.com/oauth/",
    token: "https://api.pinterest.com/v5/oauth/token",
    scope: "boards:read,pins:read,pins:write,user_accounts:read",
    sep: ",",
    basic: true,
  },
};

const RETURN_RE = /^http:\/\/127\.0\.0\.1:\d{2,5}\/api\/oauth\/([a-z]+)\/callback$/;
const MAX_AGE_MS = 15 * 60 * 1000;
const enc = new TextEncoder();
const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = (s) => atob(s.replace(/-/g, "+").replace(/_/g, "/"));

async function hmac(key, data) {
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64u(await crypto.subtle.sign("HMAC", k, enc.encode(data)));
}

function creds(env, p) {
  const id = env[`${p.toUpperCase()}_CLIENT_ID`];
  const secret = env[`${p.toUpperCase()}_CLIENT_SECRET`];
  return id && secret ? { id, secret } : null;
}

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

async function exchange(env, p, origin, form) {
  const prov = PROVIDERS[p];
  const c = creds(env, p);
  const body = new URLSearchParams({ [prov.idParam || "client_id"]: c.id, ...form });
  const headers = { "content-type": "application/x-www-form-urlencoded", accept: "application/json" };
  if (prov.basic) headers.authorization = "Basic " + btoa(`${c.id}:${c.secret}`);
  else body.set("client_secret", c.secret);
  if (form.code) body.set("redirect_uri", `${origin}/cb/${p}`);
  const r = await fetch(prov.token, { method: "POST", headers, body });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data.error) return { error: data.error_description || data.error?.message || data.error || `HTTP ${r.status}` };
  return data;
}

async function longLived(env, p, data) {
  // Meta's sign-in returns a short-lived token; swap it for a 60-day one (Pages derived from it never expire).
  const c = creds(env, p);
  let url;
  if (p === "facebook")
    url = `${META}/oauth/access_token?grant_type=fb_exchange_token&client_id=${c.id}&client_secret=${c.secret}&fb_exchange_token=${data.access_token}`;
  else if (p === "instagram")
    url = `https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=${c.secret}&access_token=${data.access_token}`;
  else if (p === "threads")
    url = `https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=${c.secret}&access_token=${data.access_token}`;
  else return data;
  const r = await fetch(url);
  const ll = await r.json().catch(() => ({}));
  return r.ok && ll.access_token ? { ...data, ...ll } : data;
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = env.PUBLIC_ORIGIN || url.origin;
    const [, action, p] = url.pathname.split("/");
    if (action === "" || action === "health") return json({ ok: true, platforms: Object.keys(PROVIDERS).filter((x) => creds(env, x)) });
    if (!PROVIDERS[p]) return json({ error: "unknown platform" }, 404);
    if (!creds(env, p)) return json({ error: `Login with ${p} is not set up on this server yet` }, 503);
    const prov = PROVIDERS[p];

    if (action === "start" && req.method === "GET") {
      const ret = url.searchParams.get("return") || "";
      const m = RETURN_RE.exec(ret);
      if (!m || m[1] !== p) return json({ error: "bad return address" }, 400);
      const payload = b64u(enc.encode(JSON.stringify({ r: ret, s: url.searchParams.get("state") || "", p, t: Date.now() })));
      const state = `${payload}.${await hmac(env.STATE_KEY, payload)}`;
      const q = new URLSearchParams({
        [prov.idParam || "client_id"]: creds(env, p).id,
        redirect_uri: `${origin}/cb/${p}`,
        response_type: "code",
        scope: prov.scope,
        state,
        ...(prov.extra || {}),
      });
      const challenge = url.searchParams.get("challenge");
      if (prov.pkce && challenge) {
        q.set("code_challenge", challenge);
        q.set("code_challenge_method", "S256");
      }
      return Response.redirect(`${prov.auth}?${q}`, 302);
    }

    if (action === "cb" && req.method === "GET") {
      const [payload, sig] = (url.searchParams.get("state") || "").split(".");
      if (!payload || sig !== (await hmac(env.STATE_KEY, payload))) return json({ error: "bad state" }, 400);
      const st = JSON.parse(unb64u(payload));
      if (st.p !== p || Date.now() - st.t > MAX_AGE_MS || !RETURN_RE.test(st.r)) return json({ error: "expired" }, 400);
      const back = new URL(st.r);
      back.searchParams.set("state", st.s);
      const code = url.searchParams.get("code");
      if (code) back.searchParams.set("code", code.replace(/#_$/, ""));
      else back.searchParams.set("error", url.searchParams.get("error") || "cancelled");
      return Response.redirect(back.toString(), 302);
    }

    if ((action === "token" || action === "refresh") && req.method === "POST") {
      const body = await req.json().catch(() => ({}));
      let data;
      if (action === "token") {
        if (!body.code) return json({ error: "missing code" }, 400);
        const form = { code: body.code, grant_type: "authorization_code" };
        if (prov.pkce && body.code_verifier) form.code_verifier = body.code_verifier;
        data = await exchange(env, p, origin, form);
        if (!data.error) data = await longLived(env, p, data);
      } else {
        if (!body.refresh_token || !["tiktok", "youtube", "pinterest"].includes(p)) return json({ error: "not refreshable" }, 400);
        data = await exchange(env, p, origin, { grant_type: "refresh_token", refresh_token: body.refresh_token });
      }
      return json(data, data.error ? 400 : 200);
    }
    return json({ error: "not found" }, 404);
  },
};
