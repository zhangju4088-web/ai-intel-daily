from __future__ import annotations

import html
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


def render_digest_html(digest: dict[str, Any]) -> str:
    digest_date = html.escape(str(digest.get("digest_date", "")))
    generated_at = html.escape(str(digest.get("generated_at", "")))
    stats = digest.get("stats", {})
    categories = digest.get("categories", {})
    archive_entries = digest.get("archive_entries", [])
    site_config = build_site_config()
    site_config_json = html.escape(json.dumps(site_config, ensure_ascii=False), quote=False)
    digest_json = html.escape(json.dumps(digest, ensure_ascii=False), quote=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 情报日报 {digest_date}</title>
  <style>
    :root {{
      --bg: #050912;
      --panel: rgba(7, 17, 32, .82);
      --panel-strong: rgba(10, 24, 44, .94);
      --text: #e7f1ff;
      --muted: #8da3bd;
      --line: rgba(118, 154, 190, .22);
      --line-strong: rgba(96, 214, 255, .30);
      --cyan: #5ee7ff;
      --cyan-soft: rgba(94, 231, 255, .10);
      --green: #60f0b7;
      --violet: #a78bfa;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 20% 0%, rgba(20, 184, 166, .16), transparent 34%),
        radial-gradient(circle at 80% 12%, rgba(59, 130, 246, .14), transparent 30%),
        linear-gradient(180deg, #06111f 0%, #050912 52%, #03060b 100%);
      color: var(--text);
      line-height: 1.55;
      overflow-x: hidden;
    }}
    #digital-bg {{
      position: fixed;
      inset: 0;
      z-index: -2;
      pointer-events: none;
    }}
    .grid-glow {{
      position: fixed;
      inset: 0;
      z-index: -1;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(94, 231, 255, .035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(94, 231, 255, .035) 1px, transparent 1px);
      background-size: 26px 26px;
    }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 0 20px; }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(4, 9, 18, .82);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(14px);
    }}
    .head {{
      padding: 18px 0 12px;
      display: grid;
      gap: 12px;
    }}
    .topline {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 14px;
    }}
    h1 {{
      margin: 0 0 4px;
      font-size: 26px;
      line-height: 1.18;
      letter-spacing: 0;
    }}
    .sub {{ color: var(--muted); font-size: 13px; }}
    .stats {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }}
    .stat {{
      min-height: 28px;
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: #b9d4ef;
      background: rgba(9, 22, 40, .62);
      font-size: 12px;
      white-space: nowrap;
    }}
    .search {{
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 11px;
      color: var(--text);
      background: rgba(8, 18, 32, .76);
      font-size: 14px;
      outline: none;
    }}
    .search::placeholder {{ color: #6f849d; }}
    .search:focus {{ border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(94, 231, 255, .12); }}
    .controls {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 190px 112px;
      gap: 10px;
      align-items: center;
    }}
    .date-select {{
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 10px;
      color: var(--text);
      background: rgba(8, 18, 32, .76);
      font-size: 14px;
      outline: none;
    }}
    .date-select:focus {{ border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(94, 231, 255, .12); }}
    .refresh-btn {{
      height: 38px;
      border: 1px solid rgba(94, 231, 255, .45);
      border-radius: 8px;
      background: rgba(94, 231, 255, .12);
      color: var(--text);
      font-size: 14px;
      font-weight: 680;
      cursor: pointer;
      white-space: nowrap;
    }}
    .refresh-btn:hover {{ background: rgba(94, 231, 255, .18); }}
    .refresh-btn:disabled {{ cursor: wait; opacity: .65; }}
    .refresh-status {{
      margin-top: -4px;
      color: var(--muted);
      font-size: 12px;
      min-height: 16px;
    }}
    .tabs {{
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 2px;
      scrollbar-width: thin;
    }}
    .tab {{
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(8, 18, 32, .72);
      color: #b9d4ef;
      min-height: 32px;
      padding: 6px 10px;
      font-size: 13px;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }}
    .tab[aria-selected="true"] {{
      border-color: var(--cyan);
      color: #fff;
      background: var(--cyan-soft);
    }}
    main {{ padding: 18px 0 40px; }}
    .view {{ display: none; }}
    .view.active {{ display: block; }}
    .view-head {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin: 8px 0 10px;
    }}
    h2 {{ margin: 0; font-size: 19px; letter-spacing: 0; }}
    .count {{ color: var(--muted); font-size: 13px; }}
    .list {{ display: flex; flex-direction: column; gap: 8px; }}
    .item {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }}
    .item[data-hidden="true"] {{ display: none; }}
    .item[open] {{ border-color: var(--line-strong); background: var(--panel-strong); }}
    .item summary {{
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 12px;
      cursor: pointer;
      list-style: none;
    }}
    .item summary::-webkit-details-marker {{ display: none; }}
    .score {{
      width: 40px;
      height: 26px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      border: 1px solid rgba(94, 231, 255, .30);
      background: var(--cyan-soft);
      color: var(--cyan);
      font-weight: 800;
      font-size: 12px;
    }}
    .title {{
      min-width: 0;
      font-size: 16px;
      font-weight: 680;
      line-height: 1.36;
      overflow-wrap: anywhere;
    }}
    .side {{
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .body {{ padding: 0 12px 12px 66px; color: #cfe0f2; }}
    .summary {{ margin: 0; color: #dbeafe; }}
    .why {{ margin: 8px 0 0; color: var(--muted); font-size: 14px; }}
    .badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
    .badge {{
      display: inline-flex;
      border: 1px solid rgba(141, 163, 189, .24);
      border-radius: 999px;
      padding: 2px 8px;
      color: #a9bdd3;
      font-size: 12px;
    }}
    .points {{ margin: 10px 0 0; padding-left: 18px; color: #c5d5e8; font-size: 14px; }}
    .points li {{ margin: 3px 0; }}
    .links {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }}
    .links a {{
      max-width: 100%;
      overflow-wrap: anywhere;
      padding: 4px 9px;
      border: 1px solid rgba(167, 139, 250, .36);
      border-radius: 999px;
      background: rgba(88, 54, 168, .18);
      color: #ddd6fe;
      text-decoration: none;
      font-size: 13px;
    }}
    .empty {{
      padding: 16px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      background: rgba(8, 18, 32, .52);
    }}
    .auth-screen {{
      position: fixed;
      inset: 0;
      z-index: 50;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 20px;
      background:
        radial-gradient(circle at 22% 16%, rgba(94, 231, 255, .18), transparent 30%),
        radial-gradient(circle at 82% 8%, rgba(167, 139, 250, .15), transparent 28%),
        rgba(3, 6, 11, .94);
      backdrop-filter: blur(16px);
    }}
    body.auth-required .auth-screen {{ display: flex; }}
    body.auth-required #appShell {{ visibility: hidden; pointer-events: none; }}
    .auth-card {{
      width: min(420px, 100%);
      border: 1px solid var(--line-strong);
      border-radius: 10px;
      background: rgba(7, 17, 32, .92);
      box-shadow: 0 24px 80px rgba(0, 0, 0, .38);
      padding: 22px;
    }}
    .auth-card h2 {{ font-size: 22px; margin-bottom: 6px; }}
    .auth-card p {{ margin: 0 0 16px; color: var(--muted); font-size: 14px; }}
    .auth-field {{ display: grid; gap: 6px; margin-top: 12px; color: #b9d4ef; font-size: 13px; }}
    .auth-field input {{
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      color: var(--text);
      background: rgba(8, 18, 32, .82);
      outline: none;
      font-size: 14px;
    }}
    .auth-field input:focus {{ border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(94, 231, 255, .12); }}
    .auth-row {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; }}
    .auth-remember {{ display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 13px; }}
    .auth-submit {{
      height: 38px;
      min-width: 112px;
      border: 1px solid rgba(94, 231, 255, .50);
      border-radius: 8px;
      background: rgba(94, 231, 255, .16);
      color: var(--text);
      font-weight: 760;
      cursor: pointer;
    }}
    .auth-error {{ min-height: 18px; margin-top: 12px; color: #fecaca; font-size: 13px; }}
    .hidden-json {{ display: none; }}
    @media (max-width: 720px) {{
      .wrap {{ padding: 0 14px; }}
      .topline {{ align-items: flex-start; flex-direction: column; }}
      .stats {{ justify-content: flex-start; }}
      .controls {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 23px; }}
      .item summary {{ grid-template-columns: 40px minmax(0, 1fr); }}
      .side {{ grid-column: 2; }}
      .body {{ padding: 0 12px 12px 12px; }}
    }}
  </style>
</head>
<body>
  <canvas id="digital-bg" aria-hidden="true"></canvas>
  <div class="grid-glow" aria-hidden="true"></div>
  <section id="authScreen" class="auth-screen" aria-label="登录">
    <form id="authForm" class="auth-card">
      <h2>登录 AI 情报日报</h2>
      <p>请输入账号密码后查看内部选题池。</p>
      <label class="auth-field">
        <span>账号</span>
        <input id="authUsername" name="username" autocomplete="username" required>
      </label>
      <label class="auth-field">
        <span>密码</span>
        <input id="authPassword" name="password" type="password" autocomplete="current-password" required>
      </label>
      <div class="auth-row">
        <label class="auth-remember"><input id="authRemember" type="checkbox"> 记住登录</label>
        <button class="auth-submit" type="submit">登录</button>
      </div>
      <div id="authError" class="auth-error" role="alert"></div>
    </form>
  </section>
  <div id="appShell">
  <header>
    <div class="wrap head">
      <div class="topline">
        <div>
          <h1>AI 情报日报 {digest_date}</h1>
          <div class="sub">主页只看今日选题池。切换栏目查看对应情报。</div>
        </div>
        <div class="stats">
          <span class="stat">候选 {stats.get("fetched_candidate_count", 0)}</span>
          <span class="stat">去重 {stats.get("unique_candidate_count", 0)}</span>
          <span class="stat">事件 {stats.get("event_count", 0)}</span>
          <span class="stat">精选 {stats.get("selected_event_count", 0)}</span>
          <span class="stat">更新 {generated_at[:16] if generated_at else ""}</span>
        </div>
      </div>
      <div class="controls">
        <input id="searchInput" class="search" type="search" placeholder="搜索当前视图">
        {render_date_select(archive_entries, digest_date)}
        <button id="refreshButton" class="refresh-btn" type="button">即时抓取</button>
      </div>
      <div id="refreshStatus" class="refresh-status"></div>
      <nav class="tabs" aria-label="栏目">
        <button class="tab" type="button" data-view="topics" aria-selected="true">今日选题池</button>
        {render_tab_buttons(categories)}
      </nav>
    </div>
  </header>
  <main>
    <div class="wrap">
      {render_topics_view(digest.get("topic_pool", []))}
      {''.join(render_category_view(category, events) for category, events in categories.items())}
    </div>
  </main>
  </div>
  <script id="site-config" class="hidden-json" type="application/json">{site_config_json}</script>
  <script id="digest-data" class="hidden-json" type="application/json">{digest_json}</script>
  <script>
    const siteConfig = JSON.parse(document.getElementById('site-config').textContent || '{{}}');
    const input = document.getElementById('searchInput');
    const dateSelect = document.getElementById('dateSelect');
    const refreshButton = document.getElementById('refreshButton');
    const refreshStatus = document.getElementById('refreshStatus');
    const tabs = Array.from(document.querySelectorAll('.tab'));
    const views = Array.from(document.querySelectorAll('.view'));
    let currentView = 'topics';

    async function sha256(text) {{
      const data = new TextEncoder().encode(text);
      const hash = await crypto.subtle.digest('SHA-256', data);
      return Array.from(new Uint8Array(hash)).map(byte => byte.toString(16).padStart(2, '0')).join('');
    }}

    function unlockApp(persist) {{
      document.body.classList.remove('auth-required');
      if (persist) localStorage.setItem('intelhub-auth-ok', '1');
      sessionStorage.setItem('intelhub-auth-ok', '1');
    }}

    async function initAuth() {{
      const auth = siteConfig.auth || {{}};
      if (!auth.enabled) return;
      if (localStorage.getItem('intelhub-auth-ok') === '1' || sessionStorage.getItem('intelhub-auth-ok') === '1') {{
        unlockApp(false);
        return;
      }}
      document.body.classList.add('auth-required');
      const form = document.getElementById('authForm');
      const username = document.getElementById('authUsername');
      const password = document.getElementById('authPassword');
      const remember = document.getElementById('authRemember');
      const error = document.getElementById('authError');
      form.addEventListener('submit', async event => {{
        event.preventDefault();
        error.textContent = '';
        const userOk = username.value.trim() === auth.username;
        const passwordOk = await sha256(password.value) === auth.password_sha256;
        if (!userOk || !passwordOk) {{
          error.textContent = '账号或密码不正确';
          password.value = '';
          password.focus();
          return;
        }}
        unlockApp(remember.checked);
      }});
      username.focus();
    }}

    function setView(name) {{
      currentView = name;
      tabs.forEach(tab => tab.setAttribute('aria-selected', tab.dataset.view === name ? 'true' : 'false'));
      views.forEach(view => view.classList.toggle('active', view.dataset.view === name));
      input.value = '';
      applySearch();
    }}
    tabs.forEach(tab => tab.addEventListener('click', () => setView(tab.dataset.view)));

    function applySearch() {{
      const query = input.value.trim().toLowerCase();
      const active = document.querySelector(`.view[data-view="${{currentView}}"]`);
      if (!active) return;
      active.querySelectorAll('.item').forEach(item => {{
        const visible = !query || (item.dataset.search || '').toLowerCase().includes(query);
        item.dataset.hidden = visible ? 'false' : 'true';
      }});
      active.querySelectorAll('[data-visible-count]').forEach(label => {{
        const visibleCount = active.querySelectorAll('.item[data-hidden="false"]').length;
        label.textContent = visibleCount;
      }});
    }}
    input.addEventListener('input', applySearch);
    if (dateSelect) {{
      dateSelect.addEventListener('change', () => {{
        const date = dateSelect.value;
        if (!date || date === {json.dumps(str(digest.get("digest_date", "")))}) return;
        const inArchive = /\\/archive\\/\\d{{4}}-\\d{{2}}-\\d{{2}}\\/?/.test(location.pathname);
        location.href = inArchive ? `../${{date}}/` : `archive/${{date}}/`;
      }});
    }}
    if (refreshButton) {{
      refreshButton.addEventListener('click', async () => {{
        const refresh = siteConfig.refresh || {{}};
        if (!refresh.webhook_url) {{
          refreshStatus.textContent = '未配置即时抓取接口，已打开 GitHub Actions 手动触发页面。';
          window.open(refresh.action_url, '_blank', 'noopener');
          return;
        }}
        refreshButton.disabled = true;
        refreshStatus.textContent = '正在触发抓取...';
        try {{
          const response = await fetch(refresh.webhook_url, {{
            method: 'POST',
            headers: {{ 'content-type': 'application/json' }},
            body: JSON.stringify({{ digest_date: {json.dumps(str(digest.get("digest_date", "")))}, source: 'site-button' }}),
          }});
          if (!response.ok) throw new Error('HTTP ' + response.status);
          refreshStatus.textContent = '已触发抓取，通常 4-6 分钟后刷新页面可看到最新结果。';
        }} catch (error) {{
          refreshStatus.textContent = '触发失败，请检查即时抓取接口配置。';
        }} finally {{
          refreshButton.disabled = false;
        }}
      }});
    }}

    document.querySelectorAll('.item summary').forEach(summary => {{
      summary.addEventListener('click', event => {{
        event.preventDefault();
        const details = summary.closest('details');
        details.open = !details.open;
      }});
    }});

    const canvas = document.getElementById('digital-bg');
    const ctx = canvas.getContext('2d');
    const pointer = {{ x: -9999, y: -9999 }};
    let cells = [];
    function resizeCanvas() {{
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(innerWidth * ratio);
      canvas.height = Math.floor(innerHeight * ratio);
      canvas.style.width = innerWidth + 'px';
      canvas.style.height = innerHeight + 'px';
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      cells = [];
      for (let y = 10; y < innerHeight; y += 18) {{
        for (let x = 10; x < innerWidth; x += 18) {{
          cells.push({{ x, y, bit: Math.random() > .5 ? '1' : '0', seed: Math.random() }});
        }}
      }}
    }}
    function draw() {{
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      ctx.font = '10px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (const cell of cells) {{
        const dx = cell.x - pointer.x;
        const dy = cell.y - pointer.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const hover = Math.max(0, 1 - dist / 150);
        const alpha = Math.min(.95, .025 + cell.seed * .025 + hover * .82);
        if (alpha < .04) continue;
        ctx.fillStyle = `rgba(94, 231, 255, ${{alpha}})`;
        ctx.fillText(cell.bit, cell.x, cell.y);
      }}
      requestAnimationFrame(draw);
    }}
    window.addEventListener('resize', resizeCanvas);
    window.addEventListener('mousemove', event => {{ pointer.x = event.clientX; pointer.y = event.clientY; }});
    window.addEventListener('mouseleave', () => {{ pointer.x = -9999; pointer.y = -9999; }});
    resizeCanvas();
    draw();
    initAuth();
    setView('topics');
  </script>
</body>
</html>
"""


def build_site_config() -> dict[str, Any]:
    password_hash = os.getenv("SITE_AUTH_PASSWORD_SHA256", "").strip().lower()
    password = os.getenv("SITE_AUTH_PASSWORD", "")
    if password and not password_hash:
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    username = os.getenv("SITE_AUTH_USERNAME", "").strip()
    auth_enabled = bool(username and password_hash)
    refresh_webhook_url = os.getenv("SITE_REFRESH_WEBHOOK_URL", "").strip()
    action_url = os.getenv(
        "SITE_REFRESH_ACTION_URL",
        "https://github.com/zhangju4088-web/ai-intel-daily/actions/workflows/pages-digest.yml",
    ).strip()
    return {
        "auth": {
            "enabled": auth_enabled,
            "username": username if auth_enabled else "",
            "password_sha256": password_hash if auth_enabled else "",
        },
        "refresh": {
            "webhook_url": refresh_webhook_url,
            "action_url": action_url,
        },
    }


def render_tab_buttons(categories: dict[str, list[dict[str, Any]]]) -> str:
    return "".join(
        f'<button class="tab" type="button" data-view="{slug(category)}">{html.escape(category)}</button>'
        for category in categories
    )


def render_date_select(entries: list[dict[str, Any]], current_date: str) -> str:
    if not entries:
        entries = [{"date": current_date}]
    options = []
    seen: set[str] = set()
    for item in entries:
        date = str(item.get("date", "")).strip()
        if not date or date in seen:
            continue
        seen.add(date)
        selected = " selected" if date == current_date else ""
        options.append(f'<option value="{html.escape(date, quote=True)}"{selected}>{html.escape(date)}</option>')
    if current_date and current_date not in seen:
        options.insert(0, f'<option value="{html.escape(current_date, quote=True)}" selected>{html.escape(current_date)}</option>')
    return f'<select id="dateSelect" class="date-select" aria-label="选择日期">{"".join(options)}</select>'


def render_topics_view(topics: list[dict[str, Any]]) -> str:
    rows = []
    for topic in topics[:12]:
        title = html.escape(str(topic.get("title", "")))
        argument = html.escape(str(topic.get("core_argument", "")))
        why = html.escape(str(topic.get("why_today", "")))
        diff = html.escape(str(topic.get("differentiation", "")))
        rank = html.escape(str(topic.get("rank", "")))
        search = html.escape(" ".join([title, argument, why, diff]), quote=True)
        links = render_links(topic.get("reading_links", []))
        rows.append(
            f"""
            <details class="item" data-search="{search}" data-hidden="false">
              <summary>
                <span class="score">{rank}</span>
                <span class="title">{title}</span>
                <span class="side">展开</span>
              </summary>
              <div class="body">
                <p class="summary">{argument}</p>
                <p class="why">{why}</p>
                <p class="why"><strong>差异化：</strong>{diff}</p>
                <div class="links">{links}</div>
              </div>
            </details>
            """
        )
    return render_view("topics", "今日选题池", rows, len(topics), active=True)


def render_category_view(category: str, events: list[dict[str, Any]]) -> str:
    rows = [render_event(event) for event in events]
    return render_view(slug(category), category, rows, len(events))


def render_view(view_id: str, title: str, rows: list[str], total: int, *, active: bool = False) -> str:
    empty = '<div class="empty">暂无内容。</div>' if not rows else ""
    return f"""
    <section class="view{' active' if active else ''}" data-view="{view_id}">
      <div class="view-head">
        <h2>{html.escape(title)}</h2>
        <span class="count">显示 <span data-visible-count>{len(rows)}</span> / {total}</span>
      </div>
      <div class="list">{''.join(rows)}{empty}</div>
    </section>
    """


def render_event(event: dict[str, Any]) -> str:
    title = html.escape(display_title(event))
    summary = html.escape(str(event.get("one_sentence_summary", "")))
    why = html.escape(str(event.get("why_it_matters", "")))
    topic = html.escape(str(event.get("topic_angle", "")))
    avoid = html.escape(str(event.get("avoid_angle", "")))
    score = html.escape(str(event.get("priority_score", "")))
    source_count = html.escape(str(event.get("source_count", 0)))
    source_types = html.escape(" / ".join(str(item) for item in event.get("source_types", [])))
    search = event_search_text(event)
    return f"""
    <details class="item" data-search="{search}" data-hidden="false">
      <summary>
        <span class="score">{score}</span>
        <span class="title">{title}</span>
        <span class="side">来源 {source_count}</span>
      </summary>
      <div class="body">
        <p class="summary">{summary}</p>
        <p class="why">{why}</p>
        <div class="badges">
          <span class="badge">{source_types}</span>
          {render_recommended_badge(event)}
        </div>
        {render_key_points(event.get("key_points", []))}
        <p class="why"><strong>选题角度：</strong>{topic}</p>
        <p class="why"><strong>避开同质化：</strong>{avoid}</p>
        <div class="links">{render_links(event.get("reading_links", []))}</div>
      </div>
    </details>
    """


def display_title(event: dict[str, Any]) -> str:
    title = str(event.get("ai_title") or "").strip()
    category = str(event.get("category") or "")
    if mostly_ascii(title):
        source = ""
        links = event.get("reading_links", [])
        if links:
            source = str(links[0].get("source_name") or "")
        prefix = {
            "大模型动态": "大模型",
            "AI行业资讯": "AI产业",
            "国际形势影响": "国际形势",
            "国际金融": "国际金融",
        }.get(category, "AI情报")
        return f"{prefix}｜{source}：{title}" if source else f"{prefix}｜{title}"
    return title


def mostly_ascii(text: str) -> bool:
    if not text:
        return False
    return sum(1 for char in text if ord(char) < 128) / max(len(text), 1) > 0.72


def render_key_points(points: list[Any]) -> str:
    rows = [f"<li>{html.escape(str(point))}</li>" for point in points[:4] if str(point).strip()]
    return f'<ul class="points">{"".join(rows)}</ul>' if rows else ""


def render_recommended_badge(event: dict[str, Any]) -> str:
    return '<span class="badge">推荐写</span>' if event.get("recommended") else '<span class="badge">观察</span>'


def render_links(links: list[dict[str, Any]]) -> str:
    rows = []
    for link in sorted(links, key=lambda item: int(item.get("display_order") or 100)):
        label = html.escape(str(link.get("link_label") or link.get("source_name") or "阅读原文"))
        source_type = html.escape(str(link.get("source_type", "")))
        url = html.escape(str(link.get("url", "")), quote=True)
        role = " *" if link.get("is_primary_reading_link") else ""
        rows.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}{role} · {source_type}</a>')
    return "".join(rows)


def render_errors(errors: list[dict[str, Any]]) -> str:
    return ""


def event_search_text(event: dict[str, Any]) -> str:
    parts = [
        display_title(event),
        event.get("ai_title", ""),
        event.get("one_sentence_summary", ""),
        event.get("detailed_summary", ""),
        event.get("why_it_matters", ""),
        event.get("topic_angle", ""),
        event.get("avoid_angle", ""),
    ]
    parts.extend(str(item) for item in event.get("key_points", []))
    for link in event.get("reading_links", []):
        parts.extend([link.get("source_name", ""), link.get("source_type", ""), link.get("original_title", "")])
    return html.escape(re.sub(r"\s+", " ", " ".join(str(item) for item in parts)).strip(), quote=True)


def slug(text: str) -> str:
    mapping = {
        "大模型动态": "models",
        "AI行业资讯": "industry",
        "国际形势影响": "geopolitics",
        "国际金融": "finance",
    }
    return mapping.get(text, re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section")


def write_digest_html(digest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_digest_html(digest), encoding="utf-8")


def render_archive_index(entries: list[dict[str, Any]]) -> str:
    return render_archive_standalone(entries)


def render_archive_standalone(entries: list[dict[str, Any]]) -> str:
    rows = []
    for item in entries:
        date = html.escape(str(item.get("date", "")))
        url = html.escape(str(item.get("url", "")), quote=True)
        selected = html.escape(str(item.get("selected_event_count", 0)))
        rows.append(f'<a class="date-link" href="../{url}">{date} · {selected}条</a>')
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 情报日报归档</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #050912; color: #e7f1ff; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 20px; }}
    h1 {{ font-size: 26px; letter-spacing: 0; }}
    .dates {{ display: flex; flex-direction: column; gap: 8px; }}
    .date-link {{ border: 1px solid rgba(118,154,190,.22); border-radius: 8px; padding: 10px 12px; color: #5ee7ff; text-decoration: none; background: rgba(7,17,32,.82); }}
  </style>
</head>
<body>
  <main>
    <h1>AI 情报日报归档</h1>
    <div class="dates">{''.join(rows)}</div>
  </main>
</body>
</html>
"""
