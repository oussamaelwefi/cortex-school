// Component tests choose English explicitly; the application defaults to French.
const preferences = new Map([["cortex-language", "en"]]);
globalThis.localStorage = {
  getItem: (key) => preferences.get(String(key)) ?? null,
  setItem: (key, value) => {
    preferences.set(String(key), String(value));
  },
  removeItem: (key) => {
    preferences.delete(String(key));
  },
  clear: () => {
    preferences.clear();
  },
};
