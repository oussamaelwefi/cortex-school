import { useId, useState, type CSSProperties } from "react";
import { ArrowRight, Bell, CalendarDays, CheckCircle2, ClipboardCheck, Mail, RefreshCw, UserPlus, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { findEndpoint } from "./api";
import { getLocale, t } from "./i18n";
import { Heading } from "./pages";
import { Empty, ErrorBox, Loading, useRemote } from "./ui";
import "./analytics.css";

type Attendance = {
  present: number;
  late: number;
  absent: number;
  excused: number;
  submissions: number;
};
const registrationStatuses = ["pending", "approved", "rejected", "withdrawn"] as const;
type Registrations = Record<(typeof registrationStatuses)[number], number>;
type Totals = {
  attendance: Attendance;
  registrations: Registrations;
  updates_published: number;
  acknowledgements_required: number;
  acknowledgements_received: number;
};
type Bucket = { start: string; end: string; totals: Totals };
type Classroom = { id: string; name: string; academic_year: string; attendance: Attendance };
type Report = {
  current: Bucket;
  previous: Bucket;
  trend: Bucket[];
  classrooms: Classroom[];
  snapshot: {
    enrolled_students: number;
    pending_registrations: number;
    updates_with_overdue_acknowledgements: number;
    failed_invitations: number;
  };
};

const analyticsEndpoint = findEndpoint("GET", "/analytics/");
const ranges = [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]] as const;
const count = (value: number) => new Intl.NumberFormat(getLocale()).format(value);
const percent = (value: number) =>
  new Intl.NumberFormat(getLocale(), { maximumFractionDigits: 1, style: "percent" }).format(value / 100);
const rate = (numerator: number, denominator: number) => denominator ? numerator / denominator * 100 : null;
const recorded = ({ present, late, absent, excused }: Attendance) => present + late + absent + excused;
const attendanceRate = (attendance: Attendance) => rate(attendance.present + attendance.late, recorded(attendance));
const registrationsTotal = (registrations: Registrations) =>
  registrationStatuses.reduce((total, status) => total + registrations[status], 0);

function dates({ start, end }: Pick<Bucket, "start" | "end">, includeYear = false) {
  const formatter = new Intl.DateTimeFormat(getLocale(), {
    month: "short", day: "numeric", ...(includeYear ? { year: "numeric" } : {}), timeZone: "UTC",
  });
  return formatter.formatRange(new Date(start), new Date(end));
}

function Change({ value, previous, percentage }: {
  value: number | null;
  previous: number | null;
  percentage: boolean;
}) {
  if (value === null || previous === null) return <small>{t("Comparison unavailable")}</small>;
  const delta = percentage ? Math.round((value - previous) * 10) / 10 : value - previous;
  const signed = new Intl.NumberFormat(getLocale(), {
    signDisplay: "exceptZero", maximumFractionDigits: 1,
  }).format(delta);
  return (
    <small>
      <b className="analytics-delta">{signed}{percentage && ` ${t("pp")}`}</b> {t("vs. previous period")}
    </small>
  );
}

function Metrics({ report }: { report: Report }) {
  const { current: { totals }, previous: { totals: previous } } = report;
  const metrics = [
    {
      label: "Attendance rate", icon: ClipboardCheck, percentage: true,
      value: attendanceRate(totals.attendance), previous: attendanceRate(previous.attendance),
    },
    {
      label: "Updates published", icon: Bell, percentage: false,
      value: totals.updates_published, previous: previous.updates_published,
    },
    {
      label: "Guardian acknowledgement rate", icon: CheckCircle2, percentage: true,
      value: rate(totals.acknowledgements_received, totals.acknowledgements_required),
      previous: rate(previous.acknowledgements_received, previous.acknowledgements_required),
    },
    {
      label: "Registration requests", icon: UserPlus, percentage: false,
      value: registrationsTotal(totals.registrations), previous: registrationsTotal(previous.registrations),
    },
  ];
  return (
    <div className="analytics-metrics">
      {metrics.map(({ label, icon: Icon, value, previous: comparison, percentage }) => (
        <article key={label} className="analytics-metric">
          <div><h2>{t(label)}</h2><Icon aria-hidden="true" size={17} /></div>
          <strong>{value === null ? "—" : percentage ? percent(value) : count(value)}</strong>
          <Change value={value} previous={comparison} percentage={percentage} />
        </article>
      ))}
    </div>
  );
}

const chartMetrics = {
  attendance: { label: "Attendance", unit: "Attendance rate", value: (totals: Totals) => attendanceRate(totals.attendance) },
  updates: { label: "Student updates", unit: "Updates published", value: (totals: Totals) => totals.updates_published },
  registrations: { label: "Registrations", unit: "Registration requests", value: (totals: Totals) => registrationsTotal(totals.registrations) },
};

