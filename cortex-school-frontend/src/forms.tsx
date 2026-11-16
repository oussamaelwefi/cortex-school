import { t, getLocale } from "./i18n";
import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { Schema, Data } from "./types";
import { initialValue } from "./lib.mjs";
export const label = (s: string) =>
  t(
    s
      .replace(/workos_/g, "")
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase()),
  );
export type Choices = Record<string, { value: string; label: string }[]>;
export function Field({
  name,
  schema: s,
  value,
  onChange,
  choices = {},
}: {
  name: string;
  schema: Schema;
  value: any;
  onChange: (v: any) => void;
  choices?: Choices;
}) {
  if (s.oneOf) {
    const key = s.discriminator || "type";
    const index = Math.max(
      0,
      s.oneOf.findIndex((x) =>
        x.properties?.[key]?.enum?.includes(value?.[key]),
      ),
    );
    return (
      <fieldset>
        <legend>{label(name)}</legend>
        <select
          aria-label={`${label(name)} type`}
          value={index}
          onChange={(e) => onChange(initialValue(s.oneOf![+e.target.value]))}
        >
          {s.oneOf.map((x, i) => (
            <option key={i} value={i}>
              {label(
                x.properties?.[key]?.enum?.[0] || x.name || `Option ${i + 1}`,
              )}
            </option>
          ))}
        </select>
        <Field
          name={name}
          schema={s.oneOf[index]}
          value={value}
          onChange={onChange}
          choices={choices}
        />
      </fieldset>
    );
  }
  if (s.type === "object")
    return (
      <fieldset>
        <legend>{label(name)}</legend>
        <div className="form-grid">
          {Object.entries(s.properties || {}).map(([k, v]) => (
            <Field
              key={k}
              name={k}
              schema={v}
              value={value?.[k]}
              onChange={(x) => onChange({ ...value, [k]: x })}
              choices={choices}
            />
          ))}
        </div>
      </fieldset>
    );
  if (s.type === "array")
    return (
      <fieldset>
        <legend>
          {label(name)}
          {s.required ? " *" : ""}
        </legend>
        {(value || []).map((v: any, i: number) => (
          <div className="array-row" key={i}>
            <Field
              name={name.replace(/s$/, "")}
              schema={{ ...s.items!, required: true }}
              value={v}
              onChange={(x) =>
                onChange(value.map((z: any, j: number) => (j === i ? x : z)))
              }
              choices={choices}
            />
            <button
              type="button"
              className="icon-button"
              aria-label={`Remove ${label(name)} ${i + 1}`}
              onClick={() =>
                onChange(value.filter((_: any, j: number) => i !== j))
              }
            >
              <Trash2 size={16} />
            </button>
          </div>
        ))}
        <button
          type="button"
          className="button subtle small"
          onClick={() => onChange([...(value || []), initialValue(s.items!)])}
        >
          <Plus size={14} /> Add {label(name.replace(/s$/, ""))}
        </button>
      </fieldset>
    );
  if (s.type === "boolean")
    return (
      <label className="switch-label">
        <span>{label(name)}</span>
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
        />
      </label>
    );
  const options =
    s.enum?.map((x) => ({ value: String(x), label: label(String(x)) })) ||
    choices[name] ||
    (name.endsWith("_ids") ? choices[name.slice(0, -1)] : undefined);
  const type =
    s.format === "date-time"
      ? "datetime-local"
      : s.format === "date"
        ? "date"
        : s.format === "time"
          ? "time"
          : s.format === "email" || name === "email"
            ? "email"
            : s.type === "integer" || s.type === "number"
              ? "number"
              : "text";
  const current =
    s.format === "date-time" && value && /Z$|[+-]\d\d:\d\d$/.test(value)
      ? new Date(value).toLocaleString("sv-SE").slice(0, 16).replace(" ", "T")
      : (value ?? "");
  return (
    <label
      className={`field ${["body", "content", "message", "notes", "reason", "rejection_reason"].includes(name) ? "wide" : ""}`}
    >
      <span>
        {label(name)}
        {s.required ? (
          <b aria-label={t("required")}> *</b>
        ) : (
          <small>{t(" optional")}</small>
        )}
      </span>
      {options ? (
        <select
          required={s.required}
          value={current}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">{t(`Select ${label(name)}`)}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : [
          "body",
          "content",
          "message",
          "notes",
          "reason",
          "rejection_reason",
        ].includes(name) ? (
        <textarea
          rows={4}
          required={s.required}
          minLength={s.min_length}
          maxLength={s.max_length}
          value={current}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          type={type}
          step={type === "number" ? "any" : undefined}
          required={s.required}
          minLength={s.min_length}
          maxLength={s.max_length}
          min={s.ge}
          max={s.le}
          pattern={s.pattern}
          placeholder={
            s.format === "uuid"
              ? t("Select or enter a record ID")
              : t(`Enter ${label(name)}`)
          }
          value={current}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  );
}
export function useDraft(s: Schema, seed?: Data) {
  return useState<any>(seed || initialValue(s));
}
