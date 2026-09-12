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

  /* The transcription guard, and it now guards ten years rather than one.
     UPSC builds the four Series by shuffling the same blocks of questions, so
     every block of Set A must reappear intact in B, C and D. One letter read
     wrong off a scan breaks the block it sits in and this fails.

     The block size is NOT fixed — 2017 shuffles four blocks of twenty-five,
     2018 and 2026 five, the rest ten — so it is discovered, largest first,
     exactly as tools/keycheck.py does. A key that matches at no block size of
     five or more is a misread, not a new format.

     Except CSAT, which keeps each passage's questions together, so its blocks
     are passages of uneven length — 2018 is 10,10,13,15,12,20 — and no size
     fits. Then each Series must be spelled out of disjoint runs of Set A, every
     run at least four long, using each of A's letters once: the same cover
     keycheck.py falls back to. */
  test("every stored key is a block permutation of its own Set A", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        const cut = (k, b) => Array.from({length: k.length / b}, (_, i) => k.slice(i*b, i*b+b).join(""));
        const same = (x, y) => x.length === y.length && x.every((v, i) => v === y[i]);
        const covers = (v, A, min) => {
          const used = A.map(() => false);
          let budget = 200000;
          const go = i => {
            if(i === v.length) return true;
            if(--budget < 0) return false;
            const cands = [];
            for(let j = 0; j < A.length; j++){
              let L = 0;
              while(i + L < v.length && j + L < A.length && !used[j + L] && A[j + L] === v[i + L]) L++;
              if(L >= min) cands.push([j, L]);
            }
            cands.sort((a, b) => b[1] - a[1]);
            for(const [j, L] of cands) for(let l = L; l >= min; l--){
              for(let t = 0; t < l; t++) used[j + t] = true;
              if(go(i + l)) return true;
              for(let t = 0; t < l; t++) used[j + t] = false;
            }
            return false;
          };
          return go(0);
        };
        const res = [];
        for(const y of KEYS.years) for(const p of y.papers){
          const sets = Object.keys(p.keys || {});
          if(!sets.length) continue;
          const n = p.keys.A.length;
          let found = null;
          for(let b = Math.floor(n / 2); b >= 5; b--){
            if(n % b) continue;
            const a = cut(p.keys.A, b).sort();
            if(["B","C","D"].every(s => same(cut(p.keys[s], b).sort(), a))){ found = b; break; }
          }
          if(!found && p.code === "gs2" && ["B","C","D"].every(s => covers(p.keys[s], p.keys.A, 4)))
            found = "passages";
          res.push({ id: y.year + " " + p.code, block: found,
                     want: (KEYS.marking[p.code] || {}).questions,
                     lens: sets.map(s => p.keys[s].length),
                     xs: sets.map(s => p.keys[s].filter(l => l === "X").length) });
        }
        return JSON.stringify(res);
      })()`));
    assert.ok(out.length >= 20, `only ${out.length} papers carry a key`);
    for (const r of out) {
      assert.ok(r.block, `${r.id}: the four Series match at no block size — a letter is misread`);
      assert.deepEqual(r.lens, [r.want, r.want, r.want, r.want], `${r.id}: a Series is the wrong length`);
      assert.equal(new Set(r.xs).size, 1,
        `${r.id}: the Series disagree on how many questions were dropped`);
    }
  });

  /* Ten years of GS-I, which is what the year chips offer. Fewer means a key
     was lost, not that a year stopped existing. */
  test("GS Paper I carries a key for every year from 2017 to 2026", () => {
    const years = JSON.parse(inPage(win, `
      JSON.stringify(KEYS.years
        .filter(y => y.papers.some(p => p.code === "gs1" && Object.keys(p.keys || {}).length))
        .map(y => y.year).sort())`));
    assert.deepEqual(years, [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]);
  });

  /* The 2026 key is provisional — published weeks after the exam and open to
     representations. The app must not call it final. */
  test("a provisional key is labelled provisional", () => {
    const st = inPage(win, `KEYS.years.find(y => y.year === 2026).status`);
    assert.equal(st, "provisional");
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
  test("by subject: nine groups, and the counts add up to the whole syllabus", () => {
    const g = JSON.parse(inPage(win, `
      (() => { state.lens = "subject";
        return JSON.stringify(groups().map(x => ({id: x.id, n: x.topics.length}))); })()`));
    assert.equal(g.length, 9);
    assert.equal(g.reduce((a, x) => a + x.n, 0), 249);
  });

  /* The lens is the point of the tab: the Commission sets the syllabus per
     paper, and 240 of 249 topics carry more than one paper tag, so this is a
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
    assert.equal(g.find(x => x.id === "prelims").n, 242);
  });

  test("most topics serve more than one paper, so the lenses really do differ", () => {
    const multi = Number(inPage(win, "ALL_TOPICS.filter(x => x.tp.papers.length > 1).length"));
    assert.equal(multi, 240);
  });

  test("progress counts topics and subtopics separately", () => {
    setStore(win, { done: {} });
    const t = JSON.parse(inPage(win, "JSON.stringify(tally(ALL_TOPICS.map(x => x.tp)))"));
    assert.equal(t.tTot, 249);
    assert.equal(t.sTot, 1760);
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
    assert.equal(items, 1760, "the whole syllabus has to be in the read view");
    assert.equal((html.match(/<h2>/g) || []).length, 9);
    assert.equal((html.match(/<h3>/g) || []).length, 249);
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
  test("five tabs, and Papers holds the three paper indexes as segments", () => {
    const tabs = JSON.parse(inPage(win,
      `JSON.stringify([...document.querySelectorAll(".tab")].map(t => t.dataset.tab))`));
    assert.deepEqual(tabs, ["syllabus", "papers", "practice", "focus", "docs"],
      "seven tabs was three tabs for one idea; Prelims/Mains/Optional are segments now");
    const segs = JSON.parse(inPage(win, "JSON.stringify(PAPER_SEGS.map(s => s[0]))"));
    assert.deepEqual(segs, ["prelims", "mains", "optional"]);
  });

  /* The bar is a grid with a hard-coded column count. A button more than there
     are columns does not overflow or clip — it silently wraps onto a second
     row, which is the kind of bug you only see on a phone. So the count is
     pinned to the buttons rather than trusted. */
  test("the tab bar has exactly as many columns as it has tabs", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        // no regex: this string is a template literal on its way through
        // eval, and a template literal eats the backslash in \d before the
        // regex ever sees it, which quietly matches nothing.
        const css = [...document.querySelectorAll("style")].map(s => s.textContent).join("");
        const at = css.indexOf(".tabs{");
        const rule = at < 0 ? "" : css.slice(at, css.indexOf("}", at));
        const key = "grid-template-columns:repeat(";
        const k = rule.indexOf(key);
        const cols = k < 0 ? null : Number(rule.slice(k + key.length, rule.indexOf(",", k)));
        return JSON.stringify({ cols, tabs: document.querySelectorAll(".tab").length });
      })()`));
    assert.equal(out.cols, out.tabs, "a fifth tab in a four-column grid quietly wraps");
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

