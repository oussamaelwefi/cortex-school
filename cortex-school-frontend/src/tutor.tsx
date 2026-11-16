import { useEffect, useRef, useState, type FormEvent } from "react";
import { BookOpen, ClipboardList, ExternalLink, LibraryBig, LoaderCircle, Search, Sparkles } from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { t } from "./i18n";
import { Heading } from "./pages";
import { pageLabel, SourceExcerpt, StudyResult, type Action, type Activity, type PageSource } from "./tutor-results";
import { Empty, ErrorBox, Loading, Modal, useRemote } from "./ui";
import "./tutor.css";

type Book = { id: string; title: string; page_count: number; indexed_page_count: number };

const booksEndpoint = findEndpoint("GET", "/guardian/tutor/books/");
const pdfEndpoint = findEndpoint("GET", "/guardian/tutor/books/{book_id}/pdf/");
const studyEndpoint = { ...findEndpoint("POST", "/guardian/tutor/books/{book_id}/study/"), timeoutMs: 45000 };
const actions = [
  { id: "search", label: "Find passages", icon: Search },
  { id: "explain", label: "Explain from the book", icon: Sparkles },
  { id: "summary", label: "Summarize", icon: ClipboardList },
  { id: "quiz", label: "Start a quiz", icon: ClipboardList },
  { id: "practice", label: "Generate a practice test", icon: BookOpen },
] as const;

function BookViewer({ book, source, onClose }: { book: Book; source: PageSource; onClose: () => void }) {
  const state = useRemote(pdfEndpoint, { book_id: book.id });
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!(state.data instanceof Blob)) return;
    const blobUrl = URL.createObjectURL(state.data);
    setUrl(blobUrl);
    return () => URL.revokeObjectURL(blobUrl);
  }, [state.data]);
  const location = `${url}#page=${source.page}`;
  return (
    <Modal title={book.title} subtitle={pageLabel(source.page)} wide onClose={onClose}>
      <div className="modal-body tutor-book-viewer">
        {state.error ? <ErrorBox error={state.error} /> : !url ? <Loading /> : (
          <>
            <a className="button small subtle" href={location} target="_blank" rel="noopener">
              {t("Open PDF in a new tab")} <ExternalLink size={14} />
            </a>
            <iframe title={`${book.title} · ${pageLabel(source.page)}`} src={location} />
            {source.passages.length > 0 && (
              <details className="tutor-viewer-excerpts">
                <summary>{t("Read the extracted passage")}</summary>
                {source.passages.map((passage) => <SourceExcerpt source={passage} key={passage.id} />)}
              </details>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

function StudyWorkspace({ book }: { book: Book }) {
  const api = useApi();
  const [topic, setTopic] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [pending, setPending] = useState<Action | null>(null);
  const [result, setResult] = useState<Activity | null>(null);
  const [error, setError] = useState("");
  const [source, setSource] = useState<PageSource | null>(null);
  const resultAnchor = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (result) {
      resultAnchor.current?.focus({ preventScroll: true });
      resultAnchor.current?.scrollIntoView({ block: "start" });
    }
  }, [result]);

  async function study(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const action = actions.find((option) => option.id === submitter?.value)?.id ?? "search";
    if (!topic.trim() && !start) {
      setError(t("Enter a topic or a starting page."));
      return;
    }
    if (end && (!start || Number(end) < Number(start) || Number(end) - Number(start) > 5)) {
      setError(t("Choose a range of up to six pages."));
      return;
    }
    setError("");
    setResult(null);
    setPending(action);
    try {
      setResult(await api(studyEndpoint, { book_id: book.id }, {
        action,
        topic: topic.trim(),
        start_page: start ? Number(start) : null,
        end_page: end ? Number(end) : null,
      }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(null);
    }
  }

  return (
    <>
      <form className="panel tutor-form" onSubmit={study}>
        <div className="tutor-book">
          <span className="tutor-book-icon"><LibraryBig size={21} /></span>
          <div>
            <h2 dir="auto">{book.title}</h2>
            <p>{t("{indexed} of {total} pages indexed").replace("{indexed}", String(book.indexed_page_count)).replace("{total}", String(book.page_count))}</p>
          </div>
          <button type="button" className="button small subtle" onClick={() => setSource({ page: 1, passages: [] })}>
            <BookOpen size={15} /> {t("Open source book")}
          </button>
        </div>
        <label className="field">
          <span>{t("Topic or question")}</span>
          <textarea dir="auto" rows={2} maxLength={500} value={topic} disabled={pending !== null}
            onChange={(event) => setTopic(event.target.value)} placeholder={t("For example, fractions or the area of a triangle")} />
          <small>{t("Use the book’s language when searching by topic.")}</small>
        </label>
        <div className="tutor-page-range">
          <label className="field"><span>{t("Start page")}</span>
            <input type="number" min={1} max={book.page_count} value={start} disabled={pending !== null}
              onChange={(event) => setStart(event.target.value)} />
          </label>
          <label className="field"><span>{t("End page")}</span>
            <input type="number" min={1} max={book.page_count} value={end} disabled={pending !== null}
              onChange={(event) => setEnd(event.target.value)} />
          </label>
          <p>{t("Enter a topic, a single page, or a range of up to six pages.")}</p>
        </div>
        <div className="tutor-actions">
          {actions.map(({ id, label, icon: Icon }) => (
            <button key={id} type="submit" value={id} className={`button small ${id === "search" ? "primary" : "subtle"}`}
              disabled={pending !== null}>
              {pending === id ? <LoaderCircle className="spin" size={15} /> : <Icon size={15} />}
              {t(label)}
            </button>
          ))}
        </div>
        {error && <ErrorBox error={error} />}
        {pending && <p className="tutor-progress" role="status">{t("Searching the selected book…")}</p>}
      </form>
      {result && (
        <div ref={resultAnchor} className="tutor-result-anchor" tabIndex={-1}>
          <StudyResult activity={result} onOpenPage={setSource} />
        </div>
      )}
      {source && <BookViewer book={book} source={source} onClose={() => setSource(null)} />}
    </>
  );
}

export function GuardianTutorPage() {
  const [selected, setSelected] = useState("");
  const [revision, setRevision] = useState(0);
  const state = useRemote(booksEndpoint, {}, revision);
  const books: Book[] = state.data ?? [];
  const book = books.find((candidate) => candidate.id === selected) ?? books[0];
  return (
    <div className="guardian-tutor">
      <Heading eyebrow="FAMILY WORKSPACE" title="Study tutor" description="Work through the school book with explanations, quizzes, and practice tests.">
        {books.length > 1 && (
          <select aria-label={t("Study book")} value={book?.id} onChange={(event) => setSelected(event.target.value)}>
            {books.map((candidate) => <option dir="auto" key={candidate.id} value={candidate.id}>{candidate.title}</option>)}
          </select>
        )}
      </Heading>
      {state.loading ? <Loading /> : state.error ? <ErrorBox error={state.error} retry={() => setRevision(revision + 1)} />
        : book ? <StudyWorkspace key={book.id} book={book} />
          : <Empty title="No study books yet" text="Study books shared by your school will appear here." />}
    </div>
  );
}
