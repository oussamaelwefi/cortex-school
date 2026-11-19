import { useEffect, useRef, useState } from "react";
import { Database, LoaderCircle, ShieldCheck } from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { t } from "./i18n";
import type { Role } from "./types";

export type ChatDataAccess = {
  school_data_enabled: boolean;
  personal_data_enabled: boolean;
  effective_data_enabled: boolean;
  can_manage_school: boolean;
  can_manage_personal: boolean;
  revision: number;
};

export function ChatDataAccessControl({
  role,
  disabled = false,
  allowSchoolManagement = false,
  onChange,
}: {
  role: Role;
  disabled?: boolean;
  allowSchoolManagement?: boolean;
  onChange?: (access: ChatDataAccess) => void;
}) {
  const api = useApi();
  const [access, setAccess] = useState<ChatDataAccess | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const sequence = useRef(0);
  const mounted = useRef(false);
  const savingLock = useRef(false);
  const callback = useRef(onChange);
  callback.current = onChange;

  useEffect(() => {
    mounted.current = true;
    async function load() {
      if (savingLock.current) return;
      const request = ++sequence.current;
      try {
        const result = await api(findEndpoint("GET", "/ai/chat/access/"), {
          role,
        });
        if (!mounted.current || request !== sequence.current) return;
        setAccess(result);
        setError("");
        callback.current?.(result);
      } catch (e) {
        if (mounted.current && request === sequence.current)
          setError((e as Error).message);
      }
    }
    void load();
    window.addEventListener("focus", load);
    return () => {
      mounted.current = false;
      sequence.current++;
      window.removeEventListener("focus", load);
    };
  }, [api, role, refresh]);

  async function change(enabled: boolean) {
    if (!access || savingLock.current || disabled) return;
    if (role === "admin" && !allowSchoolManagement) return;
    savingLock.current = true;
    const request = ++sequence.current;
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const result = await api(
        findEndpoint(
          "PUT",
          role === "admin" ? "/school/chat-data-settings" : "/ai/chat/access/",
        ),
        {},
        { enabled },
      );
      if (mounted.current && request === sequence.current) {
        setAccess(result);
        setSaved(true);
        callback.current?.(result);
      }
    } catch (e) {
      if (mounted.current && request === sequence.current)
        setError((e as Error).message);
    } finally {
      savingLock.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  const canEdit =
    access &&
    (role === "admin"
      ? allowSchoolManagement && access.can_manage_school
      : role === "guardian" && access.can_manage_personal);
  const checked =
    access &&
    (role === "admin"
      ? access.school_data_enabled
      : access.personal_data_enabled);
  return (
    <section className="chat-access" aria-label={t("Chat data privacy")}>
      <div className="chat-access-heading">
        <div>
          <ShieldCheck size={17} />
          <h2>{t("School data access")}</h2>
        </div>
        {access && (
          <span
            className={`chat-access-status ${access.effective_data_enabled ? "enabled" : "disabled"}`}
          >
            <Database size={12} />
            {t(
              access.effective_data_enabled
                ? "Data access on"
                : "Data access off",
            )}
          </span>
        )}
      </div>
      <p>
        {t(
          role === "admin"
            ? allowSchoolManagement
              ? "Allow the chat assistant to query school records for all roles. Guardian opt-outs always take priority."
              : "Manage school data access in AI settings. Guardian opt-outs always take priority."
            : role === "guardian"
              ? "Turning this off hides your profile and linked children from the chat assistant for everyone, including administrators and teachers. Your normal school access stays available."
              : "Your school controls the assistant’s access to records. Family privacy choices are always enforced.",
        )}
      </p>
      {canEdit && (
        <label className="chat-access-toggle">
          <input
            type="checkbox"
            role="switch"
            checked={Boolean(checked)}
            disabled={disabled || saving}
            onChange={(e) => void change(e.target.checked)}
          />
          <span>
            {t(
              role === "admin"
                ? "Allow school data in chat"
                : "Allow my family’s data in chat",
            )}
          </span>
          {saving && <LoaderCircle size={14} className="spin" />}
        </label>
      )}
      {!access && !error && (
        <p role="status">{t("Loading privacy settings…")}</p>
      )}
      {access && !access.school_data_enabled && (
        <p className="chat-access-note">
          {t(
            "School data access is turned off by your administrator. General writing help remains available.",
          )}
        </p>
      )}
      {access &&
        access.school_data_enabled &&
        !access.personal_data_enabled && (
          <p className="chat-access-note">
            {t(
              "Your family’s data is protected from chat lookups. General writing help remains available.",
            )}
          </p>
        )}
      {saved && (
        <p role="status" className="chat-access-note">
          {t("Privacy preference saved.")}
        </p>
      )}
      {error && (
        <div role="alert" className="chat-access-error">
          <p>{t(error)}</p>
          <button
            type="button"
            className="button subtle small"
            disabled={saving}
            onClick={() => setRefresh((value) => value + 1)}
          >
            {t("Retry")}
          </button>
        </div>
      )}
    </section>
  );
}
