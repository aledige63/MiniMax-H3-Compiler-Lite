import { t, tr } from "./i18n.js";

export function setExcluded(item, value) {
  if (value) item.excluded = true;
  else delete item.excluded;
}

export function includedSubjectChoices(units, selected, placeholder, characters = false) {
  const choices=[['',placeholder],...units.filter(u=>!u.excluded && (!characters || u.role==='character')).map(u=>[u.subject,`${u.name || 'Subject'} · Subject ${u.subject}`])];
  if(selected && !choices.some(([id])=>Number(id)===Number(selected))) choices.push([selected,tr`Subject ${selected} · escluso o non disponibile`]);
  return choices;
}

export function renderParticipation(item, kind, ui) {
  const {el,checkbox,changed} = ui;
  const box=el('div','cut-participation');
  box.append(checkbox(t('Escludi da questo cut'),Boolean(item.excluded),value=>{setExcluded(item,value);changed();},{draft:false}));
  box.append(el('p','field-help',kind==='unit'
    ? t('Con la spunta attiva il Subject resta disponibile, ma non entra nella compilazione. Le sue immagini sono usate solo se servono ad altri Subject inclusi o a guide attive.')
    : t('Con la spunta attiva la Picture resta disponibile, ma non entra nella compilazione. Escludi anche i Subject che la usano, oppure scegli per loro un’altra sorgente.')));
  return box;
}
