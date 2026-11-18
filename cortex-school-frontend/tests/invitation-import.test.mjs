import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import { ApiContext, findEndpoint } from "../src/api.tsx";
import { endpointUrl } from "../src/lib.mjs";
import { InvitationCsvImport } from "../src/invitation-import.tsx";
import { Operation } from "../src/ui.tsx";

const modes = ["school_admin", "teacher", "guardian", "mixed"];
const result = {
  created_count: 1,
  updated_count: 0,
  queued_count: 1,
  skipped_count: 0,
  failed_count: 0,
  invitations: [
    {
      id: "invitation-1",
      email: "person@example.com",
      role_slug: "teacher",
      send_status: "queued",
    },
  ],
};

test("CSV endpoint carries the selected role mode in the query", () => {
  const endpoint = findEndpoint("POST", "/invitations/upload/");
  assert.deepEqual(
    endpoint.params.find((param) => param.name === "role_mode").enum,
    modes,
  );
  for (const mode of modes)
    assert.equal(
      endpointUrl("/api", endpoint, { role_mode: mode }),
      `/api/invitations/upload/?role_mode=${mode}`,
    );
});

test("invitation CSV import", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/invitations",
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

  async function mount(
    t,
    implementation = async () => result,
    workflow = false,
  ) {
    const api = t.mock.fn(implementation),
      onDone = t.mock.fn(),
      onClose = t.mock.fn();
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    t.after(async () => {
      await act(async () => root.unmount());
      element.remove();
    });
    const component = workflow ? Operation : InvitationCsvImport;
    const props = {
      onDone,
      onClose,
      ...(workflow
        ? { endpoint: findEndpoint("POST", "/invitations/upload/") }
        : {}),
    };
    await act(async () =>
      root.render(
        createElement(
          MemoryRouter,
          null,
          createElement(
            ApiContext.Provider,
            { value: api },
            createElement(component, props),
          ),
        ),
      ),
    );
    return {
      dialog: document.querySelector("[role='dialog']"),
      api,
      onDone,
      onClose,
    };
  }

  async function chooseFile(dialog) {
    const file = new dom.window.File(
      ["email\nperson@example.com\n"],
      "people.csv",
      { type: "text/csv" },
    );
    const input = dialog.querySelector("input[type='file']");
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [file],
    });
    await act(async () =>
      input.dispatchEvent(new dom.window.Event("change", { bubbles: true })),
    );
    return file;
  }

  await suite.test(
    "requires an explicit choice and exposes all four modes through All workflows",
    async (t) => {
      const { dialog, api } = await mount(t, undefined, true);
      assert.deepEqual(
        [...dialog.querySelectorAll("input[type='radio']")].map(
          (input) => input.value,
        ),
        modes,
      );
      assert.equal(dialog.querySelector("input:checked"), null);
      assert.equal(dialog.querySelector("input[type='file']"), null);
      assert.equal(
        dialog.querySelector("button[type='submit']").disabled,
        true,
      );
      assert.equal(api.mock.callCount(), 0);
    },
  );

  for (const mode of modes)
    await suite.test(
      `submits ${mode} with the CSV and shows queue status`,
      async (t) => {
        const { dialog, api, onDone } = await mount(t);
        await act(async () =>
          dialog.querySelector(`input[value='${mode}']`).click(),
        );
        assert.match(
          dialog.textContent,
          mode === "mixed"
            ? /Required columns: email, role_slug/
            : /Required column: email/,
        );
        assert.match(
          dialog.textContent,
          mode === "mixed"
            ? /Every row must have a valid role_slug/
            : /Any role_slug values in the CSV are ignored/,
        );
        assert.equal(
          dialog.querySelector("button[type='submit']").disabled,
          true,
        );
        const file = await chooseFile(dialog);
        assert.equal(
          api.mock.callCount(),
          0,
          "choosing a file does not send it yet",
        );
        assert.equal(
          dialog.querySelector("button[type='submit']").disabled,
          false,
        );
        await act(async () =>
          dialog
            .querySelector("form")
            .dispatchEvent(
              new dom.window.Event("submit", {
                bubbles: true,
                cancelable: true,
              }),
            ),
        );
        assert.equal(api.mock.callCount(), 1);
        const [endpoint, params, body, sentFile] = api.mock.calls[0].arguments;
        assert.equal(endpoint.id, "upload_invitations");
        assert.deepEqual(params, { role_mode: mode });
        assert.equal(body, undefined);
        assert.equal(sentFile, file);
        assert.equal(onDone.mock.callCount(), 1);
        assert.match(dialog.textContent, /CSV import complete/);
        assert.match(dialog.textContent, /Queued to send/);
        assert.match(
          dialog.textContent,
          /Invitations are sent in the background/,
        );
        assert.match(
          dialog.querySelector("tbody").textContent,
          /person@example.com.*Teacher.*Queued/,
        );
        await act(async () =>
          [...dialog.querySelectorAll("button")]
            .find((button) => button.textContent === "Import another CSV")
            .click(),
        );
        assert.equal(dialog.querySelector("input:checked"), null);
        assert.equal(
          dialog.querySelector("button[type='submit']").disabled,
          true,
        );
      },
    );

  await suite.test(
    "keeps the file and selected mode when validation fails so the admin can retry",
    async (t) => {
      let fail = true;
      const { dialog, api, onDone } = await mount(t, async () => {
        if (fail) throw new Error("Mixed imports require a role_slug column.");
        return result;
      });
      await act(async () =>
        dialog.querySelector("input[value='mixed']").click(),
      );
      const file = await chooseFile(dialog);
      await act(async () =>
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      assert.match(
        dialog.querySelector("[role='alert']").textContent,
        /Mixed imports require a role_slug column/,
      );
      assert.equal(onDone.mock.callCount(), 0);
      assert.equal(dialog.querySelector("input:checked").value, "mixed");
      assert.equal(
        dialog.querySelector("button[type='submit']").disabled,
        false,
      );
      fail = false;
      await act(async () =>
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      assert.equal(api.mock.calls[1].arguments[3], file);
      assert.equal(onDone.mock.callCount(), 1);
    },
  );
});
