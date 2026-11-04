/* Fact or Fluke: renders data/*.json (written by the daily run) into five tabs. No framework, no build. */
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

/* ---------- language: 中文 / English ----------
   The <head> script picked the language before first paint (a saved choice, else the browser's
   first language) and set <html lang>. Every string below is a [中文, English] pair. */

const LANG_KEY = "fof-lang";
let LANG = document.documentElement.lang.startsWith("zh") ? "zh" : "en";
const tr = (zh, en) => (LANG === "zh" ? zh : en);
const pick = (pair) => pair[LANG === "zh" ? 0 : 1];
const games_ = (n) => tr(`${n} 場`, `${n} game${n === 1 ? "" : "s"}`);

const WHY = { players: ["球員實力", "Player strength"], absent: ["傷兵缺陣", "Injuries"], elo: ["Elo 戰績", "Elo record"],
  home: ["主場", "Home court"], schedule: ["賽程休息", "Rest & schedule"], b2b: ["背靠背", "Back-to-back"],
  rest: ["休息天數", "Rest days"], tif: ["4 天 3 戰", "3 games in 4 days"] };
const STATUS = { listed: ["上榜", "Listed"], observing: ["觀察中", "Watching"], eliminated: ["淘汰", "Eliminated"] };
const TABS = ["today", "standings", "fluke", "lastnight", "scorecard"];
const FACT_VIEWS = {
  standings: {
    title: "Standings", lead: ["證據最強", "with the strongest evidence"],
    sub: ["整季累積的 fun fact 排行榜，數據佐證越強排越前面，各種類輪流排。每則都寫了根據幾次，你自己判斷。「同類型」是出手量、助攻、籃板、身高最像他的 30 個球員。",
          "A season-long table of fun facts: the stronger the evidence, the higher it ranks, with the kinds taking turns. Each one says how many plays it rests on, so you can judge for yourself. “Similar role” means the 30 players closest to him in shot volume, assists, rebounds and height."],
  },
  fluke: {
    title: "Fluke", lead: ["最像真的", "most convincing"],
    sub: ["看起來很神，其實是運氣。這麼大的差距，光靠運氣就會落在某些人身上：每則都寫了運氣多常做到這種事、這次掃過幾個人。",
          "Looks remarkable, is luck. Gaps this big land on someone by chance alone: each verdict says how often luck does it and how many players were scanned."],
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

const label = (c) => esc(tr(c.label, c.label_en || c.label));   // a model's name on the record

/* ---------- Today ---------- */

function strip(card) {
  const y = card.yesterday || {}, all = card.all || {}, b = card.bets || {};
  const cell = (dt, dd, sub) => `<div><dt>${dt}</dt><dd>${dd}<span class="sub">${sub}</span></dd></div>`;
  return `<dl class="strip">
    ${cell(tr("昨天 · 模型", "Yesterday · model"), y.n ? `${y.model_correct}/${y.n}` : "—",
           y.market_n ? tr(`賭盤 ${y.market_correct}/${y.market_n}`, `market ${y.market_correct}/${y.market_n}`)
                      : tr("還沒有結果", "no results yet"))}
    ${cell(tr("本季 · 模型", "Season · model"), all.n ? `${all.model_correct}/${all.n}` : "—",
           all.market_n ? tr(`賭盤 ${all.market_correct}/${all.market_n}`, `market ${all.market_correct}/${all.market_n}`)
                        : tr(`從 ${md(card.since || DATA.today.day)} 開始記`, `tracked since ${md(card.since || DATA.today.day)}`))}
    ${cell(tr("模擬帳本", "Paper ledger"), b.n ? `<span class="${b.profit >= 0 ? "pos" : "neg"}">${units(b.profit)}</span>` : "—",
           b.n ? tr(`稅後 ${units(b.profit_after_tax)} · ${b.n} 注`, `${units(b.profit_after_tax)} after tax · ${b.n} bets`)
               : tr("還沒有結算的注", "no settled bets yet"))}
  </dl>${(card.previous || []).map(previous).join("")}`;
}

// a model the site no longer uses keeps its own record, never merged into the current one
function previous(c) {
  const a = c.all || {}, b = c.bets || {};
  if (!a.n && !b.n) return "";
  const span = md(c.since) + (c.until && c.until !== c.since ? `–${md(c.until)}` : "");
  const bets = !b.n ? "" : tr(` · 模擬帳本 ${units(b.profit)}（稅後 ${units(b.profit_after_tax)}）· ${b.n} 注`,
                              ` · paper ledger ${units(b.profit)} (${units(b.profit_after_tax)} after tax) · ${b.n} bets`);
  return `<p class="strip-note">${tr(`舊版模型 ${label(c)}（${span}）：猜中 ${a.model_correct || 0}/${a.n || 0}`,
                                     `Previous model, ${label(c)} (${span}): ${a.model_correct || 0}/${a.n || 0} right`)}${bets}</p>`;
}

function gameBlock(p) {
  const { home, away } = p, ph = p.p_home, mk = p.market_p_home;
  const fav = ph >= 0.5 ? home : away;
  const a = (1 - ph) * 100, m = mk == null ? null : (1 - mk) * 100;
  let probs = `<span>${tr("模型", "Model")} <b>${fav} ${pct(Math.max(ph, 1 - ph))}</b></span>`;
  if (mk != null) probs += `<span>${tr("賭盤", "Market")} <b>${mk >= 0.5 ? home : away} ${pct(Math.max(mk, 1 - mk))}</b></span>`;
  let value = `<p class="game__novalue">${tr("還沒有賠率", "No odds yet")}</p>`;
  if (p.pick) {
    const [price, book] = p.best[p.pick];
    value = `<p class="game__value"><span class="dot" aria-hidden="true"></span><span>${tr(
      `划算：${p.pick} ${price.toFixed(2)} @${esc(book)}（期望值 ${signed(p.ev[p.pick])}）`,
      `Value: ${p.pick} ${price.toFixed(2)} @${esc(book)} (expected value ${signed(p.ev[p.pick])})`)}</span></p>`;
  } else if (p.suspect) {
    value = `<p class="game__novalue">${tr(
      `模型和賭盤差太多（${p.suspect} 期望值 ${signed(p.ev[p.suspect])}），多半是模型還不知道的消息，例如傷兵，這注不算`,
      `Model and market are too far apart (${p.suspect} expected value ${signed(p.ev[p.suspect])}): usually news the model has not seen yet, such as an injury, so this one does not count`)}</p>`;
  } else if (p.best && p.best[fav] && p.best[fav][0]) {
    const [price, book] = p.best[fav];
    value = `<p class="game__novalue">${tr(
      `沒有划算的注（${fav} 最佳 ${price.toFixed(2)} @${esc(book)}，期望值 ${signed(p.ev[fav])}）`,
      `No value bet (${fav} best ${price.toFixed(2)} @${esc(book)}, expected value ${signed(p.ev[fav])})`)}</p>`;
  }
  const why = Object.entries(p.why || {})
    .filter(([, v]) => Math.abs(v) >= 0.005)
    .sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]))
    .map(([k, v]) => `<li>${WHY[k] ? pick(WHY[k]) : k} → <b>${v > 0 ? home : away} +${Math.round(Math.abs(v) * 100)}</b></li>`)
    .join("");
  const aria = tr(`模型：${away} ${pct(1 - ph)}、${home} ${pct(ph)}`, `Model: ${away} ${pct(1 - ph)}, ${home} ${pct(ph)}`)
    + (mk != null ? tr(`；賭盤：${home} ${pct(mk)}`, `; market: ${home} ${pct(mk)}`) : "");
  return `<article class="game">
    <header class="game__head">
      <time class="game__time" datetime="${esc(p.tip_utc)}">${tipTime(p.tip_utc)}</time>
      <h2 class="game__matchup">${away}<span class="at">@</span>${home}</h2>
    </header>
    <div class="wp" role="img" aria-label="${aria}">
      <span class="wp__team${fav === away ? " is-fav" : ""}">${away}</span>
      <div class="wp__bar" style="--a:${a.toFixed(1)}%${m != null ? `;--m:${m.toFixed(1)}%` : ""}">
        <i class="wp__away"></i><i class="wp__model"></i>${m != null ? `<i class="wp__market"></i>` : ""}
      </div>
      <span class="wp__team wp__team--home${fav === home ? " is-fav" : ""}">${home}</span>
    </div>
    <p class="game__probs">${probs}</p>
    ${value}
    ${why ? `<ul class="why" aria-label="${tr("各因素讓勝率移動的百分點", "How far each factor moves the win probability, in points")}"><li>${tr("為什麼：", "Why:")}</li>${why}</ul>` : ""}
  </article>`;
}

