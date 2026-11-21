import { english, serverTemplates } from "./en.js?v=1";

let language = "it";

export function setUiLanguage(value) {
  language = value === "en" ? "en" : "it";
}

export function uiLanguage() { return language; }

// Only call these helpers with application text. The substitutions are values
// supplied by the user, the archive or the model and are kept as-is.
export function t(value) {
  if (language !== "en" || typeof value !== "string") return value;
  const key = value.trim();
  return Object.hasOwn(english, key) ? value.replace(key, () => english[key]) : value;
}

export function tr(parts, ...values) {
  if (language === "it") return parts.reduce((text, part, i) => text + (i ? String(values[i - 1]) : "") + part, "");
  const key = parts.reduce((text, part, i) => text + (i ? `{${i - 1}}` : "") + part, "");
  return t(key).replace(/\{(\d+)\}/g, (match, i) => i < values.length ? String(values[i]) : match);
}

const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const diagnosticPatterns = [...serverTemplates]
  .sort((a, b) => b.length - a.length)
  .map(key => {
    const parts = key.split(/(\{\w+\})/);
    const variables = parts.filter(part => /^\{\w+\}$/.test(part));
    const pattern = parts.map((part, index) => index % 2 ? "(.+?)" : escapeRegex(part)).join("");
    return { key, variables, pattern: new RegExp(`^${pattern}$`) };
  });

export function diagnostic(value) {
  if (language !== "en" || typeof value !== "string") return value;
  return value.split("\n").map(line => {
    const exact = t(line);
    if (exact !== line) return exact;
    for (const { key, variables, pattern } of diagnosticPatterns) {
      const match = pattern.exec(line);
      if (!match) continue;
      const captured = Object.fromEntries(variables.map((name, i) => [name, match[i + 1]]));
      return english[key].replace(/\{\w+\}/g, name => {
        const value = captured[name] ?? name;
        return name === "{field}" || name === "{operator}" ? t(value) : value;
      });
    }
    // Validation may prefix a generic field error with an archive reference.
    const prefixed = line.match(/^((?:Subject|Picture|Battuta|Audio|Video) .+) — (.+)$/);
    if (prefixed) {
      const localized = diagnostic(prefixed[2]);
      if (localized !== prefixed[2]) return prefixed[1] + " — " + localized;
    }
    return line;
  }).join("\n");
}

// Capture static labels before rendering project data. On a later language
// change, skip nodes that a renderer has taken over.
export function captureStaticLabels(doc) {
  const entries = [];
  const walker = doc.createTreeWalker(doc.body, 4);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.parentElement?.closest("script, style, noscript, body [lang], [data-project-text]")) continue;
    if (Object.hasOwn(english, node.data.trim())) entries.push({
      read: () => node.data, write: value => { node.data = value; }, original: node.data
    });
  }
  for (const attr of ["aria-label", "title", "placeholder", "alt"]) {
    for (const node of doc.querySelectorAll(`[${attr}]`)) {
      const original = node.getAttribute(attr);
      if (Object.hasOwn(english, original.trim())) entries.push({
        read: () => node.getAttribute(attr), write: value => node.setAttribute(attr, value), original
      });
    }
  }
  return () => {
    for (const entry of entries) {
      if (entry.read() !== entry.original && entry.read() !== entry.previous) continue;
      entry.previous = t(entry.original);
      entry.write(entry.previous);
    }
  };
}
