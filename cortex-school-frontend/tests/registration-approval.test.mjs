import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement, useState } from "react";
import { JSDOM } from "jsdom";
import { ApiContext, findEndpoint } from "../src/api.tsx";
import { ChoicesContext, Operation } from "../src/ui.tsx";
import { Field } from "../src/forms.tsx";
import { initialValue, cleanPayload } from "../src/lib.mjs";

test("registration approval choices", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/registrations",
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
  suite.after(() => {
    globalThis.window = before.window;
    globalThis.document = before.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = before.act;
    dom.window.close();
  });
  const choices = {
    student_id: [{ value: "student-yasmine", label: "Yasmine Ben Ali" }],
  };
  async function mount(t) {
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    const api = t.mock.fn(async () => ({ status: "approved" }));
    const done = t.mock.fn();
    await act(async () =>
      root.render(
        createElement(
          ApiContext.Provider,
          { value: api },
          createElement(
            ChoicesContext.Provider,
            { value: choices },
            createElement(Operation, {
              endpoint: findEndpoint(
                "POST",
                "/registration-requests/{request_id}/approve/",
              ),
              context: { request_id: "request-yasmine" },
              recordName: "Yasmine Ben Ali",
              submitLabel: "Approve",
              onClose: () => {},
              onDone: done,
            }),
          ),
        ),
      ),
    );
    t.after(async () => {
      await act(async () => root.unmount());
      element.remove();
    });
    return { dialog: document.querySelector("[role='dialog']"), api, done };
  }
  async function change(select, value) {
    await act(async () => {
      select.value = value;
      select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
  }
  async function submit(dialog) {
    await act(async () =>
      dialog
        .querySelector("form")
        .dispatchEvent(
          new dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
  }

  await suite.test(
    "shows one resolution choice and approves a new child without an unnecessary student selection",
    async (t) => {
      const { dialog, api, done } = await mount(t);
      assert.equal(
        dialog.querySelectorAll("select").length,
        2,
        "one resolution choice and one existing-student selector",
      );
      assert.doesNotMatch(dialog.textContent, /Resolution/);
      await change(dialog.querySelector('[aria-label="Approval type"]'), "1");
      assert.equal(dialog.querySelectorAll("select").length, 1);
      assert.equal(
        dialog.querySelectorAll("fieldset").length,
        1,
        "the approval group is not repeated",
      );
      assert.doesNotMatch(dialog.textContent, /Student Id|Resolution/);
      await submit(dialog);
      assert.equal(api.mock.callCount(), 1);
      assert.deepEqual(api.mock.calls[0].arguments[1], {
        request_id: "request-yasmine",
      });
      assert.deepEqual(api.mock.calls[0].arguments[2], {
        resolution: "create",
      });
      assert.equal(done.mock.callCount(), 1);
    },
  );

  await suite.test(
    "reuses a named existing record and preserves its identifier in the approval payload",
    async (t) => {
      const { dialog, api } = await mount(t);
      const student = [...dialog.querySelectorAll("select")].find((node) =>
        [...node.options].some((option) => option.value === "student-yasmine"),
      );
      assert.ok(student);
      await change(student, "student-yasmine");
      await submit(dialog);
      assert.deepEqual(api.mock.calls[0].arguments[2], {
        resolution: "existing",
        student_id: "student-yasmine",
      });
    },
  );

  await suite.test(
    "switching to a new record removes the previous student selection",
    async (t) => {
      const { dialog, api } = await mount(t);
      await change(dialog.querySelectorAll("select")[1], "student-yasmine");
      await change(dialog.querySelector('[aria-label="Approval type"]'), "1");
      await submit(dialog);
      assert.deepEqual(api.mock.calls[0].arguments[2], {
        resolution: "create",
      });
    },
  );

  await suite.test(
    "publication audience choices also keep their discriminator without displaying it twice",
    async (t) => {
      const schema = findEndpoint("POST", "/ai/teacher-update-draft/").body
        .properties.target;
      const element = document.createElement("div");
      document.body.append(element);
      const root = createRoot(element);
      let value;
      function Audience() {
        const [state, setState] = useState(initialValue(schema));
        value = state;
        return createElement(Field, {
          name: "Target",
          schema,
          value: state,
          onChange: setState,
          choices,
        });
      }
      t.after(async () => {
        await act(async () => root.unmount());
        element.remove();
      });
      await act(async () => root.render(createElement(Audience)));
      assert.equal(element.querySelectorAll("select").length, 1);
      assert.deepEqual(cleanPayload(value, schema), { type: "classroom" });
      await change(element.querySelector("select"), "1");
      assert.deepEqual(cleanPayload(value, schema), {
        type: "students",
        student_ids: [],
      });
      assert.equal(element.querySelectorAll("select").length, 1);
    },
  );
});
