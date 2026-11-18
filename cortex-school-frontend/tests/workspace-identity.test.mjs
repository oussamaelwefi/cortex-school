import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement as h } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import {
  WorkspaceIdentity,
  WorkspaceSwitch,
  WorkspaceWelcome,
  useWorkspaceTheme,
  workspaceProfiles,
} from "../src/workspace-identity.tsx";

test("workspace identity and role-specific home pages", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost",
  });
  const previous = {
    window: globalThis.window,
    document: globalThis.document,
    act: globalThis.IS_REACT_ACT_ENVIRONMENT,
  };
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const { createRoot } = await import("react-dom/client");
  suite.after(() => {
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = previous.act;
    dom.window.close();
  });
  async function mount(t, element) {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => root.render(element));
    t.after(async () => {
      await act(async () => root.unmount());
      container.remove();
    });
    return { container, root };
  }
  await suite.test(
    "identity keeps the role, school and current page visible",
    async (t) => {
      const { container, root } = await mount(
        t,
        h(WorkspaceIdentity, {
          role: "teacher",
          schoolName: "École Les Oliviers",
          page: "My classrooms",
        }),
      );
      assert.match(container.textContent, /Teacher workspace/);
      assert.match(container.textContent, /École Les Oliviers/);
      assert.match(container.textContent, /My classrooms/);
      await act(async () =>
        root.render(
          h(WorkspaceIdentity, {
            role: "guardian",
            schoolName: "École Les Oliviers",
            page: "School policies",
          }),
        ),
      );
      assert.match(container.textContent, /Family workspace/);
      assert.doesNotMatch(container.textContent, /Teacher workspace/);
    },
  );
  await suite.test(
    "workspace switching only offers authorized roles",
    async (t) => {
      const changes = [];
      const { container } = await mount(
        t,
        h(WorkspaceSwitch, {
          role: "teacher",
          roles: ["teacher", "guardian"],
          onChange: (role) => changes.push(role),
        }),
      );
      const select = container.querySelector("select");
      assert.deepEqual(
        [...select.options].map((option) => option.value),
        ["teacher", "guardian"],
      );
      await act(async () => {
        select.value = "guardian";
        select.dispatchEvent(new window.Event("change", { bubbles: true }));
      });
      assert.deepEqual(changes, ["guardian"]);
      await act(async () => {
        select.value = "admin";
        select.dispatchEvent(new window.Event("change", { bubbles: true }));
      });
      assert.deepEqual(changes, ["guardian"]);
    },
  );
  await suite.test(
    "single-role accounts have no misleading workspace selector",
    async (t) => {
      const { container } = await mount(
        t,
        h(WorkspaceSwitch, {
          role: "teacher",
          roles: ["teacher"],
          onChange: () => assert.fail(),
        }),
      );
      assert.equal(container.querySelector("select"), null);
    },
  );
  await suite.test(
    "theme follows role changes and is removed when leaving the workspace",
    async (t) => {
      function Theme({ role }) {
        useWorkspaceTheme(role);
        return null;
      }
      const { root } = await mount(t, h(Theme, { role: "teacher" }));
      assert.equal(document.documentElement.dataset.workspaceRole, "teacher");
      await act(async () => root.render(h(Theme, { role: "guardian" })));
      assert.equal(document.documentElement.dataset.workspaceRole, "guardian");
      await act(async () => root.render(null));
      assert.equal(document.documentElement.dataset.workspaceRole, undefined);
    },
  );
  for (const role of ["admin", "teacher", "guardian"]) {
    await suite.test(
      `${role} home displays its own priorities and primary action`,
      async (t) => {
        const { container } = await mount(
          t,
          h(MemoryRouter, null, h(WorkspaceWelcome, { role, name: "Amira" })),
        );
        assert.equal(
          container.querySelector("h2").textContent,
          workspaceProfiles[role].bannerTitle,
        );
        const action = container.querySelector(".banner-link");
        assert.equal(action.getAttribute("href"), workspaceProfiles[role].href);
        assert.equal(action.textContent.trim(), workspaceProfiles[role].action);
        assert.match(
          container.querySelector(".banner-label").textContent,
          /Amira/,
        );
      },
    );
  }
});
