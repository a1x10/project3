import { describe, expect, it } from "vitest";
import { applyEdits, parseEdits, protectUserCode, expandCode, compactHtml } from "../src/siteEdit.js";

const site = "<html><body>\n<h1>Old title</h1>\n<p>Text</p>\n</body></html>";

describe("site edit engine", () => {
  it("parses and applies SEARCH/REPLACE and INSERT blocks", () => {
    const answer = "Меняю.\n<<<<<<< SEARCH\n<h1>Old title</h1>\n=======\n<h1>New title</h1>\n>>>>>>> REPLACE\n<<<<<<< INSERT_AFTER\n<p>Text</p>\n=======\n<button>Заказать</button>\n>>>>>>> END\nГотово.";
    const { blocks, segs, open } = parseEdits(answer);
    expect(blocks).toHaveLength(2);
    expect(open).toBe(false);
    expect(segs.filter((s) => s.type === "text")).toHaveLength(2);
    const { doc, results } = applyEdits(site, blocks);
    expect(results.every((r) => r.ok)).toBe(true);
    expect(doc).toContain("<h1>New title</h1>");
    expect(doc).toContain("<p>Text</p>\n<button>Заказать</button>");
  });
  it("matches ignoring whitespace and reports misses", () => {
    const { blocks } = parseEdits("<<<<<<< SEARCH\n<h1>Old   title</h1>\n=======\n<h1>X</h1>\n>>>>>>> REPLACE\n<<<<<<< SEARCH\n<nav>missing</nav>\n=======\n\n>>>>>>> REPLACE");
    const { doc, results } = applyEdits(site, blocks);
    expect(results[0]).toMatchObject({ ok: true, how: "fuzzy" });
    expect(results[1].ok).toBe(false);
    expect(doc).toContain("<h1>X</h1>");
  });
  it("detects a truncated last block", () => {
    expect(parseEdits("<<<<<<< SEARCH\n<h1>Old title</h1>\n=====").open).toBe(true);
  });
  it("protects long user code and restores it byte for byte", () => {
    const code = "x".repeat(700);
    const { text, codes } = protectUserCode("вставь\n```js\n" + code + "\n```");
    expect(text).toContain("[[CODE_1]]");
    expect(expandCode("A [[CODE_1]] B", codes)).toBe(`A ${code} B`);
    expect(compactHtml("<!-- c -->\n  <a>\n\n  </a>")).toBe("<a>\n</a>");
  });
});
