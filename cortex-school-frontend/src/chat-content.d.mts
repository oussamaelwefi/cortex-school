export type ChatContent = {
  subtitle: string;
  welcome: string;
  suggestions: string[];
  context: string;
};
export function getChatContent(role: string): ChatContent;
