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
const clampPct = (v) => `${(Math.min(Math.max(v, 0), 1) * 100).toFixed(1)}%`;
const md = (d) => `${+d.slice(5, 7)}/${+d.slice(8, 10)}`;

const WHY = { players: "球員實力", absent: "傷兵缺陣", elo: "Elo 戰績", home: "主場", schedule: "賽程休息",
  b2b: "背靠背", rest: "休息天數", tif: "4 天 3 戰" };
const STATUS = { listed: "上榜", observing: "觀察中", eliminated: "淘汰" };
const TABS = ["today", "standings", "fluke", "lastnight", "scorecard"];
const FACT_VIEWS = {
  standings: {
    title: "Standings", lead: "證據最強",
    sub: "整季累積的 fun fact 排行榜，數據佐證越強排越前面，各種類輪流排。每則都寫了根據幾次，你自己判斷。「同類型」是出手量、助攻、籃板、身高最像他的 30 個球員。",
  },
  fluke: {
    title: "Fluke", lead: "最像真的",
    sub: "看起來很神，其實是運氣。這麼大的差距，光靠運氣就會落在某些人身上：每則都寫了運氣多常做到這種事、這次掃過幾個人。",
  },
};

// season and team carry across Standings and Fluke; each page keeps its own kind
const state = { tab: "today", season: 0, status: "listed", team: "", kind: { standings: "", fluke: "" } };
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
           all.market_n ? `賭盤 ${all.market_correct}/${all.market_n}` : `從 ${md(card.since || DATA.today.day)} 開始記`)}
    ${cell("模擬帳本", b.n ? `<span class="${b.profit >= 0 ? "pos" : "neg"}">${units(b.profit)}</span>` : "—",
           b.n ? `稅後 ${units(b.profit_after_tax)} · ${b.n} 注` : "還沒有結算的注")}
  </dl>${(card.previous || []).map(previous).join("")}`;
}

// a model the site no longer uses keeps its own record, never merged into the current one
function previous(c) {
  const a = c.all || {}, b = c.bets || {};
  if (!a.n && !b.n) return "";
  const span = md(c.since) + (c.until && c.until !== c.since ? `–${md(c.until)}` : "");
  const bets = b.n ? ` · 模擬帳本 ${units(b.profit)}（稅後 ${units(b.profit_after_tax)}）· ${b.n} 注` : "";
  return `<p class="strip-note">舊版模型 ${esc(c.label)}（${span}）：猜中 ${a.model_correct || 0}/${a.n || 0}${bets}</p>`;
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
      <p class="view__sub">${longDate(t.day)} · ${games.length} 場 · 模型：${esc(DATA.meta.model_zh || "Elo＋賽程情境")} · 賭盤：麻州 5 家<br>
        <span class="legend"><i class="swatch"></i>模型</span><span class="legend"><i class="swatch swatch--market"></i>賭盤</span>
      </p>
    </header>
    <div class="today">
      <aside class="today__side" aria-label="戰績"><h2 class="side-label">戰績</h2>${strip(t.scorecard || {})}</aside>
      <div class="today__games cols-2">${games.length ? games.map(gameBlock).join("") : `<p class="empty">今天沒有比賽</p>`}</div>
    </div>`;
}

/* ---------- Standings ---------- */

function factRow(f) {
  const rank = f.status === "listed"
    ? `<span class="fact__rank">${f.rank}</span>`
    : `<span class="fact__rank fact__rank--muted">${f.status === "fluke" ? "Fluke" : STATUS[f.status]}</span>`;
  const out = f.status === "eliminated" && f.eliminated_on ? ` · ${esc(f.eliminated_on)} 淘汰` : "";
  return `<li class="fact">${rank}<div>
    <p class="fact__zh" lang="zh-Hant">${esc(f.text_zh)}</p>
    <p class="fact__en">${esc(f.text_en)}</p>
    <p class="fact__basis">${esc(f.basis_zh)} · <b>${esc(f.team)}</b>${out}</p>
    ${f.verdict_zh ? `<p class="fact__verdict">${esc(f.verdict_zh)}</p>` : ""}
    <div class="scale" role="img" aria-label="${pct(f.rate)}，比較基準 ${pct(f.p0)}">
      <i class="scale__base" style="--x:${clampPct(f.p0)}"></i><i class="scale__dot" style="--x:${clampPct(f.rate)}"></i>
    </div>
  </div></li>`;
}

