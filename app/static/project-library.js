import { t, tr } from "./i18n.js";

import {unitPictureIds} from './reference-menu.js';

export function renderLibraryRows(library, state, ui) {
  const {el,button,choose,setTrash} = ui;
  const rows = [];
  const hiddenPictures = new Set((library.trashed_pictures || []).map(p=>p.id));
  for (const kind of ['unit','picture']) {
    const key = kind === 'unit' ? 'units' : 'pictures';
    for (const item of library[(state.trashed ? 'trashed_' : '') + key] || []) {
      const name = item.name || item.media?.display_name || (kind === 'unit' ? t('Subject senza nome') : t('Immagine senza nome'));
      const row = el('div','library-row');
      const label = el('div','',name);
      label.append(el('small','',kind === 'unit'
        ? `${item.subject ? tr`Subject ${item.subject} nella scena` : t('Numero assegnato al riuso nella scena')} · ${ui.roleLabel(item.role)}`
        : item.description_en || t('Descrizione da completare')));
      row.append(label);
      const actions = el('div','navigation-actions');
      if (!state.trashed) {
        const blocked = kind === 'unit' && unitPictureIds(item).some(id=>hiddenPictures.has(id));
        const exists = kind === 'unit' ? state.unitIds.has(item.id) : state.pictureIds.has(item.id);
        const use = button(`${exists ? t('Ricarica') : t('Usa')} ${kind === 'unit' ? 'Subject' : 'immagine'}`,'button secondary small',()=>choose(kind,item));
        use.disabled = state.busy || blocked || !state.canReuse;
        actions.append(use);
        if (blocked) label.append(el('small','', t('Ripristina prima le immagini collegate dal Cestino della libreria.')));
      }
      const trash = button(state.trashed ? t('Ripristina') : t('Sposta nel cestino'),'button subtle small',()=>setTrash(kind,item,!state.trashed));
      trash.setAttribute('aria-label',`${state.trashed ? t('Ripristina') : t('Cestina')} ${kind === 'unit' ? 'Subject' : 'immagine'} ${name}`);
      trash.disabled = state.busy;
      actions.append(trash); row.append(actions); rows.push(row);
    }
  }
  if (!rows.length) rows.push(el('p','empty-list',state.trashed ? t('Il cestino della libreria è vuoto.') : t('Non ci sono riferimenti nella libreria.')));
  return rows;
}
