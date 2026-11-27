import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  FileUp,
  GraduationCap,
  Info,
  LoaderCircle,
  Mail,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  UserPlus,
  Users,
} from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { getLocale, t, useLanguage } from "./i18n";
import { ErrorBox, Loading, Modal, useRemote } from "./ui";
import { InvitationCsvImport } from "./invitation-import";
import { useInvitationUpdates } from "./invitation-updates";

type InvitationRole = "school_admin" | "teacher" | "guardian";
export type Invitation = {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role_slug: InvitationRole | null;
  send_status: string;
  workos_state: string | null;
  expires_at: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
  attempt_count: number;
  error_message: string | null;
};
type Group = "all" | "sending" | "awaiting" | "accepted" | "attention";
const listEndpoint = findEndpoint("GET", "/invitations/");
const createEndpoint = findEndpoint("POST", "/invitations/");
const detailEndpoint = findEndpoint("GET", "/invitations/{invitation_id}/");
const retryEndpoint = findEndpoint(
  "POST",
  "/invitations/{invitation_id}/retry/",
);
const roles = [
  {
    value: "teacher",
    title: "Teacher",
    plural: "Teachers",
    icon: GraduationCap,
    description:
      "Access assigned classes, take attendance and share updates with families.",
  },
  {
    value: "guardian",
    title: "Guardian",
    plural: "Guardians",
    icon: Users,
    description:
      "Follow their children’s school life and receive classroom updates.",
  },
  {
    value: "school_admin",
    title: "Administrator",
    plural: "Administrators",
    icon: ShieldCheck,
    description:
      "Manage the school, its members and its academic organization.",
  },
] as const;
const groups: { value: Group; title: string }[] = [
  { value: "all", title: "All invitations" },
  { value: "sending", title: "Sending in progress" },
  { value: "awaiting", title: "Awaiting acceptance" },
  { value: "accepted", title: "Joined the school" },
  { value: "attention", title: "Invitations to follow up" },
];
const pageSize = 12;
export const invitationRefreshMs = 15000;
const invitationReconcileMs = 60000;
const normalize = (value: string) =>
  value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase()
    .trim();
const personName = (invitation: Invitation) =>
  [invitation.first_name, invitation.last_name].filter(Boolean).join(" ");
const roleOf = (invitation: Invitation) =>
  roles.find((role) => role.value === (invitation.role_slug ?? "guardian"))!;
