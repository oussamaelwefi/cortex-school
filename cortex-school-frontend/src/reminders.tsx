import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Bell, BookOpen, FileText, LoaderCircle, Send, Sparkles, Trash2 } from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { label } from "./forms";
import { t } from "./i18n";
import { Badge, display, Empty, ErrorBox, Loading, Modal, useRemote } from "./ui";
import type { Data } from "./types";
import { PolicyDocument } from "./policy-document";

const readReminderPath = "/student-updates/{update_id}/reminder";
const getReminder = findEndpoint("GET", readReminderPath);
const prepareReminder = { ...findEndpoint("POST", readReminderPath), timeoutMs: 60000 };
const approveReminder = findEndpoint("POST", "/reminder-proposals/{proposal_id}/approve");
const listPolicies = findEndpoint("GET", "/school-policies");
const addPolicy = findEndpoint("POST", "/school-policies");
const uploadPolicyPdf = findEndpoint("POST", "/school-policies/pdf");
const downloadAdminPolicy = findEndpoint("GET", "/school-policies/{document_id}/pdf");
const deleteAdminPolicy = findEndpoint("DELETE", "/school-policies/{document_id}");
const downloadGuardianPolicy = findEndpoint("GET", "/guardian/family/policies/{document_id}/pdf/");
const getGuardianUpdate = findEndpoint("GET", "/guardian/updates/{recipient_id}/");
const acknowledgeUpdate = findEndpoint("POST", "/guardian/updates/{recipient_id}/acknowledge/");
const markNotificationRead = findEndpoint("POST", "/guardian/notifications/{notification_id}/read/");

type DeliveryStatus = "pending" | "sent" | "skipped" | "failed";
type Proposal = {
  id: string;
  message: string;
  status: "draft" | "queued" | "completed";
  sources: { id: string; title: string; heading: string; excerpt: string }[];
  recipients: {
    guardian_id: string;
    guardian_name: string | null;
    students: { recipient_id: string; name: string }[];
    status: DeliveryStatus;
    outcome_reason: string | null;
  }[];
};
type Review = {
  title: string;
  due_at: string | null;
  needs_reminder: boolean;
  pending_guardian_count: number;
  proposal: Proposal | null;
};

export function reminderReviewHref(row: Data): string | undefined {
  const updateId = row.category === "acknowledgement" && row.action?.type === "student_update"
    ? row.action.update_id
    : row.requires_acknowledgement && row.due_at && Date.parse(row.due_at) < Date.now()
      ? row.update_id
      : undefined;
  return typeof updateId === "string" ? `/updates/${encodeURIComponent(updateId)}/reminder` : undefined;
}

export function ReminderReviewPage() {
  const { updateId } = useParams();
  return updateId ? <ReminderReview key={updateId} updateId={updateId} /> : null;
}

