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
} from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { getChatContent } from "./chat-content.mjs";
import type { Role } from "./types";
import "./chat.css";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  time: Date;
};
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
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [failed, setFailed] = useState("");
  const [copied, setCopied] = useState("");
  const [liked, setLiked] = useState<Set<string>>(new Set());
  const [speaking, setSpeaking] = useState("");
  const lock = useRef(false);
  const list = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const active = useRef(true);
  const speechSupported =
    typeof window !== "undefined" && "speechSynthesis" in window;

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
    if (el)
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
    if (!content || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setFailed("");
    const user: Message = {
      id: crypto.randomUUID(),
      role: "user",
      text: content,
      time: new Date(),
    };
    const conversation = retry ? messages : [...messages, user];
    if (!retry) {
      setMessages(conversation);
      setDraft("");
    }
    // The backend accepts a single message. Include recent turns so follow-ups
    // retain context without requiring a different API contract.
    const history = conversation.filter((m) => m.id !== "welcome").slice(-12);
    const conversationText =
      history.length === 1
        ? content
        : `Continue this conversation. Respond to the latest user message.\n\n${history.map((m) => `${m.role === "user" ? "User" : "Assistant"}: ${m.text}`).join("\n\n")}`;
    const message = `${contentForRole.context}\nDo not claim to have read school records or performed actions; this chat has no school-data tools.\n\n${conversationText}`;
    try {
      const result = await api(
        findEndpoint("POST", "/ai/chat/"),
        {},
        {
          message:
            getLocale() === "fr-FR"
              ? `${message}\n\nRéponds en français, sauf si une autre langue est explicitement demandée.`
              : message,
        },
      );
      if (!result?.reply?.trim())
        throw new Error(
          t("The assistant returned an empty response. Please try again."),
        );
      if (active.current)
        setMessages((current) => [
          ...current,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            text: result.reply,
            time: new Date(),
          },
        ]);
    } catch (e) {
      if (active.current) {
        setError((e as Error).message);
        setFailed(content);
      }
    } finally {
      lock.current = false;
      if (active.current) {
        setBusy(false);
        input.current?.focus();
      }
    }
  }
  async function copy(message: Message) {
    try {
      await navigator.clipboard.writeText(message.text);
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
      message.id === "welcome" ? t(message.text) : message.text,
    );
    speech.lang = getLocale();
    speech.onend = () => setSpeaking("");
    speech.onerror = () => setSpeaking("");
    setSpeaking(message.id);
    window.speechSynthesis.speak(speech);
  }
  function reset() {
    if (lock.current) return;
    if (speechSupported) window.speechSynthesis.cancel();
    setSpeaking("");
    setMessages([welcome(role)]);
    setDraft("");
    setError("");
    setFailed("");
    setLiked(new Set());
    input.current?.focus();
  }
  const latest = [...messages].reverse().find((m) => m.role === "assistant");
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
        <button
          type="button"
          className="chat-new"
          onClick={reset}
          disabled={busy}
        >
          <Plus size={15} />
          {t(" New chat ")}
        </button>
      </header>
      <div
        className="chat-thread"
        ref={list}
        role="log"
        aria-label={t("Conversation")}
        aria-live="polite"
        aria-relevant="additions text"
      >
        <div className="chat-date">
          <span>{t("Today")}</span>
        </div>
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
              <div className="chat-bubble">
                {m.id === "welcome" ? t(m.text) : m.text}
              </div>
              <div className="chat-message-meta">
                <time dateTime={m.time.toISOString()}>
                  {m.time.toLocaleTimeString(getLocale(), {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
                {m.role === "assistant" && (
                  <div className="chat-message-tools">
                    <button
                      type="button"
                      title={copied === m.id ? t("Copied") : t("Copy message")}
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
                          next.has(m.id) ? next.delete(m.id) : next.add(m.id);
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
        {messages.length === 1 && !busy && (
          <div className="chat-suggestions">
            {suggestions.map((s) => (
              <button key={s} onClick={() => send(t(s))}>
                {t(s)}
                <ArrowUpRight size={13} />
              </button>
            ))}
          </div>
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
            <p>{error}</p>
            {failed && (
              <button disabled={busy} onClick={() => send(failed, true)}>
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
                disabled={busy || !draft.trim()}
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
    </section>
  );
}
