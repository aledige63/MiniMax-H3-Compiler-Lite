import { t } from "./i18n.js";

const markerPattern = /\[shot\s+(?<number>\d+)\]|(?<![\w#])#(?<tag>[a-zA-Z][a-zA-Z0-9_]*)\b/gi;
const timePrefix = /\b(?:a|at|al secondo)\s+(?<time>\d{1,2}:\d{2}(?:[.,]\d{1,3})?|\d+(?:[.,]\d{1,3})?)\s*(?:second[oi]|seconds?|s)?\s*(?:[,\-]\s*)?(?:(?:passa|passare|taglia|vai)\s+a\s+|(?:usa|use)\s+)?$/i;
const timeSuffix = /^\s*(?:a|at|al secondo)\s+(?<time>\d{1,2}:\d{2}(?:[.,]\d{1,3})?|\d+(?:[.,]\d{1,3})?)(?![\d.:])\s*(?:second[oi]|seconds?|s)?\s*[,\-]?\s*/i;

export function requestShotSequence(request) {
  const shots = [];
  let end = 0;
  for (const match of request.matchAll(markerPattern)) {
    const {number, tag} = match.groups;
    const previous = shots.at(-1);
    if (tag && previous && !previous.tag && !request.slice(end, match.index).trim()) {
      previous.tag = tag;
      end = match.index + match[0].length;
      continue;
    }
    if (number !== undefined && Number(number) !== shots.length + 1) throw new Error(t('Numera gli Shot in ordine da 1, senza salti o duplicati.'));
    const prefix = request.slice(end, match.index).match(timePrefix);
    end = match.index + match[0].length;
    const suffix = number !== undefined ? request.slice(end).match(timeSuffix) : null;
    if (prefix && suffix) throw new Error(t('Indica un solo tempo per ogni Shot.'));
    const timing = suffix || prefix;
    if (!timing && previous) throw new Error(t('Completa il tempo di inizio dello Shot precedente.'));
    const value = timing?.groups.time.replace(',', '.') || '0';
    const parts = value.split(':');
    const at = parts.length === 2 ? Number(parts[0]) * 60 + Number(parts[1]) : Number(value);
    if (parts.length === 2 && Number(parts[1]) >= 60) throw new Error(t('Usa il formato minuti:secondi.millisecondi.'));
    if (!previous && at !== 0) throw new Error(t('Shot 1 deve iniziare a zero secondi.'));
    if (previous && at <= previous.at_s) throw new Error(t('I tempi degli Shot devono essere crescenti.'));
    if (suffix) end += suffix[0].length;
    shots.push({number:shots.length + 1, at_s:at, tag});
  }
  return shots;
}

export function appendRequestShot(request, at, description, tag = '', duration = 15) {
  const shots = requestShotSequence(request);
  const existing = shots.length || (request.trim() ? 1 : 0);
  const previousTime = shots.at(-1)?.at_s || 0;
  if (!Number.isFinite(at) || at < 0 || at >= duration) throw new Error(t('Lo Shot deve iniziare prima della fine del cut.'));
  if (existing && at <= previousTime) throw new Error(t('Il nuovo Shot deve iniziare dopo quello precedente.'));
  if (!existing && at !== 0) throw new Error(t('Shot 1 deve iniziare a zero secondi.'));
  if (!description.trim()) throw new Error(t('Descrivi cosa accade nello Shot.'));
  if (/\[shot\b|(?<![\w#])#[a-z]/i.test(description)) throw new Error(t('Inserisci un solo Shot per volta. Scegli l’inquadratura dal menu dedicato.'));
  const milliseconds = Math.round(at * 1000);
  const minutes = String(Math.floor(milliseconds / 60000)).padStart(2, '0');
  const seconds = String(Math.floor(milliseconds % 60000 / 1000)).padStart(2, '0');
  const fraction = String(milliseconds % 1000).padStart(3, '0');
  const timing = existing ? ` At ${minutes}:${seconds}.${fraction},` : '';
  const preset = tag ? ` #${tag}` : '';
  const before = !shots.length && request.trim() ? `[Shot 1] ${request.trim()}` : request.trimEnd();
  return (before ? before + '\n\n' : '') + `[Shot ${existing + 1}]${timing}${preset} ${description.trim()}`;
}
