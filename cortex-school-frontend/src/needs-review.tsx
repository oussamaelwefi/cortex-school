import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ArrowRight, Bell, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, ClipboardCheck, Clock, Filter, Inbox, Mail, RefreshCw, Search, UserPlus, Users } from "lucide-react";
import { endpoints, findEndpoint } from "./api";
import { getLocale, t, useLanguage } from "./i18n";
import { label } from "./forms";
import { DataView, Empty, ErrorBox, Loading, Modal, Operation, useRemote } from "./ui";
import { reminderReviewHref } from "./reminders";
import type { Data, Endpoint } from "./types";

export type ReviewItem = {
  id: string; category: string; severity: "urgent" | "warning"; title: string; reason: string;
  due_at: string | null; occurred_at: string | null; school_date: string | null;
  classroom_name?: string | null; academic_year_name?: string | null; student_name?: string | null;
  teacher_name?: string | null; invitation_role?: string | null; invitation_email?: string | null;
  outstanding_acknowledgement_count?: number | null; affected_date_count?: number | null;
  action: { type: string; request_id?: string; invitation_id?: string; classroom_id?: string; academic_year_id?: string; school_date?: string; update_id?: string };
};
type Queue = {
  items: ReviewItem[]; total_count: number; category_counts: Record<string, number>;
  severity_counts: Record<string, number>; as_of: string; school_date: string;
  attendance_cutoff_time: string; informational_unread_update_count: number;
  offset: number; limit: number; has_more: boolean; next_offset: number | null;
};
const queueEndpoint = findEndpoint("GET", "/needs-review/");
const categories = [
  { key: "acknowledgement", title: "Acknowledgements", icon: Bell },
  { key: "missing_attendance", title: "Attendance", icon: ClipboardCheck },
  { key: "missing_assignment", title: "Teacher assignments", icon: Users },
  { key: "registration", title: "Registrations", icon: UserPlus },
  { key: "invitation", title: "Invitations", icon: Mail },
];
const actionLabels: Record<string, string> = {
  acknowledgement: "Review reminder", missing_attendance: "View attendance", missing_assignment: "Assign teacher",
  registration: "Review request", invitation: "View invitation",
};
type Filters = { category?: string; severity?: string; date_from?: string; date_to?: string; offset: number };
type OperationState = { endpoint: Endpoint; context: Data; recordName?: string };

function dateLabel(value: string, time = false) {
  return new Intl.DateTimeFormat(getLocale(), {
    dateStyle: "medium", ...(time ? { timeStyle: "short" as const } : { timeZone: "UTC" }),
  }).format(new Date(value.length === 10 ? `${value}T12:00:00Z` : value));
}

export function reviewDetailRequest(item: ReviewItem) {
  if (item.action.type === "registration_request") return {
    endpoint: findEndpoint("GET", "/registration-requests/"), params: {},
    select: (data: Data[]) => data.find((record) => record.id === item.action.request_id),
  };
  if (item.action.type === "invitation") return {
    endpoint: findEndpoint("GET", "/invitations/{invitation_id}/"), params: { invitation_id: item.action.invitation_id },
    select: (data: Data) => data,
  };
  return {
    endpoint: findEndpoint("GET", "/attendance/submissions"), params: { school_date: item.action.school_date ?? item.school_date },
    select: (data: Data) => data.classrooms?.find((record: Data) => record.classroom_id === item.action.classroom_id),
  };
}

