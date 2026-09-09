/* What these cover, and why these:
 *
 *   the year filter   the app decides at RUNTIME which exam years exist. Get it
 *                     wrong and it either hides papers that are out or offers
 *                     papers that are not.
 *   revision decay    the widening schedule is the whole point of the ticks. An
 *                     off-by-one in the step index silently re-shows everything
 *                     on the wrong day, and nothing would look broken.
 *   merge on import   restoring a backup must never lose a tick. Union, not
 *                     replace, is the rule; this pins it.
 *   escaping          answers and notes are typed by a person and rendered with
 *                     innerHTML.
 */
import { test, describe, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp, inPage, setStore } from "./harness.mjs";

let win;
before(() => { win = loadApp(); });

const DAY = 86400000;

describe("which exam years the page offers", () => {
  test("Prelims is held back until the end of May, Mains until 1 September", () => {
    const may = inPage(win, 'satOn("prelims", 2026).toDateString()');
    const sep = inPage(win, 'satOn("mains", 2026).toDateString()');
    assert.equal(new Date(may).getMonth(), 4);
    assert.equal(new Date(may).getDate(), 31);
    assert.equal(new Date(sep).getMonth(), 8);
    assert.equal(new Date(sep).getDate(), 1);
  });

  test("a year whose exam has not been sat is not offered", () => {
    // 25 Aug 2026: Prelims 2026 is out, Mains 2026 is not.
    const shown = inPage(win, `
      (() => {
        const at = new Date(2026, 7, 25);
        const f = k => PYQ[k].filter(y => satOn(k, y.year) <= at).map(y => y.year);
        return JSON.stringify({ prelims: f("prelims")[0], mains: f("mains")[0] });
      })()`);
    const { prelims, mains } = JSON.parse(shown);
    assert.equal(prelims, 2026, "Prelims 2026 was sat in May and should show");
    assert.equal(mains, 2025, "Mains 2026 is not sat until September");
  });

  test("every year in the data is inlined, so the build stays date-independent", () => {
    const inlined = inPage(win, "PYQ.mains.map(y => y.year).join(',')");
    assert.ok(inlined.includes("2026"),
      "build.py must inline unsat years and leave the hiding to the page");
  });
});

describe("revision decay", () => {
  // Only subtopics.length is ever read; ticks themselves are the indices.
  const topic = (n = 3) =>
    `({ id: "t1", subtopics: ${JSON.stringify(Array.from({ length: n }, (_, i) => i))} })`;

  test("a finished topic never revised is due immediately", () => {
    setStore(win, { done: { t1: [0, 1, 2] }, revised: {} });
    assert.equal(inPage(win, `dueIn(${topic()})`), 0);
  });

  test("a part-ticked topic is not in the schedule at all", () => {
    setStore(win, { done: { t1: [0] }, revised: {} });
    assert.equal(inPage(win, `dueIn(${topic()})`), null,
      "part-ticked belongs to 'Not done', not to the decay list");
  });

  test("the intervals widen 3, 7, 21, 60, 120 and then hold", () => {
    const steps = [3, 7, 21, 60, 120, 120];
    for (let n = 1; n <= steps.length; n++) {
      // n revisions, the last of them today
      const stamps = Array.from({ length: n }, () => Date.now());
      setStore(win, { done: { t1: [0, 1, 2] }, revised: { t1: stamps } });
      assert.equal(inPage(win, `dueIn(${topic()})`), steps[n - 1],
        `after ${n} revision(s) the next one is due in ${steps[n - 1]} days`);
    }
  });

  test("an overdue topic reports a non-positive number", () => {
    setStore(win, {
      done: { t1: [0, 1, 2] },
      revised: { t1: [Date.now() - 5 * DAY] },      // step 1 is 3 days
    });
    const d = inPage(win, `dueIn(${topic()})`);
    assert.ok(d <= 0, `expected due or overdue, got ${d}`);
    assert.equal(inPage(win, `isDue(${topic()})`), true);
  });
});

