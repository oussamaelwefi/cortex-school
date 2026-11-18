import {
  useContext,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CalendarDays,
  CalendarOff,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  Coffee,
  GraduationCap,
  Mail,
  RefreshCw,
  Search,
  Sun,
  Users,
} from "lucide-react";
import { findEndpoint } from "./api";
import { getLocale, t, useLanguage } from "./i18n";
import { ChoicesContext, ErrorBox, Loading, Operation, useRemote } from "./ui";

export type TeacherClassroom = {
  id: string;
  name: string;
  academic_year_id: string;
  assignment_role: "lead" | "assistant";
  assignment_effective_from: string;
  assignment_effective_until: string | null;
  access_status: "current" | "upcoming";
};
type Student = {
  student_id: string;
  first_name: string;
  last_name: string;
  effective_from: string;
  effective_until: string | null;
};
type TodayClass = {
  id: string;
  active_student_count: number;
  attendance: {
    status: "not_started" | "submitted";
    recorded_student_count: number;
  };
};
type Today = {
  school_date: string;
  can_submit_attendance: boolean;
  classrooms: TodayClass[];
};
type CalendarEntry = {
  id: string;
  title: string;
  entry_type: "term" | "holiday" | "break" | "non_instruction_day";
  starts_on: string;
  ends_on: string;
};
type Remote<T> = { data: T | null; loading: boolean; error: string };
type Composer = { classroom: TeacherClassroom; student?: Student };
const todayEndpoint = findEndpoint("GET", "/teacher/today");
const rosterEndpoint = findEndpoint(
  "GET",
  "/teacher/classrooms/{classroom_id}/students/",
);
const calendarEndpoint = findEndpoint(
  "GET",
  "/teacher/classrooms/{classroom_id}/calendar/",
);
const updateEndpoint = findEndpoint("POST", "/teacher/updates/");
const calendarLabels = {
  term: "Teaching period",
  holiday: "Public holiday",
  break: "School break",
  non_instruction_day: "Non-teaching day",
};
const calendarIcons = {
  term: BookOpen,
  holiday: Sun,
  break: Coffee,
  non_instruction_day: CalendarOff,
};