function ReminderReview({ updateId }: { updateId: string }) {
  const api = useApi();
  const [reload, setReload] = useState(0);
  const state = useRemote(getReminder, { update_id: updateId }, reload);
  const [latest, setLatest] = useState<Review | null>(null);
  const [pendingAction, setPendingAction] = useState<"standard" | "ai" | "approve" | null>(null);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const review = latest ?? (state.data as Review | null);
  const proposal = review?.proposal;
  const queued = review?.proposal?.status === "queued";
  const busy = pendingAction !== null;

  useEffect(() => {
    if (!queued) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data: Review = await api(getReminder, { update_id: updateId });
        if (!active) return;
        setPollError("");
        setLatest(data);
        if (data.proposal?.status !== "queued") return;
      } catch (err) {
        if (!active) return;
        setPollError((err as Error).message);
      }
      timer = setTimeout(poll, 2500);
    }
    timer = setTimeout(poll, 2500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, updateId, queued]);

  async function prepare(message?: string) {
    setPendingAction(message === undefined ? "ai" : "standard");
    setError("");
    try {
      setLatest(await api(prepareReminder, { update_id: updateId }, message === undefined ? undefined : { message }));
    } catch (err) {
      setError((err as Error).message);
      setReload((value) => value + 1);
    } finally {
      setPendingAction(null);
    }
  }

  async function approve(proposalId: string, message: string, includePolicySources: boolean) {
    setPendingAction("approve");
    setError("");
    try {
      setLatest(await api(approveReminder, { proposal_id: proposalId }, {
        message, include_policy_sources: includePolicySources,
      }));
    } catch (err) {
      setError((err as Error).message);
      try {
        setLatest(await api(getReminder, { update_id: updateId }));
      } catch {
        // Keep the draft and report the approval error.
      }
    } finally {
      setPendingAction(null);
    }
  }

  if (!review) {
    if (state.error) return <ErrorBox error={state.error} retry={() => setReload((value) => value + 1)} />;
    return <Loading />;
  }

  const standardMessage = t(
    "Please review and acknowledge the notice “{title}” in Cortex School. Thank you.",
  ).replace("{title}", () => review.title);

  return (
    <>
      <div className="page-heading">
        <div>
          <Link className="text-button" to="/review"><ArrowLeft size={15} />{t("Needs review")}</Link>
          <h1>{t("Acknowledgement reminder")}</h1>
          <p>{review.title}{review.due_at && ` · ${t("Due")} ${display(review.due_at)}`}</p>
        </div>
        <div className="heading-actions">
          <SchoolPoliciesButton />
        </div>
      </div>
      <section className="panel reminder-panel">
        {proposal ? (
          <ProposalView
            key={proposal.id}
            proposal={proposal}
            standardMessage={standardMessage}
            busy={busy}
            onApprove={(message, includePolicySources) => approve(proposal.id, message, includePolicySources)}
          />
        ) : (
          <>
            <h2>{t("Prepare a reminder")}</h2>
            {review.pending_guardian_count > 0 ? (
              <>
                <p>{t("Guardians awaiting a reminder")} · {review.pending_guardian_count}</p>
                <div className="reminder-actions">
                  <button type="button" className="button primary" onClick={() => prepare(standardMessage)} disabled={busy}>
                    {pendingAction === "standard" ? <LoaderCircle className="spin" size={16} /> : <Bell size={16} />}
                    {t(pendingAction === "standard" ? "Preparing reminder…" : "Use standard reminder")}
                  </button>
                  <button type="button" className="button subtle" onClick={() => prepare()} disabled={busy}>
                    {pendingAction === "ai" ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}
                    {t(pendingAction === "ai" ? "Preparing reminder…" : "Draft from school policy")}
                  </button>
                </div>
              </>
            ) : (
              <p>{t(review.needs_reminder
                ? "There are no outstanding guardian acknowledgements for this notice."
                : "Reminders are available once a required acknowledgement is overdue.")}</p>
            )}
          </>
        )}
        {error && <ErrorBox error={error} />}
        {pollError && <ErrorBox error={pollError} />}
      </section>
    </>
  );
}

function ProposalView({ proposal, standardMessage, busy, onApprove }: {
  proposal: Proposal;
  standardMessage: string;
  busy: boolean;
  onApprove: (message: string, includePolicySources: boolean) => void;
}) {
  const [message, setMessage] = useState(proposal.message);
  const [usingStandardMessage, setUsingStandardMessage] = useState(false);
  const draft = proposal.status === "draft";
  const sources = draft && usingStandardMessage ? [] : proposal.sources;
  const counts = { pending: 0, sent: 0, skipped: 0, failed: 0 };
  for (const recipient of proposal.recipients) counts[recipient.status] += 1;

  return (
    <>
      <div className="reminder-panel-title">
        <h2>{t(draft ? "Review reminder proposal" : "Reminder results")}</h2>
        <span className="badge">{t(draft ? "Awaiting approval" :
          proposal.status === "queued" ? "Queued for delivery" : "Delivery complete")}</span>
      </div>
      <div className={sources.length ? "reminder-columns" : undefined}>
        {draft ? (
          <label className="field">
            <span>{t("Reminder message")}</span>
            <textarea rows={7} maxLength={1200} value={message} disabled={busy}
              onChange={(event) => setMessage(event.target.value)} />
          </label>
        ) : (
          <div>
            <h3>{t("Approved message")}</h3>
            <p className="reminder-copy">{proposal.message}</p>
          </div>
        )}
        {sources.length > 0 && (
          <section aria-label={t("Policy sources for the draft")}>
            <h3 className="reminder-source-title"><BookOpen size={16} />{t("Policy sources for the draft")}</h3>
            {draft && <p>{t("Recipients can see these policy excerpts.")}</p>}
            {sources.map((source) => (
              <blockquote key={source.id} className="reminder-source">
                <strong>{source.title} · {source.heading}</strong>
                <p>{source.excerpt}</p>
              </blockquote>
            ))}
          </section>
        )}
      </div>
      <h3>{t("Recipients")} ({proposal.recipients.length})</h3>
      {draft ? <p>{t("The system rechecks acknowledgements before sending.")}</p> : (
        <p role="status">{t("Sent")} {counts.sent} · {t("Skipped")} {counts.skipped} · {t("Failed")} {counts.failed}
          {counts.pending > 0 && ` · ${t("Pending")} ${counts.pending}`}</p>
      )}
      <ul className="reminder-recipients">
        {proposal.recipients.map((recipient) => (
          <li key={recipient.guardian_id}>
            <div>
              <strong>{recipient.guardian_name ?? recipient.guardian_id}</strong>
              <p>{recipient.students.map((student) => student.name).join(", ")}</p>
              {recipient.outcome_reason && <p>{t(recipient.outcome_reason)}</p>}
            </div>
            <Badge value={recipient.status} />
          </li>
        ))}
      </ul>
      {draft && (
        <div className="reminder-actions reminder-approval-actions">
          <button type="button" className="button subtle" disabled={busy || (message === standardMessage && !sources.length)}
            onClick={() => { setMessage(standardMessage); setUsingStandardMessage(true); }}>
            {t("Use standard message")}
          </button>
          <button type="button" className="button primary" disabled={busy || !message.trim()}
            onClick={() => onApprove(message.trim(), !usingStandardMessage)}>
            {busy ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />}
            {t(busy ? "Approving…" : "Approve and send")}
          </button>
        </div>
      )}
    </>
  );
}

