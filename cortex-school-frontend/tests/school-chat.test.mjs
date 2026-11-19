import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement as h } from "react";
import { JSDOM } from "jsdom";
import { registerHooks } from "node:module";
import { MemoryRouter } from "react-router-dom";
import { ApiContext } from "../src/api.tsx";
import { schoolChatPayload } from "../src/chat-request.ts";

registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith(".css"))
      return { format: "module", source: "export {};", shortCircuit: true };
    return nextLoad(url, context);
  },
});
const { ChatAssistant } = await import("../src/chat.tsx");

test("chat payload sends the workspace separately and keeps bounded recent history", () => {
  const latest = { id: "last", role: "user", text: "Mes enfants ?" };
  assert.deepEqual(
    schoolChatPayload("guardian", "fr", [
      { id: "welcome", role: "assistant", text: "Welcome" },
      latest,
    ]),
    { message: "Mes enfants ?", role: "guardian", language: "fr" },
  );
  const conversation = Array.from({ length: 20 }, (_, i) => ({
    id: String(i),
    role: i % 2 ? "assistant" : "user",
    text: `${i}: ${"a".repeat(11000)}`,
  }));
  const result = schoolChatPayload("teacher", "en", [...conversation, latest]);
  assert.ok(result.message.length < 27000);
  assert.match(result.message, /Mes enfants/);
  assert.doesNotMatch(
    result.message,
    /0: a|no school-data tools|The user is a/,
  );
  const privateAnswer = schoolChatPayload("admin", "en", [
    { id: "q1", role: "user", text: "Who is absent?" },
    { id: "a1", role: "assistant", text: "PRIVATE CHILD RECORD [S1]" },
    latest,
  ]);
  assert.doesNotMatch(privateAnswer.message, /PRIVATE CHILD RECORD/);
});

async function mount(t, role, failOnce = false, options = {}) {
  const dom = new JSDOM(
    "<!doctype html><html><body><div id='root'></div></body></html>",
    { url: "http://localhost/chat" },
  );
  const previous = {
    window: globalThis.window,
    document: globalThis.document,
    act: globalThis.IS_REACT_ACT_ENVIRONMENT,
  };
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  dom.window.HTMLElement.prototype.scrollTo = () => {};
  dom.window.matchMedia = () => ({ matches: true });
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(document.getElementById("root"));
  let attempts = 0;
  const state = {
    school_data_enabled: true,
    personal_data_enabled: true,
    effective_data_enabled: true,
    can_manage_school: role === "admin",
    can_manage_personal: role === "guardian",
    revision: 0,
  };
  const api = t.mock.fn(async (endpoint, params, body) => {
    if (endpoint.path === "/ai/chat/access/" && endpoint.method === "GET")
      return { ...state };
    if (endpoint.method === "PUT") {
      if (options.failSave) throw Error("Unable to save preference");
      state[
        role === "admin" ? "school_data_enabled" : "personal_data_enabled"
      ] = body.enabled;
      state.effective_data_enabled =
        state.school_data_enabled && state.personal_data_enabled;
      state.revision++;
      return { ...state };
    }
    if (failOnce && ++attempts === 1)
      throw Error("School data is temporarily unavailable. Please try again.");
    return {
      reply: "Deux élèves [S1]. Une autorisation est requise [S2].",
      sources: [
        {
          id: "S1",
          label: "Students",
          href: role === "guardian" ? "/family" : "/classrooms",
        },
        {
          id: "S2",
          label: "Règlement des sorties",
          excerpt: "Une autorisation parentale signée est requise.",
        },
        { id: "S3", label: "Unsafe link", href: "//external.example" },
      ],
    };
  });
  api.privacy = state;
  await act(async () =>
    root.render(
      h(
        MemoryRouter,
        null,
        h(ApiContext.Provider, { value: api }, h(ChatAssistant, { role })),
      ),
    ),
  );
  t.after(async () => {
    await act(async () => root.unmount());
    dom.window.close();
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = previous.act;
  });
  return api;
}

