import { useContext, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Check,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  GraduationCap,
  LoaderCircle,
  Megaphone,
  Plus,
  RefreshCw,
  Search,
  Send,
  UserRound,
  Users,
} from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { getLocale, t, useLanguage } from "./i18n";
import { Empty, ErrorBox, Loading, Modal, ToastContext } from "./ui";
import type { Role } from "./types";

type Kind = "classrooms" | "guardians" | "teachers" | "students";
type Option = { id: string; name: string };
type Recipient = {
  id: string;
  name: string;
  roles: string[];
  read_at?: string | null;
};
type Preview = {
  audience_hash: string;
  recipient_count: number;
  guardian_count: number;
  teacher_count: number;
  recipients: Recipient[];
  students_without_guardians: string[];
};
type Publication = {
  id: string;
  title: string;
  body: string;
  created_at: string;
  target_kind?: Kind;
  recipient_count?: number;
  read_count?: number;
  read_at?: string | null;
  recipients?: Recipient[];
};
type PublicationList = {
  items: Publication[];
  total_count: number;
  unread_count?: number;
};
const kinds = {
  classrooms: {
    label: "Classes",
    icon: BookOpen,
    help: "The selected classes’ family members and currently assigned teachers receive the publication.",
  },
  guardians: {
    label: "Family members",
    icon: Users,
    help: "Only the selected family accounts receive the publication.",
  },
  teachers: {
    label: "Teachers",
    icon: GraduationCap,
    help: "Only the selected teachers receive the publication.",
  },
  students: {
    label: "Students’ families",
    icon: UserRound,
    help: "The selected students’ linked family members receive the publication. Students do not receive it directly.",
  },
};

