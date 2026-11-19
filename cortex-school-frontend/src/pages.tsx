import { t, getLocale } from "./i18n";
import { useContext, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Bell,
  Plus,
  RefreshCw,
  Search,
  CalendarDays,
  CheckCircle2,
  ClipboardCheck,
  Users,
  BookOpen,
  Clock,
  Send,
  Sparkles,
  Download,
  Filter,
  Upload,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useApi, endpoints, findEndpoint } from "./api";
import {
  Badge,
  DataView,
  Empty,
  ErrorBox,
  Loading,
  Operation,
  ToastContext,
  useRemote,
} from "./ui";
import { label } from "./forms";
import type { Data, Endpoint, Role, SchoolMemberIdentity } from "./types";
import { ChatAssistant } from "./chat";
import { GuardianNotifications, GuardianPolicyList, reminderReviewHref, SchoolPoliciesButton } from "./reminders";
import { GuardianChildCards } from "./guardian-family";
import { WorkspaceWelcome, workspaceProfiles } from "./workspace-identity";

const registrationDecisions = {
  approve: findEndpoint("POST", "/registration-requests/{request_id}/approve/"),
  reject: findEndpoint("POST", "/registration-requests/{request_id}/reject/"),
};

export type Page = {
  key: string;
  title: string;
  description: string;
  path: string;
  module: string;
  create?: string;
  params?: Data;
};
export const pages: Record<Role, Page[]> = {
  admin: [
    {
      key: "analytics",
      title: "Analytics",
      description: "Attendance, family communication, and registrations across your school.",
      path: "/analytics/",
      module: "analytics",
    },
    {
      key: "students",
      title: "Students",
      description: "Every learner, connected to your school.",
      path: "/students/",
      module: "students",
      create: "create_student",
    },
    {
      key: "academic-years",
      title: "Academic years",
      description: "Plan your school year, from the first day to the last.",
      path: "/academic-years/",
      module: "academic_years",
      create: "create_academic_year",
    },
    {
      key: "classrooms",
      title: "Classrooms",
      description: "Organize classrooms, placements, and teaching teams.",
      path: "/academic-years/{year_id}/classrooms/",
      module: "classrooms",
      create: "create_classroom",
    },
    {
      key: "enrollments",
      title: "Enrollments",
      description: "Manage enrollment history and class transfers.",
      path: "/students/{student_id}/enrollments/",
      module: "enrollments",
      create: "create_enrollment",
    },
    {
      key: "attendance",
      title: "Attendance",
      description:
        "A clear picture of who’s here and which classes need attention.",
      path: "/attendance/submissions",
      module: "attendance",
    },
    {
      key: "updates",
      title: "Student updates",
      description: "Follow classroom communication and guardian responses.",
      path: "/student-updates/",
      module: "student_updates",
    },
    { key: "publications", title: "Publications", description: "Send announcements to classes, families, teachers, or students’ families.", path: "/publications/", module: "publications" },
    {
      key: "registrations",
      title: "Registration requests",
      description: "Welcome new learners into your school community.",
      path: "/registration-requests/",
      module: "student_registration",
    },
    {
      key: "invitations",
      title: "Invitations",
      description: "Bring teachers, families, and administrators together.",
      path: "/invitations/",
      module: "invitations",
      create: "create_invitation",
    },
    {
      key: "review",
      title: "Needs review",
      description: "The right next step, all in one place.",
      path: "/needs-review/",
      module: "needs_review",
    },
    {
      key: "settings",
      title: "School settings",
      description: "Set your school’s rhythm and AI preferences.",
      path: "/school/attendance-settings",
      module: "schools",
    },
    {
      key: "members",
      title: "School members",
      description:
        "Browse your school’s administrators, teachers, and guardians.",
      path: "/members/",
      module: "members",
    },
    {
      key: "assistant",
      title: "AI assistant",
      description: "A little support for your school day.",
      path: "/ai/chat/",
      module: "ai",
    },
  ],
  teacher: [
    {
      key: "classrooms",
      title: "My classrooms",
      description: "Your classes, learners, and academic calendars.",
      path: "/teacher/classrooms/",
      module: "teachers",
    },
    {
      key: "attendance",
      title: "Daily attendance",
      description: "A small check-in. A better start to the day.",
      path: "/teacher/classrooms/{classroom_id}/attendance",
      module: "attendance",
    },
    {
      key: "updates",
      title: "Student updates",
      description: "Keep families close to the learning.",
      path: "/teacher/updates/",
      module: "student_updates",
      create: "create_update",
    },
    { key: "publications", title: "Publications", description: "Read announcements from your school administration.", path: "/publications/inbox/", module: "publications" },
    {
      key: "draft",
      title: "AI writing assistant",
      description: "Turn your classroom notes into a thoughtful family update.",
      path: "/ai/teacher-update-draft/",
      module: "ai",
    },
    {
      key: "assistant",
      title: "AI assistant",
      description: "A little support for your school day.",
      path: "/ai/chat/",
      module: "ai",
    },
  ],
  guardian: [
    {
      key: "family",
      title: "My children",
      description: "Classes, attendance, and school updates, together in one place.",
      path: "/guardian/family/",
      module: "guardian_family",
    },
    {
      key: "feed",
      title: "School updates",
      description: "Little moments. Meaningful progress.",
      path: "/guardian/feed/",
      module: "student_updates",
    },
    { key: "publications", title: "Publications", description: "Read announcements from your school administration.", path: "/publications/inbox/", module: "publications" },
    {
      key: "tutor",
      title: "Study tutor",
      description: "Work through the school book with explanations, quizzes, and practice tests.",
      path: "/guardian/tutor/books/",
      module: "tutor",
    },
    {
      key: "school-policies",
      title: "School policies",
      description: "Read policy documents shared by your school online.",
      path: "/guardian/family/policies/",
      module: "guardian_family",
    },
    {
      key: "registrations",
      title: "Registration requests",
      description: "Start and follow your child’s school registration.",
      path: "/guardian/registration-requests/",
      module: "student_registration",
      create: "create_guardian_registration_request",
    },
    {
      key: "notifications",
      title: "Notifications",
      description: "The latest from your school community.",
      path: "/guardian/notifications/",
      module: "student_updates",
    },
    {
      key: "assistant",
      title: "AI assistant",
      description: "A little support for your school day.",
      path: "/ai/chat/",
      module: "ai",
    },
  ],
};
export function Heading({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{t(eyebrow)}</p>
        <h1>{t(title)}</h1>
        <p>{t(description)}</p>
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}
export function Dashboard({ role, name }: { role: Role; name: string }) {
  const workspace = workspaceProfiles[role];
  const navigate = useNavigate();
  const [refresh, setRefresh] = useState(0);
  const ep = findEndpoint(
    "GET",
    role === "admin"
      ? "/needs-review/"
      : role === "teacher"
        ? "/teacher/today"
        : "/guardian/family/",
  );
  const state = useRemote(ep, {}, refresh);
  const students = useRemote(
    findEndpoint("GET", "/students/"),
    {},
    refresh,
    role === "admin",
  );
  const summary = useRemote(
    findEndpoint("GET", "/student-updates/summary/"),
    {},
    refresh,
    role === "admin",
  );
  const date = new Date().toLocaleDateString(getLocale(), {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  const [op, setOp] = useState<Endpoint | null>(null),
    [context, setContext] = useState<Data>({});
  const cards =
    role === "admin"
      ? [
          {
            name: t("Students"),
            value: students.data?.length,
            icon: Users,
            to: "students",
            detail: t("Your school community"),
          },
          {
            name: t("Needs review"),
            value: state.data?.total_count,
            icon: ClipboardCheck,
            to: "review",
            detail: t("Ready for your next step"),
          },
          {
            name: t("Updates completed"),
            value: summary.data?.completed,
            icon: CheckCircle2,
            to: "updates",
            detail: t("Keeping families connected"),
          },
          {
            name: t("Overdue responses"),
            value: summary.data?.overdue,
            icon: Clock,
            to: "updates",
            detail: t("A little follow-up goes a long way"),
          },
        ]
      : role === "teacher"
        ? [
            {
              name: t("Your classrooms"),
              value: state.data?.classrooms?.length,
              icon: BookOpen,
              to: "classrooms",
              detail: t("Spaces for discovery"),
            },
            {
              name: t("Learners today"),
              value: state.data?.classrooms?.reduce(
                (s: number, c: Data) => s + c.active_student_count,
                0,
              ),
              icon: Users,
              to: "classrooms",
              detail: t("Every learner matters"),
            },
            {
              name: t("Attendance submitted"),
              value: state.data?.classrooms?.filter(
                (c: Data) => c.attendance.status === "submitted",
              ).length,
              icon: ClipboardCheck,
              to: "attendance",
              detail: t("Start with a check-in"),
            },
          ]
        : [
            {
              name: t("Your children"),
              value: state.data?.children?.length,
              icon: Users,
              to: "family",
              detail: t("Growing, every day"),
            },
            {
              name: t("Registration requests"),
              value: state.data?.registration_requests?.length,
              icon: ClipboardCheck,
              to: "registrations",
              detail: t("Follow their next chapter"),
            },
          ];
  const review = state.data?.items || [];
  function reviewAction(item: Data) {
    const reminderHref = reminderReviewHref(item);
    if (reminderHref) {
      navigate(reminderHref);
      return;
    }
    const a = item.action;
    const match =
      a.type === "registration_request"
        ? registrationDecisions.approve
        : a.type === "invitation"
          ? findEndpoint("GET", "/invitations/{invitation_id}/")
          : a.type === "student_update"
            ? findEndpoint("GET", "/student-updates/{update_id}/")
            : a.type === "classroom_assignment"
              ? findEndpoint(
                  "POST",
                  "/classrooms/{classroom_id}/teacher-assignments/",
                )
              : findEndpoint("GET", "/attendance/submissions");
    setContext({ ...a, year_id: a.academic_year_id });
    setOp(match);
  }
  return (
    <>
      <Heading
        eyebrow={date}
        title={t(workspace.title)}
        description={t(workspace.description)}
      >
        <button
          className="button subtle"
          onClick={() => setRefresh((x) => x + 1)}
        >
          <RefreshCw size={16} />
          {t(" Refresh ")}
        </button>
        {role === "admin" && (
          <Link className="button primary" to="/analytics">
            <BarChart3 size={16} /> {t("School analytics")}
          </Link>
        )}
      </Heading>
      <WorkspaceWelcome role={role} name={name} />
      <div className="stats-grid">
        {cards.map((c) => (
          <Link key={c.name} to={`/${c.to}`} className="stat-card">
            <div>
              <span>{c.name}</span>
              <c.icon size={18} />
            </div>
            <strong>{c.value ?? "—"}</strong>
            <p>{c.detail}</p>
          </Link>
        ))}
      </div>
      {state.error && (
        <ErrorBox error={state.error} retry={() => setRefresh((x) => x + 1)} />
      )}
      {students.error && <ErrorBox error={students.error} />}
      {summary.error && <ErrorBox error={summary.error} />}
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>
                {role === "admin"
                  ? t("A little attention goes a long way")
                  : role === "teacher"
                    ? t("Your classrooms today")
                    : t("Your family at a glance")}
              </h2>
              <p>
                {role === "admin"
                  ? t("The things that could use your next step.")
                  : t("Everything you need for the day ahead.")}
              </p>
            </div>
            <Link
              className="text-button"
              to={
                role === "admin"
                  ? "/review"
                  : role === "teacher"
                    ? "/classrooms"
                    : "/family"
              }
            >
              {t(" View all ")}
              <ArrowUpRight size={14} />
            </Link>
          </div>
          {state.loading ? (
            <Loading />
          ) : role === "admin" ? (
            review.length ? (
              <div className="review-list">
                {review.slice(0, 4).map((item: Data) => (
                  <button
                    key={item.id}
                    onClick={() => reviewAction(item)}
                    className="review-item"
                  >
                    <span
                      className={`review-icon ${item.severity === "urgent" ? "urgent" : ""}`}
                    >
                      <ClipboardCheck size={19} />
                    </span>
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.reason}</p>
                    </div>
                    <Badge value={item.severity} />
                    {reminderReviewHref(item) ? (
                      <span className="text-button">{t("Review reminder")}</span>
                    ) : <ArrowUpRight size={16} />}
                  </button>
                ))}
              </div>
            ) : (
              <Empty
                title={t("You’re all caught up")}
                text="Your school’s review queue is clear."
              />
            )
          ) : role === "teacher" ? (
            <div className="class-grid">
              {state.data?.classrooms?.map((c: Data) => (
                <Link
                  to={`/attendance?classroom_id=${c.id}`}
                  key={c.id}
                  className="class-card"
                >
                  <BookOpen size={24} />
                  <h3>{c.name}</h3>
                  <p>
                    {c.active_student_count} learners ·{" "}
                    {label(c.assignment_role)}
                  </p>
                  <Badge value={c.attendance.status} />
                </Link>
              ))}
            </div>
          ) : (
            state.data?.children?.length ? <GuardianChildCards children={state.data.children} schoolDate={state.data.school_date} refresh={refresh} onChanged={() => setRefresh((x) => x + 1)} /> : <Empty title="No children linked yet" text="Children linked by your school will appear here." />
          )}
        </section>
        <aside className="panel quick-panel">
          <p className="eyebrow">{t("MAKE ROOM FOR WHAT MATTERS")}</p>
          <h2>{t("A good place to start.")}</h2>
          <div className="quick-links">
            {(role === "admin"
              ? [
                  [
                    "registrations",
                    t("Review registrations"),
                    t("Welcome a new learner"),
                    Users,
                  ],
                  [
                    "invitations",
                    t("Invite your community"),
                    t("Bring everyone together"),
                    Send,
                  ],
                  [
                    "academic-years",
                    t("Plan the school year"),
                    t("Set the rhythm for learning"),
                    CalendarDays,
                  ],
                ]
              : role === "teacher"
                ? [
                    [
                      "attendance",
                      t("Take attendance"),
                      t("A thoughtful start"),
                      ClipboardCheck,
                    ],
                    [
                      "updates",
                      t("Share an update"),
                      t("Keep families connected"),
                      Send,
                    ],
                    [
                      "draft",
                      t("Find the right words"),
                      t("A little help from AI"),
                      Sparkles,
                    ],
                  ]
                : [
                    [
                      "feed",
                      t("Read school updates"),
                      t("What’s happening in class"),
                      BookOpen,
                    ],
                    [
                      "registrations",
                      t("Register a child"),
                      t("A new chapter starts here"),
                      Users,
                    ],
                    [
                      "family",
                      t("View attendance"),
                      t("Stay in the loop"),
                      ClipboardCheck,
                    ],
                  ]
            ).map(([to, title, sub, Icon]: any) => (
              <Link key={to} to={`/${to}`}>
                <span className="quick-icon">
                  <Icon size={18} />
                </span>
                <div>
                  <strong>{t(title)}</strong>
                  <p>{sub}</p>
                </div>
                <ArrowRight size={15} />
              </Link>
            ))}
          </div>
          <div className="quiet-note">
            <span>✦</span>
            <p>
              {t(" Good schools grow through ")}
              <br />
              {t(" small, everyday connections. ")}
            </p>
          </div>
        </aside>
      </div>
      {op && (
        <Operation
          endpoint={op}
          context={context}
          onClose={() => setOp(null)}
          onDone={() => setRefresh((x) => x + 1)}
        />
      )}
    </>
  );
}
function RegistrationRequestActions({ request, onChanged }: {
  request: Data;
  onChanged: () => void;
}) {
  const [decision, setDecision] = useState<keyof typeof registrationDecisions | null>(null);
  const childName = [request.child_first_name, request.child_last_name].filter(Boolean).join(" ");

  return (
    <div className="registration-actions">
      <button type="button" className="button small primary" onClick={() => setDecision("approve")}>
        {t("Approve")}
      </button>
      <button type="button" className="button small danger" onClick={() => setDecision("reject")}>
        {t("Reject")}
      </button>
      {decision && (
        <Operation
          endpoint={registrationDecisions[decision]}
          context={{ request_id: request.id }}
          recordName={childName}
          submitLabel={decision === "approve" ? "Approve" : "Reject"}
          onClose={() => setDecision(null)}
          onDone={onChanged}
        />
      )}
    </div>
  );
}

export function ResourcePage({
  page,
  role,
  context,
  choices,
  schoolMembers,
}: {
  page: Page;
  role: Role;
  context: Data;
  choices: Record<string, { value: string; label: string }[]>;
  schoolMembers?: SchoolMemberIdentity[];
}) {
  const [op, setOp] = useState<Endpoint | null>(null),
    [refresh, setRefresh] = useState(0),
    [search, setSearch] = useState(""),
    [params, setParams] = useState<Data>({}),
    [filters, setFilters] = useState(false),
    [workflows, setWorkflows] = useState(false);
  const endpoint = findEndpoint("GET", page.path);
  const values = { ...context, ...params };
  const required = endpoint?.params.filter((p) => p.in === "path") || [];
  const ready = required.every((p) => values[p.name]);
  const state = useRemote(endpoint, values, refresh, !!endpoint && ready);
  const create = endpoints.find((e) => e.id === page.create && e.role === role);
  const actions = endpoints.filter(
    (e) => e.module === page.module && (e.role === role || e.role === "shared"),
  );
  const title = t(page.title);
  const acknowledgementsOnly =
    params.category?.length === 1 && params.category[0] === "acknowledgement";
  let records = state.data;
  if (schoolMembers && Array.isArray(records)) {
    const membersById = new Map(schoolMembers.map((member) => [member.id, member]));
    records = records.map((request: Data) => {
      const requester = membersById.get(request.guardian_workos_user_id);
      return {
        ...request,
        guardian_name: requester?.name ?? null,
        guardian_email: requester?.email ?? null,
      };
    });
  }
  const data =
    Array.isArray(records) && search
      ? records.filter((x) =>
          JSON.stringify(x).toLowerCase().includes(search.toLowerCase()),
        )
      : records;
  const reloadRecords = () => setRefresh((x) => x + 1);
  function rowAction(row: Data) {
    if (role !== "admin") return null;
    if (page.key === "registrations") {
      return row.status === "pending"
        ? <RegistrationRequestActions request={row} onChanged={reloadRecords} />
        : null;
    }
    if (page.key === "review" || page.key === "updates") {
      const href = reminderReviewHref(row);
      return href ? (
        <Link to={href} className="button small subtle">
          <Bell size={14} /> {t("Review reminder")}
        </Link>
      ) : null;
    }
    return null;
  }

  function exportCsv() {
    if (!Array.isArray(data) || !data.length) return;
    const { guardian_name, guardian_email, ...registrationFields } = data[0];
    const keys = Object.keys(schoolMembers ? registrationFields : data[0]).filter(
      (k) => typeof data[0][k] !== "object",
    );
    const safe = (x: any) => {
      let s = String(x ?? "");
      if (/^[=+@\-\t\r]/.test(s)) s = "'" + s;
      return '"' + s.replaceAll('"', '""') + '"';
    };
    const blob = new Blob(
      [
        "\uFEFF" +
          [
            keys.map(safe).join(","),
            ...data.map((row) => keys.map((k) => safe(row[k])).join(",")),
          ].join("\r\n"),
      ],
      { type: "text/csv;charset=utf-8;" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cortex-${page.key}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
  if (page.key === "assistant" || page.key === "draft")
    return <AssistantPage page={page} role={role} />;
  if (page.key === "school-policies")
    return (
      <>
        <Heading eyebrow="FAMILY WORKSPACE" title={title} description={page.description} />
        {state.loading ? <Loading /> : state.error ? (
          <ErrorBox error={state.error} retry={() => setRefresh((value) => value + 1)} />
        ) : <GuardianPolicyList policies={state.data ?? []} />}
      </>
    );
  return (
    <>
      <Heading
        eyebrow={`${role === "admin" ? t("SCHOOL MANAGEMENT") : role === "teacher" ? t("TEACHER WORKSPACE") : t("FAMILY WORKSPACE")}`}
        title={title}
        description={page.description}
      >
        {page.key === "settings" && role === "admin" && <SchoolPoliciesButton />}
        {page.key === "invitations" && role === "admin" && (
          <button
            type="button"
            className="button subtle"
            onClick={() => setOp(findEndpoint("POST", "/invitations/upload/"))}
          >
            <Upload size={16} />{t("Import CSV")}
          </button>
        )}
        {page.key === "review" && (
          <button
            type="button"
            className={`button ${acknowledgementsOnly ? "subtle" : "primary"}`}
            onClick={() =>
              setParams((current) => ({
                ...current,
                category: acknowledgementsOnly ? [] : ["acknowledgement"],
                offset: 0,
              }))
            }
          >
            <Bell size={16} />
            {t(acknowledgementsOnly ? "Clear acknowledgement filter" : "Overdue acknowledgements")}
          </button>
        )}
        <button
          className="button subtle"
          onClick={() => setWorkflows(!workflows)}
        >
          <Sparkles size={16} />
          {t(" All workflows ")}
        </button>
        {create && (
          <button className="button primary" onClick={() => setOp(create)}>
            <Plus size={16} /> {t(create.title)}
          </button>
        )}
      </Heading>
      {workflows && (
        <section className="panel workflow-panel">
          <h2>{t(`${title} workflows`)}</h2>
          <p>
            {t(
              " Choose a task. Related records will be prefilled where available. ",
            )}
          </p>
          <div className="record-actions">
            {actions.map((e) => (
              <button
                className="button small subtle"
                key={e.method + e.path}
                onClick={() => setOp(e)}
              >
                {t(e.title)}
                <ArrowUpRight size={13} />
              </button>
            ))}
          </div>
        </section>
      )}
      <section className="panel">
        <div className="table-toolbar">
          <div className="search-input">
            <Search size={17} />
            <input
              aria-label={`Search ${title}`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t(`Search ${title.toLowerCase()}…`)}
            />
          </div>
          <div className="toolbar-actions">
            {required.map((p) => (
              <label className="inline-select" key={p.name}>
                <span className="sr-only">{label(p.name)}</span>
                {choices[p.name] ? (
                  <select
                    aria-label={label(p.name)}
                    value={values[p.name] || ""}
                    onChange={(e) =>
                      setParams({ ...params, [p.name]: e.target.value })
                    }
                  >
                    <option value="">{t(`Select ${label(p.name)}`)}</option>
                    {choices[p.name].map((x) => (
                      <option key={x.value} value={x.value}>
                        {x.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label={label(p.name)}
                    placeholder={label(p.name)}
                    value={values[p.name] || ""}
                    onChange={(e) =>
                      setParams({ ...params, [p.name]: e.target.value })
                    }
                  />
                )}
              </label>
            ))}
            <button
              className={`button subtle small ${filters ? "selected" : ""}`}
              onClick={() => setFilters(!filters)}
            >
              <Filter size={15} />
              {t(" Filters ")}
            </button>
            <button
              className="icon-button"
              aria-label={t("Refresh records")}
              onClick={() => setRefresh((x) => x + 1)}
            >
              <RefreshCw size={17} />
            </button>
            {Array.isArray(data) && data.length > 0 && (
              <button
                className="icon-button"
                aria-label={t("Export records as CSV")}
                onClick={exportCsv}
              >
                <Download size={17} />
              </button>
            )}
          </div>
        </div>
        {filters && (
          <div className="filter-bar">
            {endpoint?.params
              .filter((p) => p.in === "query")
              .map((p) => (
                <label className="field" key={p.name}>
                  <span>{label(p.name)}</span>
                  {p.type === "array" && p.items?.enum ? (
                    <select
                      multiple
                      aria-label={label(p.name)}
                      value={params[p.name] || []}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          [p.name]: Array.from(
                            e.target.selectedOptions,
                            (o) => o.value,
                          ),
                        })
                      }
                    >
                      {p.items.enum.map((v) => (
                        <option key={v} value={v}>
                          {label(v)}
                        </option>
                      ))}
                    </select>
                  ) : p.enum ? (
                    <select
                      value={params[p.name] ?? ""}
                      onChange={(e) =>
                        setParams({ ...params, [p.name]: e.target.value })
                      }
                    >
                      <option value="">{t("All")}</option>
                      {p.enum.map((v) => (
                        <option key={v} value={v}>
                          {label(v)}
                        </option>
                      ))}
                    </select>
                  ) : p.type === "boolean" ? (
                    <select
                      value={String(params[p.name] ?? "")}
                      onChange={(e) =>
                        setParams({ ...params, [p.name]: e.target.value })
                      }
                    >
                      <option value="">{t("All")}</option>
                      <option value="true">{t("Yes")}</option>
                      <option value="false">{t("No")}</option>
                    </select>
                  ) : (
                    <input
                      type={
                        p.format === "date"
                          ? "date"
                          : p.type === "integer"
                            ? "number"
                            : "text"
                      }
                      placeholder={label(p.name)}
                      value={params[p.name] ?? ""}
                      onChange={(e) =>
                        setParams({ ...params, [p.name]: e.target.value })
                      }
                    />
                  )}
                </label>
              ))}
            {!endpoint?.params.some((p) => p.in === "query") && (
              <p>{t("Use search to find a record in this list.")}</p>
            )}
            <button className="text-button" onClick={() => setParams({})}>
              {t(" Reset filters ")}
            </button>
          </div>
        )}
        {!ready ? (
          <Empty
            title={t("Choose a record to get started")}
            text="Select the year, student, or classroom above to see its records."
          />
        ) : state.loading ? (
          <Loading />
        ) : state.error ? (
          <ErrorBox
            error={state.error}
            retry={() => setRefresh((x) => x + 1)}
          />
        ) : (
          <>
            {page.key === "settings" && (
              <div className="settings-actions">
                <button
                  className="button primary"
                  onClick={() =>
                    setOp(findEndpoint("PUT", "/school/attendance-settings"))
                  }
                >
                  {t(" Edit attendance settings ")}
                </button>
                <button
                  className="button subtle"
                  onClick={() =>
                    setOp(findEndpoint("GET", "/school/ai-settings"))
                  }
                >
                  {t(" View AI settings ")}
                </button>
                <button
                  className="button subtle"
                  onClick={() =>
                    setOp(findEndpoint("PUT", "/school/ai-settings"))
                  }
                >
                  {t(" Edit AI settings ")}
                </button>
              </div>
            )}
            {page.key === "feed" ? (
              <Feed
                data={data || []}
                onChanged={() => setRefresh((x) => x + 1)}
              />
            ) : page.key === "notifications" ? (
              <GuardianNotifications
                data={data || []}
                onChanged={() => setRefresh((x) => x + 1)}
              />
            ) : (
              <DataView
                data={data}
                endpoint={endpoint}
                context={values}
                onChanged={reloadRecords}
                rowAction={rowAction}
              />
            )}
          </>
        )}
        <div className="table-footer">
          <span>
            {Array.isArray(data)
              ? t(`${data.length} records shown`)
              : t("School workspace")}
          </span>
          <span>
            {state.loading ? t("Updating…") : t("Connected to your community")}
          </span>
        </div>
      </section>
      {op && (
        <Operation
          endpoint={op}
          context={values}
          seed={page.key === "settings" ? state.data : undefined}
          onClose={() => setOp(null)}
          onDone={() => setRefresh((x) => x + 1)}
        />
      )}
    </>
  );
}
function Feed({ data, onChanged }: { data: Data[]; onChanged: () => void }) {
  const [op, setOp] = useState<Endpoint | null>(null),
    [context, setContext] = useState<Data>({});
  if (!data.length)
    return (
      <Empty
        title={t("Your next classroom story starts here")}
        text="Updates from your child’s teachers will appear here."
      />
    );
  return (
    <div className="feed-list">
      {data.map((item) => (
        <article className="feed-card" key={item.recipient_id}>
          <div className="feed-meta">
            <span className="avatar">
              {item.student_first_name?.[0] || "S"}
            </span>
            <div>
              <strong>
                {item.student_first_name} {item.student_last_name}
              </strong>
              <p>{item.classroom_name}</p>
            </div>
            <Badge value={item.status} />
          </div>
          <h2>{item.title}</h2>
          <p className="prose">{item.body}</p>
          {item.due_at && (
            <p className="deadline">
              <Clock size={14} />
              {t(" Due")}{" "}
              {new Date(item.due_at).toLocaleDateString(getLocale())}
            </p>
          )}
          <div className="record-actions">
            {[
              [
                "GET",
                "/guardian/updates/{recipient_id}/",
                t("View conversation"),
              ],
              [
                "POST",
                "/guardian/updates/{recipient_id}/read/",
                t("Mark as read"),
              ],
              ...(item.requires_acknowledgement
                ? [
                    [
                      "POST",
                      "/guardian/updates/{recipient_id}/acknowledge/",
                      t("Acknowledge"),
                    ],
                  ]
                : []),
              ...(item.allows_replies
                ? [
                    [
                      "POST",
                      "/guardian/updates/{recipient_id}/replies/",
                      t("Reply"),
                    ],
                  ]
                : []),
            ].map(([m, p, t]) => (
              <button
                className="button subtle small"
                key={p}
                onClick={() => {
                  setContext(item);
                  setOp(findEndpoint(m, p));
                }}
              >
                {t}
                <ArrowUpRight size={13} />
              </button>
            ))}
          </div>
        </article>
      ))}
      {op && (
        <Operation
          endpoint={op}
          context={context}
          onClose={() => setOp(null)}
          onDone={onChanged}
        />
      )}
    </div>
  );
}
function AssistantPage({ page, role }: { page: Page; role: Role }) {
  const [op, setOp] = useState<Endpoint | null>(null);
  if (page.key === "assistant") return <ChatAssistant key={role} role={role} />;
  return (
    <>
      <Heading
        eyebrow={t("A LITTLE EXTRA SUPPORT")}
        title={page.title}
        description={page.description}
      />
      <section className="panel assistant-panel">
        <span className="assistant-icon">
          <Sparkles size={32} />
        </span>
        <h2>
          {page.key === "draft"
            ? t("Your voice. A little help finding the words.")
            : t("What’s on your mind today?")}
        </h2>
        <p>
          {page.key === "draft"
            ? t(
                "Start with your classroom notes. Generate a draft, review it, then use it in a student update.",
              )
            : t(
                "Ask a question and get support from your school’s configured AI assistant.",
              )}
        </p>
        <button
          className="button primary"
          onClick={() => setOp(findEndpoint("POST", page.path))}
        >
          <Sparkles size={17} />
          {page.key === "draft"
            ? t("Write a draft")
            : t("Start a conversation")}
        </button>
        <small>
          {t(
            " AI responses can contain mistakes. Always review before sharing. ",
          )}
        </small>
      </section>
      {op && (
        <Operation
          endpoint={op}
          onClose={() => setOp(null)}
          onDone={() => {}}
        />
      )}
    </>
  );
}
export function AttendancePage({
  choices,
  initialClassroom,
}: {
  choices: { value: string; label: string }[];
  initialClassroom: string;
}) {
  const api = useApi(),
    toast = useContext(ToastContext);
  const [classroom, setClassroom] = useState(initialClassroom),
    [date, setDate] = useState(""),
    [refresh, setRefresh] = useState(0),
    [edits, setEdits] = useState<Record<string, Data>>({}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const get = findEndpoint(
    "GET",
    date
      ? "/teacher/classrooms/{classroom_id}/attendance/{school_date}"
      : "/teacher/classrooms/{classroom_id}/attendance",
  );
  const state = useRemote(
    get,
    { classroom_id: classroom, school_date: date },
    refresh,
    !!classroom,
  );
  const entries: Data[] = state.data?.entries || [];
  const current = (r: Data) => ({ ...r, ...edits[r.placement_id] });
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api(
        findEndpoint(
          "PUT",
          "/teacher/classrooms/{classroom_id}/attendance/{school_date}",
        ),
        { classroom_id: classroom, school_date: state.data.school_date },
        {
          entries: entries.map((r) => {
            const v = current(r);
            return {
              placement_id: v.placement_id,
              status: v.status,
              note: v.note || null,
            };
          }),
        },
      );
      toast(t("Attendance saved successfully"));
      setEdits({});
      setRefresh((x) => x + 1);
    } catch (x) {
      setError((x as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        eyebrow={t("THE DAILY CHECK-IN")}
        title={t("Daily attendance")}
        description={t(
          "Every learner counts. Start the day with a thoughtful check-in.",
        )}
      >
        <button
          className="button primary"
          disabled={!state.data || busy || state.loading}
          onClick={save}
        >
          <CheckCircle2 size={17} />
          {busy
            ? t("Saving…")
            : state.data?.submitted
              ? t("Save changes")
              : t("Submit attendance")}
        </button>
      </Heading>
      <section className="panel">
        <div className="table-toolbar">
          <select
            aria-label={t("Classroom")}
            value={classroom}
            onChange={(e) => {
              setClassroom(e.target.value);
              setEdits({});
            }}
          >
            <option value="">{t("Select classroom")}</option>
            {choices.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
          <label className="date-control">
            <span>
              {date ? t("Selected date") : t("School’s current date")}
            </span>
            <input
              aria-label={t("Attendance date")}
              type="date"
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
                setEdits({});
              }}
            />
          </label>
          <button
            className="button subtle small"
            disabled={!entries.length}
            onClick={() =>
              setEdits(
                Object.fromEntries(
                  entries.map((r) => [
                    r.placement_id,
                    { ...current(r), status: "present" },
                  ]),
                ),
              )
            }
          >
            {t(" Mark all present ")}
          </button>
          {state.data && (
            <Badge value={state.data.submitted ? "submitted" : "not_started"} />
          )}
        </div>
        {error && <ErrorBox error={error} />}{" "}
        {!classroom ? (
          <Empty
            title={t("Choose your classroom")}
            text="Select a class above to open today’s attendance sheet."
          />
        ) : state.loading ? (
          <Loading />
        ) : state.error ? (
          <ErrorBox error={state.error} />
        ) : entries.length ? (
          <>
            <div className="attendance-summary">
              {["present", "absent", "late", "excused"].map((s) => (
                <div key={s}>
                  <strong>
                    {entries.filter((r) => current(r).status === s).length}
                  </strong>
                  <span>{label(s)}</span>
                </div>
              ))}
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("Student")}</th>
                    <th>{t("Attendance")}</th>
                    <th>{t("Note")}</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((r) => {
                    const v = current(r);
                    return (
                      <tr key={r.placement_id}>
                        <td>
                          <div className="student-cell">
                            <span className="avatar">
                              {r.first_name[0]}
                              {r.last_name[0]}
                            </span>
                            <strong>
                              {r.first_name} {r.last_name}
                            </strong>
                          </div>
                        </td>
                        <td>
                          <select
                            aria-label={`Attendance for ${r.first_name} ${r.last_name}`}
                            value={v.status}
                            onChange={(e) =>
                              setEdits({
                                ...edits,
                                [r.placement_id]: {
                                  ...v,
                                  status: e.target.value,
                                },
                              })
                            }
                          >
                            {["present", "absent", "late", "excused"].map(
                              (s) => (
                                <option value={s} key={s}>
                                  {label(s)}
                                </option>
                              ),
                            )}
                          </select>
                        </td>
                        <td>
                          <input
                            aria-label={`Note for ${r.first_name}`}
                            placeholder={t("Add a note (optional)")}
                            value={v.note || ""}
                            maxLength={1000}
                            onChange={(e) =>
                              setEdits({
                                ...edits,
                                [r.placement_id]: {
                                  ...v,
                                  note: e.target.value,
                                },
                              })
                            }
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <Empty title={t("No students on this date")} />
        )}
      </section>
    </>
  );
}
