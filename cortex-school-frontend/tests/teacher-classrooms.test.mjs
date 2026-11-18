import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import { ApiContext } from "../src/api.tsx";
import { TeacherClassroomsPage } from "../src/teacher-classrooms.tsx";

test("teacher classroom workspace", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/classrooms",
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
  const classes = [
    {
      id: "class-6a",
      name: "6A",
      academic_year_id: "year-current",
      assignment_role: "lead",
      assignment_effective_from: "2026-09-01",
      assignment_effective_until: null,
      access_status: "current",
    },
    {
      id: "class-6b",
      name: "6B",
      academic_year_id: "year-current",
      assignment_role: "assistant",
      assignment_effective_from: "2026-09-01",
      assignment_effective_until: null,
      access_status: "current",
    },
    {
      id: "class-future",
      name: "7A",
      academic_year_id: "year-future",
      assignment_role: "lead",
      assignment_effective_from: "2027-09-01",
      assignment_effective_until: null,
      access_status: "upcoming",
    },
  ];
  const roster = [
    {
      student_id: "student-yasmine",
      first_name: "Yasmine",
      last_name: "Ben Ali",
      effective_from: "2026-09-01",
      effective_until: null,
    },
    {
      student_id: "student-adam",
      first_name: "Adam",
      last_name: "Trabelsi",
      effective_from: "2026-09-15",
      effective_until: null,
    },
  ];
  async function mount(t, options = {}) {
    const api = t.mock.fn(async (endpoint, params = {}, body) => {
      const overridden = await options.read?.(endpoint, params, body);
      if (overridden !== undefined) return overridden;
      if (endpoint.path === "/teacher/today")
        return {
          school_date: "2026-11-18",
          can_submit_attendance: true,
          classrooms: [
            {
              id: "class-6a",
              active_student_count: 2,
              attendance: { status: "not_started", recorded_student_count: 0 },
            },
            {
              id: "class-6b",
              active_student_count: 1,
              attendance: { status: "submitted", recorded_student_count: 1 },
            },
          ],
        };
      if (endpoint.path.endsWith("/students/"))
        return params.classroom_id === "class-6a" ? roster : [];
      if (endpoint.path.endsWith("/calendar/"))
        return {
          entries: [
            {
              id: "term-1",
              title: "First term",
              entry_type: "term",
              starts_on: "2026-09-01",
              ends_on: "2026-12-19",
            },
            {
              id: "holiday-1",
              title: "Winter holiday",
              entry_type: "break",
              starts_on: "2026-12-20",
              ends_on: "2027-01-03",
            },
          ],
        };
      if (endpoint.path === "/teacher/updates/" && endpoint.method === "POST")
        return { id: "new-update" };
      throw new Error(`Unexpected call: ${endpoint.method} ${endpoint.path}`);
    });
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    const onRefresh = t.mock.fn();
    t.after(async () => {
      await act(async () => root.unmount());
      element.remove();
    });
    await act(async () =>
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: [options.path ?? "/classrooms"] },
          createElement(
            ApiContext.Provider,
            { value: api },
            createElement(TeacherClassroomsPage, {
              classrooms: {
                data: options.classes ?? classes,
                loading: false,
                error: options.error ?? "",
              },
              onRefresh,
            }),
          ),
        ),
      ),
    );
    const button = (text, parent = element) =>
      [...parent.querySelectorAll("button")].find(
        (node) => node.textContent.trim() === text,
      );
    const click = async (node) => {
      assert.ok(node, "the control is available");
      await act(async () => node.click());
    };
    const change = async (input, value) =>
      act(async () => {
        const proto =
          input.tagName === "SELECT"
            ? dom.window.HTMLSelectElement.prototype
            : dom.window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, "value").set.call(input, value);
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
        input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
    return { element, api, onRefresh, button, click, change };
  }

  await suite.test(
    "class cards keep names, roles, current counts and direct actions together without fetching every roster",
    async (t) => {
      const { element, api } = await mount(t);
      const cards = element.querySelectorAll(".tc-class-card");
      assert.equal(cards.length, 3);
      assert.match(
        cards[0].textContent,
        /6A.*Lead teacher.*2Students today.*Attendance not recorded/s,
      );
      assert.match(
        cards[1].textContent,
        /6B.*Assistant teacher.*Attendance saved/s,
      );
      assert.equal(
        cards[0].querySelector("a").getAttribute("href"),
        "/attendance?classroom_id=class-6a",
      );
      assert.doesNotMatch(
        element.textContent,
        /year-current|class-6a|academic_year_id|All workflows/,
      );
      assert.equal(
        api.mock.callCount(),
        1,
        "only the shared daily overview is requested on this page",
      );
    },
  );

  await suite.test(
    "opening a class loads its students once and fetches its calendar only when requested",
    async (t) => {
      const { element, api, button, click } = await mount(t);
      await click(
        button("Open class", element.querySelector(".tc-class-card")),
      );
      assert.match(
        element.querySelector(".tc-roster").textContent,
        /Yasmine Ben Ali.*Adam Trabelsi/s,
      );
      assert.doesNotMatch(element.textContent, /student-yasmine|student-adam/);
      assert.equal(
        api.mock.calls.filter(({ arguments: [endpoint] }) =>
          endpoint.path.endsWith("/calendar/"),
        ).length,
        0,
      );
      await click(button("Calendar"));
      assert.match(
        element.querySelector(".tc-calendar-events").textContent,
        /First term.*Winter holiday/s,
      );
      assert.ok(
        api.mock.calls
          .filter(({ arguments: [endpoint] }) =>
            endpoint.path.endsWith("/calendar/"),
          )
          .every(
            ({ arguments: [, params] }) => params.classroom_id === "class-6a",
          ),
      );
      await click(
        [...element.querySelectorAll('[role="tab"]')].find((node) =>
          node.textContent.startsWith("Students"),
        ),
      );
      await click(button("Calendar"));
      assert.equal(
        api.mock.calls.filter(({ arguments: [endpoint] }) =>
          endpoint.path.endsWith("/calendar/"),
        ).length,
        1,
      );
      assert.equal(
        api.mock.calls.filter(({ arguments: [endpoint] }) =>
          endpoint.path.endsWith("/students/"),
        ).length,
        1,
      );
    },
  );

  await suite.test(
    "name search and assignment filters stay local and do not lose focus",
    async (t) => {
      const { element, api, button, click, change } = await mount(t);
      await click(
        [...element.querySelectorAll(".tc-filters button")].find((node) =>
          node.textContent.startsWith("Upcoming assignments"),
        ),
      );
      assert.equal(element.querySelectorAll(".tc-class-card").length, 1);
      assert.match(element.querySelector(".tc-class-card").textContent, /7A/);
      await click(
        [...element.querySelectorAll(".tc-filters button")].find((node) =>
          node.textContent.startsWith("All my classes"),
        ),
      );
      const search = element.querySelector(
        'input[aria-label="Search my classes"]',
      );
      search.focus();
      await change(search, "6b");
      assert.equal(document.activeElement === search, true);
      assert.equal(element.querySelectorAll(".tc-class-card").length, 1);
      assert.match(element.querySelector(".tc-class-card").textContent, /6B/);
      await change(search, "unknown");
      assert.match(element.textContent, /No classes match these filters/);
      await click(button("Show all my classes"));
      assert.equal(element.querySelectorAll(".tc-class-card").length, 3);
      assert.equal(api.mock.callCount(), 1);
    },
  );

  await suite.test(
    "upcoming classes explain their availability and cannot start attendance or message composition",
    async (t) => {
      const { element, button, click } = await mount(t);
      const card = element.querySelector(".tc-class-card.upcoming");
      assert.equal(button("Attendance", card).disabled, true);
      assert.equal(button("Write to families", card), undefined);
      assert.equal(
        card.querySelector(".tc-student-count"),
        null,
        "an unavailable count is not rendered as zero",
      );
      await click(button("Open class", card));
      assert.match(
        element.querySelector(".tc-upcoming-note").textContent,
        /Prepare for your upcoming class/,
      );
      assert.equal(button("Write to families"), undefined);
      await click(button("Calendar"));
      assert.ok(element.querySelector(".tc-calendar-events"));
    },
  );

  await suite.test(
    "a class message starts with the correct named class and classroom audience",
    async (t) => {
      const { element, api, button, click, change } = await mount(t);
      await click(
        button("Write to families", element.querySelector(".tc-class-card")),
      );
      const dialog = document.querySelector("[role='dialog']");
      assert.match(dialog.textContent, /6A/);
      assert.equal(dialog.querySelector("select").value, "class-6a");
      await change(
        dialog.querySelector("input[maxlength='255']"),
        "Class news",
      );
      await act(async () =>
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      const call = api.mock.calls.find(
        ({ arguments: [endpoint] }) => endpoint.method === "POST",
      );
      assert.equal(call.arguments[2].classroom_id, "class-6a");
      assert.deepEqual(call.arguments[2].target, { type: "classroom" });
    },
  );

  await suite.test(
    "a student's message is addressed only to that student and preserves the class context",
    async (t) => {
      const { element, api, click, change } = await mount(t, {
        path: "/classrooms?classroom_id=class-6a",
      });
      await click(
        element.querySelector(
          '[aria-label="Write an update · Yasmine Ben Ali"]',
        ),
      );
      const dialog = document.querySelector("[role='dialog']");
      assert.match(dialog.textContent, /6A · Yasmine Ben Ali/);
      await change(
        dialog.querySelector("input[maxlength='255']"),
        "Yasmine's progress",
      );
      await act(async () =>
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      const call = api.mock.calls.find(
        ({ arguments: [endpoint] }) => endpoint.method === "POST",
      );
      assert.equal(call.arguments[2].classroom_id, "class-6a");
      assert.deepEqual(call.arguments[2].target, {
        type: "students",
        student_ids: ["student-yasmine"],
      });
    },
  );

  await suite.test(
    "daily overview failures keep classes usable without inventing counts",
    async (t) => {
      const { element, button, click } = await mount(t, {
        read(endpoint) {
          if (endpoint.path === "/teacher/today")
            throw new Error("Today unavailable");
        },
      });
      assert.equal(element.querySelectorAll(".tc-class-card").length, 3);
      assert.equal(element.querySelectorAll(".tc-student-count").length, 0);
      assert.match(
        element.textContent,
        /Today’s attendance overview is unavailable/,
      );
      await click(
        button("Open class", element.querySelector(".tc-class-card")),
      );
      assert.match(
        element.querySelector(".tc-roster").textContent,
        /Yasmine Ben Ali/,
      );
    },
  );

  await suite.test(
    "unassigned classes and stale deep links have clear states and never fetch an unauthorized roster",
    async (t) => {
      const { element, api, button, click } = await mount(t, {
        path: "/classrooms?classroom_id=not-my-class",
      });
      assert.match(
        element.textContent,
        /This class is not in your current assignments/,
      );
      assert.ok(
        api.mock.calls.every(
          ({ arguments: [endpoint] }) => endpoint.path === "/teacher/today",
        ),
      );
      await click(button("Back to my classes"));
      assert.equal(element.querySelectorAll(".tc-class-card").length, 3);
    },
  );
});
