import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement, useState } from "react";
import { JSDOM } from "jsdom";
import { Modal } from "../src/ui.tsx";

test("dialog typing preserves focus and Escape uses the latest close handler", async (t) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/",
  });
  const before = {
    window: globalThis.window,
    document: globalThis.document,
    act: globalThis.IS_REACT_ACT_ENVIRONMENT,
  };
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const { createRoot } = await import("react-dom/client");
  const element = document.createElement("div");
  document.body.append(element);
  document.body.style.overflow = "auto";
  const root = createRoot(element);
  t.after(async () => {
    await act(async () => root.unmount());
    element.remove();
    globalThis.window = before.window;
    globalThis.document = before.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = before.act;
    dom.window.close();
  });
  function Harness() {
    const [open, setOpen] = useState(false);
    const [value, setValue] = useState("");
    const [closedWith, setClosedWith] = useState("");
    return createElement(
      "div",
      null,
      createElement("button", { onClick: () => setOpen(true) }, "Open"),
      createElement("output", null, closedWith),
      open &&
        createElement(
          Modal,
          {
            title: "Edit year",
            onClose: () => {
              setClosedWith(value);
              setOpen(false);
            },
          },
          createElement("input", {
            "aria-label": "Name",
            value,
            onChange: (e) => setValue(e.target.value),
          }),
          createElement("button", null, "Last action"),
        ),
    );
  }
  await act(async () => root.render(createElement(Harness)));
  const trigger = element.querySelector("button");
  trigger.focus();
  await act(async () => trigger.click());
  const dialog = document.querySelector("[role='dialog']");
  const input = dialog.querySelector("input");
  input.focus();
  for (const character of "2026-2027") {
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLInputElement.prototype,
        "value",
      ).set.call(input, input.value + character);
      input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    assert.equal(document.activeElement === input, true);
  }
  await act(async () =>
    document.dispatchEvent(
      new dom.window.KeyboardEvent("keydown", { key: "Escape" }),
    ),
  );
  assert.equal(document.querySelector("[role='dialog']"), null);
  assert.equal(
    element.querySelector("output").textContent,
    "2026-2027",
    "Escape uses the handler from the latest render",
  );
  assert.equal(document.body.style.overflow, "auto");
  assert.equal(document.activeElement === trigger, true);
});
