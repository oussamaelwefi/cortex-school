import { useEffect, useRef, useState, type FormEvent } from "react";
import { BookOpen, ClipboardList, ExternalLink, LibraryBig, LoaderCircle, Search, Sparkles } from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { t } from "./i18n";
import { Heading } from "./pages";
import { pageLabel, SourceExcerpt, StudyResult, type Action, type Activity, type PageSource } from "./tutor-results";
import { Empty, ErrorBox, Loading, Modal, useRemote } from "./ui";
import "./tutor.css";
import "katex/dist/katex.min.css";

type Book = { id: string; title: string; page_count: number; indexed_page_count: number; subject?: string };
type TutorChild = { id: string; first_name: string; last_name: string; classroom_name: string | null };
type Language = "ar" | "fr" | "en";
type StudyInput = { action: Action; topic: string; start_page: number | null; end_page: number | null; language: Language | null };

const booksEndpoint = findEndpoint("GET", "/guardian/tutor/books/");
const pdfEndpoint = findEndpoint("GET", "/guardian/tutor/books/{book_id}/pdf/");
const studyEndpoint = { ...findEndpoint("POST", "/guardian/tutor/books/{book_id}/study/"), timeoutMs: 45000 };
const childrenEndpoint = findEndpoint("GET", "/guardian/tutor/children/");
const classMaterialsPath = "/guardian/tutor/children/{student_id}/materials/";
const materialsEndpoint = findEndpoint("GET", classMaterialsPath);
const materialPdfEndpoint = findEndpoint("GET", `${classMaterialsPath}{material_id}/pdf/`);
const materialStudyEndpoint = { ...findEndpoint("POST", `${classMaterialsPath}{material_id}/study/`), timeoutMs: 45000 };
const actions = [
  { id: "search", label: "Find passages", icon: Search },
  { id: "explain", label: "Explain from the book", icon: Sparkles },
  { id: "summary", label: "Summarize", icon: ClipboardList },
  { id: "quiz", label: "Start a quiz", icon: ClipboardList },
  { id: "practice", label: "Generate a practice test", icon: BookOpen },
] as const;

function bookParams(book: Book, studentId?: string) {
  return studentId ? { student_id: studentId, material_id: book.id } : { book_id: book.id };
}