function date(value: string) {
  return new Date(value).toLocaleString(getLocale(), {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function usePublicationList(
  role: Role,
  search: string,
  unread: boolean,
  offset: number,
  revision: number,
) {
  const api = useApi();
  const [state, setState] = useState<{
    data: PublicationList | null;
    loading: boolean;
    error: string;
  }>({ data: null, loading: true, error: "" });
  useEffect(() => {
    let active = true,
      pending = false;
    async function load() {
      if (pending) return;
      pending = true;
      setState((value) => ({ ...value, loading: true, error: "" }));
      try {
        const data = await api(
          findEndpoint(
            "GET",
            role === "admin" ? "/publications/" : "/publications/inbox/",
          ),
          {
            search,
            limit: 20,
            offset,
            ...(role === "admin" ? {} : { role, unread_only: unread }),
          },
        );
        if (active) setState({ data, loading: false, error: "" });
      } catch (error) {
        if (active)
          setState((value) => ({
            ...value,
            loading: false,
            error: (error as Error).message,
          }));
      } finally {
        pending = false;
      }
    }
    const refresh = () => {
      if (document.visibilityState !== "hidden") void load();
    };
    void load();
    const timer = window.setInterval(refresh, 30000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [api, role, search, unread, offset, revision]);
  return state;
}

function PublicationComposer({
  onClose,
  onPublished,
}: {
  onClose: () => void;
  onPublished: () => void;
}) {
  const api = useApi();
  const toast = useContext(ToastContext);
  const [options, setOptions] = useState<Record<Kind, Option[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [reload, setReload] = useState(0);
  const [kind, setKind] = useState<Kind>("classrooms");
  const [ids, setIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const requestKey = useRef(crypto.randomUUID());
  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError("");
    api(findEndpoint("GET", "/publications/audiences/"))
      .then((value) => {
        if (active) {
          setOptions(value);
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (active) {
          setLoadError(failure.message);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [api, reload]);
  const choices = options?.[kind] || [];
  const visible = choices.filter((option) =>
    option.name
      .toLocaleLowerCase(getLocale())
      .includes(query.trim().toLocaleLowerCase(getLocale())),
  );
  const selected = new Set(ids);
  const allVisible =
    visible.length > 0 && visible.every((option) => selected.has(option.id));
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending.current || loading || loadError) return;
    setError("");
    if (!ids.length) {
      setError("Choose at least one publication target.");
      return;
    }
    if (!title.trim() || !message.trim()) {
      setError("Enter a title and a message before continuing.");
      return;
    }
    if (
      ids.length > 500 ||
      title.trim().length > 255 ||
      message.trim().length > 5000
    ) {
      setError("Check the publication length and select at most 500 targets.");
      return;
    }
    pending.current = true;
    setBusy(true);
    try {
      const target = { kind, ids };
      if (!preview) {
        setPreview(
          await api(
            findEndpoint("POST", "/publications/preview/"),
            {},
            { target },
          ),
        );
      } else {
        await api(
          findEndpoint("POST", "/publications/"),
          {},
          {
            title: title.trim(),
            body: message.trim(),
            target,
            audience_hash: preview.audience_hash,
            idempotency_key: requestKey.current,
            confirmed: true,
          },
        );
        toast(t("Publication published"));
        onPublished();
        onClose();
      }
    } catch (failure) {
      const text = (failure as Error).message;
      if (text.startsWith("The recipients have changed.")) setPreview(null);
      setError(text);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <Modal
      title={preview ? "Confirm publication" : "New school publication"}
      onClose={() => {
        if (!pending.current) onClose();
      }}
      wide
    >
      <form className="pub-composer" onSubmit={submit}>
        <div className="modal-body pub-editor">
          {preview ? (
            <>
              <div className="pub-notice">
                <Send size={19} />
                <p>
                  {t(
                    "Do you want to publish this message to these school accounts?",
                  )}
                </p>
              </div>
              <div className="pub-preview-counts">
                <div>
                  <strong>{preview.recipient_count}</strong>
                  <span>{t("Recipient accounts")}</span>
                </div>
                <div>
                  <strong>{preview.guardian_count}</strong>
                  <span>{t("Family members")}</span>
                </div>
                <div>
                  <strong>{preview.teacher_count}</strong>
                  <span>{t("Teachers")}</span>
                </div>
              </div>
              <details className="pub-recipients">
                <summary>{t("View publication recipients")}</summary>
                <ul>
                  {preview.recipients.map((recipient) => (
                    <li key={recipient.id}>
                      <span>{recipient.name}</span>
                      <small>
                        {recipient.roles
                          .map((role) =>
                            t(
                              role === "guardian" ? "Family member" : "Teacher",
                            ),
                          )
                          .join(" · ")}
                      </small>
                    </li>
                  ))}
                </ul>
              </details>
              {preview.students_without_guardians.length > 0 && (
                <div className="pub-warning" role="status">
                  <strong>
                    {t(
                      "These students have no active family account and will not receive the publication:",
                    )}
                  </strong>
                  <ul>
                    {preview.students_without_guardians.map((name, index) => (
                      <li key={index}>{name}</li>
                    ))}
                  </ul>
                </div>
              )}
              <article className="pub-message">
                <h3>{title}</h3>
                <p dir="auto">{message}</p>
              </article>
            </>
          ) : (
            <>
              <div className="pub-notice">
                <Megaphone size={20} />
                <p>
                  {t(
                    "Choose who receives your message. You will review the recipients before publishing.",
                  )}
                </p>
              </div>
              <fieldset className="pub-kind-fieldset">
                <legend>{t("Send a publication to")}</legend>
                <div className="pub-kinds">
                  {(
                    Object.entries(kinds) as [Kind, (typeof kinds)[Kind]][]
                  ).map(([value, config]) => (
                    <label
                      key={value}
                      className={kind === value ? "selected" : ""}
                    >
                      <input
                        type="radio"
                        name="publication-kind"
                        value={value}
                        checked={kind === value}
                        disabled={busy}
                        onChange={() => {
                          setKind(value);
                          setIds([]);
                          setQuery("");
                        }}
                      />
                      <config.icon size={20} />
                      <span>{t(config.label)}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <p className="pub-target-help">{t(kinds[kind].help)}</p>
              {loading ? (
                <Loading />
              ) : loadError ? (
                <ErrorBox
                  error={t(loadError)}
                  retry={() => setReload((value) => value + 1)}
                />
              ) : (
                <section
                  className="pub-targets"
                  aria-label={t("Choose publication recipients")}
                >
                  <div className="pub-target-toolbar">
                    <label className="pub-search">
                      <Search size={16} />
                      <input
                        type="search"
                        aria-label={t("Search publication targets")}
                        placeholder={t("Search by name…")}
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        disabled={busy}
                      />
                    </label>
                    <span>
                      {ids.length} {t("selected")}
                    </span>
                  </div>
                  <div className="pub-selection-tools">
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy || !visible.length}
                      onClick={() =>
                        setIds(
                          allVisible
                            ? ids.filter(
                                (id) =>
                                  !visible.some((option) => option.id === id),
                              )
                            : [
                                ...new Set([
                                  ...ids,
                                  ...visible.map((option) => option.id),
                                ]),
                              ].slice(0, 500),
                        )
                      }
                    >
                      {t(
                        allVisible
                          ? "Unselect visible targets"
                          : "Select visible targets",
                      )}
                    </button>
                    {ids.length > 0 && (
                      <button
                        type="button"
                        className="text-button"
                        disabled={busy}
                        onClick={() => setIds([])}
                      >
                        {t("Clear selection")}
                      </button>
                    )}
                  </div>
                  <div className="pub-options">
                    {visible.length ? (
                      visible.map((option) => (
                        <label key={option.id}>
                          <input
                            type="checkbox"
                            checked={selected.has(option.id)}
                            disabled={
                              busy ||
                              (!selected.has(option.id) && ids.length >= 500)
                            }
                            onChange={(event) =>
                              setIds(
                                event.target.checked
                                  ? [...ids, option.id]
                                  : ids.filter((id) => id !== option.id),
                              )
                            }
                          />
                          <span>{option.name}</span>
                        </label>
                      ))
                    ) : (
                      <p>
                        {t(
                          choices.length
                            ? "No recipients match your search."
                            : "No eligible recipients in this category.",
                        )}
                      </p>
                    )}
                  </div>
                </section>
              )}
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
                  dir="auto"
                  rows={7}
                  maxLength={5000}
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  disabled={busy}
                />
                <small>{message.length} / 5 000</small>
              </label>
            </>
          )}
          {error && <ErrorBox error={t(error)} />}
        </div>
        <footer className="pub-composer-actions">
          <button
            type="button"
            className="button subtle"
            disabled={busy}
            onClick={() => {
              if (preview) {
                setPreview(null);
                setError("");
              } else onClose();
            }}
          >
            {t(preview ? "Back to message" : "Cancel")}
          </button>
          <button
            className="button primary"
            disabled={busy || loading || !!loadError || !ids.length}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : preview ? (
              <Send size={16} />
            ) : (
              <Users size={16} />
            )}
            {t(
              busy
                ? preview
                  ? "Publishing…"
                  : "Checking recipients…"
                : preview
                  ? "Confirm publication"
                  : "Review recipients",
            )}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

export function PublicationsPage({ role }: { role: Role }) {
  useLanguage();
  const api = useApi();
  const admin = role === "admin";
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [unread, setUnread] = useState(false);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [composing, setComposing] = useState(false);
  const [selected, setSelected] = useState<Publication | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const selectionVersion = useRef(0);
  const state = usePublicationList(role, search, unread, offset, revision);
  const data = state.data;
  useEffect(() => {
    if (data && !state.loading && offset > 0 && offset >= data.total_count)
      setOffset(Math.max(0, Math.floor((data.total_count - 1) / 20) * 20));
  }, [data?.total_count, state.loading, offset]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);
  const refresh = () => setRevision((value) => value + 1);
  async function open(publication: Publication) {
    const version = ++selectionVersion.current;
    setSelected(publication);
    setDetailLoading(true);
    setDetailError("");
    try {
      const result = await api(
        findEndpoint(
          admin ? "GET" : "POST",
          admin
            ? "/publications/{publication_id}/"
            : "/publications/inbox/{publication_id}/read/",
        ),
        { publication_id: publication.id, ...(admin ? {} : { role }) },
      );
      if (version === selectionVersion.current) {
        setSelected(result);
        if (!admin) refresh();
      }
    } catch (failure) {
      if (version === selectionVersion.current)
        setDetailError((failure as Error).message);
    } finally {
      if (version === selectionVersion.current) setDetailLoading(false);
    }
  }
  function closeDetail() {
    selectionVersion.current++;
    setSelected(null);
  }
  return (
    <div className="publications-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {t(admin ? "SCHOOL COMMUNICATION" : "FROM YOUR SCHOOL")}
          </p>
          <h1>{t("School publications")}</h1>
          <p>
            {t(
              admin
                ? "Send clear announcements to the right people and follow readership."
                : "Read the announcements sent to you by your school administration.",
            )}
          </p>
        </div>
        <div className="heading-actions">
          <button
            className="button subtle"
            onClick={refresh}
            disabled={state.loading}
            aria-label={t("Refresh publications")}
          >
            <RefreshCw size={16} />
          </button>
          {admin && (
            <button
              className="button primary"
              onClick={() => setComposing(true)}
            >
              <Plus size={17} />
              {t("New publication")}
            </button>
          )}
        </div>
      </div>
      <div className="pub-overview">
        <span className="pub-overview-icon">
          <Megaphone size={26} />
        </span>
        <div>
          <strong>
            {t(admin ? "Your school, informed." : "Your school’s latest news.")}
          </strong>
          <p>
            {t(
              admin
                ? "Classes reach their families and teachers. Students reach their linked family members."
                : "Only publications addressed to your account appear in this space.",
            )}
          </p>
        </div>
        <span className="pub-total">
          <strong>{data?.total_count ?? "—"}</strong>
          {t("Publications")}
        </span>
        {!admin && (
          <span className="pub-total">
            <strong>{data?.unread_count ?? "—"}</strong>
            {t("Unread")}
          </span>
        )}
      </div>
      <div className="pub-toolbar">
        <label className="pub-search">
          <Search size={17} />
          <input
            type="search"
            aria-label={t("Search publications")}
            placeholder={t("Search publications…")}
            maxLength={120}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </label>
        {!admin && (
          <label className="pub-unread">
            <input
              type="checkbox"
              checked={unread}
              onChange={(event) => {
                setUnread(event.target.checked);
                setOffset(0);
              }}
            />
            {t("Unread only")}
          </label>
        )}
        <span className="pub-live">{t("Updates automatically")}</span>
      </div>
      {state.error && <ErrorBox error={t(state.error)} retry={refresh} />}
      {!data && state.loading ? (
        <Loading />
      ) : data?.items.length ? (
        <div className="pub-list" aria-busy={state.loading}>
          {data.items.map((publication) => (
            <article
              className={`pub-card ${!admin && !publication.read_at ? "unread" : ""}`}
              key={publication.id}
            >
              <div className="pub-card-meta">
                <span>
                  <Megaphone size={14} />
                  {t("School administration")}
                </span>
                <time dateTime={publication.created_at}>
                  {date(publication.created_at)}
                </time>
              </div>
              <button
                className="pub-open"
                onClick={() => void open(publication)}
              >
                <h2>{publication.title}</h2>
                <span className="sr-only">{t("Read publication")}</span>
              </button>
              <p className="pub-excerpt">{publication.body}</p>
              <div className="pub-card-footer">
                {admin ? (
                  <>
                    <span>
                      {t(
                        kinds[publication.target_kind!]?.label ||
                          "Publications",
                      )}
                    </span>
                    <span>
                      <Users size={14} />
                      {publication.recipient_count} {t("recipients")}
                    </span>
                    <span>
                      <CheckCheck size={14} />
                      {publication.read_count} {t("read")}
                    </span>
                  </>
                ) : (
                  <span
                    className={`pub-read-state ${publication.read_at ? "read" : ""}`}
                  >
                    {publication.read_at ? (
                      <CheckCheck size={14} />
                    ) : (
                      <span className="pub-unread-dot" />
                    )}
                    {t(publication.read_at ? "Read" : "Unread")}
                  </span>
                )}
                <button
                  className="text-button"
                  onClick={() => void open(publication)}
                >
                  {t(admin ? "View readership" : "Read publication")}
                  <ChevronRight size={14} />
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        !state.error && (
          <Empty
            title={t(
              search || unread
                ? "No publications match these filters"
                : "No school publications yet",
            )}
            text={
              admin
                ? "Publish your first school announcement to keep your community informed."
                : "Announcements addressed to you will appear here."
            }
          />
        )
      )}
      {!!data?.total_count && (
        <nav className="pub-pagination" aria-label={t("Publication pages")}>
          <span>
            {Math.min(offset + 1, data.total_count)}–
            {Math.min(offset + 20, data.total_count)} / {data.total_count}
          </span>
          <button
            className="button subtle"
            disabled={offset === 0 || state.loading}
            onClick={() => setOffset(Math.max(0, offset - 20))}
            aria-label={t("Previous page")}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            className="button subtle"
            disabled={offset + 20 >= data.total_count || state.loading}
            onClick={() => setOffset(offset + 20)}
            aria-label={t("Next page")}
          >
            <ChevronRight size={16} />
          </button>
        </nav>
      )}
      {composing && (
        <PublicationComposer
          onClose={() => setComposing(false)}
          onPublished={() => {
            setSearchInput("");
            setSearch("");
            setOffset(0);
            refresh();
          }}
        />
      )}
      {selected && (
        <Modal
          title={selected.title}
          subtitle={`${t("School administration")} · ${date(selected.created_at)}`}
          onClose={closeDetail}
          wide
        >
          <div className="modal-body pub-detail">
            <p className="pub-full-message" dir="auto">
              {selected.body}
            </p>
            {detailLoading && <Loading />}
            {detailError && (
              <ErrorBox
                error={t(detailError)}
                retry={() => void open(selected)}
              />
            )}
            {admin && selected.recipients && (
              <section className="pub-receipts">
                <h3>
                  {t("Publication readership")}{" "}
                  <span>
                    {selected.read_count} / {selected.recipient_count}
                  </span>
                </h3>
                <ul>
                  {selected.recipients.map((recipient) => (
                    <li key={recipient.id}>
                      <div>
                        <strong>{recipient.name}</strong>
                        <small>
                          {recipient.roles
                            .map((value) =>
                              t(
                                value === "guardian"
                                  ? "Family member"
                                  : "Teacher",
                              ),
                            )
                            .join(" · ")}
                        </small>
                      </div>
                      <span className="pub-read-state">
                        {recipient.read_at ? (
                          <CheckCheck size={15} />
                        ) : (
                          <Check size={15} />
                        )}
                        {recipient.read_at
                          ? date(recipient.read_at)
                          : t("Unread")}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
          <footer>
            <button className="button primary" onClick={closeDetail}>
              {t("Close")}
            </button>
          </footer>
        </Modal>
      )}
    </div>
  );
}
