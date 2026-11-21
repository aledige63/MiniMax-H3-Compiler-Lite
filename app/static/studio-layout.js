import { diagnostic, t, tr } from "./i18n.js";

// Navigazione e dimensioni dei pannelli: solo preferenze locali, nessuna API.
const labels = {images:'Immagini', subjects:'Subject', direction:'Regia', dialogues:'Dialoghi', audio:'Audio', video:'Video', continuity:'Continuità', versions:'Versioni', settings:'Impostazioni'};
const preferenceKey = 'minimax.studio.layout';
const clamp = (value, min, max, fallback) => Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback;

export function sectionCounts(draft, view) {
  const camera = draft?.camera;
  return {images:draft?.pictures?.length || 0, subjects:draft?.active_units?.length || 0,
    dialogues:draft?.dialogues?.length || 0, audio:draft?.audio_references?.length || 0,
    video:draft?.videos?.length || 0, versions:view?.versions?.length || 0,
    direction:camera && ['framing','angle','movement','notes','subject'].some(key => camera[key]) ? 1 : 0,
    continuity:draft?.continuity?.mode && draft.continuity.mode !== 'none' ? 1 : 0, settings:0};
}

export function issueSections(issues = []) {
  const groups = Object.fromEntries(Object.keys(labels).map(key => [key, []]));
  for (const issue of issues) {
    const key = /^(?:Picture|Immagin)/i.test(issue) ? 'images' : /^Subject|dettagli[oa] fisic/i.test(issue) ? 'subjects'
      : /^Battuta|Dialogh/i.test(issue) ? 'dialogues' : /^Audio|Suoni|Rumori/i.test(issue) ? 'audio'
      : /^Video/i.test(issue) ? 'video' : /continuità|contesto|raccordo/i.test(issue) ? 'continuity'
      : /regia|camera|inquadratura/i.test(issue) ? 'direction' : null;
    if (key) groups[key].push(issue);
  }
  return groups;
}

export function createStudioLayout(doc, win = window) {
  const get = id => doc.getElementById(id);
  const buttons = [...doc.querySelectorAll('[data-studio-section]')];
  const panels = [...doc.querySelectorAll('[data-studio-panel]')];
  const editor = get('element-panels');
  let preferences = {};
  try { preferences = JSON.parse(win.localStorage.getItem(preferenceKey)) || {}; } catch {}
  const state = {section:Object.hasOwn(labels,preferences.section) ? preferences.section : 'subjects',
    results:clamp(preferences.results,32,52,42), proposal:clamp(preferences.proposal,35,70,55)};
  const scrolls = new Map();
  let cutId = null;
  const save = () => { try { win.localStorage.setItem(preferenceKey,JSON.stringify(state)); } catch {} };

  function selectSection(key, {focus = false} = {}) {
    if (!Object.hasOwn(labels,key)) return;
    if (state.section !== key) {
      scrolls.set(state.section, editor.scrollTop);
      state.section = key;
      editor.scrollTop = scrolls.get(key) || 0;
    }
    for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.studioSection === key));
    for (const panel of panels) {
      panel.hidden = panel.dataset.studioPanel !== key;
      if (!panel.hidden && panel.tagName === 'DETAILS') panel.open = true;
    }
    get('studio-section').value = key;
    // Applicare dopo hidden ripristina lo scroll anche per sezioni più lunghe.
    editor.scrollTop = scrolls.get(key) || 0;
    if (focus) editor.focus({preventScroll:true});
    save();
  }
  buttons.forEach(button => button.addEventListener('click', () => selectSection(button.dataset.studioSection)));
  get('studio-section').addEventListener('change', event => selectSection(event.target.value));
  editor.addEventListener('scroll', () => scrolls.set(state.section,editor.scrollTop), {passive:true});

  function setSize(kind, value, persist = true) {
    const columns = kind === 'results';
    state[kind] = clamp(value, columns ? 32 : 35, columns ? 52 : 70, columns ? 42 : 55);
    get('application').style.setProperty(columns ? '--results-share' : '--proposal-share', state[kind] + '%');
    get(columns ? 'results-resize' : 'prompt-resize').setAttribute('aria-valuenow',String(Math.round(state[kind])));
    if (persist) save();
  }
  for (const [id, kind, vertical] of [['results-resize','results',true], ['prompt-resize','proposal',false]]) {
    const separator = get(id);
    let dragging = false;
    separator.addEventListener('keydown', event => {
      const deltas = vertical ? {ArrowLeft:2,ArrowRight:-2} : {ArrowUp:-2,ArrowDown:2};
      let value = state[kind];
      if (event.key in deltas) value += deltas[event.key];
      else if (event.key === 'Home') value = vertical ? 32 : 35;
      else if (event.key === 'End') value = vertical ? 52 : 70;
      else return;
      event.preventDefault(); setSize(kind,value);
    });
    const move = event => {
      if (!dragging) return;
      const rect = (vertical ? get('studio-workspace') : get('results-column')).getBoundingClientRect();
      const size = vertical ? rect.width : rect.height;
      if (!size) return;
      setSize(kind,100 * (vertical ? rect.right - event.clientX : event.clientY - rect.top) / size,false);
    };
    const stop = () => {
      if (!dragging) return;
      dragging = false; doc.body.classList.remove('resizing-columns','resizing-prompts');
      doc.removeEventListener('pointermove', move); doc.removeEventListener('pointerup',stop); doc.removeEventListener('pointercancel',stop);
      win.removeEventListener('blur',stop); save();
    };
    separator.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault(); dragging = true;
      doc.body.classList.add(vertical ? 'resizing-columns' : 'resizing-prompts');
      doc.addEventListener('pointermove',move);doc.addEventListener('pointerup',stop);doc.addEventListener('pointercancel',stop);win.addEventListener('blur',stop);
    });
    separator.addEventListener('dblclick', () => setSize(kind,vertical ? 42 : 55));
  }
  setSize('results',state.results,false);setSize('proposal',state.proposal,false);
  selectSection(state.section);

  return {selectSection, update(draft, view) {
    if (cutId !== view?.id) { cutId = view?.id; scrolls.clear(); editor.scrollTop = 0; }
    const counts = sectionCounts(draft,view), issues = issueSections(view?.catalogue_issues);
    for (const option of get('studio-section').options || []) {
      const key = option.value;
      option.textContent = t(labels[key]) + (counts[key] ? ` · ${counts[key]}` : '') + (issues[key]?.length ? t(' · da completare') : '');
    }
    for (const button of buttons) {
      const key = button.dataset.studioSection, count = counts[key], warnings = issues[key];
      button.querySelector('[data-studio-count]').textContent = count ? String(count) : '';
      button.querySelector('.studio-warning').hidden = warnings.length === 0;
      button.title = warnings.length ? warnings.map(diagnostic).join('\n') : t(labels[key]);
      button.setAttribute('aria-label',t(labels[key]) + (count ? ` · ${count}` : '') + (warnings.length ? tr` · ${warnings.length} controlli da completare` : ''));
    }
  }};
}