function BookViewer({ book, studentId, source, onClose }: { book: Book; studentId?: string; source: PageSource; onClose: () => void }) {
  const state = useRemote(studentId ? materialPdfEndpoint : pdfEndpoint, bookParams(book, studentId));
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

function StudyWorkspace({ book, studentId }: { book: Book; studentId?: string }) {
  const api = useApi();
  const [topic, setTopic] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [language, setLanguage] = useState<Language | "">("");
  const [pending, setPending] = useState<Action | null>(null);
  const [result, setResult] = useState<Activity | null>(null);
  const [error, setError] = useState("");
  const [source, setSource] = useState<PageSource | null>(null);
  const [lastRequest, setLastRequest] = useState<StudyInput | null>(null);
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
    if (!topic.trim() && !start && (!studentId || action === "search")) {
      setError(t("Enter a topic or a starting page."));
      return;
    }
    if (end && (!start || Number(end) < Number(start) || Number(end) - Number(start) > 5)) {
      setError(t("Choose a range of up to six pages."));
      return;
    }
    const useOpeningPages = !topic.trim() && !start;
    await runStudy({
      action, topic: topic.trim(), language: language || null,
      start_page: start ? Number(start) : useOpeningPages ? 1 : null,
      end_page: end ? Number(end) : useOpeningPages ? Math.min(6, book.page_count) : null,
    });
  }

  async function runStudy(request: StudyInput) {
    if (pending) return;
    setError("");
    setResult(null);
    setPending(request.action);
    setLastRequest(request);
    try {
      setResult(await api(studentId ? materialStudyEndpoint : studyEndpoint, bookParams(book, studentId), request));
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
            {book.subject && <p dir="auto">{book.subject}</p>}
            <p>{t("{indexed} of {total} pages indexed").replace("{indexed}", String(book.indexed_page_count)).replace("{total}", String(book.page_count))}</p>
          </div>
          <button type="button" className="button small subtle" onClick={() => setSource({ page: 1, passages: [] })}>
            <BookOpen size={15} /> {t(studentId ? "Open study PDF" : "Open source book")}
          </button>
        </div>
        <label className="field">
          <span>{t("Topic or question")}</span>
          <textarea dir="auto" rows={2} maxLength={500} value={topic} disabled={pending !== null}
            onChange={(event) => setTopic(event.target.value)} placeholder={t("For example, fractions or the area of a triangle")} />
          <small>{t(studentId ? "Search in the material’s language. Leave the topic and pages blank to study the first six pages." : "Use the book’s language when searching by topic.")}</small>
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
          <label className="field"><span>{t("Response language")}</span>
            <select value={language} disabled={pending !== null} onChange={(event) => setLanguage(event.target.value as Language | "")}>
              <option value="">{t(studentId ? "Same as the material" : "Default (Arabic)")}</option>
              <option value="ar">{t("Arabic")}</option>
              <option value="fr">{t("French")}</option>
              <option value="en">{t("English")}</option>
            </select>
          </label>
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
        {pending && <p className="tutor-progress" role="status">{t(pending === "search" ? "Searching the selected book…" : "Preparing your study activity…")}</p>}
      </form>
      {result && (
        <div ref={resultAnchor} className="tutor-result-anchor" tabIndex={-1}>
          <StudyResult activity={result} onOpenPage={setSource} onRetry={lastRequest ? () => { void runStudy(lastRequest); } : undefined} />
        </div>
      )}
      {source && <BookViewer book={book} studentId={studentId} source={source} onClose={() => setSource(null)} />}
    </>
  );
}

function MaterialLibrary({ child }: { child?: TutorChild }) {
  const [selected, setSelected] = useState("");
  const [revision, setRevision] = useState(0);
  const state = useRemote(child ? materialsEndpoint : booksEndpoint, child ? { student_id: child.id } : {}, revision, !child || !!child.classroom_name);
  const books: Book[] = state.data ?? [];
  const book = books.find((candidate) => candidate.id === selected) ?? books[0];
  if (child && !child.classroom_name) {
    return <Empty title="No current class" text="Class materials will appear once your child is placed in a class." />;
  }
  if (state.loading) return <Loading />;
  if (state.error) return <ErrorBox error={state.error} retry={() => setRevision((value) => value + 1)} />;
  if (!book) return child
    ? <Empty title="No study materials yet" text="PDFs published by your child’s teachers will appear here." />
    : <Empty title="No study books yet" text="Study books shared by your school will appear here." />;
  return (
    <>
      {books.length > 1 && (
        <label className="field tutor-document-select">
          <span>{t(child ? "Study material" : "Study book")}</span>
          <select value={book.id} onChange={(event) => setSelected(event.target.value)}>
            {books.map((candidate) => <option dir="auto" key={candidate.id} value={candidate.id}>
              {candidate.subject ? `${candidate.subject} · ${candidate.title}` : candidate.title}
            </option>)}
          </select>
        </label>
      )}
      <StudyWorkspace key={book.id} book={book} studentId={child?.id} />
    </>
  );
}

export function GuardianTutorPage() {
  const [selection, setSelection] = useState<{ childId: string } | "school" | null>(null);
  const [revision, setRevision] = useState(0);
  const state = useRemote(childrenEndpoint, {}, revision);
  const children: TutorChild[] = state.data ?? [];
  const schoolLibrary = selection === "school" || (!state.loading && !state.error && !children.length);
  const child = !schoolLibrary && (selection
    ? children.find((candidate) => candidate.id === selection.childId)
    : children.length === 1 ? children[0] : undefined);

  return (
    <div className="guardian-tutor">
      <Heading eyebrow="FAMILY WORKSPACE" title="Study tutor" description="Use your child’s class materials to get explanations, quizzes, and practice tests." />
      {!state.loading && !state.error && (
        <section className="panel tutor-library-picker" aria-label={t("Choose study materials")}>
          {children.length > 0 ? (
            <label className="field">
              <span>{t("Study library")}</span>
              <select value={schoolLibrary ? "school" : child ? `child:${child.id}` : ""} onChange={(event) => {
                const value = event.target.value;
                setSelection(value === "school" ? value : value.startsWith("child:") ? { childId: value.slice(6) } : null);
              }}>
                {!child && !schoolLibrary && <option value="" disabled>{t("Choose a child")}</option>}
                {children.map((candidate) => <option key={candidate.id} value={`child:${candidate.id}`}>
                  {[`${candidate.first_name} ${candidate.last_name}`, candidate.classroom_name].filter(Boolean).join(" · ")}
                </option>)}
                <option value="school">{t("School library")}</option>
              </select>
            </label>
          ) : <strong>{t("School library")}</strong>}
        </section>
      )}
      {state.loading ? <Loading /> : state.error ? <ErrorBox error={state.error} retry={() => setRevision((value) => value + 1)} />
        : schoolLibrary ? <MaterialLibrary key="school" />
          : child ? <MaterialLibrary key={child.id} child={child} />
            : <Empty title="Choose a child" text="Select a child to see the materials shared with their current class." />}
    </div>
  );
}
