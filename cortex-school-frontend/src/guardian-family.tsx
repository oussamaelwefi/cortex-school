import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Bell, BookOpen, CalendarDays, CheckCircle2, ChevronDown, GraduationCap, RefreshCw, UserPlus, Users } from "lucide-react";
import { findEndpoint } from "./api";
import { getLocale, t, useLanguage } from "./i18n";
import { Badge, ErrorBox, Loading, Modal, useRemote } from "./ui";
import { GuardianUpdateDialog } from "./reminders";
import { attendancePeriod, summarizeAttendance, type AttendanceRecord } from "./family-attendance";

type Snapshot = { state: "submitted" | "not_submitted" | "not_expected"; status: AttendanceRecord["status"] | null; note?: string | null; school_date: string | null };
export type FamilyChild = {
  id: string; first_name: string; last_name: string;
  placement: { state: "current" | "not_placed" | "not_enrolled"; classroom_name: string | null; academic_year_name: string | null };
  attendance: { today: Snapshot; latest_submitted: Snapshot | null };
  unread_update_count: number; needs_response_count: number;
  latest_update: { recipient_id: string; title: string; author_label: string; occurred_at: string; needs_response: boolean } | null;
};
type Registration = { id: string; child_first_name: string; child_last_name: string; academic_year_name: string; status: string; rejection_reason: string | null };
type Family = { school_date: string; school_timezone: string; children: FamilyChild[]; registration_requests: Registration[] };
const familyEndpoint = findEndpoint("GET", "/guardian/family/");
const attendanceEndpoint = findEndpoint("GET", "/guardian/students/{student_id}/attendance");
const profileEndpoint = findEndpoint("GET", "/guardian/students/{student_id}/");
const formatDate = (value: string) => new Date(value.length === 10 ? `${value}T12:00:00Z` : value).toLocaleDateString(getLocale(), { dateStyle: "medium", ...(value.length === 10 ? { timeZone: "UTC" } : {}) });
const rateLabel = (value: number | null) => value === null ? "—" : new Intl.NumberFormat(getLocale(), { style: "percent", maximumFractionDigits: 1 }).format(value / 100);

function SchoolRecord({ child, onClose }: { child: FamilyChild; onClose: () => void }) {
  const [refresh, setRefresh] = useState(0);
  const state = useRemote(profileEndpoint, { student_id: child.id }, refresh);
  const enrollments: { id: string; academic_year: { name: string; status: string; starts_on: string; ends_on: string } }[] = state.data?.enrollments ?? [];
  return (
    <Modal title={`${child.first_name} ${child.last_name}`} subtitle={t("School record")} onClose={onClose}>
      <div className="modal-body gf-school-record">
        <div className="gf-record-class"><GraduationCap size={23} /><div><strong>{child.placement.classroom_name ?? t(child.placement.state === "not_placed" ? "Awaiting class placement" : "Not enrolled this year")}</strong>{child.placement.academic_year_name && <p>{child.placement.academic_year_name}</p>}</div></div>
        <h3>{t("Enrollment history")}</h3>
        {state.loading ? <Loading /> : state.error ? <ErrorBox error={state.error} retry={() => setRefresh((value) => value + 1)} />
          : enrollments.length ? <ul>{enrollments.map((enrollment) => <li key={enrollment.id}><div><strong>{enrollment.academic_year.name}</strong><p>{formatDate(enrollment.academic_year.starts_on)} – {formatDate(enrollment.academic_year.ends_on)}</p></div><Badge value={enrollment.academic_year.status} /></li>)}</ul>
          : <p>{t("No enrollment history yet.")}</p>}
      </div>
    </Modal>
  );
}

