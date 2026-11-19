import type { Role } from "./types";

export function schoolChatPayload(
  role: Role,
  language: "fr" | "en",
  conversation: { id: string; role: "user" | "assistant"; text: string }[],
) {
  const recent = conversation
    .filter((message) => message.id !== "welcome")
    .slice(-12);
  const included: string[] = [];
  let size = 0;
  for (const message of [...recent].reverse()) {
    const turn = `${message.role === "user" ? "User" : "Assistant"}: ${message.text}`;
    if (included.length && size + turn.length > 26000) break;
    included.unshift(turn);
    size += turn.length + 2;
  }
  const message =
    recent.length === 1
      ? recent[0].text
      : `Continue this conversation. Answer the latest user message.\n\n${included.join("\n\n")}`;
  return { message, role, language };
}