function renderFacts(which) {
  const seasons = DATA.standings.seasons || [];
  const s = seasons[state.season] || seasons[0] || {};
  const status = which === "fluke" ? "fluke" : state.status;
  const list = s[status] || [];
  const kinds = DATA.standings.kinds || {};
  const here = Object.keys(kinds).filter((k) => list.some((f) => f.kind === k));
  if (!here.includes(state.kind[which])) state.kind[which] = "";
  const kind = state.kind[which], team = state.team, v = FACT_VIEWS[which];
  // observing / fluke / eliminated ship the first 60 (top: true) plus each team's and each kind's first 10
  const shown = list.filter((f) => (!team || f.team === team) && (!kind || f.kind === kind)
                                   && (team || kind || f.top !== false));
  const counts = s.counts || {};
  const total = counts[status] ?? list.length;
  const note = status === "listed" || !shown.length ? ""
    : !team && !kind && shown.length < total ? `<p class="list-note">${v.lead}的 ${shown.length} 則，共 ${total} 則。選球隊或種類可以看更多。</p>`
    : (team || kind) && shown.length >= 10 ? `<p class="list-note">只列出每隊、每種類最前面的 10 則</p>` : "";
  const teams = DATA.meta.teams || {}, followed = DATA.meta.followed || [];
  const opt = (c) => `<option value="${c}"${c === team ? " selected" : ""}>${c} · ${esc(teams[c] || c)}</option>`;
  const others = Object.keys(teams).filter((c) => !followed.includes(c)).sort();
  const kindOpt = (k) => `<option value="${k}"${k === kind ? " selected" : ""}>${esc(kinds[k][0])}</option>`;
  let empty = `<p class="empty">這個條件下沒有${which === "fluke" ? " Fluke 判決" : " fun fact"}</p>`;
  if (!list.length && state.season === 0 && seasons.length > 1 && (which === "fluke" || status === "listed")) {
    empty = `<div class="empty"><p>本季還沒有${which === "fluke" ? " Fluke 判決" : " fun fact 上榜"}：開季才兩週，樣本還小，證據會隨比賽累積。</p>
      <div class="seg"><button type="button" data-season="1">看 ${esc(seasons[1].label.replace(" demo", ""))} 示範榜</button></div></div>`;
  }
  $(`#view-${which}`).innerHTML = `
    <header class="view__head">
      <h1 class="view__title">${v.title}</h1>
      <p class="view__sub">${v.sub}</p>
    </header>
    <div class="standings">
      <div class="controls">
        <span class="controls__label" id="${which}-lbl-season">球季</span>
        <div class="seg" role="group" aria-labelledby="${which}-lbl-season">${seasons.map((x, i) =>
          `<button type="button" aria-pressed="${i === state.season}" data-season="${i}">${esc(x.label.replace(" demo", " 示範"))}</button>`).join("")}</div>
        ${which === "standings" ? `<span class="controls__label" id="${which}-lbl-status">狀態</span>
        <div class="seg" role="group" aria-labelledby="${which}-lbl-status">${Object.keys(STATUS).map((k) =>
          `<button type="button" aria-pressed="${k === state.status}" data-status="${k}">${STATUS[k]} <span class="seg__n">${counts[k] ?? (s[k] || []).length}</span></button>`).join("")}</div>` : ""}
        <label class="controls__label" for="${which}-kind">種類</label>
        <select class="select" id="${which}-kind">
          <option value="">全部種類</option>${here.map(kindOpt).join("")}
        </select>
        <label class="controls__label" for="${which}-team">球隊</label>
        <select class="select" id="${which}-team">
          <option value="">全部球隊</option>
          <optgroup label="關注">${followed.map(opt).join("")}</optgroup>
          <optgroup label="其他">${others.map(opt).join("")}</optgroup>
        </select>
      </div>
      <div class="standings__list">
        ${note}
        ${shown.length ? `<ol class="facts cols-2">${shown.map(factRow).join("")}</ol>` : empty}
      </div>
    </div>`;
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
  const l = DATA.lastnight, games = l.games || [];
  const moved = (id, title, list, none) => `<section aria-labelledby="h-${id}">
        <h2 class="section-label" id="h-${id}">${title}</h2>
        ${list.length ? `<ol class="facts">${list.map(factRow).join("")}</ol>` : `<p class="empty">${none}</p>`}
      </section>`;
  $("#view-lastnight").innerHTML = `
    <header class="view__head">
      <h1 class="view__title">Last night</h1>
      <p class="view__sub">${longDate(l.day)} · ${games.length} 場</p>
    </header>
    <div class="lastnight">
      <div>
        ${moved("listed", "新上榜", l.listed || [], "昨晚的比賽沒有讓 fun fact 上榜")}
        ${moved("overturned", "被推翻", l.eliminated || [], "昨晚的比賽沒有推翻任何 fun fact")}
      </div>
      <section aria-labelledby="h-scores">
        <h2 class="section-label" id="h-scores">比分</h2>
        ${games.length ? `<ol class="scores">${games.map(scoreRow).join("")}</ol>` : `<p class="empty">昨晚沒有比賽</p>`}
      </section>
    </div>`;
}

