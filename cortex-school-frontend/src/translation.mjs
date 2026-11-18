export function translate(value, language, dictionary) {
  if (language !== "fr" || !value) return value;
  const trimmed = value.trim();
  if (dictionary[trimmed]) return value.replace(trimmed, dictionary[trimmed]);
  const tr = (text) => translate(text, language, dictionary);
  const patterns = [
    [/^Acknowledgement overdue for (.+)$/, (m) => `Accusé de réception en retard pour ${m[1]}`],
    [/^(.+) attendance is missing$/, (m) => `Présence non transmise pour ${m[1]}`],
    [/^(.+) needs a teacher assignment$/, (m) => `Un enseignant doit être affecté à ${m[1]}`],
    [/^Registration request for (.+)$/, (m) => `Demande d’inscription pour ${m[1]}`],
    [/^Invitation for (.+)$/, (m) => `Invitation pour ${m[1]}`],
    [/^(\d+) guardian acknowledgements? remain outstanding\.$/, (m) => `${m[1]} accusé${m[1] === "1" ? "" : "s"} de réception en attente.`],
    [/^No active teacher assignment owns attendance for (\d{4}-\d{2}-\d{2})\.$/, (m) => `Aucun enseignant actif n’est chargé de la présence pour le ${m[1]}.`],
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
