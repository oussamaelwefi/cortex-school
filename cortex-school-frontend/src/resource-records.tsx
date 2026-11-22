import {
  BarChart3,
  Bell,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  CircleAlert,
  Layers,
  MessageSquareText,
  UserPlus,
} from "lucide-react";
import type { Choices } from "./forms";
import { getLocale, t } from "./i18n";
import type { Data, Role } from "./types";
import { Badge, display, RegistrationRequester, type RecordTable } from "./ui";

export const resourceIcons = {
  enrollments: Layers,
  attendance: ClipboardCheck,
  updates: MessageSquareText,
  registrations: UserPlus,
  feed: BookOpen,
  notifications: Bell,
};

export const resourceCopy = {
  enrollments: {
    list: "Enrollment history",
    empty: "No enrollments yet",
    note: "This student’s enrollments will appear here.",
  },
  attendance: {
    list: "Classroom submissions",
    empty: "No classrooms expected",
    note: "Choose another date to check classroom submissions.",
  },
  updates: {
    list: "Updates",
    empty: "No student updates",
    note: "Student updates will appear here when teachers send them.",
  },
  registrations: {
    list: "Requests",
    empty: "No registration requests",
    note: "Submitted registration requests will appear here.",
  },
  feed: {
    list: "Classroom feed",
    empty: "No school updates",
    note: "Updates from your child’s teachers will appear here.",
  },
  notifications: {
    list: "Inbox",
    empty: "No notifications",
    note: "Notifications from your school will appear here.",
  },
};

export type ResourceKey = keyof typeof resourceCopy;

export function resourceKey(role: Role, key: string): ResourceKey | undefined {
  if (
    role === "admin" &&
    ["enrollments", "attendance", "updates", "registrations"].includes(key)
  )
    return key as ResourceKey;
  if (role === "teacher" && key === "updates") return key;
  if (
    role === "guardian" &&
    (key === "registrations" || key === "feed" || key === "notifications")
  )
    return key;
}

export function dateLabel(value: string | null | undefined) {
  if (!value) return "—";
  const schoolDate = /^\d{4}-\d{2}-\d{2}$/.test(value);
  return new Date(schoolDate ? `${value}T00:00:00Z` : value).toLocaleDateString(
    getLocale(),
    { dateStyle: "medium", ...(schoolDate ? { timeZone: "UTC" } : {}) },
  );
}

export function yearLabel(choices: Choices, id: string) {
  return choices.academic_year_id?.find((year) => year.value === id)?.label;
}

export function recordTable(
  key: ResourceKey | undefined,
  role: Role,
  choices: Choices,
): RecordTable | undefined {
  const academicYear = {
    label: "Academic year",
    value: (row: Data) => yearLabel(choices, row.academic_year_id) ?? "—",
  };
  const status = {
    label: "Status",
    value: (row: Data) => (
      <span className="resource-badges">
        <Badge value={row.status} />
        {row.is_overdue && <Badge value="overdue" />}
      </span>
    ),
  };
  const created = (label: string) => ({
    label,
    value: (row: Data) => dateLabel(row.created_at),
  });

  switch (key) {
    case "enrollments":
      return {
        primaryLabel: "Academic year",
        title: (row) =>
          yearLabel(choices, row.academic_year_id) ?? t("Enrollment"),
        columns: [
          created("Enrolled on"),
          { label: "Last updated", value: (row) => dateLabel(row.updated_at) },
        ],
      };
    case "attendance":
      return {
        primaryLabel: "Classroom",
        title: (row) => row.classroom_name,
        subtitle: (row) => row.academic_year_name,
        columns: [
          status,
          {
            label: "Recorded students",
            value: (row) =>
              `${display(row.recorded_student_count)} / ${display(row.active_student_count)}`,
          },
          ...["Present", "Late", "Absent", "Excused"].map((label) => ({
            label,
            value: (row: Data) => display(row.counts?.[label.toLowerCase()]),
          })),
          { label: "Submitted at", value: (row) => display(row.submitted_at) },
        ],
      };
    case "updates":
      return {
        primaryLabel: "Update",
        title: (row) => row.title,
        subtitle: (row) => row.classroom_name,
        columns: [
          ...(role === "admin"
            ? [
                {
                  label: "Student",
                  value: (row: Data) =>
                    [row.student_first_name, row.student_last_name]
                      .filter(Boolean)
                      .join(" ") || "—",
                },
                status,
              ]
            : [
                {
                  label: "Recipients",
                  value: (row: Data) => display(row.recipient_count),
                },
              ]),
          { label: "Due date", value: (row) => display(row.due_at) },
          created("Sent on"),
        ],
      };
    case "registrations":
      return {
        primaryLabel: "Child",
        title: (row) =>
          [row.child_first_name, row.child_last_name]
            .filter(Boolean)
            .join(" ") || t("Child"),
        columns: [
          ...(role === "admin"
            ? [
                {
                  label: "Requested by",
                  value: (row: Data) => <RegistrationRequester row={row} />,
                },
              ]
            : []),
          academicYear,
          status,
          created("Requested on"),
        ],
      };
  }
}

export function AttendanceOverview({ summary }: { summary: Data }) {
  return (
    <dl className="resource-metrics" aria-label={t("Attendance summary")}>
      {[
        {
          name: "Expected classrooms",
          value: summary.expected_classroom_count,
          icon: BarChart3,
          tone: "expected",
        },
        {
          name: "Submitted registers",
          value: summary.submitted_classroom_count,
          icon: CheckCircle2,
          tone: "submitted",
        },
        {
          name: "Missing registers",
          value: summary.missing_classroom_count,
          icon: CircleAlert,
          tone: "missing",
        },
      ].map(({ name, value, icon: Icon, tone }) => (
        <div className="resource-metric" data-tone={tone} key={name}>
          <span className="resource-metric-icon">
            <Icon size={20} aria-hidden="true" />
          </span>
          <dt>{t(name)}</dt>
          <dd>{display(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
