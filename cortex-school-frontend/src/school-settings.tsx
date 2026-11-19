import { useState } from "react";
import {
  CalendarDays,
  ChevronDown,
  RefreshCw,
  Settings2,
  Sparkles,
} from "lucide-react";
import { findEndpoint } from "./api";
import { t, useLanguage } from "./i18n";
import { ErrorBox, Loading, Operation, useRemote } from "./ui";
import { SchoolPoliciesButton } from "./reminders";
import { AISettingsValues, InstructionalDays } from "./school-settings-values";
import type { Endpoint } from "./types";
import { ChatDataAccessControl } from "./chat-data-access";

export function SchoolSettingsPage() {
  useLanguage();
  const [refresh, setRefresh] = useState(0),
    [aiOpen, setAiOpen] = useState(false),
    [operation, setOperation] = useState<Endpoint | null>(null);
  const attendance = useRemote(
    findEndpoint("GET", "/school/attendance-settings"),
    {},
    refresh,
  );
  const ai = useRemote(
    findEndpoint("GET", "/school/ai-settings"),
    {},
    refresh,
    aiOpen,
  );
  const reload = () => setRefresh((value) => value + 1);
  return (
    <div className="school-settings-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("SCHOOL MANAGEMENT")}</p>
          <h1>{t("School settings")}</h1>
          <p>
            {t(
              "Set your school’s instructional days, attendance rules, and AI preferences.",
            )}
          </p>
        </div>
        <div className="heading-actions">
          <button
            className="button subtle"
            onClick={reload}
            disabled={attendance.loading || ai.loading}
          >
            <RefreshCw size={15} />
            {t("Refresh")}
          </button>
          <SchoolPoliciesButton />
        </div>
      </div>
      <ChatDataAccessControl role="admin" />
      <section className="panel ss-section">
        <header>
          <div>
            <span className="ss-section-icon">
              <CalendarDays size={21} />
            </span>
            <div>
              <h2>{t("Attendance settings")}</h2>
              <p>{t("Choose when attendance is expected at your school.")}</p>
            </div>
          </div>
          <button
            className="button subtle small"
            disabled={attendance.loading || Boolean(attendance.error)}
            onClick={() =>
              setOperation(findEndpoint("PUT", "/school/attendance-settings"))
            }
          >
            <Settings2 size={14} />
            {t("Edit attendance settings")}
          </button>
        </header>
        {attendance.loading ? (
          <Loading />
        ) : attendance.error ? (
          <div className="ss-content">
            <ErrorBox error={attendance.error} retry={reload} />
          </div>
        ) : (
          attendance.data && (
            <div className="ss-content">
              <dl className="ss-attendance-meta">
                <div>
                  <dt>{t("School timezone")}</dt>
                  <dd>{attendance.data.timezone}</dd>
                </div>
                <div>
                  <dt>{t("Attendance cutoff time")}</dt>
                  <dd>{attendance.data.attendance_cutoff_time.slice(0, 5)}</dd>
                </div>
              </dl>
              <h3>{t("Instructional days")}</h3>
              <p className="ss-help">
                {t(
                  "Attendance is expected on these days, except calendar holidays and breaks.",
                )}
              </p>
              <InstructionalDays
                days={attendance.data.instructional_weekdays}
              />
            </div>
          )
        )}
      </section>
      <section className="panel ss-section">
        <header>
          <div>
            <span className="ss-section-icon">
              <Sparkles size={21} />
            </span>
            <div>
              <h2>{t("AI settings")}</h2>
              <p>
                {t(
                  "See which AI features are enabled and their default languages.",
                )}
              </p>
            </div>
          </div>
          <button
            className="button subtle small"
            aria-expanded={aiOpen}
            aria-controls="school-ai-settings"
            onClick={() => setAiOpen(!aiOpen)}
          >
            {t(aiOpen ? "Hide AI settings" : "View AI settings")}
            <ChevronDown size={14} />
          </button>
        </header>
        {aiOpen && (
          <div className="ss-content" id="school-ai-settings">
            {ai.loading ? (
              <Loading />
            ) : ai.error ? (
              <ErrorBox error={ai.error} retry={reload} />
            ) : (
              ai.data && (
                <>
                  <AISettingsValues settings={ai.data} />
                  <div className="ss-edit-ai">
                    <button
                      className="button subtle small"
                      onClick={() =>
                        setOperation(findEndpoint("PUT", "/school/ai-settings"))
                      }
                    >
                      <Settings2 size={14} />
                      {t("Edit AI settings")}
                    </button>
                  </div>
                </>
              )
            )}
          </div>
        )}
      </section>
      {operation && (
        <Operation
          endpoint={operation}
          onClose={() => setOperation(null)}
          onDone={reload}
        />
      )}
    </div>
  );
}
