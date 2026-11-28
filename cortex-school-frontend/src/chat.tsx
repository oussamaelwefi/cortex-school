import { t, getLocale } from "./i18n";
import { useEffect, useRef, useState } from "react";
import {
  Check,
  Copy,
  LoaderCircle,
  Send,
  Sparkles,
  ThumbsUp,
  Volume2,
  VolumeX,
  Plus,
  ArrowUpRight,
  Database,
  BookOpen,
  History,
} from "lucide-react";
import { Link } from "react-router-dom";
import { findEndpoint, useApi } from "./api";
import { getChatContent } from "./chat-content.mjs";
import { ChatDataAccessControl } from "./chat-data-access";
import {
  ChatHistory,
  conversationEndpoint,
  type ChatSource,
  type SavedConversation,
} from "./chat-history";
import type { Role } from "./types";
import "./chat.css";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  time: Date;
  sources?: ChatSource[];
  hidden?: boolean;
};
const hiddenReply =
  "This saved reply is unavailable because its school data changed or can no longer be verified.";
const welcome = (role: Role): Message => ({
  id: "welcome",
  role: "assistant",
  text: getChatContent(role).welcome,
  time: new Date(),
});
export function ChatAssistant({ role }: { role: Role }) {
  const api = useApi();
  const contentForRole = getChatContent(role);
  const suggestions = contentForRole.suggestions;
  const [messages, setMessages] = useState<Message[]>(() => [welcome(role)]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [beforeTurn, setBeforeTurn] = useState<number | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [failed, setFailed] = useState<Message | null>(null);
  const [copied, setCopied] = useState("");
  const [liked, setLiked] = useState<Set<string>>(new Set());
  const [speaking, setSpeaking] = useState("");
  const lock = useRef(false);
  const historyLock = useRef(false);
  const privacyRevision = useRef<number | null>(null);
  const generation = useRef(0);
  const [dataEnabled, setDataEnabled] = useState<boolean | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const scrollAnchor = useRef<{ height: number; top: number } | null>(null);
  const historyToggle = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const active = useRef(true);
  const speechSupported =
    typeof window !== "undefined" && "speechSynthesis" in window;
  const messageText = (message: Message) =>
    message.id === "welcome" && dataEnabled === false
      ? "Hello! I can help with writing and general questions. School data lookups are currently turned off for this chat."
      : message.text;

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      clearTimeout(copyTimer.current);
      if (speechSupported) window.speechSynthesis.cancel();
    };
  }, [speechSupported]);
  useEffect(() => {
    const el = list.current;
    if (!el) return;
    const anchor = scrollAnchor.current;
    if (anchor) {
      scrollAnchor.current = null;
      el.scrollTop = anchor.top + el.scrollHeight - anchor.height;
      return;
    }
    el.scrollTo({
      top: el.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  }, [messages, busy, error]);
  useEffect(() => {
    if (input.current) {
      input.current.style.height = "auto";
      input.current.style.height = `${Math.min(input.current.scrollHeight, 160)}px`;
    }
  }, [draft]);

  async function send(text: string, retry = false) {
    const content = text.trim();
    if (!content || lock.current || historyLock.current || (retry && !failed))
      return;
    lock.current = true;
    const version = generation.current;
    setBusy(true);
    setError("");
    const user: Message = (retry && failed) || {
      id: crypto.randomUUID(),
      role: "user",
      text: content,
      time: new Date(),
    };
    setFailed(null);
    if (!retry) {
      setMessages((current) => [
        ...current.filter((message) => message.id !== failed?.id),
        user,
      ]);
      setDraft("");
    }
    try {
      const result = await api(
        findEndpoint("POST", "/ai/chat/"),
        {},
        {
          role,
          language: getLocale() === "fr-FR" ? "fr" : "en",
          message: user.text,
          client_message_id: user.id,
          conversation_id: conversationId,
        },
      );
      if (!result?.reply?.trim())
        throw new Error(
          t("The assistant returned an empty response. Please try again."),
        );
      if (active.current && version === generation.current) {
        setConversationId(result.conversation_id);
        setHistoryVersion((value) => value + 1);
        setMessages((current) => [
          ...current,
          {
            id: result.message_id,
            role: "assistant",
            text: result.reply,
            time: new Date(result.created_at),
            sources: Array.isArray(result.sources) ? result.sources : [],
            hidden: result.hidden,
          },
        ]);
      }
    } catch (e) {
      if (active.current && version === generation.current) {
        setError((e as Error).message);
        setFailed(user);
      }
    } finally {
      lock.current = false;
      if (active.current) {
        setBusy(false);
        input.current?.focus();
      }
    }
  }

  async function openConversation(id: string, older: number | null = null) {
    if (lock.current || historyLock.current) return;
    historyLock.current = true;
    setHistoryBusy(true);
    setError("");
    const version = generation.current;
    try {
      const result: SavedConversation = await api(conversationEndpoint, {
        role,
        conversation_id: id,
        before_turn: older,
      });
      if (!active.current || version !== generation.current) return;
      const restored = result.messages.map((message): Message => ({
        id: message.id,
        role: message.sender,
        text: message.text ?? hiddenReply,
        time: new Date(message.created_at),
        sources: message.sources,
        hidden: message.text === null,
      }));
      if (older !== null) {
        if (list.current)
          scrollAnchor.current = {
            height: list.current.scrollHeight,
            top: list.current.scrollTop,
          };
        setMessages((current) => [...restored, ...current]);
      } else {
        resetConversation();
        setMessages(restored);
        setConversationId(result.id);
        if (window.matchMedia("(max-width: 700px)").matches)
          setHistoryOpen(false);
        input.current?.focus();
      }
      setBeforeTurn(result.before_turn);
    } catch (failure) {
      if (active.current && version === generation.current)
        setError((failure as Error).message);
    } finally {
      historyLock.current = false;
      if (active.current) setHistoryBusy(false);
    }
  }
  async function copy(message: Message) {
    try {
      await navigator.clipboard.writeText(
        message.id === "welcome" ? t(messageText(message)) : message.text,
      );
      setCopied(message.id);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(""), 2000);
    } catch {
      setError(
        t("Could not copy this message. Select the text and copy it manually."),
      );
    }
  }
  function speak(message: Message) {
    if (!speechSupported) return;
    window.speechSynthesis.cancel();
    if (speaking === message.id) {
      setSpeaking("");
      return;
    }
    const speech = new SpeechSynthesisUtterance(
      message.id === "welcome" ? t(messageText(message)) : message.text,
    );
    speech.lang = getLocale();
    speech.onend = () => setSpeaking("");
    speech.onerror = () => setSpeaking("");
    setSpeaking(message.id);
    window.speechSynthesis.speak(speech);
  }
  function resetConversation(clearDraft = true) {
    if (speechSupported) window.speechSynthesis.cancel();
    setSpeaking("");
    setMessages([welcome(role)]);
    setConversationId(null);
    setBeforeTurn(null);
    if (clearDraft) setDraft("");
    setError("");
    setFailed(null);
    setCopied("");
    setLiked(new Set());
  }
  function reset() {
    if (lock.current || historyLock.current) return;
    resetConversation();
    setHistoryOpen(false);
    input.current?.focus();
  }
  const latest = [...messages]
    .reverse()
    .find((m) => m.role === "assistant" && !m.hidden);
  return (
    <section className="chat-workspace" aria-label={t("AI assistant")}>
      <header className="chat-heading">
        <div className="chat-heading-title">
          <span className="chat-orb" aria-hidden="true" />
          <div>
            <h1>
              {t(" Cortex assistant ")}
              <span>AI</span>
            </h1>
            <p>{t(contentForRole.subtitle)}</p>
          </div>
        </div>
        <div className="chat-heading-actions">
          <button
            ref={historyToggle}
            type="button"
            className="chat-new"
            aria-expanded={historyOpen}
            aria-controls={historyOpen ? "chat-history" : undefined}
            onClick={() => setHistoryOpen((value) => !value)}
          >
            <History size={15} />
            {t("History")}
          </button>
          <button
            type="button"
            className="chat-new"
            onClick={reset}
            disabled={busy || historyBusy}
          >
            <Plus size={15} />
            {t(" New chat ")}
          </button>
        </div>
      </header>
      <ChatDataAccessControl
        role={role}
        disabled={busy || historyBusy}
        onChange={(access) => {
          setDataEnabled(access.effective_data_enabled);
          if (
            privacyRevision.current !== null &&
            privacyRevision.current !== access.revision
          ) {
            generation.current++;
            resetConversation(false);
          }
          privacyRevision.current = access.revision;
        }}
      />
      <div className="chat-body">
        {historyOpen && (
          <ChatHistory
            key={historyVersion}
            role={role}
            selected={conversationId}
            disabled={busy || historyBusy}
            onOpen={(id) => {
              if (window.matchMedia("(max-width: 700px)").matches)
                setHistoryOpen(false);
              void openConversation(id);
            }}
            onClose={() => {
              setHistoryOpen(false);
              historyToggle.current?.focus();
            }}
            onDeleted={(id) => {
              if (id === conversationId) resetConversation();
              setHistoryVersion((value) => value + 1);
            }}
          />
        )}
        <div className="chat-conversation">
          <div
            className="chat-thread"
            ref={list}
            role="log"
            aria-label={t("Conversation")}
            aria-live="polite"
            aria-relevant="additions text"
          >
            <div className="chat-date">
              <span>
                {messages[0] &&
                messages[0].time.toDateString() !== new Date().toDateString()
                  ? messages[0].time.toLocaleDateString(getLocale(), {
                      day: "numeric",
                      month: "long",
                      year: "numeric",
                    })
                  : t("Today")}
              </span>
            </div>
            {beforeTurn !== null && conversationId && (
              <button
                className="chat-history-more chat-older"
                type="button"
                disabled={busy || historyBusy}
                onClick={() =>
                  void openConversation(conversationId, beforeTurn)
                }
              >
                {t("Show older messages")}
              </button>
            )}
            {messages.map((m) => (
              <article
                key={m.id}
                className={`chat-message ${m.role}`}
                aria-label={`${m.role === "user" ? t("You") : t("Cortex assistant")} at ${m.time.toLocaleTimeString(getLocale(), { hour: "2-digit", minute: "2-digit" })}`}
              >
                {m.role === "assistant" && (
                  <span className="chat-orb message-orb" aria-hidden="true" />
                )}
                <div className="chat-message-content">
                  <div
                    className={`chat-bubble${m.hidden ? " chat-hidden-reply" : ""}`}
                  >
                    {m.id === "welcome" || m.hidden
                      ? t(messageText(m))
                      : m.text}
                  </div>
                  {!!m.sources?.length && (
                    <section
                      className="chat-sources"
                      aria-label={t("Answer sources")}
                    >
                      <p>
                        <Database size={13} />
                        {t("Based on your accessible school data")}
                      </p>
                      {m.sources.map((source) => (
                        <div className="chat-source" key={source.id}>
                          {source.href?.startsWith("/") &&
                          !source.href.startsWith("//") ? (
                            <Link to={source.href}>
                              <BookOpen size={13} />
                              <span>
                                [{source.id}] {t(source.label)}
                              </span>
                              <ArrowUpRight size={13} />
                            </Link>
                          ) : (
                            <strong>
                              [{source.id}] {t(source.label)}
                            </strong>
                          )}
                          {source.excerpt && (
                            <details>
                              <summary>{t("View cited passage")}</summary>
                              <p>{source.excerpt}</p>
                            </details>
                          )}
                        </div>
                      ))}
                    </section>
                  )}
                  <div className="chat-message-meta">
                    <time dateTime={m.time.toISOString()}>
                      {m.time.toLocaleTimeString(getLocale(), {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </time>
                    {m.role === "assistant" && !m.hidden && (
                      <div className="chat-message-tools">
                        <button
                          type="button"
                          title={
                            copied === m.id ? t("Copied") : t("Copy message")
                          }
                          aria-label={
                            copied === m.id ? t("Copied") : t("Copy message")
                          }
                          onClick={() => copy(m)}
                        >
                          {copied === m.id ? (
                            <Check size={14} />
                          ) : (
                            <Copy size={14} />
                          )}
                        </button>
                        <button
                          type="button"
                          title={t("Helpful")}
                          aria-label={t("Mark response helpful")}
                          aria-pressed={liked.has(m.id)}
                          onClick={() =>
                            setLiked((previous) => {
                              const next = new Set(previous);
                              next.has(m.id)
                                ? next.delete(m.id)
                                : next.add(m.id);
                              return next;
                            })
                          }
                        >
                          <ThumbsUp size={14} />
                        </button>
                        {speechSupported && (
                          <button
                            type="button"
                            title={
                              speaking === m.id
                                ? t("Stop reading")
                                : t("Read aloud")
                            }
                            aria-label={
                              speaking === m.id
                                ? t("Stop reading")
                                : t("Read message aloud")
                            }
                            onClick={() => speak(m)}
                          >
                            {speaking === m.id ? (
                              <VolumeX size={14} />
                            ) : (
                              <Volume2 size={14} />
                            )}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </article>
            ))}
            {messages.length === 1 && !busy && !historyBusy && (
              <div className="chat-suggestions">
                {(dataEnabled ? suggestions : suggestions.slice(0, 1)).map(
                  (s) => (
                    <button key={s} onClick={() => send(t(s))}>
                      {t(s)}
                      <ArrowUpRight size={13} />
                    </button>
                  ),
                )}
              </div>
            )}
            {historyBusy && (
              <p className="chat-thinking" role="status">
                <LoaderCircle className="spin" size={15} />{" "}
                {t("Loading conversation…")}
              </p>
            )}
            {busy && (
              <div className="chat-thinking" role="status">
                <span className="chat-orb message-orb" />
                <LoaderCircle className="spin" size={15} />
                <span>
                  {t(" Thinking it through")}
                  <span className="thinking-dots">…</span>
                </span>
              </div>
            )}
            {error && (
              <div className="chat-error" role="alert">
                <p>{t(error)}</p>
                {failed && (
                  <button
                    disabled={busy || historyBusy}
                    onClick={() => send(failed.text, true)}
                  >
                    {t(" Try again ")}
                    <ArrowUpRight size={13} />
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="chat-compose-area">
            <form
              className="chat-composer"
              onSubmit={(e) => {
                e.preventDefault();
                void send(draft);
              }}
            >
              <label className="sr-only" htmlFor="chat-message">
                {t(" Your message ")}
              </label>
              <textarea
                id="chat-message"
                ref={input}
                placeholder={t("Ask anything…")}
                rows={2}
                value={draft}
                maxLength={12000}
                readOnly={historyBusy}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    void send(draft);
                  }
                }}
              />
              <div className="chat-composer-toolbar">
                <span className="chat-composer-note">
                  <Sparkles size={13} />
                  {t(" A little help, a fresh perspective. ")}
                </span>
                <div>
                  {speechSupported && latest && (
                    <button
                      type="button"
                      className="chat-voice"
                      onClick={() => speak(latest)}
                    >
                      {speaking ? <VolumeX size={13} /> : <Volume2 size={13} />}{" "}
                      {speaking ? t("Stop") : t("Read aloud")}
                    </button>
                  )}
                  <button
                    type="submit"
                    className="chat-send"
                    disabled={busy || historyBusy || !draft.trim()}
                  >
                    {busy ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : (
                      <Send size={14} />
                    )}{" "}
                    {t(" Send ")}
                  </button>
                </div>
              </div>
            </form>
            <p className="chat-disclaimer">
              {t(" AI can make mistakes. Review important details.")}{" "}
              <span>{t("Enter to send · Shift + Enter for a new line")}</span>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
