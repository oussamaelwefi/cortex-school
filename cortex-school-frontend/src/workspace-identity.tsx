import { useEffect } from "react";
import { ArrowRight, BookOpen, Building2, Heart } from "lucide-react";
import { Link } from "react-router-dom";
import { t } from "./i18n";
import type { Role } from "./types";

export const workspaceProfiles = {
  admin: {
    label: "School administration",
    icon: Building2,
    home: "School overview",
    title: "Manage your school",
    description:
      "Students, registrations, classrooms and school activity at a glance.",
    bannerTitle: "Your priorities, in one place.",
    bannerDescription:
      "Review pending requests and keep your school’s daily operations moving.",
    action: "Review pending requests",
    href: "/review",
    highlights: ["Registrations", "School members", "School analytics"],
  },
  teacher: {
    label: "Teacher workspace",
    icon: BookOpen,
    home: "My school day",
    title: "Your classes today",
    description:
      "Find your classes, record attendance and share updates with families.",
    bannerTitle: "Ready for your next class.",
    bannerDescription:
      "Open a class to find your students, take attendance or prepare a family update.",
    action: "Open my classes",
    href: "/classrooms",
    highlights: ["My classrooms", "Attendance", "Family updates"],
  },
  guardian: {
    label: "Family workspace",
    icon: Heart,
    home: "My family overview",
    title: "Your children’s school life",
    description:
      "Follow your children’s attendance, school updates and registration requests.",
    bannerTitle: "Stay close to their school day.",
    bannerDescription:
      "Find each child’s school information and the updates shared by their teachers.",
    action: "View my children",
    href: "/family",
    highlights: ["My children", "School updates", "Registration requests"],
  },
} as const;

export function useWorkspaceTheme(role: Role) {
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.dataset.workspaceRole;
    root.dataset.workspaceRole = role;
    return () => {
      if (previous === undefined) delete root.dataset.workspaceRole;
      else root.dataset.workspaceRole = previous;
    };
  }, [role]);
}

export function WorkspaceIdentity({
  role,
  schoolName,
  page,
}: {
  role: Role;
  schoolName: string;
  page: string;
}) {
  const profile = workspaceProfiles[role];
  const Icon = profile.icon;
  return (
    <div className="workspace-identity" aria-label={t("Current workspace")}>
      <span className="workspace-identity-icon" aria-hidden="true">
        <Icon size={21} />
      </span>
      <div>
        <strong>{t(profile.label)}</strong>
        <div className="workspace-location">
          <span title={schoolName}>{schoolName}</span>
          <span aria-hidden="true">/</span>
          <span title={t(page)}>{t(page)}</span>
        </div>
      </div>
    </div>
  );
}

export function WorkspaceSwitch({
  role,
  roles,
  onChange,
}: {
  role: Role;
  roles: Role[];
  onChange: (role: Role) => void;
}) {
  if (roles.length < 2) return null;
  return (
    <label className="workspace-switch">
      <span>{t("Switch workspace")}</span>
      <select
        className="role-switch"
        aria-label={t("Switch workspace role")}
        value={role}
        onChange={(event) => {
          const next = event.target.value as Role;
          if (roles.includes(next) && next !== role) onChange(next);
        }}
      >
        {roles.map((value) => (
          <option key={value} value={value}>
            {t(workspaceProfiles[value].label)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function WorkspaceWelcome({ role, name }: { role: Role; name: string }) {
  const workspace = workspaceProfiles[role];
  const Icon = workspace.icon;
  return (
    <section className="welcome-banner workspace-welcome">
      <div>
        <span className="banner-label">
          <Icon size={14} aria-hidden="true" />
          {t(`Good to see you${name ? `, ${name}` : ""}.`)}
        </span>
        <h2>{t(workspace.bannerTitle)}</h2>
        <p>{t(workspace.bannerDescription)}</p>
        <Link className="banner-link" to={workspace.href}>
          {t(workspace.action)} <ArrowRight size={17} />
        </Link>
        <div className="workspace-highlights">
          {workspace.highlights.map((highlight) => (
            <span key={highlight}>{t(highlight)}</span>
          ))}
        </div>
      </div>
      <div className="workspace-emblem" aria-hidden="true">
        <Icon size={76} strokeWidth={1.3} />
      </div>
    </section>
  );
}
