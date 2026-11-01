/* Fact or Fluke: renders data/*.json (written by the daily run) into three tabs. No framework, no build. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => `${Math.round(x * 100)}%`;
const signed = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)}%`;
const units = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(2)}u`;
const ET = "America/New_York";
const tipTime = (iso) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: ET });
const longDate = (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-US",
  { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
const ordinal = (n) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th")}`;
const clampPct = (v) => `${(Math.min(Math.max(v, 0), 1) * 100).toFixed(1)}%`;

const WHY = { elo: "Elo", home: "主場", b2b: "背靠背", rest: "休息天數", tif: "4 天 3 戰" };
const STATUS = { listed: "上榜", observing: "觀察中", eliminated: "淘汰" };
const TABS = ["today", "standings", "lastnight"];

const state = { tab: "today", season: 0, status: "listed", team: "" };
const DATA = {};

async function load(name) {
  const res = await fetch(new URL(`data/${name}.json`, window.location.href), { cache: "no-cache" });
  if (!res.ok) throw new Error(`${name}.json ${res.status}`);
  return res.json();
}

/* ---------- Today ---------- */

function strip(card) {
  const y = card.yesterday || {}, all = card.all || {}, b = card.bets || {};
  const cell = (dt, dd, sub) => `<div><dt>${dt}</dt><dd>${dd}<span class="sub">${sub}</span></dd></div>`;
  return `<dl class="strip">
    ${cell("昨天 · 模型", y.n ? `${y.model_correct}/${y.n}` : "—",
           y.market_n ? `賭盤 ${y.market_correct}/${y.market_n}` : "還沒有結果")}
    ${cell("本季 · 模型", all.n ? `${all.model_correct}/${all.n}` : "—",
           all.market_n ? `賭盤 ${all.market_correct}/${all.market_n}` : "從 11/1 開始記")}
    ${cell("模擬帳本", b.n ? `<span class="${b.profit >= 0 ? "pos" : "neg"}">${units(b.profit)}</span>` : "—",
           b.n ? `稅後 ${units(b.profit_after_tax)} · ${b.n} 注` : "還沒有結算的注")}
  </dl>`;
}

function gameBlock(p) {
  const { home, away } = p, ph = p.p_home, mk = p.market_p_home;
  const fav = ph >= 0.5 ? home : away;
  const a = (1 - ph) * 100, m = mk == null ? null : (1 - mk) * 100;
  let probs = `<span>模型 <b>${fav} ${pct(Math.max(ph, 1 - ph))}</b></span>`;
  if (mk != null) probs += `<span>賭盤 <b>${mk >= 0.5 ? home : away} ${pct(Math.max(mk, 1 - mk))}</b></span>`;
  let value = `<p class="game__novalue">還沒有賠率</p>`;
  if (p.pick) {
    const [price, book] = p.best[p.pick];
    value = `<p class="game__value"><span class="dot" aria-hidden="true"></span><span>划算：${p.pick} ${price.toFixed(2)} @${esc(book)}（期望值 ${signed(p.ev[p.pick])}）</span></p>`;
  } else if (p.suspect) {
    value = `<p class="game__novalue">模型和賭盤差太多（${p.suspect} 期望值 ${signed(p.ev[p.suspect])}），多半是模型還不知道的消息，例如傷兵，這注不算</p>`;
  } else if (p.best && p.best[fav] && p.best[fav][0]) {
    const [price, book] = p.best[fav];
    value = `<p class="game__novalue">沒有划算的注（${fav} 最佳 ${price.toFixed(2)} @${esc(book)}，期望值 ${signed(p.ev[fav])}）</p>`;
  }
  const why = Object.entries(p.why || {})
    .filter(([, v]) => Math.abs(v) >= 0.005)
    .sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]))
    .map(([k, v]) => `<li>${WHY[k] || k} → <b>${v > 0 ? home : away} +${Math.round(Math.abs(v) * 100)}</b></li>`)
    .join("");
  const label = `模型：${away} ${pct(1 - ph)}、${home} ${pct(ph)}` + (mk != null ? `；賭盤：${home} ${pct(mk)}` : "");
  return `<article class="game">
    <header class="game__head">
      <time class="game__time" datetime="${esc(p.tip_utc)}">${tipTime(p.tip_utc)}</time>
      <h2 class="game__matchup">${away}<span class="at">@</span>${home}</h2>
    </header>
    <div class="wp" role="img" aria-label="${label}">
      <span class="wp__team${fav === away ? " is-fav" : ""}">${away}</span>
      <div class="wp__bar" style="--a:${a.toFixed(1)}%${m != null ? `;--m:${m.toFixed(1)}%` : ""}">
        <i class="wp__away"></i><i class="wp__model"></i>${m != null ? `<i class="wp__market"></i>` : ""}
      </div>
      <span class="wp__team wp__team--home${fav === home ? " is-fav" : ""}">${home}</span>
    </div>
    <p class="game__probs">${probs}</p>
    ${value}
    ${why ? `<ul class="why" aria-label="各因素讓勝率移動的百分點"><li>為什麼：</li>${why}</ul>` : ""}
  </article>`;
}

