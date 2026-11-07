import assert from "node:assert/strict";
import { test } from "node:test";
import worker, { scopes } from "./worker.js";

const env = { STATE_KEY: "k".repeat(32), PUBLIC_ORIGIN: "https://connect.test", TIKTOK_CLIENT_ID: "ck",
  TIKTOK_CLIENT_SECRET: "cs", FACEBOOK_CLIENT_ID: "fb", FACEBOOK_CLIENT_SECRET: "fs" };
const ret = "http://127.0.0.1:51234/api/oauth/tiktok/callback";

test("start → provider → back to this computer → token", async () => {
  const start = await worker.fetch(new Request(`https://connect.test/start/tiktok?return=${encodeURIComponent(ret)}&state=s1&challenge=abc`), env);
  assert.equal(start.status, 302);
  const auth = new URL(start.headers.get("location"));
  assert.equal(auth.origin + auth.pathname, "https://www.tiktok.com/v2/auth/authorize/");
  assert.equal(auth.searchParams.get("client_key"), "ck");
  assert.equal(auth.searchParams.get("redirect_uri"), "https://connect.test/cb/tiktok");
  assert.equal(auth.searchParams.get("code_challenge"), "abc");

  const cb = await worker.fetch(new Request(`https://connect.test/cb/tiktok?code=C1&state=${encodeURIComponent(auth.searchParams.get("state"))}`), env);
  const back = new URL(cb.headers.get("location"));
  assert.equal(back.origin + back.pathname, ret);
  assert.equal(back.searchParams.get("code"), "C1");
  assert.equal(back.searchParams.get("state"), "s1");

  const seen = [];
  globalThis.fetch = async (u, init) => {
    seen.push([String(u), String(init.body)]);
    return new Response(JSON.stringify({ access_token: "a", refresh_token: "r", expires_in: 86400 }), { status: 200 });
  };
  const tok = await worker.fetch(new Request("https://connect.test/token/tiktok", { method: "POST", body: JSON.stringify({ code: "C1", code_verifier: "v" }) }), env);
  assert.equal((await tok.json()).refresh_token, "r");
  const form = new URLSearchParams(seen[0][1]);
  assert.equal(form.get("client_secret"), "cs");
  assert.equal(form.get("redirect_uri"), "https://connect.test/cb/tiktok");
  assert.equal(form.get("code_verifier"), "v");
});

test("refuses foreign return addresses, forged state and unset platforms", async () => {
  const bad = await worker.fetch(new Request(`https://connect.test/start/tiktok?return=${encodeURIComponent("https://evil.example/x")}`), env);
  assert.equal(bad.status, 400);
  const forged = await worker.fetch(new Request("https://connect.test/cb/tiktok?code=x&state=eyJ9.bad"), env);
  assert.equal(forged.status, 400);
  const unset = await worker.fetch(new Request(`https://connect.test/start/youtube?return=${encodeURIComponent(ret)}`), env);
  assert.equal(unset.status, 503);
  const refresh = await worker.fetch(new Request("https://connect.test/refresh/facebook", { method: "POST", body: "{}" }), env);
  assert.equal(refresh.status, 400);
});

test("approved extra scopes are added from variables, anything odd is ignored", () => {
  assert.equal(scopes({}, "tiktok"), "user.info.basic,video.upload,video.publish");
  assert.equal(scopes({ TIKTOK_EXTRA_SCOPES: "video.list" }, "tiktok"), "user.info.basic,video.upload,video.publish,video.list");
  assert.equal(scopes({ LINKEDIN_EXTRA_SCOPES: "r_member_social &x=1" }, "linkedin"), "openid profile w_member_social r_member_social");
});