function Trend({ trend }: { trend: Bucket[] }) {
  const titleId = useId();
  const [metric, setMetric] = useState<keyof typeof chartMetrics>("attendance");
  const [selected, setSelected] = useState<number | null>(null);
  const definition = chartMetrics[metric];
  const values = trend.map((bucket) => definition.value(bucket.totals));
  const lastWithData = values.reduce<number>((index, value, i) => value !== null ? i : index, 0);
  const activeIndex = selected ?? lastWithData;
  const isRate = metric === "attendance";
  const upper = isRate ? 100 : Math.max(4, Math.ceil(Math.max(0, ...values.map((value) => value ?? 0)) / 4) * 4);
  const scale = [upper, upper * .75, upper * .5, upper * .25, 0];
  const format = (value: number) => isRate ? percent(value) : count(value);
  const valueAt = (index: number) => values[index] === null ? t("No attendance records") : format(values[index]);
  const labelStep = Math.ceil(trend.length / 6);
  const chartStyle = { "--periods": trend.length } as CSSProperties;

  return (
    <section className="analytics-panel analytics-trend" aria-labelledby={titleId}>
      <div className="analytics-panel-heading">
        <h2 id={titleId}>{t("School trends")}</h2>
        <div className="analytics-switch" role="group" aria-label={t("Trend metric")}>
          {(Object.keys(chartMetrics) as (keyof typeof chartMetrics)[]).map((key) => (
            <button key={key} type="button" aria-pressed={metric === key} onClick={() => {
              setMetric(key);
              setSelected(null);
            }}>
              {t(chartMetrics[key].label)}
            </button>
          ))}
        </div>
      </div>
      <div className="analytics-trend-detail">
        <span>{dates(trend[activeIndex])}</span>
        <strong>{valueAt(activeIndex)}</strong>
        {values[activeIndex] !== null && <span>{t(definition.unit)}</span>}
      </div>
      <div className="analytics-chart" style={chartStyle}>
        <div className="analytics-axis" aria-hidden="true">
          {scale.map((tick) => <span key={tick}>{format(tick)}</span>)}
        </div>
        <div className="analytics-plot">
          <div className="analytics-gridlines" aria-hidden="true">{scale.map((tick) => <i key={tick} />)}</div>
          <div className="analytics-bars">
            {trend.map((bucket, index) => (
              <button key={bucket.start} type="button"
                aria-label={`${dates(bucket)}, ${valueAt(index)}`}
                aria-pressed={activeIndex === index} data-metric={metric}
                onClick={() => setSelected(index)} onFocus={() => setSelected(index)}
                onMouseEnter={() => setSelected(index)}>
                {values[index] === null
                  ? <span className="analytics-bar-missing" />
                  : <span className="analytics-bar" style={{ height: `${values[index] / upper * 100}%` }} />}
              </button>
            ))}
          </div>
        </div>
        <div className="analytics-axis-dates" aria-hidden="true">
          {trend.map((bucket, index) => (
            <span key={bucket.start}>{index % labelStep === 0 ? dates({ start: bucket.start, end: bucket.start }) : ""}</span>
          ))}
        </div>
      </div>
      {isRate && <p className="analytics-note">{t("Attendance includes present and late entries. Days without recorded attendance have no rate.")}</p>}
    </section>
  );
}

function Snapshot({ snapshot }: { snapshot: Report["snapshot"] }) {
  const titleId = useId();
  const rows = [
    { label: "Pending registrations", value: snapshot.pending_registrations, icon: UserPlus, to: "/registrations" },
    { label: "Updates with overdue acknowledgements", value: snapshot.updates_with_overdue_acknowledgements, icon: Bell, to: "/review" },
    { label: "Failed invitations", value: snapshot.failed_invitations, icon: Mail, to: "/invitations" },
  ];
  return (
    <section className="analytics-panel analytics-snapshot" aria-labelledby={titleId}>
      <div className="analytics-panel-heading"><h2 id={titleId}>{t("Needs attention")}</h2><span>{t("Now")}</span></div>
      <ul>
        {rows.map(({ label, value, icon: Icon, to }) => (
          <li key={label}>
            <Link to={to}>
              <Icon aria-hidden="true" size={17} /><span>{t(label)}</span><strong>{count(value)}</strong>
              <ArrowRight aria-hidden="true" size={15} />
            </Link>
          </li>
        ))}
      </ul>
      <Link className="analytics-enrolled" to="/students">
        <Users aria-hidden="true" size={19} /><span>{t("Students enrolled in active years")}</span>
        <strong>{count(snapshot.enrolled_students)}</strong>
      </Link>
    </section>
  );
}

