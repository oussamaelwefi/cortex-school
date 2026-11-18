import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import { createServer } from "vite";
import { fileURLToPath } from "node:url";
import { ApiContext } from "../src/api.tsx";
import { GuardianFamilyPage } from "../src/guardian-family.tsx";
import { attendancePeriod, summarizeAttendance } from "../src/family-attendance.ts";
import { familyFixture, attendanceFixture } from "./fixtures/guardian-family.mjs";

test("attendance uses 30 school-date-based calendar days and counts present plus late", () => {
  const period = attendancePeriod("2026-11-18");
  assert.deepEqual(period, { from: "2026-10-20", to: "2026-11-18" });
  assert.deepEqual(attendancePeriod("2024-03-01"), { from: "2024-02-01", to: "2024-03-01" });
  const summary = summarizeAttendance(attendanceFixture("child-1"), period);
  assert.equal(summary.recorded, 20);
  assert.deepEqual(summary.counts, { present: 18, late: 1, absent: 1, excused: 0 });
  assert.equal(summary.rate, 95);
  assert.equal(summarizeAttendance([], period).rate, null, "no records do not mean zero attendance");
});

test("attendance excludes out-of-period days and counts transfer days only once", () => {
  const period = attendancePeriod("2026-11-18");
  const record = attendanceFixture("child-1")[0];
  const summary = summarizeAttendance([
    { ...record, attendance_record_id: "old-placement", status: "absent", updated_at: "2026-11-18T09:30:00+02:00" },
    { ...record, attendance_record_id: "new-placement", status: "late", updated_at: "2026-11-18T08:00:00Z" },
    { ...record, school_date: "2026-11-19", status: "absent" },
    { ...record, school_date: "2026-10-19", status: "absent" },
  ], period);
  assert.equal(summary.recorded, 1);
  assert.equal(summary.counts.late, 1);
  assert.equal(summary.rate, 100);
});

test("guardians have one child workspace without a separate attendance tab", async (t) => {
  const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), configFile: false, optimizeDeps: { noDiscovery: true }, server: { middlewareMode: true, hmr: false, watch: null } });
  t.after(() => server.close());
  const { pages } = await server.ssrLoadModule("/src/pages.tsx");
  assert.equal(pages.guardian.filter((page) => page.title === "My children").length, 1);
  assert.equal(pages.guardian.some((page) => page.title === "My family" || page.key === "students"), false);
  assert.equal(pages.guardian.some((page) => page.key === "attendance"), false);
  assert.ok(pages.admin.some((page) => page.key === "attendance"));
  assert.ok(pages.teacher.some((page) => page.key === "attendance"));
  assert.ok(pages.guardian.some((page) => page.key === "registrations"));
});

