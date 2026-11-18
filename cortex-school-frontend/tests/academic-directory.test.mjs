import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ApiContext } from "../src/api.tsx";
import {
  AcademicDirectoryPage,
  studentDirectoryCsv,
} from "../src/academic-directory.tsx";
import {
  directoryFixture,
  oldDirectoryFixture,
  directoryYears,
  directoryMembers,
} from "./fixtures/academic-directory.mjs";

test("student CSV preserves rates and leaves missing history unset", () => {
  const csv = studentDirectoryCsv(directoryFixture.students, directoryFixture);
  assert.match(csv, /"Yasmine Ben Ali","2026–2027","6A","95.0%","20"/);
  assert.match(csv, /"Adam Trabelsi","2026–2027","6A","","0"/);
  assert.doesNotMatch(csv, /student-1|enrollment-1/);
});

test("academic directories", async (suite) => {
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
  function Location() {
    const location = useLocation();
    return createElement("output", null, location.pathname + location.search);
  }
  async function mount(
    t,
    mode = "classrooms",
    path = `/${mode}`,
    fetchDirectory = (year) =>
      year === "year-old" ? oldDirectoryFixture : directoryFixture,
  ) {
    const api = t.mock.fn(async (endpoint, params) => {
      assert.equal(endpoint.path, "/academic-years/{year_id}/directory/");
      return fetchDirectory(params.year_id);
    });
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    const onYearChange = t.mock.fn();
    t.after(async () => {
      await act(async () => root.unmount());
      element.remove();
    });
    await act(async () =>
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: [path] },
          createElement(
            ApiContext.Provider,
            { value: api },
            createElement(AcademicDirectoryPage, {
              mode,
              years: { data: directoryYears, loading: false, error: "" },
              initialYear: "year-current",
              onYearChange,
              members: { data: directoryMembers, loading: false, error: "" },
            }),
            createElement(Location),
          ),
        ),
      ),
    );
    const button = (text, parent = element) =>
      [...parent.querySelectorAll("button")].find(
        (entry) => entry.textContent === text,
      );
    return { element, api, button, onYearChange };
  }

  await suite.test(
    "class cards show teachers and counts, and open the correct roster without extra API calls",
    async (t) => {
      const { element, api } = await mount(t);
      assert.equal(element.querySelectorAll(".ad-class-card").length, 3);
      const card = element.querySelector(".ad-class-card");
      assert.match(
        card.textContent,
        /6A.*Salma Mansour.*Mehdi Trabelsi.*2 students/,
      );
      await act(async () => card.querySelector("button").click());
      const dialog = document.querySelector("[role='dialog']");
      assert.match(
        dialog.textContent,
        /Teaching team.*Salma Mansour.*Lead teacher.*Mehdi Trabelsi.*Assistant teacher/,
      );
      assert.match(dialog.textContent, /Yasmine Ben Ali/);
      assert.match(dialog.textContent, /Adam Trabelsi/);
      assert.doesNotMatch(
        dialog.textContent,
        /Lina Haddad|user_salma|enrollment-1/,
      );
      assert.equal(api.mock.callCount(), 1);
    },
  );

  await suite.test(
    "year selection requests that year, clears the open class, and makes historical data read-only",
    async (t) => {
      const { element, api, onYearChange } = await mount(
        t,
        "classrooms",
        "/classrooms?classroom_id=class-6a",
      );
      assert.ok(document.querySelector("[role='dialog']"));
      await act(async () => {
        const select = element.querySelector(
          "select[aria-label='Academic year']",
        );
        select.value = "year-old";
        select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
      assert.equal(api.mock.calls.at(-1).arguments[1].year_id, "year-old");
      assert.equal(onYearChange.mock.calls[0].arguments[0], "year-old");
      assert.equal(document.querySelector("[role='dialog']"), null);
      assert.match(element.querySelector(".ad-class-card").textContent, /5A/);
      assert.doesNotMatch(element.textContent, /Salma Mansour/);
      assert.equal(
        [...element.querySelectorAll("button")].find(
          (entry) => entry.textContent === "Create classroom",
        ).disabled,
        true,
      );
      assert.match(
        element.querySelector(".ad-roster-date").textContent,
        /30 Jun 2026/,
      );
    },
  );

  await suite.test(
    "students show honest rates and direct year-specific class links",
    async (t) => {
      const { element, api } = await mount(t, "students");
      const rows = [...element.querySelectorAll("tbody tr")];
      const yasmine = rows.find((row) => row.textContent.includes("Yasmine"));
      const adam = rows.find((row) => row.textContent.includes("Adam"));
      assert.match(yasmine.textContent, /95%.*19 of 20 days/);
      assert.equal(
        yasmine.querySelector("a").getAttribute("href"),
        "/classrooms?year_id=year-current&classroom_id=class-6a",
      );
      assert.match(adam.textContent, /—No attendance records yet/);
      assert.doesNotMatch(adam.textContent, /0%/);
      assert.match(element.textContent, /Awaiting class placement/);
      assert.match(element.textContent, /Not enrolled this year/);
      assert.equal(
        api.mock.callCount(),
        1,
        "one bulk request rather than per-student attendance requests",
      );
    },
  );

  await suite.test(
    "student profiles open their class and preserve edit, guardian and enrollment actions",
    async (t) => {
      const { element, button } = await mount(
        t,
        "students",
        "/students?year_id=year-current&student_id=student-1",
      );
      const dialog = document.querySelector("[role='dialog']");
      assert.match(
        dialog.textContent,
        /Yasmine Ben Ali.*Attendance this academic year.*95%/,
      );
      assert.equal(
        dialog.querySelector("a").getAttribute("href"),
        "/classrooms?year_id=year-current&classroom_id=class-6a",
      );
      await act(async () => button("Edit student", dialog).click());
      const operation = document.querySelector("[role='dialog']");
      assert.match(operation.textContent, /Yasmine Ben Ali/);
      assert.equal(operation.querySelector("input").value, "Yasmine");
      assert.doesNotMatch(operation.textContent, /Student Id/);
    },
  );

  await suite.test(
    "class filtering and name search stay local and attendance sorting keeps missing rates last",
    async (t) => {
      const { element, api } = await mount(t, "students");
      await act(async () => {
        const select = element.querySelector(
          "select[aria-label='Filter students by class']",
        );
        select.value = "class-6a";
        select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
      assert.equal(element.querySelectorAll("tbody tr").length, 2);
      await act(async () => {
        const select = element.querySelector(
          "select[aria-label='Sort students']",
        );
        select.value = "attendance";
        select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
      assert.match(element.querySelector("tbody tr").textContent, /Yasmine/);
      const input = element.querySelector("input[type='search']");
      await act(async () => {
        Object.getOwnPropertyDescriptor(
          dom.window.HTMLInputElement.prototype,
          "value",
        ).set.call(input, "ADAM");
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
        input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
      assert.equal(element.querySelectorAll("tbody tr").length, 1);
      assert.match(element.querySelector("tbody tr").textContent, /Adam/);
      assert.equal(api.mock.callCount(), 1);
    },
  );

  await suite.test(
    "class actions prefill the selected class and use student names for enrollment choices",
    async (t) => {
      const { button } = await mount(
        t,
        "classrooms",
        "/classrooms?year_id=year-current&classroom_id=class-6a",
      );
      await act(async () =>
        button(
          "Place student",
          document.querySelector("[role='dialog']"),
        ).click(),
      );
      const operation = document.querySelector("[role='dialog']");
      assert.match(operation.textContent, /6A/);
      assert.match(
        operation.querySelector("select").textContent,
        /Yasmine Ben Ali/,
      );
      assert.doesNotMatch(operation.textContent, /Classroom Id/);
      assert.equal(
        operation.querySelector("input[type='date']").value,
        "2026-11-18",
      );
    },
  );

  await suite.test(
    "a failed directory request has retry and never presents invented zero rates",
    async (t) => {
      let fail = true;
      const { element, api } = await mount(t, "students", "/students", () => {
        if (fail) throw new Error("Directory unavailable");
        return directoryFixture;
      });
      assert.match(
        element.querySelector("[role='alert']").textContent,
        /Directory unavailable/,
      );
      assert.equal(element.querySelector("table"), null);
      fail = false;
      await act(async () =>
        element.querySelector("[role='alert'] button").click(),
      );
      assert.equal(api.mock.callCount(), 2);
      assert.equal(element.querySelectorAll("tbody tr").length, 5);
    },
  );
});
