import { useContext, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  BookOpen,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Download,
  GraduationCap,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Users,
} from "lucide-react";
import { endpoints, findEndpoint } from "./api";
import { getLocale, t, useLanguage } from "./i18n";
import {
  Badge,
  ChoicesContext,
  Empty,
  ErrorBox,
  Loading,
  Modal,
  Operation,
  useRemote,
} from "./ui";
import type { Data, Endpoint, SchoolMemberIdentity } from "./types";
import { StudentGuardianContext, StudentGuardians } from "./student-guardians";

type Year = { id: string; name: string; status: string };
type Remote<T> = { data: T | null; loading: boolean; error: string };
type Attendance = {
  present: number;
  late: number;
  absent: number;
  excused: number;
  recorded_days: number;
  rate: number | null;
};
export type DirectoryStudent = {
  id: string;
  first_name: string;
  last_name: string;
  enrollment_id: string | null;
  placement_id: string | null;
  classroom_id: string | null;
  attendance: Attendance;
  guardian_ids?: string[];
};
type Teacher = {
  id: string;
  teacher_workos_user_id: string;
  role: string;
  effective_from: string;
  effective_until: string | null;
};
type Classroom = {
  id: string;
  name: string;
  teachers: Teacher[];
  student_ids: string[];
};
export type AcademicDirectory = {
  year_id: string;
  year_name: string;
  year_status: string;
  school_date: string;
  roster_date: string;
  attendance_from: string;
  attendance_through: string | null;
  classrooms: Classroom[];
  students: DirectoryStudent[];
};
type OperationState = {
  endpoint: Endpoint;
  context: Data;
  seed?: Data;
  recordName?: string;
};
const directoryEndpoint = findEndpoint(
  "GET",
  "/academic-years/{year_id}/directory/",
);
const fullName = (student: DirectoryStudent) =>
  `${student.first_name} ${student.last_name}`;
const normalized = (text: string) =>
  text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase()
    .trim();