/* These tests are about the MECHANISM -- a tagged question being asked, an
   untyped number staying a lettered cell -- so they must not depend on what
   happens to be in the bank. They used to go looking for a paper with nothing
   typed in; 2022 was that paper when they were written, then 2020 was, and
   once every year is imported there is no such paper at all.

   So each test takes one paper, sets its real questions aside for the length
   of the test, and puts them back. SETASIDE opens that, PUTBACK closes it. */
const YR = 2022;
const SETASIDE = `
        const __saved = QUIZ.questions;
        QUIZ.questions = __saved.filter(q => !(q.paper && q.paper.year === ${YR} && q.paper.code === "gs1"));`;
const PUTBACK = `QUIZ.questions = __saved;`;

describe("typing a past question in", () => {
  /* The scorer used to be a bare answer sheet. A question tagged with its
     paper cell is asked properly; an untyped one stays a lettered cell, and
     both live in the same grid so a paper fills in as it is typed. */
  test("a tagged question is asked with its options; the rest stay letters", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        const YR = ${YR};${SETASIDE}
        const paper = KEYS.years.find(y => y.year === YR).papers.find(p => p.code === "gs1");
        QUIZ.questions.push({ id: "t-1", topic: "polity-basic-structure",
          paper: {year: YR, code: "gs1", set: "A", n: 2},
          q: "typed question", options: ["a","b","c","d"],
          answer: "ABCD".indexOf(paper.keys.A[1]) });
        // the answer sheet is reached by opening the UPSC paper as a paper;
        // "Score a paper" as a mode of its own is gone
        state.tab = "practice"; state.qmode = "papers";
        state.qpaperId = "upsc-" + YR + "-gs1"; state.qset = "A"; state.qn = 1;
        // the plain grid is still there, behind its own link, for when the
        // paper is open in front of you and you only want to mark letters
        state.qsheet = true;
        render();
        const r = { wide: document.querySelectorAll(".cell.wide").length,
                    plain: document.querySelectorAll(".cell:not(.wide)").length,
                    opts: document.querySelectorAll(".copt").length };
        QUIZ.questions.pop(); ${PUTBACK}
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
        const YR = ${YR};${SETASIDE}
        QUIZ.questions.push({ id: "t-2", topic: "polity-basic-structure",
          paper: {year: YR, code: "gs1", set: "A", n: 2},
          q: "typed", options: ["a","b","c","d"], answer: 0 });
        // one folder per paper now; the Series is a control inside the sheet
        state.qpaperId = "upsc-" + YR + "-gs1"; state.qset = "B"; state.qsheet = true; render();
        const n = document.querySelectorAll(".cell.wide").length;
        QUIZ.questions.pop(); ${PUTBACK} state.qset = "A"; state.qsheet = false; render();
        return n;
      })()`);
    assert.equal(Number(leaked), 0, "a Set A question must not appear on Set B");
  });

  /* Once a UPSC paper has its questions typed in it stops being an answer
     sheet and becomes a paper you sit — one question at a time, with the
     numbers nobody has typed yet still in the palette so you never score out
     of 95 on a hundred-question paper. */
  test("a typed UPSC paper is sat one question at a time", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        const YR = ${YR};${SETASIDE}
        const paper = KEYS.years.find(y => y.year === YR).papers.find(p => p.code === "gs1");
        QUIZ.questions.push({ id: "t-3", topic: "polity-basic-structure",
          paper: {year: YR, code: "gs1", set: "A", n: 2},
          q: "the typed one", options: ["w","x","y","z"],
          answer: "ABCD".indexOf(paper.keys.A[1]) });
        state.tab = "practice"; state.qmode = "papers";
        state.qpaperId = "upsc-" + YR + "-gs1"; state.qset = "A"; state.qsheet = false;
        state.qn = 2; render();
        const asked = { stem: document.querySelector(".qcard.run .qstem").textContent.trim(),
                        opts: document.querySelectorAll(".qcard.run .opt").length,
                        palette: document.querySelectorAll(".palette .pq").length,
                        dropped: document.querySelectorAll(".palette .pq.drop").length };
        state.qn = 3; render();
        asked.untypedIsLettersOnly = document.querySelectorAll(".qcard.run .opt.lonly").length;
        QUIZ.questions.pop(); ${PUTBACK} state.qpaperId = null; render();
        return JSON.stringify(asked);
      })()`));
    assert.equal(out.stem, "the typed one", "the typed question is asked");
    assert.equal(out.opts, 4);
    assert.equal(out.palette, 100, "the whole paper is in the palette, not just what is typed");
    assert.equal(out.dropped, 1, "the question the Commission dropped is marked as dropped");
    assert.equal(out.untypedIsLettersOnly, 4, "an untyped number still takes a letter");
  });

  /* The sheet is per Series because the paper is. Reading it off the folder id
     instead meant a UPSC paper always reported nothing answered, however much
     of it had been filled in. */
  test("a UPSC answer sheet is stored per Series", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        store.attempts["2022-gs1-A"] = {1: 0, 2: 1, 3: 2};
        const p = paperList().find(x => x.id === "upsc-2022-gs1");
        p.set = "A"; const onA = paperAnswered(p);
        p.set = "B"; const onB = paperAnswered(p);
        delete store.attempts["2022-gs1-A"];
        return JSON.stringify({onA, onB});
      })()`));
    assert.equal(out.onA, 3, "the sheet is found where the scorer writes it");
    assert.equal(out.onB, 0, "and it does not bleed into another Series");
  });
});

/* The exam hall's colour language. Green/red/grey is not decoration: without
   the middle state a question you skipped and one you have never reached look
   identical, and the palette stops being able to tell you where the work is. */
describe("the question palette", () => {
  test("answered, seen-but-not-answered and not-visited are three states", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        state.tab = "practice"; state.qmode = "papers";
        state.qpaperId = "upsc-2023-gs1"; state.qset = "B"; state.qsheet = false;
        delete store.attempts["2023-gs1-B"]; delete store.seen["2023-gs1-B"];
        state.qn = 1; render();
        // answer 1 and 2, then look at 3 and 4 and leave them
        for(const k of [1, 2]){ state.qn = k; render();
          document.querySelectorAll(".qcard.run .opt")[0].click(); }
        for(const k of [3, 4]){ state.qn = k; render(); }
        state.qn = 50; render();
        const cls = n => document.querySelector(\`.pq[data-goq="\${n}"]\`).className;
        const r = { answered: cls(1), alsoAnswered: cls(2), seen: cls(3), seen2: cls(4),
                    untouched: cls(80), here: cls(50), dropped: cls(14) };
        delete store.attempts["2023-gs1-B"]; delete store.seen["2023-gs1-B"];
        state.qpaperId = null; save();
        return JSON.stringify(r);
      })()`));
    assert.match(out.answered, /\bdone\b/, "an answered question is green");
    assert.match(out.alsoAnswered, /\bdone\b/);
    assert.match(out.seen, /\bleft\b/, "one you looked at and left is red");
    assert.match(out.seen2, /\bleft\b/);
    assert.doesNotMatch(out.untouched, /\b(done|left)\b/, "one you never reached stays grey");
    assert.match(out.here, /\bhere\b/);
    assert.match(out.dropped, /\bdrop\b/);
  });

  test("answering a question you had skipped turns it green", () => {
    const out = inPage(win, `
      (() => {
        state.tab = "practice"; state.qmode = "papers";
        state.qpaperId = "upsc-2023-gs1"; state.qset = "B"; state.qsheet = false;
        delete store.attempts["2023-gs1-B"]; delete store.seen["2023-gs1-B"];
        state.qn = 5; render();                       // seen, left alone
        state.qn = 6; render();
        state.qn = 5; render();                       // came back
        document.querySelectorAll(".qcard.run .opt")[2].click();
        state.qn = 9; render();
        const c = document.querySelector('.pq[data-goq="5"]').className;
        delete store.attempts["2023-gs1-B"]; delete store.seen["2023-gs1-B"];
        state.qpaperId = null; save();
        return c;
      })()`);
    assert.match(out, /\bdone\b/, "answered beats seen, or coming back would look like failing");
  });
});

