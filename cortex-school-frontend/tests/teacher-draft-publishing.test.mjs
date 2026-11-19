import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement as h } from "react";
import { JSDOM } from "jsdom";
import { ApiContext, findEndpoint } from "../src/api.tsx";
import { CurrentUserContext } from "../src/current-user.ts";
import { ChoicesContext, Operation } from "../src/ui.tsx";
import { withTeacherSignature } from "../src/teacher-draft-review.tsx";

const classroom = "00000000-0000-4000-8000-000000000001";
const target = {
  type: "students",
  student_ids: ["00000000-0000-4000-8000-000000000002"],
};
const draft = {
  outcome: "draft",
  title: "Bienvenue",
  body: "Chers parents,\n\nBienvenue en classe.\n\n[Nom de l'enseignant(e)]",
  questions: [],
};

test("teacher signatures replace placeholders and do not duplicate existing names", () => {
  assert.equal(
    withTeacherSignature(draft.body, "Amira Ben Ali"),
    "Chers parents,\n\nBienvenue en classe.\n\nAmira Ben Ali",
  );
  assert.equal(
    withTeacherSignature("Hello\n[Teacher's name]", "Amira $Ali"),
    "Hello\nAmira $Ali",
  );
  assert.equal(
    withTeacherSignature("مرحبا\n[اسم المعلمة]", "أميرة"),
    "مرحبا\nأميرة",
  );
  assert.equal(
    withTeacherSignature("Bonjour\n\nAmira Ben Ali", "Amira Ben Ali"),
    "Bonjour\n\nAmira Ben Ali",
  );
  assert.equal(
    withTeacherSignature("Bonjour", "Amira Ben Ali"),
    "Bonjour\n\nAmira Ben Ali",
  );
  assert.equal(withTeacherSignature("Bonjour\n[Votre nom]", ""), "Bonjour");
});

async function mount(
  t,
  { displayName = "Amira Ben Ali", generated = draft, publish, preview } = {},
) {
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
  const onDone = t.mock.fn(),
    onClose = t.mock.fn();
  const api = t.mock.fn(async (endpoint, params, body) => {
    if (endpoint.method === "GET") return [];
    if (endpoint.path === "/ai/teacher-update-draft/")
      return typeof generated === "function" ? generated() : generated;
    if (endpoint.path === "/teacher/updates/preview/")
      return preview
        ? preview(body)
        : {
            classroom_id: classroom,
            target_type: target.type,
            student_names: ["Yasmine Trabelsi"],
            student_count: 1,
            unique_guardian_count: 2,
          };
    if (endpoint.path === "/teacher/updates/")
      return publish ? publish(body) : { id: "update-1" };
    throw Error("Unexpected endpoint");
  });
  await act(async () =>
    root.render(
      h(
        ApiContext.Provider,
        { value: api },
        h(
          CurrentUserContext.Provider,
          { value: { displayName } },
          h(
            ChoicesContext.Provider,
            {
              value: {
                classroom_id: [
                  { value: classroom, label: "6e A" },
                  {
                    value: "00000000-0000-4000-8000-000000000003",
                    label: "6e B",
                  },
                ],
              },
            },
            h(Operation, {
              endpoint: findEndpoint("POST", "/ai/teacher-update-draft/"),
              seed: {
                classroom_id: classroom,
                target,
                observations: "Bienvenue dans la classe.",
              },
              onDone,
              onClose,
            }),
          ),
        ),
      ),
    ),
  );
  const submit = () =>
    document
      .querySelector('[role="dialog"] form')
      .dispatchEvent(
        new window.Event("submit", { bubbles: true, cancelable: true }),
      );
  const button = (text) =>
    [...document.querySelectorAll("button")].find(
      (element) => element.textContent.trim() === text,
    );
  const calls = (path) =>
    api.mock.calls.filter((call) => call.arguments[0].path === path);
  await act(async () => submit());
  return { api, onDone, onClose, submit, button, calls };
}

async function fill(element, value) {
  const prototype =
    element.tagName === "TEXTAREA"
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(
      element,
      value,
    );
    element.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}