const dateLabel = (value: string) =>
  new Date(`${value}T12:00:00Z`).toLocaleDateString(getLocale(), {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
const classHref = (year: string, classroom: string) =>
  `/classrooms?year_id=${encodeURIComponent(year)}&classroom_id=${encodeURIComponent(classroom)}`;
const studentHref = (year: string, student: string) =>
  `/students?year_id=${encodeURIComponent(year)}&student_id=${encodeURIComponent(student)}`;

export function studentDirectoryCsv(
  students: DirectoryStudent[],
  directory: AcademicDirectory,
) {
  const quote = (value: string) =>
    `"${(/^[\s]*[=+@\-\t\r]/.test(value) ? "'" + value : value).replaceAll('"', '""')}"`;
  const rows = [
    [
      t("Student"),
      t("Academic year"),
      t("Classroom"),
      t("Attendance rate"),
      t("Recorded days"),
    ],
    ...students.map((student) => [
      fullName(student),
      directory.year_name,
      directory.classrooms.find(
        (classroom) => classroom.id === student.classroom_id,
      )?.name ?? "",
      student.attendance.rate === null
        ? ""
        : `${student.attendance.rate.toFixed(1)}%`,
      String(student.attendance.recorded_days),
    ]),
  ];
  return "\uFEFF" + rows.map((row) => row.map(quote).join(",")).join("\r\n");
}

export function AttendanceRate({ attendance }: { attendance: Attendance }) {
  return (
    <div className="ad-attendance">
      {attendance.rate === null ? (
        <>
          <strong>—</strong>
          <small>{t("No attendance records yet")}</small>
        </>
      ) : (
        <>
          <div>
            <strong>
              {new Intl.NumberFormat(getLocale(), {
                maximumFractionDigits: 1,
                style: "percent",
              }).format(attendance.rate / 100)}
            </strong>
            <span>
              {t("{attended} of {total} days")
                .replace(
                  "{attended}",
                  String(attendance.present + attendance.late),
                )
                .replace("{total}", String(attendance.recorded_days))}
            </span>
          </div>
          <span className="ad-rate-track" aria-hidden="true">
            <span style={{ width: `${attendance.rate}%` }} />
          </span>
        </>
      )}
    </div>
  );
}

function TeacherList({
  teachers,
  members,
  compact = false,
}: {
  teachers: Teacher[];
  members: Remote<SchoolMemberIdentity[]>;
  compact?: boolean;
}) {
  if (!teachers.length)
    return <p className="ad-muted">{t("No teacher assigned")}</p>;
  return (
    <ul className={`ad-teachers ${compact ? "compact" : ""}`}>
      {(compact ? teachers.slice(0, 2) : teachers).map((assignment) => {
        const person = members.data?.find(
          (member) => member.id === assignment.teacher_workos_user_id,
        );
        return (
          <li key={assignment.id}>
            <GraduationCap size={16} aria-hidden="true" />
            <span>
              <strong>
                {person?.name ??
                  t(
                    members.loading
                      ? "Loading teacher…"
                      : "Teacher details unavailable",
                  )}
              </strong>
              {!compact && person?.email && <small>{person.email}</small>}
            </span>
            <span className="ad-teacher-role">
              {t(
                assignment.role === "lead"
                  ? "Lead teacher"
                  : "Assistant teacher",
              )}
            </span>
          </li>
        );
      })}
      {compact && teachers.length > 2 && (
        <li className="ad-muted">
          {t("+{count} more teachers").replace(
            "{count}",
            String(teachers.length - 2),
          )}
        </li>
      )}
    </ul>
  );
}

function RosterTable({
  students,
  directory,
  onOpen,
}: {
  students: DirectoryStudent[];
  directory: AcademicDirectory;
  onOpen?: (student: DirectoryStudent) => void;
}) {
  const guardianSource = useContext(StudentGuardianContext);
  return (
    <div className="table-wrap ad-table">
      <table>
        <thead>
          <tr>
            <th>{t("Student")}</th>
            <th>{t("Classroom")}</th>
            {guardianSource.enabled && <th>{t("Guardians")}</th>}
            <th>{t("Attendance rate")}</th>
          </tr>
        </thead>
        <tbody>
          {students.map((student) => {
            const classroom = directory.classrooms.find(
              (entry) => entry.id === student.classroom_id,
            );
            return (
              <tr key={student.id}>
                <td>
                  {onOpen ? (
                    <button
                      className="record-button"
                      onClick={() => onOpen(student)}
                    >
                      {fullName(student)}
                    </button>
                  ) : (
                    <Link
                      className="ad-student-link"
                      to={studentHref(directory.year_id, student.id)}
                    >
                      {fullName(student)}
                    </Link>
                  )}
                </td>
                <td>
                  {classroom ? (
                    <Link
                      className="ad-class-link"
                      to={classHref(directory.year_id, classroom.id)}
                    >
                      <BookOpen size={14} />
                      {classroom.name}
                      <ArrowRight size={13} />
                    </Link>
                  ) : (
                    <span className="ad-muted">
                      {t(
                        student.enrollment_id
                          ? "Awaiting class placement"
                          : "Not enrolled this year",
                      )}
                    </span>
                  )}
                </td>
                {guardianSource.enabled && (
                  <td>
                    <StudentGuardians
                      studentId={student.id}
                      guardianIds={student.guardian_ids}
                    />
                  </td>
                )}
                <td>
                  <AttendanceRate attendance={student.attendance} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function AcademicDirectoryPage({
  mode,
  years,
  initialYear,
  onYearChange,
  members,
  onRefreshYears,
}: {
  mode: "classrooms" | "students";
  years: Remote<Year[]>;
  initialYear: string;
  onYearChange: (year: string) => void;
  members: Remote<SchoolMemberIdentity[]>;
  onRefreshYears?: () => void;
}) {
  useLanguage();
  const inheritedChoices = useContext(ChoicesContext);
  const [params, setParams] = useSearchParams();
  const yearId = params.get("year_id") || initialYear;
  const [refresh, setRefresh] = useState(0),
    [search, setSearch] = useState(""),
    [sort, setSort] = useState("name"),
    [page, setPage] = useState(0);
  const [operation, setOperation] = useState<OperationState | null>(null),
    [workflows, setWorkflows] = useState(false);
  const state = useRemote(
    directoryEndpoint,
    { year_id: yearId },
    refresh,
    Boolean(yearId) && !years.loading,
  );
  const directory =
    state.data?.year_id === yearId ? (state.data as AcademicDirectory) : null;
  const loading =
    years.loading ||
    (Boolean(yearId) && !state.error && (!directory || state.loading));
  const error = years.error || state.error;
  const classroomFilter = params.get("class_filter") || "all";
  const query = normalized(search);
  const title = mode === "classrooms" ? "Classrooms" : "Students";
  const students = directory?.students ?? [],
    classrooms = directory?.classrooms ?? [];
  const selectedClass = classrooms.find(
    (entry) => entry.id === params.get("classroom_id"),
  );
  const selectedStudent = students.find(
    (entry) => entry.id === params.get("student_id"),
  );
  const filteredStudents = students
    .filter((student) => {
      const classroom = classrooms.find(
        (entry) => entry.id === student.classroom_id,
      );
      return (
        (!query ||
          normalized(`${fullName(student)} ${classroom?.name ?? ""}`).includes(
            query,
          )) &&
        (classroomFilter === "all" ||
          (classroomFilter === "unplaced"
            ? Boolean(student.enrollment_id) && !student.classroom_id
            : classroomFilter === "not_enrolled"
              ? !student.enrollment_id
              : student.classroom_id === classroomFilter))
      );
    })
    .sort((a, b) =>
      sort === "attendance"
        ? (b.attendance.rate ?? -1) - (a.attendance.rate ?? -1) ||
          fullName(a).localeCompare(fullName(b), getLocale())
        : fullName(a).localeCompare(fullName(b), getLocale()),
    );
  const filteredClasses = classrooms.filter(
    (classroom) =>
      !query ||
      normalized(
        `${classroom.name} ${classroom.teachers.map((assignment) => members.data?.find((member) => member.id === assignment.teacher_workos_user_id)?.name ?? "").join(" ")}`,
      ).includes(query),
  );
  const resultLength =
    mode === "students" ? filteredStudents.length : filteredClasses.length;
  const lastPage = Math.max(0, Math.ceil(resultLength / 20) - 1),
    currentPage = Math.min(page, lastPage);
  const slice = <T,>(rows: T[]) =>
    rows.slice(currentPage * 20, (currentPage + 1) * 20);
  const reload = () => {
    if (years.error) onRefreshYears?.();
    setRefresh((value) => value + 1);
  };
  const choices = {
    ...inheritedChoices,
    year_id: (years.data ?? []).map((year) => ({
      value: year.id,
      label: year.name,
    })),
    academic_year_id: (years.data ?? []).map((year) => ({
      value: year.id,
      label: year.name,
    })),
    classroom_id: classrooms.map((classroom) => ({
      value: classroom.id,
      label: classroom.name,
    })),
    enrollment_id: students
      .filter((student) => student.enrollment_id)
      .map((student) => ({
        value: student.enrollment_id!,
        label: fullName(student),
      })),
  };
  function setQuery(next: Record<string, string | null>) {
    setParams((previous) => {
      const result = new URLSearchParams(previous);
      Object.entries(next).forEach(([key, value]) =>
        value === null ? result.delete(key) : result.set(key, value),
      );
      return result;
    });
  }
  function openOperation(
    id: string,
    context: Data = {},
    seed?: Data,
    recordName?: string,
  ) {
    const endpoint = endpoints.find((entry) => entry.id === id);
    if (endpoint)
      setOperation({
        endpoint,
        context: { year_id: yearId, academic_year_id: yearId, ...context },
        seed,
        recordName,
      });
  }
  const selectedContext = selectedClass
    ? { classroom_id: selectedClass.id }
    : selectedStudent
      ? {
          student_id: selectedStudent.id,
          enrollment_id: selectedStudent.enrollment_id,
        }
      : {};
  const missingClass =
    directory && params.get("classroom_id") && !selectedClass;
  const missingStudent =
    directory && params.get("student_id") && !selectedStudent;

  function exportStudents() {
    if (!directory) return;
    const url = URL.createObjectURL(
      new Blob([studentDirectoryCsv(filteredStudents, directory)], {
        type: "text/csv;charset=utf-8;",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "cortex-students.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <ChoicesContext.Provider value={choices}>
      <div className="academic-directory-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{t("SCHOOL MANAGEMENT")}</p>
            <h1>{t(title)}</h1>
            <p>
              {t(
                mode === "classrooms"
                  ? "Your classes, teaching teams, and students in one place."
                  : "Every student’s class and attendance, together in one directory.",
              )}
            </p>
          </div>
          <div className="heading-actions">
            <button
              className="button subtle"
              disabled={loading}
              onClick={reload}
            >
              <RefreshCw size={15} />
              {t("Refresh")}
            </button>
            <button
              className="button subtle"
              onClick={() => setWorkflows(!workflows)}
              aria-expanded={workflows}
            >
              <Settings2 size={15} />
              {t("All workflows")}
            </button>
            <button
              className="button primary"
              disabled={
                mode === "classrooms" &&
                (!yearId || loading || directory?.year_status === "closed")
              }
              onClick={() =>
                openOperation(
                  mode === "classrooms" ? "create_classroom" : "create_student",
                )
              }
            >
              <Plus size={16} />
              {t(mode === "classrooms" ? "Create classroom" : "Add student")}
            </button>
          </div>
        </div>
        <div className="ad-year-bar">
          <label>
            <CalendarDays size={17} />
            <span>{t("Academic year")}</span>
            <select
              aria-label={t("Academic year")}
              value={yearId}
              disabled={years.loading || !years.data?.length}
              onChange={(event) => {
                setQuery({
                  year_id: event.target.value,
                  classroom_id: null,
                  student_id: null,
                  class_filter: null,
                });
                onYearChange(event.target.value);
                setSearch("");
                setPage(0);
              }}
            >
              {!years.data?.length && (
                <option value="">{t("Choose an academic year")}</option>
              )}
              {years.data?.map((year) => (
                <option value={year.id} key={year.id}>
                  {year.name}
                </option>
              ))}
            </select>
          </label>
          {directory && !loading && (
            <>
              <Badge value={directory.year_status} />
              <span className="ad-roster-date">
                {t("Roster as of {date}").replace(
                  "{date}",
                  dateLabel(directory.roster_date),
                )}
              </span>
            </>
          )}
        </div>
        {workflows && (
          <section className="panel ad-workflows">
            <h2>{t("All workflows")}</h2>
            <div className="record-actions">
              {endpoints
                .filter(
                  (entry) =>
                    entry.module ===
                      (mode === "classrooms" ? "classrooms" : "students") &&
                    entry.id !== "get_academic_year_directory",
                )
                .map((entry) => (
                  <button
                    key={entry.id}
                    className="button small subtle"
                    onClick={() => openOperation(entry.id, selectedContext)}
                  >
                    {t(entry.title)}
                    <ArrowRight size={13} />
                  </button>
                ))}
            </div>
          </section>
        )}
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorBox error={error} retry={reload} />
        ) : !yearId ? (
          <section className="panel">
            <Empty
              title="Choose an academic year"
              text="Create or select an academic year to view classes and student attendance."
            />
            <div className="ad-empty-action">
              <Link className="button primary" to="/academic-years">
                {t("Academic years")}
                <ArrowRight size={14} />
              </Link>
            </div>
          </section>
        ) : (
          directory && (
            <>
              <div className="ad-stats">
                {(mode === "classrooms"
                  ? [
                      [BookOpen, "Classrooms", classrooms.length],
                      [
                        GraduationCap,
                        "Assigned teachers",
                        new Set(
                          classrooms.flatMap((classroom) =>
                            classroom.teachers.map(
                              (teacher) => teacher.teacher_workos_user_id,
                            ),
                          ),
                        ).size,
                      ],
                      [
                        Users,
                        "Placed students",
                        students.filter((student) => student.classroom_id)
                          .length,
                      ],
                    ]
                  : [
                      [Users, "Students", students.length],
                      [
                        BookOpen,
                        "Placed students",
                        students.filter((student) => student.classroom_id)
                          .length,
                      ],
                      [
                        CalendarDays,
                        "Awaiting class placement",
                        students.filter(
                          (student) =>
                            student.enrollment_id && !student.classroom_id,
                        ).length,
                      ],
                    ]
                ).map(([Icon, label, value]: any) => (
                  <div key={label}>
                    <span className="ad-stat-icon">
                      <Icon size={20} />
                    </span>
                    <div>
                      <strong>{value}</strong>
                      <span>{t(label)}</span>
                    </div>
                  </div>
                ))}
              </div>
              {members.error && mode === "classrooms" && (
                <p className="ad-data-note" role="status">
                  {t(
                    "Teacher names could not be loaded. Refresh School members to try again.",
                  )}{" "}
                  <Link to="/members">{t("School members")}</Link>
                </p>
              )}
              <section
                className={
                  mode === "students" ? "panel ad-results" : "ad-results"
                }
              >
                <div className="ad-toolbar">
                  <label className="search-input">
                    <Search size={17} />
                    <span className="sr-only">
                      {t(
                        mode === "classrooms"
                          ? "Search classrooms"
                          : "Search students",
                      )}
                    </span>
                    <input
                      type="search"
                      value={search}
                      placeholder={t(
                        mode === "classrooms"
                          ? "Search by class or teacher…"
                          : "Search by student or class…",
                      )}
                      onChange={(event) => {
                        setSearch(event.target.value);
                        setPage(0);
                      }}
                    />
                  </label>
                  <div className="ad-filter-controls">
                    {mode === "students" && (
                      <>
                        <select
                          aria-label={t("Filter students by class")}
                          value={classroomFilter}
                          onChange={(event) => {
                            setQuery({ class_filter: event.target.value });
                            setPage(0);
                          }}
                        >
                          <option value="all">{t("All students")}</option>
                          {classrooms.map((classroom) => (
                            <option key={classroom.id} value={classroom.id}>
                              {classroom.name}
                            </option>
                          ))}
                          <option value="unplaced">
                            {t("Awaiting class placement")}
                          </option>
                          <option value="not_enrolled">
                            {t("Not enrolled this year")}
                          </option>
                        </select>
                        <select
                          aria-label={t("Sort students")}
                          value={sort}
                          onChange={(event) => {
                            setSort(event.target.value);
                            setPage(0);
                          }}
                        >
                          <option value="name">{t("Name: A to Z")}</option>
                          <option value="attendance">
                            {t("Attendance: highest first")}
                          </option>
                        </select>
                      </>
                    )}
                    {mode === "students" && (
                      <button
                        className="icon-button"
                        aria-label={t("Export students as CSV")}
                        title={t("Export students as CSV")}
                        disabled={!filteredStudents.length}
                        onClick={exportStudents}
                      >
                        <Download size={16} />
                      </button>
                    )}
                    <span>
                      {t(
                        resultLength === 1 ? "1 result" : "{count} results",
                      ).replace("{count}", String(resultLength))}
                    </span>
                  </div>
                </div>
                {resultLength === 0 ? (
                  <Empty
                    title={
                      search || classroomFilter !== "all"
                        ? "No matching records"
                        : mode === "classrooms"
                          ? "No classrooms in this academic year"
                          : "No students yet"
                    }
                    text={
                      search || classroomFilter !== "all"
                        ? "Try another search or filter."
                        : mode === "classrooms"
                          ? "Create a classroom to start building your teaching teams and student rosters."
                          : "Add a student to start organizing your school records."
                    }
                  />
                ) : mode === "students" ? (
                  <RosterTable
                    students={slice(filteredStudents)}
                    directory={directory}
                    onOpen={(student) => setQuery({ student_id: student.id })}
                  />
                ) : (
                  <div className="ad-class-grid">
                    {slice(filteredClasses).map((classroom) => (
                      <article
                        className="panel ad-class-card"
                        key={classroom.id}
                      >
                        <header>
                          <span className="ad-class-icon">
                            <BookOpen size={22} />
                          </span>
                          <div>
                            <h2>{classroom.name}</h2>
                            <span>{directory.year_name}</span>
                          </div>
                        </header>
                        <div className="ad-card-teachers">
                          <span className="ad-section-label">
                            {t("Teaching team")}
                          </span>
                          <TeacherList
                            teachers={classroom.teachers}
                            members={members}
                            compact
                          />
                        </div>
                        <footer>
                          <span>
                            <Users size={15} />
                            {t(
                              classroom.student_ids.length === 1
                                ? "1 student"
                                : "{count} students",
                            ).replace(
                              "{count}",
                              String(classroom.student_ids.length),
                            )}
                          </span>
                          <button
                            className="button small subtle"
                            aria-label={`${t("View class")} · ${classroom.name}`}
                            onClick={() =>
                              setQuery({ classroom_id: classroom.id })
                            }
                          >
                            {t("View class")}
                            <ArrowRight size={14} />
                          </button>
                        </footer>
                      </article>
                    ))}
                  </div>
                )}
                {resultLength > 0 && (
                  <footer className="ad-pagination">
                    <span>
                      {t("Showing {from}–{to} of {total}")
                        .replace("{from}", String(currentPage * 20 + 1))
                        .replace(
                          "{to}",
                          String(Math.min(currentPage * 20 + 20, resultLength)),
                        )
                        .replace("{total}", String(resultLength))}
                    </span>
                    <div>
                      <button
                        className="icon-button"
                        aria-label={t("Previous page")}
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
                        className="icon-button"
                        aria-label={t("Next page")}
                        disabled={currentPage === lastPage}
                        onClick={() => setPage(currentPage + 1)}
                      >
                        <ChevronRight size={17} />
                      </button>
                    </div>
                  </footer>
                )}
              </section>
              <p className="ad-attendance-note">
                {t(
                  "Attendance rate includes present and late days. Only recorded days are counted.",
                )}{" "}
                {directory.attendance_through
                  ? `${dateLabel(directory.attendance_from)} – ${dateLabel(directory.attendance_through)}`
                  : t(
                      "Attendance recording has not started for this academic year.",
                    )}
              </p>
            </>
          )
        )}
        {!loading && !error && (missingClass || missingStudent) && (
          <ErrorBox
            error={t(
              "This record is not available in the selected academic year.",
            )}
          />
        )}
        {directory && !loading && !operation && selectedClass && (
          <Modal
            title={selectedClass.name}
            subtitle={`${directory.year_name} · ${t("Roster as of {date}").replace("{date}", dateLabel(directory.roster_date))}`}
            wide
            onClose={() => setQuery({ classroom_id: null })}
          >
            <div className="modal-body ad-class-detail">
              <div className="ad-detail-heading">
                <h3>{t("Teaching team")}</h3>
                {directory.year_status !== "closed" && (
                  <button
                    className="button small subtle"
                    onClick={() =>
                      openOperation(
                        "create_teacher_assignment",
                        { classroom_id: selectedClass.id },
                        undefined,
                        selectedClass.name,
                      )
                    }
                  >
                    <Plus size={14} />
                    {t("Assign teacher")}
                  </button>
                )}
              </div>
              <TeacherList
                teachers={selectedClass.teachers}
                members={members}
              />
              <div className="ad-detail-heading">
                <h3>
                  {t("Class students")}{" "}
                  <span>{selectedClass.student_ids.length}</span>
                </h3>
                {directory.year_status !== "closed" && (
                  <button
                    className="button small subtle"
                    onClick={() =>
                      openOperation(
                        "create_class_placement",
                        { classroom_id: selectedClass.id },
                        { effective_from: directory.roster_date },
                        selectedClass.name,
                      )
                    }
                  >
                    <Plus size={14} />
                    {t("Place student")}
                  </button>
                )}
              </div>
              {selectedClass.student_ids.length ? (
                <RosterTable
                  students={students.filter((student) =>
                    selectedClass.student_ids.includes(student.id),
                  )}
                  directory={directory}
                />
              ) : (
                <Empty
                  title="No students placed in this class"
                  text="Students will appear here once their class placement begins."
                />
              )}
            </div>
            <footer>
              {directory.year_status !== "closed" && (
                <button
                  className="button subtle"
                  onClick={() =>
                    openOperation(
                      "replace_classroom",
                      { classroom_id: selectedClass.id },
                      selectedClass,
                      selectedClass.name,
                    )
                  }
                >
                  {t("Edit classroom")}
                </button>
              )}
              <button
                className="button primary"
                onClick={() => setQuery({ classroom_id: null })}
              >
                {t("Close")}
              </button>
            </footer>
          </Modal>
        )}
        {directory && !loading && !operation && selectedStudent && (
          <Modal
            title={fullName(selectedStudent)}
            subtitle={directory.year_name}
            wide
            onClose={() => setQuery({ student_id: null })}
          >
            <div className="modal-body ad-student-detail">
              <div className="ad-student-class">
                <BookOpen size={19} />
                <div>
                  <span>{t("Classroom")}</span>
                  {selectedStudent.classroom_id ? (
                    <Link
                      className="ad-class-link"
                      to={classHref(
                        directory.year_id,
                        selectedStudent.classroom_id,
                      )}
                    >
                      {
                        classrooms.find(
                          (entry) => entry.id === selectedStudent.classroom_id,
                        )?.name
                      }
                      <ArrowRight size={14} />
                    </Link>
                  ) : (
                    <strong>
                      {t(
                        selectedStudent.enrollment_id
                          ? "Awaiting class placement"
                          : "Not enrolled this year",
                      )}
                    </strong>
                  )}
                </div>
              </div>
              <h3>{t("Attendance this academic year")}</h3>
              <AttendanceRate attendance={selectedStudent.attendance} />
              <div className="ad-status-counts">
                {(["present", "late", "absent", "excused"] as const).map(
                  (status) => (
                    <div key={status}>
                      <strong>{selectedStudent.attendance[status]}</strong>
                      <Badge value={status} />
                    </div>
                  ),
                )}
              </div>
              <p className="ad-muted">
                {t(
                  "Attendance rate includes present and late days. Only recorded days are counted.",
                )}
              </p>
              <section className="ad-student-guardians">
                <h3>{t("Guardians")}</h3>
                <StudentGuardians
                  studentId={selectedStudent.id}
                  guardianIds={selectedStudent.guardian_ids}
                  details
                />
              </section>
              <div className="record-actions">
                <button
                  className="button small subtle"
                  onClick={() =>
                    openOperation(
                      "update_student",
                      { student_id: selectedStudent.id },
                      selectedStudent,
                      fullName(selectedStudent),
                    )
                  }
                >
                  {t("Edit student")}
                </button>
                <button
                  className="button small subtle"
                  onClick={() =>
                    openOperation(
                      "add_guardian",
                      { student_id: selectedStudent.id },
                      undefined,
                      fullName(selectedStudent),
                    )
                  }
                >
                  {t("Link guardian")}
                </button>
                {!selectedStudent.enrollment_id &&
                  directory.year_status !== "closed" && (
                    <button
                      className="button small subtle"
                      onClick={() =>
                        openOperation(
                          "create_enrollment",
                          { student_id: selectedStudent.id },
                          { academic_year_id: directory.year_id },
                          fullName(selectedStudent),
                        )
                      }
                    >
                      {t("Enroll student")}
                    </button>
                  )}
                <button
                  className="button small subtle"
                  onClick={() =>
                    openOperation(
                      "list_student_enrollments",
                      { student_id: selectedStudent.id },
                      undefined,
                      fullName(selectedStudent),
                    )
                  }
                >
                  {t("Enrollment history")}
                </button>
              </div>
            </div>
            <footer>
              <button
                className="button primary"
                onClick={() => setQuery({ student_id: null })}
              >
                {t("Close")}
              </button>
            </footer>
          </Modal>
        )}
        {operation && (
          <Operation
            endpoint={operation.endpoint}
            context={operation.context}
            seed={operation.seed}
            recordName={operation.recordName}
            onClose={() => setOperation(null)}
            onDone={reload}
          />
        )}
      </div>
    </ChoicesContext.Provider>
  );
}
