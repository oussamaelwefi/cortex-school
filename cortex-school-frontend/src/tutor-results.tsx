import { useState } from "react";
import { BookOpen, Check, ChevronLeft, ChevronRight, ClipboardList, Search, Sparkles } from "lucide-react";
import { t } from "./i18n";
import { Empty } from "./ui";
import { StudyMarkdown } from "./study-markdown";

export type Source = { id: string; page: number; excerpt: string };
export type PageSource = { page: number; passages: Source[] };
type Question = { prompt: string; options: string[]; answer: string; explanation: string; source_ids: string[] };
type LessonSection = { heading: string; body: string; calculation: string | null; source_ids: string[] };
export type Action = "search" | "explain" | "summary" | "quiz" | "practice";
export type Activity = {
  action: Action;
  status: "ready" | "no_sources" | "generation_unavailable";
  text: string;
  lesson?: { title: string; takeaway: string; sections: LessonSection[] } | null;
  source_ids: string[];
  questions: Question[];
  sources: Source[];
};

function direction(text: string) {
  return /^[^\p{L}]*\p{Script=Arabic}/u.test(text) ? "rtl" : undefined;
}

export function pageLabel(page: number) {
  return `${t("Page")} ${page}`;
}

function StudyText({ text }: { text: string }) {
  return <StudyMarkdown text={text} inline />;
}

function groupPages(sources: Source[]): PageSource[] {
  const pages = new Map<number, Source[]>();
  for (const source of sources) {
    const passages = pages.get(source.page) ?? [];
    passages.push(source);
    pages.set(source.page, passages);
  }
  return Array.from(pages, ([page, passages]) => ({ page, passages }));
}

function SourceLinks({ sources, onOpenPage }: { sources: Source[]; onOpenPage: (page: PageSource) => void }) {
  const pages = groupPages(sources);
  if (!pages.length) return null;
  return (
    <div className="tutor-citations">
      <span>{t("Book sources")}</span>
      {pages.map((page) => (
        <button key={page.page} type="button" className="tutor-page-link" onClick={() => onOpenPage(page)}>
          <BookOpen size={14} aria-hidden="true" /> {pageLabel(page.page)}
        </button>
      ))}
    </div>
  );
}

export function SourceExcerpt({ source }: { source: Source }) {
  return (
    <blockquote className="tutor-excerpt" dir="auto">
      <StudyMarkdown text={source.excerpt} />
    </blockquote>
  );
}

function SearchResults({ sources, onOpenPage }: { sources: Source[]; onOpenPage: (page: PageSource) => void }) {
  return (
    <div className="tutor-hit-list">
      {groupPages(sources).map((page) => (
        <article className="tutor-hit" key={page.page}>
          <div className="tutor-hit-header">
            <h3>{pageLabel(page.page)}</h3>
            <button type="button" className="tutor-page-link" onClick={() => onOpenPage(page)}>
              <BookOpen size={14} aria-hidden="true" /> {t("Open original page")}
            </button>
          </div>
          <details>
            <summary>{t("Read the extracted passage")}</summary>
            {page.passages.map((source) => <SourceExcerpt source={source} key={source.id} />)}
          </details>
        </article>
      ))}
    </div>
  );
}

function Solution({ question, chosen, sources, onOpenPage }: {
  question: Question;
  chosen?: string;
  sources: Source[];
  onOpenPage: (page: PageSource) => void;
}) {
  const correct = chosen === question.answer;
  return (
    <div className="tutor-feedback" dir={direction(question.explanation)}
      data-correct={chosen === undefined || correct} role="status">
      <div className="tutor-feedback-heading">
        {correct && <Check size={17} aria-hidden="true" />}
        <strong>{t(chosen === undefined ? "Solution" : correct ? "Correct" : "Correct answer")}</strong>
      </div>
      <p className="tutor-correct-answer" dir="auto"><StudyText text={question.answer} /></p>
      <p className="tutor-prose" dir="auto"><StudyText text={question.explanation} /></p>
      <SourceLinks sources={sources.filter((source) => question.source_ids.includes(source.id))} onOpenPage={onOpenPage} />
    </div>
  );
}