test("an AI draft requires recipient review and explicit confirmation before publication", async (t) => {
  let finishPublication;
  const state = await mount(t, {
    publish: () =>
      new Promise((resolve) => {
        finishPublication = resolve;
      }),
  });
  assert.match(
    document.querySelector("h2").textContent,
    /Review your AI draft/,
  );
  const message = document.querySelector("textarea");
  assert.match(message.value, /Amira Ben Ali$/);
  assert.doesNotMatch(message.value, /Nom de l/);
  assert.equal(state.calls("/teacher/updates/").length, 0);
  await fill(
    document.querySelector('input[maxlength="255"]'),
    "Bienvenue en 6e A",
  );
  await fill(
    message,
    "Chers parents,\nBienvenue dans notre classe.\n\nAmira Ben Ali",
  );
  await act(async () => state.button("Review recipients").click());
  assert.equal(state.calls("/teacher/updates/").length, 0);
  assert.deepEqual(state.calls("/teacher/updates/preview/")[0].arguments[2], {
    classroom_id: classroom,
    target,
  });
  assert.match(document.body.textContent, /Do you want to publish/);
  assert.match(
    document.querySelector(".tdr-preview").textContent,
    /Bienvenue en 6e A/,
  );
  assert.match(
    document.querySelector(".tdr-preview").textContent,
    /Bienvenue dans notre classe/,
  );
  assert.match(
    document.querySelector(".tdr-audience").textContent,
    /Yasmine Trabelsi/,
  );
  await act(async () => state.button("Back to draft").click());
  assert.equal(
    document.querySelector("textarea").value,
    "Chers parents,\nBienvenue dans notre classe.\n\nAmira Ben Ali",
  );
  assert.equal(state.calls("/teacher/updates/").length, 0);
  await act(async () => state.button("Review recipients").click());
  await act(async () => {
    state.submit();
    state.submit();
  });
  assert.equal(state.calls("/teacher/updates/").length, 1);
  assert.deepEqual(state.calls("/teacher/updates/")[0].arguments[2], {
    classroom_id: classroom,
    target,
    title: "Bienvenue en 6e A",
    body: "Chers parents,\nBienvenue dans notre classe.\n\nAmira Ben Ali",
  });
  assert.equal(state.onClose.mock.calls.length, 0);
  await act(async () => finishPublication({ id: "update-1" }));
  assert.equal(state.onClose.mock.calls.length, 1);
  assert.equal(state.onDone.mock.calls.length, 1);
});

test("publication failure keeps the reviewed text and allows an explicit retry", async (t) => {
  let attempts = 0;
  const state = await mount(t, {
    publish: async () => {
      if (++attempts === 1) throw Error("Publication unavailable");
      return { id: "update-1" };
    },
  });
  await act(async () => state.submit());
  await act(async () => state.submit());
  assert.match(
    document.querySelector('[role="alert"]').textContent,
    /Publication unavailable/,
  );
  assert.match(
    document.querySelector(".tdr-preview").textContent,
    /Amira Ben Ali/,
  );
  assert.equal(state.onClose.mock.calls.length, 0);
  assert.equal(state.calls("/teacher/updates/").length, 1);
  await act(async () => state.submit());
  assert.equal(state.calls("/teacher/updates/").length, 2);
  assert.equal(state.onDone.mock.calls.length, 1);
});

test("clarification returns to the original observations without allowing publication", async (t) => {
  const state = await mount(t, {
    generated: {
      outcome: "needs_more_information",
      title: null,
      body: null,
      questions: ["Quelle activité ?"],
    },
  });
  assert.match(document.body.textContent, /Quelle activité/);
  assert.equal(state.button("Review recipients"), undefined);
  assert.equal(state.button("Confirm publication"), undefined);
  await act(async () => state.button("Edit observations").click());
  assert.equal(
    document.querySelector('input[maxlength="3000"],textarea[maxlength="3000"]')
      .value,
    "Bienvenue dans la classe.",
  );
  assert.equal(state.calls("/teacher/updates/").length, 0);
});

test("a missing profile name requires a signature before reviewing publication", async (t) => {
  const state = await mount(t, { displayName: "" });
  await act(async () => state.submit());
  assert.match(
    document.querySelector('[role="alert"]').textContent,
    /Enter your name/,
  );
  assert.equal(state.calls("/teacher/updates/preview/").length, 0);
  await fill(document.querySelector('input[maxlength="150"]'), "Amira Ben Ali");
  await act(async () => state.submit());
  assert.match(
    document.querySelector(".tdr-preview").textContent,
    /Amira Ben Ali/,
  );
  assert.equal(state.calls("/teacher/updates/").length, 0);
});

test("publication keeps the audience used for generation if the form changes while waiting", async (t) => {
  let finishGeneration;
  const state = await mount(t, {
    generated: () =>
      new Promise((resolve) => {
        finishGeneration = resolve;
      }),
  });
  const select = document.querySelector("select");
  await act(async () => {
    select.value = "00000000-0000-4000-8000-000000000003";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
  assert.equal(select.value, "00000000-0000-4000-8000-000000000003");
  await act(async () => finishGeneration(draft));
  assert.match(
    document.querySelector('[role="dialog"] header').textContent,
    /6e A/,
  );
  await act(async () => state.submit());
  assert.deepEqual(state.calls("/teacher/updates/preview/")[0].arguments[2], {
    classroom_id: classroom,
    target,
  });
  assert.equal(state.calls("/teacher/updates/").length, 0);
});