/* ---------- Scorecard ---------- */

const CAL = { w: 320, h: 216, l: 40, r: 14, t: 14, b: 34 };   // calibration chart box (viewBox units)
const calX = (v) => CAL.l + (v - 0.5) / 0.5 * (CAL.w - CAL.l - CAL.r);
const calY = (v) => CAL.h - CAL.b - v * (CAL.h - CAL.t - CAL.b);
const band = (b) => `${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%`;

function calibration(bins) {
  if (!bins.length) return `<p class="empty">還沒有結果，第一批比賽打完才會有點。</p>`;
  const grid = [0, 0.25, 0.5, 0.75, 1].map((v) => `<line x1="${CAL.l}" x2="${CAL.w - CAL.r}" y1="${calY(v)}" y2="${calY(v)}"/>
      <text x="${CAL.l - 6}" y="${calY(v) + 4}" text-anchor="end">${v * 100}%</text>`).join("");
  const ticks = [0.5, 0.6, 0.7, 0.8, 0.9, 1].map((v) =>
    `<text x="${calX(v)}" y="${CAL.h - CAL.b + 18}" text-anchor="middle">${Math.round(v * 100)}%</text>`).join("");
  const dots = bins.map((b, i) => `<g class="cal__pt">
      <circle class="cal__dot" cx="${calX(b.predicted)}" cy="${calY(b.actual)}" r="5"/>
      <circle class="cal__hit" cx="${calX(b.predicted)}" cy="${calY(b.actual)}" r="14" tabindex="0" data-i="${i}"
        aria-label="模型說 ${band(b)}，平均 ${pct(b.predicted)}；熱門實際贏 ${pct(b.actual)}，${b.n} 場"/>
    </g>`).join("");
  const rows = bins.map((b) => `<tr><td>${band(b)}<span class="sub">平均 ${pct(b.predicted)}</span></td>
      <td>${pct(b.actual)}</td><td>${b.n}</td></tr>`).join("");
  return `<figure class="cal">
      <svg viewBox="0 0 ${CAL.w} ${CAL.h}" role="img" aria-labelledby="cal-desc">
        <desc id="cal-desc">校準圖：橫軸是模型說熱門贏的機率，縱軸是熱門實際贏的比例，點落在斜線上代表說幾成就真的贏幾成。</desc>
        <g class="cal__grid">${grid}</g>
        <g class="cal__axis">${ticks}<text x="${(CAL.l + CAL.w - CAL.r) / 2}" y="${CAL.h - 2}" text-anchor="middle">模型說熱門會贏</text></g>
        <line class="cal__ref" x1="${calX(0.5)}" y1="${calY(0.5)}" x2="${calX(1)}" y2="${calY(1)}"/>
        <line class="cal__ref" x1="${CAL.l + 8}" y1="${CAL.t + 10}" x2="${CAL.l + 26}" y2="${CAL.t + 10}"/>
        <text x="${CAL.l + 32}" y="${CAL.t + 14}">斜線：說幾成就贏幾成</text>
        ${dots}
      </svg>
      <div class="cal__tip" hidden></div>
    </figure>
    <table class="data-table">
      <thead><tr><th scope="col">模型說</th><th scope="col">熱門實際贏</th><th scope="col">場數</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function bindCalibration(bins) {
  const fig = $("#view-scorecard .cal");
  if (!fig) return;
  const tip = $(".cal__tip", fig), svg = $("svg", fig);
  const showTip = (el) => {
    const b = bins[Number(el.dataset.i)], box = svg.getBoundingClientRect(), k = box.width / CAL.w;
    tip.replaceChildren();
    const strong = document.createElement("b");
    strong.textContent = `熱門贏 ${pct(b.actual)}`;
    tip.append(strong, document.createTextNode(` · 模型說平均 ${pct(b.predicted)}（${band(b)}）· ${b.n} 場`));
    tip.hidden = false;
    const x = Number(el.getAttribute("cx")) * k, y = Number(el.getAttribute("cy")) * k;
    tip.style.left = `${Math.min(Math.max(x - tip.offsetWidth / 2, 0), box.width - tip.offsetWidth)}px`;
    const above = y - tip.offsetHeight - 12;              // no room above the dot: below it, never on it
    tip.style.top = `${above >= 0 ? above : y + 14}px`;
  };
  for (const el of fig.querySelectorAll(".cal__hit")) {
    el.addEventListener("pointerenter", () => showTip(el));
    el.addEventListener("focus", () => showTip(el));
    el.addEventListener("pointerleave", () => { tip.hidden = true; });
    el.addEventListener("blur", () => { tip.hidden = true; });
  }
}

function versionRow(name, v) {
  return `<tr><td>${name}</td><td>${v.n ? `${v.correct}/${v.n}` : "—"}</td><td>${v.n ? v.log_loss.toFixed(3) : "—"}</td></tr>`;
}

function renderScorecard() {
  const s = DATA.scorecard, view = $("#view-scorecard");
  const head = (sub) => `<header class="view__head"><h1 class="view__title">Scorecard</h1>
      <p class="view__sub">${sub}</p></header>`;
  if (!s) {
    view.innerHTML = `${head("模型 vs 賭盤")}<p class="empty">成績單下次每日更新時產生。</p>`;
    return;
  }
  const all = s.model_all || {}, mm = (s.model_vs_market || {}).model || {}, mk = (s.model_vs_market || {}).market || {};
  const led = s.ledger || {}, clv = s.clv || {}, ver = s.versions || {}, eve = s.evening || {}, eveClv = eve.clv || {};
  const few = !all.n ? `<p class="list-note">第一批比賽打完、隔天早上更新後才有成績。</p>`
    : all.n < 100 ? `<p class="list-note">樣本還很少（${all.n} 場），先看看就好；一兩百場以後這些數字才比較穩。</p>` : "";
  const books = (s.books || []).map((b) => `<tr><td>${esc(b.book)}</td><td>${(b.vig * 100).toFixed(1)}%</td><td>${b.games}</td></tr>`).join("");
  view.innerHTML = `
    ${head(`模型 vs 賭盤 · ${esc(s.label)} · ${md(s.since)} 起 · ${all.n || 0} 場有結果`)}
    ${few}
    <dl class="strip strip--4">
      ${scoreCell("猜中 · 模型", all.n ? `${all.correct}/${all.n}` : "—", mk.n ? `賭盤熱門 ${mk.correct}/${mk.n}` : "還沒有結果")}
      ${scoreCell("Log loss · 越低越準", mm.n ? mm.log_loss.toFixed(3) : "—", mm.n ? `賭盤 ${mk.log_loss.toFixed(3)} · 同樣 ${mm.n} 場` : "還沒有結果")}
      ${scoreCell("模擬帳本 · 早上", led.n ? `<span class="${led.profit >= 0 ? "pos" : "neg"}">${units(led.profit)}</span>` : "—",
                  led.n ? `稅後 ${units(led.profit_after_tax)} · ${led.n} 注 ${led.wins} 勝` : "還沒有結算的注")}
      ${scoreCell("收盤線價值", clv.n ? signed(clv.mean) : "—", clv.n ? `${clv.n} 注裡 ${clv.beat} 注賠率比收盤好` : "還沒有收盤賠率")}
    </dl>
    <div class="cols-2 scorecard">
      <section aria-labelledby="h-cal">
        <h2 class="section-label" id="h-cal">校準</h2>
        <p class="list-note">模型說熱門有七成機會贏的比賽，熱門真的贏七成左右，點就會落在斜線上。</p>
        ${calibration(s.calibration || [])}
      </section>
      <div>
        <section aria-labelledby="h-ver">
          <h2 class="section-label" id="h-ver">早上版 vs 賽前版</h2>
          <p class="list-note">開賽前傷兵報告有變動、重算過勝率的比賽，各自跟同一時間的賭盤比。</p>
          ${ver.pregame && ver.pregame.n ? `<table class="data-table">
            <thead><tr><th scope="col">同樣這幾場</th><th scope="col">猜中</th><th scope="col">Log loss</th></tr></thead>
            <tbody>${versionRow("賽前版（最後一次重算）", ver.pregame)}${versionRow("早上版", ver.morning_same_games || {})}${versionRow("收盤賭盤", ver.closing_market || {})}</tbody>
          </table>` : `<p class="empty">還沒有賽前重算過、而且打完的比賽。</p>`}
        </section>
        <section aria-labelledby="h-eve">
          <h2 class="section-label" id="h-eve">晚上新增的注</h2>
          <p class="list-note">開賽前的傷兵消息讓比賽變得值得投、晚上用 email 通知的注，跟早上的帳本分開算。</p>
          ${eve.n ? `<dl class="strip strip--2">
            ${scoreCell("模擬帳本 · 晚上", `<span class="${eve.profit >= 0 ? "pos" : "neg"}">${units(eve.profit)}</span>`,
                        `稅後 ${units(eve.profit_after_tax)} · ${eve.n} 注 ${eve.wins} 勝`)}
            ${scoreCell("收盤線價值", eveClv.n ? signed(eveClv.mean) : "—", eveClv.n ? `${eveClv.n} 注裡 ${eveClv.beat} 注賠率比收盤好` : "還沒有收盤賠率")}
          </dl>` : `<p class="empty">還沒有晚上新增、而且打完的注。</p>`}
        </section>
        <section aria-labelledby="h-books">
          <h2 class="section-label" id="h-books">各家抽成</h2>
          <p class="list-note">勝負盤兩邊的隱含機率加起來超過 100% 的部分，本季平均；越低越划算。</p>
          ${books ? `<table class="data-table">
            <thead><tr><th scope="col">麻州的書商</th><th scope="col">平均抽成</th><th scope="col">場數</th></tr></thead>
            <tbody>${books}</tbody>
          </table>` : `<p class="empty">還沒有賠率</p>`}
        </section>
        ${(s.previous || []).map(previous).join("")}
      </div>
    </div>`;
  bindCalibration(s.calibration || []);
}

const scoreCell = (dt, dd, sub) => `<div><dt>${dt}</dt><dd>${dd}<span class="sub">${sub}</span></dd></div>`;

/* ---------- layout: 自動 / 電腦 / 手機 (the <head> script applied the saved choice before first paint) ---------- */

const LAYOUT_KEY = "fof-layout";
const WIDE = window.matchMedia("(min-width: 64rem)");
const VIEWPORT = { device: "width=device-width, initial-scale=1, viewport-fit=cover", desktop: "width=1200, viewport-fit=cover" };

function applyLayout(mode) {
  const root = document.documentElement;
  root.dataset.layout = mode;
  // a phone that asks for 電腦 lays the page out 1200px wide and zooms out, like "request desktop site"
  $('meta[name="viewport"]').setAttribute("content", mode === "desktop" ? VIEWPORT.desktop : VIEWPORT.device);
  root.dataset.view = mode === "desktop" || (mode === "auto" && WIDE.matches) ? "desktop" : "mobile";
  for (const b of document.querySelectorAll(".seg--mode button")) b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
}

function chooseLayout(mode) {
  // leaving the zoomed-out desktop page on a small screen: reload, so the browser starts again at its own width and zoom
  const unzoom = document.documentElement.dataset.layout === "desktop" && mode !== "desktop" && screen.width < 1024;
  try { localStorage.setItem(LAYOUT_KEY, mode); } catch (err) { /* storage blocked: switch now, just not remembered */ }
  if (unzoom) location.reload();
  else applyLayout(mode);
}

/* ---------- shell ---------- */

const renderFactViews = () => { renderFacts("standings"); renderFacts("fluke"); };
const RENDER = { today: renderToday, standings: () => renderFacts("standings"), fluke: () => renderFacts("fluke"),
                 lastnight: renderLastNight, scorecard: renderScorecard };

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
  $(".seg--mode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (b) chooseLayout(b.dataset.mode);
  });
  // 自動 follows the window across the breakpoint (also when the viewport changes back after leaving 電腦)
  WIDE.addEventListener("change", () => { if (document.documentElement.dataset.layout === "auto") applyLayout("auto"); });
  $(".tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) show(b.dataset.tab);
  });
  $(".tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const i = TABS.indexOf(state.tab) + (e.key === "ArrowRight" ? 1 : -1);
    show(TABS[(i + TABS.length) % TABS.length], { focus: true });
  });
  for (const which of ["standings", "fluke"]) {
    $(`#view-${which}`).addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.season != null) { state.season = Number(b.dataset.season); state.status = "listed"; }
      else if (b.dataset.status) state.status = b.dataset.status;
      else return;
      renderFactViews();
    });
    $(`#view-${which}`).addEventListener("change", (e) => {
      const id = e.target.id;
      if (id === `${which}-team`) state.team = e.target.value;
      else if (id === `${which}-kind`) state.kind[which] = e.target.value;
      else return;
      renderFactViews();
      $(`#${id}`).focus();
    });
  }
}

async function init() {
  applyLayout(document.documentElement.dataset.layout || "auto");
  bind();
  try {
    const [meta, today, standings, lastnight] = await Promise.all(["meta", "today", "standings", "lastnight"].map(load));
    // the scorecard came later: until the daily run first writes it, its tab says so instead of failing the page
    const scorecard = await load("scorecard").catch(() => null);
    Object.assign(DATA, { meta, today, standings, lastnight, scorecard });
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
