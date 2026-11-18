import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter, useLocation } from "react-router-dom";
import { membersCsv, SchoolMembersPage } from "../src/school-members.tsx";
import { schoolMembersFixture } from "./fixtures/school-members.mjs";

test("member CSV exports readable roles, includes all results, and escapes spreadsheet formulas", () => {
  const csv = membersCsv([
    ...schoolMembersFixture,
    { ...schoolMembersFixture[0], name: ' =HYPERLINK("https://example.test")' },
  ]);
  assert.equal(csv.split("\r\n").length, 8);
  assert.match(csv, /Teacher; Guardian/);
  assert.match(csv, /"' =HYPERLINK\(""https:\/\/example.test""\)"/);
  assert.doesNotMatch(csv, /membership_|user_admin|school_admin/);
});

test("school member directory", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/members",
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
    return createElement(
      "output",
      { "data-location": true },
      useLocation().search,
    );
  }
  async function mount(t, props = {}, path = "/members") {
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    t.after(async () => {
      await act(async () => root.unmount());
      element.remove();
    });
    const onRefresh = t.mock.fn();
    const render = async (next = {}) =>
      act(async () =>
        root.render(
          createElement(
            MemoryRouter,
            { initialEntries: [path] },
            createElement(SchoolMembersPage, {
              members: schoolMembersFixture,
              loading: false,
              error: "",
              onRefresh,
              ...props,
              ...next,
            }),
            createElement(Location),
          ),
        ),
      );
    await render();
    const rows = () =>
      [...element.querySelectorAll("tbody tr")].map((row) => row.textContent);
    const group = (title) =>
      [...element.querySelectorAll(".sm-groups button")].find((button) =>
        button.textContent.includes(title),
      );
    return { element, rows, group, onRefresh, render };
  }
  async function search(element, value) {
    const input = element.querySelector("input[type='search']");
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLInputElement.prototype,
        "value",
      ).set.call(input, value);
      input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
  }

  await suite.test(
    "keeps names, email and readable roles together without exposing internal IDs",
    async (t) => {
      const { element, rows, group } = await mount(t);
      assert.equal(rows().length, 6);
      assert.equal(group("All members").getAttribute("aria-pressed"), "true");
      assert.equal(
        group("All members").querySelector("strong").textContent,
        "6",
      );
      assert.equal(
        group("Administrators").querySelector("strong").textContent,
        "1",
      );
      assert.equal(group("Teachers").querySelector("strong").textContent, "3");
      assert.equal(group("Guardians").querySelector("strong").textContent, "3");
      assert.match(
        rows()[0],
        /Amira Ben Salem.*amira@example.test.*Administrator.*Active/,
      );
      assert.match(element.textContent, /Members with multiple roles/);
      assert.doesNotMatch(
        element.textContent,
        /membership_|user_admin|school_admin/,
      );
      assert.equal(
        element.querySelector("a[href='/invitations']").textContent,
        "Manage invitations",
      );
    },
  );

  await suite.test(
    "shows each type separately, counting people with several roles in both groups",
    async (t) => {
      const { element, rows, group } = await mount(t);
      await act(async () => group("Teachers").click());
      assert.equal(rows().length, 3);
      assert.ok(rows().every((row) => row.includes("Teacher")));
      assert.match(element.querySelector("output").textContent, /role=teacher/);
      assert.match(
        element.querySelector(".sm-directory-heading").textContent,
        /Teachers3 members/,
      );
      await act(async () => group("Guardians").click());
      assert.equal(rows().length, 3);
      assert.ok(rows().some((row) => row.includes("Salma Mansour")));
      assert.ok(rows().every((row) => row.includes("Guardian")));
      await act(async () => group("Administrators").click());
      assert.equal(rows().length, 1);
      assert.match(rows()[0], /Amira Ben Salem/);
      await act(async () => group("All members").click());
      assert.equal(rows().length, 6);
    },
  );

  await suite.test(
    "restores a shared role filter and searches only that group by name or email",
    async (t) => {
      const { element, rows, group } = await mount(
        t,
        {},
        "/members?role=teacher",
      );
      assert.equal(rows().length, 3);
      await search(element, " EMILIE ");
      assert.equal(rows().length, 1);
      assert.match(rows()[0], /Émilie Laurent/);
      assert.equal(
        group("Teachers").querySelector("strong").textContent,
        "3",
        "counts stay school-wide",
      );
      await search(element, "MEHDI@EXAMPLE");
      assert.equal(rows().length, 1);
      assert.match(rows()[0], /Mehdi Trabelsi/);
      await search(element, "nadia");
      assert.equal(rows().length, 0);
      assert.match(element.textContent, /No matching members/);
      await act(async () =>
        element.querySelector("button[aria-label='Clear search']").click(),
      );
      assert.equal(rows().length, 3);
    },
  );

  await suite.test(
    "paginates and sorts results, then resets the page when the group changes",
    async (t) => {
      const members = Array.from({ length: 23 }, (_, index) => ({
        ...schoolMembersFixture[0],
        id: `user_${index}`,
        membership_id: `membership_${index}`,
        name: `Member ${String(index + 1).padStart(2, "0")}`,
        roles: [index === 22 ? "guardian" : "teacher"],
      }));
      const { element, rows, group } = await mount(t, { members });
      assert.equal(rows().length, 20);
      await act(async () =>
        element.querySelector("button[aria-label='Next members page']").click(),
      );
      assert.equal(rows().length, 3);
      assert.match(
        element.querySelector(".sm-pagination").textContent,
        /Showing 21–23 of 23/,
      );
      await act(async () => group("Guardians").click());
      assert.equal(rows().length, 1);
      assert.equal(
        element.querySelector("button[aria-label='Previous members page']")
          .disabled,
        true,
      );
      await act(async () => group("Teachers").click());
      await act(async () => {
        const select = element.querySelector("select");
        select.value = "desc";
        select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
      assert.match(rows()[0], /Member 22/);
      await search(element, "Member 01");
      assert.equal(rows().length, 1);
      assert.match(rows()[0], /Member 01/);
    },
  );

  await suite.test(
    "keeps role and search selections during refresh, and distinguishes loading, errors and empty groups",
    async (t) => {
      const { element, rows, onRefresh, render } = await mount(
        t,
        {},
        "/members?role=guardian",
      );
      await search(element, "Salma");
      await act(async () =>
        [...element.querySelectorAll("button")]
          .find((button) => button.textContent === "Refresh")
          .click(),
      );
      assert.equal(onRefresh.mock.callCount(), 1);
      assert.equal(rows().length, 1);
      await render({ loading: true });
      assert.ok(element.querySelector("[role='status']"));
      assert.equal(element.querySelector(".sm-groups strong").textContent, "—");
      assert.equal(rows().length, 0);
      await render({ error: "Could not load school members" });
      assert.match(
        element.querySelector("[role='alert']").textContent,
        /Could not load school members/,
      );
      assert.doesNotMatch(element.textContent, /No matching members/);
      await act(async () =>
        element.querySelector("[role='alert'] button").click(),
      );
      assert.equal(onRefresh.mock.callCount(), 2);
      await render();
      assert.match(rows()[0], /Salma/);
      await act(async () =>
        element.querySelector("button[aria-label='Clear search']").click(),
      );
      await render({ members: [schoolMembersFixture[0]] });
      assert.match(element.textContent, /No members in this group yet/);
      await render({ members: [] });
      assert.match(element.textContent, /No school members yet/);
    },
  );
});