function Quiz({ activity, onOpenPage }: { activity: Activity; onOpenPage: (page: PageSource) => void }) {
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [checked, setChecked] = useState<Record<number, string>>({});
  const question = activity.questions[index];
  const choice = selected[index];
  const graded = checked[index] !== undefined;
  const completed = Object.keys(checked).length;
  const score = activity.questions.filter((item, position) => checked[position] === item.answer).length;
  const questionLabel = t("Question {number} of {total}")
    .replace("{number}", String(index + 1)).replace("{total}", String(activity.questions.length));
  return (
    <div className="tutor-quiz">
      <div className="tutor-quiz-progress">
        <strong>{questionLabel}</strong>
        <progress aria-label={t("Quiz progress")} max={activity.questions.length} value={completed} />
      </div>
      <fieldset className="tutor-quiz-question" dir={direction(question.prompt)}>
        <legend dir="auto"><StudyText text={question.prompt} /></legend>
        <div className="tutor-choices">
          {question.options.map((option) => (
            <label key={option} className="tutor-choice" data-selected={choice === option}
              data-correct={graded && option === question.answer}>
              <input type="radio" name="tutor-quiz-option" value={option} checked={choice === option}
                disabled={graded} onChange={() => setSelected({ ...selected, [index]: option })} />
              <span dir="auto"><StudyText text={option} /></span>
              {graded && option === question.answer && <Check aria-hidden="true" size={16} />}
            </label>
          ))}
        </div>
      </fieldset>
      {graded && <Solution question={question} chosen={checked[index]} sources={activity.sources} onOpenPage={onOpenPage} />}
      <div className="tutor-quiz-navigation">
        <button type="button" className="button small subtle" disabled={index === 0} onClick={() => setIndex(index - 1)}>
          <ChevronLeft aria-hidden="true" size={16} /> {t("Previous")}
        </button>
        {graded
          ? index + 1 < activity.questions.length
            ? <button type="button" className="button small primary" onClick={() => setIndex(index + 1)}>
                {t("Next question")} <ChevronRight aria-hidden="true" size={16} />
              </button>
            : <strong className="tutor-score">{t("{score} of {total} correct")
                .replace("{score}", String(score)).replace("{total}", String(activity.questions.length))}</strong>
          : <button type="button" className="button small primary" disabled={choice === undefined}
              onClick={() => setChecked({ ...checked, [index]: choice })}>
              {t("Check answer")}
            </button>}
      </div>
    </div>
  );
}

function PracticeQuestion({ question, index, sources, onOpenPage }: {
  question: Question;
  index: number;
  sources: Source[];
  onOpenPage: (page: PageSource) => void;
}) {
  const [show, setShow] = useState(false);
  return (
    <article className="tutor-practice-question" dir={direction(question.prompt)}>
      <span className="tutor-problem-number">{t("Problem {number}").replace("{number}", String(index + 1))}</span>
      <h3 dir="auto"><StudyText text={question.prompt} /></h3>
      <button type="button" className="button small subtle" aria-expanded={show} onClick={() => setShow(!show)}>
        {t(show ? "Hide solution" : "Show solution")}
      </button>
      {show && <Solution question={question} sources={sources} onOpenPage={onOpenPage} />}
    </article>
  );
}

const resultLabels = { search: "Book passages", explain: "Explanation", summary: "Summary", quiz: "Quiz", practice: "Practice test" };

export function StudyResult({ activity, onOpenPage, onRetry }: { activity: Activity; onOpenPage: (page: PageSource) => void; onRetry?: () => void }) {
  if (activity.status === "no_sources") {
    return <Empty title="No matching passages" text="Try a different topic or choose another page from the book." />;
  }
  const isSearch = activity.action === "search";
  const unavailable = activity.status === "generation_unavailable";
  const label = t(resultLabels[activity.action]);
  const Icon = isSearch ? Search : activity.lesson ? Sparkles : ClipboardList;
  const title = activity.lesson?.title ?? label;
  return (
    <section className="panel tutor-result">
      <header className="tutor-result-header" dir={direction(title)}>
        <span className="tutor-result-icon"><Icon aria-hidden="true" size={21} /></span>
        <div>
          {activity.lesson && <p>{label}</p>}
          <h2 dir="auto">{title}</h2>
        </div>
      </header>
      <div className="tutor-result-body">
        {unavailable ? (
          <>
            <div className="tutor-unavailable" role="status">
              <p className="tutor-result-note">{t("The tutor could not generate this activity. Please try again.")}</p>
              {onRetry && <button type="button" className="button small primary" onClick={onRetry}>{t("Try again")}</button>}
            </div>
            <details className="tutor-fallback-sources">
              <summary>{t("Read matching book passages")}</summary>
              <SearchResults sources={activity.sources} onOpenPage={onOpenPage} />
            </details>
          </>
        ) : isSearch
          ? <SearchResults sources={activity.sources} onOpenPage={onOpenPage} />
          : activity.lesson ? (
            <>
              <p className="tutor-takeaway" dir="auto"><StudyText text={activity.lesson.takeaway} /></p>
              <div className="tutor-lesson-sections">
                {activity.lesson.sections.map((section, index) => (
                  <article key={index} className="tutor-lesson-section" dir={direction(section.heading)}>
                    <div dir="auto">
                      <h3>{section.heading}</h3>
                      <p className="tutor-prose"><StudyText text={section.body} /></p>
                    </div>
                    {section.calculation && <div className="tutor-equation" dir="ltr">{section.calculation}</div>}
                    <SourceLinks sources={activity.sources.filter((source) => section.source_ids.includes(source.id))} onOpenPage={onOpenPage} />
                  </article>
                ))}
              </div>
            </>
          ) : activity.action === "quiz" && activity.questions.length > 0
            ? <Quiz activity={activity} onOpenPage={onOpenPage} />
            : activity.questions.length > 0 ? (
              <div className="tutor-practice-list">
                {activity.questions.map((question, index) => <PracticeQuestion key={index} question={question}
                  index={index} sources={activity.sources} onOpenPage={onOpenPage} />)}
              </div>
            ) : (
              <>
                <p className="tutor-prose" dir="auto"><StudyText text={activity.text} /></p>
                <SourceLinks sources={activity.sources} onOpenPage={onOpenPage} />
              </>
            )}
      </div>
    </section>
  );
}
