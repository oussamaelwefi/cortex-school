import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SourceExcerpt, StudyResult } from "../src/tutor-results.tsx";

const source = {
  id: "source-1", page: 4,
  excerpt: String.raw`# أوظف الجمع والطرح

| اسم الموظف | العدد |
| --- | --- |
| نادر | 18,5 |

أنجز العمليات التالية:

$$
\begin{array}{rcr}
99{,}98 &amp; - &amp; 100{,}1 \\
0{,}63 &amp;amp; + &amp;amp; 8
\end{array}
$$

- أحسب $\frac{6}{2}$.
- أفسّر النتيجة.`,
};
const render = (component, props) => renderToStaticMarkup(createElement(component, props));
const callbacks = { onOpenPage() {}, onRetry() {} };

test("OCR excerpts render Arabic, tables, lists and escaped LaTeX arrays", () => {
  const html = render(SourceExcerpt, { source });
  assert.match(html, /<h1>أوظف الجمع والطرح<\/h1>/);
  assert.match(html, /<table dir="ltr">/);
  assert.match(html, /<th dir="auto">اسم الموظف<\/th>/);
  assert.match(html, /class="katex-display"/);
  assert.match(html, /<mtable/);
  assert.match(html, /<mfrac>/);
  assert.match(html, /<ul>/);
  assert.doesNotMatch(html, /katex-error|&amp;amp;|\$\$/);
});

test("untrusted OCR cannot inject HTML or load external illustrations", () => {
  const html = render(SourceExcerpt, { source: { ...source, excerpt: String.raw`
&lt;script&gt;alert(1)&lt;/script&gt;

<img src="https://example.invalid/tracker" onerror="alert(1)">

![missing diagram](https://example.invalid/diagram)

$\href{javascript:alert(1)}{click}$
` } });
  assert.doesNotMatch(html, /<script|<img|href="javascript:|onerror=/);
});

test("failed quizzes keep their label, offer retry and collapse source passages", () => {
  const html = render(StudyResult, { ...callbacks, activity: {
    action: "quiz", status: "generation_unavailable", text: "", questions: [], source_ids: [], sources: [source],
  } });
  assert.match(html, /<h2 dir="auto">Quiz<\/h2>/);
  assert.match(html, /Please try again/);
  assert.match(html, />Try again<\/button>/);
  assert.match(html, /<details class="tutor-fallback-sources"><summary>Read matching book passages/);
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/);
});

test("ready quizzes show answer choices and isolate Arabic arithmetic", () => {
  const html = render(StudyResult, { ...callbacks, activity: {
    action: "quiz", status: "ready", text: "", source_ids: [], sources: [source],
    questions: [{ prompt: "احسب 18,5 + 19,75.", options: ["38,25", "37", "39", "40"], answer: "38,25", explanation: "نجمع العددين.", source_ids: [source.id] }],
  } });
  assert.equal((html.match(/type="radio"/g) ?? []).length, 4);
  assert.match(html, /<bdi dir="ltr" class="tutor-inline-math">18,5 \+ 19,75<\/bdi>/);
  assert.match(html, /Check answer/);
  assert.doesNotMatch(html, /Read matching book passages/);
});
