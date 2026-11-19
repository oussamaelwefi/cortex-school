import { useContext, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  LoaderCircle,
  Send,
  Sparkles,
  Users,
} from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { CurrentUserContext } from "./current-user";
import { t } from "./i18n";
import { ChoicesContext, ErrorBox, Modal, ToastContext } from "./ui";
import type { Data } from "./types";

type Draft = {
  outcome: "draft" | "needs_more_information";
  title: string | null;
  body: string | null;
  questions: string[];
};
type Audience = {
  classroom_id: string;
  target_type: "classroom" | "students";
  student_names: string[];
  student_count: number;
  unique_guardian_count: number;
};

const signaturePlaceholder =
  /\[\s*(?:nom\s+de\s+l['’]enseignant(?:\(e\)|e)?|teacher(?:['’]s)?\s+name|your\s+name|votre\s+nom|اسم\s+المعلم(?:ة)?)\s*\]/giu;

export function withTeacherSignature(body: string, displayName: string) {
  const name = displayName.trim();
  const text = body.trim();
  const replaced = text.replace(signaturePlaceholder, () => name).trim();
  if (
    !name ||
    replaced !== text ||
    replaced.split(/\r?\n/).at(-1)?.trim() === name
  )
    return replaced;
  return `${replaced}\n\n${name}`;
}

export function TeacherDraftReview({
  draft,
  request,
  onBack,
  onClose,
  onDone,
}: {
  draft: Draft;
  request: Data;
  onBack: () => void;
  onClose: () => void;
  onDone: () => void;
}) {
  const api = useApi();
  const toast = useContext(ToastContext);
  const { displayName } = useContext(CurrentUserContext);
  const choices = useContext(ChoicesContext);
  const classroomName =
    choices.classroom_id?.find(
      (choice) => choice.value === request.classroom_id,
    )?.label || t("Selected class");
  const [title, setTitle] = useState(draft.title || "");
  const [message, setMessage] = useState(() =>
    withTeacherSignature(draft.body || "", displayName),
  );
  const [signature, setSignature] = useState("");
  const [audience, setAudience] = useState<Audience | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const clarification = draft.outcome === "needs_more_information";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending.current || clarification) return;
    setError("");
    const signedMessage = !displayName.trim()
      ? withTeacherSignature(message, signature)
      : message.trim();
    if (!title.trim() || !signedMessage.trim()) {
      setError("Enter a title and a message before continuing.");
      return;
    }
    if (!displayName.trim() && !signature.trim()) {
      setError("Enter your name for the signature before publishing.");
      return;
    }
    if (title.trim().length > 255 || signedMessage.length > 5000) {
      setError(
        "Use at most 255 characters for the title and 5,000 for the message.",
      );
      return;
    }
    pending.current = true;
    setBusy(true);
    try {
      if (!audience) {
        const preview = await api(
          findEndpoint("POST", "/teacher/updates/preview/"),
          {},
          {
            classroom_id: request.classroom_id,
            target: request.target,
          },
        );
        setMessage(signedMessage);
        setAudience(preview);
      } else {
        await api(
          findEndpoint("POST", "/teacher/updates/"),
          {},
          {
            classroom_id: request.classroom_id,
            target: request.target,
            title: title.trim(),
            body: signedMessage,
          },
        );
        toast(t("Update published"));
        onDone();
        onClose();
      }
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  return (
    <Modal
      title={
        clarification
          ? "Complete your observations"
          : audience
            ? "Confirm publication"
            : "Review your AI draft"
      }
      subtitle={classroomName}
      onClose={() => {
        if (!pending.current) onClose();
      }}
      wide
    >
      <form onSubmit={submit} className="tdr-form">
        <div className="modal-body tdr-body">
          <div className="tdr-notice">
            <Sparkles size={19} aria-hidden="true" />
            <p>
              {t(
                clarification
                  ? "Add the missing details to generate a useful draft."
                  : audience
                    ? "Do you want to publish this message to the selected families?"
                    : "Review and edit this draft. Nothing is published until you confirm.",
              )}
            </p>
          </div>
          {clarification ? (
            <ul className="tdr-questions">
              {draft.questions.map((question, index) => (
                <li key={index}>{question}</li>
              ))}
            </ul>
          ) : audience ? (
            <>
              <section
                className="tdr-audience"
                aria-label={t("Publication recipients")}
              >
                <div className="tdr-audience-heading">
                  <Users size={19} />
                  <strong>
                    {classroomName} ·{" "}
                    {t(
                      audience.target_type === "classroom"
                        ? "Whole class"
                        : "Selected students",
                    )}
                  </strong>
                </div>
                <dl>
                  <div>
                    <dt>{t("Students")}</dt>
                    <dd>{audience.student_count}</dd>
                  </div>
                  <div>
                    <dt>{t("Family accounts")}</dt>
                    <dd>{audience.unique_guardian_count}</dd>
                  </div>
                </dl>
                <details>
                  <summary>{t("View student recipients")}</summary>
                  <ul>
                    {audience.student_names.map((name, index) => (
                      <li key={index}>{name}</li>
                    ))}
                  </ul>
                </details>
                {audience.unique_guardian_count === 0 && (
                  <p>
                    {t(
                      "No family account is currently linked to these students.",
                    )}
                  </p>
                )}
              </section>
              <article
                className="tdr-preview"
                aria-label={t("Message to publish")}
              >
                <h3>{title}</h3>
                <p>{message}</p>
              </article>
            </>
          ) : (
            <div className="tdr-fields">
              <label className="field">
                <span>{t("Title")} *</span>
                <input
                  required
                  maxLength={255}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  disabled={busy}
                />
              </label>
              <label className="field">
                <span>{t("Message")} *</span>
                <textarea
                  required
                  rows={10}
                  maxLength={5000}
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  disabled={busy}
                />
                <small>{message.length} / 5 000</small>
              </label>
              {displayName.trim() ? (
                <p className="tdr-signature">
                  <Check size={15} />
                  {t("Your profile name has been added to the signature.")}
                </p>
              ) : (
                <label className="field">
                  <span>{t("Teacher signature")} *</span>
                  <input
                    required
                    maxLength={150}
                    value={signature}
                    onChange={(event) => setSignature(event.target.value)}
                    disabled={busy}
                  />
                  <small>
                    {t(
                      "Your profile has no name. Enter the signature to use for this message.",
                    )}
                  </small>
                </label>
              )}
            </div>
          )}
          {error && <ErrorBox error={t(error)} />}
        </div>
        <footer className="tdr-actions">
          <button
            type="button"
            className="button subtle"
            disabled={busy}
            onClick={() => {
              setError("");
              if (audience) setAudience(null);
              else onBack();
            }}
          >
            <ArrowLeft size={16} />
            {t(audience ? "Back to draft" : "Edit observations")}
          </button>
          {!clarification && (
            <button className="button primary" disabled={busy}>
              {busy ? (
                <LoaderCircle className="spin" size={16} />
              ) : audience ? (
                <Send size={16} />
              ) : (
                <Users size={16} />
              )}
              {t(
                busy
                  ? audience
                    ? "Publishing…"
                    : "Checking recipients…"
                  : audience
                    ? "Confirm publication"
                    : "Review recipients",
              )}
            </button>
          )}
        </footer>
      </form>
    </Modal>
  );
}
