import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import { ApiContext, findEndpoint } from "../src/api.tsx";
import { AcademicDirectoryPage } from "../src/academic-directory.tsx";
import { SchoolMembersPage } from "../src/school-members.tsx";
import { SchoolSettingsPage } from "../src/school-settings.tsx";
import {
  StudentGuardianContext,
  StudentGuardians,
} from "../src/student-guardians.tsx";
import { DataView, Operation } from "../src/ui.tsx";
import {
  directoryFixture,
  directoryMembers,
  directoryYears,
} from "./fixtures/academic-directory.mjs";
import { schoolMembersFixture } from "./fixtures/school-members.mjs";

const attendanceSettings = {
  timezone: "Africa/Tunis",
  instructional_weekdays: [0, 1, 2, 3, 4],
  attendance_cutoff_time: "10:00:00",
};
const aiSettings = {
  ai_teacher_draft_enabled: true,
  ai_teacher_draft_default_language: "fr",
  ai_guardian_weekly_explanation_enabled: false,
  ai_guardian_weekly_explanation_default_language: "auto",
};
const guardians = {
  enabled: true,
  students: directoryFixture.students,
  members: schoolMembersFixture,
  loading: false,
  error: "",
};

test("admin relationships and school settings", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/settings",
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
  async function mount(t, component, props = {}, source = guardians) {
    const api = t.mock.fn(async (endpoint, params, body) => {
      if (endpoint.path.endsWith("/directory/")) return directoryFixture;
      if (endpoint.path === "/school/attendance-settings")
        return endpoint.method === "PUT" ? body : attendanceSettings;
      if (endpoint.path === "/school/ai-settings") return aiSettings;
      if (endpoint.path === "/ai/chat/access/")
        return {
          school_data_enabled: true,
          personal_data_enabled: true,
          effective_data_enabled: true,
          can_manage_school: true,
          can_manage_personal: false,
          revision: 0,
        };
      throw new Error(`Unexpected endpoint ${endpoint.path}`);
    });
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    t.after(async () => {
      await act(async () => root.unmount());
      element.remove();
    });
    await act(async () =>
      root.render(
        createElement(
          MemoryRouter,
          null,
          createElement(
            ApiContext.Provider,
            { value: api },
            createElement(
              StudentGuardianContext.Provider,
              { value: source },
              createElement(component, props),
            ),
          ),
        ),
      ),
    );
    const button = (text, parent = element) =>
      [...parent.querySelectorAll("button")].find(
        (entry) => entry.textContent === text,
      );
    return { element, api, button };
  }

  await suite.test(
    "student directory and class rosters display linked guardian names without per-row requests",
    async (t) => {
      const { element, api } = await mount(t, AcademicDirectoryPage, {
        mode: "students",
        years: { data: directoryYears, loading: false, error: "" },
        initialYear: "year-current",
        onYearChange: () => {},
        members: { data: directoryMembers, loading: false, error: "" },
      });
      const rows = [...element.querySelectorAll("tbody tr")];
      assert.match(
        rows.find((row) => row.textContent.includes("Yasmine")).textContent,
        /Nadia Ben Ali/,
      );
      assert.match(
        rows.find((row) => row.textContent.includes("Nour")).textContent,
        /No guardian linked/,
      );
      assert.equal(api.mock.callCount(), 1);
      await act(async () =>
        rows
          .find((row) => row.textContent.includes("Yasmine"))
          .querySelector("button")
          .click(),
      );
      const dialog = document.querySelector("[role='dialog']");
      assert.match(dialog.textContent, /Nadia Ben Ali/);
      assert.equal(
        dialog.querySelector("a[href='mailto:nadia@example.test']").textContent,
        "nadia@example.test",
      );
    },
  );

  await suite.test(
    "generic student lists also show guardians and keep internal links out of record details",
    async (t) => {
      const { element } = await mount(t, DataView, {
        endpoint: findEndpoint("GET", "/students/"),
        data: directoryFixture.students,
      });
      assert.ok(
        [...element.querySelectorAll("th")].some(
          (entry) => entry.textContent === "Guardians",
        ),
      );
      assert.match(element.querySelector("tbody").textContent, /Nadia Ben Ali/);
      await act(async () => element.querySelector("tbody button").click());
      assert.match(
        document.querySelector("[role='dialog']").textContent,
        /Nadia Ben Ali/,
      );
      assert.doesNotMatch(
        document.querySelector("[role='dialog']").textContent,
        /user_guardian1/,
      );
    },
  );

  await suite.test(
    "missing guardian profiles and failed link data are never called unlinked",
    async (t) => {
      const { element } = await mount(
        t,
        StudentGuardians,
        { studentId: "student-unknown" },
        { ...guardians, students: null, members: null, error: "Unavailable" },
      );
      assert.match(element.textContent, /Guardian information unavailable/);
      assert.doesNotMatch(element.textContent, /No guardian linked/);
    },
  );

  await suite.test(
    "teacher rows link to their classes and guardian rows link to their children",
    async (t) => {
      const { element } = await mount(t, SchoolMembersPage, {
        members: schoolMembersFixture,
        loading: false,
        error: "",
        onRefresh: () => {},
      });
      const group = (name) =>
        [...element.querySelectorAll(".sm-groups button")].find((entry) =>
          entry.textContent.includes(name),
        );
      await act(async () => group("Teachers").click());
      assert.ok(
        [...element.querySelectorAll("a")].some(
          (entry) =>
            entry.getAttribute("href") ===
            "/classrooms?year_id=year-current&classroom_id=class-6a",
        ),
      );
      assert.match(
        element.querySelector("tbody").textContent,
        /2026–2027.*Lead teacher/,
      );
      await act(async () => group("Guardians").click());
      const row = [...element.querySelectorAll("tbody tr")].find((entry) =>
        entry.textContent.includes("Nadia"),
      );
      assert.match(row.textContent, /Yasmine Ben Ali.*Adam Trabelsi/);
      assert.equal(
        row.querySelector("a[href='/students?student_id=student-1']")
          .textContent,
        "Yasmine Ben Ali",
      );
    },
  );

  await suite.test(
    "settings name all seven weekdays and View AI settings fetches and displays directly",
    async (t) => {
      const { element, api, button } = await mount(t, SchoolSettingsPage);
      assert.equal(api.mock.callCount(), 2);
      const weekdays = [...element.querySelectorAll(".ss-weekdays li")];
      assert.deepEqual(
        weekdays.map((entry) => entry.querySelector("strong").textContent),
        [
          "Monday",
          "Tuesday",
          "Wednesday",
          "Thursday",
          "Friday",
          "Saturday",
          "Sunday",
        ],
      );
      assert.equal(weekdays[0].dataset.instructional, "true");
      assert.equal(weekdays[5].dataset.instructional, "false");
      await act(async () => button("View AI settings").click());
      assert.equal(api.mock.callCount(), 3);
      assert.equal(api.mock.calls[1].arguments[0].method, "GET");
      assert.match(
        element.querySelector("#school-ai-settings").textContent,
        /Teacher update draftsEnabled.*French.*Guardian weekly explanationsDisabled.*Automatic/,
      );
      assert.equal(
        [...element.querySelectorAll("button")].some(
          (entry) => entry.textContent === "Run",
        ),
        false,
      );
      assert.equal(
        api.mock.calls.some(
          ({ arguments: [endpoint] }) => endpoint.method !== "GET",
        ),
        false,
      );
    },
  );

  await suite.test(
    "weekday editing sends the correct numeric values after choosing named days",
    async (t) => {
      const { api, button } = await mount(t, SchoolSettingsPage);
      await act(async () => button("Edit attendance settings").click());
      const dialog = document.querySelector("[role='dialog']");
      const saturday = [...dialog.querySelectorAll(".ss-weekday-field label")]
        .find((entry) => entry.textContent === "Saturday")
        .querySelector("input");
      const monday = [...dialog.querySelectorAll(".ss-weekday-field label")]
        .find((entry) => entry.textContent === "Monday")
        .querySelector("input");
      assert.equal(monday.checked, true);
      assert.equal(saturday.checked, false);
      await act(async () => saturday.click());
      await act(async () =>
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      const put = api.mock.calls.find(
        ({ arguments: [endpoint] }) => endpoint.method === "PUT",
      );
      assert.deepEqual(
        put.arguments[2].instructional_weekdays,
        [0, 1, 2, 3, 4, 5],
      );
      assert.equal(put.arguments[2].timezone, "Africa/Tunis");
    },
  );

  await suite.test(
    "the AI workflow dialog also loads immediately without a Run step",
    async (t) => {
      const { api } = await mount(t, Operation, {
        endpoint: findEndpoint("GET", "/school/ai-settings"),
        onClose: () => {},
        onDone: () => {},
      });
      assert.equal(api.mock.callCount(), 1);
      assert.match(
        document.querySelector("[role='dialog']").textContent,
        /Teacher update draftsEnabled/,
      );
      assert.equal(document.querySelector("[role='dialog'] form"), null);
    },
  );
});
