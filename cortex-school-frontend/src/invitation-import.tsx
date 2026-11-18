import { useState } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  FileUp,
  GraduationCap,
  Layers,
  LoaderCircle,
  ShieldCheck,
  Users,
} from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { label } from "./forms";
import { t } from "./i18n";
import { Badge, ErrorBox, Modal } from "./ui";

const uploadEndpoint = findEndpoint("POST", "/invitations/upload/");
const modes = [
  {
    value: "school_admin",
    title: "Administrators only",
    description: "Invite everyone as a school administrator.",
    icon: ShieldCheck,
  },
  {
    value: "teacher",
    title: "Teachers only",
    description: "Invite everyone as a teacher.",
    icon: GraduationCap,
  },
  {
    value: "guardian",
    title: "Guardians only",
    description: "Invite everyone as a guardian.",
    icon: Users,
  },
  {
    value: "mixed",
    title: "Mixed roles",
    description: "Read each person’s role from the role_slug column.",
    icon: Layers,
  },
] as const;
type Mode = (typeof modes)[number]["value"];
type ImportResult = {
  created_count: number;
  updated_count: number;
  queued_count: number;
  skipped_count: number;
  failed_count: number;
  invitations: {
    id: string;
    email: string;
    role_slug: string | null;
    send_status: string;
  }[];
};

export function InvitationCsvImport({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const api = useApi();
  const [mode, setMode] = useState<Mode | null>(null);
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const selected = modes.find((entry) => entry.value === mode);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!mode || !file || busy) return;
    setBusy(true);
    setError("");
    try {
      const response: ImportResult = await api(
        uploadEndpoint,
        { role_mode: mode },
        undefined,
        file,
      );
      setResult(response);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Import invitations" onClose={onClose} wide>
      {result ? (
        <>
          <div className="modal-body invitation-import">
            <div className="ii-result-title">
              <CheckCircle2 size={23} />
              <div>
                <h3>{t("CSV import complete")}</h3>
                <p>
                  {t(
                    "Invitations are sent in the background. Follow their delivery status in Invitations.",
                  )}
                </p>
              </div>
            </div>
            <div className="ii-result-counts">
              <div>
                <strong>{result.queued_count}</strong>
                <span>{t("Queued to send")}</span>
              </div>
              <div>
                <strong>{result.skipped_count}</strong>
                <span>{t("Already queued or sent")}</span>
              </div>
              <div>
                <strong>{result.failed_count}</strong>
                <span>{t("Could not queue")}</span>
              </div>
            </div>
            {selected && (
              <p className="ii-result-mode">
                {t("Import type")}: <strong>{t(selected.title)}</strong>
              </p>
            )}
            <div className="table-wrap ii-results">
              <table>
                <thead>
                  <tr>
                    <th>{t("Email")}</th>
                    <th>{t("Role")}</th>
                    <th>{t("Status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.invitations.slice(0, 10).map((invitation) => (
                    <tr key={invitation.id}>
                      <td>{invitation.email}</td>
                      <td>{label(invitation.role_slug || "guardian")}</td>
                      <td>
                        <Badge value={invitation.send_status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {result.invitations.length > 10 && (
              <p className="ii-result-mode">
                {t(
                  "Showing the first 10 results. View Invitations for the full list.",
                )}
              </p>
            )}
          </div>
          <footer>
            <button
              type="button"
              className="button subtle"
              onClick={() => {
                setResult(null);
                setMode(null);
                setFile(undefined);
                setError("");
              }}
            >
              {t("Import another CSV")}
            </button>
            <Link
              to="/invitations"
              className="button primary"
              onClick={onClose}
            >
              {t("View invitations")}
            </Link>
          </footer>
        </>
      ) : (
        <form onSubmit={submit}>
          <div className="modal-body invitation-import">
            <fieldset className="ii-role-picker" disabled={busy}>
              <legend>{t("Who is in this CSV file?")}</legend>
              <p>
                {t(
                  "Choose how roles should be assigned before selecting your file.",
                )}
              </p>
              <div className="ii-role-options">
                {modes.map(
                  ({ value, title, description, icon: Icon }, index) => (
                    <label
                      className="ii-role-option"
                      key={value}
                      data-selected={mode === value}
                    >
                      <input
                        type="radio"
                        name="invitation-role-mode"
                        value={value}
                        required
                        checked={mode === value}
                        onChange={() => {
                          setMode(value);
                          setError("");
                        }}
                      />
                      <span className="ii-role-icon">
                        <Icon size={21} />
                      </span>
                      <span>
                        <strong>
                          {index + 1}. {t(title)}
                        </strong>
                        <small>{t(description)}</small>
                      </span>
                    </label>
                  ),
                )}
              </div>
            </fieldset>
            {selected && (
              <section
                className="ii-file-section"
                aria-label={t("Select invitation CSV")}
              >
                <div className="ii-role-note">
                  <p>
                    {t(
                      mode === "mixed"
                        ? "Every row must have a valid role_slug: school_admin, teacher, or guardian."
                        : "The selected role applies to every person. Any role_slug values in the CSV are ignored.",
                    )}
                  </p>
                </div>
                <label className="upload field">
                  <span>
                    <FileUp size={16} />
                    {t("Choose CSV file")}
                  </span>
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    required
                    disabled={busy}
                    onChange={(event) => {
                      setFile(event.target.files?.[0]);
                      setError("");
                    }}
                  />
                  <small>
                    {t(
                      mode === "mixed"
                        ? "Required columns: email, role_slug. Optional: first_name, last_name."
                        : "Required column: email. Optional: first_name, last_name.",
                    )}{" "}
                    {t("Save the file as UTF-8 CSV.")}
                  </small>
                </label>
                <p className="ii-send-note">
                  {t(
                    "Importing automatically queues these invitations for sending.",
                  )}
                </p>
              </section>
            )}
            {error && <ErrorBox error={t(error)} />}
          </div>
          <footer>
            <button type="button" className="button subtle" onClick={onClose}>
              {t("Close")}
            </button>
            <button
              type="submit"
              className="button primary"
              disabled={busy || !mode || !file}
            >
              {busy ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <FileUp size={16} />
              )}
              {t(busy ? "Importing…" : "Import and send invitations")}
            </button>
          </footer>
        </form>
      )}
    </Modal>
  );
}