/* The syllabus tab is called Syllabus, and used to open on three stacked
   dashboard cards with the syllabus itself below the fold. The map is the
   whole of it on one screen — every topic, one square. */
describe("the syllabus map", () => {
  test("every topic gets a square, and none is invented", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        state.tab = "syllabus"; state.lens = "map"; render();
        const tiles = [...document.querySelectorAll(".mt")];
        const ids = tiles.map(t => t.dataset.sheet);
        return JSON.stringify({
          tiles: tiles.length,
          topics: ALL_TOPICS.length,
          subjects: document.querySelectorAll(".mapsub").length,
          allReal: ids.every(id => !!OWNER[id]),
          unique: new Set(ids).size
        });
      })()`));
    assert.equal(out.tiles, out.topics, "one square per topic, all 249 of them");
    assert.equal(out.unique, out.topics, "and no topic drawn twice");
    assert.equal(out.subjects, 9);
    assert.ok(out.allReal, "every square resolves to a real topic");
  });

  test("the map opens on the syllabus, not on a stack of cards", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        state.tab = "syllabus"; state.lens = "map"; render();
        return JSON.stringify({ pace: document.querySelectorAll(".pace").length,
                                map: document.querySelectorAll(".mapwrap").length });
      })()`));
    assert.equal(out.map, 1);
    assert.equal(out.pace, 0, "the exam clock folds into the map's own header line");
  });
});