function ClassroomBreakdown({ classrooms }: { classrooms: Classroom[] }) {
  const [lowestFirst, setLowestFirst] = useState(true);
  const titleId = useId();
  const sorted = [...classrooms].sort((a, b) =>
    ((attendanceRate(a.attendance) ?? 0) - (attendanceRate(b.attendance) ?? 0)) * (lowestFirst ? 1 : -1)
      || a.name.localeCompare(b.name, getLocale()));
  return (
    <section className="analytics-panel analytics-classrooms" aria-labelledby={titleId}>
      <div className="analytics-panel-heading">
        <h2 id={titleId}>{t("Attendance by classroom")}</h2>
        {classrooms.length > 0 && (
          <select aria-label={t("Sort classroom attendance")} value={lowestFirst ? "low" : "high"}
            onChange={(event) => setLowestFirst(event.target.value === "low")}>
            <option value="low">{t("Lowest rate first")}</option>
            <option value="high">{t("Highest rate first")}</option>
          </select>
        )}
      </div>
      {classrooms.length ? (
        <div className="table-wrap">
          <table aria-labelledby={titleId}>
            <thead><tr>
              <th scope="col">{t("Classroom")}</th>
              <th scope="col" aria-sort={lowestFirst ? "ascending" : "descending"}>{t("Attendance rate")}</th>
              {["Present", "Late", "Absent", "Excused", "Registers"].map((name) => <th scope="col" key={name}>{t(name)}</th>)}
            </tr></thead>
            <tbody>
              {sorted.map(({ id, name, academic_year, attendance }) => (
                <tr key={id}>
                  <th scope="row"><strong>{name}</strong><small>{academic_year}</small></th>
                  <td><strong>{percent(attendanceRate(attendance) ?? 0)}</strong></td>
                  {[attendance.present, attendance.late, attendance.absent, attendance.excused, attendance.submissions]
                    .map((value, index) => <td key={index}>{count(value)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty title="No attendance records" text="Classroom totals appear when attendance is submitted in this period." />}
    </section>
  );
}

function RegistrationBreakdown({ registrations }: { registrations: Registrations }) {
  const titleId = useId();
  const total = registrationsTotal(registrations);
  const statusLabels = { approved: "Approved", pending: "Pending", rejected: "Rejected", withdrawn: "Withdrawn" };
  return (
    <section className="analytics-panel analytics-registrations" aria-labelledby={titleId}>
      <div className="analytics-panel-heading"><h2 id={titleId}>{t("Registrations by status")}</h2></div>
      <p>{t("Current status of requests submitted in this period.")}</p>
      <div className="analytics-registration-bar" aria-hidden="true">
        {total > 0 && registrationStatuses.map((status) => (
          <span key={status} data-status={status} style={{ flexGrow: registrations[status] }} />
        ))}
      </div>
      <dl>
        {registrationStatuses.map((status) => (
          <div key={status}>
            <dt><i data-status={status} aria-hidden="true" />{t(statusLabels[status])}</dt>
            <dd>{count(registrations[status])}</dd>
          </div>
        ))}
      </dl>
      <Link className="analytics-section-link" to="/registrations">{t("View registration requests")} <ArrowRight size={15} /></Link>
    </section>
  );
}

export function SchoolAnalyticsPage() {
  const [days, setDays] = useState<(typeof ranges)[number][0]>(30);
  const [revision, setRevision] = useState(0);
  const state = useRemote(analyticsEndpoint, { days }, revision);
  const report = state.data as Report | null;
  const refresh = () => setRevision((version) => version + 1);

  return (
    <div className="school-analytics">
      <Heading eyebrow="SCHOOL MANAGEMENT" title="School analytics" description="Attendance, family communication, and registrations across your school.">
        <button className="button subtle" type="button" onClick={refresh} disabled={state.loading}>
          <RefreshCw size={15} aria-hidden="true" /> {t("Refresh")}
        </button>
      </Heading>
      <div className="analytics-period">
        <div className="analytics-switch" role="group" aria-label={t("Reporting period")}>
          {ranges.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={days === value} onClick={() => setDays(value)}>{t(label)}</button>
          ))}
        </div>
        {report && (
          <div className="analytics-period-dates">
            <CalendarDays size={16} aria-hidden="true" />
            <strong>{dates(report.current, true)}</strong>
            <span>{t("Compared with")} {dates(report.previous, true)}</span>
          </div>
        )}
      </div>
      {state.loading ? <Loading /> : state.error ? <ErrorBox error={state.error} retry={refresh} /> : report && (
        <>
          <Metrics report={report} />
          <div className="analytics-layout">
            <Trend key={days} trend={report.trend} />
            <Snapshot snapshot={report.snapshot} />
            <ClassroomBreakdown classrooms={report.classrooms} />
            <RegistrationBreakdown registrations={report.current.totals.registrations} />
          </div>
          <p className="analytics-note">{t("Acknowledgement rates count responses received so far for updates published in each period.")}</p>
        </>
      )}
    </div>
  );
}