function ReviewDetails({ item, onClose, onOperation }: {
  item: ReviewItem; onClose: () => void; onOperation: (operation: OperationState) => void;
}) {
  const [refresh, setRefresh] = useState(0);
  const request = reviewDetailRequest(item);
  const state = useRemote(request.endpoint, request.params, refresh);
  const record = state.data && request.select(state.data);
  const actions = item.action.type === "registration_request"
    ? record?.status === "pending" ? [
      findEndpoint("POST", "/registration-requests/{request_id}/approve/"),
      findEndpoint("POST", "/registration-requests/{request_id}/reject/"),
    ] : []
    : item.action.type === "invitation" ? endpoints.filter((endpoint) =>
      endpoint.module === "invitations" && endpoint.role === "admin" && endpoint.method !== "GET" &&
      endpoint.params.some((param) => param.name === "invitation_id" && param.in === "path")) : [];
  const readableRecord = record && Object.fromEntries(Object.entries(record).filter(([key]) =>
    key !== "id" && !key.endsWith("_id") && !key.includes("workos") && key !== "classroom_id"));
  return (
    <Modal title={t(item.title)} subtitle={t(item.reason)} onClose={onClose} wide>
      <div className="modal-body">
        {state.loading ? <Loading /> : state.error ? <ErrorBox error={state.error} retry={() => setRefresh((value) => value + 1)} />
          : !record ? <Empty title="This item has changed" text="Refresh the queue to see the latest items." /> : (
            <>
              {actions.length > 0 && <div className="record-actions">{actions.map((endpoint, index) => (
                <button key={endpoint.id} type="button" className={`button ${index === 0 ? "primary" : "subtle"}`}
                  onClick={() => onOperation({ endpoint, context: { ...item.action }, recordName: item.student_name ?? item.invitation_email ?? undefined })}>
                  {t(item.action.type === "registration_request" ? index === 0 ? "Approve" : "Reject" : endpoint.title)}
                </button>
              ))}</div>}
              <DataView data={readableRecord} endpoint={request.endpoint} context={item.action} />
            </>
          )}
      </div>
    </Modal>
  );
}

function QueueItem({ item, onOpen }: { item: ReviewItem; onOpen: (item: ReviewItem) => void }) {
  const category = categories.find((entry) => entry.key === item.category);
  const Icon = category?.icon ?? ClipboardCheck;
  const href = reminderReviewHref(item);
  const action = t(actionLabels[item.category] ?? "View details");
  const context = [
    item.classroom_name && !item.title.includes(item.classroom_name) ? item.classroom_name : null,
    item.teacher_name,
    item.academic_year_name,
    item.invitation_role ? label(item.invitation_role) : null,
    item.affected_date_count ? t("{count} school days affected").replace("{count}", String(item.affected_date_count)) : null,
  ].filter(Boolean);
  return (
    <article className="nr-item" data-priority={item.severity}>
      <span className="nr-item-icon"><Icon size={20} aria-hidden="true" /></span>
      <div className="nr-item-content">
        <div className="nr-item-labels"><span>{t(category?.title ?? "Review")}</span><span className="nr-priority">{t(item.severity === "urgent" ? "Urgent" : "Follow-up")}</span></div>
        <h3>{t(item.title)}</h3>
        <p>{t(item.reason)}</p>
        {context.length > 0 && <ul className="nr-item-context" aria-label={t("Context")}>{context.map((value, index) => <li key={index}>{value}</li>)}</ul>}
      </div>
      <div className="nr-item-action">
        {item.due_at ? <span className="nr-due"><Clock size={13} aria-hidden="true" /><span>{t("Due")} <time dateTime={item.due_at}>{dateLabel(item.due_at, true)}</time></span></span>
          : item.occurred_at && <span className="nr-due">{t("Created")} <time dateTime={item.occurred_at}>{dateLabel(item.occurred_at)}</time></span>}
        {href ? <Link className="button small primary" to={href}>{action}<ArrowRight size={14} /></Link>
          : <button type="button" className="button small subtle" onClick={() => onOpen(item)} aria-label={`${action} · ${t(item.title)}`}>{action}<ArrowRight size={14} /></button>}
      </div>
    </article>
  );
}

