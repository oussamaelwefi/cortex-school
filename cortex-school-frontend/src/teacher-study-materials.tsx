import { useState, type FormEvent } from "react";
import { FileText, LoaderCircle, Upload } from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { t } from "./i18n";
import { Empty, ErrorBox, Loading, useRemote } from "./ui";
import type { TeacherClassroom } from "./teacher-classrooms";

const materialsPath = "/teacher/classrooms/{classroom_id}/study-materials/";
const listMaterials = findEndpoint("GET", materialsPath);
const publishMaterial = {
  ...findEndpoint("POST", materialsPath),
  timeoutMs: 60000,
};
const unpublishMaterial = findEndpoint(
  "DELETE",
  `${materialsPath}{material_id}/`,
);
const maxPdfSize = 10 * 1024 * 1024;

type Material = {
  id: string;
  title: string;
  subject: string;
  grade_level: number | null;
  page_count: number;
  indexed_page_count: number;
};

function indexedPages(material: Material) {
  return t("{indexed} of {total} pages indexed")
    .replace("{indexed}", String(material.indexed_page_count))
    .replace("{total}", String(material.page_count));
}

export function TeacherStudyMaterials({
  classroom,
  classrooms,
  revision,
}: {
  classroom: TeacherClassroom;
  classrooms: TeacherClassroom[];
  revision: number;
}) {
  const api = useApi();
  const [refresh, setRefresh] = useState(0);
  const [adding, setAdding] = useState(false);
  const [additional, setAdditional] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const params = { classroom_id: classroom.id };
  const state = useRemote(listMaterials, params, revision + refresh);
  const materials: Material[] = state.data ?? [];
  const otherClasses = classrooms.filter(
    ({ id, access_status }) =>
      id !== classroom.id && access_status === "current",
  );

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || removing) return;
    const form = new FormData(event.currentTarget);
    const pdf = form.get("file");
    const title = String(form.get("title") ?? "").trim();
    const subject = String(form.get("subject") ?? "").trim();
    if (!(pdf instanceof File) || !pdf.size || !title || !subject) {
      setError("Choose a PDF and enter its lesson title and subject.");
      return;
    }
    if (pdf.size > maxPdfSize) {
      setError("Choose a PDF of 10 MB or less.");
      return;
    }
    const grade = form.get("grade_level");
    const payload = new FormData();
    payload.append("file", pdf);
    payload.append(
      "metadata",
      JSON.stringify({
        title,
        subject,
        grade_level: grade ? Number(grade) : null,
        additional_classroom_ids: additional,
      }),
    );
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const material: Material = await api(publishMaterial, params, payload);
      setAdding(false);
      setAdditional([]);
      setRefresh((value) => value + 1);
      setNotice(
        t("Published to the selected classes. {pages}.").replace(
          "{pages}",
          indexedPages(material),
        ),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function unpublish(material: Material) {
    if (busy || removing) return;
    setRemoving(material.id);
    setError("");
    setNotice("");
    try {
      await api(unpublishMaterial, { ...params, material_id: material.id });
      setRefresh((value) => value + 1);
      setNotice(t("Material unpublished from this class."));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div className="teacher-study-materials">
      <div className="tc-roster-heading">
        <div>
          <h3>{t("Study materials")}</h3>
          <p>
            {t("Share lesson PDFs that families can use in the Study tutor.")}
          </p>
        </div>
        {!adding && (
          <button
            type="button"
            className="button primary"
            onClick={() => {
              setAdding(true);
              setError("");
              setNotice("");
            }}
          >
            <Upload size={16} aria-hidden="true" /> {t("Upload study PDF")}
          </button>
        )}
      </div>
      {adding && (
        <form className="study-material-form" onSubmit={publish}>
          <fieldset disabled={busy}>
            <legend className="sr-only">{t("Upload study PDF")}</legend>
            <label className="field">
              <span>{t("Lesson title")}</span>
              <input name="title" maxLength={200} required dir="auto" />
            </label>
            <label className="field">
              <span>{t("Subject")}</span>
              <input name="subject" maxLength={100} required dir="auto" />
            </label>
            <label className="field">
              <span>{t("Grade level (optional)")}</span>
              <input type="number" name="grade_level" min={1} max={13} />
            </label>
            <label className="field study-material-file">
              <span>{t("Study PDF")}</span>
              <input
                type="file"
                name="file"
                accept="application/pdf,.pdf"
                required
              />
              <small>
                {t(
                  "Choose a PDF with selectable text, up to 10 MB and 100 pages.",
                )}
              </small>
            </label>
            {otherClasses.length > 0 && (
              <fieldset className="study-material-classes">
                <legend>{t("Also share with")}</legend>
                {otherClasses.map((other) => (
                  <label key={other.id}>
                    <input
                      type="checkbox"
                      checked={additional.includes(other.id)}
                      disabled={
                        additional.length >= 19 &&
                        !additional.includes(other.id)
                      }
                      onChange={(event) =>
                        setAdditional((ids) =>
                          event.target.checked
                            ? [...ids, other.id]
                            : ids.filter((id) => id !== other.id),
                        )
                      }
                    />
                    {other.name}
                  </label>
                ))}
              </fieldset>
            )}
          </fieldset>
          <div className="study-material-actions">
            <button
              type="button"
              className="button subtle"
              disabled={busy}
              onClick={() => {
                setAdding(false);
                setAdditional([]);
                setError("");
              }}
            >
              {t("Cancel")}
            </button>
            <button
              type="submit"
              className="button primary"
              disabled={busy || removing !== null}
            >
              {busy ? (
                <LoaderCircle size={16} className="spin" aria-hidden="true" />
              ) : (
                <Upload size={16} aria-hidden="true" />
              )}
              {t(busy ? "Indexing and publishing…" : "Index and publish")}
            </button>
          </div>
        </form>
      )}
      {error && <ErrorBox error={error} />}
      {notice && (
        <p className="study-material-notice" role="status">
          {notice}
        </p>
      )}
      {state.loading ? (
        <Loading />
      ) : state.error ? (
        <ErrorBox
          error={state.error}
          retry={() => setRefresh((value) => value + 1)}
        />
      ) : materials.length > 0 ? (
        <ul className="study-material-list">
          {materials.map((material) => (
            <li key={material.id}>
              <FileText size={22} aria-hidden="true" />
              <div>
                <strong dir="auto">{material.title}</strong>
                <p>
                  <bdi>{material.subject}</bdi> · {indexedPages(material)}
                </p>
              </div>
              <button
                type="button"
                className="button subtle small"
                disabled={busy || removing !== null}
                aria-label={`${t("Unpublish")} · ${material.title}`}
                onClick={() => void unpublish(material)}
              >
                {t(removing === material.id ? "Unpublishing…" : "Unpublish")}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        !adding && (
          <Empty
            title="No materials published"
            text="Upload a lesson PDF to make it available to this class’s families."
          />
        )
      )}
    </div>
  );
}