export function SchoolPoliciesButton() {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  return (
    <>
      <button type="button" className="button subtle" aria-haspopup="dialog" onClick={() => setOpen(true)}>
        <BookOpen size={16} /> {t("School policies")}
      </button>
      {open && (
        <Modal title="School policies" wide onClose={close}>
          <PolicyLibrary />
        </Modal>
      )}
    </>
  );
}

function PolicyLibrary() {
  const api = useApi();
  const [refresh, setRefresh] = useState(0);
  const policies = useRemote(listPolicies, {}, refresh);
  const [mode, setMode] = useState<"pdf" | "text">("pdf");
  const [pdf, setPdf] = useState<File>();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const saving = busy || deleting;
  const uploadingPdf = mode === "pdf";
  const ready = uploadingPdf ? Boolean(pdf) : Boolean(title.trim() && text.trim());

  function selectMode(nextMode: "pdf" | "text") {
    if (nextMode === mode) return;
    setMode(nextMode);
    setPdf(undefined);
    setStatus("");
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || saving || pendingRemoval) return;
    const form = event.currentTarget;
    setStatus("");
    setError("");
    if (uploadingPdf && pdf && pdf.size > 10 * 1024 * 1024) {
      setError("Choose a PDF of 10 MB or less.");
      return;
    }
    setBusy(true);
    try {
      if (uploadingPdf) {
        await api(uploadPolicyPdf, {}, undefined, pdf);
        form.reset();
        setPdf(undefined);
      } else {
        await api(addPolicy, {}, { title: title.trim(), text: text.trim() });
        setTitle("");
        setText("");
      }
      setStatus(uploadingPdf ? "PDF available to guardians." : "Policy added.");
      setRefresh((value) => value + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(policy: PolicyFile) {
    if (saving) return;
    setDeleting(true);
    setError("");
    setStatus("");
    try {
      await api(deleteAdminPolicy, { document_id: policy.id });
      setPendingRemoval(null);
      setStatus("Policy deleted.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRefresh((value) => value + 1);
      setDeleting(false);
    }
  }

  return (
    <div className="modal-body">
      <h3>{t("School policy library")}</h3>
      {status && <p role="status">{t(status)}</p>}
      {error && <ErrorBox error={error} />}
      {policies.loading && <Loading />}
      {policies.error && <ErrorBox error={policies.error} retry={() => setRefresh((value) => value + 1)} />}
      {policies.data?.length ? (
        <ul className="policy-library-list">
          {policies.data.map((policy: PolicyFile & { passage_count: number; has_pdf: boolean }) => (
            <li className="policy-library-item" key={policy.id}>
              <div className="policy-library-info">
                <strong>{policy.title}</strong>
                <small>
                  {policy.passage_count} {t(policy.passage_count === 1 ? "passage" : "passages")} · {t(policy.has_pdf ? "Available to guardians" : "Indexed text only")}
                </small>
              </div>
              {pendingRemoval === policy.id ? (
                <div className="policy-delete-confirmation" role="group" aria-label={t("Confirm policy deletion")}>
                  <strong>{t("Delete this policy?")}</strong>
                  <p>{t("This removes the policy from the school library and future searches.")}</p>
                  <div className="reminder-actions">
                    <button type="button" className="button small subtle" autoFocus disabled={deleting}
                      onClick={() => setPendingRemoval(null)}>{t("Cancel")}</button>
                    <button type="button" className="button small danger" disabled={deleting}
                      onClick={() => remove(policy)}>{t(deleting ? "Deleting…" : "Delete policy")}</button>
                  </div>
                </div>
              ) : (
                <div className="reminder-actions">
                  <button type="button" className="button small subtle" disabled={saving || pendingRemoval !== null}
                    aria-label={`${t("Delete policy")} · ${policy.title}`} onClick={() => setPendingRemoval(policy.id)}>
                    <Trash2 size={15} />{t("Delete")}
                  </button>
                </div>
              )}
              {policy.has_pdf && pendingRemoval !== policy.id && (
                <PolicyDocument policy={policy} endpoint={downloadAdminPolicy} disabled={saving} />
              )}
            </li>
          ))}
        </ul>
      ) : !policies.loading && !policies.error && <p>{t("No school policies have been added yet.")}</p>}
      <form onSubmit={submit} className="reminder-policy-form">
        <div className="reminder-actions">
          <button type="button" className="button subtle" aria-pressed={uploadingPdf} disabled={busy}
            onClick={() => selectMode("pdf")}>
            {t("PDF file")}
          </button>
          <button type="button" className="button subtle" aria-pressed={!uploadingPdf} disabled={busy}
            onClick={() => selectMode("text")}>
            {t("Paste text")}
          </button>
        </div>
        {uploadingPdf ? (
          <label className="upload field">
            <span>{t("Policy PDF")}</span>
            <input type="file" accept=".pdf,application/pdf" required disabled={busy}
              onChange={(event) => setPdf(event.target.files?.[0])} />
            <small>{t("Choose a PDF with selectable text, up to 10 MB and 100 pages.")}</small>
            <small>{t("Guardians at your school can read uploaded PDFs online.")}</small>
          </label>
        ) : (
          <>
            <label className="field">
              <span>{t("Policy title")}</span>
              <input required maxLength={200} value={title} disabled={busy}
                onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="field">
              <span>{t("Policy text")}</span>
              <textarea required maxLength={16000} rows={5} value={text} disabled={busy}
                onChange={(event) => setText(event.target.value)} />
              <small>{t("Separate paragraphs with a blank line. Start a section heading with #.")}</small>
            </label>
          </>
        )}
        <button type="submit" className="button primary" disabled={saving || pendingRemoval !== null || !ready}>
          {uploadingPdf ? t(busy ? "Uploading PDF…" : "Upload PDF") : t(busy ? "Adding policy…" : "Add policy")}
        </button>
      </form>
    </div>
  );
}

type PolicyFile = { id: string; title: string };
type GuardianPolicySource = {
  id: string;
  document_id: string;
  title: string;
  heading: string;
  excerpt: string;
  has_pdf: boolean;
};

export function GuardianPolicyList({ policies }: { policies: PolicyFile[] }) {
  if (!policies.length) return <Empty title="No school policy PDFs yet" text="Files shared by your school will appear here." />;

  return (
    <div className="feed-list">
      {policies.map((policy) => (
        <article className="feed-card policy-file" key={policy.id}>
          <span className="avatar"><FileText size={17} /></span>
          <h3>{policy.title}</h3>
          <PolicyDocument policy={policy} endpoint={downloadGuardianPolicy} />
        </article>
      ))}
    </div>
  );
}

function GuardianReminderSources({ sources, defaultExpanded = false }: {
  sources: GuardianPolicySource[];
  defaultExpanded?: boolean;
}) {
  const panelId = useId();
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (!sources.length) return null;
  return (
    <div className="guardian-reminder-sources">
      <button type="button" className="button small subtle" aria-expanded={expanded} aria-controls={panelId}
        onClick={() => setExpanded(!expanded)}>
        <BookOpen size={15} />
        {t(expanded ? "Hide policy sources" : "View policy sources")}
      </button>
      <div id={panelId} hidden={!expanded}>
        {sources.map((source) => (
          <div key={source.id} className="reminder-source">
            <strong>{source.title} · {t(source.heading)}</strong>
            <blockquote>{source.excerpt}</blockquote>
            {source.has_pdf && (
              <PolicyDocument policy={{ id: source.document_id, title: source.title }} endpoint={downloadGuardianPolicy} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function GuardianNotifications({
  data,
  onChanged,
}: {
  data: Data[];
  onChanged: () => void;
}) {
  const api = useApi();
  const [selected, setSelected] = useState<Data | null>(null);
  const [marking, setMarking] = useState<string | null>(null);
  const [error, setError] = useState("");
  async function markRead(id: string) {
    setMarking(id);
    setError("");
    try {
      await api(markNotificationRead, { notification_id: id });
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setMarking(null);
    }
  }

  if (!data.length)
    return (
      <Empty
        title="No notifications"
        text="Notifications from your school will appear here."
      />
    );
  return (
    <div className="feed-list resource-feed-list">
      {error && <ErrorBox error={error} />}
      {data.map((notification) => (
        <article
          className="feed-card resource-feed-card resource-notification"
          data-unread={!notification.read_at}
          key={notification.id}
        >
          <div className="feed-meta">
            <span className="avatar" aria-hidden="true">
              <Bell size={19} />
            </span>
            <div>
              <h3>{notification.update_title}</h3>
              <p>
                {notification.student_first_name}{" "}
                {notification.student_last_name} ·{" "}
                <time dateTime={notification.created_at}>
                  {display(notification.created_at)}
                </time>
              </p>
            </div>
            <Badge value={notification.read_at ? "read" : "unread"} />
          </div>
          <p className="resource-notification-type">
            {notification.notification_type === "acknowledgement_reminder"
              ? t("Acknowledgement reminder")
              : label(notification.notification_type)}
          </p>
          {notification.message && (
            <p className="prose reminder-copy" dir="auto">
              {notification.message}
            </p>
          )}
          <GuardianReminderSources
            sources={notification.policy_sources ?? []}
          />
          {(notification.recipient_id || !notification.read_at) && (
            <div className="record-actions">
              {notification.recipient_id && (
                <button
                  type="button"
                  className="button small subtle"
                  onClick={() => setSelected(notification)}
                >
                  {t("Open update")}
                </button>
              )}
              {!notification.read_at && (
                <button
                  type="button"
                  className="button small subtle"
                  disabled={marking !== null}
                  onClick={() => markRead(notification.id)}
                >
                  {t("Mark as read")}
                </button>
              )}
            </div>
          )}
        </article>
      ))}
      {selected && (
        <GuardianUpdateDialog
          notification={selected}
          onClose={() => setSelected(null)}
          onAcknowledged={() => {
            setSelected(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
export function GuardianUpdateDialog({ notification, onClose, onAcknowledged }: {
  notification: Data;
  onClose: () => void;
  onAcknowledged: () => void;
}) {
  const api = useApi();
  const params = { recipient_id: notification.recipient_id };
  const update = useRemote(getGuardianUpdate, params);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function acknowledge() {
    setBusy(true);
    setError("");
    try {
      await api(acknowledgeUpdate, params);
      onAcknowledged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={notification.update_title} onClose={onClose}>
      <div className="modal-body">
        {update.loading ? <Loading /> : update.error ? <ErrorBox error={update.error} /> : (
          <>
            {update.data?.body && <p className="prose reminder-copy">{update.data.body}</p>}
            {update.data?.due_at && <p>{t("Due")} {display(update.data.due_at)}</p>}
            {update.data?.requires_acknowledgement && !update.data.acknowledged_at && (
              <button type="button" className="button primary" disabled={busy} onClick={acknowledge}>
                {t("Acknowledge")}
              </button>
            )}
            {update.data?.acknowledged_at && <Badge value="acknowledged" />}
            {error && <ErrorBox error={error} />}
          </>
        )}
        <GuardianReminderSources sources={notification.policy_sources ?? []} defaultExpanded />
      </div>
    </Modal>
  );
}
