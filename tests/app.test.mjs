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
