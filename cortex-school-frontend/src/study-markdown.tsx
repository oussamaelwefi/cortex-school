import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { decodeHTML } from "entities";
import { Children, type ReactNode } from "react";

function readableChildren(children: ReactNode) {
  const expression = /(\(?[\d٠-٩۰-۹]+(?:[.,٫][\d٠-٩۰-۹]+)?(?:\s*\)?\s*[=+−×*÷/<>≤≥-]\s*\(?\s*[\d٠-٩۰-۹]+(?:[.,٫][\d٠-٩۰-۹]+)?)+\)?)/g;
  return Children.map(children, (child) => typeof child !== "string" ? child :
    child.split(expression).map((part, index) => index % 2 === 0 ? part :
      <bdi dir="ltr" className="tutor-inline-math" key={index}>{part}</bdi>));
}

// OCR exports sometimes escape LaTeX alignment characters more than once.
// Decode before parsing; raw HTML is still disabled in the renderer.
function readableText(text: string) {
  return decodeHTML(decodeHTML(text)).replace(/[\u200e\u200f\u202a-\u202e\u2066-\u2069]/g, "");
}

export function StudyMarkdown({ text, inline = false }: { text: string; inline?: boolean }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypeKatex, { trust: false, maxSize: 10, maxExpand: 1000, strict: "ignore" }]]}
      skipHtml
      components={{
        p: inline ? ({ children }) => <>{readableChildren(children)}</> : ({ children }) => <p dir="auto">{readableChildren(children)}</p>,
        table: ({ children }) => <div className="tutor-excerpt-table"><table dir="ltr">{children}</table></div>,
        th: ({ children }) => <th dir="auto">{children}</th>,
        td: ({ children }) => <td dir="auto">{children}</td>,
        // Textbook links and missing OCR illustrations are reference text.
        a: ({ children }) => <span>{children}</span>,
        img: () => null,
      }}
    >
      {readableText(text)}
    </Markdown>
  );
}
