import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { ApiContext, findEndpoint } from "../src/api.tsx";
import { PolicyDocument } from "../src/policy-document.tsx";

const policy = { id: "policy-1", title: "Family handbook" };
const guardianPdf = findEndpoint("GET", "/guardian/family/policies/{document_id}/pdf/");
const adminPdf = findEndpoint("GET", "/school-policies/{document_id}/pdf");

test("policy documents can be read without saving a file", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
  const before = { window: globalThis.window, document: globalThis.document, act: globalThis.IS_REACT_ACT_ENVIRONMENT };
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

  async function mount(t, api, endpoint = guardianPdf) {
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    t.after(async () => { await act(async () => root.unmount()); element.remove(); });
    const created = t.mock.method(URL, "createObjectURL", () => "blob:policy-preview");
    const revoked = t.mock.method(URL, "revokeObjectURL", () => {});
    await act(async () => root.render(createElement(ApiContext.Provider, { value: api },
      createElement(PolicyDocument, { policy, endpoint }))));
    return { element, root, created, revoked };
  }

  for (const endpoint of [guardianPdf, adminPdf]) {
    await suite.test(`${endpoint.path}: preview uses the authenticated API and releases its URL on close`, async (t) => {
      const pdf = new Blob(["%PDF-1.7"], { type: "application/pdf" });
      const api = t.mock.fn(async () => pdf);
      const { element, created, revoked } = await mount(t, api, endpoint);
      assert.equal(api.mock.callCount(), 0, "closed documents are not fetched");
      assert.equal(element.querySelector("iframe"), null);
      const toggle = element.querySelector("button");
      await act(async () => toggle.click());
      assert.deepEqual(api.mock.calls[0].arguments, [endpoint, { document_id: policy.id }]);
      assert.equal(created.mock.calls[0].arguments[0], pdf);
      assert.ok(element.querySelector(".policy-pdf-reader"));
      assert.equal(element.querySelector("iframe"), null, "reading does not rely on browser PDF plugins");
      assert.equal(element.querySelector("a[download]").getAttribute("download"), "Family handbook.pdf");
      assert.equal(element.querySelector("a[target='_blank']").getAttribute("href"), "blob:policy-preview");
      assert.equal(revoked.mock.callCount(), 0, "the URL stays alive while reading");
      await act(async () => toggle.click());
      assert.equal(element.querySelector("iframe"), null);
      assert.deepEqual(revoked.mock.calls[0].arguments, ["blob:policy-preview"]);
    });
  }

  await suite.test("failed previews show an error and retry the same document", async (t) => {
    let attempts = 0;
    const api = t.mock.fn(async () => {
      if (++attempts === 1) throw new Error("Policy PDF not found.");
      return new Blob(["%PDF-1.7"], { type: "application/pdf" });
    });
    const { element } = await mount(t, api);
    await act(async () => element.querySelector("button").click());
    assert.match(element.querySelector("[role='alert']").textContent, /Policy PDF not found/);
    assert.equal(element.querySelector("iframe"), null);
    await act(async () => element.querySelector("[role='alert'] button").click());
    assert.equal(api.mock.callCount(), 2);
    assert.ok(element.querySelector(".policy-pdf-reader"));
  });

  await suite.test("closing during a fetch does not create an orphaned preview URL", async (t) => {
    let finish;
    const api = () => new Promise((resolve) => { finish = resolve; });
    const { element, created } = await mount(t, api);
    await act(async () => element.querySelector("button").click());
    assert.ok(element.querySelector("[role='status']"));
    await act(async () => element.querySelector("button").click());
    await act(async () => finish(new Blob(["%PDF-1.7"], { type: "application/pdf" })));
    assert.equal(created.mock.callCount(), 0);
    assert.equal(element.querySelector("iframe"), null);
  });
});
