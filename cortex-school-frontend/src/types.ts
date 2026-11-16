export type Data = Record<string, any>;
export type SchoolMemberIdentity = {
  id: string;
  name: string;
  email: string;
};
export type Schema = {
  type?: string;
  format?: string;
  enum?: any[];
  default?: any;
  required?: boolean;
  nullable?: boolean;
  properties?: Record<string, Schema>;
  items?: Schema;
  oneOf?: Schema[];
  discriminator?: string;
  min_length?: number;
  max_length?: number;
  ge?: number;
  le?: number;
  pattern?: string;
  name?: string;
};
export type Param = Schema & { name: string; in: string };
export type Endpoint = {
  id: string;
  title: string;
  method: string;
  path: string;
  module: string;
  role: string;
  params: Param[];
  body: Schema | null;
  upload: boolean;
  timeoutMs?: number;
};
export type Role = "admin" | "teacher" | "guardian";
