import { useEffect, useId, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { t } from "./i18n";
import { ErrorBox, Loading } from "./ui";

export function PdfReader({ file }: { file: Blob }) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(0);
  const [rendering, setRendering] = useState(true);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const textId = useId();

  useEffect(() => {
    let active = true;
    let task: PDFDocumentLoadingTask | undefined;
    setPdf(null);
    setError("");
    setPage(1);
    setRendering(true);
    Promise.all([import("./pdf-engine"), file.arrayBuffer()])
      .then(async ([engine, data]) => {
        if (!active) return;
        task = engine.openPdf(data);
        const document = await task.promise;
        if (active) setPdf(document);
      })
      .catch(() => { if (active) setError("This policy PDF could not be opened."); });
    return () => { active = false; void task?.destroy().catch(() => {}); };
  }, [file, revision]);

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const resize = () => setWidth(Math.max(0, node.clientWidth - 24));
    resize();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(resize);
      observer.observe(node);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  useEffect(() => {
    const node = canvas.current;
    if (!pdf || !node || !width) return;
    let active = true;
    let task: RenderTask | undefined;
    setRendering(true);
    setText("");
    setError("");
    pdf.getPage(page).then(async (documentPage) => {
      if (!active) return;
      const original = documentPage.getViewport({ scale: 1 });
      const viewport = documentPage.getViewport({ scale: width / original.width * zoom });
      const ratio = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(12_000_000 / (viewport.width * viewport.height)));
      node.width = Math.ceil(viewport.width * ratio);
      node.height = Math.ceil(viewport.height * ratio);
      node.style.width = `${viewport.width}px`;
      node.style.height = `${viewport.height}px`;
      task = documentPage.render({ canvas: node, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
      const [, content] = await Promise.all([task.promise, documentPage.getTextContent().catch(() => null)]);
      if (active) {
        setText(content?.items.map((item) => "str" in item ? item.str : "").join(" ") ?? "");
        setRendering(false);
        container.current?.scrollTo?.({ top: 0, left: 0 });
      }
    }).catch(() => { if (active) setError("This policy PDF could not be opened."); });
    return () => { active = false; task?.cancel(); };
  }, [pdf, page, zoom, width]);

  const pageLabel = t("Page {number} of {total}").replace("{number}", String(page)).replace("{total}", String(pdf?.numPages ?? "…"));
  return (
    <div className="policy-pdf-reader">
      {pdf && (
        <div className="policy-page-controls" aria-label={t("Document controls")}>
          <button type="button" className="icon-button" aria-label={t("Previous page")} disabled={rendering || page === 1} onClick={() => setPage(page - 1)}><ChevronLeft size={18} /></button>
          <span aria-live="polite">{pageLabel}</span>
          <button type="button" className="icon-button" aria-label={t("Next page")} disabled={rendering || page === pdf.numPages} onClick={() => setPage(page + 1)}><ChevronRight size={18} /></button>
          <button type="button" className="icon-button" aria-label={t("Zoom out")} disabled={rendering || zoom <= 0.5} onClick={() => setZoom(Math.max(0.5, zoom - 0.25))}><ZoomOut size={18} /></button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" className="icon-button" aria-label={t("Zoom in")} disabled={rendering || zoom >= 2} onClick={() => setZoom(Math.min(2, zoom + 0.25))}><ZoomIn size={18} /></button>
        </div>
      )}
      {error ? <ErrorBox error={error} retry={() => setRevision((value) => value + 1)} /> : rendering && <Loading />}
      <div className="policy-pdf-page" ref={container} aria-busy={!error && rendering}>
        <canvas ref={canvas} key={`${page}-${zoom}-${width}`} role="img" aria-label={pageLabel} aria-describedby={textId} hidden={Boolean(error) || !pdf} />
        <p id={textId} className="sr-only">{text}</p>
      </div>
    </div>
  );
}
