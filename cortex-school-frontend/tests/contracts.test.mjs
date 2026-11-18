import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  endpointUrl,
  errorMessage,
  rolesFromClaims,
  initialValue,
  cleanPayload,
} from "../src/lib.mjs";
const routes = JSON.parse(
  readFileSync(new URL("../src/contracts.json", import.meta.url), "utf8"),
);
const find = (id) => routes.find((x) => x.id === id);
test("contracts contain 109 unique business routes and all backend modules", () => {
  assert.equal(routes.length, 109);
  assert.equal(
    new Set(routes.map((e) => e.method + e.path)).size,
    routes.length,
  );
  for (const module of [
    "academic_years",
    "ai",
    "analytics",
    "attendance",
    "classrooms",
    "enrollments",
    "guardian_family",
    "invitations",
    "members",
    "needs_review",
    "reminders",
    "schools",
    "students",
    "student_registration",
    "student_updates",
    "teachers",
    "tutor",
  ])
    assert.ok(
      routes.some((e) => e.module === module),
      module,
    );
  for (const e of routes)
    for (const key of [...e.path.matchAll(/\{([^}]+)\}/g)].map((m) => m[1]))
      assert.ok(
        e.params.some((p) => p.name === key && p.in === "path"),
        e.path,
      );
});
test("URLs encode identifiers and preserve repeated query filters, false, and zero", () => {
  const e = {
    path: "/students/{student_id}/",
    params: [
      { in: "query", name: "category" },
      { in: "query", name: "offset" },
      { in: "query", name: "unread_only" },
    ],
  };
  assert.equal(
    endpointUrl("/api/", e, {
      student_id: "a/b",
      category: ["invitation", "registration"],
      offset: 0,
      unread_only: false,
    }),
    "/api/students/a%2Fb/?category=invitation&category=registration&offset=0&unread_only=false",
  );
  assert.throws(() => endpointUrl("/api", e, {}), /Choose student id/);
});
test("school admin permission and teacher/guardian claims control role access", () => {
  assert.deepEqual(
    rolesFromClaims({ role: "school_admin", permissions: [] }),
    [],
  );
  assert.deepEqual(
    rolesFromClaims({
      permissions: ["school:manage"],
      roles: ["teacher", "guardian"],
    }),
    ["admin", "teacher", "guardian"],
  );
  assert.deepEqual(rolesFromClaims({ role: "teacher" }), ["teacher"]);
});
test("registration approvals preserve the selected resolution and remove unrelated fields", () => {
  const s = find("approve_school_registration_request").body;
  assert.equal(s.discriminator, "resolution");
  assert.deepEqual(
    cleanPayload({ resolution: "create", student_id: "unrelated" }, s),
    { resolution: "create" },
  );
  assert.deepEqual(
    cleanPayload({ resolution: "existing", student_id: "student-1" }, s),
    { resolution: "existing", student_id: "student-1" },
  );
});
test("updates preserve nested audience, defaults, optional omission and timezone", () => {
  const s = find("create_update").body;
  const value = initialValue(s);
  assert.deepEqual(value.target, { type: "classroom" });
  assert.equal(value.allows_replies, true);
  assert.equal(value.requires_acknowledgement, false);
  const result = cleanPayload(
    {
      ...value,
      classroom_id: "c",
      title: "Hello",
      body: "",
      due_at: "2026-11-06T10:00",
      target: { type: "students", student_ids: ["s"] },
    },
    s,
  );
  assert.equal(result.body, undefined);
  assert.match(result.due_at, /Z$/);
  assert.deepEqual(result.target, { type: "students", student_ids: ["s"] });
  assert.equal(
    s.properties.target.oneOf[1].properties.student_ids.required,
    true,
  );
});
test("attendance and invitation request shapes match backend contracts", () => {
  assert.ok(find("upload_invitations").upload);
  assert.ok(find("upload_school_policy_pdf").upload);
  const s = find("put_teacher_attendance").body;
  assert.deepEqual(
    cleanPayload(
      {
        entries: [
          { placement_id: "p", status: "present", note: "", student_id: "s" },
        ],
      },
      s,
    ),
    { entries: [{ placement_id: "p", status: "present" }] },
  );
});
test("validation errors retain their field location", () => {
  assert.equal(
    errorMessage(
      {
        detail: [
          { loc: ["body", "entries", 0, "status"], msg: "Invalid value" },
        ],
      },
      422,
    ),
    "entries → 0 → status: Invalid value",
  );
  assert.equal(
    errorMessage({ detail: "Closed year is read-only" }, 409),
    "Closed year is read-only",
  );
});
