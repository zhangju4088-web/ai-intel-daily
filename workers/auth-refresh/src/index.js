const SESSION_TTL_SECONDS = 60 * 60 * 24 * 14;
const PASSWORD_ITERATIONS = 120000;

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(env) });
    }

    try {
      await ensureBootstrapAdmin(env);
      const url = new URL(request.url);
      const path = url.pathname.replace(/\/+$/, "") || "/";

      if (path === "/health" && request.method === "GET") {
        return json(env, { ok: true });
      }
      if (path === "/login" && request.method === "POST") {
        return login(request, env);
      }
      if (path === "/me" && request.method === "GET") {
        const session = await requireUser(request, env);
        return json(env, { user: publicUser(session.user) });
      }
      if (path === "/password" && request.method === "PATCH") {
        const session = await requireUser(request, env);
        return changeOwnPassword(request, env, session.user);
      }
      if (path === "/admin/users" && request.method === "GET") {
        await requireAdmin(request, env);
        return listUsers(env);
      }
      if (path === "/admin/users" && request.method === "POST") {
        await requireAdmin(request, env);
        return createUser(request, env);
      }
      if (path === "/refresh" && request.method === "POST") {
        await requireUser(request, env);
        return triggerRefresh(request, env);
      }

      return json(env, { error: "not_found" }, 404);
    } catch (error) {
      return json(env, { error: error.message || "server_error" }, error.status || 500);
    }
  },
};

async function ensureBootstrapAdmin(env) {
  const username = (env.ADMIN_USERNAME || "admin").trim();
  if (!username || !env.ADMIN_PASSWORD) return;
  const key = userKey(username);
  if (await env.AUTH_KV.get(key)) return;
  const password = await hashPassword(env.ADMIN_PASSWORD);
  await env.AUTH_KV.put(
    key,
    JSON.stringify({
      username,
      role: "admin",
      password,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })
  );
}

async function login(request, env) {
  const body = await readJson(request);
  const username = cleanUsername(body.username);
  const password = String(body.password || "");
  const user = await getUser(env, username);
  if (!user || !(await verifyPassword(password, user.password))) {
    throw httpError("invalid_credentials", 401);
  }
  const token = randomToken();
  await env.AUTH_KV.put(
    sessionKey(token),
    JSON.stringify({ username: user.username, created_at: new Date().toISOString() }),
    { expirationTtl: SESSION_TTL_SECONDS }
  );
  return json(env, { token, user: publicUser(user) });
}

async function changeOwnPassword(request, env, user) {
  const body = await readJson(request);
  const oldPassword = String(body.old_password || "");
  const newPassword = String(body.new_password || "");
  if (newPassword.length < 8) throw httpError("password_too_short", 400);
  if (!(await verifyPassword(oldPassword, user.password))) {
    throw httpError("invalid_old_password", 401);
  }
  user.password = await hashPassword(newPassword);
  user.updated_at = new Date().toISOString();
  await env.AUTH_KV.put(userKey(user.username), JSON.stringify(user));
  return json(env, { ok: true });
}

async function createUser(request, env) {
  const body = await readJson(request);
  const username = cleanUsername(body.username);
  const password = String(body.password || "");
  const role = body.role === "admin" ? "admin" : "user";
  if (!username) throw httpError("invalid_username", 400);
  if (password.length < 8) throw httpError("password_too_short", 400);
  if (await getUser(env, username)) throw httpError("user_exists", 409);

  const user = {
    username,
    role,
    password: await hashPassword(password),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  await env.AUTH_KV.put(userKey(username), JSON.stringify(user));
  return json(env, { user: publicUser(user) }, 201);
}

async function listUsers(env) {
  const list = await env.AUTH_KV.list({ prefix: "user:" });
  const users = [];
  for (const key of list.keys) {
    const user = await env.AUTH_KV.get(key.name, "json");
    if (user) users.push(publicUser(user));
  }
  users.sort((a, b) => a.username.localeCompare(b.username));
  return json(env, { users });
}

async function triggerRefresh(request, env) {
  if (!env.GITHUB_TOKEN) throw httpError("github_token_missing", 500);
  const body = await readJson(request);
  const digestDate = String(body.digest_date || new Date().toISOString().slice(0, 10));
  const owner = env.GITHUB_OWNER || "zhangju4088-web";
  const repo = env.GITHUB_REPO || "ai-intel-daily";
  const workflow = env.GITHUB_WORKFLOW || "pages-digest.yml";
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "ai-intel-auth-refresh-worker",
    },
    body: JSON.stringify({
      ref: "main",
      inputs: {
        digest_date: digestDate,
        extract_limit: "16",
      },
    }),
  });
  if (!response.ok) {
    throw httpError("github_dispatch_failed", 502);
  }
  return json(env, { ok: true, digest_date: digestDate });
}

async function requireAdmin(request, env) {
  const session = await requireUser(request, env);
  if (session.user.role !== "admin") throw httpError("forbidden", 403);
  return session;
}

async function requireUser(request, env) {
  const auth = request.headers.get("authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  if (!token) throw httpError("unauthorized", 401);
  const session = await env.AUTH_KV.get(sessionKey(token), "json");
  if (!session?.username) throw httpError("unauthorized", 401);
  const user = await getUser(env, session.username);
  if (!user) throw httpError("unauthorized", 401);
  return { token, user };
}

async function getUser(env, username) {
  return env.AUTH_KV.get(userKey(username), "json");
}

async function hashPassword(password) {
  const salt = randomToken(16);
  const key = await crypto.subtle.importKey("raw", textBytes(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: hexBytes(salt), iterations: PASSWORD_ITERATIONS },
    key,
    256
  );
  return { salt, hash: bytesHex(new Uint8Array(bits)), iterations: PASSWORD_ITERATIONS };
}

async function verifyPassword(password, stored) {
  if (!stored?.salt || !stored?.hash) return false;
  const key = await crypto.subtle.importKey("raw", textBytes(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: hexBytes(stored.salt), iterations: stored.iterations || PASSWORD_ITERATIONS },
    key,
    256
  );
  return timingSafeEqual(bytesHex(new Uint8Array(bits)), stored.hash);
}

function publicUser(user) {
  return {
    username: user.username,
    role: user.role === "admin" ? "admin" : "user",
    created_at: user.created_at,
    updated_at: user.updated_at,
  };
}

async function readJson(request) {
  return request.json().catch(() => ({}));
}

function cleanUsername(username) {
  return String(username || "").trim().toLowerCase().replace(/[^a-z0-9_.-]/g, "").slice(0, 64);
}

function userKey(username) {
  return `user:${username}`;
}

function sessionKey(token) {
  return `session:${token}`;
}

function randomToken(bytes = 32) {
  const array = new Uint8Array(bytes);
  crypto.getRandomValues(array);
  return bytesHex(array);
}

function textBytes(text) {
  return new TextEncoder().encode(text);
}

function bytesHex(bytes) {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function hexBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i += 1) {
    bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

function timingSafeEqual(left, right) {
  if (left.length !== right.length) return false;
  let result = 0;
  for (let i = 0; i < left.length; i += 1) {
    result |= left.charCodeAt(i) ^ right.charCodeAt(i);
  }
  return result === 0;
}

function httpError(message, status) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function json(env, data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json",
      ...corsHeaders(env),
    },
  });
}

function corsHeaders(env) {
  return {
    "access-control-allow-origin": env.ALLOWED_ORIGIN || "https://zhangju4088-web.github.io",
    "access-control-allow-methods": "GET, POST, PATCH, OPTIONS",
    "access-control-allow-headers": "content-type, authorization",
  };
}
