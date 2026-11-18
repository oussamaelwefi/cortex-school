import { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  GraduationCap,
  LogOut,
  RefreshCw,
} from "lucide-react";
import { findEndpoint, useApi } from "./api";
import { LanguageSwitch, t } from "./i18n";
import { ErrorBox, Loading } from "./ui";

type SchoolRequest = {
  id: string;
  school_name: string;
  country_code: string;
  timezone: string;
  status: "pending" | "provisioning" | "failed" | "approved" | "rejected";
  rejection_reason: string | null;
  organization_id: string | null;
};
const descriptions = {
  pending: "Your request is waiting for a platform operator to review it.",
  provisioning:
    "Your request was accepted. We are preparing your school workspace.",
  failed:
    "Your request was accepted. The platform team needs to finish setting up your school.",
  approved:
    "Your school is ready. Open your workspace to sign in as its first administrator.",
  rejected:
    "Your request was not accepted. You can review the reason below and submit a new request.",
};
const statusNames = {
  pending: "Awaiting review",
  provisioning: "Setting up your school",
  failed: "Setup needs attention",
  approved: "School ready",
  rejected: "Request declined",
};

export function OnboardingPage({
  email,
  onExit,
  onEnter,
}: {
  email: string;
  onExit: () => void;
  onEnter: (organizationId: string) => Promise<void>;
}) {
  const api = useApi();
  const [requests, setRequests] = useState<SchoolRequest[] | null>(null);
  const [countries, setCountries] = useState<{ code: string; name: string }[]>(
    [],
  );
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [schoolName, setSchoolName] = useState("");
  const [country, setCountry] = useState("");
  const localTimezone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const [timezone, setTimezone] = useState(localTimezone);
  const [notes, setNotes] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([
      api(findEndpoint("GET", "/school-requests/mine")),
      api(findEndpoint("GET", "/school-requests/countries")),
    ])
      .then(([items, options]) => {
        if (!active) return;
        setRequests(items);
        setCountries(options);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [api]);
  const awaitingCompletion =
    requests?.some((item) =>
      ["pending", "provisioning", "failed"].includes(item.status),
    ) ?? false;
  useEffect(() => {
    if (!awaitingCompletion) return;
    let active = true;
    const timer = window.setInterval(() => {
      api(findEndpoint("GET", "/school-requests/mine"))
        .then((items) => {
          if (active) setRequests(items);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [api, awaitingCompletion]);
  async function refresh() {
    setRefreshing(true);
    setError("");
    try {
      const [items, options] = await Promise.all([
        api(findEndpoint("GET", "/school-requests/mine")),
        api(findEndpoint("GET", "/school-requests/countries")),
      ]);
      setRequests(items);
      setCountries(options);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api(
        findEndpoint("POST", "/school-requests/"),
        {},
        {
          school_name: schoolName.trim(),
          country_code: country,
          timezone: timezone.trim(),
          notes: notes.trim(),
        },
      );
      setRequests((items) => [result, ...(items || [])]);
      setShowForm(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function enter(organizationId: string) {
    setBusy(true);
    setError("");
    try {
      await onEnter(organizationId);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <div className="onboarding-page">
      <header className="onboarding-topbar">
        <a className="onboarding-brand" href="/">
          cortex<span>school</span>
        </a>
        <div>
          <LanguageSwitch />
          <button className="button" onClick={onExit}>
            <LogOut size={16} />
            {t("Sign out")}
          </button>
        </div>
      </header>
      <main className="onboarding-main">
        <div className="onboarding-intro">
          <span className="onboarding-icon">
            <GraduationCap size={32} />
          </span>
          <p className="eyebrow">{t("WELCOME TO CORTEX SCHOOL")}</p>
          <h1>{t("Let’s find your school workspace.")}</h1>
          <p>
            {t("You are signed in as")} <strong>{email}</strong>.
          </p>
        </div>
        {error && <ErrorBox error={error} retry={refresh} />}
        {!requests && !error && <Loading />}
        <div className="onboarding-grid">
          <section
            className="onboarding-content"
            aria-label={t("Your school requests")}
          >
            {requests?.map((item) => (
              <article
                className={`onboarding-card onboarding-request ${item.status}`}
                key={item.id}
              >
                <div className="onboarding-request-heading">
                  <div>
                    <p className="eyebrow">{t("YOUR SCHOOL REQUEST")}</p>
                    <h2>{item.school_name}</h2>
                  </div>
                  <span className="onboarding-status">
                    {item.status === "approved" ? (
                      <CheckCircle2 size={16} />
                    ) : (
                      <Clock3 size={16} />
                    )}
                    {t(statusNames[item.status])}
                  </span>
                </div>
                <p role="status">{t(descriptions[item.status])}</p>
                {item.rejection_reason && (
                  <div className="onboarding-reason">
                    <strong>{t("Reason")}</strong>
                    <p>{item.rejection_reason}</p>
                  </div>
                )}
                {item.status === "approved" && item.organization_id && (
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => enter(item.organization_id!)}
                  >
                    {t(busy ? "Connecting…" : "Open school workspace")}
                    <ArrowRight size={16} />
                  </button>
                )}
              </article>
            ))}
            {requests && !awaitingCompletion && (
              <section className="onboarding-card">
                <h2>{t("Setting up a new school?")}</h2>
                <p>
                  {t(
                    "Request a dedicated workspace for your school. A platform operator will review your request before you become its first administrator.",
                  )}
                </p>
                {!showForm ? (
                  <button
                    className="button primary"
                    onClick={() => setShowForm(true)}
                  >
                    {t("Request a school workspace")}
                    <ArrowRight size={16} />
                  </button>
                ) : (
                  <form className="onboarding-form" onSubmit={submit}>
                    <label>
                      {t("School name")}
                      <input
                        name="school_name"
                        value={schoolName}
                        onChange={(e) => setSchoolName(e.target.value)}
                        required
                        minLength={2}
                        maxLength={255}
                        autoComplete="organization"
                      />
                    </label>
                    <div className="onboarding-fields">
                      <label>
                        {t("Country")}
                        <select
                          name="country_code"
                          value={country}
                          onChange={(e) => setCountry(e.target.value)}
                          required
                        >
                          <option value="">{t("Choose a country")}</option>
                          {countries.map((option) => (
                            <option key={option.code} value={option.code}>
                              {option.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        {t("School timezone")}
                        <input
                          name="timezone"
                          value={timezone}
                          onChange={(e) => setTimezone(e.target.value)}
                          list="school-timezones"
                          required
                          maxLength={64}
                        />
                        <datalist id="school-timezones">
                          {[
                            ...new Set([
                              localTimezone,
                              "Africa/Tunis",
                              "Africa/Algiers",
                              "Africa/Casablanca",
                              "Europe/Paris",
                              "UTC",
                            ]),
                          ].map((zone) => (
                            <option key={zone} value={zone} />
                          ))}
                        </datalist>
                      </label>
                    </div>
                    <label>
                      {t("Tell us about your school")}
                      <textarea
                        name="notes"
                        value={notes}
                        onChange={(e) => setNotes(e.target.value)}
                        maxLength={2000}
                        rows={4}
                        placeholder={t(
                          "Your role at the school and any details that help us review your request.",
                        )}
                      />
                      <small>
                        {t(
                          "Optional · Only the platform team can review these details.",
                        )}
                      </small>
                    </label>
                    {!countries.length && (
                      <ErrorBox error="No countries are available yet. Contact the platform operator before submitting a school request." />
                    )}
                    <div className="onboarding-actions">
                      <button
                        className="button primary"
                        disabled={busy || !countries.length}
                        type="submit"
                      >
                        {t(busy ? "Submitting…" : "Submit school request")}
                      </button>
                      <button
                        className="button"
                        disabled={busy}
                        type="button"
                        onClick={() => setShowForm(false)}
                      >
                        {t("Cancel")}
                      </button>
                    </div>
                  </form>
                )}
              </section>
            )}
            {requests && (
              <button
                className="button"
                onClick={refresh}
                disabled={refreshing}
              >
                <RefreshCw size={15} className={refreshing ? "spin" : ""} />
                {t("Refresh request status")}
              </button>
            )}
          </section>
          <aside className="onboarding-card onboarding-help">
            <h2>{t("Joining an existing school?")}</h2>
            <p>
              {t(
                "Accept the invitation from your school administrator using this email address. Your school administrator assigns your role and school access.",
              )}
            </p>
            <p>
              {t(
                "After accepting an invitation, sign in again to open your school workspace.",
              )}
            </p>
            <div className="onboarding-steps">
              <h3>{t("How school setup works")}</h3>
              <ol>
                <li>{t("Submit your school details.")}</li>
                <li>{t("A platform operator reviews your request.")}</li>
                <li>
                  {t(
                    "Once approved, open your school as its first administrator.",
                  )}
                </li>
              </ol>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
