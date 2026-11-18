import { useEffect, useId, useState } from "react";
import { BookOpen, Download, ExternalLink } from "lucide-react";
import { t } from "./i18n";
import { ErrorBox, Loading, useRemote } from "./ui";
import type { Endpoint } from "./types";
import { PdfReader } from "./pdf-reader";

export function PolicyDocument({ policy, endpoint, disabled = false }: {
  policy: { id: string; title: string };
  endpoint: Endpoint;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [url, setUrl] = useState("");
  const panelId = useId();
  // Fetch with the normal bearer-authenticated client before rendering.
  const state = useRemote(endpoint, { document_id: policy.id }, revision, open);
  useEffect(() => {
    if (!open || !(state.data instanceof Blob)) {
      setUrl("");
      return;
    }
    const previewUrl = URL.createObjectURL(state.data);
    setUrl(previewUrl);
    return () => URL.revokeObjectURL(previewUrl);
  }, [open, state.data]);

  const invalidFile = state.data !== null && !(state.data instanceof Blob);
  return (
    <div className="policy-document">
      <button type="button" className="button small subtle" disabled={disabled}
        aria-label={`${t(open ? "Hide document" : "View document")} · ${policy.title}`}
        aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(!open)}>
        <BookOpen size={15} />{t(open ? "Hide document" : "View document")}
      </button>
      {open && (
        <section id={panelId} className="policy-document-preview" aria-label={policy.title}>
          {state.error || invalidFile ? (
            <ErrorBox error={state.error || "This policy PDF could not be opened."}
              retry={() => setRevision((value) => value + 1)} />
          ) : !url || state.loading ? <Loading /> : (
            <>
              <div className="policy-document-toolbar">
                <p>{t("Read the document below, or open it in a new tab.")}</p>
                <div className="reminder-actions">
                  <a className="button small subtle" href={url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink size={15} />{t("Open PDF in a new tab")}
                  </a>
                  <a className="button small subtle" href={url} download={`${policy.title}.pdf`}>
                    <Download size={15} />{t("Download PDF")}
                  </a>
                </div>
              </div>
              <PdfReader file={state.data} />
            </>
          )}
        </section>
      )}
    </div>
  );
}