const dateLabel = (value: string | null) =>
  value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleDateString(getLocale(), {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "—";

export function invitationState(invitation: Invitation, now = Date.now()) {
  if (invitation.workos_state === "accepted")
    return {
      group: "accepted",
      title: "Joined the school",
      tone: "success",
      description:
        "This person has accepted their invitation and joined your school.",
    } as const;
  if (["pending", "queued", "processing"].includes(invitation.send_status))
    return {
      group: "sending",
      title:
        invitation.send_status === "processing"
          ? "Sending invitation"
          : "Queued to send",
      tone: "progress",
      description:
        "The invitation is being sent in the background. Its status updates automatically.",
    } as const;
  if (invitation.send_status === "failed")
    return {
      group: "attention",
      title: "Invitation not sent",
      tone: "error",
      description:
        "The last send attempt failed. You can review the details and try again.",
    } as const;
  if (invitation.workos_state === "revoked")
    return {
      group: "attention",
      title: "Invitation revoked",
      tone: "warning",
      description:
        "This invitation is no longer valid. Send another invitation if access is still needed.",
    } as const;
  if (
    invitation.workos_state === "expired" ||
    (invitation.expires_at && Date.parse(invitation.expires_at) <= now)
  )
    return {
      group: "attention",
      title: "Invitation expired",
      tone: "warning",
      description:
        "The invitation link has expired. Send another invitation to give this person access.",
    } as const;
  if (invitation.send_status === "sent")
    return {
      group: "awaiting",
      title: "Awaiting acceptance",
      tone: "neutral",
      description:
        "The invitation was sent. This person still needs to accept the link in their email.",
    } as const;
  return {
    group: "all",
    title: "Invitation status unavailable",
    tone: "neutral",
    description: "Refresh the invitation to check its latest status.",
  } as const;
}
export function canRetryInvitation(invitation: Invitation) {
  return (
    invitation.workos_state !== "accepted" &&
    !["queued", "processing"].includes(invitation.send_status)
  );
}
function Status({ invitation }: { invitation: Invitation }) {
  const status = invitationState(invitation);
  return (
    <span className={`iv-status ${status.tone}`}>
      <span />
      {t(status.title)}
    </span>
  );
}
function Person({ invitation }: { invitation: Invitation }) {
  const name = personName(invitation);
  return (
    <div className="iv-person">
      <span className="iv-avatar" aria-hidden="true">
        {(
          invitation.first_name?.[0] || invitation.email[0]
        ).toLocaleUpperCase()}
        {invitation.last_name?.[0]?.toLocaleUpperCase()}
      </span>
      <div>
        <strong dir="auto">{name || invitation.email}</strong>
        {name && <span>{invitation.email}</span>}
      </div>
    </div>
  );
}

function InvitePerson({
  initialRole,
  onClose,
  onDone,
}: {
  initialRole: InvitationRole | null;
  onClose: () => void;
  onDone: (invitation: Invitation) => void;
}) {
  const api = useApi();
  const [role, setRole] = useState<InvitationRole | null>(initialRole);
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!role || !email.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const invitation: Invitation = await api(
        createEndpoint,
        {},
        {
          email: email.trim().toLocaleLowerCase(),
          role_slug: role,
          first_name: firstName.trim() || null,
          last_name: lastName.trim() || null,
        },
      );
      onDone(invitation);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Invite a person"
      subtitle={t(
        "Choose their role and send them a link to join your school.",
      )}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form onSubmit={submit}>
        <div className="modal-body iv-invite-form">
          <fieldset className="iv-role-picker" disabled={busy}>
            <legend>{t("Role at the school")}</legend>
            <div className="iv-role-options">
              {roles.map(({ value, title, description, icon: Icon }) => (
                <label
                  key={value}
                  className="iv-role-option"
                  data-selected={role === value}
                >
                  <input
                    type="radio"
                    name="invitation-role"
                    value={value}
                    checked={role === value}
                    required
                    onChange={() => setRole(value)}
                  />
                  <Icon size={22} aria-hidden="true" />
                  <strong>{t(title)}</strong>
                  <span>{t(description)}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="field">
            <span>
              {t("Email")} <b>*</b>
            </span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              required
              maxLength={320}
              value={email}
              disabled={busy}
              placeholder="nom@exemple.com"
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <div className="form-grid">
            <label className="field">
              <span>
                {t("First name")} <small>{t("Optional")}</small>
              </span>
              <input
                name="first_name"
                autoComplete="given-name"
                maxLength={255}
                value={firstName}
                disabled={busy}
                onChange={(event) => setFirstName(event.target.value)}
              />
            </label>
            <label className="field">
              <span>
                {t("Last name")} <small>{t("Optional")}</small>
              </span>
              <input
                name="last_name"
                autoComplete="family-name"
                maxLength={255}
                value={lastName}
                disabled={busy}
                onChange={(event) => setLastName(event.target.value)}
              />
            </label>
          </div>
          <p className="iv-form-note">
            <Mail size={17} aria-hidden="true" />
            {t(
              "They will receive an email invitation with the role you selected. You can follow its progress on this page.",
            )}
          </p>
          {error && <ErrorBox error={error} />}
        </div>
        <footer>
          <button
            type="button"
            className="button subtle"
            disabled={busy}
            onClick={onClose}
          >
            {t("Cancel")}
          </button>
          <button
            type="submit"
            className="button primary"
            disabled={busy || !role || !email.trim()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Send size={16} />
            )}
            {t(busy ? "Preparing invitation…" : "Send invitation")}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function InvitationDetails({
  invitation,
  confirmInitially,
  refreshRevision,
  onClose,
  onDone,
}: {
  invitation: Invitation;
  confirmInitially: boolean;
  refreshRevision: number;
  onClose: () => void;
  onDone: (invitation: Invitation) => void;
}) {
  const api = useApi();
  const [revision, setRevision] = useState(0);
  const remote = useRemote(
    detailEndpoint,
    { invitation_id: invitation.id },
    revision + refreshRevision,
  );
  const record: Invitation | null = remote.data;
  const [confirm, setConfirm] = useState(confirmInitially);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const retryable = !!record && canRetryInvitation(record);
  async function retry() {
    if (!record || !retryable || busy || remote.loading || remote.error) return;
    setBusy(true);
    setError("");
    try {
      onDone(await api(retryEndpoint, { invitation_id: record.id }));
    } catch (err) {
      setError((err as Error).message);
      setRevision((value) => value + 1);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={confirm ? "Resend invitation" : "Invitation details"}
      subtitle={invitation.email}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="modal-body iv-details">
        {remote.loading ? (
          <Loading />
        ) : remote.error ? (
          <ErrorBox
            error={remote.error}
            retry={() => setRevision((value) => value + 1)}
          />
        ) : (
          record && (
            <>
              <Person invitation={record} />
              <Status invitation={record} />
              <p className="iv-state-description">
                {t(invitationState(record).description)}
              </p>
              <dl className="iv-detail-grid">
                <div>
                  <dt>{t("Role")}</dt>
                  <dd>{t(roleOf(record).title)}</dd>
                </div>
                <div>
                  <dt>{t("Send attempts")}</dt>
                  <dd>{record.attempt_count}</dd>
                </div>
                <div>
                  <dt>{t("Invitation created")}</dt>
                  <dd>{dateLabel(record.created_at)}</dd>
                </div>
                <div>
                  <dt>{t("Last sent")}</dt>
                  <dd>{dateLabel(record.sent_at)}</dd>
                </div>
                <div>
                  <dt>{t("Invitation expires")}</dt>
                  <dd>{dateLabel(record.expires_at)}</dd>
                </div>
              </dl>
              {record.send_status === "failed" && record.error_message && (
                <details className="iv-error-details">
                  <summary>{t("Why did sending fail?")}</summary>
                  <p>{record.error_message}</p>
                </details>
              )}
              {confirm && retryable && (
                <div className="iv-resend-confirm">
                  <Mail size={20} aria-hidden="true" />
                  <div>
                    <strong>
                      {t("Send another invitation to this person?")}
                    </strong>
                    <p>
                      {t(
                        "The invitation will be queued again for the same email address and role.",
                      )}
                    </p>
                  </div>
                </div>
              )}
              {invitationState(record).group === "accepted" && (
                <Link
                  to={`/members?role=${record.role_slug ?? "guardian"}`}
                  className="text-button"
                  onClick={onClose}
                >
                  {t("View school members")}
                  <ArrowRight size={15} />
                </Link>
              )}
            </>
          )
        )}
        {error && <ErrorBox error={error} />}
      </div>
      <footer>
        <button
          type="button"
          className="button subtle"
          disabled={busy}
          onClick={onClose}
        >
          {t("Close")}
        </button>
        {retryable && !remote.loading && !remote.error && (
          <button
            type="button"
            className="button primary"
            disabled={busy}
            onClick={() => (confirm ? void retry() : setConfirm(true))}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Send size={16} />
            )}
            {t(
              busy
                ? "Preparing invitation…"
                : confirm
                  ? "Confirm resend"
                  : "Resend invitation",
            )}
          </button>
        )}
      </footer>
    </Modal>
  );
}

export function InvitationsPage({
  getAccessToken,
}: {
  getAccessToken?: () => Promise<string | undefined>;
}) {
  useLanguage();
  const api = useApi();
  const [params, setParams] = useSearchParams();
  const roleFilter = roles.some((role) => role.value === params.get("role"))
    ? params.get("role")!
    : "all";
  const group: Group =
    groups.find((entry) => entry.value === params.get("status"))?.value ??
    "all";
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [remote, setRemote] = useState<{
    data: Invitation[] | null;
    loading: boolean;
    error: string;
  }>({ data: null, loading: true, error: "" });
  const [notice, setNotice] = useState("");
  const [invite, setInvite] = useState<{ role: InvitationRole | null } | null>(
    null,
  );
  const [importOpen, setImportOpen] = useState(false);
  const [selected, setSelected] = useState<{
    invitation: Invitation;
    confirm: boolean;
  } | null>(null);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  const fetching = useRef(true);
  const liveRefreshPending = useRef(false);
  const refreshFromSocket = useCallback(() => {
    if (document.visibilityState !== "visible") return;
    if (fetching.current) {
      liveRefreshPending.current = true;
      return;
    }
    fetching.current = true;
    reload();
  }, [reload]);
  const liveConnected = useInvitationUpdates(getAccessToken, refreshFromSocket);
  useEffect(() => {
    let active = true;
    fetching.current = true;
    setRemote((previous) => ({ ...previous, loading: true, error: "" }));
    api(listEndpoint)
      .then((data: Invitation[]) => {
        if (active) setRemote({ data, loading: false, error: "" });
      })
      .catch((error: Error) => {
        if (active)
          setRemote((previous) => ({
            ...previous,
            loading: false,
            error: error.message,
          }));
      })
      .finally(() => {
        if (!active) return;
        fetching.current = false;
        if (liveRefreshPending.current) {
          liveRefreshPending.current = false;
          refreshFromSocket();
        }
      });
    return () => {
      active = false;
    };
  }, [api, revision, refreshFromSocket]);
  useEffect(() => {
    const refreshVisiblePage = () => {
      if (document.visibilityState !== "visible" || fetching.current) return;
      fetching.current = true;
      reload();
    };
    const timer = window.setInterval(
      refreshVisiblePage,
      liveConnected ? invitationReconcileMs : invitationRefreshMs,
    );
    window.addEventListener("focus", refreshVisiblePage);
    document.addEventListener("visibilitychange", refreshVisiblePage);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refreshVisiblePage);
      document.removeEventListener("visibilitychange", refreshVisiblePage);
    };
  }, [liveConnected, reload]);
  const records = remote.data ?? [];
  const counts = {
    all: remote.data === null ? null : records.length,
    sending:
      remote.data === null
        ? null
        : records.filter(
            (record) => invitationState(record).group === "sending",
          ).length,
    awaiting:
      remote.data === null
        ? null
        : records.filter(
            (record) => invitationState(record).group === "awaiting",
          ).length,
    accepted:
      remote.data === null
        ? null
        : records.filter(
            (record) => invitationState(record).group === "accepted",
          ).length,
    attention:
      remote.data === null
        ? null
        : records.filter(
            (record) => invitationState(record).group === "attention",
          ).length,
  };
  function changeFilters(next: { role?: string; status?: Group }) {
    const updated = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value === "all") updated.delete(key);
      else updated.set(key, value);
    }
    setParams(updated, { replace: true });
    setPage(0);
  }
  function clearFilters() {
    setParams({}, { replace: true });
    setSearch("");
    setPage(0);
  }
  const query = normalize(search);
  const filtered = records
    .filter(
      (record) =>
        (roleFilter === "all" ||
          (record.role_slug ?? "guardian") === roleFilter) &&
        (group === "all" || invitationState(record).group === group) &&
        (!query ||
          normalize(`${personName(record)} ${record.email}`).includes(query)),
    )
    .sort((a, b) =>
      sort === "name"
        ? (personName(a) || a.email).localeCompare(
            personName(b) || b.email,
            getLocale(),
            { sensitivity: "base" },
          )
        : (sort === "oldest" ? 1 : -1) *
          (Date.parse(a.created_at) - Date.parse(b.created_at)),
    );
  const lastPage = Math.max(0, Math.ceil(filtered.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const visible = filtered.slice(
    currentPage * pageSize,
    (currentPage + 1) * pageSize,
  );
  const filteredView = roleFilter !== "all" || group !== "all" || !!query;
  function changed(record: Invitation, created = false) {
    setRemote((previous) => ({
      ...previous,
      data: [
        record,
        ...(previous.data ?? []).filter((item) => item.id !== record.id),
      ],
    }));
    setInvite(null);
    setSelected(null);
    setNotice(
      record.workos_state === "accepted"
        ? "This person has already joined your school."
        : record.send_status === "sent"
          ? "An invitation has already been sent to this email address."
          : "The invitation is queued. Its status will update automatically here.",
    );
    if (created) clearFilters();
    reload();
  }
  const summary = [
    { key: "all", title: "All invitations", icon: Mail },
    { key: "awaiting", title: "Awaiting acceptance", icon: Clock3 },
    { key: "accepted", title: "Joined the school", icon: CheckCircle2 },
    { key: "attention", title: "Invitations to follow up", icon: AlertCircle },
  ] as const;
  return (
    <div className="invitations-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("SCHOOL MANAGEMENT")}</p>
          <h1>{t("Invitations")}</h1>
          <p>
            {t(
              "Welcome your team and families, and follow every invitation in one place.",
            )}
          </p>
        </div>
        <div className="heading-actions">
          <button
            type="button"
            className="button subtle"
            disabled={remote.loading}
            onClick={reload}
          >
            <RefreshCw size={16} className={remote.loading ? "spin" : ""} />
            {t("Refresh")}
          </button>
          <button
            type="button"
            className="button subtle"
            onClick={() => setImportOpen(true)}
          >
            <FileUp size={16} />
            {t("Import CSV")}
          </button>
          <button
            type="button"
            className="button primary"
            onClick={() =>
              setInvite({
                role:
                  roleFilter === "all" ? null : (roleFilter as InvitationRole),
              })
            }
          >
            <UserPlus size={16} />
            {t("Invite a person")}
          </button>
        </div>
      </div>
      {notice && (
        <div className="iv-notice" role="status">
          <Check size={18} />
          <span>{t(notice)}</span>
          <button
            type="button"
            className="text-button"
            onClick={() => setNotice("")}
          >
            {t("Dismiss")}
          </button>
        </div>
      )}
      <section
        className="iv-welcome"
        aria-label={t("Invite your school community")}
      >
        <div>
          <span className="iv-welcome-icon">
            <UserPlus size={24} />
          </span>
          <h2>{t("Who would you like to invite?")}</h2>
          <p>
            {t(
              "Choose a profile to start. Their invitation gives them access to the right school workspace.",
            )}
          </p>
          <Link to="/members" className="text-button">
            {t("View school members")}
            <ArrowRight size={14} />
          </Link>
        </div>
        <div className="iv-quick-roles">
          {roles.map(({ value, plural, icon: Icon }) => (
            <button
              type="button"
              key={value}
              onClick={() => setInvite({ role: value })}
            >
              <Icon size={23} aria-hidden="true" />
              <span>{t(plural)}</span>
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          ))}
        </div>
      </section>
      <div className="iv-summary" aria-label={t("Invitation overview")}>
        {summary.map(({ key, title, icon: Icon }) => (
          <button
            type="button"
            key={key}
            aria-pressed={group === key}
            onClick={() => changeFilters({ status: key })}
          >
            <span>
              <span>{t(title)}</span>
              <Icon size={18} aria-hidden="true" />
            </span>
            <strong>{counts[key] ?? "—"}</strong>
            <small>
              {t(
                key === "attention"
                  ? "Failed, expired or revoked"
                  : key === "accepted"
                    ? "Access activated after acceptance"
                    : key === "awaiting"
                      ? "Waiting for an email response"
                      : "Teachers, families and administrators",
              )}
            </small>
          </button>
        ))}
      </div>
      <section
        className="panel iv-directory"
        aria-label={t("Invitation tracking")}
      >
        <header className="iv-directory-heading">
          <div>
            <h2>{t("Invitation tracking")}</h2>
            <span>
              {remote.data === null
                ? "—"
                : filtered.length === 1
                  ? t("1 invitation")
                  : t("{count} invitations").replace(
                      "{count}",
                      String(filtered.length),
                    )}
            </span>
          </div>
          <label className="iv-sort">
            <span>{t("Sort by")}</span>
            <select
              aria-label={t("Sort invitations")}
              value={sort}
              onChange={(event) => {
                setSort(event.target.value);
                setPage(0);
              }}
            >
              <option value="newest">{t("Newest first")}</option>
              <option value="oldest">{t("Oldest first")}</option>
              <option value="name">{t("Name")}</option>
            </select>
          </label>
        </header>
        <div className="iv-toolbar">
          <label className="iv-search">
            <Search size={17} aria-hidden="true" />
            <input
              type="search"
              aria-label={t("Search invitations")}
              placeholder={t("Search by name or email…")}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
            />
          </label>
          <label>
            <span className="sr-only">{t("Filter invitation roles")}</span>
            <select
              aria-label={t("Filter invitation roles")}
              value={roleFilter}
              onChange={(event) => changeFilters({ role: event.target.value })}
            >
              <option value="all">{t("All roles")}</option>
              {roles.map((role) => (
                <option key={role.value} value={role.value}>
                  {t(role.plural)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="sr-only">{t("Filter invitation statuses")}</span>
            <select
              aria-label={t("Filter invitation statuses")}
              value={group}
              onChange={(event) =>
                changeFilters({ status: event.target.value as Group })
              }
            >
              {groups.map((entry) => (
                <option key={entry.value} value={entry.value}>
                  {t(entry.title)}
                  {counts[entry.value] !== null
                    ? ` (${counts[entry.value]})`
                    : ""}
                </option>
              ))}
            </select>
          </label>
          {filteredView && (
            <button
              type="button"
              className="text-button"
              onClick={clearFilters}
            >
              {t("Clear filters")}
            </button>
          )}
        </div>
        {!!counts.sending && (
          <div className="iv-sending-note">
            <LoaderCircle size={16} className="spin" aria-hidden="true" />
            <span>
              {t(
                counts.sending === 1
                  ? "An invitation is being sent in the background."
                  : "{count} invitations are being sent in the background.",
              ).replace("{count}", String(counts.sending))}
            </span>
            <button
              type="button"
              className="text-button"
              onClick={() => changeFilters({ status: "sending" })}
            >
              {t("View sending invitations")}
            </button>
          </div>
        )}
        {remote.error && <ErrorBox error={remote.error} retry={reload} />}
        {remote.error && remote.data !== null && (
          <p className="iv-stale-note">
            {t(
              "Showing the last available results. Refresh to get the latest invitation statuses.",
            )}
          </p>
        )}
        {remote.data === null ? (
          remote.loading ? (
            <Loading />
          ) : null
        ) : !filtered.length ? (
          <div className="iv-empty">
            <Mail size={32} />
            <h3>
              {t(
                filteredView
                  ? "No invitations match your filters"
                  : "Bring your school community together",
              )}
            </h3>
            <p>
              {t(
                filteredView
                  ? "Try another name, email address, role or status."
                  : "Invite your first teacher, family contact or administrator to get started.",
              )}
            </p>
            <button
              type="button"
              className="button primary"
              onClick={() =>
                filteredView ? clearFilters() : setInvite({ role: null })
              }
            >
              {filteredView ? (
                t("Clear filters")
              ) : (
                <>
                  <UserPlus size={16} />
                  {t("Invite a person")}
                </>
              )}
            </button>
          </div>
        ) : (
          <>
            <div className="iv-table-wrap">
              <table className="iv-table">
                <thead>
                  <tr>
                    <th>{t("Person")}</th>
                    <th>{t("Role")}</th>
                    <th>{t("Invitation status")}</th>
                    <th>{t("Invitation created")}</th>
                    <th>{t("Actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((record) => {
                    const role = roleOf(record),
                      Icon = role.icon,
                      status = invitationState(record);
                    return (
                      <tr key={record.id}>
                        <td data-label={t("Person")}>
                          <Person invitation={record} />
                        </td>
                        <td data-label={t("Role")}>
                          <span className="iv-role">
                            <Icon size={15} aria-hidden="true" />
                            {t(role.title)}
                          </span>
                        </td>
                        <td data-label={t("Invitation status")}>
                          <Status invitation={record} />
                          <small className="iv-status-detail">
                            {status.group === "accepted"
                              ? t("School access activated")
                              : status.group === "awaiting" && record.expires_at
                                ? `${t("Valid until")} ${dateLabel(record.expires_at)}`
                                : status.group === "attention"
                                  ? t("You can resend this invitation")
                                  : t("Status updates automatically")}
                          </small>
                        </td>
                        <td
                          className="iv-created"
                          data-label={t("Invitation created")}
                        >
                          <time dateTime={record.created_at}>
                            {dateLabel(record.created_at)}
                          </time>
                        </td>
                        <td
                          className="iv-row-actions"
                          data-label={t("Actions")}
                        >
                          {canRetryInvitation(record) && (
                            <button
                              type="button"
                              className="button small subtle"
                              onClick={() =>
                                setSelected({
                                  invitation: record,
                                  confirm: true,
                                })
                              }
                              aria-label={t(
                                "Resend invitation to {email}",
                              ).replace("{email}", record.email)}
                            >
                              <Send size={14} />
                              {t(
                                record.send_status === "failed"
                                  ? "Retry sending"
                                  : "Resend",
                              )}
                            </button>
                          )}
                          <button
                            type="button"
                            className="iv-detail-button"
                            onClick={() =>
                              setSelected({
                                invitation: record,
                                confirm: false,
                              })
                            }
                            aria-label={t(
                              "View invitation for {email}",
                            ).replace("{email}", record.email)}
                          >
                            <Info size={16} />
                            <span>{t("Details")}</span>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <footer className="iv-pagination">
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
                  aria-label={t("Previous page")}
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  <ChevronLeft size={18} />
                </button>
                <span>
                  {currentPage + 1} / {lastPage + 1}
                </span>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t("Next page")}
                  disabled={currentPage >= lastPage}
                  onClick={() => setPage(currentPage + 1)}
                >
                  <ChevronRight size={18} />
                </button>
              </div>
            </footer>
          </>
        )}
      </section>
      <p className="iv-footnote">
        <ShieldCheck size={15} aria-hidden="true" />
        {t(
          "An accepted invitation activates school access. Child registrations and class assignments are managed separately.",
        )}
      </p>
      {invite && (
        <InvitePerson
          initialRole={invite.role}
          onClose={() => setInvite(null)}
          onDone={(record) => changed(record, true)}
        />
      )}
      {importOpen && (
        <InvitationCsvImport
          onClose={() => setImportOpen(false)}
          onDone={reload}
        />
      )}
      {selected && (
        <InvitationDetails
          invitation={selected.invitation}
          confirmInitially={selected.confirm}
          refreshRevision={revision}
          onClose={() => setSelected(null)}
          onDone={(record) => changed(record)}
        />
      )}
    </div>
  );
}
