import {
  t,
  LanguageProvider,
  LanguageSwitch,
  useLanguage,
} from "./i18n";
import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  AuthKitProvider,
  LoginRequiredError,
  useAuth,
} from "@workos-inc/authkit-react";
import {
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Bell,
  BookOpen,
  CalendarDays,
  Check,
  ClipboardCheck,
  GraduationCap,
  Heart,
  Home,
  Layers,
  LibraryBig,
  LogOut,
  Menu,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { ApiContext, findEndpoint, makeApi, sessionRejectedMessage } from "./api";
import { CurrentUserContext } from "./current-user";
import { rolesFromClaims } from "./lib.mjs";
import {
  ChoicesContext,
  ErrorBox,
  Loading,
  ToastContext,
  useRemote,
} from "./ui";
import {
  AttendancePage,
  Dashboard,
  Heading,
  pages,
  ResourcePage,
} from "./pages";
import type { Data, Role } from "./types";
import type { Choices } from "./forms";
import { ReminderReviewPage } from "./reminders";
import { SchoolAnalyticsPage } from "./analytics";
import { GuardianTutorPage } from "./tutor";
import { NeedsReviewPage } from "./needs-review";
import { GuardianFamilyPage } from "./guardian-family";
import { SchoolMembersPage } from "./school-members";
import { AcademicDirectoryPage } from "./academic-directory";
import { AcademicYearsPage } from "./academic-years";
import { TeacherClassroomsPage } from "./teacher-classrooms";
import { InvitationsPage } from "./invitations";
import { StudentGuardianContext } from "./student-guardians";
import { SchoolSettingsPage } from "./school-settings";
import { OnboardingPage } from "./onboarding";
import {
  WorkspaceIdentity,
  WorkspaceSwitch,
  useWorkspaceTheme,
  workspaceProfiles,
} from "./workspace-identity";
import "./onboarding.css";
import "./styles.css";
import "./needs-review.css";
import "./guardian-family.css";
import "./invitation-import.css";
import "./invitations.css";
import "./school-members.css";
import "./academic-directory.css";
import "./academic-years.css";
import "./teacher-classrooms.css";
import "./teacher-draft-review.css";
import "./student-guardians.css";
import "./school-settings.css";
import "./workspace-identity.css";
function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark brand-logo">
        <img src="/cortex-logo.png" alt="" width="36" height="44" />
      </span>
      <span>
        cortex<span className="brand-school">school</span>
      </span>
    </div>
  );
}
function Login() {
  const { signIn, signUp, isLoading } = useAuth();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function login(createAccount = false) {
    setBusy(true);
    setError("");
    try {
      if (createAccount) await signUp();
      else await signIn();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <section className="login-story">
        <Brand />
        <div className="login-story-copy">
          <span className="banner-label">
            <span />
            {t(" A SCHOOL COMMUNITY, CONNECTED ")}
          </span>
          <h1>
            {t(" Great things ")}
            <br />
            {t(" grow ")}
            <em>{t("together.")}</em>
          </h1>
          <p>
            {t(" A thoughtful home for learning, teaching, ")}
            <br />
            {t(" and every little moment in between. ")}
          </p>
          <div className="login-illustration">
            <div className="paper-card">
              <BookOpen size={28} />
              <p>
                {t(" Curiosity today. ")}
                <br />
                <strong>{t("Possibility tomorrow.")}</strong>
              </p>
              <span>✦</span>
            </div>
            <div className="floating-heart">
              <Heart size={25} />
            </div>
            <div className="floating-star">✷</div>
            <div className="login-circle" />
            <div className="login-arch" />
          </div>
        </div>
        <footer>
          <span>{t("Made for your school. Built around your people.")}</span>
          <span>✦</span>
        </footer>
      </section>
      <main className="login-form">
        <div className="login-language">
          <LanguageSwitch />
        </div>
        <div className="mobile-brand">
          <Brand />
        </div>
        <div className="login-box">
          <span className="login-mini-icon">
            <GraduationCap size={28} />
          </span>
          <p className="eyebrow">{t("WELCOME TO CORTEX SCHOOL")}</p>
          <h2>
            {t(" Your school day ")}
            <br />
            {t(" starts here. ")}
          </h2>
          <p>{t("Sign in to your connected school workspace.")}</p>
          {error && <ErrorBox error={error} />}
          <button
            className="button primary login-button"
            onClick={() => login()}
            disabled={busy || isLoading}
          >
            {busy ? t("Connecting…") : t("Sign in to your school")}
            <ArrowRight size={18} />
          </button>
          <div className="secure-note">
            <ShieldCheck size={15} />
            <span>{t("Secure sign-in powered by WorkOS")}</span>
          </div>
          <div className="login-help">
            <strong>{t("Joining your school?")}</strong>
            <p>
              {t(" Use the invitation from your school administrator. ")}
              <br />
              {t(" You can create your account during secure sign-in. ")}
            </p>
          </div>
          <div className="login-help">
            <strong>{t("Setting up a new school?")}</strong>
            <p>{t("Create your account, then request a school workspace for operator approval.")}</p>
            <button
              className="text-button"
              onClick={() => login(true)}
              disabled={busy || isLoading}
            >
              {t("Register your school")} <ArrowRight size={15} />
            </button>
          </div>
        </div>
        <p className="login-copyright">
          © {new Date().getFullYear()}
          {t(" Cortex School · Growing together. ")}
        </p>
      </main>
    </div>
  );
}
function Authenticated() {
  const auth = useAuth();
  const [claims, setClaims] = useState<Data | null>(null),
    [error, setError] = useState("");
  const [rejectedRequest, setRejectedRequest] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);
  useEffect(() => {
    let active = true;
    auth
      .getAccessToken()
      .then((token) => {
        if (!token)
          throw new Error("No access token was returned. Sign in again.");
        const encoded = token
          .split(".")[1]
          .replace(/-/g, "+")
          .replace(/_/g, "/");
        const decoded = JSON.parse(
          new TextDecoder().decode(
            Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0)),
          ),
        );
        if (active) setClaims(decoded);
      })
      .catch((e) => {
        if (!active) return;
        if (e instanceof LoginRequiredError) setRejectedRequest("");
        else setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [auth.user?.id, auth.getAccessToken]);
  const api = useMemo(
    () =>
      makeApi(async (forceRefresh) => {
        try {
          return await auth.getAccessToken({ forceRefresh });
        } catch (e) {
          if (e instanceof LoginRequiredError) return undefined;
          throw e;
        }
      }, setRejectedRequest),
    [auth.getAccessToken],
  );

  async function signInAgain() {
    setSigningIn(true);
    try {
      await auth.signIn();
    } catch (e) {
      setError((e as Error).message);
      setSigningIn(false);
    }
  }

  if (error || rejectedRequest !== null)
    return (
      <div className="center-page">
        {rejectedRequest !== null && <ErrorBox error={sessionRejectedMessage} />}
        {error && <ErrorBox error={error} />}
        {rejectedRequest && <small>{t("Request ID")} {rejectedRequest}</small>}
        <button className="button primary" onClick={signInAgain} disabled={signingIn}>
          {t(signingIn ? "Connecting…" : "Sign in again")}
        </button>
      </div>
    );
  if (!claims) return <Loading />;
  const roles = rolesFromClaims(claims) as Role[];
  if (!roles.length || !claims.org_id)
    return (
      <ApiContext.Provider value={api}>
        <OnboardingPage
          key={auth.user?.id}
          email={auth.user?.email || ""}
          onExit={() => auth.signOut()}
          onEnter={(organizationId) => auth.signIn({ organizationId })}
        />
      </ApiContext.Provider>
    );
  return (
    <ApiContext.Provider value={api}>
      <CurrentUserContext.Provider value={{ displayName: [auth.user?.firstName, auth.user?.lastName].map((part) => part?.trim()).filter(Boolean).join(" ") }}>
      <Shell
        roles={roles}
        name={auth.user?.firstName || ""}
        email={auth.user?.email || ""}
        organization={claims.org_id}
        onExit={() => auth.signOut()}
      />
      </CurrentUserContext.Provider>
    </ApiContext.Provider>
  );
}
const icons: Record<string, any> = {
  analytics: BarChart3,
  students: Users,
  "academic-years": CalendarDays,
  classrooms: BookOpen,
  enrollments: Layers,
  attendance: ClipboardCheck,
  updates: BookOpen,
  registrations: UserPlus,
  invitations: SendIcon,
  review: ClipboardCheck,
  settings: Settings,
  members: Users,
  assistant: Sparkles,
  draft: Sparkles,
  family: Users,
  feed: BookOpen,
  "school-policies": BookOpen,
  tutor: LibraryBig,
  notifications: Bell,
};
function SendIcon(props: any) {
  return <UserPlus {...props} />;
}
function Shell({
  roles,
  name,
  email,
  organization,
  onExit,
}: {
  roles: Role[];
  name: string;
  email: string;
  organization?: string;
  onExit: () => void;
}) {
  const [revision, setRevision] = useState(0);
  const [role, setRole] = useState<Role>(roles[0]),
    [menu, setMenu] = useState(false),
    [toast, setToast] = useState(""),
    [globalSearch, setGlobalSearch] = useState("");
  const location = useLocation();
  const navigate = useNavigate();
  useWorkspaceTheme(role);
  const workspace = workspaceProfiles[role];
  const WorkspaceIcon = workspace.icon;
  const school = useRemote(
    findEndpoint("GET", "/school/context"),
    { organization_id: organization },
    0,
    !!organization,
  );
  const schoolName =
    school.data?.organization_id === organization && school.data?.name?.trim()
      ? school.data.name.trim()
      : t("Your school");
  useEffect(() => {
    setMenu(false);
    setGlobalSearch("");
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(t);
  }, [toast]);
  const years = useRemote(
    findEndpoint(
      "GET",
      role === "guardian" ? "/guardian/academic-years/" : "/academic-years/",
    ),
    {},
    revision,
    role !== "teacher",
  );
  const students = useRemote(
    findEndpoint(
      "GET",
      role === "guardian" ? "/guardian/students/" : "/students/",
    ),
    {},
    revision,
    role !== "teacher",
  );
  const [year, setYear] = useState("");
  const activeYear =
    year ||
    years.data?.find((y: Data) => y.status === "active")?.id ||
    years.data?.[0]?.id ||
    "";
  const classrooms = useRemote(
    findEndpoint(
      "GET",
      role === "teacher"
        ? "/teacher/classrooms/"
        : "/academic-years/{year_id}/classrooms/",
    ),
    { year_id: activeYear },
    revision,
    role === "teacher" || (role === "admin" && !!activeYear),
  );
  const [memberRevision, setMemberRevision] = useState(0);
  const members = useRemote(
    findEndpoint("GET", "/members/"),
    {},
    revision + memberRevision,
    role === "admin",
  );
  const memberChoices = (memberRole?: string) =>
    (members.data || [])
      .filter((m: Data) => !memberRole || m.roles.includes(memberRole))
      .map((m: Data) => ({ value: m.id, label: `${m.name} · ${m.email}` }));
  const choices: Choices = {
    ...(members.data
      ? {
          user_id: memberChoices(),
          teacher_workos_user_id: memberChoices("teacher"),
          guardian_workos_user_id: memberChoices("guardian"),
        }
      : {}),
    year_id: (years.data || []).map((y: Data) => ({
      value: y.id,
      label: y.name,
    })),
    academic_year_id: (years.data || []).map((y: Data) => ({
      value: y.id,
      label: y.name,
    })),
    student_id: (students.data || []).map((s: Data) => ({
      value: s.id,
      label: `${s.first_name} ${s.last_name}`,
    })),
    classroom_id: (classrooms.data || []).map((c: Data) => ({
      value: c.id,
      label: c.name,
    })),
  };
  const context = { year_id: activeYear };
  const filtered = pages[role].filter((p) =>
    `${t(p.title)} ${p.description}`
      .toLowerCase()
      .includes(globalSearch.toLowerCase()),
  );
  return (
    <ToastContext.Provider
      value={(message) => {
        setToast(message);
        setRevision((x) => x + 1);
      }}
    >
      <ChoicesContext.Provider value={choices}>
        <StudentGuardianContext.Provider value={{ enabled: role === "admin", students: students.data, members: members.data, loading: students.loading || members.loading, error: students.error || members.error }}>
        <div className="app-shell" data-role={role}>
          {menu && (
            <button
              className="sidebar-overlay"
              aria-label={t("Close navigation")}
              onClick={() => setMenu(false)}
            />
          )}
          <aside className={`sidebar ${menu ? "open" : ""}`}>
            <NavLink to="/" className="brand-link">
              <Brand />
            </NavLink>
            <div className="school-switch">
              <span className="school-avatar">
                <WorkspaceIcon size={20} />
              </span>
              <div>
                <strong>{schoolName}</strong>
                <span>{t(workspace.label)}</span>
              </div>
            </div>
            <p className="nav-label">{t("WORKSPACE")}</p>
            <nav aria-label={t("Main navigation")}>
              <NavLink to="/" end>
                <Home size={18} />
                <span>{t(workspace.home)}</span>
              </NavLink>
              {pages[role].map((p) => {
                const Icon = icons[p.key] || BookOpen;
                return (
                  <NavLink key={p.key} to={`/${p.key}`}>
                    <Icon size={18} />
                    <span>{t(p.title)}</span>
                    {p.key === "review" && <span className="nav-dot" />}
                  </NavLink>
                );
              })}
            </nav>
            <div className="sidebar-bottom">
              <div className="sidebar-card">
                <span>✦</span>
                <strong>{t("Better, together.")}</strong>
                <p>
                  {t(" A little connection makes ")}
                  <br />
                  {t("a big difference. ")}
                </p>
              </div>
              <button className="user-profile" onClick={onExit}>
                <span className="avatar">{name.slice(0, 1) || "C"}</span>
                <span>
                  <strong>{name || t("School member")}</strong>
                  <small>{email}</small>
                </span>
                <LogOut size={17} />
              </button>
            </div>
          </aside>
          <div className="main-shell">
            <header className="topbar">
              <button
                className="icon-button mobile-menu"
                aria-label={t("Open navigation")}
                onClick={() => setMenu(true)}
              >
                <Menu size={21} />
              </button>
              <WorkspaceIdentity
                role={role}
                schoolName={schoolName}
                page={
                  pages[role].find((p) =>
                    location.pathname === `/${p.key}` ||
                    location.pathname.startsWith(`/${p.key}/`),
                  )?.title || workspace.home
                }
              />
              <div className="topbar-right">
                <LanguageSwitch />
                <div className="global-search">
                  <Search size={16} />
                  <input
                    placeholder={t("Find a workspace…")}
                    aria-label={t("Find a workspace")}
                    value={globalSearch}
                    onChange={(e) => setGlobalSearch(e.target.value)}
                  />
                  {globalSearch && (
                    <div className="search-results">
                      {filtered.length ? (
                        filtered.map((p) => (
                          <NavLink to={`/${p.key}`} key={p.key}>
                            {t(p.title)}
                            <ArrowUpRight size={14} />
                          </NavLink>
                        ))
                      ) : (
                        <p>{t("No matching workspaces")}</p>
                      )}
                    </div>
                  )}
                </div>
                <WorkspaceSwitch
                  role={role}
                  roles={roles}
                  onChange={(next) => {
                    React.startTransition(() => {
                      setRole(next);
                      setYear("");
                      setMenu(false);
                      setGlobalSearch("");
                      navigate("/", { replace: true });
                    });
                  }}
                />
                <span className="topbar-avatar">{name[0] || "C"}</span>
              </div>
            </header>
            <main className="content" key={role}>
              {!organization && (
                <ErrorBox error="Your account is not linked to a school organization. Contact your administrator to enable school features." />
              )}
              {role !== "teacher" && !["/analytics", "/tutor", "/members", "/invitations", "/students", "/classrooms", "/academic-years", "/settings"].includes(location.pathname) && years.data?.length > 0 && (
                <div className="year-selector">
                  <CalendarDays size={14} />
                  <select
                    aria-label={t("Active academic year")}
                    value={activeYear}
                    onChange={(e) => setYear(e.target.value)}
                  >
                    {years.data.map((y: Data) => (
                      <option key={y.id} value={y.id}>
                        {y.name} · {y.status}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <Routes>
                <Route
                  path="/"
                  element={<Dashboard role={role} name={name} />}
                />
                {role === "admin" && (
                  <Route path="/updates/:updateId/reminder" element={<ReminderReviewPage />} />
                )}
                {role === "guardian" && <>
                  <Route path="/students" element={<Navigate to="/family" replace />} />
                  <Route path="/attendance" element={<Navigate to="/family" replace />} />
                </>}
                {pages[role].map((page) => (
                  <Route
                    key={page.key}
                    path={`/${page.key}`}
                    element={
                      role === "guardian" && page.key === "family" ? (
                        <GuardianFamilyPage />
                      ) : role === "admin" && page.key === "review" ? (
                        <NeedsReviewPage />
                      ) : role === "admin" && page.key === "invitations" ? (
                        <InvitationsPage />
                      ) : role === "admin" && page.key === "members" ? (
                        <SchoolMembersPage
                          members={members.data}
                          loading={members.loading}
                          error={members.error}
                          onRefresh={() => setMemberRevision((value) => value + 1)}
                        />
                      ) : role === "admin" && page.key === "academic-years" ? (
                        <AcademicYearsPage years={years} initialYear={activeYear} onYearChange={setYear} onRefresh={() => setRevision((value) => value + 1)} />
                      ) : role === "admin" && (page.key === "students" || page.key === "classrooms") ? (
                        <AcademicDirectoryPage key={page.key} mode={page.key} years={years} initialYear={activeYear} onYearChange={setYear} members={members} onRefreshYears={() => setRevision((value) => value + 1)} />
                      ) : role === "admin" && page.key === "settings" ? (
                        <SchoolSettingsPage />
                      ) : page.key === "analytics" ? (
                        <SchoolAnalyticsPage />
                      ) : page.key === "tutor" ? (
                        <GuardianTutorPage />
                      ) : role === "teacher" && page.key === "classrooms" ? (
                        <TeacherClassroomsPage classrooms={classrooms} onRefresh={() => setRevision((value) => value + 1)} />
                      ) : role === "teacher" && page.key === "attendance" ? (
                        <AttendancePage
                          choices={choices.classroom_id}
                          initialClassroom={
                            new URLSearchParams(location.search).get(
                              "classroom_id",
                            ) ||
                            choices.classroom_id?.[0]?.value ||
                            ""
                          }
                        />
                      ) : (
                        <ResourcePage
                          key={page.key}
                          page={page}
                          role={role}
                          choices={choices}
                          context={context}
                          schoolMembers={
                            role === "admin" && page.key === "registrations"
                              ? members.data ?? []
                              : undefined
                          }
                        />
                      )
                    }
                  />
                ))}
                <Route
                  path="*"
                  element={
                    <>
                      <Heading
                        eyebrow={t("WORKSPACE")}
                        title={t("Let’s find your way back.")}
                        description={t(
                          "This page is not available in your current workspace.",
                        )}
                      />
                      <NavLink className="button primary" to="/">
                        {t(" Return to overview ")}
                      </NavLink>
                    </>
                  }
                />
              </Routes>
              <footer className="content-footer">
                <span>Cortex School</span>
                <span>{t("Thoughtfully connected.")}</span>
              </footer>
            </main>
          </div>
          {toast && (
            <div className="toast" role="status">
              <Check size={18} />
              {toast}
              <button
                aria-label={t("Dismiss notification")}
                onClick={() => setToast("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
        </div>
        </StudentGuardianContext.Provider>
      </ChoicesContext.Provider>
    </ToastContext.Provider>
  );
}
function App() {
  useLanguage();
  const { user, isLoading } = useAuth();
  if (isLoading) return <Loading />;
  if (user) return <Authenticated key={user.id} />;
  return <Login />;
}
class AppBoundary extends React.Component<
  { children: React.ReactNode },
  { error: boolean }
> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    if (this.state.error)
      return (
        <div className="center-page">
          <h1>{t("Something interrupted your workspace.")}</h1>
          <p>{t("Reload the page to try again.")}</p>
          <button
            className="button primary"
            onClick={() => window.location.reload()}
          >
            {t(" Reload workspace ")}
          </button>
        </div>
      );
    return this.props.children;
  }
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LanguageProvider>
      <AppBoundary>
        <AuthKitProvider
          clientId={
            import.meta.env.VITE_WORKOS_CLIENT_ID ||
            "client_01KT21GY6QP06ZC02SWM7JKX20"
          }
          redirectUri={
            import.meta.env.VITE_WORKOS_REDIRECT_URI || window.location.origin
          }
          devMode={import.meta.env.VITE_WORKOS_DEV_MODE === "true" || undefined}
        >
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AuthKitProvider>
      </AppBoundary>
    </LanguageProvider>
  </React.StrictMode>,
);
