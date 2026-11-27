import { test } from "node:test";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import { ApiContext } from "../src/api.tsx";
import {
  InvitationsPage,
  invitationState,
  canRetryInvitation,
  invitationRefreshMs,
} from "../src/invitations.tsx";
import { invitationCsvTemplate } from "../src/invitation-import.tsx";

const tomorrow = new Date(Date.now() + 86400000).toISOString();
const yesterday = new Date(Date.now() - 86400000).toISOString();
const fixture = (id, props = {}) => ({
  id,
  email: `${id}@example.test`,
  first_name: id,
  last_name: "Ben Ali",
  role_slug: "teacher",
  send_status: "sent",
  workos_state: "pending",
  expires_at: tomorrow,
  created_at: "2026-10-01T09:00:00Z",
  updated_at: "2026-10-01T09:00:00Z",
  sent_at: "2026-10-01T09:00:00Z",
  attempt_count: 1,
  error_message: null,
  ...props,
});
const records = [
  fixture("Amira"),
  fixture("Sana", {
    role_slug: "guardian",
    workos_state: "accepted",
    expires_at: yesterday,
  }),
  fixture("Mohamed", {
    role_slug: "school_admin",
    send_status: "failed",
    error_message: "Email delivery was unavailable",
  }),
  fixture("Leila", {
    send_status: "queued",
    workos_state: null,
    expires_at: null,
  }),
  fixture("Nadia", { role_slug: "guardian", expires_at: yesterday }),
];
test("invitation lifecycle separates acceptance, sending, failures and expiration", () => {
  assert.equal(invitationState(records[0]).group, "awaiting");
  assert.equal(
    invitationState(records[1]).group,
    "accepted",
    "acceptance wins over expired timestamps",
  );
  assert.equal(invitationState(records[2]).group, "attention");
  assert.equal(invitationState(records[3]).group, "sending");
  assert.equal(invitationState(records[4]).title, "Invitation expired");
  assert.equal(
    invitationState(fixture("revoked", { workos_state: "revoked" })).title,
    "Invitation revoked",
  );
  assert.equal(
    invitationState(fixture("bad-date", { expires_at: "invalid" })).group,
    "awaiting",
  );
  assert.equal(canRetryInvitation(records[1]), false);
  assert.equal(canRetryInvitation(records[3]), false);
  assert.equal(
    canRetryInvitation(fixture("processing", { send_status: "processing" })),
    false,
  );
  assert.equal(canRetryInvitation(records[2]), true);
});
test("downloadable invitation templates match the selected import mode", () => {
  for (const role of ["guardian", "teacher", "school_admin"])
    assert.equal(
      invitationCsvTemplate(role),
      "\uFEFFemail,first_name,last_name\r\n",
    );
  assert.equal(
    invitationCsvTemplate("mixed"),
    "\uFEFFemail,first_name,last_name,role_slug\r\n",
  );
});
test("administrator invitation workspace", async (suite) => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/invitations",
    pretendToBeVisual: true,
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
    const data = structuredClone(options.data ?? records);
    const api = t.mock.fn(async (endpoint, params = {}, body) => {
      const override = await options.read?.(endpoint, params, body);
      if (override !== undefined) return override;
      if (endpoint.method === "GET" && endpoint.path === "/invitations/")
        return [...data];
      if (endpoint.method === "GET")
        return data.find((item) => item.id === params.invitation_id);
      if (endpoint.path.includes("/retry/")) {
        const index = data.findIndex(
          (item) => item.id === params.invitation_id,
        );
        data[index] = {
          ...data[index],
          send_status: "queued",
          workos_state: null,
          expires_at: null,
        };
        return data[index];
      }
      if (endpoint.method === "POST") {
        const created = fixture("new-invitation", {
          ...body,
          send_status: "queued",
          workos_state: null,
          expires_at: null,
        });
        data.push(created);
        return created;
      }
      throw Error(`Unexpected endpoint ${endpoint.path}`);
    });
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    t.after(async () => {
      await act(async () => root.unmount());
      container.remove();
    });
    await act(async () =>
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: [options.path ?? "/invitations"] },
          createElement(
            ApiContext.Provider,
            { value: api },
            createElement(InvitationsPage, {
              getAccessToken: options.getAccessToken,
            }),
          ),
        ),
      ),
    );
    const click = async (button) => {
      assert.ok(button);
      await act(async () => button.click());
    };
    const change = async (input, value) => {
      await act(async () => {
        const proto =
          input.tagName === "SELECT"
            ? dom.window.HTMLSelectElement.prototype
            : dom.window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, "value").set.call(input, value);
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
        input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
    };
    const button = (text, base = container) =>
      [...base.querySelectorAll("button")].find(
        (item) => item.textContent.trim() === text,
      );
    return { container, root, api, data, click, change, button };
  }
  await suite.test(
    "one list request renders readable states and only valid resend actions",
    async (t) => {
      const { container, api } = await mount(t);
      assert.equal(api.mock.callCount(), 1);
      assert.equal(container.querySelectorAll("tbody tr").length, 5);
      assert.match(container.textContent, /Awaiting acceptance/);
      assert.match(container.textContent, /Joined the school/);
      assert.match(container.textContent, /Invitation expired/);
      assert.doesNotMatch(
        container.textContent,
        /workos_|celery_|get_invitations|school_admin/,
      );
      assert.equal(
        container.querySelectorAll("button[aria-label^='Resend invitation to']")
          .length,
        3,
      );
      assert.deepEqual(
        [...container.querySelectorAll(".iv-summary strong")].map(
          (el) => el.textContent,
        ),
        ["5", "1", "1", "2"],
      );
    },
  );
  await suite.test(
    "name search and role/status filters stay local and preserve school-wide counts",
    async (t) => {
      const { container, api, change } = await mount(t, {
        path: "/invitations?role=guardian",
      });
      assert.equal(container.querySelectorAll("tbody tr").length, 2);
      await change(container.querySelector("input[type=search]"), "nadia");
      assert.equal(container.querySelectorAll("tbody tr").length, 1);
      assert.match(container.querySelector("tbody").textContent, /Nadia/);
      await change(
        container.querySelector(
          "select[aria-label='Filter invitation statuses']",
        ),
        "attention",
      );
      assert.equal(container.querySelectorAll("tbody tr").length, 1);
      assert.equal(
        container.querySelector(".iv-summary strong").textContent,
        "5",
      );
      assert.equal(api.mock.callCount(), 1);
    },
  );
  await suite.test(
    "invitations paginate and filtering resets to the first page",
    async (t) => {
      const { container, click, change } = await mount(t, {
        data: Array.from({ length: 27 }, (_, index) =>
          fixture(`Person${index}`),
        ),
      });
      assert.equal(container.querySelectorAll("tbody tr").length, 12);
      await click(container.querySelector("button[aria-label='Next page']"));
      assert.match(
        container.querySelector(".iv-pagination").textContent,
        /13–24 of 27/,
      );
      await change(container.querySelector("input[type=search]"), "Person26");
      assert.equal(container.querySelectorAll("tbody tr").length, 1);
      assert.equal(
        container.querySelector("button[aria-label='Previous page']").disabled,
        true,
      );
    },
  );
  await suite.test(
    "role shortcuts prefill a clear invitation form and create the chosen role",
    async (t) => {
      const { container, api, click, change, button } = await mount(t);
      await click([...container.querySelectorAll(".iv-quick-roles button")][0]);
      const dialog = document.querySelector("[role=dialog]");
      assert.equal(
        dialog.querySelector("input[type=radio]:checked").value,
        "teacher",
      );
      await change(
        dialog.querySelector("input[name=email]"),
        "  TEACHER@example.test ",
      );
      await change(dialog.querySelector("input[name=first_name]"), "  Ines ");
      await act(async () =>
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      const request = api.mock.calls.find(
        (call) => call.arguments[0].method === "POST",
      );
      assert.deepEqual(request.arguments[2], {
        email: "teacher@example.test",
        role_slug: "teacher",
        first_name: "Ines",
        last_name: null,
      });
      assert.equal(document.querySelector("[role=dialog]"), null);
      assert.match(
        container.querySelector("[role=status]").textContent,
        /queued/,
      );
      assert.ok(button("Invite a person"));
    },
  );
  await suite.test(
    "a failed create preserves the entered person and allows correction",
    async (t) => {
      const { click, change, button } = await mount(t, {
        read: (endpoint) => {
          if (endpoint.method === "POST")
            throw Error("This email has a different role");
        },
      });
      await click(button("Invite a person"));
      const dialog = document.querySelector("[role=dialog]");
      assert.equal(dialog.querySelector("input:checked"), null);
      await click(dialog.querySelector("input[value=guardian]"));
      await change(
        dialog.querySelector("input[name=email]"),
        "family@example.test",
      );
      await act(async () =>
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      assert.equal(
        dialog.querySelector("input[name=email]").value,
        "family@example.test",
      );
      assert.match(
        dialog.querySelector("[role=alert]").textContent,
        /different role/,
      );
    },
  );
  await suite.test(
    "resending loads fresh detail, requires confirmation and targets only that invitation",
    async (t) => {
      const { container, api, click, button } = await mount(t);
      await click(
        container.querySelector(
          "button[aria-label='Resend invitation to Mohamed@example.test']",
        ),
      );
      assert.equal(
        api.mock.calls.filter((call) => call.arguments[0].method === "POST")
          .length,
        0,
      );
      const dialog = document.querySelector("[role=dialog]");
      assert.match(dialog.textContent, /Send another invitation/);
      await click(button("Confirm resend", dialog));
      const request = api.mock.calls.find(
        (call) => call.arguments[0].method === "POST",
      );
      assert.equal(
        request.arguments[0].path,
        "/invitations/{invitation_id}/retry/",
      );
      assert.deepEqual(request.arguments[1], { invitation_id: "Mohamed" });
      assert.equal(document.querySelector("[role=dialog]"), null);
    },
  );
  await suite.test(
    "a newly accepted or processing invitation cannot be resent from a stale row",
    async (t) => {
      const { container, api, click } = await mount(t, {
        read: (endpoint) =>
          endpoint.path === "/invitations/{invitation_id}/"
            ? fixture("Mohamed", { workos_state: "accepted" })
            : undefined,
      });
      await click(
        container.querySelector(
          "button[aria-label='Resend invitation to Mohamed@example.test']",
        ),
      );
      const dialog = document.querySelector("[role=dialog]");
      assert.match(dialog.textContent, /accepted their invitation/);
      assert.equal(
        [...dialog.querySelectorAll("button")].some(
          (button) => button.textContent === "Confirm resend",
        ),
        false,
      );
      assert.equal(
        api.mock.calls.filter((call) => call.arguments[0].method === "POST")
          .length,
        0,
      );
    },
  );
  await suite.test(
    "list failures leave counts unknown and keep inviting/importing available",
    async (t) => {
      const { container, button } = await mount(t, {
        read: () => {
          throw Error("School service unavailable");
        },
      });
      assert.deepEqual(
        [...container.querySelectorAll(".iv-summary strong")].map(
          (el) => el.textContent,
        ),
        ["—", "—", "—", "—"],
      );
      assert.match(
        container.querySelector("[role=alert]").textContent,
        /unavailable/,
      );
      assert.ok(button("Invite a person"));
      assert.ok(button("Import CSV"));
    },
  );
  await suite.test(
    "the CSV import remains directly accessible with all four role modes",
    async (t) => {
      const { click, button } = await mount(t);
      await click(button("Import CSV"));
      const dialog = document.querySelector("[role=dialog]");
      assert.equal(dialog.querySelectorAll("input[type=radio]").length, 4);
      await click(dialog.querySelector("input[value=mixed]"));
      assert.ok(button("Download CSV template", dialog));
    },
  );
  await suite.test(
    "automatic refresh shows a newly accepted invitation without losing filters or focus",
    async (t) => {
      let tick;
      t.mock.method(window, "setInterval", (callback, delay) => {
        assert.equal(delay, invitationRefreshMs);
        tick = callback;
        return 12345;
      });
      const { container, data, api, change } = await mount(t, {
        path: "/invitations?role=teacher",
      });
      const search = container.querySelector("input[type=search]");
      await change(search, "Amira");
      await act(async () => search.focus());
      data[0] = { ...data[0], workos_state: "accepted" };
      await act(async () => tick());
      assert.equal(api.mock.callCount(), 2);
      assert.equal(container.querySelectorAll("tbody tr").length, 1);
      assert.match(
        container.querySelector("tbody").textContent,
        /Joined the school/,
      );
      assert.equal(
        container.querySelector(
          "button[aria-label='Resend invitation to Amira@example.test']",
        ),
        null,
      );
      assert.equal(
        container.querySelector("select[aria-label='Filter invitation roles']")
          .value,
        "teacher",
      );
      assert.equal(search.value, "Amira");
      assert.equal(document.activeElement === search, true);
    },
  );
  await suite.test(
    "hidden pages pause refresh and returning to the tab updates immediately",
    async (t) => {
      let tick;
      let visibility = "visible";
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => visibility,
      });
      t.after(() => {
        delete document.visibilityState;
      });
      t.mock.method(window, "setInterval", (callback) => {
        tick = callback;
        return 12345;
      });
      const { api, data } = await mount(t);
      visibility = "hidden";
      await act(async () => {
        tick();
        window.dispatchEvent(new window.Event("focus"));
      });
      assert.equal(api.mock.callCount(), 1);
      data[0] = { ...data[0], workos_state: "accepted" };
      visibility = "visible";
      await act(async () =>
        document.dispatchEvent(new window.Event("visibilitychange")),
      );
      assert.equal(api.mock.callCount(), 2);
      await act(async () => window.dispatchEvent(new window.Event("focus")));
      assert.equal(api.mock.callCount(), 3);
    },
  );
  await suite.test(
    "background refresh never overlaps a request and cleans up on navigation",
    async (t) => {
      let tick, finish;
      let lists = 0;
      t.mock.method(window, "setInterval", (callback) => {
        tick = callback;
        return 12345;
      });
      const cleared = t.mock.method(window, "clearInterval");
      const { root, api, data } = await mount(t, {
        read: (endpoint) => {
          if (endpoint.path === "/invitations/" && ++lists === 2)
            return new Promise((resolve) => {
              finish = resolve;
            });
        },
      });
      await act(async () => tick());
      await act(async () => {
        tick();
        window.dispatchEvent(new window.Event("focus"));
      });
      assert.equal(api.mock.callCount(), 2);
      await act(async () => finish([...data]));
      await act(async () => root.render(null));
      await act(async () => window.dispatchEvent(new window.Event("focus")));
      assert.equal(api.mock.callCount(), 2);
      assert.equal(
        cleared.mock.calls.some((call) => call.arguments[0] === 12345),
        true,
      );
    },
  );
  await suite.test(
    "live events trigger a follow-up refresh and polling resumes on disconnect",
    async (t) => {
      const connections = [];
      class TestSocket {
        static OPEN = 1;
        readyState = 0;
        constructor(url) {
          this.url = url.href;
          connections.push(this);
        }
        open() {
          this.readyState = TestSocket.OPEN;
          return this.onopen();
        }
        send(token) {
          this.token = token;
        }
        event(type) {
          this.onmessage({ data: JSON.stringify({ type }) });
        }
        close() {
          this.readyState = 3;
          this.onclose?.();
        }
      }
      const originalWebSocket = window.WebSocket;
      window.WebSocket = TestSocket;
      t.after(() => {
        window.WebSocket = originalWebSocket;
      });
      const poll = t.mock.method(window, "setInterval", () => 12345);
      const timeout = window.setTimeout.bind(window);
      let reconnect;
      t.mock.method(window, "setTimeout", (callback, delay) => {
        if (delay !== 1000) return timeout(callback, delay);
        reconnect = callback;
        return 23456;
      });

      let finish,
        lists = 0;
      const { api, container, data, root } = await mount(t, {
        getAccessToken: async () => "workos-token",
        read: () => {
          if (++lists === 2)
            return new Promise((resolve) => {
              finish = resolve;
            });
        },
      });
      const first = connections[0];
      assert.equal(first.url, "ws://localhost/api/invitations/ws");
      await act(async () => first.open());
      assert.equal(first.token, "workos-token");
      await act(async () => first.event("invitations.ready"));
      assert.equal(poll.mock.calls.at(-1).arguments[1], 60000);

      const previous = [...data];
      data[0] = { ...data[0], workos_state: "accepted" };
      await act(async () => first.event("invitations.changed"));
      assert.equal(api.mock.callCount(), 2);
      await act(async () => finish(previous));
      assert.equal(api.mock.callCount(), 3);
      const updated = [...container.querySelectorAll("tbody tr")].find((row) =>
        row.textContent.includes("Amira"),
      );
      assert.match(updated.textContent, /Joined the school/);

      await act(async () => first.close());
      const [pollNow, pollDelay] = poll.mock.calls.at(-1).arguments;
      assert.equal(pollDelay, invitationRefreshMs);
      await act(async () => pollNow());
      assert.equal(api.mock.callCount(), 4);

      await act(async () => reconnect());
      const second = connections[1];
      await act(async () => second.open());
      await act(async () => second.event("invitations.ready"));
      assert.equal(api.mock.callCount(), 5);
      await act(async () => root.render(null));
      assert.equal(second.readyState, 3);
    },
  );
  await suite.test(
    "a failed automatic sync keeps cached rows and reports the failure",
    async (t) => {
      let tick;
      let unavailable = false;
      t.mock.method(window, "setInterval", (callback) => {
        tick = callback;
        return 12345;
      });
      const { container } = await mount(t, {
        read: () => {
          if (unavailable)
            throw Error(
              "Invitation status could not be synchronized. Please try again.",
            );
        },
      });
      unavailable = true;
      await act(async () => tick());
      assert.equal(container.querySelectorAll("tbody tr").length, 5);
      assert.match(
        container.querySelector("[role=alert]").textContent,
        /could not be synchronized/,
      );
      assert.match(container.textContent, /Showing the last available results/);
    },
  );
});