function ChildCard({ child, schoolDate, refresh, onChanged }: { child: FamilyChild; schoolDate: string; refresh: number; onChanged: () => void }) {
  const [retry, setRetry] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [updateOpen, setUpdateOpen] = useState(false);
  const closeProfile = useCallback(() => setProfileOpen(false), []);
  const closeUpdate = useCallback(() => setUpdateOpen(false), []);
  const period = attendancePeriod(schoolDate);
  const attendance = useRemote(attendanceEndpoint, { student_id: child.id, ...period, limit: 500 }, refresh + retry);
  const summary = summarizeAttendance((attendance.data ?? []) as AttendanceRecord[], period);
  const fullName = `${child.first_name} ${child.last_name}`;
  const today = child.attendance.today;
  const latest = child.attendance.latest_submitted;
  const todayLabel = today.state === "submitted" && today.status ? today.status
    : today.state === "not_submitted" ? "Not recorded yet" : "No attendance expected";
  return (
    <article className="gf-child-card">
      <header className="gf-child-heading"><span className="gf-child-avatar" aria-hidden="true">{child.first_name[0]}{child.last_name[0]}</span><div><h2 dir="auto">{fullName}</h2><div className="gf-placement"><BookOpen size={14} /><span>{child.placement.classroom_name ?? t(child.placement.state === "not_placed" ? "Awaiting class placement" : "Not enrolled this year")}</span>{child.placement.academic_year_name && <span className="gf-year">{child.placement.academic_year_name}</span>}</div></div></header>
      <div className="gf-today"><div><span className="gf-section-label">{t("Today’s attendance")}</span><span className={`gf-today-status ${today.state === "submitted" ? today.status : "unrecorded"}`}><span />{t(todayLabel === "present" ? "Present" : todayLabel === "late" ? "Late" : todayLabel === "absent" ? "Absent" : todayLabel === "excused" ? "Excused" : todayLabel)}</span></div><CalendarDays size={19} aria-hidden="true" /></div>
      {today.note && <p className="gf-attendance-note" dir="auto">{today.note}</p>}
      {today.state !== "submitted" && latest?.status && latest.school_date && <p className="gf-last-record">{t("Last recorded")}: <Badge value={latest.status} /> · {formatDate(latest.school_date)}</p>}
      <section className="gf-attendance-rate" aria-label={`${t("Attendance rate")} · ${fullName}`} aria-busy={attendance.loading}>
        <div className="gf-rate-heading"><span className="gf-section-label">{t("Attendance rate")}</span><span>{t("Last 30 days")}</span></div>
        {attendance.error ? <div className="gf-attendance-error"><p>{t("Attendance is temporarily unavailable.")}</p><button type="button" className="text-button" onClick={() => setRetry((value) => value + 1)}>{t("Try again")}</button></div> : (
          <><div className="gf-rate-value"><strong>{attendance.loading ? "—" : rateLabel(summary.rate)}</strong><span>{attendance.loading ? t("Loading attendance…") : summary.recorded ? t("{attended} of {total} recorded days attended").replace("{attended}", String(summary.counts.present + summary.counts.late)).replace("{total}", String(summary.recorded)) : t("No attendance records yet")}</span></div><div className="gf-rate-track" aria-hidden="true"><span style={{ width: `${summary.rate ?? 0}%` }} /></div><div className="gf-attendance-counts">{(["present", "late", "absent", "excused"] as const).map((status) => <span key={status} data-status={status}><i /><b>{attendance.loading ? "—" : summary.counts[status]}</b>{t(status === "present" ? "Present" : status === "late" ? "Late" : status === "absent" ? "Absent" : "Excused")}</span>)}</div></>
        )}
        <button type="button" className="text-button gf-history-toggle" aria-expanded={historyOpen} aria-controls={`attendance-${child.id}`} disabled={attendance.loading || Boolean(attendance.error)} onClick={() => setHistoryOpen(!historyOpen)}>{t(historyOpen ? "Hide attendance details" : "Attendance details")}<ChevronDown size={14} /></button>
        {historyOpen && <div className="gf-attendance-history" id={`attendance-${child.id}`}>
          <p>{formatDate(period.from)} – {formatDate(period.to)}</p>
          {summary.history.length ? <div className="gf-history-scroll"><table aria-label={`${t("Attendance history")} · ${fullName}`}><thead><tr><th>{t("Date")}</th><th>{t("Classroom")}</th><th>{t("Status")}</th></tr></thead><tbody>{summary.history.map((record) => <tr key={record.school_date}><td><time dateTime={record.school_date}>{formatDate(record.school_date)}</time>{record.note && <small dir="auto">{record.note}</small>}</td><td>{record.classroom_name}</td><td><Badge value={record.status} /></td></tr>)}</tbody></table></div> : <p>{t("Submitted attendance will appear here.")}</p>}
        </div>}
      </section>
      <section className="gf-child-updates"><div className="gf-updates-heading"><Bell size={15} /><strong>{t("School updates")}</strong>{child.needs_response_count > 0 && <span>{t("{count} awaiting your response").replace("{count}", String(child.needs_response_count))}</span>}</div>{child.latest_update ? <button type="button" className="gf-latest-update" onClick={() => setUpdateOpen(true)}><span><strong dir="auto">{child.latest_update.title}</strong><small>{child.latest_update.author_label} · {formatDate(child.latest_update.occurred_at)}</small></span><ArrowRight size={16} /></button> : <p>{t("No school updates yet.")}</p>}<span className="gf-unread">{child.unread_update_count ? t("{count} unread updates").replace("{count}", String(child.unread_update_count)) : t("All updates read")}</span></section>
      <footer className="gf-child-actions"><button type="button" className="button small subtle" aria-label={`${t("School record")} · ${fullName}`} onClick={() => setProfileOpen(true)}><GraduationCap size={15} />{t("School record")}</button><Link to="/feed" className="text-button">{t("All school updates")}<ArrowRight size={13} /></Link></footer>
      {profileOpen && <SchoolRecord child={child} onClose={closeProfile} />}
      {updateOpen && child.latest_update && <GuardianUpdateDialog notification={{ recipient_id: child.latest_update.recipient_id, update_title: child.latest_update.title }} onClose={closeUpdate} onAcknowledged={() => { setUpdateOpen(false); onChanged(); }} />}
    </article>
  );
}

