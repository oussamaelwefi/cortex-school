export function translate(value, language, dictionary) {
  if (language !== "fr" || !value) return value;
  const trimmed = value.trim();
  if (dictionary[trimmed]) return value.replace(trimmed, dictionary[trimmed]);
  const tr = (text) => translate(text, language, dictionary);
  const patterns = [
    [/^Good to see you(.*)\.$/, (m) => `Heureux de vous retrouver${m[1]} !`],
    [
      /^(\d+) records shown$/,
      (m) =>
        `${m[1]} élément${m[1] === "1" ? "" : "s"} affiché${m[1] === "1" ? "" : "s"}`,
    ],
    [/^Search (.+)…$/, (m) => `Rechercher : ${tr(m[1])}…`],
    [/^Select (.+)$/, (m) => `Choisir : ${tr(m[1])}`],
    [/^Enter (.+)$/, (m) => `Saisir : ${tr(m[1])}`],
    [/^(.+) workflows$/, (m) => `Actions : ${tr(m[1])}`],
    [/^(.+) completed$/, (m) => `${tr(m[1])} : terminé`],
    [/^Continue to (.+)\.$/, (m) => `Continuer : ${tr(m[1])}.`],
    [/^(.+) items$/, (m) => `${m[1]} éléments`],
  ];
  for (const [pattern, format] of patterns) {
    const match = trimmed.match(pattern);
    if (match) return format(match);
  }
  const entry = Object.keys(dictionary).find(
    (k) => k.toLocaleLowerCase("en") === trimmed.toLocaleLowerCase("en"),
  );
  return entry ? value.replace(trimmed, dictionary[entry]) : value;
}