/* The shelf. What matters is not the listing but WHERE the files are: every
   directory the app owns is deleted with the app, so the shelf is a folder the
   user picks and the app is only a guest in it. */
describe("the shelf", () => {
  test("without the Android bridge it says so instead of pretending", () => {
    const out = inPage(win, `
      (() => { state.tab = "docs"; render(); return view.textContent; })()`);
    assert.match(out, /needs the Android app/);
    assert.doesNotMatch(out, /Add documents/, "no controls that could not work");
  });

  test("with a bridge but no folder yet, it asks for one and is honest about uninstalling", () => {
    const w = loadApp({ docsList: () => "[]", docsFolder: () => null,
                        docsPick: () => {}, docsAdd: () => {},
                        docsOpen: () => {}, docsRemove: () => true });
    const out = inPage(w, `(() => { state.tab = "docs"; render(); return view.textContent; })()`);
    assert.match(out, /Choose the folder/);
    assert.match(out, /will not delete them/, "the whole point of the feature is stated");
  });

  test("with a folder it lists what is in it, and nothing else", () => {
    const files = [
      { id: "content://tree/doc/1", name: "Laxmikanth notes.pdf", size: 2411724,
        mime: "application/pdf", on: 1757000000000 },
      { id: "content://tree/doc/2", name: "map practice.png", size: 51200,
        mime: "image/png", on: 1756900000000 },
    ];
    const w = loadApp({ docsList: () => JSON.stringify(files),
                        docsFolder: () => "TaraCmd", docsPick: () => {}, docsAdd: () => {},
                        docsOpen: () => {}, docsRemove: () => true });
    const out = JSON.parse(inPage(w, `
      (() => {
        state.tab = "docs"; render();
        return JSON.stringify({
          rows: document.querySelectorAll(".drow").length,
          names: [...document.querySelectorAll(".dn")].map(n => n.textContent),
          sizes: [...document.querySelectorAll(".ds")].map(n => n.textContent),
          ids: [...document.querySelectorAll("[data-doc]")].map(n => n.dataset.doc),
          folder: document.querySelector(".dfolder").textContent.trim()
        });
      })()`));
    assert.equal(out.rows, 2);
    assert.deepEqual(out.names, ["Laxmikanth notes.pdf", "map practice.png"]);
    assert.match(out.sizes[0], /2\.3 MB/);
    assert.deepEqual(out.ids, ["content://tree/doc/1", "content://tree/doc/2"]);
    assert.match(out.folder, /TaraCmd/);
  });

  test("a document's name is escaped, because the phone's filesystem is not a trusted author", () => {
    const w = loadApp({
      docsList: () => JSON.stringify([{ id: "content://x", name: "<img src=x onerror=alert(1)>.pdf",
                                        size: 10, mime: "application/pdf", on: 0 }]),
      docsFolder: () => "TaraCmd", docsPick: () => {}, docsAdd: () => {},
      docsOpen: () => {}, docsRemove: () => true });
    const out = JSON.parse(inPage(w, `
      (() => {
        state.tab = "docs"; render();
        return JSON.stringify({ imgs: document.querySelectorAll(".dn img").length,
                                text: document.querySelector(".dn").textContent });
      })()`));
    assert.equal(out.imgs, 0, "a filename must never become markup");
    assert.match(out.text, /onerror/, "it is shown as the text it is");
  });
});

/* A, B, C and D are the same hundred questions shuffled, so a paper that can
   only ask you one of them was offering three empty grids as if they were
   three more papers. */
