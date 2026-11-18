import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  GraduationCap,
  RefreshCw,
  Search,
  ShieldCheck,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { getLocale, t, useLanguage } from "./i18n";
import { label } from "./forms";
import { Empty, ErrorBox, Loading } from "./ui";
import type { SchoolMemberIdentity } from "./types";

export type SchoolMember = SchoolMemberIdentity & {
  membership_id: string;
  roles: string[];
  status: string;
  classrooms?: {
    id: string;
    name: string;
    academic_year_id: string;
    academic_year_name: string;
    assignment_role: string;
  }[];
  children?: { id: string; name: string }[];
};

const groups = [
  {
    key: "all",
    title: "All members",
    description: "Your whole school community",
    icon: Users,
  },
  {
    key: "school_admin",
    title: "Administrators",
    description: "School leadership and administration",
    icon: ShieldCheck,
  },
  {
    key: "teacher",
    title: "Teachers",
    description: "Your teaching team",
    icon: GraduationCap,
  },
  {
    key: "guardian",
    title: "Guardians",
    description: "Parents and family contacts",
    icon: Users,
  },
] as const;
const roleTitles: Record<string, string> = {
  school_admin: "Administrator",
  teacher: "Teacher",
  guardian: "Guardian",
};
const pageSize = 20;
const normalize = (text: string) =>
  text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase()
    .trim();
const roleTitle = (role: string) => t(roleTitles[role] ?? label(role));

