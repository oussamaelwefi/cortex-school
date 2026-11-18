import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import { ApiContext } from "../src/api.tsx";
import { NeedsReviewPage, reviewDetailRequest } from "../src/needs-review.tsx";
import { reviewItems, queueResponse } from "./fixtures/review-queue.mjs";

test("admin review queue", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/review" });
  const before = { window: globalThis.window, document: globalThis.document, act: globalThis.IS_REACT_ACT_ENVIRONMENT };
  globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const { createRoot } = await import("react-dom/client");
  suite.after(() => { globalThis.window = before.window; globalThis.document = before.document; globalThis.IS_REACT_ACT_ENVIRONMENT = before.act; dom.window.close(); });
  async function mount(t, records = reviewItems, readDetail = () => null) {
    const api = t.mock.fn(async (endpoint, params) => endpoint.path === "/needs-review/" ? queueResponse(records, params) : readDetail(endpoint, params));
    const element = document.createElement("div"); document.body.append(element);
    const root = createRoot(element);
    t.after(async () => { await act(async () => root.unmount()); element.remove(); });
    await act(async () => root.render(createElement(MemoryRouter, null, createElement(ApiContext.Provider, { value: api }, createElement(NeedsReviewPage)))));
    const button = (selector, text) => Array.from(element.querySelectorAll(selector)).find((node) => node.textContent.includes(text));
    return { element, api, button };
  }

  await suite.test("keeps context, due date and the next action together without raw response fields", async (t) => {
    const { element } = await mount(t);
    assert.equal(element.querySelectorAll(".nr-item").length, 5);
    const attendance = element.querySelectorAll(".nr-item")[1];
    assert.match(attendance.textContent, /6B attendance is missing/);
    assert.match(attendance.textContent, /Amira Mansour/);
    assert.match(attendance.textContent, /2026–2027/);
    assert.ok(attendance.querySelector("time"));
    assert.match(attendance.querySelector("button").textContent, /View attendance/);
    assert.equal(element.querySelector("a[href='/updates/pickup-update/reminder']").textContent, "Review reminder");
    assert.doesNotMatch(element.textContent, /next_offset|category_counts|class-6b|year-2026/);
  });

  await suite.test("category filters reach the API while summary counts stay school-wide", async (t) => {
    const { element, button, api } = await mount(t);
    await act(async () => button(".nr-sidebar button", "Acknowledgements").click());
    assert.deepEqual(api.mock.calls.at(-1).arguments[1].category, ["acknowledgement"]);
    assert.equal(api.mock.calls.at(-1).arguments[1].offset, 0);
    assert.equal(element.querySelectorAll(".nr-item").length, 1);
    assert.equal(element.querySelector(".nr-overview strong").textContent, "5");
    assert.match(button(".nr-sidebar button", "Attendance").textContent, /1$/);
  });

  await suite.test("pagination retains filters and changing category resets to the first page", async (t) => {
    const records = Array.from({ length: 23 }, (_, index) => ({ ...reviewItems[1], id: `attendance-${index}`, title: `Class ${index} attendance is missing` }));
    const { element, api, button } = await mount(t, records);
    await act(async () => element.querySelector("button[aria-label='Next page']").click());
    assert.equal(api.mock.calls.at(-1).arguments[1].offset, 20);
    assert.equal(element.querySelectorAll(".nr-item").length, 3);
    assert.match(element.querySelector(".nr-pagination").textContent, /Showing 21–23 of 23/);
    await act(async () => button(".nr-sidebar button", "Attendance").click());
    assert.equal(api.mock.calls.at(-1).arguments[1].offset, 0);
    assert.deepEqual(api.mock.calls.at(-1).arguments[1].category, ["missing_attendance"]);
  });

  await suite.test("date ranges are validated before fetching, then applied together", async (t) => {
    const { element, api, button } = await mount(t);
    await act(async () => button(".nr-toolbar button", "Date range").click());
    const from = element.querySelector("input[aria-label='From date']"), to = element.querySelector("input[aria-label='To date']");
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
      setter.call(from, "2026-11-20"); from.dispatchEvent(new dom.window.Event("input", { bubbles: true })); from.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      setter.call(to, "2026-11-18"); to.dispatchEvent(new dom.window.Event("input", { bubbles: true })); to.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    const beforeApply = api.mock.callCount();
    await act(async () => element.querySelector(".nr-date-range").dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })));
    assert.equal(api.mock.callCount(), beforeApply);
    assert.match(element.querySelector("[role='alert']").textContent, /start date/);
    await act(async () => {
      Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set.call(from, "2026-11-01");
      from.dispatchEvent(new dom.window.Event("input", { bubbles: true })); from.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await act(async () => element.querySelector(".nr-date-range").dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })));
    assert.equal(api.mock.calls.at(-1).arguments[1].date_from, "2026-11-01");
    assert.equal(api.mock.calls.at(-1).arguments[1].date_to, "2026-11-18");
  });

  await suite.test("attendance details load the correct school day and classroom without changing data", async (t) => {
    const { button, api } = await mount(t, reviewItems, () => ({ classrooms: [
      { classroom_id: "another-class", classroom_name: "Another class", status: "submitted" },
      { classroom_id: "class-6b", classroom_name: "6B", status: "missing", active_student_count: 24 },
    ] }));
    await act(async () => button(".nr-item button", "View attendance").click());
    assert.equal(api.mock.calls.at(-1).arguments[0].path, "/attendance/submissions");
    assert.deepEqual(api.mock.calls.at(-1).arguments[1], { school_date: "2026-11-18" });
    assert.match(document.querySelector("[role='dialog']").textContent, /24/);
    assert.doesNotMatch(document.querySelector("[role='dialog']").textContent, /Another class/);
    assert.ok(api.mock.calls.every(({ arguments: [endpoint] }) => endpoint.method === "GET"));
  });

  await suite.test("an empty queue keeps its filters available", async (t) => {
    const { element } = await mount(t, []);
    assert.match(element.textContent, /You’re all caught up/);
    assert.ok(element.querySelector("select[aria-label='Priority']"));
    assert.equal(element.querySelector(".nr-overview strong").textContent, "0");
  });
});

test("registration details select the exact request and invitation details bind its ID", () => {
  const request = reviewDetailRequest(reviewItems[3]);
  assert.equal(request.select([{ id: "another-request" }, { id: "request-1", status: "pending" }]).id, "request-1");
  assert.deepEqual(reviewDetailRequest(reviewItems[4]).params, { invitation_id: "invite-1" });
});