function renderToday() {
  const t = DATA.today, games = t.games || [];
  $("#view-today").innerHTML = `
    <header class="view__head">
      <h1 class="view__title">Today</h1>
      <p class="view__sub">${longDate(t.day)} · ${games.length} 場 · 模型：Elo＋賽程情境（基準版）· 賭盤：麻州 5 家<br>
        <span class="legend"><i class="swatch"></i>模型</span><span class="legend"><i class="swatch swatch--market"></i>賭盤</span>
      </p>
    </header>
    ${strip(t.scorecard || {})}
    ${games.length ? games.map(gameBlock).join("") : `<p class="empty">今天沒有比賽</p>`}`;
}

/* ---------- Standings ---------- */

function factRow(f) {
  const rank = f.status === "listed"
    ? `<span class="fact__rank">${f.rank}</span>`
    : `<span class="fact__rank fact__rank--muted">${STATUS[f.status]}</span>`;
  const out = f.status === "eliminated" && f.eliminated_on ? ` · ${esc(f.eliminated_on)} 淘汰` : "";
  return `<li class="fact">${rank}<div>
    <p class="fact__zh" lang="zh-Hant">${esc(f.text_zh)}</p>
    <p class="fact__en">${esc(f.text_en)}</p>
    <p class="fact__basis">${esc(f.basis_zh)} · <b>${esc(f.team)}</b>${out}</p>
    <div class="scale" role="img" aria-label="${pct(f.rate)}，比較基準 ${pct(f.p0)}">
      <i class="scale__base" style="--x:${clampPct(f.p0)}"></i><i class="scale__dot" style="--x:${clampPct(f.rate)}"></i>
    </div>
  </div></li>`;
}

function renderStandings() {
  const seasons = DATA.standings.seasons || [];
  const s = seasons[state.season] || seasons[0] || {};
  const list = s[state.status] || [];
  // observing / eliminated ship the league-wide top (top: true) plus each team's strongest few
  const shown = state.team ? list.filter((f) => f.team === state.team) : list.filter((f) => f.top !== false);
  const counts = s.counts || {};
  const total = counts[state.status] ?? list.length;
  const note = state.status === "listed" || !shown.length ? ""
    : !state.team && shown.length < total ? `<p class="list-note">證據最強的 ${shown.length} 則，共 ${total} 則。選球隊可以看各隊的。</p>`
    : state.team && shown.length >= 10 ? `<p class="list-note">${esc(state.team)} 證據最強的 ${shown.length} 則</p>` : "";
  const teams = DATA.meta.teams || {}, followed = DATA.meta.followed || [];
  const opt = (c) => `<option value="${c}"${c === state.team ? " selected" : ""}>${c} · ${esc(teams[c] || c)}</option>`;
  const others = Object.keys(teams).filter((c) => !followed.includes(c)).sort();
  let empty = `<p class="empty">這個條件下沒有 fun fact</p>`;
  if (!list.length && state.status === "listed" && state.season === 0 && seasons.length > 1) {
    empty = `<div class="empty"><p>本季還沒有 fun fact 上榜：開季才兩週，樣本還小，證據會隨比賽累積。</p>
      <div class="seg"><button type="button" data-season="1">看 ${esc(seasons[1].label.replace(" demo", ""))} 示範榜</button></div></div>`;
  }
  $("#view-standings").innerHTML = `
    <header class="view__head">
      <h1 class="view__title">Standings</h1>
      <p class="view__sub">整季累積的 fun fact 排行榜，數據佐證越強排越前面。每則都寫了根據幾次，你自己判斷。</p>
    </header>
    <div class="controls">
      <div class="seg" role="group" aria-label="球季">${seasons.map((x, i) =>
        `<button type="button" aria-pressed="${i === state.season}" data-season="${i}">${esc(x.label.replace(" demo", " 示範"))}</button>`).join("")}</div>
      <div class="seg" role="group" aria-label="狀態">${Object.keys(STATUS).map((k) =>
        `<button type="button" aria-pressed="${k === state.status}" data-status="${k}">${STATUS[k]} ${counts[k] ?? (s[k] || []).length}</button>`).join("")}</div>
      <label class="visually-hidden" for="team">球隊</label>
      <select class="select" id="team">
        <option value="">全部球隊</option>
        <optgroup label="關注">${followed.map(opt).join("")}</optgroup>
        <optgroup label="其他">${others.map(opt).join("")}</optgroup>
      </select>
    </div>
    ${note}
    ${shown.length ? `<ol class="facts">${shown.map(factRow).join("")}</ol>` : empty}`;
}