export function GuardianChildCards({ children, schoolDate, refresh = 0, onChanged }: { children: FamilyChild[]; schoolDate: string; refresh?: number; onChanged: () => void }) {
  useLanguage();
  return <div className="gf-children-grid">{children.map((child) => <ChildCard key={child.id} child={child} schoolDate={schoolDate} refresh={refresh} onChanged={onChanged} />)}</div>;
}

export function GuardianFamilyPage() {
  useLanguage();
  const [refresh, setRefresh] = useState(0);
  const state = useRemote(familyEndpoint, {}, refresh);
  const family = state.data as Family | null;
  const children = family?.children ?? [];
  const requests = family?.registration_requests ?? [];
  const refreshFamily = useCallback(() => setRefresh((value) => value + 1), []);
  return (
    <div className="guardian-family-page">
      <div className="page-heading"><div><p className="eyebrow">{t("FAMILY WORKSPACE")}</p><h1>{t("My children")}</h1><p>{t("Classes, attendance, and school updates, together in one place.")}</p></div><div className="heading-actions"><button type="button" className="button subtle" onClick={refreshFamily} disabled={state.loading}><RefreshCw size={15} />{t("Refresh")}</button><Link to="/registrations" className="button primary"><UserPlus size={16} />{t("Registration requests")}</Link></div></div>
      {state.loading ? <Loading /> : state.error ? <ErrorBox error={state.error} retry={refreshFamily} /> : family && (
        <>
          <section className="gf-overview" aria-label={t("Your family at a glance")}><div><span className="gf-overview-icon"><Users size={20} /></span><span><strong>{children.length}</strong><span>{t("Children")}</span></span></div><div><span className="gf-overview-icon"><BookOpen size={20} /></span><span><strong>{children.filter((child) => child.placement.state === "current").length}</strong><span>{t("In a class")}</span></span></div><div><span className="gf-overview-icon"><Bell size={20} /></span><span><strong>{children.reduce((sum, child) => sum + child.needs_response_count, 0)}</strong><span>{t("Awaiting your response")}</span></span></div></section>
          <div className="gf-section-heading"><div><h2>{t("Your children at a glance")}</h2><p>{t("Open a child’s attendance details or school record to learn more.")}</p></div><span><CalendarDays size={14} />{formatDate(family.school_date)}</span></div>
          {children.length ? <GuardianChildCards children={children} schoolDate={family.school_date} refresh={refresh} onChanged={refreshFamily} /> : <section className="gf-empty"><GraduationCap size={30} /><h2>{t("No children linked yet")}</h2><p>{t("Children linked by your school will appear here. You can also follow a registration request below.")}</p><Link to="/registrations" className="button primary">{t("Registration requests")}<ArrowRight size={14} /></Link></section>}
          {children.length > 0 && <p className="gf-rate-explanation"><CheckCircle2 size={14} />{t("Attendance rate includes present and late days. Only recorded days are counted.")}</p>}
          {requests.length > 0 && <section className="gf-registration-list"><header><div><h2>{t("Registration requests")}</h2><p>{t("Follow the next steps for your children’s enrollment.")}</p></div><Link to="/registrations" className="text-button">{t("View all")}<ArrowRight size={14} /></Link></header>{requests.slice(0, 3).map((request) => <Link to="/registrations" className="gf-registration" key={request.id}><span className="gf-registration-icon"><UserPlus size={17} /></span><span><strong>{request.child_first_name} {request.child_last_name}</strong><small>{request.academic_year_name}{request.rejection_reason && ` · ${request.rejection_reason}`}</small></span><Badge value={request.status} /><ArrowRight size={15} /></Link>)}</section>}
        </>
      )}
    </div>
  );
}
