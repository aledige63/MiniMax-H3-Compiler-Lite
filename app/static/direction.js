import { tr } from "./i18n.js";

// Preview delle scelte esplicite; il modello le integra nella singola narrazione.
export function cameraPreview(camera, options) {
  if (!camera || !options) return '';
  const selected=key=>(options[key]||[]).find(v=>v.value===camera[key])?.en;
  const framing=[selected('framing'),selected('angle')].filter(Boolean).join(', ');
  const movement=selected('movement');
  const motion=movement ? ['The camera',movement,selected('amplitude'),selected('speed')].filter(Boolean).join(' ') : '';
  const target=camera.subject?` · <Subject ${camera.subject}>`:'';
  return [framing,motion].filter(Boolean).join('. ')+target;
}
export function hasCameraSelection(camera) {
  return Boolean(camera && (camera.framing || camera.angle || camera.movement || camera.notes?.trim()));
}

export function cameraTag(name) {
  return name.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^[^a-z]+/, "").slice(0, 60);
}

export function shotPresetSnapshots(request, presets) {
  const tags = new Set([...request.matchAll(/(?<![\w#])#([a-zA-Z][a-zA-Z0-9_]*)\b/g)].map(match => match[1]));
  const missing = [...tags].filter(tag => !presets.some(preset => preset.tag === tag));
  if (missing.length) throw new Error(tr`Inquadrature non disponibili nella libreria: ${missing.map(tag => "#" + tag).join(", ")}.`);
  return presets.filter(preset => tags.has(preset.tag));
}
