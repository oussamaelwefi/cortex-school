import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { getChatContent } from "../src/chat-content.mjs";

test("guardians receive home-learning and teacher-contact suggestions", () => {
  const content = getChatContent("guardian");
  assert.match(content.suggestions[0], /my child’s teacher/);
  assert.match(content.suggestions[1], /at home/);
  assert.match(content.suggestions[2], /my child/);
  assert.ok(
    content.suggestions.every(
      (s) => !s.includes("classroom") && !s.includes("to a parent"),
    ),
  );
  assert.match(content.context, /parent or guardian/);
});

test("teacher and administrator suggestions are distinct from guardian suggestions", () => {
  assert.match(getChatContent("teacher").suggestions[0], /to a parent/);
  assert.match(getChatContent("admin").suggestions[0], /announcement/);
  assert.notDeepEqual(
    getChatContent("teacher").suggestions,
    getChatContent("guardian").suggestions,
  );
  assert.equal(getChatContent("unknown"), getChatContent("guardian"));
});

test("each role has French translations for welcome, subtitle and suggestions", () => {
  const fr = JSON.parse(
    readFileSync(new URL("../src/fr.json", import.meta.url), "utf8"),
  );
  for (const role of ["guardian", "teacher", "admin"]) {
    const content = getChatContent(role);
    for (const text of [
      content.welcome,
      content.subtitle,
      ...content.suggestions,
    ]) {
      assert.ok(fr[text], `${role}: ${text}`);
    }
  }
});