export function membersCsv(members: SchoolMember[]) {
  const quote = (value: string) => {
    const safe = /^[\s]*[=+@\-\t\r]/.test(value) ? `'${value}` : value;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const rows = [
    [
      t("Name"),
      t("Email"),
      t("Roles"),
      t("Status"),
      t("Assigned classes"),
      t("Children"),
    ],
    ...members.map((member) => [
      member.name,
      member.email,
      member.roles.map(roleTitle).join("; "),
      label(member.status),
      (member.classrooms ?? [])
        .map(
          (classroom) => `${classroom.name} (${classroom.academic_year_name})`,
        )
        .join("; "),
      (member.children ?? []).map((child) => child.name).join("; "),
    ]),
  ];
  return "\uFEFF" + rows.map((row) => row.map(quote).join(",")).join("\r\n");
}

export function SchoolMembersPage({
  members,
  loading,
  error,
  onRefresh,
}: {
  members: SchoolMember[] | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
}) {
  useLanguage();
  const [params, setParams] = useSearchParams();
  const group =
    groups.find((entry) => entry.key === params.get("role")) ?? groups[0];
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("asc");
  const [page, setPage] = useState(0);
  const people = members ?? [];
  const query = normalize(search);
  const filtered = people
    .filter(
      (member) =>
        (group.key === "all" || member.roles.includes(group.key)) &&
        (!query ||
          normalize(
            `${member.name} ${member.email} ${(member.classrooms ?? []).map((classroom) => classroom.name).join(" ")} ${(member.children ?? []).map((child) => child.name).join(" ")}`,
          ).includes(query)),
    )
    .sort(
      (a, b) =>
        (sort === "asc" ? 1 : -1) *
        (a.name.localeCompare(b.name, getLocale(), { sensitivity: "base" }) ||
          a.email.localeCompare(b.email)),
    );
  const lastPage = Math.max(0, Math.ceil(filtered.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const visible = filtered.slice(
    currentPage * pageSize,
    (currentPage + 1) * pageSize,
  );
  const unavailable = loading || Boolean(error);
  const count = (value: number) =>
    t(value === 1 ? "1 member" : "{count} members").replace(
      "{count}",
      String(value),
    );

  function chooseGroup(key: string) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (key === "all") next.delete("role");
      else next.set("role", key);
      return next;
    });
    setPage(0);
  }
  function exportMembers() {
    const url = URL.createObjectURL(
      new Blob([membersCsv(filtered)], { type: "text/csv;charset=utf-8;" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `cortex-members-${group.key}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="school-members-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("SCHOOL MANAGEMENT")}</p>
          <h1>{t("School members")}</h1>
          <p>
            {t("Browse your school’s administrators, teachers, and guardians.")}
          </p>
        </div>
        <div className="heading-actions">
          <button
            type="button"
            className="button subtle"
            disabled={loading}
            onClick={onRefresh}
          >
            <RefreshCw size={15} />
            {t("Refresh")}
          </button>
          <Link to="/invitations" className="button primary">
            <UserPlus size={16} />
            {t("Manage invitations")}
          </Link>
        </div>
      </div>

      <section className="sm-groups" aria-label={t("Filter members by role")}>
        {groups.map(({ key, title, description, icon: Icon }) => (
          <button
            key={key}
            type="button"
            aria-pressed={group.key === key}
            aria-controls="school-member-directory"
            onClick={() => chooseGroup(key)}
          >
            <span className="sm-group-top">
              <span className="sm-group-icon">
                <Icon size={20} aria-hidden="true" />
              </span>
              <strong>
                {unavailable
                  ? "—"
                  : key === "all"
                    ? people.length
                    : people.filter((member) => member.roles.includes(key))
                        .length}
              </strong>
            </span>
            <span className="sm-group-title">
              {t(title)}
              {group.key === key && <Check size={14} aria-hidden="true" />}
            </span>
            <span className="sm-group-description">{t(description)}</span>
          </button>
        ))}
      </section>
      {people.some((member) => member.roles.length > 1) && !unavailable && (
        <p className="sm-multiple-roles">
          {t("Members with multiple roles appear in each relevant group.")}
        </p>
      )}

      <section
        className="panel sm-directory"
        id="school-member-directory"
        aria-label={t("Member directory")}
        aria-busy={loading}
      >
        <div className="sm-directory-heading">
          <div>
            <h2>{t(group.title)}</h2>
            <span aria-live="polite">
              {unavailable
                ? t("Active school accounts")
                : count(filtered.length)}
            </span>
          </div>
          <span className="sm-active-note">
            <span />
            {t("Active school accounts")}
          </span>
        </div>
        <div className="sm-toolbar">
          <label className="search-input">
            <Search size={17} aria-hidden="true" />
            <span className="sr-only">{t("Search school members")}</span>
            <input
              type="search"
              value={search}
              disabled={unavailable}
              placeholder={t("Search by name or email…")}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
            />
            {search && (
              <button
                type="button"
                className="icon-button"
                aria-label={t("Clear search")}
                onClick={() => {
                  setSearch("");
                  setPage(0);
                }}
              >
                <X size={14} />
              </button>
            )}
          </label>
          <div className="sm-tools">
            <label className="sm-sort">
              <span>{t("Sort by")}</span>
              <select
                aria-label={t("Sort members")}
                value={sort}
                disabled={unavailable}
                onChange={(event) => {
                  setSort(event.target.value);
                  setPage(0);
                }}
              >
                <option value="asc">{t("Name: A to Z")}</option>
                <option value="desc">{t("Name: Z to A")}</option>
              </select>
            </label>
            <button
              type="button"
              className="button subtle small"
              disabled={unavailable || filtered.length === 0}
              onClick={exportMembers}
            >
              <Download size={14} />
              {t("Export CSV")}
            </button>
          </div>
        </div>

        {loading ? (
          <Loading />
        ) : error ? (
          <div className="sm-error">
            <ErrorBox error={error} retry={onRefresh} />
          </div>
        ) : filtered.length === 0 ? (
          <div className="sm-empty">
            <Empty
              title={
                query
                  ? "No matching members"
                  : people.length === 0
                    ? "No school members yet"
                    : "No members in this group yet"
              }
              text={
                query
                  ? "Try a different name or email, or choose another group."
                  : "Members appear here after accepting their school invitation."
              }
            />
            {query ? (
              <button
                type="button"
                className="button subtle"
                onClick={() => {
                  setSearch("");
                  setPage(0);
                }}
              >
                {t("Clear search")}
              </button>
            ) : (
              <Link to="/invitations" className="button subtle">
                {t("Manage invitations")}
                <ArrowRight size={14} />
              </Link>
            )}
          </div>
        ) : (
          <>
            <div className="table-wrap sm-table-wrap">
              <table
                className={
                  group.key !== "school_admin" ? "sm-has-relations" : ""
                }
              >
                <caption className="sr-only">{t(group.title)}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t("Member")}</th>
                    <th scope="col">{t("Email")}</th>
                    <th scope="col">{t("Roles")}</th>
                    {group.key !== "school_admin" && (
                      <th scope="col">
                        {t(
                          group.key === "teacher"
                            ? "Assigned classes"
                            : group.key === "guardian"
                              ? "Children"
                              : "Classes and children",
                        )}
                      </th>
                    )}
                    <th scope="col">{t("Status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((member) => (
                    <tr key={member.membership_id}>
                      <td>
                        <div className="sm-member">
                          <span className="sm-avatar" aria-hidden="true">
                            {member.name
                              .trim()
                              .split(/\s+/)
                              .slice(0, 2)
                              .map((part) => part[0])
                              .join("")
                              .toLocaleUpperCase()}
                          </span>
                          <strong>{member.name}</strong>
                        </div>
                      </td>
                      <td className="sm-email">
                        <a href={`mailto:${member.email}`}>{member.email}</a>
                      </td>
                      <td>
                        <div className="sm-roles">
                          {member.roles.length ? (
                            member.roles.map((role) => (
                              <span
                                className="sm-role"
                                data-role={role}
                                key={role}
                              >
                                {roleTitle(role)}
                              </span>
                            ))
                          ) : (
                            <span className="sm-no-role">
                              {t("No role assigned")}
                            </span>
                          )}
                        </div>
                      </td>
                      {group.key !== "school_admin" && (
                        <td className="sm-relations">
                          {(group.key === "all" || group.key === "teacher") &&
                            member.roles.includes("teacher") && (
                              <div>
                                {group.key === "all" && (
                                  <span className="sm-relation-label">
                                    {t("Assigned classes")}
                                  </span>
                                )}
                                {member.classrooms?.length ? (
                                  <ul>
                                    {member.classrooms.map((classroom) => (
                                      <li key={classroom.id}>
                                        <Link
                                          to={`/classrooms?year_id=${encodeURIComponent(classroom.academic_year_id)}&classroom_id=${encodeURIComponent(classroom.id)}`}
                                        >
                                          {classroom.name}
                                          <ArrowRight size={11} />
                                        </Link>
                                        <small>
                                          {classroom.academic_year_name} ·{" "}
                                          {t(
                                            classroom.assignment_role === "lead"
                                              ? "Lead teacher"
                                              : "Assistant teacher",
                                          )}
                                        </small>
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <span className="sm-no-role">
                                    {t("No current class assignments")}
                                  </span>
                                )}
                              </div>
                            )}
                          {(group.key === "all" || group.key === "guardian") &&
                            member.roles.includes("guardian") && (
                              <div>
                                {group.key === "all" && (
                                  <span className="sm-relation-label">
                                    {t("Children")}
                                  </span>
                                )}
                                {member.children?.length ? (
                                  <ul>
                                    {member.children.map((child) => (
                                      <li key={child.id}>
                                        <Link
                                          to={`/students?student_id=${encodeURIComponent(child.id)}`}
                                        >
                                          {child.name}
                                          <ArrowRight size={11} />
                                        </Link>
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <span className="sm-no-role">
                                    {t("No children linked")}
                                  </span>
                                )}
                              </div>
                            )}
                          {!member.roles.some(
                            (role) => role === "teacher" || role === "guardian",
                          ) && <span className="sm-no-role">—</span>}
                        </td>
                      )}
                      <td>
                        <span
                          className={`sm-status ${member.status === "active" ? "is-active" : ""}`}
                        >
                          <span />
                          {label(member.status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <footer className="sm-pagination">
              <span>
                {t("Showing {from}–{to} of {total}")
                  .replace("{from}", String(currentPage * pageSize + 1))
                  .replace(
                    "{to}",
                    String(
                      Math.min((currentPage + 1) * pageSize, filtered.length),
                    ),
                  )
                  .replace("{total}", String(filtered.length))}
              </span>
              <div>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t("Previous members page")}
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  <ChevronLeft size={17} />
                </button>
                <span>
                  {t("Page {page} of {total}")
                    .replace("{page}", String(currentPage + 1))
                    .replace("{total}", String(lastPage + 1))}
                </span>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t("Next members page")}
                  disabled={currentPage === lastPage}
                  onClick={() => setPage(currentPage + 1)}
                >
                  <ChevronRight size={17} />
                </button>
              </div>
            </footer>
          </>
        )}
      </section>
      <p className="sm-invitation-note">
        {t("Waiting for someone to join?")}{" "}
        <Link to="/invitations">
          {t("Track pending invitations")}
          <ArrowRight size={12} />
        </Link>
      </p>
    </div>
  );
}