test("guardian child workspace", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/family" });
  const before = { window: globalThis.window, document: globalThis.document, act: globalThis.IS_REACT_ACT_ENVIRONMENT };
  globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const { createRoot } = await import("react-dom/client");
  suite.after(() => { globalThis.window = before.window; globalThis.document = before.document; globalThis.IS_REACT_ACT_ENVIRONMENT = before.act; dom.window.close(); });
  async function mount(t, family = familyFixture, attendance = attendanceFixture) {
    const api = t.mock.fn(async (endpoint, params) => {
      if (endpoint.path === "/guardian/family/") return family;
      if (endpoint.path.endsWith("/attendance")) return attendance(params.student_id);
      if (endpoint.path === "/guardian/students/{student_id}/") return { enrollments: [{ id: "enrollment-private-id", academic_year: { name: "2026–2027", status: "active", starts_on: "2026-09-15", ends_on: "2027-06-30" } }] };
      if (endpoint.path === "/guardian/updates/{recipient_id}/") return { body: "Please review the reading project.", requires_acknowledgement: true, acknowledged_at: null };
      throw new Error(`Unexpected endpoint ${endpoint.path}`);
    });
    const element = document.createElement("div"); document.body.append(element); const root = createRoot(element);
    t.after(async () => { await act(async () => root.unmount()); element.remove(); });
    await act(async () => root.render(createElement(MemoryRouter, null, createElement(ApiContext.Provider, { value: api }, createElement(GuardianFamilyPage)))));
    return { element, api };
  }

  await suite.test("groups each child’s class, today status, rate and updates", async (t) => {
    const { element, api } = await mount(t);
    const cards = element.querySelectorAll(".gf-child-card");
    assert.equal(cards.length, 2);
    assert.match(cards[0].textContent, /Yasmine Ben Ali/);
    assert.match(cards[0].textContent, /6A/);
    assert.match(cards[0].textContent, /95%/);
    assert.match(cards[1].textContent, /100%/);
    assert.match(cards[0].textContent, /1 awaiting your response/);
    assert.match(element.textContent, /Only recorded days are counted/);
    const attendanceCalls = api.mock.calls.filter(({ arguments: [endpoint] }) => endpoint.path.endsWith("/attendance"));
    assert.deepEqual(attendanceCalls.map(({ arguments: [, params] }) => params.student_id), ["child-1", "child-2"]);
    for (const { arguments: [, params] } of attendanceCalls) assert.deepEqual({ from: params.from, to: params.to, limit: params.limit }, { from: "2026-10-20", to: "2026-11-18", limit: 500 });
  });

  await suite.test("does not label missing attendance as absence or show a made-up rate", async (t) => {
    const family = structuredClone(familyFixture);
    family.children = [{ ...family.children[0], placement: { state: "not_placed", classroom_name: null, academic_year_name: null }, attendance: { today: { state: "not_expected", status: null, school_date: family.school_date }, latest_submitted: null } }];
    const { element } = await mount(t, family, () => []);
    assert.match(element.textContent, /Awaiting class placement/);
    assert.match(element.textContent, /No attendance expected/);
    assert.match(element.textContent, /No attendance records yet/);
    assert.equal(element.querySelector(".gf-rate-value strong").textContent, "—");
    assert.doesNotMatch(element.querySelector(".gf-today-status").textContent, /Absent/);
  });

  await suite.test("opens the child’s attendance history and enrollment record without exposing IDs", async (t) => {
    const { element, api } = await mount(t);
    const card = element.querySelector(".gf-child-card");
    await act(async () => card.querySelector(".gf-history-toggle").click());
    assert.equal(card.querySelectorAll("tbody tr").length, 20);
    await act(async () => card.querySelector(".gf-child-actions button").click());
    assert.deepEqual(api.mock.calls.at(-1).arguments[1], { student_id: "child-1" });
    const dialog = document.querySelector("[role='dialog']");
    assert.match(dialog.textContent, /Enrollment history/);
    assert.match(dialog.textContent, /2026–2027/);
    assert.doesNotMatch(dialog.textContent, /enrollment-private-id|child-1/);
  });

  await suite.test("opens the linked update without automatically acknowledging it", async (t) => {
    const { element, api } = await mount(t);
    await act(async () => element.querySelector(".gf-latest-update").click());
    assert.deepEqual(api.mock.calls.at(-1).arguments[1], { recipient_id: "recipient-1" });
    assert.match(document.querySelector("[role='dialog']").textContent, /Please review the reading project/);
    assert.ok(api.mock.calls.every(({ arguments: [endpoint] }) => endpoint.method === "GET"));
  });

  await suite.test("keeps a child’s class visible when their attendance request fails", async (t) => {
    const { element } = await mount(t, familyFixture, (studentId) => {
      if (studentId === "child-1") throw new Error("Attendance unavailable");
      return attendanceFixture(studentId);
    });
    const cards = element.querySelectorAll(".gf-child-card");
    assert.match(cards[0].textContent, /6A/);
    assert.match(cards[0].textContent, /Attendance is temporarily unavailable/);
    assert.match(cards[1].textContent, /100%/);
  });

  await suite.test("shows registration progress when no children have been linked yet", async (t) => {
    const { element, api } = await mount(t, { ...familyFixture, children: [] });
    assert.match(element.textContent, /No children linked yet/);
    assert.match(element.querySelector(".gf-registration-list").textContent, /Lina Ben Ali/);
    assert.equal(api.mock.calls.filter(({ arguments: [endpoint] }) => endpoint.path.endsWith("/attendance")).length, 0);
  });
});
