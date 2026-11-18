import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Badge } from "../src/ui.tsx";

test("badges distinguish successful states from neutral labels and other statuses", () => {
  for (const value of [
    "present",
    "submitted",
    "approved",
    "active",
    "completed",
  ])
    assert.match(
      renderToStaticMarkup(createElement(Badge, { value })),
      /class="badge success"/,
    );
  for (const value of ["not_started", "lead", "assistant", "closed"])
    assert.match(
      renderToStaticMarkup(createElement(Badge, { value })),
      /class="badge "/,
    );
  for (const value of ["pending", "draft", "late"])
    assert.match(
      renderToStaticMarkup(createElement(Badge, { value })),
      /class="badge amber"/,
    );
  for (const value of ["absent", "failed", "rejected"])
    assert.match(
      renderToStaticMarkup(createElement(Badge, { value })),
      /class="badge red"/,
    );
});
