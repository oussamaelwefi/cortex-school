import type { Endpoint, Schema, Data } from "./types";
export function endpointUrl(
  base: string,
  endpoint: Endpoint,
  values?: Data,
): string;
export function errorMessage(body: any, status: number): string;
export function rolesFromClaims(claims: Data): string[];
export function initialValue(schema: Schema): any;
export function cleanPayload(value: any, schema: Schema): any;