export function NeedsReviewPage() {
  useLanguage();
  const [refresh, setRefresh] = useState(0);
  const [filters, setFilters] = useState<Filters>({ offset: 0 });
  const [search, setSearch] = useState("");
  const [rangeOpen, setRangeOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [dateError, setDateError] = useState("");
  const [selected, setSelected] = useState<ReviewItem | null>(null);
  const [operation, setOperation] = useState<OperationState | null>(null);
  const closeDetails = useCallback(() => setSelected(null), []);
  const overview = useRemote(queueEndpoint, { limit: 1 }, refresh);
  const state = useRemote(queueEndpoint, {
    category: filters.category ? [filters.category] : [], severity: filters.severity ? [filters.severity] : [],
    date_from: filters.date_from, date_to: filters.date_to, limit: 20, offset: filters.offset,
  }, refresh);
  const totals = overview.data as Queue | null;
  const queue = state.data as Queue | null;
  const items = (queue?.items ?? []).filter((item) => [item.title, item.reason, item.classroom_name, item.student_name, item.teacher_name, item.invitation_email]
    .some((value) => value?.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())));
  const categoryTitle = categories.find((category) => category.key === filters.category)?.title ?? "All items";
  const filtered = Boolean(filters.category || filters.severity || filters.date_from || filters.date_to || search);

  function changeFilters(next: Partial<Filters>) {
    setFilters((current) => ({ ...current, ...next, offset: 0 }));
    setSearch("");
  }
  function reset() {
    setFilters({ offset: 0 }); setSearch(""); setDateFrom(""); setDateTo(""); setDateError(""); setRangeOpen(false);
  }
  function openItem(item: ReviewItem) {
    if (item.action.type === "classroom_assignment") {
      setOperation({ endpoint: findEndpoint("POST", "/classrooms/{classroom_id}/teacher-assignments/"), context: { ...item.action, year_id: item.action.academic_year_id }, recordName: item.classroom_name ?? undefined });
    } else setSelected(item);
  }
  const resultCount = queue?.total_count === 1 ? t("1 item") : t("{count} items").replace("{count}", String(queue?.total_count ?? "—"));

  return (
    <div className="needs-review-page">
      <div className="page-heading">
        <div><p className="eyebrow">{t("SCHOOL MANAGEMENT")}</p><h1>{t("Needs review")}</h1><p>{t("Your school’s next steps, together in one place.")}</p></div>
        <div className="heading-actions"><button type="button" className="button subtle" disabled={state.loading || overview.loading} onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={15} />{t("Refresh")}</button></div>
      </div>
      <section className="nr-overview" aria-label={t("Review queue overview")}>
        <button type="button" onClick={reset}><span className="nr-stat-icon"><Inbox size={20} /></span><span><strong>{totals?.total_count ?? "—"}</strong><span>{t("Open items")}</span></span></button>
        <button type="button" data-tone="urgent" onClick={() => { reset(); setFilters({ severity: "urgent", offset: 0 }); }}><span className="nr-stat-icon"><AlertCircle size={20} /></span><span><strong>{totals?.severity_counts.urgent ?? "—"}</strong><span>{t("Urgent")}</span></span></button>
        <button type="button" onClick={() => { reset(); setFilters({ severity: "warning", offset: 0 }); }}><span className="nr-stat-icon"><Clock size={20} /></span><span><strong>{totals?.severity_counts.warning ?? "—"}</strong><span>{t("Follow-up")}</span></span></button>
      </section>
      {overview.error && !state.error && <ErrorBox error={overview.error} retry={() => setRefresh((value) => value + 1)} />}
      <div className="nr-layout">
        <aside className="nr-sidebar">
          <h2>{t("Review queue")}</h2>
          <nav aria-label={t("Review categories")}>
            {[{ key: "", title: "All items", icon: Inbox }, ...categories].map(({ key, title, icon: Icon }) => (
              <button type="button" key={key} aria-pressed={(filters.category ?? "") === key} onClick={() => changeFilters({ category: key || undefined })}>
                <Icon size={16} aria-hidden="true" /><span>{t(title)}</span><b>{key ? totals?.category_counts[key] ?? "—" : totals?.total_count ?? "—"}</b>
              </button>
            ))}
          </nav>
          {totals && <div className="nr-school-day"><CalendarDays size={15} /><div><strong>{dateLabel(totals.school_date)}</strong><p>{t("Attendance cutoff")} · {totals.attendance_cutoff_time.slice(0, 5)}</p></div></div>}
        </aside>
        <section className="nr-queue" aria-label={t("Items to review")}>
          <header className="nr-queue-heading"><div><h2>{t(categoryTitle)}</h2><span>{resultCount}</span></div>{filters.severity !== "warning" && <span className="nr-order"><AlertCircle size={13} />{t("Urgent items first")}</span>}</header>
          <div className="nr-toolbar">
            <label className="nr-search"><Search size={16} /><input aria-label={t("Search this page")} placeholder={t("Search this page…")} value={search} onChange={(event) => setSearch(event.target.value)} /></label>
            <select aria-label={t("Priority")} value={filters.severity ?? ""} onChange={(event) => changeFilters({ severity: event.target.value || undefined })}><option value="">{t("All priorities")}</option><option value="urgent">{t("Urgent")}</option><option value="warning">{t("Follow-up")}</option></select>
            <button type="button" className="button small subtle" aria-expanded={rangeOpen} onClick={() => setRangeOpen(!rangeOpen)}><Filter size={14} />{t("Date range")}{(filters.date_from || filters.date_to) && <span className="nr-filter-dot" />}</button>
            {filtered && <button type="button" className="text-button nr-clear" onClick={reset}>{t("Clear filters")}</button>}
          </div>
          {rangeOpen && <form className="nr-date-range" onSubmit={(event) => {
            event.preventDefault();
            if (dateFrom && dateTo && dateFrom > dateTo) { setDateError("The start date must be on or before the end date."); return; }
            setDateError(""); changeFilters({ date_from: dateFrom || undefined, date_to: dateTo || undefined });
          }}><label>{t("From")}<input type="date" aria-label={t("From date")} value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label><label>{t("To")}<input type="date" aria-label={t("To date")} value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label><button type="submit" className="button small primary">{t("Apply dates")}</button>{dateError && <p role="alert">{t(dateError)}</p>}</form>}
          <div className="nr-items" aria-busy={state.loading}>
            {state.loading ? <Loading /> : state.error ? <ErrorBox error={state.error} retry={() => setRefresh((value) => value + 1)} />
              : items.length ? items.map((item) => <QueueItem key={item.id} item={item} onOpen={openItem} />)
              : <div className="nr-empty"><CheckCircle2 size={29} /><h3>{t(filtered ? "No matching items" : "You’re all caught up")}</h3><p>{t(filtered ? "Try another category, priority, or date range." : "Your school’s review queue is clear.")}</p>{filtered && <button type="button" className="button small subtle" onClick={reset}>{t("Clear filters")}</button>}</div>}
          </div>
          {queue && !state.loading && !state.error && <footer className="nr-pagination">
            <span>{search ? t("{count} matches on this page").replace("{count}", String(items.length)) : queue.total_count ? t("Showing {from}–{to} of {total}").replace("{from}", String(queue.offset + 1)).replace("{to}", String(queue.offset + queue.items.length)).replace("{total}", String(queue.total_count)) : t("No open items")}</span>
            <div><button type="button" className="icon-button" aria-label={t("Previous page")} disabled={queue.offset === 0} onClick={() => { setFilters((current) => ({ ...current, offset: Math.max(0, queue.offset - queue.limit) })); setSearch(""); }}><ChevronLeft size={18} /></button><button type="button" className="icon-button" aria-label={t("Next page")} disabled={!queue.has_more || queue.next_offset === null} onClick={() => { setFilters((current) => ({ ...current, offset: queue.next_offset! })); setSearch(""); }}><ChevronRight size={18} /></button></div>
          </footer>}
        </section>
      </div>
      {totals && <div className="nr-footnote"><span>{t("Updated")} {new Date(totals.as_of).toLocaleTimeString(getLocale(), { hour: "2-digit", minute: "2-digit" })}</span>{totals.informational_unread_update_count > 0 && <Link to="/updates">{t("{count} unread informational updates").replace("{count}", String(totals.informational_unread_update_count))}<ArrowRight size={13} /></Link>}</div>}
      {selected && <ReviewDetails item={selected} onClose={closeDetails} onOperation={(next) => { setSelected(null); setOperation(next); }} />}
      {operation && <Operation endpoint={operation.endpoint} context={operation.context} recordName={operation.recordName} onClose={() => setOperation(null)} onDone={() => setRefresh((value) => value + 1)} />}
    </div>
  );
}
