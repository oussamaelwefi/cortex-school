import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;

// Bundle the font, character-map and image-decoder resources with the app.
// Documents never need a third-party CDN to display their contents.
const assets = Object.fromEntries(Object.entries(import.meta.glob<string>(
  "../node_modules/pdfjs-dist/{cmaps,standard_fonts,wasm}/*.{bcmap,ttf,pfb,wasm,js}",
  { eager: true, query: "?url", import: "default" },
)).map(([path, url]) => [path.split("/pdfjs-dist/")[1], url]));

class BundledPdfData {
  async fetch({ kind, filename }: { kind: string; filename: string }) {
    const directory = { cMapUrl: "cmaps", standardFontDataUrl: "standard_fonts", wasmUrl: "wasm" }[kind];
    const url = assets[`${directory}/${filename}`];
    if (!url) throw new Error("Missing PDF rendering resource");
    const response = await fetch(url);
    if (!response.ok) throw new Error("Could not load PDF rendering resource");
    return new Uint8Array(await response.arrayBuffer());
  }
}

export function openPdf(data: ArrayBuffer) {
  return getDocument({ data: new Uint8Array(data), BinaryDataFactory: BundledPdfData, useWorkerFetch: false });
}