function date(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(getLocale(), {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
function fullName(student: Student) {
  return `${student.first_name} ${student.last_name}`;
}
function Access({ classroom }: { classroom: TeacherClassroom }) {
  return (
    <span className={`tc-access ${classroom.access_status}`}>
      <span />
      {t(
        classroom.access_status === "current"
          ? "Current assignment"
          : "Upcoming assignment",
      )}
    </span>
  );
}
function Role({ classroom }: { classroom: TeacherClassroom }) {
  return (
    <span className="tc-role">
      <GraduationCap size={14} />
      {t(
        classroom.assignment_role === "lead"
          ? "Lead teacher"
          : "Assistant teacher",
      )}
    </span>
  );
}
function AssignmentDates({ classroom }: { classroom: TeacherClassroom }) {
  return (
    <span className="tc-assignment-dates">
      <CalendarDays size={14} />
      <span>
        {t("Assigned from")}{" "}
        <time dateTime={classroom.assignment_effective_from}>
          {date(classroom.assignment_effective_from)}
        </time>
        {classroom.assignment_effective_until && (
          <>
            {" "}
            · {t("Ends on")}{" "}
            <time dateTime={classroom.assignment_effective_until}>
              {date(classroom.assignment_effective_until)}
            </time>
          </>
        )}
      </span>
    </span>
  );
}
function AttendanceLink({
  classroom,
  primary = false,
}: {
  classroom: TeacherClassroom;
  primary?: boolean;
}) {
  const content = (
    <>
      <ClipboardCheck size={16} />
      {t("Attendance")}
    </>
  );
  return classroom.access_status === "current" ? (
    <Link
      className={`button small ${primary ? "primary" : "subtle"}`}
      to={`/attendance?classroom_id=${encodeURIComponent(classroom.id)}`}
    >
      {content}
    </Link>
  ) : (
    <button
      className="button small subtle"
      disabled
      title={t("Available when your assignment starts.")}
    >
      {content}
    </button>
  );
}
function MessageButton({
  onClick,
  children,
}: {
  onClick: () => void;
  children?: ReactNode;
}) {
  return (
    <button className="button small subtle" onClick={onClick}>
      <Mail size={15} />
      {children ?? t("Write to families")}
    </button>
  );
}

function ClassCard({
  classroom,
  today,
  schoolDate,
  canSubmit,
  onOpen,
  onCompose,
}: {
  classroom: TeacherClassroom;
  today?: TodayClass;
  schoolDate?: string;
  canSubmit?: boolean;
  onOpen: () => void;
  onCompose: () => void;
}) {
  const upcoming = classroom.access_status === "upcoming";
  return (
    <article className={`tc-class-card ${upcoming ? "upcoming" : ""}`}>
      <header>
        <span className="tc-class-icon">
          <BookOpen size={24} />
        </span>
        <Access classroom={classroom} />
      </header>
      <h2>{classroom.name}</h2>
      <Role classroom={classroom} />
      <div className="tc-card-day">
        {today ? (
          <>
            <div className="tc-student-count">
              <Users size={18} />
              <strong>{today.active_student_count}</strong>
              <span>{t("Students today")}</span>
            </div>
            <p
              className={`tc-attendance-state ${today.attendance.status === "submitted" ? "submitted" : ""}`}
            >
              {today.attendance.status === "submitted" ? (
                <CheckCircle2 size={14} />
              ) : (
                <Clock3 size={14} />
              )}
              <span>
                {t(
                  today.attendance.status === "submitted"
                    ? "Attendance saved"
                    : canSubmit === false
                      ? "No attendance expected today"
                      : "Attendance not recorded",
                )}
              </span>
            </p>
            {schoolDate && (
              <time className="tc-school-date" dateTime={schoolDate}>
                {date(schoolDate)}
              </time>
            )}
          </>
        ) : (
          <div className="tc-card-preparation">
            <Users size={19} />
            <p>
              {t(
                upcoming
                  ? "Get to know the class calendar before your assignment begins."
                  : "Open the class to see its current students.",
              )}
            </p>
          </div>
        )}
      </div>
      <AssignmentDates classroom={classroom} />
      <footer>
        <div className="tc-card-actions">
          <AttendanceLink classroom={classroom} primary />
          <button className="button small subtle" onClick={onOpen}>
            {t("Open class")}
            <ArrowRight size={15} />
          </button>
        </div>
        {upcoming ? (
          <p className="tc-upcoming-help">
            {t(
              "Attendance and messages are available when your assignment starts.",
            )}
          </p>
        ) : (
          <button className="tc-compose-link" onClick={onCompose}>
            <Mail size={14} />
            {t("Write to families")}
            <ArrowRight size={13} />
          </button>
        )}
      </footer>
    </article>
  );
}

function ClassWorkspace({
  classroom,
  onBack,
  onCompose,
  onRefresh,
  revision,
}: {
  classroom: TeacherClassroom;
  onBack: () => void;
  onCompose: (student?: Student) => void;
  onRefresh: () => void;
  revision: number;
}) {
  const [tab, setTab] = useState<"students" | "calendar">("students");
  const [calendarOpened, setCalendarOpened] = useState(false);
  const [query, setQuery] = useState("");
  const roster = useRemote(
    rosterEndpoint,
    { classroom_id: classroom.id },
    revision,
  );
  const calendar = useRemote(
    calendarEndpoint,
    { classroom_id: classroom.id },
    revision,
    calendarOpened,
  );
  const students: Student[] = roster.data ?? [];
  const visible = students
    .filter((student) =>
      fullName(student)
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()),
    )
    .sort(
      (a, b) =>
        a.last_name.localeCompare(b.last_name, getLocale()) ||
        a.first_name.localeCompare(b.first_name, getLocale()),
    );
  const entries: CalendarEntry[] = [...(calendar.data?.entries ?? [])].sort(
    (a, b) =>
      a.starts_on.localeCompare(b.starts_on) ||
      a.title.localeCompare(b.title, getLocale()),
  );
  const current = classroom.access_status === "current";
  const panelId = `classroom-${classroom.id}`;
  function selectTab(next: "students" | "calendar") {
    if (next === "calendar") setCalendarOpened(true);
    setTab(next);
  }
  function navigateTabs(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? "students"
        : event.key === "End"
          ? "calendar"
          : tab === "students"
            ? "calendar"
            : "students";
    selectTab(next);
    event.currentTarget
      .querySelectorAll<HTMLButtonElement>('[role="tab"]')
      [next === "students" ? 0 : 1]?.focus();
  }

  return (
    <>
      <button className="tc-back" onClick={onBack}>
        <ArrowLeft size={15} />
        {t("Back to my classes")}
      </button>
      <section className="tc-detail-heading">
        <span className="tc-detail-icon">
          <BookOpen size={28} />
        </span>
        <div>
          <div className="tc-detail-title">
            <h2>{classroom.name}</h2>
            <Access classroom={classroom} />
          </div>
          <Role classroom={classroom} />
          <AssignmentDates classroom={classroom} />
        </div>
        <div className="tc-detail-actions">
          <button
            className="icon-button"
            aria-label={t("Refresh class")}
            onClick={onRefresh}
          >
            <RefreshCw size={16} />
          </button>
          <AttendanceLink classroom={classroom} primary />
          {current && <MessageButton onClick={() => onCompose()} />}
        </div>
      </section>
      {!current && (
        <div className="tc-upcoming-note">
          <Clock3 size={19} />
          <div>
            <strong>{t("Prepare for your upcoming class")}</strong>
            <p>
              {t(
                "You can consult the calendar now. Students appear as their placements become current; attendance and messages follow your assignment dates.",
              )}
            </p>
          </div>
        </div>
      )}
      <section className="tc-class-content">
        <div
          className="tc-tabs"
          role="tablist"
          aria-label={t("Class details")}
          onKeyDown={navigateTabs}
        >
          <button
            id={`${panelId}-students-tab`}
            role="tab"
            aria-selected={tab === "students"}
            tabIndex={tab === "students" ? 0 : -1}
            aria-controls={`${panelId}-students`}
            onClick={() => selectTab("students")}
          >
            <Users size={17} />
            {t("Students")}
            {!roster.loading && !roster.error && roster.data !== null && (
              <span>{students.length}</span>
            )}
          </button>
          <button
            id={`${panelId}-calendar-tab`}
            role="tab"
            aria-selected={tab === "calendar"}
            tabIndex={tab === "calendar" ? 0 : -1}
            aria-controls={`${panelId}-calendar`}
            onClick={() => selectTab("calendar")}
          >
            <CalendarDays size={17} />
            {t("Calendar")}
          </button>
        </div>
        {tab === "students" ? (
          <div
            role="tabpanel"
            id={`${panelId}-students`}
            aria-labelledby={`${panelId}-students-tab`}
          >
            <div className="tc-roster-heading">
              <div>
                <h3>{t("Class roster")}</h3>
                <p>{t("Students currently enrolled in this class.")}</p>
              </div>
              <label className="tc-search">
                <Search size={16} />
                <input
                  type="search"
                  aria-label={t("Search students in this class")}
                  placeholder={t("Find a student…")}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
            </div>
            {roster.loading ? (
              <Loading />
            ) : roster.error ? (
              <div className="tc-panel-error">
                <ErrorBox error={roster.error} retry={onRefresh} />
              </div>
            ) : visible.length ? (
              <ul className="tc-roster">
                {visible.map((student) => (
                  <li key={student.student_id}>
                    <span className="tc-student-avatar">
                      {student.first_name[0]}
                      {student.last_name[0]}
                    </span>
                    <div>
                      <strong>{fullName(student)}</strong>
                      <span>
                        {t("In this class since")}{" "}
                        <time dateTime={student.effective_from}>
                          {date(student.effective_from)}
                        </time>
                      </span>
                    </div>
                    {current && (
                      <button
                        className="button subtle small"
                        aria-label={`${t("Write an update")} · ${fullName(student)}`}
                        onClick={() => onCompose(student)}
                      >
                        <Mail size={14} />
                        <span>{t("Write an update")}</span>
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="tc-empty">
                <Users size={31} />
                <h3>
                  {t(
                    students.length
                      ? "No matching student"
                      : "No current students yet",
                  )}
                </h3>
                <p>
                  {t(
                    students.length
                      ? "Try another name to find a student in this class."
                      : "Students will appear here when their class placements are active.",
                  )}
                </p>
              </div>
            )}
          </div>
        ) : (
          <div
            role="tabpanel"
            id={`${panelId}-calendar`}
            aria-labelledby={`${panelId}-calendar-tab`}
          >
            <div className="tc-roster-heading">
              <div>
                <h3>{t("Class calendar")}</h3>
                <p>
                  {t("Teaching periods and days off shared by your school.")}
                </p>
              </div>
              <span className="tc-read-only">
                <CalendarDays size={14} />
                {t("Set by the school")}
              </span>
            </div>
            {calendar.loading ? (
              <Loading />
            ) : calendar.error ? (
              <div className="tc-panel-error">
                <ErrorBox error={calendar.error} retry={onRefresh} />
              </div>
            ) : entries.length ? (
              <ul className="tc-calendar-events">
                {entries.map((entry) => {
                  const Icon = calendarIcons[entry.entry_type];
                  return (
                    <li key={entry.id}>
                      <span className={`tc-calendar-icon ${entry.entry_type}`}>
                        <Icon size={19} />
                      </span>
                      <div>
                        <strong>{entry.title}</strong>
                        <span>{t(calendarLabels[entry.entry_type])}</span>
                      </div>
                      <p>
                        <time dateTime={entry.starts_on}>
                          {date(entry.starts_on)}
                        </time>
                        {entry.ends_on !== entry.starts_on && (
                          <>
                            <span aria-hidden="true">—</span>
                            <time dateTime={entry.ends_on}>
                              {date(entry.ends_on)}
                            </time>
                          </>
                        )}
                      </p>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="tc-empty">
                <CalendarDays size={31} />
                <h3>{t("No calendar events yet")}</h3>
                <p>
                  {t(
                    "Teaching periods, holidays, and school breaks will appear here once added by your school.",
                  )}
                </p>
              </div>
            )}
          </div>
        )}
      </section>
    </>
  );
}

export function TeacherClassroomsPage({
  classrooms,
  onRefresh,
}: {
  classrooms: Remote<TeacherClassroom[]>;
  onRefresh: () => void;
}) {
  useLanguage();
  const baseChoices = useContext(ChoicesContext);
  const heading = useRef<HTMLHeadingElement>(null);
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [revision, setRevision] = useState(0);
  const [composer, setComposer] = useState<Composer | null>(null);
  const today = useRemote(todayEndpoint, {}, revision);
  const daily: Today | undefined = today.data;
  const records = [...(classrooms.data ?? [])].sort(
    (a, b) =>
      (a.access_status === b.access_status
        ? 0
        : a.access_status === "current"
          ? -1
          : 1) || a.name.localeCompare(b.name, getLocale(), { numeric: true }),
  );
  const selectedId = params.get("classroom_id");
  const selected = records.find((classroom) => classroom.id === selectedId);
  const visible = records.filter(
    (classroom) =>
      (filter === "all" || classroom.access_status === filter) &&
      classroom.name
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()),
  );
  function open(classroom?: TeacherClassroom) {
    setParams((before) => {
      const next = new URLSearchParams(before);
      if (classroom) next.set("classroom_id", classroom.id);
      else next.delete("classroom_id");
      return next;
    });
    heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }
  function refresh() {
    setRevision((value) => value + 1);
    onRefresh();
  }
  const choices = {
    ...baseChoices,
    classroom_id: records.map((classroom) => ({
      value: classroom.id,
      label: classroom.name,
    })),
  };

  return (
    <ChoicesContext.Provider value={choices}>
      <div className="teacher-classrooms-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{t("TEACHER WORKSPACE")}</p>
            <h1 ref={heading} tabIndex={-1}>
              {t("My classrooms")}
            </h1>
            <p>
              {t(
                "Your students, attendance, and class calendars, all in one place.",
              )}
            </p>
          </div>
          <div className="heading-actions">
            <button
              className="button subtle"
              disabled={classrooms.loading}
              onClick={refresh}
            >
              <RefreshCw
                size={16}
                className={classrooms.loading ? "spin" : ""}
              />
              {t("Refresh")}
            </button>
          </div>
        </div>
        {classrooms.loading ? (
          <Loading />
        ) : classrooms.error ? (
          <ErrorBox error={classrooms.error} retry={refresh} />
        ) : selectedId ? (
          selected ? (
            <ClassWorkspace
              key={selected.id}
              classroom={selected}
              revision={revision}
              onBack={() => open()}
              onCompose={(student) =>
                setComposer({ classroom: selected, student })
              }
              onRefresh={refresh}
            />
          ) : (
            <div className="tc-empty tc-no-access">
              <BookOpen size={32} />
              <h2>{t("This class is not in your current assignments")}</h2>
              <p>
                {t(
                  "Return to your classes or refresh to see your latest assignments.",
                )}
              </p>
              <button className="button primary" onClick={() => open()}>
                <ArrowLeft size={15} />
                {t("Back to my classes")}
              </button>
            </div>
          )
        ) : !records.length ? (
          <div className="tc-empty tc-no-access">
            <BookOpen size={36} />
            <h2>{t("Your classes will be here")}</h2>
            <p>
              {t(
                "Once your school assigns you to a class in a published year, you will find its students and calendar here.",
              )}
            </p>
            <button className="button subtle" onClick={refresh}>
              <RefreshCw size={15} />
              {t("Refresh")}
            </button>
          </div>
        ) : (
          <>
            <div className="tc-toolbar">
              <div
                className="tc-filters"
                role="group"
                aria-label={t("Filter class assignments")}
              >
                {[
                  ["all", "All my classes"],
                  ["current", "Current assignments"],
                  ["upcoming", "Upcoming assignments"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    aria-pressed={filter === key}
                    onClick={() => setFilter(key)}
                  >
                    {t(label)}
                    <span>
                      {key === "all"
                        ? records.length
                        : records.filter(
                            (classroom) => classroom.access_status === key,
                          ).length}
                    </span>
                  </button>
                ))}
              </div>
              <label className="tc-search">
                <Search size={16} />
                <input
                  type="search"
                  aria-label={t("Search my classes")}
                  placeholder={t("Find a class…")}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
            </div>
            {today.error && (
              <details className="tc-overview-error">
                <summary>
                  {t("Today’s attendance overview is unavailable")}
                </summary>
                <ErrorBox
                  error={today.error}
                  retry={() => setRevision((value) => value + 1)}
                />
              </details>
            )}
            {visible.length ? (
              <div className="tc-class-grid">
                {visible.map((classroom) => (
                  <ClassCard
                    key={classroom.id}
                    classroom={classroom}
                    today={daily?.classrooms.find(
                      (entry) => entry.id === classroom.id,
                    )}
                    schoolDate={daily?.school_date}
                    canSubmit={daily?.can_submit_attendance}
                    onOpen={() => open(classroom)}
                    onCompose={() => setComposer({ classroom })}
                  />
                ))}
              </div>
            ) : (
              <div className="tc-empty tc-no-match">
                <Search size={29} />
                <h3>{t("No classes match these filters")}</h3>
                <p>{t("Try another class name or assignment status.")}</p>
                <button
                  className="button subtle"
                  onClick={() => {
                    setFilter("all");
                    setQuery("");
                  }}
                >
                  {t("Show all my classes")}
                </button>
              </div>
            )}
            <p className="tc-footnote">
              <GraduationCap size={15} />
              {t(
                "Your school manages class assignments. This workspace follows your assigned access dates.",
              )}
            </p>
          </>
        )}
        {composer && (
          <Operation
            endpoint={updateEndpoint}
            recordName={
              composer.student
                ? `${composer.classroom.name} · ${fullName(composer.student)}`
                : composer.classroom.name
            }
            seed={{
              classroom_id: composer.classroom.id,
              target: composer.student
                ? {
                    type: "students",
                    student_ids: [composer.student.student_id],
                  }
                : { type: "classroom" },
            }}
            submitLabel="Publish update"
            onClose={() => setComposer(null)}
            onDone={refresh}
          />
        )}
      </div>
    </ChoicesContext.Provider>
  );
}
