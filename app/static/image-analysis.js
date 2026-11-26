import { t } from "./i18n.js";

const defaults = {category:'auto', level:'compact', attribute:'', view:''};

export function selectedAnalysis(picture = {}, options) {
  const settings = {...defaults, ...picture.analysis};
  if (settings.category === 'auto') settings.category = options?.role_categories?.[picture.role] || picture.role;
  return settings;
}

export const sheetAnalysisKinds = new Set(['image_character_sheet', 'image_object_sheet']);

export function sheetAnalysisSupported(picture, options, kind) {
  const category = selectedAnalysis(picture, options).category;
  if (kind === 'image_object_sheet') return ['object','appearance'].includes(picture?.role) && category === 'held_item';
  if (kind === 'image_character_sheet') return ['identity','appearance'].includes(picture?.role) && category === 'character';
  return false;
}

export function setAnalysisChoice(picture, key, value) {
  const settings = {...defaults, ...picture.analysis, [key]:value};
  const saved = Object.fromEntries(Object.entries(settings).filter(([key,value]) => value !== defaults[key]));
  if (Object.keys(saved).length) picture.analysis = saved;
  else delete picture.analysis;
}

export function analysisLabel(settings, options) {
  if (!settings) return '';
  const category = options?.categories.find(item => item.value === settings.category)?.label || (settings.category === 'scale_reference' ? t('Riferimento dimensionale') : settings.category);
  return `${t(category).split(' · ')[0]} · ${settings.level[0].toUpperCase() + settings.level.slice(1)}${settings.attribute ? ` · ${settings.attribute}` : ''}${settings.view ? ` · ${t(options?.views.find(item => item.value === settings.view)?.label) || settings.view}` : ''}`;
}

export function analysisProposals(jobs, picture, options) {
  const selection = picture && selectedAnalysis(picture,options);
  const latest = new Map();
  for (const job of jobs) {
    // I lavori attivi rimangono visibili e annullabili anche cambiando categoria.
    const pending = ['queued','running'].includes(job.status);
    if (job.analysis && selection && !pending && ['category','attribute','view'].some(key=>job.analysis[key] !== selection[key])) continue;
    const profile = job.analysis && JSON.stringify(['category','level','attribute','view'].map(key=>job.analysis[key]));
    latest.set(job.kind + (profile ? ':' + profile : ''),job);
  }
  return [...latest.values()];
}

export function renderAnalysisControls(picture, options, ui) {
  const {el, field, selectField, changed, openSubjects, button} = ui;
  const box = el('section','image-analysis-settings');
  box.setAttribute('aria-label',t('Impostazioni di analisi della Picture'));
  box.append(el('h3','',t('Analisi dell’immagine')));
  if (!options) {
    box.append(el('p','field-help',t('Caricamento delle categorie di analisi…')));
    return box;
  }
  const settings = () => ({...defaults, ...picture.analysis});
  const choices = key => options[key].map(item => [item.value,t(item.label)]);
  const help = el('p','field-help');
  const detail = button(t('Apri i dettagli fisici nei Subject'),'button subtle',openSubjects);
  const updateHint = () => {
    const category = selectedAnalysis(picture,options).category;
    const hints = {
      scale_reference:t('La descrizione riguarda il rapporto dimensionale visibile. Scegli poi questa foto in Dimensioni e scala del Subject; nessuna misura in centimetri viene dedotta automaticamente.'),
      body_mark:t('Collega poi questa Picture nei Dettagli fisici e modifiche del personaggio, indicando la posizione.'),
      replacement:t('Collega poi questa Picture nei Dettagli fisici e modifiche del personaggio con operazione Sostituzione e posizione sul corpo.'),
      accessory:t('La descrizione riguarda solo gli accessori indossati. Scegli esplicitamente chi li indossa e come usarli nella richiesta.'),
      held_item:t('La descrizione riguarda solo l’oggetto. Il portatore e l’eventuale Subject autonomo vanno scelti esplicitamente.'),
      attribute_transfer:t('Specifica l’attributo da isolare, per esempio acconciatura o colore del rossetto. Il destinatario si sceglie a parte.'),
      body_shape:t('La descrizione riguarda solo corporatura e proporzioni. Dichiara nella richiesta a chi applicarle.'),
      style_transfer:t('La descrizione riguarda la tecnica visiva. Per usarla come guida, scegli il ruolo H3 Guida di stile.'),
      clothing:t('La descrizione riguarda solo gli abiti. Associali esplicitamente al personaggio con una sorgente Abito.'),
      footwear:t('La descrizione riguarda solo le calzature. Associale esplicitamente al personaggio con una sorgente Scarpe.')
    };
    help.textContent = (hints[category] || t('La categoria segue ciò che vuoi descrivere e non crea Subject.')) + t(' La descrizione attuale cambia solo applicando una proposta; cambiare livello non avvia inferenze.');
    detail.hidden = !['body_mark','replacement'].includes(category);
  };
  const change = (key,value) => {setAnalysisChoice(picture,key,value);updateHint();changed();};
  const first = el('div','two-fields');
  first.append(selectField(t('Categoria di analisi'),settings().category,choices('categories'),value=>change('category',value),{draft:false}),
    selectField(t('Livello di descrizione'),settings().level,choices('levels'),value=>change('level',value),{draft:false}));
  const second = el('div','two-fields');
  second.append(field(t('Attributo o dettaglio da isolare · facoltativo'),settings().attribute,value=>change('attribute',value),{draft:false,placeholder:t('Obbligatorio per Attributo specifico, es. acconciatura')}),
    selectField(t('Vista dell’immagine · facoltativa'),settings().view,choices('views'),value=>change('view',value),{draft:false}));
  box.append(first,second,help,detail);
  updateHint();
  return box;
}