describe("the Series chips", () => {
  test("only the Series whose questions are typed in is offered", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        state.tab = "practice"; state.qmode = "papers";
        state.qpaperId = "upsc-2023-gs1"; state.qset = "B";
        state.qsheet = true; state.qallsets = false; render();
        const shown = [...document.querySelectorAll("[data-set]")].map(b => b.textContent.trim());
        const link = !!document.getElementById("allsets");
        return JSON.stringify({ shown, link });
      })()`));
    assert.deepEqual(out.shown, ["Set B"], "2023 has questions typed for Set B only");
    assert.ok(out.link, "and the other three are one tap away, not gone");
  });

  test("the other Series come back when you say you sat one", () => {
    const shown = JSON.parse(inPage(win, `
      (() => {
        document.getElementById("allsets").click();
        const s = [...document.querySelectorAll("[data-set]")].map(b => b.textContent.trim());
        state.qallsets = false;
        return JSON.stringify(s);
      })()`));
    assert.deepEqual(shown, ["Set A", "Set B", "Set C", "Set D"]);
  });

  test("a paper with nothing typed offers all four and hides nothing", () => {
    const out = JSON.parse(inPage(win, `
      (() => {
        const __s2 = QUIZ.questions;
        QUIZ.questions = __s2.filter(q => !(q.paper && q.paper.year === 2020));
        state.qpaperId = "upsc-2020-gs1"; state.qset = null;
        state.qsheet = true; state.qallsets = false; renderQuiz();
        const shown = [...document.querySelectorAll("[data-set]")].map(b => b.textContent.trim());
        const link = !!document.getElementById("allsets");
        state.qpaperId = null; state.qsheet = false; render();
        QUIZ.questions = __s2;
        return JSON.stringify({ shown, link });
      })()`));
    assert.deepEqual(out.shown, ["Set A", "Set B", "Set C", "Set D"],
      "with no questions typed, every Series is equally worth marking a sheet against");
    assert.equal(out.link, false, "and there is nothing to reveal");
  });
});


/* Sitting a paper like the exam: two hours of wall clock, a submit that locks
   the answers and marks them on the Commission's scheme, and retakes that keep
   what each earlier attempt scored. */
describe("sitting a paper against the clock", () => {
  const OPEN = `const p = paperList().find(x => x.id === "upsc-2023-gs1"); p.set = "B"; p.letters = p.keys.B; const id = paperId(p);`;

  test("two hours, and the paper submits itself when they are up", () => {
    const out = JSON.parse(inPage(win, `(() => { ${OPEN}
      delete store.sit[id]; paperStartClock(p);
      const r = { mins: paperSit(p).mins, sub: paperSit(p).sub, left: Math.round(sitLeft(paperSit(p)) / 60000) };
      store.sit[id].start = Date.now() - 121 * 60000;
      r.after = paperSubmitted(p);
      r.at = store.sit[id].sub - store.sit[id].start;
      delete store.sit[id];
      return JSON.stringify(r); })()`));
    assert.equal(out.mins, 120);
    assert.equal(out.sub, null, "a running clock has not submitted anything");
    assert.equal(out.left, 120);
    assert.equal(out.after, true, "time up is submitted, whether or not the app was open");
    assert.equal(out.at, 120 * 60000, "and at the two-hour mark, not whenever it was noticed");
  });

  test("a submitted paper locks, shows right and wrong, and scores +2 / -0.66", () => {
    const out = JSON.parse(inPage(win, `(() => { ${OPEN}
      const right = LET.indexOf(p.letters[0]);
      store.attempts[id] = {1: right, 2: (LET.indexOf(p.letters[1]) + 1) % 4};
      delete store.sit[id]; paperSubmit(p);
      state.tab = "practice"; state.qmode = "papers"; state.qpaperId = "upsc-2023-gs1";
      state.qset = "B"; state.qsheet = false; state.qn = 1; render();
      const cls = n => document.querySelector('.pq[data-goq="' + n + '"]').className;
      const r = { locked: document.querySelectorAll(".qcard.run .opt[disabled]").length,
                  one: cls(1), two: cls(2), three: cls(3),
                  marks: document.querySelector(".score .big").textContent.trim() };
      document.querySelectorAll(".qcard.run .opt")[(right + 1) % 4].click();
      r.kept = store.attempts[id][1] === right;
      delete store.attempts[id]; delete store.sit[id]; delete store.seen[id]; state.qpaperId = null;
      return JSON.stringify(r); })()`));
    assert.equal(out.locked, 4, "every option is locked after the submit");
    assert.match(out.one, /\bok\b/, "a right answer is green");
    assert.match(out.two, /\bno\b/, "a wrong one is red");
    assert.match(out.three, /\bskip\b/, "one never answered says so");
    assert.equal(out.marks, "1.34", "one right and one wrong is 2 - 0.66");
    assert.equal(out.kept, true, "a tap on a submitted paper changes nothing");
  });

  test("a reattempt keeps the score; redoing mistakes keeps only the right answers", () => {
    const out = JSON.parse(inPage(win, `(() => { ${OPEN}
      delete store.past[id];
      const right = n => LET.indexOf(p.letters[n - 1]);
      store.attempts[id] = {1: right(1), 2: (right(2) + 1) % 4, 3: right(3)};
      paperSubmit(p); paperRetake(p, "mistakes");
      const r = { past: store.past[id].length, marks: store.past[id][0].marks,
                  kept: Object.keys(store.attempts[id]).sort().join(","),
                  clock: store.sit[id] === undefined };
      paperRetake(p, "all");
      r.pastAfter = store.past[id].length;
      r.sheetAfter = Object.keys(store.attempts[id]).length;
      delete store.past[id]; delete store.attempts[id]; delete store.seen[id];
      return JSON.stringify(r); })()`));
    assert.equal(out.past, 1, "the attempt it replaces is kept");
    assert.equal(out.marks, 3.34, "two right and one wrong");
    assert.equal(out.kept, "1,3", "only the right answers survive a redo of the mistakes");
    assert.equal(out.clock, true, "and the clock starts again from nothing");
    assert.equal(out.pastAfter, 2);
    assert.equal(out.sheetAfter, 0, "from scratch is from scratch");
  });
});

/* Focus measured by the day: a total that outlives the sixty-run log, a goal
   and its streak, and each day openable to the runs that made it. */
describe("focus, day by day", () => {
  test("a finished run is added to its day, and the day outlives the run log", () => {
    setStore(win, {});
    inPage(win, `focusStart(1); store.focusRun.start = Date.now() - 2 * 60000; focusEnd("done"); store.focus = [];`);
    const today = JSON.parse(inPage(win, "JSON.stringify(focusHistory().at(-1))"));
    assert.equal(today.mins, 2, "the run log is gone but the day still knows its minutes");
  });

  test("the goal streak counts the days that met it, and today does not break it early", () => {
    setStore(win, { focusGoal: 60 });
    const n = inPage(win, `(() => {
      const k = d => fdayKey(Date.now() - d * 86400000);
      store.focusDays = { [k(0)]: {mins: 10, runs: 1, voided: 0}, [k(1)]: {mins: 65, runs: 2, voided: 0},
                          [k(2)]: {mins: 70, runs: 2, voided: 0}, [k(3)]: {mins: 5, runs: 1, voided: 0} };
      const unfinished = focusGoalStreak();
      store.focusDays[k(0)].mins = 61;
      return JSON.stringify([unfinished, focusGoalStreak()]); })()`);
    assert.deepEqual(JSON.parse(n), [2, 3]);
  });

  test("tapping a day lists that day's runs", () => {
    setStore(win, { focus: [
      { on: Date.now() - 60000, mins: 25, ran: 1500, kind: "done" },
      { on: Date.now(),         mins: 40, ran: 300,  kind: "void" }] });
    const out = JSON.parse(inPage(win, `(() => {
      state.tab = "focus"; state.fday = null; render();
      document.querySelector('.fbar[data-fday="' + fdayKey(Date.now()) + '"]').click();
      return JSON.stringify({ runs: document.querySelectorAll(".frun").length,
                              walked: document.querySelectorAll(".frun.void").length }); })()`));
    assert.equal(out.runs, 2);
    assert.equal(out.walked, 1, "the one walked out of is shown as such");
  });
});

/* The progress backup in the shelf folder is what survives an uninstall, so
   both directions are pinned: a change is written out, and a backup found in
   a freshly picked folder comes back in. */
describe("the progress backup on the shelf", () => {
  test("changes reach the shelf folder, and a backup found there comes back", () => {
    let written = null;
    const kept = JSON.stringify({ done: { "t-kept": [0] }, backedUp: 1 });
    const w = loadApp({
      docsList: () => "[]", docsFolder: () => "Documents",
      docsBackupWrite: (s) => { written = s; return true; }, docsBackupRead: () => kept,
      focusAwake() {}, appVersion: () => "", savedPath: () => null,
    });
    w.confirm = () => true;
    const n = Number(inPage(w, "offerShelfRestore()"));
    assert.ok(n >= 1, "the backup is merged in");
    assert.deepEqual(JSON.parse(inPage(w, 'JSON.stringify(store.done["t-kept"])')), [0]);
    inPage(w, 'store.done["t-new"] = [2]; save(); shelfBackupNow();');
    assert.ok(written && JSON.parse(written).done["t-new"], "and a change is written back out");
    w.close();
  });
});

/* CSAT: the Commission's GS Paper II keys, sat on the answer grid against the
   same two-hour clock, marked +2.5 / -0.83 and qualifying at a third. */
describe("CSAT on the answer grid", () => {
  test("all ten years carry four Series of eighty, and 2021's C-or-D cell takes either", () => {
    const out = JSON.parse(inPage(win, `(() => {
      const yrs = KEYS.years.filter(y => y.year >= 2017 && y.year <= 2026).map(y =>
        Object.values(y.papers.find(p => p.code === "gs2").keys).map(v => v.length).join("/"));
      const p = paperList().find(x => x.id === "upsc-2021-gs2"); p.set = "A"; p.letters = p.keys.A;
      const id = paperId(p), n = p.letters.indexOf("CD") + 1;
      const at = a => { store.attempts[id] = {[n]: a}; return paperRightAt(p, n); };
      const r = { yrs, n, c: at("C"), d: at("D"), dIdx: at(3), a: at("A") };
      store.attempts[id] = {[n]: "D"}; r.score = paperScore(p).right;
      delete store.attempts[id];
      return JSON.stringify(r); })()`));
    assert.equal(out.yrs.length, 10);
    assert.ok(out.yrs.every(x => x === "80/80/80/80"), out.yrs.join(" "));
    assert.equal(out.n, 39, "the Commission accepted C or D at 39 in Series A");
    assert.equal(out.c, true);
    assert.equal(out.d, true, "either letter scores");
    assert.equal(out.dIdx, true, "whether the sheet holds a letter or an option number");
    assert.equal(out.a, false);
    assert.equal(out.score, 1);
  });

  test("the grid runs the two-hour clock, then locks and marks itself at +2.5 / -0.83", () => {
    const out = JSON.parse(inPage(win, `(() => {
      const id = "2024-gs2-A", L = KEYS.years.find(y => y.year === 2024).papers.find(p => p.code === "gs2").keys.A;
      delete store.attempts[id]; delete store.sit[id]; delete store.past[id];
      state.tab = "practice"; state.qmode = "papers"; state.qpaperId = "upsc-2024-gs2";
      // the sheet itself, not the question-by-question view its typed questions open on
      state.qset = "A"; state.qsheet = true; render();
      const r = { go: !!document.getElementById("pclockgo") };
      const wrongL = LET[(LET.indexOf(L[1]) + 1) % 4];
      document.querySelector('.omr [data-q="1"][data-a="' + L[0] + '"]').click();
      document.querySelector('.omr [data-q="2"][data-a="' + wrongL + '"]').click();
      const pp = paperList().find(x => x.id === "upsc-2024-gs2"); pp.set = "A"; pp.letters = L;
      paperStartClock(pp); render();
      r.clock = !!document.getElementById("pclock");
      r.unmarked = document.querySelectorAll(".omr .cell.ok, .omr .cell.no").length;
      store.sit[id].start = Date.now() - 121 * 60000; render();
      r.ok = document.querySelectorAll(".omr .cell.ok").length;
      r.no = document.querySelectorAll(".omr .cell.no").length;
      r.marks = document.querySelector(".score .big").textContent.trim();
      r.verdict = document.querySelector(".score .lil").textContent;
      r.retake = !!document.getElementById("pretake") && !!document.getElementById("pretry");
      document.querySelector('.omr [data-q="3"][data-a="A"]').click();
      r.locked = store.attempts[id][3] === undefined;
      document.getElementById("pretry").click();
      r.kept = Object.keys(store.attempts[id]).join(",");
      r.past = store.past[id].length;
      r.hist = !!document.querySelector(".phist");
      delete store.attempts[id]; delete store.sit[id]; delete store.past[id]; delete store.seen[id];
      state.qpaperId = null; state.qsheet = false;
      return JSON.stringify(r); })()`));
    assert.equal(out.go, true, "a CSAT paper offers the clock");
    assert.equal(out.clock, true);
    assert.equal(out.unmarked, 0, "nothing is marked while the clock runs");
    assert.equal(out.ok, 1, "after the submit the right answer is green");
    assert.equal(out.no, 1, "and the wrong one red");
    assert.equal(out.marks, "1.67", "one right and one wrong is 2.5 - 0.83");
    assert.match(out.verdict, /below the qualifying mark/);
    assert.equal(out.retake, true);
    assert.equal(out.locked, true, "a submitted sheet does not take new marks");
    assert.equal(out.kept, "1", "redoing the mistakes keeps only the right answer");
    assert.equal(out.past, 1, "and the attempt it replaced is kept");
    assert.equal(out.hist, true);
  });
});

/* The mistakes notebook: every question got wrong on a submitted paper, kept
   across all papers, grouped by topic, and asked again on a widening schedule. */
describe("the mistakes notebook", () => {
  test("a submit keeps every wrong answer, and nothing is kept before it", () => {
    const out = JSON.parse(inPage(win, `(() => {
      store.mistakes = {};
      const p = paperList().find(x => x.kind === "typed" && x.questions.length >= 3);
      const id = paperId(p), q = p.questions;
      store.attempts[id] = {1: (q[0].answer + 1) % 4, 2: q[1].answer};
      delete store.sit[id];
      const before = Object.keys(store.mistakes).length;
      paperSubmit(p);
      const m = store.mistakes[q[0].id] || {};
      const r = { before, keys: Object.keys(store.mistakes), first: q[0].id,
                  due: Math.round((m.due - Date.now()) / 86400000), step: m.step, wrong: m.wrong };
      delete store.attempts[id]; delete store.sit[id];
      const u = paperList().find(x => x.id === "upsc-2023-gs1"); u.set = "B"; u.letters = u.keys.B;
      const uid = paperId(u), uq = paperAsked(u).get(1);
      store.attempts[uid] = {1: (uq.answer + 1) % 4};
      delete store.sit[uid]; paperSubmit(u);
      r.upsc = !!store.mistakes[uq.id];
      delete store.attempts[uid]; delete store.sit[uid]; store.mistakes = {};
      return JSON.stringify(r); })()`));
    assert.equal(out.before, 0, "an answer on a paper still being sat is not a mistake yet");
    assert.deepEqual(out.keys, [out.first], "the wrong one is kept, the right one is not");
    assert.equal(out.due, 1, "and it comes back tomorrow");
    assert.equal(out.step, 0);
    assert.equal(out.wrong, 1);
    assert.equal(out.upsc, true, "a UPSC paper's typed questions are kept the same way");
  });

  test("right answers widen the gap 1, 3, 7, 21, 60 and then clear it; a wrong one starts over", () => {
    const out = JSON.parse(inPage(win, `(() => {
      store.mistakes = {}; const t0 = Date.now(), d = x => Math.round((x - t0) / 86400000);
      mistakeNote("zz", true, t0); const untouched = !store.mistakes.zz;
      mistakeNote("zz", false, t0); const gaps = [d(store.mistakes.zz.due)];
      for(let i = 0; i < 4; i++){ mistakeNote("zz", true, t0); gaps.push(d(store.mistakes.zz.due)); }
      mistakeNote("zz", false, t0); const reset = d(store.mistakes.zz.due);
      for(let i = 0; i < 5; i++) mistakeNote("zz", true, t0);
      const m = store.mistakes.zz; store.mistakes = {};
      return JSON.stringify({untouched, gaps, reset, done: !!m.done, due: m.due, wrong: m.wrong, right: m.right}); })()`));
    assert.equal(out.untouched, true, "right first time is not a mistake");
    assert.deepEqual(out.gaps, [1, 3, 7, 21, 60]);
    assert.equal(out.reset, 1, "wrong again is tomorrow again");
    assert.equal(out.done, true, "right at the last interval clears it");
    assert.equal(out.due, null);
    assert.equal(out.wrong, 2);
    assert.equal(out.right, 9);
  });

  test("due mistakes go on the plan, and the notebook asks them one at a time", () => {
    const out = JSON.parse(inPage(win, `(() => {
      const q = QUIZ.questions.find(x => x.source), q2 = QUIZ.questions.find(x => x.paper);
      store.mistakes = {
        [q.id]: {on: Date.now() - 3 * 86400000, step: 0, wrong: 1, right: 0, due: Date.now() - 1000},
        [q2.id]: {on: Date.now(), step: 0, wrong: 1, right: 0, due: Date.now() + 86400000}};
      const r = { plan: planItems().filter(i => i.kind === "mistakes").map(i => i.title) };
      const box = document.createElement("div"); box.innerHTML = planHtml(); document.body.appendChild(box);
      bindPlan(box); box.querySelector('[data-plan="mistakes"]').click(); box.remove();
      r.mode = state.qmode;
      r.badge = (document.querySelector(".modes .mbadge") || {}).textContent;
      r.rows = document.querySelectorAll(".mrow").length;
      r.squares = document.querySelectorAll(".mrow .mt").length;
      r.upscLabel = [...document.querySelectorAll(".mrow .ms")].some(e => /^UPSC \\d{4}/.test(e.textContent));
      document.getElementById("mgo").click();
      r.asked = document.querySelector(".qcard.run .qstem").textContent === q.q;
      document.querySelector('[data-mpick="' + q.answer + '"]').click();
      r.step = store.mistakes[q.id].step;
      r.note = document.querySelector(".qcard.run .note").textContent;
      document.getElementById("mnext").click();
      r.after = !!document.getElementById("mgo") || !!document.querySelector(".modes .mbadge");
      document.querySelector('[data-mclear="' + q2.id + '"]').click();
      r.cleared = !!store.mistakes[q2.id].done;
      r.left = document.querySelectorAll(".mrow").length;
      store.mistakes = {}; state.qmode = "daily";
      return JSON.stringify(r); })()`));
    assert.deepEqual(out.plan, ["1 mistake to try again"], "only the one due today is on the plan");
    assert.equal(out.mode, "mistakes", "and it opens the notebook");
    assert.equal(out.badge, "1");
    assert.equal(out.rows, 2, "the notebook holds every open mistake, due or not");
    assert.equal(out.squares, 0, "and none of its text wears the map square's class");
    assert.equal(out.upscLabel, true, "a UPSC question says which paper it came from");
    assert.equal(out.asked, true);
    assert.equal(out.step, 1, "a right answer moves it on");
    assert.match(out.note, /3 days/);
    assert.equal(out.after, false, "nothing is due once it has been answered");
    assert.equal(out.cleared, true, "I know it now clears a mistake");
    assert.equal(out.left, 1);
  });
});

/* `.mt` is the syllabus map's 16px square. Two other places used that class
   name for a line of text, and the text was drawn inside a 16px box, spilling
   over the name above it. Class names are global; these two must not collide. */
describe("the toppers list", () => {
  test("a row's meta line does not borrow the map square's class", () => {
    const out = JSON.parse(inPage(win, `(() => {
      state.tab = "toppers"; renderToppers();
      const r = { rows: document.querySelectorAll(".tcard").length,
                  meta: document.querySelectorAll(".tcard .tmeta").length,
                  squares: document.querySelectorAll(".tcard .mt").length };
      state.tab = "syllabus"; render();
      return JSON.stringify(r); })()`));
    assert.ok(out.rows > 0, "the toppers tab draws rows");
    assert.equal(out.meta, out.rows, "every row carries its own meta class");
    assert.equal(out.squares, 0, "and none of them is styled as a map square");
  });
});
