import { t } from "./i18n";

export const instructionalDays = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;
export function InstructionalDays({ days }: { days: number[] }) {
  return (
    <ul className="ss-weekdays" aria-label={t("Instructional days")}>
      {instructionalDays.map((name, index) => (
        <li key={name} data-instructional={days.includes(index)}>
          <strong>{t(name)}</strong>
          <span>
            {t(days.includes(index) ? "Instructional day" : "No classes")}
          </span>
        </li>
      ))}
    </ul>
  );
}
export type SchoolAISettings = {
  ai_teacher_draft_enabled: boolean;
  ai_teacher_draft_default_language: string;
  ai_guardian_weekly_explanation_enabled: boolean;
  ai_guardian_weekly_explanation_default_language: string;
};
const languages: Record<string, string> = {
  auto: "Automatic",
  en: "English",
  fr: "French",
  ar: "Arabic",
};
export function AISettingsValues({ settings }: { settings: SchoolAISettings }) {
  return (
    <div className="ss-ai-grid">
      {[
        {
          title: "Teacher update drafts",
          description: "AI assistance for teachers writing student updates.",
          enabled: settings.ai_teacher_draft_enabled,
          language: settings.ai_teacher_draft_default_language,
        },
        {
          title: "Guardian weekly explanations",
          description: "AI explanations of children’s weekly school updates.",
          enabled: settings.ai_guardian_weekly_explanation_enabled,
          language: settings.ai_guardian_weekly_explanation_default_language,
        },
      ].map((feature) => (
        <article key={feature.title}>
          <div>
            <h3>{t(feature.title)}</h3>
            <span className="ss-feature-status" data-enabled={feature.enabled}>
              {t(feature.enabled ? "Enabled" : "Disabled")}
            </span>
          </div>
          <p>{t(feature.description)}</p>
          <dl>
            <dt>{t("Default language")}</dt>
            <dd>{t(languages[feature.language] ?? feature.language)}</dd>
          </dl>
        </article>
      ))}
    </div>
  );
}