for (const role of ["admin", "teacher", "guardian"]) {
  test(`${role} can ask for data and inspect the returned record and policy sources`, async (t) => {
    const api = await mount(t, role);
    await act(async () =>
      document.querySelectorAll(".chat-suggestions button")[1].click(),
    );
    const [endpoint, , payload] = api.mock.calls.find(
      (c) => c.arguments[0].method === "POST",
    ).arguments;
    assert.equal(endpoint.path, "/ai/chat/");
    assert.equal(payload.role, role);
    assert.equal(payload.language, "en");
    assert.match(
      document.querySelector(".chat-sources").textContent,
      /S1.*Students/,
    );
    assert.equal(
      document.querySelector(".chat-source a").getAttribute("href"),
      role === "guardian" ? "/family" : "/classrooms",
    );
    assert.equal(document.querySelectorAll(".chat-source a").length, 1);
    const details = document.querySelector(".chat-source details");
    assert.match(details.textContent, /autorisation parentale signée/);
    assert.equal(details.open, false);
    assert.equal(document.querySelectorAll(".chat-message.user").length, 1);
  });
}

test("a failed lookup keeps the question and retries it without duplicating the user turn", async (t) => {
  const api = await mount(t, "guardian", true);
  await act(async () =>
    document.querySelectorAll(".chat-suggestions button")[1].click(),
  );
  assert.ok(document.querySelector('[role="alert"]'));
  await act(async () => document.querySelector(".chat-error button").click());
  const posts = api.mock.calls.filter((c) => c.arguments[0].method === "POST");
  assert.equal(posts.length, 2);
  assert.deepEqual(posts[0].arguments[2], posts[1].arguments[2]);
  assert.equal(document.querySelectorAll(".chat-message.user").length, 1);
  assert.equal(document.querySelector('[role="alert"]'), null);
  assert.ok(document.querySelector(".chat-sources"));
});

for (const role of ["admin", "guardian"]) {
  test(`${role} can disable data access and clear old sourced answers`, async (t) => {
    const api = await mount(t, role);
    await act(async () =>
      document.querySelectorAll(".chat-suggestions button")[1].click(),
    );
    assert.ok(document.querySelector(".chat-sources"));
    await act(async () => document.querySelector('[role="switch"]').click());
    assert.equal(document.querySelector('[role="switch"]').checked, false);
    assert.equal(document.querySelector(".chat-sources"), null);
    assert.equal(
      document.querySelectorAll(".chat-suggestions button").length,
      1,
    );
    assert.match(
      document.querySelector(".chat-access-status").textContent,
      /Data access off/,
    );
    const update = api.mock.calls.find(
      (c) => c.arguments[0].method === "PUT",
    ).arguments;
    assert.equal(
      update[0].path,
      role === "admin" ? "/school/chat-data-settings" : "/ai/chat/access/",
    );
    assert.deepEqual(update[2], { enabled: false });
    await act(async () => document.querySelector('[role="switch"]').click());
    assert.equal(
      document.querySelectorAll(".chat-suggestions button").length,
      3,
    );
  });
}

test("teacher sees data access status without a setting they cannot change", async (t) => {
  await mount(t, "teacher");
  assert.ok(document.querySelector(".chat-access-status"));
  assert.equal(document.querySelector('[role="switch"]'), null);
});

test("a failed privacy save preserves the last confirmed preference", async (t) => {
  await mount(t, "guardian", false, { failSave: true });
  await act(async () => document.querySelector('[role="switch"]').click());
  assert.equal(document.querySelector('[role="switch"]').checked, true);
  assert.match(
    document.querySelector('.chat-access [role="alert"]').textContent,
    /Unable to save preference/,
  );
  assert.match(
    document.querySelector(".chat-access-status").textContent,
    /Data access on/,
  );
});

test("returning to the chat refreshes external privacy changes and clears old results", async (t) => {
  const api = await mount(t, "guardian");
  await act(async () =>
    document.querySelectorAll(".chat-suggestions button")[1].click(),
  );
  api.privacy.personal_data_enabled = false;
  api.privacy.effective_data_enabled = false;
  api.privacy.revision++;
  await act(async () => window.dispatchEvent(new window.Event("focus")));
  assert.equal(document.querySelector(".chat-sources"), null);
  assert.equal(document.querySelector('[role="switch"]').checked, false);
  assert.equal(document.querySelectorAll(".chat-suggestions button").length, 1);
});