describe("restoring a backup", () => {
  test("ticks are unioned, never replaced, and come back sorted and unique", () => {
    setStore(win, { done: { t1: [2, 1] } });
    inPage(win, "mergeStore({ done: { t1: [1, 3] } })");
    const got = JSON.parse(inPage(win, "JSON.stringify(store.done.t1)"));
    assert.deepEqual(got, [1, 2, 3], "unioned, deduped and back in order");
  });

  test("a topic only in the backup is brought in", () => {
    setStore(win, { done: { t1: [1] } });
    inPage(win, "mergeStore({ done: { t9: [1] } })");
    assert.deepEqual(JSON.parse(inPage(win, "JSON.stringify(store.done.t9)")), [1]);
  });

  test("revision dates are unioned and kept to the last twelve", () => {
    const mine = Array.from({ length: 8 }, (_, i) => 1000 + i);
    const theirs = Array.from({ length: 8 }, (_, i) => 2000 + i);
    setStore(win, { revised: { t1: mine } });
    inPage(win, `mergeStore({ revised: { t1: ${JSON.stringify(theirs)} } })`);
    const got = JSON.parse(inPage(win, "JSON.stringify(store.revised.t1)"));
    assert.equal(got.length, 12, "the tail is what matters, not a diary");
    assert.deepEqual(got, [...got].sort((a, b) => a - b), "kept in order");
    assert.equal(got.at(-1), 2007, "the most recent survives");
  });

  test("an answer already on this device wins; the backup only fills gaps", () => {
    setStore(win, { picks: { q1: "mine" } });
    inPage(win, 'mergeStore({ picks: { q1: "theirs", q2: "theirs" } })');
    assert.equal(inPage(win, "store.picks.q1"), "mine", "local data wins");
    assert.equal(inPage(win, "store.picks.q2"), "theirs", "gaps are filled");
  });
});

describe("what a person types is escaped before it is rendered", () => {
  test("esc() neutralises markup", () => {
    const out = inPage(win, `esc('<img src=x onerror=alert(1)>')`);
    assert.ok(!out.includes("<img"), `esc left markup intact: ${out}`);
    assert.ok(out.includes("&lt;"), `expected an escaped bracket, got: ${out}`);
  });
});

describe("the exam clock", () => {
  test("lastSundayOfMay really lands on a Sunday in May", () => {
    for (const y of [2025, 2026, 2027, 2028]) {
      const d = new Date(inPage(win, `lastSundayOfMay(${y}).toDateString()`));
      assert.equal(d.getDay(), 0, `${y}: not a Sunday`);
      assert.equal(d.getMonth(), 4, `${y}: not in May`);
      assert.ok(d.getDate() > 24, `${y}: not the last one`);
    }
  });

  test("nextExam is always in the future", () => {
    const on = new Date(inPage(win, "nextExam().on.toDateString()"));
    assert.ok(on >= new Date(new Date().toDateString()), `nextExam looked backwards: ${on}`);
  });
});

