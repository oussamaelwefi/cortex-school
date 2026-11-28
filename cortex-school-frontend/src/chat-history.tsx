import { useEffect, useState } from "react";
import { LoaderCircle, MessageSquare, Trash2, X } from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { getLocale, t } from "./i18n";
import type { Role } from "./types";
import { Modal } from "./ui";

const list = findEndpoint("GET", "/ai/chat/conversations/");
const remove = findEndpoint(
  "DELETE",
  "/ai/chat/conversations/{conversation_id}/",
);
export const conversationEndpoint = findEndpoint(
  "GET",
  "/ai/chat/conversations/{conversation_id}/",
);

type ConversationSummary = {
  id: string;
  title: string;
  updated_at: string;
};
type ConversationList = {
  conversations: ConversationSummary[];
  next_offset: number | null;
};
export type ChatSource = {
  id: string;
  label: string;
  href?: string | null;
  excerpt?: string | null;
};
export type SavedConversation = ConversationSummary & {
  messages: {
    id: string;
    sender: "user" | "assistant";
    text: string | null;
    sources: ChatSource[];
    created_at: string;
  }[];
  before_turn: number | null;
};

export function ChatHistory({
  role,
  selected,
  disabled,
  onOpen,
  onDeleted,
  onClose,
}: {
  role: Role;
  selected: string | null;
  disabled: boolean;
  onOpen: (id: string) => void;
  onDeleted: (id: string) => void;
  onClose: () => void;
}) {
  const api = useApi();
  const [rows, setRows] = useState<ConversationSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [next, setNext] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api(list, { role, offset })
      .then((page: ConversationList) => {
        if (!active) return;
        setRows((previous) =>
          offset
            ? [
                ...previous,
                ...page.conversations.filter(
                  (row) => !previous.some((item) => item.id === row.id),
                ),
              ]
            : page.conversations,
        );
        setNext(page.next_offset);
      })
      .catch((failure: Error) => {
        if (active) setError(failure.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, offset, revision, role]);

  async function confirmDelete() {
    if (!pending || deleting) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await api(remove, { role, conversation_id: pending.id });
      onDeleted(pending.id);
    } catch (failure) {
      setDeleteError((failure as Error).message);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <aside
      id="chat-history"
      className="chat-history"
      aria-label={t("Conversation history")}
    >
      <header>
        <h2>{t("Conversation history")}</h2>
        <button
          className="chat-history-icon"
          type="button"
          onClick={onClose}
          aria-label={t("Close history")}
        >
          <X size={16} />
        </button>
      </header>
      <div className="chat-history-list">
        {rows.length > 0 && (
          <ul>
            {rows.map((row) => (
              <li
                key={row.id}
                className={row.id === selected ? "selected" : ""}
              >
                <button
                  className="chat-history-row"
                  type="button"
                  aria-current={row.id === selected ? "true" : undefined}
                  disabled={disabled}
                  onClick={() => onOpen(row.id)}
                  title={row.title}
                >
                  <MessageSquare size={15} aria-hidden="true" />
                  <span>
                    <strong>{row.title}</strong>
                    <time dateTime={row.updated_at}>
                      {new Date(row.updated_at).toLocaleDateString(
                        getLocale(),
                        { day: "numeric", month: "short", year: "numeric" },
                      )}
                    </time>
                  </span>
                </button>
                <button
                  type="button"
                  className="chat-history-icon"
                  aria-label={`${t("Delete conversation")} · ${row.title}`}
                  disabled={disabled}
                  onClick={() => {
                    setDeleteError("");
                    setPending(row);
                  }}
                >
                  <Trash2 size={15} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
        {loading && (
          <p role="status">
            <LoaderCircle className="spin" size={15} />{" "}
            {t("Loading conversations…")}
          </p>
        )}
        {error && (
          <div role="alert">
            <p>{t(error)}</p>
            <button
              type="button"
              onClick={() => setRevision((value) => value + 1)}
            >
              {t("Retry")}
            </button>
          </div>
        )}
        {!loading && !error && !rows.length && (
          <p>{t("No saved conversations yet.")}</p>
        )}
        {!loading && !error && next !== null && (
          <button
            className="chat-history-more"
            type="button"
            onClick={() => setOffset(next)}
          >
            {t("Show more conversations")}
          </button>
        )}
      </div>
      {pending && (
        <Modal
          title="Delete conversation"
          onClose={() => {
            if (!deleting) setPending(null);
          }}
        >
          <p>{t("Delete this conversation and its messages?")}</p>
          <p>
            <strong>{pending.title}</strong>
          </p>
          {deleteError && <p role="alert">{t(deleteError)}</p>}
          <footer className="actions">
            <button
              type="button"
              className="button secondary"
              disabled={deleting}
              onClick={() => setPending(null)}
            >
              {t("Cancel")}
            </button>
            <button
              type="button"
              className="button danger"
              disabled={deleting}
              onClick={() => void confirmDelete()}
            >
              {t("Delete conversation")}
            </button>
          </footer>
        </Modal>
      )}
    </aside>
  );
}
