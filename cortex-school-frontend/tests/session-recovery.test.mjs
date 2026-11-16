import assert from "node:assert/strict";
import { test } from "node:test";
import { setImmediate } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

function rejectedToken(requestId) {
  return Response.json(
    { detail: "Invalid or expired access token" },
    {
      status: 401,
      headers: { "WWW-Authenticate": "Bearer", "X-Request-ID": requestId },
    },
  );
}

test("school API session recovery", async (suite) => {
  const server = await createServer({
    root: fileURLToPath(new URL("..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true },
    server: { middlewareMode: true, hmr: false, watch: null },
  });
  suite.after(() => server.close());
  const { findEndpoint, makeApi } = await server.ssrLoadModule("/src/api.tsx");
  const students = findEndpoint("GET", "/students/");
  const academicYears = findEndpoint("GET", "/academic-years/");
  const chat = findEndpoint("POST", "/ai/chat/");
  const policy = findEndpoint("GET", "/guardian/family/policies/{document_id}/pdf/");

  await suite.test("policy downloads return the original PDF bytes", async (t) => {
    const bytes = new TextEncoder().encode("%PDF-1.7");
    t.mock.method(globalThis, "fetch", async () =>
      new Response(bytes, { headers: { "Content-Type": "application/pdf" } }),
    );
    const api = makeApi(async () => "valid", t.mock.fn());

    const file = await api(policy, { document_id: "pol-1" });
    assert.equal(file.type, "application/pdf");
    assert.deepEqual(new Uint8Array(await file.arrayBuffer()), bytes);
  });

  await suite.test("concurrent Bearer 401s share a refresh", async (t) => {
    let token = "expired";
    const getToken = t.mock.fn(async (forceRefresh) => {
      if (forceRefresh) {
        await setImmediate();
        token = "fresh";
      }
      return token;
    });
    const onSessionRejected = t.mock.fn();
    const fetch = t.mock.method(globalThis, "fetch", async (_url, options) =>
      options.headers.Authorization === "Bearer fresh"
        ? Response.json({ loaded: true })
        : rejectedToken("first-request"),
    );
    const api = makeApi(getToken, onSessionRejected);

    assert.deepEqual(await Promise.all([api(students), api(academicYears)]), [
      { loaded: true },
      { loaded: true },
    ]);
    assert.equal(
      getToken.mock.calls.filter(({ arguments: [force] }) => force).length,
      1,
    );
    assert.equal(fetch.mock.callCount(), 4);
    assert.equal(onSessionRejected.mock.callCount(), 0);
  });

  await suite.test("a second Bearer 401 prompts sign-in", async (t) => {
    const getToken = async (forceRefresh) =>
      forceRefresh ? "fresh" : "expired";
    const onSessionRejected = t.mock.fn();
    const fetch = t.mock.method(globalThis, "fetch", async (_url, options) =>
      rejectedToken(
        options.headers.Authorization === "Bearer fresh" ? "retry" : "original",
      ),
    );
    const api = makeApi(getToken, onSessionRejected);

    await assert.rejects(api(students), /Sign in again/);
    assert.equal(fetch.mock.callCount(), 2);
    assert.deepEqual(
      onSessionRejected.mock.calls.map((call) => call.arguments),
      [["retry"]],
    );
  });

  await suite.test(
    "an unavailable assistant leaves school requests usable",
    async (t) => {
      const getToken = t.mock.fn(async () => "valid");
      const onSessionRejected = t.mock.fn();
      t.mock.method(globalThis, "fetch", async (_url, options) =>
        options.method === "POST"
          ? Response.json(
              { detail: "The AI provider is unavailable" },
              { status: 503 },
            )
          : Response.json({ loaded: true }),
      );
      const api = makeApi(getToken, onSessionRejected);

      await assert.rejects(api(chat, {}, { message: "hello" }), /AI provider/);
      assert.deepEqual(await api(students), { loaded: true });
      assert.equal(getToken.mock.callCount(), 2);
      assert.equal(onSessionRejected.mock.callCount(), 0);
    },
  );
});
