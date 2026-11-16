import { createContext, useContext } from "react";
import raw from "./contracts.json";
import type { Data, Endpoint } from "./types";
import { endpointUrl, errorMessage } from "./lib.mjs";
export const endpoints = raw as Endpoint[];
export const findEndpoint = (method: string, path: string) =>
  endpoints.find(
    (e) =>
      e.method === method &&
      e.path.replace(/\/$/, "") === path.replace(/\/$/, ""),
  )!;
export type Api = (
  e: Endpoint,
  params?: Data,
  body?: any,
  file?: File,
) => Promise<any>;
export const ApiContext = createContext<Api>(async () => {});
export const useApi = () => useContext(ApiContext);
export const sessionRejectedMessage =
  "Your school session could not be verified. Sign in again to continue.";
const sessionRejected = (response: Response) =>
  response.status === 401 &&
  /^Bearer\b/i.test(response.headers.get("WWW-Authenticate") ?? "");

export function makeApi(
  getToken: (forceRefresh?: boolean) => Promise<string | undefined>,
  onSessionRejected: (requestId: string) => void,
): Api {
  let refresh: Promise<string | undefined> | undefined;

  async function refreshToken(rejectedToken: string) {
    const latestToken = await getToken();
    if (latestToken !== rejectedToken) return latestToken;
    refresh ??= getToken(true).finally(() => {
      refresh = undefined;
    });
    return refresh;
  }

  function rejectSession(requestId = "") {
    onSessionRejected(requestId);
    return new Error(sessionRejectedMessage);
  }

  return async (e, params = {}, body, file) => {
    const token = await getToken();
    if (!token) throw rejectSession();
    const headers: Record<string, string> = {};
    let payload: BodyInit | undefined;
    if (file) {
      const form = new FormData();
      form.append("file", file);
      payload = form;
    } else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    async function send(accessToken: string) {
      try {
        return await fetch(
          endpointUrl(import.meta.env.VITE_API_BASE_URL || "/api", e, params),
          {
            method: e.method,
            headers: { ...headers, Authorization: `Bearer ${accessToken}` },
            body: payload,
            signal: AbortSignal.timeout(e.timeoutMs ?? 30000),
          },
        );
      } catch {
        throw new Error(
          "Unable to reach the school server. Check that the backend is running and try again.",
        );
      }
    }

    let response = await send(token);
    if (sessionRejected(response)) {
      const requestId = response.headers.get("X-Request-ID") ?? "";
      let nextToken: string | undefined;
      try {
        nextToken = await refreshToken(token);
      } catch {
        throw new Error(
          "Unable to refresh your school session. Please try again.",
        );
      }
      if (!nextToken || nextToken === token) throw rejectSession(requestId);
      // The Bearer challenge comes from the auth dependency before the handler runs.
      response = await send(nextToken);
      if (sessionRejected(response))
        throw rejectSession(response.headers.get("X-Request-ID") ?? requestId);
    }
    if (response.status === 204) return null;
    if (response.ok && response.headers.get("Content-Type")?.startsWith("application/pdf"))
      return response.blob();
    const result = await response.json().catch(() => null);
    if (!response.ok)
      throw new Error(
        errorMessage(result, response.status) +
          (response.headers.get("X-Request-ID")
            ? ` (Request ${response.headers.get("X-Request-ID")})`
            : ""),
      );
    return result;
  };
}
