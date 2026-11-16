export function endpointUrl(base, endpoint, values = {}) {
  const path = endpoint.path.replace(/\{([^}]+)\}/g, (_, key) => {
    if (values[key] === undefined || values[key] === "")
      throw new Error(`Choose ${key.replaceAll("_", " ")} to continue.`);
    return encodeURIComponent(values[key]);
  });
  const query = new URLSearchParams();
  for (const param of endpoint.params) {
    if (
      param.in === "query" &&
      values[param.name] !== undefined &&
      values[param.name] !== "" &&
      values[param.name] !== null
    ) {
      const value = values[param.name];
      if (Array.isArray(value))
        value.forEach((v) => query.append(param.name, String(v)));
      else query.set(param.name, String(value));
    }
  }
  return base.replace(/\/$/, "") + path + (query.size ? "?" + query : "");
}
export function errorMessage(body, status) {
  const detail = body?.detail;
  if (Array.isArray(detail))
    return detail
      .map(
        (e) =>
          `${(e.loc || []).filter((v) => v !== "body").join(" → ")}: ${e.msg}`,
      )
      .join("\n");
  if (typeof detail === "string") return detail;
  return body?.message || `Request failed (${status}). Please try again.`;
}
export function rolesFromClaims(claims) {
  const roles = new Set([claims.role, ...(claims.roles || [])]);
  return [
    ...((claims.permissions || []).includes("school:manage") ? ["admin"] : []),
    ...(roles.has("teacher") ? ["teacher"] : []),
    ...(roles.has("guardian") ? ["guardian"] : []),
  ];
}
export function initialValue(s) {
  if (s.default !== undefined) return s.default;
  if (s.oneOf) return initialValue(s.oneOf[0]);
  if (s.type === "object")
    return Object.fromEntries(
      Object.entries(s.properties || {})
        .filter(([, v]) => v.required || v.default !== undefined)
        .map(([k, v]) => [k, initialValue(v)]),
    );
  if (s.type === "array") return [];
  if (s.type === "boolean") return false;
  if (s.enum?.length === 1) return s.enum[0];
  return "";
}
export function cleanPayload(value, schema) {
  if (schema.oneOf) {
    const key = schema.discriminator || "type";
    const choice =
      schema.oneOf.find((s) =>
        s.properties?.[key]?.enum?.includes(value?.[key]),
      ) || schema.oneOf[0];
    return cleanPayload(value, choice);
  }
  if (schema.type === "object")
    return Object.fromEntries(
      Object.entries(value || {})
        .filter(
          ([k, v]) =>
            schema.properties?.[k] &&
            !(v === "" && !schema.properties[k].required),
        )
        .map(([k, v]) => [k, cleanPayload(v, schema.properties[k])]),
    );
  if (schema.type === "array")
    return value.map((v) => cleanPayload(v, schema.items));
  if (schema.format === "date-time" && value)
    return new Date(value).toISOString();
  if (schema.type === "integer" || schema.type === "number")
    return value === "" && schema.nullable ? null : Number(value);
  return value;
}
