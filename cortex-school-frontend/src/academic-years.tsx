import { useContext, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  BookOpen,
  CalendarDays,
  CalendarOff,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Coffee,
  Edit3,
  LockKeyhole,
  Plus,
  RefreshCw,
  Search,
  Send,
  Sun,
  Trash2,
} from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { getLocale, t, useLanguage } from "./i18n";
import { ErrorBox, Loading, Modal, ToastContext, useRemote } from "./ui";

export type AcademicYear = {
  id: string;
  name: string;
  starts_on: string;
  ends_on: string;
  status: "draft" | "active" | "closed";
};
type EntryType = "term" | "holiday" | "break" | "non_instruction_day";
export type CalendarEntry = {
  id: string;
  title: string;
  entry_type: EntryType;
  starts_on: string;
  ends_on: string;
};
type Readiness = { can_publish: boolean; errors: string[]; warnings: string[] };
type Editor =
  | { kind: "year"; year?: AcademicYear }
  | {
      kind: "entry";
      year: AcademicYear;
      entry?: CalendarEntry;
      entryType?: EntryType;
    };
type Action =
  | { kind: "publish"; year: AcademicYear }
  | { kind: "close"; year: AcademicYear }
  | {
      kind: "delete";
      year: AcademicYear;
      entry: CalendarEntry;
    };
