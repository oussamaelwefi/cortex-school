import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement as h } from "react";
import { JSDOM } from "jsdom";
import { ApiContext, findEndpoint } from "../src/api.tsx";
import { ChoicesContext, Operation } from "../src/ui.tsx";

test("teacher draft generation keeps observations after a timeout and supports retry", async (t) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/draft",
  });
  const previous = {
    window: globalThis.window,
    document: globalThis.document,
    act: globalThis.IS_REACT_ACT_ENVIRONMENT,
  };
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const { createRoot } = await import("react-dom/client");
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  t.after(async () => {
    await act(async () => root.unmount());
    dom.window.close();
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = previous.act;
  });
  let fail, finish;
  const api = t.mock.fn((endpoint) =>
    endpoint.method === "GET"
      ? Promise.resolve([])
      : new Promise((resolve, reject) => {
          finish = resolve;
          fail = reject;
        }),
  );
  const endpoint = findEndpoint("POST", "/ai/teacher-update-draft/");
  const classroom = "00000000-0000-4000-8000-000000000001";
  await act(async () =>
    root.render(
      h(
        ApiContext.Provider,
        { value: api },
        h(
          ChoicesContext.Provider,
          { value: { classroom_id: [{ value: classroom, label: "6e A" }] } },
          h(Operation, {
            endpoint,
            seed: {
              classroom_id: classroom,
              observations: "Les élèves ont terminé un atelier de lecture.",
            },
            onClose: () => {},
            onDone: () => {},
          }),
        ),
      ),
    ),
  );
  const dialog = document.querySelector("[role=dialog]");
  const observations = dialog.querySelector(
    'input[maxlength="3000"],textarea[maxlength="3000"]',
  );
  const submit = () =>
    dialog
      .querySelector("form")
      .dispatchEvent(
        new window.Event("submit", { bubbles: true, cancelable: true }),
      );
  await act(async () => submit());
  assert.match(
    dialog.querySelector("[role=status]").textContent,
    /Generating the draft/,
  );
  await act(async () =>
    fail(
      Error(
        "AI generation took too long. Your text has been kept. Please try again.",
      ),
    ),
  );
  assert.equal(
    observations.value,
    "Les élèves ont terminé un atelier de lecture.",
  );
  assert.match(
    dialog.querySelector("[role=alert]").textContent,
    /text has been kept/,
  );
  await act(async () => submit());
  const generations = api.mock.calls.filter(
    (call) => call.arguments[0].method === "POST",
  );
  assert.equal(generations.length, 2);
  assert.equal(generations[1].arguments[2].observations, observations.value);
  await act(async () =>
    finish({
      outcome: "draft",
      title: "Un bel atelier",
      body: "Les élèves ont terminé leur activité de lecture.",
      questions: [],
    }),
  );
  assert.match(dialog.textContent, /Un bel atelier/);
  assert.match(dialog.textContent, /activité de lecture/);
  assert.equal(dialog.querySelector("[role=alert]"), null);
});