describe("scoring a Prelims paper against the official key", () => {
  test("2022 GS-I carries all four Series, 100 letters each", () => {
    const shape = JSON.parse(inPage(win, `
      (() => {
        const p = KEYS.years.find(y => y.year === 2022).papers.find(p => p.code === "gs1");
        return JSON.stringify({
          sets: Object.keys(p.keys),
          lengths: Object.values(p.keys).map(k => k.length),
          xs: Object.values(p.keys).map(k => k.filter(l => l === "X").length),
          droppedCount: p.dropped_count,
        });
      })()`));
    assert.deepEqual(shape.sets, ["A", "B", "C", "D"]);
    assert.deepEqual(shape.lengths, [100, 100, 100, 100]);
    assert.deepEqual(shape.xs, [1, 1, 1, 1], "one dropped question in every Series");
    assert.equal(shape.droppedCount, 1, "and the paper's own header agrees");
  });

  /* The transcription guard. UPSC builds the four Series by shuffling the same
     ten-question blocks, so every block in Set A must reappear intact in B, C
     and D. A single letter read wrong off the scan breaks the block it sits in
     and this fails — which is what makes a hand-read key trustworthy. */
  test("the four Series are permutations of one set of ten-question blocks", () => {
    const blocks = JSON.parse(inPage(win, `
      (() => {
        const p = KEYS.years.find(y => y.year === 2022).papers.find(p => p.code === "gs1");
        const cut = k => Array.from({length: 10}, (_, i) => k.slice(i*10, i*10+10).join(""));
        return JSON.stringify(Object.fromEntries(
          Object.entries(p.keys).map(([s, k]) => [s, cut(k).sort()])));
      })()`));
    for (const s of ["B", "C", "D"]) {
      assert.deepEqual(blocks[s], blocks.A,
        `Set ${s} does not use the same blocks as Set A — a letter is misread`);
    }
  });

  test("the dropped question follows the Series you sat, not the paper", () => {
    const at = JSON.parse(inPage(win, `
      (() => {
        const p = KEYS.years.find(y => y.year === 2022).papers.find(p => p.code === "gs1");
        return JSON.stringify(Object.fromEntries(Object.entries(p.keys)
          .map(([s, k]) => [s, k.indexOf("X") + 1])));
      })()`));
    assert.deepEqual(at, { A: 61, B: 71, C: 31, D: 11 });
    assert.equal(new Set(Object.values(at)).size, 4,
      "a per-paper list of dropped questions could not express this");
  });

  test("a perfect sheet scores 198 of 200 — the dropped question is left out", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        const p = KEYS.years.find(y => y.year === 2022).papers.find(p => p.code === "gs1");
        const key = p.keys.A, m = KEYS.marking.gs1;
        let right = 0, wrong = 0, blank = 0;
        key.forEach(k => { if (k === "X") return; right++; });
        return JSON.stringify({ right, marks: right * m.correct + wrong * m.wrong, total: m.total });
      })()`));
    assert.equal(out.right, 99);
    assert.equal(out.marks, 198);
    assert.equal(out.total, 200);
  });
});

describe("the syllabus tab", () => {
  test("by subject: eight groups, and the counts add up to the whole syllabus", () => {
    const g = JSON.parse(inPage(win, `
      (() => { state.lens = "subject";
        return JSON.stringify(groups().map(x => ({id: x.id, n: x.topics.length}))); })()`));
    assert.equal(g.length, 8);
    assert.equal(g.reduce((a, x) => a + x.n, 0), 242);
  });

  /* The lens is the point of the tab: the Commission sets the syllabus per
     paper, and 240 of 242 topics carry more than one paper tag, so this is a
     genuinely different shape of the same material rather than the same list
     grouped twice. */
  test("by paper: six papers, each holding exactly the topics tagged for it", () => {
    const g = JSON.parse(inPage(win, `
      (() => { state.lens = "paper";
        const out = groups().map(x => ({
          id: x.id, n: x.topics.length,
          tagged: ALL_TOPICS.filter(t => t.tp.papers.includes(x.id)).length }));
        state.lens = "subject";
        return JSON.stringify(out); })()`));
    assert.deepEqual(g.map(x => x.id),
      ["prelims", "mains-gs1", "mains-gs2", "mains-gs3", "mains-gs4", "essay"]);
    for (const x of g) assert.equal(x.n, x.tagged, `${x.id} lost topics in the regroup`);
    assert.equal(g.find(x => x.id === "prelims").n, 235);
  });

  test("most topics serve more than one paper, so the lenses really do differ", () => {
    const multi = Number(inPage(win, "ALL_TOPICS.filter(x => x.tp.papers.length > 1).length"));
    assert.equal(multi, 240);
  });

  test("progress counts topics and subtopics separately", () => {
    setStore(win, { done: {} });
    const t = JSON.parse(inPage(win, "JSON.stringify(tally(ALL_TOPICS.map(x => x.tp)))"));
    assert.equal(t.tTot, 242);
    assert.equal(t.sTot, 1723);
    assert.equal(t.tDone, 0);
    // finishing one topic moves the topic count by one and the subtopic count
    // by that topic's length — one percentage could not say both
    const n = Number(inPage(win, `
      (() => { const tp = ALL_TOPICS[0].tp;
        store.done[tp.id] = tp.subtopics.map((_, i) => i);
        return tp.subtopics.length; })()`));
    const after = JSON.parse(inPage(win, "JSON.stringify(tally(ALL_TOPICS.map(x => x.tp)))"));
    assert.equal(after.tDone, 1);
    assert.equal(after.sDone, n);
  });

  test("read-it-all renders every subtopic, not a teaser", () => {
    const html = inPage(win, "readHtml()");
    const items = (html.match(/<li>/g) || []).length;
    assert.equal(items, 1723, "the whole syllabus has to be in the read view");
    assert.equal((html.match(/<h2>/g) || []).length, 8);
    assert.equal((html.match(/<h3>/g) || []).length, 242);
  });

  test("a topic opened in place shows all of its subtopics and what it counts for", () => {
    const out = JSON.parse(inPage(win, `
      (() => { const tp = ALL_TOPICS.find(x => x.tp.papers.length > 1).tp;
        const h = subtopicsHtml(tp, "");
        return JSON.stringify({ boxes: (h.match(/data-tick=/g) || []).length,
                                subtopics: tp.subtopics.length,
                                counts: /Counts for /.test(h) }); })()`));
    assert.equal(out.boxes, out.subtopics, "every subtopic is a tick target");
    assert.ok(out.counts, "the topic says which papers it serves");
  });

  test("search reaches subtopics and marks what matched", () => {
    const out = JSON.parse(inPage(win, `
      (() => { const term = "monsoon";
        const hits = ALL_TOPICS.filter(({tp}) =>
          tp.name.toLowerCase().includes(term) ||
          tp.subtopics.some(s => s.toLowerCase().includes(term)));
        const h = topicHtml(hits[0].tp, hits[0].s, term);
        return JSON.stringify({ topics: hits.length, marked: /<mark>/.test(h) }); })()`));
    assert.ok(out.topics > 0, "monsoon should match something in a UPSC syllabus");
    assert.ok(out.marked, "matched words are highlighted");
  });
});

describe("the Optional tab", () => {
  test("three subjects, each with eleven years and both papers linked", () => {
    const subs = JSON.parse(inPage(win, `
      (() => JSON.stringify((OPTIONALS.subjects || []).map(s => ({
        id: s.id,
        years: s.pyq.length,
        span: [s.pyq[s.pyq.length - 1].year, s.pyq[0].year],
        linked: s.pyq.reduce((a, y) => a + y.papers.filter(p => p.url).length, 0),
        codes: [...new Set(s.pyq.flatMap(y => y.papers.map(p => p.code)))],
      }))))()`));
    assert.deepEqual(subs.map(s => s.id), ["geography", "law", "agriculture"]);
    for (const s of subs) {
      assert.equal(s.years, 11, `${s.id} should span eleven years`);
      assert.deepEqual(s.span, [2016, 2026], `${s.id} span`);
      assert.equal(s.linked, 22, `${s.id} should have both papers for every year`);
      assert.deepEqual(s.codes, ["p1", "p2"]);
    }
  });

  /* 2023 is the year the scraper used to lose: the Commission labelled it
     "Agricultural Paper - I" that year and "Agriculture" in every other, so
     matching the subject name exactly dropped it without a word. */
  test("Agriculture has 2023, the year the Commission spelled differently", () => {
    const y = JSON.parse(inPage(win, `
      (() => { const a = OPTIONALS.subjects.find(s => s.id === "agriculture");
        const y = a.pyq.find(y => y.year === 2023);
        return JSON.stringify(y ? y.papers.map(p => p.url) : null); })()`));
    assert.ok(y, "2023 is missing from Agriculture again");
    assert.equal(y.length, 2);
    for (const u of y) assert.match(u, /upsc\.gov\.in/, "papers stay on the Commission's site");
  });

  test("the answer log key keeps the three subjects apart", () => {
    const ids = JSON.parse(inPage(win, "JSON.stringify(OPTIONALS.subjects.map(s => s.id))"));
    assert.equal(new Set(ids).size, ids.length,
      "the log is keyed year-<subject id>-<code>; a duplicate id would merge two subjects");
  });
});

describe("the focus dial", () => {
  test("the dial is bounded at 1 and 60 minutes, whatever it is handed", () => {
    const c = JSON.parse(inPage(win,
      "JSON.stringify([focusClamp(0), focusClamp(-9), focusClamp(1), focusClamp(60), focusClamp(61), focusClamp(999), focusClamp(25.4)])"));
    assert.deepEqual(c, [1, 1, 1, 60, 60, 60, 25]);
  });

  test("a run is stored, not held in a variable, so a reload cannot lose it", () => {
    inPage(win, "focusStart(45)");
    const r = JSON.parse(inPage(win, "JSON.stringify(store.focusRun)"));
    assert.equal(r.mins, 45);
    assert.ok(r.start > 0, "the clock is a wall-clock start, not a countdown in memory");
    const left = Number(inPage(win, "focusLeft(store.focusRun)"));
    assert.ok(left > 44 * 60000 && left <= 45 * 60000, `remaining looked wrong: ${left}`);
  });

  /* The whole feature. Leaving is not blocked — it is counted, and counting it
     is worth nothing unless it actually costs the run. */
  test("leaving the app voids the run and puts the clock back to zero", () => {
    inPage(win, "focusStart(30); store.focusStreak = 4;");
    inPage(win, "focusInterrupt()");
    assert.equal(inPage(win, "store.focusRun"), null, "the run is gone, not paused");
    assert.equal(Number(inPage(win, "store.focusStreak")), 0, "the streak resets to zero");
    assert.equal(JSON.parse(inPage(win, "JSON.stringify(store.focus)")).at(-1).kind, "void");
  });

  test("the native side reports every way of leaving through one hook", () => {
    inPage(win, "focusStart(30)");
    assert.equal(inPage(win, "typeof window.taracmdInterrupted"), "function",
      "MainActivity.onPause calls this by name");
    inPage(win, "window.taracmdInterrupted()");
    assert.equal(inPage(win, "store.focusRun"), null);
  });

  test("a run seen out counts, and lengthens the streak", () => {
    inPage(win, "store.focusStreak = 2; focusStart(1); store.focusRun.start = Date.now() - 61000;");
    assert.equal(inPage(win, "focusDone(store.focusRun)"), true);
    inPage(win, 'focusEnd("done")');
    assert.equal(JSON.parse(inPage(win, "JSON.stringify(store.focus)")).at(-1).kind, "done");
    assert.equal(Number(inPage(win, "store.focusStreak")), 3);
  });

  test("nothing about the phone is blocked — back is the app's, not the run's", () => {
    inPage(win, "focusStart(30); state.tab = 'focus'; state.read = false;");
    inPage(win, "state.open = new Set(); state.openTopics = new Set();");
    inPage(win, "openId = null");
    assert.equal(inPage(win, "state.tab !== 'syllabus' ? taracmdBack() : true"), true,
      "back still walks the app; a run must not hold it hostage");
    inPage(win, 'focusEnd("void")');
  });

  test("the dial's geometry puts 60 at the top and 15 at the right", () => {
    const pts = JSON.parse(inPage(win,
      "JSON.stringify({top: focusPoint(60).map(Math.round), right: focusPoint(15).map(Math.round)})"));
    assert.deepEqual(pts.top, [100, 16], "60 minutes is twelve o'clock");
    assert.deepEqual(pts.right, [184, 100], "15 minutes is three o'clock");
  });

  test("the log is capped, so a year of runs cannot fill localStorage", () => {
    inPage(win, `store.focus = Array.from({length: 80}, (_, i) => ({on: i, mins: 25, ran: 1, kind: "done"}));`);
    inPage(win, 'focusStart(25); focusEnd("void")');
    const n = Number(inPage(win, "store.focus.length"));
    assert.ok(n <= 60, `log grew to ${n}`);
  });
});

describe("navigation", () => {
  test("four tabs, and Papers holds the three paper indexes as segments", () => {
    const tabs = JSON.parse(inPage(win,
      `JSON.stringify([...document.querySelectorAll(".tab")].map(t => t.dataset.tab))`));
    assert.deepEqual(tabs, ["syllabus", "papers", "practice", "focus"],
      "seven tabs was three tabs for one idea; Prelims/Mains/Optional are segments now");
    const segs = JSON.parse(inPage(win, "JSON.stringify(PAPER_SEGS.map(s => s[0]))"));
    assert.deepEqual(segs, ["prelims", "mains", "optional"]);
  });

  test("every paper index still renders behind its segment", () => {
    for (const seg of ["prelims", "mains", "optional"]) {
      inPage(win, `state.tab = "papers"; state.pset = ${JSON.stringify(seg)}; render();`);
      // textContent, not innerText: jsdom does not implement innerText at all
      const body = inPage(win, `document.getElementById("papersview").textContent`);
      assert.ok(body && body.length > 40, `${seg} rendered nothing behind the segment`);
    }
  });

  /* renderPapers points the paper renderers at a panel below its segment by
     reassigning `view`. If it ever failed to put it back, every later render
     would draw into the wrong element. */
  test("renderPapers puts `view` back where it found it", () => {
    inPage(win, `state.tab = "papers"; state.pset = "prelims"; render();`);
    assert.equal(inPage(win, `view === document.getElementById("view")`), true);
  });

  test("the drawer holds the long tail, and Toppers lights no tab", () => {
    const items = JSON.parse(inPage(win,
      `JSON.stringify([...document.querySelectorAll(".ditem b")].map(e => e.textContent))`));
    assert.deepEqual(items,
      ["Toppers' copies", "Read the whole syllabus", "Back up or restore", "Updates"],
      "the drawer is where rare destinations go, so name them rather than count them");
    inPage(win, `state.tab = "toppers"; markTab("toppers"); render();`);
    assert.equal(Number(inPage(win, `document.querySelectorAll(".tab.on").length`)), 0,
      "no tab may claim to be where you are when you are somewhere else");
  });

  /* The ladder is the part a regroup can quietly break. Drawer first, because
     it is the topmost thing on the screen. */
  test("back unwinds drawer, then sheet, then the outline, then the tab", () => {
    inPage(win, `state.tab = "syllabus"; state.read = false; openId = null;
                 state.open = new Set(); state.openTopics = new Set(); openDrawer();`);
    assert.equal(inPage(win, "taracmdBack()"), true, "drawer closes first");
    assert.equal(inPage(win, "drawerOpen()"), false);

    inPage(win, `state.open = new Set(["polity"]);`);
    assert.equal(inPage(win, "taracmdBack()"), true, "an open outline collapses");
    assert.equal(Number(inPage(win, "state.open.size")), 0);

    inPage(win, `state.tab = "papers"; markTab("papers");`);
    assert.equal(inPage(win, "taracmdBack()"), true, "any other tab returns to the syllabus");
    assert.equal(inPage(win, "state.tab"), "syllabus");

    assert.equal(inPage(win, "taracmdBack()"), false, "then the OS takes over");
  });

  test("the theme control has three states, not two", () => {
    const opts = JSON.parse(inPage(win,
      `JSON.stringify([...document.querySelectorAll("[data-theme-set]")].map(b => b.dataset.themeSet))`));
    assert.deepEqual(opts, ["light", "dark", "system"],
      "'follow the phone' is a state a toggle cannot express");
    inPage(win, `store.theme = null; markTheme();`);
    assert.equal(inPage(win, `document.querySelector("[data-theme-set='system']").classList.contains("on")`),
      true, "no stored theme means System, not Light");
  });
});

describe("updates", () => {
  test("the drawer says what is installed and where the newer one is", () => {
    inPage(win, "openDrawer()");
    const item = inPage(win, `document.getElementById("dUpdate").textContent`);
    assert.match(item, /Updates/);
    // no bridge in a browser, so it must not claim to know a version
    assert.equal(inPage(win, "appVersion()"), null);
    assert.match(inPage(win, `document.getElementById("dVer").textContent`),
      /only known inside the app/);
    inPage(win, "closeDrawer()");
  });

  /* The repository is private, so a version check from the page would need a
     token — and a token shipped inside an APK is a token given away. The link
     goes to where the build lives instead. */
  test("no credential is embedded for the update check", () => {
    const src = inPage(win, "RELEASES");
    assert.match(src, /^https:\/\/github\.com\//);
    assert.ok(!/token|ghp_|Authorization|api\.github\.com/i.test(src),
      "the update link must not carry or imply a credential");
  });
});

describe("today's plan and the focus history", () => {
  test("the plan is drawn from your own data, not invented", () => {
    // nothing done, nothing due, quiz logged -> nothing to do
    const today = new Date().toISOString().slice(0, 10);
    setStore(win, { done: {}, revised: {}, picks: {}, daily: { [today]: {score: 5, of: 5} } });
    assert.equal(JSON.parse(inPage(win, "JSON.stringify(planItems())")).length, 0,
      "an empty plan is honest when there is nothing due");

    // a finished topic revised long ago falls due, and lands on the plan
    inPage(win, `(() => { const tp = ALL_TOPICS[0].tp;
      store.done[tp.id] = tp.subtopics.map((_, i) => i);
      store.revised[tp.id] = [Date.now() - 200 * 86400000]; })()`);
    const items = JSON.parse(inPage(win, "JSON.stringify(planItems())"));
    assert.equal(items.length, 1);
    assert.equal(items[0].kind, "topic");
    assert.match(items[0].note, /overdue/);
  });

  test("the plan is capped, so a backlog does not become a wall", () => {
    inPage(win, `(() => { store.done = {}; store.revised = {};
      ALL_TOPICS.slice(0, 40).forEach(({tp}) => {
        store.done[tp.id] = tp.subtopics.map((_, i) => i);
        store.revised[tp.id] = [Date.now() - 300 * 86400000]; }); })()`);
    const topics = JSON.parse(inPage(win, `JSON.stringify(planItems().filter(i => i.kind === "topic"))`));
    assert.equal(topics.length, Number(inPage(win, "PLAN_N")),
      "forty overdue topics is a list nobody reads; the syllabus tab has the rest");
  });

  test("history counts only runs that were seen out", () => {
    const DAY = 86400000;
    inPage(win, `store.focus = [
      {on: Date.now(),           mins: 25, ran: 1500, kind: "done"},
      {on: Date.now(),           mins: 45, ran: 600,  kind: "void"},
      {on: Date.now() - ${DAY},  mins: 30, ran: 1800, kind: "done"}];`);
    const days = JSON.parse(inPage(win, "JSON.stringify(focusHistory())"));
    assert.equal(days.length, 14, "a fortnight, including the days with nothing on them");
    assert.equal(days.at(-1).mins, 25, "the voided 10 minutes are not focused time");
    assert.equal(days.at(-1).voided, 1, "but they are still shown");
    assert.equal(days.at(-2).mins, 30);
  });
});

describe("typing a past question in", () => {
  /* The scorer used to be a bare answer sheet. A question tagged with its
     paper cell is asked properly; an untyped one stays a lettered cell, and
     both live in the same grid so a paper fills in as it is typed. */
  test("a tagged question is asked with its options; the rest stay letters", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        const paper = KEYS.years.find(y => y.year === 2022).papers.find(p => p.code === "gs1");
        QUIZ.questions.push({ id: "t-1", topic: "polity-basic-structure",
          paper: {year: 2022, code: "gs1", set: "A", n: 2},
          q: "typed question", options: ["a","b","c","d"],
          answer: "ABCD".indexOf(paper.keys.A[1]) });
        // the answer sheet is reached by opening the UPSC paper as a paper;
        // "Score a paper" as a mode of its own is gone
        state.tab = "practice"; state.qmode = "papers";
        state.qpaperId = "upsc-2022-gs1"; state.qset = "A"; state.qn = 1;
        render();
        const r = { wide: document.querySelectorAll(".cell.wide").length,
                    plain: document.querySelectorAll(".cell:not(.wide)").length,
                    opts: document.querySelectorAll(".copt").length };
        QUIZ.questions.pop();
        return JSON.stringify(r);
      })()`));
    assert.equal(out.wide, 1, "the typed question is asked properly");
    assert.equal(out.opts, 4);
    assert.equal(out.plain, 99, "the other 99 are still an answer sheet");
  });

  test("a tagged question belongs to one set only", () => {
    // the sets are shuffled against each other, so a tag names a set as well
    // as a number and must not leak into another set's paper
    const leaked = inPage(win, `
      (() => {
        QUIZ.questions.push({ id: "t-2", topic: "polity-basic-structure",
          paper: {year: 2022, code: "gs1", set: "A", n: 2},
          q: "typed", options: ["a","b","c","d"], answer: 0 });
        // one folder per paper now; the Series is a control inside the sheet
        state.qpaperId = "upsc-2022-gs1"; state.qset = "B"; render();
        const n = document.querySelectorAll(".cell.wide").length;
        QUIZ.questions.pop(); state.qset = "A"; render();
        return n;
      })()`);
    assert.equal(Number(leaked), 0, "a Set A question must not appear on Set B");
  });
});