const calendarEndpoint = findEndpoint(
  "GET",
  "/academic-years/{year_id}/calendar/",
);
const readinessEndpoint = findEndpoint(
  "GET",
  "/academic-years/{year_id}/readiness/",
);
const statusLabels = { draft: "Draft", active: "Active", closed: "Closed" };
const entryLabels: Record<EntryType, string> = {
  term: "Teaching period",
  holiday: "Public holiday",
  break: "School break",
  non_instruction_day: "Non-teaching day",
};
const entryIcons = {
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
function Dates({ start, end }: { start: string; end: string }) {
  return (
    <span className="ay-dates">
      <time dateTime={start}>{date(start)}</time>
      <span aria-hidden="true">—</span>
      <time dateTime={end}>{date(end)}</time>
    </span>
  );
}
function Status({ status }: { status: AcademicYear["status"] }) {
  return (
    <span className={`ay-status ${status}`}>
      <span />
      {t(statusLabels[status])}
    </span>
  );
}
function readinessMessage(message: string) {
  const missingTeachers = message.match(
    /^(\d+) classroom\(s\) have no teacher assignment$/,
  );
  const missingPlacements = message.match(
    /^(\d+) enrollment\(s\) have no class placement$/,
  );
  if (missingTeachers)
    return t("{count} classes have no teacher assigned.").replace(
      "{count}",
      missingTeachers[1],
    );
  if (missingPlacements)
    return t("{count} enrollments have no class placement.").replace(
      "{count}",
      missingPlacements[1],
    );
  return t(message);
}

function EditorDialog({
  editor,
  onClose,
  onSaved,
}: {
  editor: Editor;
  onClose: () => void;
  onSaved: (yearId?: string) => void;
}) {
  const api = useApi();
  const toast = useContext(ToastContext);
  const entry = editor.kind === "entry" ? editor.entry : undefined;
  const [name, setName] = useState(
    entry?.title ?? (editor.kind === "year" ? editor.year?.name : "") ?? "",
  );
  const [start, setStart] = useState(
    entry?.starts_on ?? editor.year?.starts_on ?? "",
  );
  const [end, setEnd] = useState(entry?.ends_on ?? editor.year?.ends_on ?? "");
  const [entryType, setEntryType] = useState<EntryType>(
    entry?.entry_type ??
      (editor.kind === "entry" ? editor.entryType : undefined) ??
      "term",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const isYear = editor.kind === "year";
  const editing = isYear ? Boolean(editor.year) : Boolean(entry);
  const title = isYear
    ? editing
      ? "Edit academic year"
      : "Create academic year"
    : editing
      ? "Edit calendar event"
      : "Add calendar event";

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (isYear ? end <= start : end < start) {
      setError(
        t(
          isYear
            ? "The end date must be after the start date."
            : "The end date cannot be before the start date.",
        ),
      );
      return;
    }
    if (
      !isYear &&
      editor.year &&
      (start < editor.year.starts_on || end > editor.year.ends_on)
    ) {
      setError(t("Calendar entries must fall within the academic year"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const endpoint = isYear
        ? editing
          ? findEndpoint("PUT", "/academic-years/{year_id}/")
          : findEndpoint("POST", "/academic-years/")
        : findEndpoint(
            editing ? "PUT" : "POST",
            editing
              ? "/academic-years/{year_id}/calendar/entries/{entry_id}/"
              : "/academic-years/{year_id}/calendar/entries/",
          );
      const result = await api(
        endpoint,
        { year_id: editor.year?.id, entry_id: entry?.id },
        {
          ...(isYear
            ? { name: name.trim() }
            : { title: name.trim(), entry_type: entryType }),
          starts_on: start,
          ends_on: end,
        },
      );
      toast(
        t(
          isYear
            ? editing
              ? "Academic year updated"
              : "Academic year created as draft"
            : "Calendar saved",
        ),
      );
      onSaved(isYear ? result.id : undefined);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title={title}
      subtitle={editor.year?.name}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="ay-editor" onSubmit={submit}>
        <div className="modal-body">
          {isYear && !editing && (
            <p className="ay-form-help">
              {t(
                "Start with the dates. Add a teaching period, then publish when you are ready.",
              )}
            </p>
          )}
          {!isYear && (
            <label className="field">
              <span>{t("Event type")}</span>
              <select
                value={entryType}
                onChange={(e) => setEntryType(e.target.value as EntryType)}
                disabled={busy}
              >
                {Object.entries(entryLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {t(label)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>{t(isYear ? "Year name" : "Event title")}</span>
            <input
              type="text"
              required
              autoFocus
              maxLength={isYear ? 32 : 255}
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              placeholder={t(
                isYear
                  ? "e.g. 2026–2027"
                  : entryType === "term"
                    ? "e.g. First term"
                    : "e.g. School holiday",
              )}
            />
          </label>
          <div className="ay-date-fields">
            <label className="field">
              <span>{t("Start date")}</span>
              <input
                required
                type="date"
                value={start}
                min={isYear ? undefined : editor.year?.starts_on}
                max={isYear ? undefined : editor.year?.ends_on}
                onChange={(e) => setStart(e.target.value)}
                disabled={busy}
              />
            </label>
            <label className="field">
              <span>{t("End date")}</span>
              <input
                required
                type="date"
                value={end}
                min={
                  isYear ? start || undefined : start || editor.year?.starts_on
                }
                max={isYear ? undefined : editor.year?.ends_on}
                onChange={(e) => setEnd(e.target.value)}
                disabled={busy}
              />
            </label>
          </div>
          {!isYear && (
            <p className="ay-form-help">
              {t("Keep this event within the school year’s dates.")}
            </p>
          )}
          {error && <ErrorBox error={error} />}
        </div>
        <footer>
          <button
            type="button"
            className="button subtle"
            onClick={onClose}
            disabled={busy}
          >
            {t("Cancel")}
          </button>
          <button
            type="submit"
            className="button primary"
            disabled={busy || !name.trim()}
          >
            {busy ? (
              <RefreshCw size={15} className="spin" />
            ) : (
              <Check size={15} />
            )}
            {t(
              busy
                ? "Saving…"
                : isYear
                  ? editing
                    ? "Save changes"
                    : "Create academic year"
                  : "Save event",
            )}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function ActionDialog({
  action,
  onClose,
  onSaved,
}: {
  action: Action;
  onClose: () => void;
  onSaved: () => void;
}) {
  const api = useApi();
  const toast = useContext(ToastContext);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Recheck on opening the publication dialog; the backend validates once more on POST.
  const readiness = useRemote(
    readinessEndpoint,
    { year_id: action.year.id },
    0,
    action.kind === "publish",
  );
  const report: Readiness | undefined = readiness.data;
  const title =
    action.kind === "publish"
      ? "Publish academic year"
      : action.kind === "close"
        ? "Close academic year"
        : "Delete calendar event";
  async function confirm() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api(
        action.kind === "delete"
          ? findEndpoint(
              "DELETE",
              "/academic-years/{year_id}/calendar/entries/{entry_id}/",
            )
          : findEndpoint(
              "POST",
              action.kind === "publish"
                ? "/academic-years/{year_id}/publish/"
                : "/academic-years/{year_id}/close/",
            ),
        {
          year_id: action.year.id,
          ...(action.kind === "delete" ? { entry_id: action.entry.id } : {}),
        },
      );
      toast(
        t(
          action.kind === "publish"
            ? "Academic year published"
            : action.kind === "close"
              ? "Academic year closed"
              : "Calendar event deleted",
        ),
      );
      onSaved();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }
  return (
    <Modal
      title={title}
      subtitle={action.year.name}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="modal-body ay-confirm">
        {action.kind === "publish" ? (
          <>
            <p>
              {t(
                "Publishing makes this year active for your school. Review the setup before continuing.",
              )}
            </p>
            {readiness.loading ? (
              <Loading />
            ) : readiness.error ? (
              <ErrorBox error={readiness.error} />
            ) : (
              report && (
                <>
                  {report.errors.length > 0 && (
                    <div className="ay-blockers" role="alert">
                      <ul>
                        {report.errors.map((message) => (
                          <li key={message}>{readinessMessage(message)}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {report.warnings.length > 0 && (
                    <div className="ay-notes">
                      <strong>{t("You can complete these later")}</strong>
                      <ul>
                        {report.warnings.map((message) => (
                          <li key={message}>{readinessMessage(message)}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {report.can_publish && (
                    <p className="ay-ready-line">
                      <CheckCircle2 size={17} />
                      {t("The calendar meets the publication requirements.")}
                    </p>
                  )}
                </>
              )
            )}
          </>
        ) : action.kind === "close" ? (
          <p>
            {t(
              "Closing this year keeps its history available and makes it read-only.",
            )}
          </p>
        ) : (
          <>
            <p>
              <strong>{action.entry.title}</strong>
            </p>
            <p>{t("This event will be removed from the school calendar.")}</p>
          </>
        )}
        {error && <ErrorBox error={error} />}
      </div>
      <footer>
        <button
          type="button"
          className="button subtle"
          onClick={onClose}
          disabled={busy}
        >
          {t("Cancel")}
        </button>
        <button
          className={`button ${action.kind === "publish" ? "primary" : "ay-danger"}`}
          disabled={
            busy ||
            (action.kind === "publish" &&
              (readiness.loading ||
                Boolean(readiness.error) ||
                !report?.can_publish))
          }
          onClick={confirm}
        >
          {busy && <RefreshCw size={15} className="spin" />}
          {t(
            busy
              ? "Saving…"
              : action.kind === "publish"
                ? "Publish year"
                : action.kind === "close"
                  ? "Close year"
                  : "Delete event",
          )}
        </button>
      </footer>
    </Modal>
  );
}

function YearWorkspace({
  year,
  revision,
  onEdit,
  onAction,
  onRecheck,
}: {
  year: AcademicYear;
  revision: number;
  onEdit: (editor: Editor) => void;
  onAction: (action: Action) => void;
  onRecheck: () => void;
}) {
  const calendar = useRemote(calendarEndpoint, { year_id: year.id }, revision);
  const readiness = useRemote(
    readinessEndpoint,
    { year_id: year.id },
    revision,
    year.status === "draft",
  );
  const [filter, setFilter] = useState("all");
  const entries: CalendarEntry[] = [...(calendar.data?.entries ?? [])].sort(
    (a, b) =>
      a.starts_on.localeCompare(b.starts_on) || a.title.localeCompare(b.title),
  );
  const periods = entries.filter((entry) => entry.entry_type === "term");
  const visible = entries.filter(
    (entry) =>
      filter === "all" ||
      (filter === "terms"
        ? entry.entry_type === "term"
        : entry.entry_type !== "term"),
  );
  const report: Readiness | undefined = readiness.data;
  const writable = year.status !== "closed";
  const canPublish =
    !readiness.loading && !readiness.error && report?.can_publish;
  const addTerm = () => onEdit({ kind: "entry", year, entryType: "term" });

  return (
    <div className="ay-workspace">
      <section className="ay-year-header">
        <div>
          <div className="ay-year-title">
            <h2>{year.name}</h2>
            <Status status={year.status} />
          </div>
          <Dates start={year.starts_on} end={year.ends_on} />
        </div>
        <div className="ay-year-actions">
          {writable && (
            <button
              className="button subtle small"
              onClick={() => onEdit({ kind: "year", year })}
            >
              <Edit3 size={15} />
              {t("Edit year")}
            </button>
          )}
          <Link
            className="button subtle small"
            to={`/classrooms?year_id=${encodeURIComponent(year.id)}`}
          >
            <BookOpen size={15} />
            {t("View classes")}
          </Link>
          {year.status === "draft" && (
            <button
              className="button primary small"
              disabled={!canPublish}
              onClick={() => onAction({ kind: "publish", year })}
              aria-describedby="ay-publication-status"
            >
              <Send size={15} />
              {t("Publish year")}
            </button>
          )}
          {year.status === "active" && (
            <button
              className="button subtle small"
              onClick={() => onAction({ kind: "close", year })}
            >
              <LockKeyhole size={15} />
              {t("Close year")}
            </button>
          )}
        </div>
      </section>

      {year.status === "draft" ? (
        <section
          className={`ay-setup ${canPublish ? "ready" : ""}`}
          aria-label={t("Publication checklist")}
        >
          <div className="ay-setup-heading">
            <span className="ay-setup-icon">
              {canPublish ? (
                <CheckCircle2 size={22} />
              ) : (
                <CalendarDays size={22} />
              )}
            </span>
            <div>
              <h3 id="ay-publication-status">
                {t(
                  readiness.loading
                    ? "Checking your year…"
                    : canPublish
                      ? "Your year is ready to publish"
                      : "A little preparation before publishing",
                )}
              </h3>
              <p>
                {t(
                  "A new year starts as a draft. Add at least one teaching period, then publish it.",
                )}
              </p>
            </div>
            <button
              className="button subtle small"
              onClick={onRecheck}
              disabled={readiness.loading}
            >
              <RefreshCw
                size={14}
                className={readiness.loading ? "spin" : ""}
              />
              {t("Check readiness")}
            </button>
          </div>
          <ol className="ay-steps">
            <li className="done">
              <span>
                <Check size={15} />
              </span>
              <div>
                <strong>{t("Define the year")}</strong>
                <small>{t("Name and dates saved")}</small>
              </div>
            </li>
            <li
              className={
                !calendar.loading && !calendar.error && periods.length > 0
                  ? "done"
                  : ""
              }
            >
              <span>
                {calendar.loading ? (
                  <RefreshCw size={14} className="spin" />
                ) : periods.length ? (
                  <Check size={15} />
                ) : (
                  "2"
                )}
              </span>
              <div>
                <strong>{t("Add a teaching period")}</strong>
                <small>{t("Set your terms or semesters")}</small>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>{t("Publish the year")}</strong>
                <small>{t("Make it active for the school")}</small>
              </div>
            </li>
          </ol>
          {readiness.error ? (
            <ErrorBox error={readiness.error} retry={onRecheck} />
          ) : (
            !readiness.loading &&
            report && (
              <>
                {report.errors.length > 0 && (
                  <div className="ay-blockers">
                    <AlertCircle size={17} />
                    <div>
                      <strong>{t("Before you can publish")}</strong>
                      <ul>
                        {report.errors.map((message) => (
                          <li key={message}>{readinessMessage(message)}</li>
                        ))}
                      </ul>
                    </div>
                    {!calendar.loading &&
                      !calendar.error &&
                      !periods.length && (
                        <button
                          className="button small primary"
                          onClick={addTerm}
                        >
                          <Plus size={15} />
                          {t("Add a term")}
                        </button>
                      )}
                  </div>
                )}
                {report.warnings.length > 0 && (
                  <details className="ay-preparation-notes">
                    <summary>{t("Other setup to complete")}</summary>
                    <p>{t("These items do not prevent publication.")}</p>
                    <ul>
                      {report.warnings.map((message) => (
                        <li key={message}>{readinessMessage(message)}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </>
            )
          )}
        </section>
      ) : (
        <div className={`ay-state-note ${year.status}`}>
          <span>
            {year.status === "closed" ? (
              <LockKeyhole size={18} />
            ) : (
              <CheckCircle2 size={18} />
            )}
          </span>
          <div>
            <strong>
              {t(
                year.status === "closed"
                  ? "This year is closed"
                  : "This year is published",
              )}
            </strong>
            <p>
              {t(
                year.status === "closed"
                  ? "The calendar and school history remain available to consult."
                  : "Manage the calendar and open the classes associated with this year.",
              )}
            </p>
          </div>
        </div>
      )}

      <section className="ay-calendar" aria-label={t("School calendar")}>
        <header>
          <div>
            <p className="eyebrow">{t("THE SCHOOL RHYTHM")}</p>
            <h3>{t("School calendar")}</h3>
            <p>{t("Teaching periods, holidays, and days away from class.")}</p>
          </div>
          {writable && (
            <div className="ay-calendar-actions">
              <button
                className="button subtle small"
                onClick={() =>
                  onEdit({ kind: "entry", year, entryType: "holiday" })
                }
              >
                <Plus size={15} />
                {t("Add an event")}
              </button>
              <button className="button primary small" onClick={addTerm}>
                <BookOpen size={15} />
                {t("Add a term")}
              </button>
            </div>
          )}
        </header>
        {calendar.loading ? (
          <Loading />
        ) : calendar.error ? (
          <div className="ay-calendar-error">
            <ErrorBox error={calendar.error} retry={onRecheck} />
          </div>
        ) : (
          <>
            <div
              className="ay-calendar-filters"
              aria-label={t("Filter calendar events")}
            >
              {[
                ["all", "All events"],
                ["terms", "Teaching periods"],
                ["days-off", "Holidays and days off"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                >
                  {t(label)}
                  <span>
                    {key === "all"
                      ? entries.length
                      : key === "terms"
                        ? periods.length
                        : entries.length - periods.length}
                  </span>
                </button>
              ))}
            </div>
            {visible.length ? (
              <ul className="ay-events">
                {visible.map((entry) => {
                  const Icon = entryIcons[entry.entry_type];
                  return (
                    <li key={entry.id} className="ay-event">
                      <span className={`ay-event-icon ${entry.entry_type}`}>
                        <Icon size={19} />
                      </span>
                      <div className="ay-event-title">
                        <strong>{entry.title}</strong>
                        <span>{t(entryLabels[entry.entry_type])}</span>
                      </div>
                      <Dates start={entry.starts_on} end={entry.ends_on} />
                      {writable && (
                        <div className="ay-event-actions">
                          <button
                            className="icon-button"
                            aria-label={`${t("Edit event")} · ${entry.title}`}
                            title={t("Edit event")}
                            onClick={() =>
                              onEdit({ kind: "entry", year, entry })
                            }
                          >
                            <Edit3 size={16} />
                          </button>
                          <button
                            className="icon-button"
                            aria-label={`${t("Delete event")} · ${entry.title}`}
                            title={t("Delete event")}
                            onClick={() =>
                              onAction({ kind: "delete", year, entry })
                            }
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="ay-calendar-empty">
                <CalendarDays size={30} />
                <h4>
                  {t(
                    entries.length
                      ? "No events in this category"
                      : writable
                        ? "Let’s plan the school year"
                        : "No calendar events",
                  )}
                </h4>
                <p>
                  {t(
                    entries.length
                      ? "Choose another category to see the rest of the calendar."
                      : writable
                        ? "Start with a teaching period, then add holidays and school breaks."
                        : "No events were recorded for this year.",
                  )}
                </p>
              </div>
            )}
          </>
        )}
      </section>
      <p className="ay-year-footnote">
        <Clock3 size={14} />
        {t(
          "Teachers see their classes once the year is published, according to their assignment dates.",
        )}
      </p>
    </div>
  );
}

export function AcademicYearsPage({
  years,
  initialYear,
  onYearChange,
  onRefresh,
}: {
  years: { data: AcademicYear[] | null; loading: boolean; error: string };
  initialYear: string;
  onYearChange: (id: string) => void;
  onRefresh: () => void;
}) {
  useLanguage();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const records = [...(years.data ?? [])].sort(
    (a, b) =>
      b.starts_on.localeCompare(a.starts_on) || a.name.localeCompare(b.name),
  );
  const selected =
    records.find(
      (year) => year.id === (params.get("year_id") || initialYear),
    ) ??
    records.find((year) => year.status === "active") ??
    records[0];
  const visible = records.filter(
    (year) =>
      (filter === "all" || year.status === filter) &&
      year.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  function select(id: string) {
    onYearChange(id);
    setParams(
      (before) => {
        const next = new URLSearchParams(before);
        next.set("year_id", id);
        return next;
      },
      { replace: true },
    );
  }
  function refresh() {
    setRevision((value) => value + 1);
    onRefresh();
  }
  function saved(yearId?: string) {
    setEditor(null);
    setAction(null);
    if (yearId) select(yearId);
    refresh();
  }
  return (
    <div className="academic-years-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("SCHOOL MANAGEMENT")}</p>
          <h1>{t("Academic years")}</h1>
          <p>
            {t(
              "Prepare the calendar, publish when ready, and keep previous years in view.",
            )}
          </p>
        </div>
        <div className="heading-actions">
          <button
            className="button subtle"
            onClick={refresh}
            disabled={years.loading}
          >
            <RefreshCw size={16} className={years.loading ? "spin" : ""} />
            {t("Refresh")}
          </button>
          <button
            className="button primary"
            onClick={() => setEditor({ kind: "year" })}
          >
            <Plus size={17} />
            {t("Create academic year")}
          </button>
        </div>
      </div>
      {years.loading ? (
        <Loading />
      ) : years.error ? (
        <ErrorBox error={years.error} retry={refresh} />
      ) : !records.length ? (
        <section className="ay-first-year">
          <CalendarDays size={36} />
          <h2>{t("A new school year starts here")}</h2>
          <p>
            {t(
              "Create your first year, set its teaching periods, then publish it for your school.",
            )}
          </p>
          <button
            className="button primary"
            onClick={() => setEditor({ kind: "year" })}
          >
            <Plus size={16} />
            {t("Create academic year")}
          </button>
        </section>
      ) : (
        <div className="ay-layout">
          <aside className="ay-sidebar" aria-label={t("School years")}>
            <div className="ay-sidebar-heading">
              <h2>{t("School years")}</h2>
              <span>{records.length}</span>
            </div>
            <label className="ay-search">
              <Search size={16} />
              <input
                type="search"
                aria-label={t("Search academic years")}
                placeholder={t("Search years…")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <select
              className="ay-status-filter"
              aria-label={t("Filter years by status")}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">{t("All statuses")}</option>
              {Object.entries(statusLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {t(label)}
                </option>
              ))}
            </select>
            <nav aria-label={t("Select an academic year")}>
              {visible.length ? (
                visible.map((year) => (
                  <button
                    key={year.id}
                    className="ay-year-option"
                    aria-pressed={selected?.id === year.id}
                    onClick={() => select(year.id)}
                  >
                    <div>
                      <strong>{year.name}</strong>
                      <Status status={year.status} />
                      <span className="ay-year-range">
                        {year.starts_on.slice(0, 4)} —{" "}
                        {year.ends_on.slice(0, 4)}
                      </span>
                    </div>
                    <ChevronRight size={17} />
                  </button>
                ))
              ) : (
                <p className="ay-no-match">
                  {t("No years match your search.")}
                </p>
              )}
            </nav>
            <p className="ay-sidebar-hint">
              <CalendarDays size={16} />
              {t("Select a year to manage its calendar and publication.")}
            </p>
          </aside>
          {selected && (
            <YearWorkspace
              key={selected.id}
              year={selected}
              revision={revision}
              onEdit={setEditor}
              onAction={setAction}
              onRecheck={() => setRevision((value) => value + 1)}
            />
          )}
        </div>
      )}
      {editor && (
        <EditorDialog
          editor={editor}
          onClose={() => setEditor(null)}
          onSaved={saved}
        />
      )}
      {action && (
        <ActionDialog
          action={action}
          onClose={() => setAction(null)}
          onSaved={saved}
        />
      )}
    </div>
  );
}
