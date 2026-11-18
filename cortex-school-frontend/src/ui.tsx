import { t, getLocale } from "./i18n";
import { useEffect, useRef, useState, createContext, useContext } from "react";
import { createPortal } from "react-dom";
import {
  X,
  LoaderCircle,
  AlertCircle,
  Check,
  ArrowUpRight,
  Inbox,
  ChevronRight,
} from "lucide-react";
import { useApi, endpoints, findEndpoint } from "./api";
import { Field, label, type Choices } from "./forms";
import { initialValue, cleanPayload } from "./lib.mjs";
import type { Data, Endpoint } from "./types";
import { InvitationCsvImport } from "./invitation-import";
import { AISettingsValues, InstructionalDays } from "./school-settings-values";
import { StudentGuardianContext, StudentGuardians } from "./student-guardians";
export const ToastContext = createContext<(s: string) => void>(() => {});
export const ChoicesContext = createContext<Choices>({});
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={24} />
      {t(" Loading your workspace… ")}
    </div>
  );
}
export function ErrorBox({
  error,
  retry,
}: {
  error: string;
  retry?: () => void;
}) {
  return (
    <div role="alert" className="error-box">
      <AlertCircle size={19} />
      <div>
        {t(error)}
        {retry && (
          <button className="text-button" onClick={retry}>
            {t(" Try again ")}
          </button>
        )}
      </div>
    </div>
  );
}
export function Empty({
  title = t("Nothing here yet"),
  text = t("Records will appear here as your school gets started."),
}: {
  title?: string;
  text?: string;
}) {
  return (
    <div className="empty">
      <span>
        <Inbox size={28} />
      </span>
      <h3>{t(title)}</h3>
      <p>{t(text)}</p>
    </div>
  );
}
export function Badge({ value }: { value: any }) {
  const v = String(value);
  return (
    <span
      className={`badge ${/urgent|failed|absent|overdue|rejected|missing/.test(v) ? "red" : /pending|draft|late|assigned|warning|queued/.test(v) ? "amber" : ""}`}
    >
      {label(v)}
    </span>
  );
}
export function display(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? t("Yes") : t("No");
  if (typeof v === "object")
    return Array.isArray(v)
      ? `${v.length} items`
      : v.name || v.title || v.first_name || t("View details");
  if (typeof v === "string" && /^\d{4}-\d\d-\d\dT/.test(v))
    return new Date(v).toLocaleString(getLocale(), {
      dateStyle: "medium",
      timeStyle: "short",
    });
  return String(v);
}
export function useRemote(
  endpoint: Endpoint | undefined,
  params: Data = {},
  refresh = 0,
  enabled = true,
) {
  const api = useApi();
  const [state, setState] = useState<{
    data: any;
    error: string;
    loading: boolean;
  }>({ data: null, error: "", loading: enabled });
  const serial = JSON.stringify(params);
  useEffect(() => {
    let active = true;
    if (!endpoint || !enabled) {
      setState({ data: null, error: "", loading: false });
      return;
    }
    setState({ data: null, error: "", loading: true });
    api(endpoint, JSON.parse(serial))
      .then((data) => {
        if (active) setState({ data, error: "", loading: false });
      })
      .catch((e) => {
        if (active) setState({ data: null, error: e.message, loading: false });
      });
    return () => {
      active = false;
    };
  }, [api, endpoint, serial, refresh, enabled]);
  return state;
}
export function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const heading = useRef(`dialog-${Math.random().toString(36).slice(2)}`);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const before = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const elements = ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input,select,textarea,a[href],[tabindex="0"]',
        );
        if (!elements?.length) return;
        const first = elements[0],
          last = elements[elements.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.body.style.overflow = before;
      document.removeEventListener("keydown", handler);
      previous?.focus();
    };
  }, [onClose]);
  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${wide ? "wide-modal" : ""}`}
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={heading.current}
        tabIndex={-1}
      >
        <header>
          <div>
            <p className="eyebrow">{t("CORTEX WORKSPACE")}</p>
            <h2 id={heading.current}>{t(title)}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label={t("Close dialog")}
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </div>,
    document.body,
  );
}
export function Operation({
  endpoint: e,
  context = {},
  seed,
  recordName,
  submitLabel,
  onClose,
  onDone,
}: {
  endpoint: Endpoint;
  context?: Data;
  seed?: Data;
  recordName?: string;
  submitLabel?: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const api = useApi(),
    toast = useContext(ToastContext),
    baseChoices = useContext(ChoicesContext);
  const policyPdf = e.id === "upload_school_policy_pdf";
  const editableParams = e.params.filter(
    (p) => recordName === undefined || p.in !== "path" || !context[p.name],
  );
  const [params, setParams] = useState<Data>(() =>
    Object.fromEntries(
      e.params.map((p) => [p.name, context[p.name] ?? p.default ?? ""]),
    ),
  );
  const [body, setBody] = useState<any>(() =>
    e.body
      ? {
          ...initialValue(e.body),
          ...Object.fromEntries(
            Object.entries(seed || {}).filter(([k]) => e.body?.properties?.[k]),
          ),
        }
      : undefined,
  );
  const [file, setFile] = useState<File>();
  const [readRevision, setReadRevision] = useState(0);
  const directAi = useRemote(e, {}, readRevision, e.id === "get_school_ai_settings");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [result, setResult] = useState<any>(undefined),
    [confirmed, setConfirmed] = useState(false);
  const roster = useRemote(
    findEndpoint("GET", "/teacher/classrooms/{classroom_id}/students/"),
    { classroom_id: body?.classroom_id },
    0,
    e.role === "teacher" && !!body?.classroom_id,
  );
  const choices: Choices = {
    ...baseChoices,
    ...(roster.data
      ? {
          student_id: roster.data.map((s: Data) => ({
            value: s.student_id || s.id,
            label: `${s.first_name} ${s.last_name}`,
          })),
        }
      : {}),
  };
  const existing = findEndpoint("GET", e.path);
  const settings = useRemote(
    existing,
    params,
    0,
    e.method === "PUT" && e.module === "schools",
  );
  useEffect(() => {
    if (settings.data && e.body)
      setBody(
        Object.fromEntries(
          Object.entries(settings.data).filter(
            ([k]) => e.body?.properties?.[k],
          ),
        ),
      );
  }, [settings.data, e.body]);
  const dangerous =
    e.method === "DELETE" ||
    /close_academic|withdraw|reject|remove_guardian/.test(e.id);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (settings.loading || settings.error) return;
    if (body?.requires_acknowledgement && !body.due_at) {
      setError(t("Choose a due date when requesting acknowledgement."));
      return;
    }
    if (dangerous && !confirmed) {
      setError(t("Confirm this action before continuing."));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await api(
        e,
        params,
        e.body ? cleanPayload(body, e.body) : undefined,
        file,
      );
      if (
        e.method === "GET" ||
        e.upload ||
        e.module === "ai" ||
        e.id.includes("preview") ||
        e.id.includes("explanation")
      )
        setResult(response);
      else {
        toast(t(`${e.title} completed`));
        onDone();
        onClose();
      }
    } catch (x) {
      setError((x as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (e.id === "upload_invitations")
    return <InvitationCsvImport onClose={onClose} onDone={onDone} />;
  if (e.id === "get_school_ai_settings")
    return <Modal title="AI settings" onClose={onClose} wide><div className="modal-body">{directAi.loading ? <Loading/> : directAi.error ? <ErrorBox error={directAi.error} retry={() => setReadRevision((value) => value + 1)}/> : directAi.data && <AISettingsValues settings={directAi.data}/>}</div><footer><button className="button primary" onClick={onClose}>{t("Close")}</button></footer></Modal>;
  return (
    <Modal
      title={e.title}
      subtitle={recordName}
      onClose={onClose}
      wide={!!e.body && Object.keys(e.body.properties || {}).length > 5}
    >
      <form onSubmit={submit}>
        <div className="modal-body">
          {settings.loading && <Loading />}
          {settings.error && <ErrorBox error={settings.error} />}
          {roster.error && <ErrorBox error={roster.error} />}
          {result !== undefined ? (
            <DataView
              data={result}
              endpoint={e}
              context={params}
              onChanged={onDone}
            />
          ) : (
            <>
              {editableParams.length > 0 && (
                <div className="form-grid">
                  {editableParams.map((p) => (
                    <Field
                      key={p.name}
                      name={p.name}
                      schema={p}
                      value={params[p.name]}
                      onChange={(v) => setParams({ ...params, [p.name]: v })}
                      choices={choices}
                    />
                  ))}
                </div>
              )}
              {e.body?.oneOf ? (
                <Field
                  name="Approval"
                  schema={e.body}
                  value={body}
                  onChange={setBody}
                  choices={choices}
                />
              ) : (
                e.body && (
                  <div className="form-grid">
                    {Object.entries(e.body.properties || {}).map(([k, s]) => (
                      <Field
                        key={k}
                        name={k}
                        schema={s}
                        value={body?.[k]}
                        onChange={(v) => setBody({ ...body, [k]: v })}
                        choices={choices}
                      />
                    ))}
                  </div>
                )
              )}
              {e.upload && (
                <label className="upload field">
                  <span>{t(policyPdf ? "Policy PDF" : "Import invitations (.csv)")}</span>
                  <input
                    type="file"
                    accept={policyPdf ? ".pdf,application/pdf" : ".csv,text/csv"}
                    required
                    onChange={(event) => setFile(event.target.files?.[0])}
                  />
                  <small>
                    {policyPdf
                      ? t("Choose a PDF with selectable text, up to 10 MB and 100 pages.")
                      : "Columns: email, first_name, last_name, role_slug. Roles: school_admin, teacher, guardian. Save as UTF-8 CSV."}
                  </small>
                </label>
              )}
              {dangerous && (
                <label className="confirm">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                  />{" "}
                  {t(" I understand and confirm this change. ")}
                </label>
              )}
              {!e.body && !e.params.length && !e.upload && (
                <p>{t(`Continue to ${e.title}.`)}</p>
              )}
            </>
          )}
          {error && <ErrorBox error={t(error)} />}
        </div>
        <footer>
          <button type="button" className="button subtle" onClick={onClose}>
            {t(" Close ")}
          </button>
          {result === undefined && (
            <button
              className={`button ${dangerous ? "danger" : "primary"}`}
              disabled={busy || settings.loading || !!settings.error}
            >
              {busy ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <Check size={16} />
              )}{" "}
              {e.method === "GET"
                ? t("Load records")
                : submitLabel
                  ? t(submitLabel)
                  : e.upload
                    ? t(policyPdf ? "Upload PDF" : "Import invitations")
                    : e.id.includes("preview")
                      ? t("Preview audience")
                      : e.method === "POST" && e.module === "ai"
                        ? t("Generate")
                        : t("Confirm")}
            </button>
          )}
        </footer>
      </form>
    </Modal>
  );
}
function bind(e: Endpoint, row: Data, parent: Data): Data {
  const context = { ...parent, ...row, ...(row.action || {}) };
  const nouns = e.path.split("/").filter((s) => s && !s.startsWith("{"));
  const noun = nouns[nouns.length - 1];
  const map: Record<string, string> = {
    "academic-years": "year_id",
    students: "student_id",
    classrooms: "classroom_id",
    enrollments: "enrollment_id",
    guardians: "guardian_id",
    invitations: "invitation_id",
    members: "user_id",
    "registration-requests": "request_id",
    "teacher-assignments": "assignment_id",
    entries: "entry_id",
    updates: "update_id",
    "student-updates": "update_id",
    notifications: "notification_id",
    recipients: "recipient_id",
    children: "student_id",
    registration_requests: "request_id",
  };
  if (row.id && map[noun] && !row[map[noun]]) context[map[noun]] = row.id;
  if (row.update_id) context.update_id = row.update_id;
  if (row.academic_year_id) context.year_id = row.academic_year_id;
  return context;
}
function nestedEndpoint(e: Endpoint, key: string): Endpoint {
  const paths: Record<string, string> = {
    recipients: "/teacher/updates/{update_id}/recipients/",
    children: "/guardian/students/",
    registration_requests: "/registration-requests/",
    enrollments: "/enrollments/",
    classrooms: "/classrooms/",
    entries: e.path.includes("calendar")
      ? "/academic-years/{year_id}/calendar/entries/"
      : e.path,
  };
  return paths[key] ? { ...e, path: paths[key] } : e;
}
export function DataView({
  data,
  endpoint,
  context = {},
  onChanged = () => {},
  onSelect,
  rowAction,
}: {
  data: any;
  endpoint: Endpoint;
  context?: Data;
  onChanged?: () => void;
  onSelect?: (row: Data) => void;
  rowAction?: (row: Data) => React.ReactNode;
}) {
  const [selectedRow, setSelected] = useState<Data | null>(null),
    [op, setOp] = useState<Endpoint | null>(null);
  const studentGuardians = useContext(StudentGuardianContext);
  if (data === null || data === undefined) return <Empty />;
  if (typeof data !== "object") return <p className="prose">{display(data)}</p>;
  const array = Array.isArray(data) ? data : null;
  const studentId = (row: Data) => row && typeof row === "object" ? row.student_id || (endpoint.path.includes("students") && row.first_name && row.last_name ? row.id : undefined) : undefined;
  const hasStudentGuardians = studentGuardians.enabled && (array ? array.some((row) => studentId(row)) : studentId(data));
  const selected = selectedRow?.id
    ? array?.find((row) => row?.id === selectedRow.id) ?? selectedRow
    : selectedRow;
  if (array?.length && array.every((v) => v === null || typeof v !== "object"))
    return (
      <ul className="plain-list">
        {array.map((v, i) => (
          <li key={i}>{display(v)}</li>
        ))}
      </ul>
    );
  const select = (row: Data) => (onSelect ? onSelect(row) : setSelected(row));
  const selectedContext = selected
    ? bind(endpoint, selected, context)
    : context;
  const schoolRegistrations = endpoint.id === "list_school_registration_requests";
  const allowed = endpoints.filter(
    (x) =>
      x.module !== "reminders" &&
      (!schoolRegistrations || x.module !== "student_registration" || selected?.status === "pending") &&
      (x.role === endpoint.role || x.role === "shared") &&
      x.params.filter((p) => p.in === "path").length > 0 &&
      x.params
        .filter((p) => p.in === "path")
        .every((p) => selectedContext[p.name] !== undefined) &&
      x.path !== endpoint.path,
  );
  if (array) {
    if (!array.length) return <Empty />;
    const preferred = [
      "first_name",
      "last_name",
      "child_first_name",
      "child_last_name",
      "guardian_name",
      "name",
      "title",
      "student_first_name",
      "student_last_name",
      "classroom_name",
      "email",
      "role_slug",
      "roles",
      "status",
      "send_status",
      "starts_on",
      "ends_on",
      "school_date",
      "effective_from",
      "effective_until",
      "due_at",
      "created_at",
      "reason",
      "category",
      "severity",
      "active_student_count",
    ];
    const keys = preferred
      .filter((k) => array.some((x) => x?.[k] !== undefined))
      .slice(0, 6);
    if (!keys.length)
      keys.push(
        ...Object.keys(array[0] || {})
          .filter(
            (k) =>
              !k.endsWith("_id") &&
              k !== "id" &&
              typeof array[0][k] !== "object",
          )
          .slice(0, 5),
      );
    return (
      <>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {keys.map((k) => (
                  <th key={k}>
                    {k === "guardian_name" ? t("Requested by") : label(k)}
                  </th>
                ))}
                {hasStudentGuardians && <th>{t("Guardians")}</th>}
                <th>
                  {schoolRegistrations ? t("Actions") : <span className="sr-only">{t("Open record")}</span>}
                </th>
              </tr>
            </thead>
            <tbody>
              {array.map((row, i) => (
                <tr key={row.id || row.recipient_id || i}>
                  {keys.map((k, j) => (
                    <td key={k}>
                      {j === 0 ? (
                        <button
                          className="record-button"
                          onClick={() => select(row)}
                        >
                          {typeof row === "object"
                            ? display(row[k])
                            : display(row)}
                        </button>
                      ) : k === "guardian_name" ? (
                        <div className="registration-requester">
                          <strong>
                            {row.guardian_name || row.guardian_email || t("Guardian profile unavailable")}
                          </strong>
                          {row.guardian_name && row.guardian_email && row.guardian_email !== row.guardian_name && (
                            <span>{row.guardian_email}</span>
                          )}
                        </div>
                      ) : k === "roles" ? (
                        <div className="member-roles">
                          {(row.roles || []).map((role: string) => (
                            <Badge key={role} value={role} />
                          ))}
                        </div>
                      ) : /status|severity|role_slug/.test(k) ? (
                        <Badge value={row[k]} />
                      ) : (
                        display(row[k])
                      )}
                    </td>
                  ))}
                  {hasStudentGuardians && <td>{studentId(row) && <StudentGuardians studentId={studentId(row)} guardianIds={row.guardian_ids}/>}</td>}
                  <td>
                    {rowAction?.(row)}
                    <button
                      className="icon-button"
                      aria-label={`Open ${row.name || row.title || row.first_name || "record"}`}
                      onClick={() => select(row)}
                    >
                      <ChevronRight size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selected && (
          <Modal
            title={
              selected.title ||
              selected.name ||
              [selected.first_name, selected.last_name]
                .filter(Boolean)
                .join(" ") ||
              t("Record details")
            }
            onClose={() => setSelected(null)}
            wide
          >
            <div className="modal-body">
              <div className="record-actions">
                {allowed.map((x) => (
                  <button
                    key={x.method + x.path}
                    className={`button small ${x.method === "DELETE" ? "danger" : "subtle"}`}
                    onClick={() => setOp(x)}
                  >
                    {t(x.title)}
                    <ArrowUpRight size={13} />
                  </button>
                ))}
              </div>
              <DataView
                data={selected}
                endpoint={endpoint}
                context={selectedContext}
                onChanged={onChanged}
              />
            </div>
          </Modal>
        )}
        {op && (
          <Operation
            endpoint={op}
            context={selectedContext}
            seed={selected || undefined}
            onClose={() => setOp(null)}
            onDone={onChanged}
          />
        )}
      </>
    );
  }
  const primitives = Object.entries(data).filter(
    ([, v]) => typeof v !== "object" || v === null,
  );
  const nested = Object.entries(data).filter(
    ([key, v]) => key !== "guardian_ids" && v !== null && typeof v === "object",
  );
  return (
    <div className="data-object">
      <dl className="detail-grid">
        {primitives.map(([k, v]) => (
          <div
            key={k}
            className={
              ["body", "content", "reply", "explanation", "reason"].includes(k)
                ? "wide"
                : ""
            }
          >
            <dt>{label(k)}</dt>
            <dd>
              {/status|severity/.test(k) ? <Badge value={v} /> : display(v)}
            </dd>
          </div>
        ))}
      </dl>
      {hasStudentGuardians && <section className="sg-object"><h3>{t("Guardians")}</h3><StudentGuardians studentId={studentId(data)} guardianIds={data.guardian_ids} details/></section>}
      {nested.map(([k, v]) => (
        <section className="nested-section" key={k}>
          <h3>
            {label(k)}{" "}
            {Array.isArray(v) && <span className="count">{v.length}</span>}
          </h3>
          {k === "instructional_weekdays" ? <InstructionalDays days={v as number[]}/> : <DataView
            data={v}
            endpoint={nestedEndpoint(endpoint, k)}
            context={bind(endpoint, data, context)}
            onChanged={onChanged}
            rowAction={rowAction}
          />}
        </section>
      ))}
    </div>
  );
}