/* ---------- Last Night ---------- */

function scoreRow(g) {
  if (!g.final) return `<li class="score"><span class="score__line">${g.away} @ ${g.home}</span><span class="score__marks">未完賽</span></li>`;
  const homeWon = g.home_score > g.away_score;
  const marks = [g.model_right == null ? "" : `模型${g.model_right ? "猜中" : "猜錯"}`,
                 g.market_right == null ? "" : `賭盤${g.market_right ? "猜中" : "猜錯"}`].filter(Boolean).join(" · ");
  return `<li class="score">
    <span class="score__line"><span class="${homeWon ? "l" : "w"}">${g.away} ${g.away_score}</span>
      – <span class="${homeWon ? "w" : "l"}">${g.home_score} ${g.home}</span></span>
    <span class="score__marks">${marks}</span>
  </li>`;
}

function renderLastNight() {
  const l = DATA.lastnight, recs = l.records || [], games = l.games || [];
  $("#view-lastnight").innerHTML = `
    <header class="view__head">
      <h1 class="view__title">Last night</h1>
      <p class="view__sub">${longDate(l.day)} · ${games.length} 場</p>
    </header>
    <h2 class="section-label">紀錄</h2>
    ${recs.length ? `<ol class="records">${recs.map((r) => `<li class="record">
        <span class="record__nth">${ordinal(r.count)}<small>time</small></span>
        <div><p class="record__zh" lang="zh-Hant">${esc(r.text_zh)}</p><p class="record__en">${esc(r.text_en)}</p></div>
      </li>`).join("")}</ol>` : `<p class="empty">昨晚沒有夠稀有的紀錄</p>`}
    <h2 class="section-label">比分</h2>
    ${games.length ? `<ol class="scores">${games.map(scoreRow).join("")}</ol>` : `<p class="empty">昨晚沒有比賽</p>`}`;
}

/* ---------- shell ---------- */

const RENDER = { today: renderToday, standings: renderStandings, lastnight: renderLastNight };

function show(tab, { focus = false } = {}) {
  state.tab = TABS.includes(tab) ? tab : "today";
  for (const t of TABS) {
    const btn = $(`#tab-${t}`), view = $(`#view-${t}`);
    btn.setAttribute("aria-selected", String(t === state.tab));
    btn.tabIndex = t === state.tab ? 0 : -1;
    view.hidden = t !== state.tab;
  }
  if (focus) $(`#tab-${state.tab}`).focus();
  history.replaceState(null, "", `#${state.tab}`);
  window.scrollTo({ top: 0 });
}

function bind() {
  $(".tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) show(b.dataset.tab);
  });
  $(".tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const i = TABS.indexOf(state.tab) + (e.key === "ArrowRight" ? 1 : -1);
    show(TABS[(i + TABS.length) % TABS.length], { focus: true });
  });
  $("#view-standings").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.season != null) { state.season = Number(b.dataset.season); state.status = "listed"; }
    else if (b.dataset.status) state.status = b.dataset.status;
    else return;
    renderStandings();
  });
  $("#view-standings").addEventListener("change", (e) => {
    if (e.target.id === "team") { state.team = e.target.value; renderStandings(); $("#team").focus(); }
  });
}

async function init() {
  bind();
  try {
    const [meta, today, standings, lastnight] = await Promise.all(["meta", "today", "standings", "lastnight"].map(load));
    Object.assign(DATA, { meta, today, standings, lastnight });
  } catch (err) {
    $("#view-today").innerHTML = `<p class="empty">資料載入失敗（${esc(err.message)}），晚點再重新整理看看。</p>`;
    return;
  }
  $("#mast-date").textContent = longDate(DATA.meta.day);
  const updated = new Date(DATA.meta.generated_at).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: ET });
  $("#colophon").textContent = `資料：stats.nba.com · NBA 官方傷兵報告 · The Odds API（麻州 5 家）· 更新於 ${updated} ET${DATA.meta.partial ? " · 昨晚的追蹤數據還沒出來，fun fact 用前一天的累計" : ""} · 這是分析和娛樂，不是投資建議。`;
  for (const t of TABS) RENDER[t]();
  show(location.hash.slice(1));
}

init();