function renderToday() {
  const t = DATA.today, games = t.games || [];
  const model = tr(DATA.meta.model_zh || "Elo＋賽程情境", DATA.meta.model_en || DATA.meta.model_zh || "Elo + schedule context");
  $("#view-today").innerHTML = `
    <header class="view__head">
      <h1 class="view__title">Today</h1>
      <p class="view__sub">${longDate(t.day)} · ${games_(games.length)} · ${tr("模型：", "model: ")}${esc(model)} · ${tr("賭盤：麻州 5 家", "market: 5 Massachusetts sportsbooks")}<br>
        <span class="legend"><i class="swatch"></i>${tr("模型", "Model")}</span><span class="legend"><i class="swatch swatch--market"></i>${tr("賭盤", "Market")}</span>
      </p>
    </header>
    <div class="today">
      <aside class="today__side" aria-label="${tr("戰績", "Record")}"><h2 class="side-label">${tr("戰績", "Record")}</h2>${strip(t.scorecard || {})}</aside>
      <div class="today__games cols-2">${games.length ? games.map(gameBlock).join("") : `<p class="empty">${tr("今天沒有比賽", "No games today")}</p>`}</div>
    </div>`;
}

/* ---------- Standings ---------- */

function factRow(f) {
  const rank = f.status === "listed"
    ? `<span class="fact__rank">${f.rank}</span>`
    : `<span class="fact__rank fact__rank--muted">${f.status === "fluke" ? "Fluke" : pick(STATUS[f.status])}</span>`;
  const out = f.status === "eliminated" && f.eliminated_on
    ? tr(` · ${esc(f.eliminated_on)} 淘汰`, ` · eliminated ${esc(f.eliminated_on)}`) : "";
  // in Chinese the English line stays underneath as a gloss; in English it is the fact itself
  const text = LANG === "zh"
    ? `<p class="fact__text" lang="zh-Hant">${esc(f.text_zh)}</p><p class="fact__gloss" lang="en">${esc(f.text_en)}</p>`
    : `<p class="fact__text">${esc(f.text_en)}</p>`;
  const verdict = tr(f.verdict_zh, f.verdict_en || f.verdict_zh);
  return `<li class="fact">${rank}<div>
    ${text}
    <p class="fact__basis">${esc(tr(f.basis_zh, f.basis_en || f.basis_zh))} · <b>${esc(f.team)}</b>${out}</p>
    ${verdict ? `<p class="fact__verdict">${esc(verdict)}</p>` : ""}
    <div class="scale" role="img" aria-label="${tr(`${pct(f.rate)}，比較基準 ${pct(f.p0)}`, `${pct(f.rate)}, against a baseline of ${pct(f.p0)}`)}">
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
    : !team && !kind && shown.length < total ? `<p class="list-note">${tr(
        `${v.lead[0]}的 ${shown.length} 則，共 ${total} 則。選球隊或種類可以看更多。`,
        `The ${shown.length} ${v.lead[1]}, of ${total}. Pick a team or a kind to see more.`)}</p>`
    : (team || kind) && shown.length >= 10 ? `<p class="list-note">${tr("只列出每隊、每種類最前面的 10 則",
        "Only the first 10 per team and per kind are listed.")}</p>` : "";
  const teams = DATA.meta.teams || {}, followed = DATA.meta.followed || [];
  const opt = (c) => `<option value="${c}"${c === team ? " selected" : ""}>${c} · ${esc(teams[c] || c)}</option>`;
  const others = Object.keys(teams).filter((c) => !followed.includes(c)).sort();
  const kindOpt = (k) => `<option value="${k}"${k === kind ? " selected" : ""}>${esc(pick(kinds[k]))}</option>`;
  const what = which === "fluke" ? tr(" Fluke 判決", "Fluke verdicts") : tr(" fun fact", "fun facts");
  let empty = `<p class="empty">${tr(`這個條件下沒有${what}`, `No ${what} match these filters.`)}</p>`;
  if (!list.length && state.season === 0 && seasons.length > 1 && (which === "fluke" || status === "listed")) {
    const none = which === "fluke" ? tr(" Fluke 判決", "Fluke verdicts") : tr(" fun fact 上榜", "listed fun facts");
    const demo = esc(seasons[1].label.replace(" demo", ""));
    empty = `<div class="empty"><p>${tr(`本季還沒有${none}：開季才兩週，樣本還小，證據會隨比賽累積。`,
        `No ${none} yet this season: it is only a couple of weeks old, samples are small, and the evidence builds game by game.`)}</p>
      <div class="seg"><button type="button" data-season="1">${tr(`看 ${demo} 示範榜`, `See the ${demo} demo table`)}</button></div></div>`;
  }
  $(`#view-${which}`).innerHTML = `
    <header class="view__head">
      <h1 class="view__title">${v.title}</h1>
      <p class="view__sub">${pick(v.sub)}</p>
    </header>
    <div class="standings">
      <div class="controls">
        <span class="controls__label" id="${which}-lbl-season">${tr("球季", "Season")}</span>
        <div class="seg" role="group" aria-labelledby="${which}-lbl-season">${seasons.map((x, i) =>
          `<button type="button" aria-pressed="${i === state.season}" data-season="${i}">${esc(x.label.replace(" demo", tr(" 示範", " demo")))}</button>`).join("")}</div>
        ${which === "standings" ? `<span class="controls__label" id="${which}-lbl-status">${tr("狀態", "Status")}</span>
        <div class="seg" role="group" aria-labelledby="${which}-lbl-status">${Object.keys(STATUS).map((k) =>
          `<button type="button" aria-pressed="${k === state.status}" data-status="${k}">${pick(STATUS[k])} <span class="seg__n">${counts[k] ?? (s[k] || []).length}</span></button>`).join("")}</div>` : ""}
        <label class="controls__label" for="${which}-kind">${tr("種類", "Kind")}</label>
        <select class="select" id="${which}-kind">
          <option value="">${tr("全部種類", "All kinds")}</option>${here.map(kindOpt).join("")}
        </select>
        <label class="controls__label" for="${which}-team">${tr("球隊", "Team")}</label>
        <select class="select" id="${which}-team">
          <option value="">${tr("全部球隊", "All teams")}</option>
          <optgroup label="${tr("關注", "Followed")}">${followed.map(opt).join("")}</optgroup>
          <optgroup label="${tr("其他", "Others")}">${others.map(opt).join("")}</optgroup>
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
  if (!g.final) return `<li class="score"><span class="score__line">${g.away} @ ${g.home}</span><span class="score__marks">${tr("未完賽", "Not final")}</span></li>`;
  const homeWon = g.home_score > g.away_score;
  const marks = [g.model_right == null ? "" : g.model_right ? tr("模型猜中", "model right") : tr("模型猜錯", "model wrong"),
                 g.market_right == null ? "" : g.market_right ? tr("賭盤猜中", "market right") : tr("賭盤猜錯", "market wrong")]
    .filter(Boolean).join(" · ");
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
      <p class="view__sub">${longDate(l.day)} · ${games_(games.length)}</p>
    </header>
    <div class="lastnight">
      <div>
        ${moved("listed", tr("新上榜", "Newly listed"), l.listed || [],
                tr("昨晚的比賽沒有讓 fun fact 上榜", "Last night's games put no fun fact on the list"))}
        ${moved("overturned", tr("被推翻", "Overturned"), l.eliminated || [],
                tr("昨晚的比賽沒有推翻任何 fun fact", "Last night's games overturned no fun fact"))}
      </div>
      <section aria-labelledby="h-scores">
        <h2 class="section-label" id="h-scores">${tr("比分", "Scores")}</h2>
        ${games.length ? `<ol class="scores">${games.map(scoreRow).join("")}</ol>` : `<p class="empty">${tr("昨晚沒有比賽", "No games last night")}</p>`}
      </section>
    </div>`;
}

/* ---------- Scorecard ---------- */

const CAL = { w: 320, h: 216, l: 40, r: 14, t: 14, b: 34 };   // calibration chart box (viewBox units)
const calX = (v) => CAL.l + (v - 0.5) / 0.5 * (CAL.w - CAL.l - CAL.r);
const calY = (v) => CAL.h - CAL.b - v * (CAL.h - CAL.t - CAL.b);
const band = (b) => `${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%`;

function calibration(bins) {
  if (!bins.length) return `<p class="empty">${tr("還沒有結果，第一批比賽打完才會有點。",
    "No results yet; the points appear once the first games are played.")}</p>`;
  const grid = [0, 0.25, 0.5, 0.75, 1].map((v) => `<line x1="${CAL.l}" x2="${CAL.w - CAL.r}" y1="${calY(v)}" y2="${calY(v)}"/>
      <text x="${CAL.l - 6}" y="${calY(v) + 4}" text-anchor="end">${v * 100}%</text>`).join("");
  const ticks = [0.5, 0.6, 0.7, 0.8, 0.9, 1].map((v) =>
    `<text x="${calX(v)}" y="${CAL.h - CAL.b + 18}" text-anchor="middle">${Math.round(v * 100)}%</text>`).join("");
  const dots = bins.map((b, i) => `<g class="cal__pt">
      <circle class="cal__dot" cx="${calX(b.predicted)}" cy="${calY(b.actual)}" r="5"/>
      <circle class="cal__hit" cx="${calX(b.predicted)}" cy="${calY(b.actual)}" r="14" tabindex="0" data-i="${i}"
        aria-label="${tr(`模型說 ${band(b)}，平均 ${pct(b.predicted)}；熱門實際贏 ${pct(b.actual)}，${b.n} 場`,
                         `Model said ${band(b)}, ${pct(b.predicted)} on average; favourites won ${pct(b.actual)}, ${games_(b.n)}`)}"/>
    </g>`).join("");
  const rows = bins.map((b) => `<tr><td>${band(b)}<span class="sub">${tr("平均", "average")} ${pct(b.predicted)}</span></td>
      <td>${pct(b.actual)}</td><td>${b.n}</td></tr>`).join("");
  return `<figure class="cal">
      <svg viewBox="0 0 ${CAL.w} ${CAL.h}" role="img" aria-labelledby="cal-desc">
        <desc id="cal-desc">${tr("校準圖：橫軸是模型說熱門贏的機率，縱軸是熱門實際贏的比例，點落在斜線上代表說幾成就真的贏幾成。",
          "Calibration chart: across, how likely the model said the favourite was to win; up, how often the favourite actually won. A point on the diagonal means the probability came true.")}</desc>
        <g class="cal__grid">${grid}</g>
        <g class="cal__axis">${ticks}<text x="${(CAL.l + CAL.w - CAL.r) / 2}" y="${CAL.h - 2}" text-anchor="middle">${tr("模型說熱門會贏", "Model's chance for the favourite")}</text></g>
        <line class="cal__ref" x1="${calX(0.5)}" y1="${calY(0.5)}" x2="${calX(1)}" y2="${calY(1)}"/>
        <line class="cal__ref" x1="${CAL.l + 8}" y1="${CAL.t + 10}" x2="${CAL.l + 26}" y2="${CAL.t + 10}"/>
        <text x="${CAL.l + 32}" y="${CAL.t + 14}">${tr("斜線：說幾成就贏幾成", "Diagonal: said 70%, won 70%")}</text>
        ${dots}
      </svg>
      <div class="cal__tip" hidden></div>
    </figure>
    <table class="data-table">
      <thead><tr><th scope="col">${tr("模型說", "Model said")}</th><th scope="col">${tr("熱門實際贏", "Favourite won")}</th><th scope="col">${tr("場數", "Games")}</th></tr></thead>
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
    strong.textContent = tr(`熱門贏 ${pct(b.actual)}`, `Favourite won ${pct(b.actual)}`);
    tip.append(strong, document.createTextNode(tr(` · 模型說平均 ${pct(b.predicted)}（${band(b)}）· ${b.n} 場`,
      ` · model said ${pct(b.predicted)} on average (${band(b)}) · ${games_(b.n)}`)));
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
    view.innerHTML = `${head(tr("模型 vs 賭盤", "Model vs market"))}<p class="empty">${tr("成績單下次每日更新時產生。",
      "The scorecard appears after the next daily update.")}</p>`;
    return;
  }
  const all = s.model_all || {}, mm = (s.model_vs_market || {}).model || {}, mk = (s.model_vs_market || {}).market || {};
  const led = s.ledger || {}, clv = s.clv || {}, ver = s.versions || {}, eve = s.evening || {}, eveClv = eve.clv || {};
  const few = !all.n ? `<p class="list-note">${tr("第一批比賽打完、隔天早上更新後才有成績。",
      "Results appear the morning after the first games are played.")}</p>`
    : all.n < 100 ? `<p class="list-note">${tr(`樣本還很少（${all.n} 場），先看看就好；一兩百場以後這些數字才比較穩。`,
      `Still a small sample (${games_(all.n)}): read it lightly; these numbers settle after a couple of hundred.`)}</p>` : "";
  const books = (s.books || []).map((b) => `<tr><td>${esc(b.book)}</td><td>${(b.vig * 100).toFixed(1)}%</td><td>${b.games}</td></tr>`).join("");
  const settled = (r) => tr(`稅後 ${units(r.profit_after_tax)} · ${r.n} 注 ${r.wins} 勝`,
                            `${units(r.profit_after_tax)} after tax · ${r.n} bets, ${r.wins} won`);
  const beat = (c) => tr(`${c.n} 注裡 ${c.beat} 注賠率比收盤好`, `${c.beat} of ${c.n} bets beat the closing price`);
  view.innerHTML = `
    ${head(tr(`模型 vs 賭盤 · ${label(s)} · ${md(s.since)} 起 · ${all.n || 0} 場有結果`,
              `Model vs market · ${label(s)} · since ${md(s.since)} · ${games_(all.n || 0)} scored`))}
    ${few}
    <dl class="strip strip--4">
      ${scoreCell(tr("猜中 · 模型", "Right · model"), all.n ? `${all.correct}/${all.n}` : "—",
                  mk.n ? tr(`賭盤熱門 ${mk.correct}/${mk.n}`, `market favourite ${mk.correct}/${mk.n}`) : tr("還沒有結果", "no results yet"))}
      ${scoreCell(tr("Log loss · 越低越準", "Log loss · lower is better"), mm.n ? mm.log_loss.toFixed(3) : "—",
                  mm.n ? tr(`賭盤 ${mk.log_loss.toFixed(3)} · 同樣 ${mm.n} 場`, `market ${mk.log_loss.toFixed(3)} · same ${games_(mm.n)}`) : tr("還沒有結果", "no results yet"))}
      ${scoreCell(tr("模擬帳本 · 早上", "Paper ledger · morning"), led.n ? `<span class="${led.profit >= 0 ? "pos" : "neg"}">${units(led.profit)}</span>` : "—",
                  led.n ? settled(led) : tr("還沒有結算的注", "no settled bets yet"))}
      ${scoreCell(tr("收盤線價值", "Closing-line value"), clv.n ? signed(clv.mean) : "—", clv.n ? beat(clv) : tr("還沒有收盤賠率", "no closing odds yet"))}
    </dl>
    <div class="cols-2 scorecard">
      <section aria-labelledby="h-cal">
        <h2 class="section-label" id="h-cal">${tr("校準", "Calibration")}</h2>
        <p class="list-note">${tr("模型說熱門有七成機會贏的比賽，熱門真的贏七成左右，點就會落在斜線上。",
          "When the model gives favourites 70% and they win about 70% of those games, the point sits on the diagonal.")}</p>
        ${calibration(s.calibration || [])}
      </section>
      <div>
        <section aria-labelledby="h-ver">
          <h2 class="section-label" id="h-ver">${tr("早上版 vs 賽前版", "Morning vs pre-game")}</h2>
          <p class="list-note">${tr("開賽前傷兵報告有變動、重算過勝率的比賽，各自跟同一時間的賭盤比。",
            "Games whose win probability was recomputed after a pre-game injury report, each against the market at the same moment.")}</p>
          ${ver.pregame && ver.pregame.n ? `<table class="data-table">
            <thead><tr><th scope="col">${tr("同樣這幾場", "These games")}</th><th scope="col">${tr("猜中", "Right")}</th><th scope="col">Log loss</th></tr></thead>
            <tbody>${versionRow(tr("賽前版（最後一次重算）", "Pre-game (last recompute)"), ver.pregame)}${versionRow(tr("早上版", "Morning"), ver.morning_same_games || {})}${versionRow(tr("收盤賭盤", "Closing market"), ver.closing_market || {})}</tbody>
          </table>` : `<p class="empty">${tr("還沒有賽前重算過、而且打完的比賽。", "No finished games with a pre-game recompute yet.")}</p>`}
        </section>
        <section aria-labelledby="h-eve">
          <h2 class="section-label" id="h-eve">${tr("晚上新增的注", "Evening bets")}</h2>
          <p class="list-note">${tr("開賽前的傷兵消息讓比賽變得值得投、晚上用 email 通知的注，跟早上的帳本分開算。",
            "Bets that became worth making on pre-game injury news and went out by email in the evening, kept apart from the morning ledger.")}</p>
          ${eve.n ? `<dl class="strip strip--2">
            ${scoreCell(tr("模擬帳本 · 晚上", "Paper ledger · evening"), `<span class="${eve.profit >= 0 ? "pos" : "neg"}">${units(eve.profit)}</span>`, settled(eve))}
            ${scoreCell(tr("收盤線價值", "Closing-line value"), eveClv.n ? signed(eveClv.mean) : "—", eveClv.n ? beat(eveClv) : tr("還沒有收盤賠率", "no closing odds yet"))}
          </dl>` : `<p class="empty">${tr("還沒有晚上新增、而且打完的注。", "No settled evening bets yet.")}</p>`}
        </section>
        <section aria-labelledby="h-books">
          <h2 class="section-label" id="h-books">${tr("各家抽成", "Sportsbook margins")}</h2>
          <p class="list-note">${tr("勝負盤兩邊的隱含機率加起來超過 100% 的部分，本季平均；越低越划算。",
            "How far the two sides' implied probabilities add up past 100%, averaged over the season; lower is better for the bettor.")}</p>
          ${books ? `<table class="data-table">
            <thead><tr><th scope="col">${tr("麻州的書商", "Massachusetts sportsbook")}</th><th scope="col">${tr("平均抽成", "Average margin")}</th><th scope="col">${tr("場數", "Games")}</th></tr></thead>
            <tbody>${books}</tbody>
          </table>` : `<p class="empty">${tr("還沒有賠率", "No odds yet")}</p>`}
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

// the few strings that live in index.html carry both languages as data-zh / data-en (and data-aria-*)
function applyStatic() {
  for (const el of document.querySelectorAll("[data-en]")) el.textContent = tr(el.dataset.zh, el.dataset.en);
  for (const el of document.querySelectorAll("[data-aria-en]")) el.setAttribute("aria-label", tr(el.dataset.ariaZh, el.dataset.ariaEn));
  for (const b of document.querySelectorAll(".seg--lang button")) b.setAttribute("aria-pressed", String(b.dataset.lang === LANG));
}

function colophon() {
  const updated = new Date(DATA.meta.generated_at).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: ET });
  $("#colophon").textContent = tr(
    `資料：stats.nba.com · NBA 官方傷兵報告 · The Odds API（麻州 5 家）· 更新於 ${updated} ET${DATA.meta.partial ? " · 昨晚的追蹤數據還沒出來，fun fact 用前一天的累計" : ""} · 這是分析和娛樂，不是投資建議。`,
    `Data: stats.nba.com · official NBA injury reports · The Odds API (5 Massachusetts sportsbooks) · updated ${updated} ET${DATA.meta.partial ? " · last night's tracking data is not out yet, so fun facts use the totals through the night before" : ""} · Analysis and entertainment, not betting advice.`);
}

function chooseLang(lang) {
  LANG = lang === "zh" ? "zh" : "en";
  try { localStorage.setItem(LANG_KEY, LANG); } catch (err) { /* storage blocked: switch now, just not remembered */ }
  document.documentElement.lang = LANG === "zh" ? "zh-Hant" : "en";
  applyStatic();
  if (DATA.meta) {
    colophon();
    for (const t of TABS) RENDER[t]();
  }
}

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
  $(".seg--lang").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-lang]");
    if (b && b.dataset.lang !== LANG) chooseLang(b.dataset.lang);
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
  applyStatic();
  bind();
  try {
    const [meta, today, standings, lastnight] = await Promise.all(["meta", "today", "standings", "lastnight"].map(load));
    // the scorecard came later: until the daily run first writes it, its tab says so instead of failing the page
    const scorecard = await load("scorecard").catch(() => null);
    Object.assign(DATA, { meta, today, standings, lastnight, scorecard });
  } catch (err) {
    $("#view-today").innerHTML = `<p class="empty">${tr(`資料載入失敗（${esc(err.message)}），晚點再重新整理看看。`,
      `Could not load the data (${esc(err.message)}). Try refreshing in a while.`)}</p>`;
    return;
  }
  $("#mast-date").textContent = longDate(DATA.meta.day);
  colophon();
  for (const t of TABS) RENDER[t]();
  show(location.hash.slice(1));
}

init();
