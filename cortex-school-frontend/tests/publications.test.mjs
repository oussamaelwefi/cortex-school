import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement as h } from "react";
import { JSDOM } from "jsdom";
import { ApiContext } from "../src/api.tsx";
import { PublicationsPage } from "../src/publications.tsx";

const options = {
  classrooms: [
    { id: "00000000-0000-4000-8000-000000000001", name: "6e A" },
    { id: "00000000-0000-4000-8000-000000000002", name: "6e B" },
  ],
  guardians: [{ id: "user_GuardianA", name: "Sonia Ben Ali" }],
  teachers: [{ id: "user_TeacherA", name: "Amira Trabelsi" }],
  students: [
    { id: "00000000-0000-4000-8000-000000000003", name: "Yasmine Ben Ali" },
  ],
};
const received = {
  id: "publication-1",
  title: "Réunion des familles",
  body: "La réunion aura lieu à l’école.",
  created_at: "2026-11-19T09:00:00Z",
  read_at: null,
};

async function mount(t, role = "admin", overrides = {}) {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/publications",
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
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  t.after(async () => {
    await act(async () => root.unmount());
    dom.window.close();
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = previous.act;
  });
  const sent = [];
  let read = false;
  const api = t.mock.fn(async (endpoint, params = {}, body) => {
    const custom = await overrides.api?.(endpoint, params, body);
    if (custom !== undefined) return custom;
    if (endpoint.path === "/publications/audiences/") return options;
    if (endpoint.path === "/publications/preview/")
      return {
        audience_hash: "a".repeat(64),
        recipient_count: 2,
        guardian_count: 1,
        teacher_count: 1,
        recipients: [
          { id: "user_GuardianA", name: "Sonia Ben Ali", roles: ["guardian"] },
          { id: "user_TeacherA", name: "Amira Trabelsi", roles: ["teacher"] },
        ],
        students_without_guardians: [],
      };
    if (endpoint.path === "/publications/" && endpoint.method === "POST") {
      const item = {
        ...body,
        id: `sent-${sent.length}`,
        created_at: received.created_at,
        target_kind: body.target.kind,
        recipient_count: 2,
        read_count: 0,
      };
      sent.unshift(item);
      return item;
    }
    if (endpoint.path === "/publications/")
      return { items: sent, total_count: sent.length };
    if (endpoint.path === "/publications/inbox/")
      return {
        items: [{ ...received, read_at: read ? received.created_at : null }],
        total_count: 1,
        unread_count: read ? 0 : 1,
      };
    if (endpoint.path === "/publications/inbox/{publication_id}/read/") {
      read = true;
      return { ...received, read_at: received.created_at };
    }
    throw Error(`Unexpected endpoint: ${endpoint.path}`);
  });
  await act(async () =>
    root.render(
      h(ApiContext.Provider, { value: api }, h(PublicationsPage, { role })),
    ),
  );
  const button = (text, scope = document) =>
    [...scope.querySelectorAll("button")].find(
      (item) => item.textContent.trim() === text,
    );
  const calls = (method, path) =>
    api.mock.calls.filter(
      (call) =>
        call.arguments[0].method === method && call.arguments[0].path === path,
    );
  const dialog = () => document.querySelector('[role="dialog"]');
  const submit = () =>
    dialog()
      .querySelector("form")
      .dispatchEvent(
        new window.Event("submit", { bubbles: true, cancelable: true }),
      );
  return { api, button, calls, dialog, submit };
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

test("admin publication previews each target category and publishes only after confirmation", async (t) => {
  const state = await mount(t);
  for (const kind of ["classrooms", "guardians", "teachers", "students"]) {
    await act(async () => state.button("New publication").click());
    await act(async () =>
      state
        .dialog()
        .querySelector(`input[name="publication-kind"][value="${kind}"]`)
        .click(),
    );
    await act(async () =>
      state.dialog().querySelector(".pub-options input").click(),
    );
    await fill(
      state.dialog().querySelector('input[maxlength="255"]'),
      "Informations pour la rentrée",
    );
    const message = state.dialog().querySelector("textarea");
    message.focus();
    await fill(message, "Bienvenue dans notre établissement.");
    assert.equal(document.activeElement, message);
    const previous = state.calls("POST", "/publications/").length;
    await act(async () => state.submit());
    assert.equal(state.calls("POST", "/publications/").length, previous);
    assert.deepEqual(
      state.calls("POST", "/publications/preview/").at(-1).arguments[2],
      { target: { kind, ids: [options[kind][0].id] } },
    );
    assert.match(state.dialog().textContent, /Sonia Ben Ali/);
    assert.match(state.dialog().textContent, /Amira Trabelsi/);
    await act(async () =>
      state.button("Back to message", state.dialog()).click(),
    );
    assert.equal(
      state.dialog().querySelector("textarea").value,
      "Bienvenue dans notre établissement.",
    );
    assert.equal(
      state.dialog().querySelector(".pub-options input").checked,
      true,
    );
    await act(async () => state.submit());
    await act(async () => {
      state.submit();
      state.submit();
    });
    assert.equal(state.calls("POST", "/publications/").length, previous + 1);
    const payload = state.calls("POST", "/publications/").at(-1).arguments[2];
    assert.equal(payload.confirmed, true);
    assert.equal(payload.audience_hash, "a".repeat(64));
    assert.match(payload.idempotency_key, /^[a-f0-9-]{36}$/);
    assert.deepEqual(payload.target, { kind, ids: [options[kind][0].id] });
    assert.equal(state.dialog(), null);
  }
});

test("failed publication keeps the confirmation and reuses the same attempt key on retry", async (t) => {
  let attempts = 0;
  const state = await mount(t, "admin", {
    api: async (endpoint) => {
      if (
        endpoint.method === "POST" &&
        endpoint.path === "/publications/" &&
        ++attempts === 1
      )
        throw Error("Unable to publish");
    },
  });
  await act(async () => state.button("New publication").click());
  await act(async () =>
    state.dialog().querySelector(".pub-options input").click(),
  );
  await fill(
    state.dialog().querySelector('input[maxlength="255"]'),
    "Informations",
  );
  await fill(state.dialog().querySelector("textarea"), "Un message important.");
  await act(async () => state.submit());
  await act(async () => state.submit());
  assert.match(
    state.dialog().querySelector('[role="alert"]').textContent,
    /Unable to publish/,
  );
  assert.match(
    state.dialog().querySelector(".pub-message").textContent,
    /Un message important/,
  );
  await act(async () => state.submit());
  const requests = state.calls("POST", "/publications/");
  assert.equal(requests.length, 2);
  assert.deepEqual(requests[0].arguments[2], requests[1].arguments[2]);
});

test("an audience change returns to recipient review and preserves the message", async (t) => {
  const state = await mount(t, "admin", {
    api: async (endpoint) => {
      if (endpoint.method === "POST" && endpoint.path === "/publications/")
        throw Error(
          "The recipients have changed. Review them again before publishing. (Request test)",
        );
    },
  });
  await act(async () => state.button("New publication").click());
  await act(async () =>
    state.dialog().querySelector(".pub-options input").click(),
  );
  await fill(
    state.dialog().querySelector('input[maxlength="255"]'),
    "Informations",
  );
  await fill(state.dialog().querySelector("textarea"), "Mon message conservé.");
  await act(async () => state.submit());
  await act(async () => state.submit());
  assert.equal(
    state.dialog().querySelector("textarea").value,
    "Mon message conservé.",
  );
  assert.equal(state.button("Confirm publication", state.dialog()), undefined);
  assert.match(
    state.dialog().querySelector('[role="alert"]').textContent,
    /recipients have changed/,
  );
});

for (const role of ["teacher", "guardian"])
  test(`${role} inbox shows received publications and marks only that role's inbox as read`, async (t) => {
    const state = await mount(t, role);
    assert.equal(state.button("New publication"), undefined);
    assert.equal(
      state.calls("GET", "/publications/inbox/")[0].arguments[1].role,
      role,
    );
    assert.match(
      document.querySelector(".pub-card .pub-read-state").textContent,
      /Unread/,
    );
    await act(async () => state.button("Read publication").click());
    assert.equal(
      state.calls("POST", "/publications/inbox/{publication_id}/read/").length,
      1,
    );
    assert.deepEqual(
      state.calls("POST", "/publications/inbox/{publication_id}/read/")[0]
        .arguments[1],
      { publication_id: received.id, role },
    );
    assert.match(state.dialog().textContent, /La réunion aura lieu/);
    assert.match(
      document.querySelector(".pub-card .pub-read-state").textContent,
      /^Read$/,
    );
    assert.equal(state.calls("POST", "/publications/").length, 0);
  });
