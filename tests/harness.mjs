/* Loads the SHIPPED page, not the template.
 *
 * web/taracmd.html is what build.py writes and what a phone actually opens, so
 * that is what gets tested. A test against templates/index.html would pass
 * happily while the thing people install was broken.
 *
 * The app's state lives in `let store`, declared at the top level of a classic
 * <script>. That is a global *lexical* binding, so it is not a property of
 * window and cannot be reached as win.store — win.eval() runs inside the page's
 * own scope and can. Functions declared with `function` are on window as usual.
 */
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

export function loadApp(bridge) {
  const html = readFileSync(new URL("../web/taracmd.html", import.meta.url), "utf8");
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "https://taracmd.test/",
    pretendToBeVisual: true,
    /* The page reads AndroidHost once, at parse time, because in the real
       WebView addJavascriptInterface runs before loadUrl. So a fake bridge has
       to be in place before the scripts run, not after. */
    beforeParse: bridge ? (w) => { w.AndroidHost = bridge; } : undefined,
  });
  return dom.window;
}

/** Evaluate an expression in the page's own scope. */
export const inPage = (win, expr) => win.eval(expr);

/** Replace the app's store wholesale, then return what the page sees. */
export function setStore(win, patch) {
  win.eval(`store = Object.assign({}, BLANK, ${JSON.stringify(patch)});`);
}
