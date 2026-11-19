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
});

async function mount(t, role, failOnce = false) {
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
  const api = t.mock.fn(async () => {
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
    const [endpoint, , payload] = api.mock.calls[0].arguments;
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
  assert.equal(api.mock.callCount(), 2);
  assert.deepEqual(
    api.mock.calls[0].arguments[2],
    api.mock.calls[1].arguments[2],
  );
  assert.equal(document.querySelectorAll(".chat-message.user").length, 1);
  assert.equal(document.querySelector('[role="alert"]'), null);
  assert.ok(document.querySelector(".chat-sources"));
});
