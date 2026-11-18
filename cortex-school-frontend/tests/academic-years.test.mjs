import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement, useState } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import { ApiContext } from "../src/api.tsx";
import { AcademicYearsPage } from "../src/academic-years.tsx";

test("academic year workspace", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/academic-years",
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

  async function mount(t, options = {}) {
    let records = [
      {
        id: "draft",
        name: "2027–2028",
        status: "draft",
        starts_on: "2027-09-01",
        ends_on: "2028-06-30",
      },
      {
        id: "active",
        name: "2026–2027",
        status: "active",
        starts_on: "2026-09-01",
        ends_on: "2027-06-30",
      },
      {
        id: "closed",
        name: "2025–2026",
        status: "closed",
        starts_on: "2025-09-01",
        ends_on: "2026-06-30",
      },
    ];
    const entries = {
      draft: [],
      active: [
        {
          id: "term",
          title: "First semester",
          entry_type: "term",
          starts_on: "2026-09-01",
          ends_on: "2026-12-31",
        },
        {
          id: "holiday",
          title: "Winter holiday",
          entry_type: "holiday",
          starts_on: "2026-12-20",
          ends_on: "2026-12-25",
        },
      ],
      closed: [
        {
          id: "history",
          title: "Historical term",
          entry_type: "term",
          starts_on: "2025-09-01",
          ends_on: "2025-12-31",
        },
      ],
    };
    const api = t.mock.fn(async (endpoint, params = {}, body) => {
      const override = await options.read?.(endpoint, params, body);
      if (override !== undefined) return override;
      if (endpoint.method === "GET" && endpoint.path.endsWith("/calendar/"))
        return { entries: entries[params.year_id] ?? [] };
      if (endpoint.method === "GET" && endpoint.path.endsWith("/readiness/")) {
        const ready = (entries[params.year_id] ?? []).some(
          (entry) => entry.entry_type === "term",
        );
        return {
          can_publish: ready,
          errors: ready ? [] : ["At least one calendar term is required"],
          warnings: ["No classrooms have been created"],
        };
      }
      if (endpoint.method === "POST" && endpoint.path === "/academic-years/") {
        const year = { ...body, id: "new-year", status: "draft" };
        records.push(year);
        return year;
      }
      if (
        endpoint.method === "PUT" &&
        endpoint.path === "/academic-years/{year_id}/"
      ) {
        const index = records.findIndex((year) => year.id === params.year_id);
        records[index] = { ...records[index], ...body };
        return records[index];
      }
      if (
        endpoint.method === "POST" &&
        endpoint.path.endsWith("/calendar/entries/")
      ) {
        const entry = { ...body, id: "new-event" };
        (entries[params.year_id] ??= []).push(entry);
        return entry;
      }
      if (endpoint.method === "DELETE") {
        entries[params.year_id] = entries[params.year_id].filter(
          (entry) => entry.id !== params.entry_id,
        );
        return null;
      }
      if (
        endpoint.path.endsWith("/publish/") ||
        endpoint.path.endsWith("/close/")
      ) {
        const index = records.findIndex((year) => year.id === params.year_id);
        records[index] = {
          ...records[index],
          status: endpoint.path.endsWith("/publish/") ? "active" : "closed",
        };
        return records[index];
      }
      throw new Error(
        `Unexpected API call: ${endpoint.method} ${endpoint.path}`,
      );
    });
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    const onYearChange = t.mock.fn();
    function Harness() {
      const [data, setData] = useState([...records]);
      return createElement(AcademicYearsPage, {
        years: { data, loading: false, error: "" },
        initialYear: options.initialYear ?? "draft",
        onYearChange,
        onRefresh: () => setData([...records]),
      });
    }
    await act(async () =>
      root.render(
        createElement(
          MemoryRouter,
          null,
          createElement(
            ApiContext.Provider,
            { value: api },
            createElement(Harness),
          ),
        ),
      ),
    );
    t.after(async () => {
      await act(async () => root.unmount());
      element.remove();
    });
    const button = (text, parent = element) =>
      [...parent.querySelectorAll("button")].find(
        (node) => node.textContent.trim() === text,
      );
    const click = async (node) => {
      assert.ok(node, "button is available");
      await act(async () => node.click());
    };
    const change = async (input, value) => {
      assert.ok(input);
      await act(async () => {
        const prototype =
          input.tagName === "SELECT"
            ? dom.window.HTMLSelectElement.prototype
            : dom.window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(prototype, "value").set.call(
          input,
          value,
        );
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
        input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
    };
    const submit = async () =>
      act(async () =>
        document
          .querySelector("[role='dialog'] form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
    return {
      element,
      api,
      button,
      click,
      change,
      submit,
      entries,
      onYearChange,
    };
  }

  await suite.test(
    "a draft explains the missing period and can be published after adding one, without treating warnings as blockers",
    async (t) => {
      const { element, api, button, click, change, submit } = await mount(t);
      assert.equal(button("Publish year").disabled, true);
      assert.match(
        element.querySelector(".ay-blockers").textContent,
        /At least one calendar term is required/,
      );
      await click(button("Add a term"));
      const dialog = document.querySelector("[role='dialog']");
      assert.doesNotMatch(dialog.textContent, /Year Id|Calendar Id/);
      assert.equal(dialog.querySelector("select").value, "term");
      assert.equal(
        dialog.querySelector("input[type=date]").value,
        "2027-09-01",
      );
      await change(dialog.querySelector("input[type=text]"), "First term");
      await submit();
      const create = api.mock.calls.find(
        ({ arguments: [endpoint] }) => endpoint.method === "POST",
      );
      assert.equal(create.arguments[1].year_id, "draft");
      assert.equal(create.arguments[2].title, "First term");
      assert.equal(button("Publish year").disabled, false);
      await click(button("Publish year"));
      assert.match(
        document.querySelector("[role='dialog']").textContent,
        /You can complete these later.*No classrooms have been created/s,
      );
      assert.equal(
        api.mock.calls.filter(({ arguments: [endpoint] }) =>
          endpoint.path.endsWith("/publish/"),
        ).length,
        0,
      );
      await click(
        button("Publish year", document.querySelector("[role='dialog']")),
      );
      assert.match(
        element.querySelector(".ay-state-note").textContent,
        /This year is published/,
      );
      assert.equal(document.querySelector("[role='dialog']"), null);
    },
  );

  await suite.test(
    "closed years keep their calendar readable with no mutation actions",
    async (t) => {
      const { element, api } = await mount(t, { initialYear: "closed" });
      assert.match(
        element.querySelector(".ay-events").textContent,
        /Historical term/,
      );
      assert.match(
        element.querySelector(".ay-state-note").textContent,
        /This year is closed/,
      );
      assert.doesNotMatch(
        element.querySelector(".ay-workspace").textContent,
        /Add a term|Add an event|Edit year|Close year|Publish year/,
      );
      assert.equal(element.querySelector(".ay-event-actions"), null);
      assert.ok(
        api.mock.calls.every(
          ({ arguments: [endpoint] }) => endpoint.method === "GET",
        ),
      );
    },
  );

  await suite.test(
    "closing an active year requires confirmation and refreshes the workspace as read-only",
    async (t) => {
      const { element, api, button, click } = await mount(t, {
        initialYear: "active",
      });
      await click(button("Close year"));
      assert.match(
        document.querySelector("[role='dialog']").textContent,
        /read-only/,
      );
      await click(button("Cancel", document.querySelector("[role='dialog']")));
      assert.ok(
        api.mock.calls.every(
          ({ arguments: [endpoint] }) => endpoint.method === "GET",
        ),
      );
      await click(button("Close year"));
      await click(
        button("Close year", document.querySelector("[role='dialog']")),
      );
      const call = api.mock.calls.find(({ arguments: [endpoint] }) =>
        endpoint.path.endsWith("/close/"),
      );
      assert.equal(call.arguments[1].year_id, "active");
      assert.match(
        element.querySelector(".ay-state-note").textContent,
        /This year is closed/,
      );
      assert.equal(element.querySelector(".ay-event-actions"), null);
    },
  );

  await suite.test(
    "event deletion identifies its target and only happens after confirmation",
    async (t) => {
      const { element, api, button, click } = await mount(t, {
        initialYear: "active",
      });
      await click(
        element.querySelector('[aria-label="Delete event · Winter holiday"]'),
      );
      assert.match(
        document.querySelector("[role='dialog']").textContent,
        /Winter holiday/,
      );
      await click(button("Cancel", document.querySelector("[role='dialog']")));
      assert.ok(
        api.mock.calls.every(
          ({ arguments: [endpoint] }) => endpoint.method === "GET",
        ),
      );
      await click(
        element.querySelector('[aria-label="Delete event · Winter holiday"]'),
      );
      await click(
        button("Delete event", document.querySelector("[role='dialog']")),
      );
      const call = api.mock.calls.find(
        ({ arguments: [endpoint] }) => endpoint.method === "DELETE",
      );
      assert.deepEqual(call.arguments[1], {
        year_id: "active",
        entry_id: "holiday",
      });
      assert.doesNotMatch(
        element.querySelector(".ay-events").textContent,
        /Winter holiday/,
      );
    },
  );

  await suite.test(
    "new years are created as drafts and become the selected workspace",
    async (t) => {
      const { element, api, button, click, change, submit, onYearChange } =
        await mount(t);
      await click(button("Create academic year"));
      const dialog = document.querySelector("[role='dialog']");
      await change(dialog.querySelector("input[type=text]"), "2028–2029");
      const dates = dialog.querySelectorAll("input[type=date]");
      await change(dates[0], "2028-09-01");
      await change(dates[1], "2029-06-30");
      await submit();
      assert.match(
        element.querySelector(".ay-year-title").textContent,
        /2028–2029.*Draft/,
      );
      assert.equal(onYearChange.mock.calls.at(-1).arguments[0], "new-year");
      assert.ok(
        api.mock.calls.some(
          ({ arguments: [endpoint, params] }) =>
            endpoint.path.endsWith("/calendar/") &&
            params.year_id === "new-year",
        ),
      );
    },
  );

  await suite.test(
    "a readiness failure cannot enable publication and its retry recovers",
    async (t) => {
      let fail = true;
      const { element, button, click } = await mount(t, {
        read(endpoint) {
          if (endpoint.path.endsWith("/readiness/") && fail)
            throw new Error("Readiness unavailable");
        },
      });
      assert.equal(button("Publish year").disabled, true);
      assert.match(
        element.querySelector("[role='alert']").textContent,
        /Readiness unavailable/,
      );
      fail = false;
      await click(button("Check readiness"));
      assert.doesNotMatch(element.textContent, /Readiness unavailable/);
      assert.match(
        element.querySelector(".ay-blockers").textContent,
        /At least one calendar term is required/,
      );
    },
  );

  await suite.test(
    "switching years discards late calendar responses and prefills edits for the selected year",
    async (t) => {
      let resolveDraft;
      const pending = new Promise((resolve) => {
        resolveDraft = resolve;
      });
      const { element, button, click, change, submit, api } = await mount(t, {
        read(endpoint, params) {
          if (
            endpoint.path.endsWith("/calendar/") &&
            params.year_id === "draft"
          )
            return pending;
        },
      });
      await click(
        [...element.querySelectorAll(".ay-year-option")].find((node) =>
          node.textContent.includes("2026–2027"),
        ),
      );
      await act(async () =>
        resolveDraft({
          entries: [
            {
              id: "wrong",
              title: "Wrong year event",
              entry_type: "term",
              starts_on: "2027-09-01",
              ends_on: "2027-12-31",
            },
          ],
        }),
      );
      assert.match(
        element.querySelector(".ay-events").textContent,
        /First semester/,
      );
      assert.doesNotMatch(element.textContent, /Wrong year event/);
      assert.equal(
        element.querySelector('a[href="/classrooms?year_id=active"]')
          .textContent,
        "View classes",
      );
      await click(button("Edit year"));
      assert.equal(
        document.querySelector("[role='dialog'] input[type=text]").value,
        "2026–2027",
      );
      await change(
        document.querySelector("[role='dialog'] input[type=text]"),
        "Current school year",
      );
      await submit();
      const call = api.mock.calls.find(
        ({ arguments: [endpoint] }) => endpoint.method === "PUT",
      );
      assert.equal(call.arguments[1].year_id, "active");
      assert.match(
        element.querySelector(".ay-year-title").textContent,
        /Current school year/,
      );
    },
  );
});
