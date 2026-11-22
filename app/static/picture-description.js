import {t, tr} from './i18n.js';
import {analysisLabel, selectedAnalysis} from './image-analysis.js';

export const pictureTasks = new Set(['image_analyze', 'image_character_sheet', 'description_translate']);
const pending = job => ['queued','running'].includes(job.status);
export const pictureTaskLabel = kind => t(({image_analyze:'Immagine singola',
  image_character_sheet:'Character sheet',description_translate:'Traduzione in inglese'})[kind] || 'Analisi');

// Choose one result, never promote an older proposal after a dismissal or a
// profile change. Legacy receipts without a profile remain readable in history.
export function pictureProposalView(jobs, picture, options, mode) {
  const matching = jobs.filter(job => job.target_id === picture.id && pictureTasks.has(job.kind));
  const recent = new Set(matching.slice(-3).map(job=>job.id));
  const all = matching.filter(job=>recent.has(job.id) || pending(job));
  const selection = selectedAnalysis(picture,options);
  let current = all.filter(pending).at(-1) || all.at(-1) || null;
  if (current && !pending(current)) {
    const mismatch = current.kind !== 'description_translate' && (current.kind !== mode || !current.analysis
      || ['category','level','attribute','view'].some(key => current.analysis[key] !== selection[key]));
    if (current.discarded || current.applied || current.stale || current.status === 'cancelled' || mismatch) current = null;
  }
  return {current,history:all.filter(job=>job !== current).reverse()};
}

export function renderPictureProposals(panel, picture, jobs, mode, options, state, ui) {
  const {el,serverButton,apply,dismiss,cancel,diagnostic,canApply,locked} = ui;
  const {current,history} = pictureProposalView(jobs,picture,options,mode);
  const dismissing = current && state.pendingDismiss?.has(current.id);
  panel.replaceChildren();
  panel.hidden = !current && !history.length && !state.notice;
  if(state.notice) {
    const notice=el('p',state.noticeError ? 'issues' : 'field-help',state.notice);
    notice.tabIndex=-1;notice.dataset.discardNotice='true';
    notice.setAttribute('role',state.noticeError ? 'alert' : 'status');panel.append(notice);
  }
  if (current && !dismissing) {
    const box = el('div','description-proposal');
    box.append(el('h4','',pending(current) ? t('Analisi in corso') : current.result?.text ? t('Proposta da rivedere') : t('Analisi non riuscita')),
      el('p','field-help',`${pictureTaskLabel(current.kind)}${current.analysis ? ' · '+analysisLabel(current.analysis,options) : ''}`));
    if (pending(current)) {
      box.append(el('p','field-help',t('La descrizione attuale resta modificabile.')),
        serverButton(t('Annulla operazione'),()=>cancel(current)));
    } else {
      if (current.result?.text) {
        box.append(el('p','proposed-description',current.result.text));
        for (const warning of current.result.warnings || []) box.append(el('p','analysis-warning',diagnostic(warning)));
        const use = serverButton(t('Usa questa descrizione'),()=>apply(current),'apply');
        use.dataset.job = current.id; use.disabled = !canApply(current);
        box.append(use);
        if (!locked && !canApply(current)) box.append(el('p','field-help',t('Salva la bozza per verificare che questa proposta sia ancora attuale.')));
      } else box.append(el('p','issues',ui.error(current)));
      const discard = serverButton(t('Scarta'),()=>dismiss(current),'dismiss');
      discard.disabled = locked;
      box.append(discard);
    }
    panel.append(box);
  }
  if (history.length) {
    const archive = el('details','description-history');
    archive.open = state.historyOpen || false;
    archive.append(el('summary','',tr`Storico delle proposte (${history.length})`));
    archive.addEventListener('toggle',()=>{state.historyOpen=archive.open;});
    const list=el('div','description-history-list');
    for (const job of history) {
      const item=el('details','description-history-item');
      item.open=state.openJobs?.has(job.id) || false;
      item.addEventListener('toggle',()=>{
        state.openJobs ??= new Set();
        if(item.open)state.openJobs.add(job.id);else state.openJobs.delete(job.id);
      });
      const status=job.discarded ? t('Scartata') : job.applied ? t('Applicata') : pending(job) ? t('In corso')
        : job.stale ? t('Riferimento modificato') : job.status==='failed' ? t('Analisi non riuscita') : t('Precedente');
      item.append(el('summary','',`${pictureTaskLabel(job.kind)} · ${job.analysis?.level || t('Profilo precedente')} · ${status}`));
      if(job.model)item.append(el('p','field-help',job.model));
      if(job.result?.text)item.append(el('p','proposed-description',job.result.text));
      for(const warning of job.result?.warnings || [])item.append(el('p','analysis-warning',diagnostic(warning)));
      if(job.result?.issues?.length)item.append(el('p','issues',ui.error(job)));
      if(pending(job))item.append(serverButton(t('Annulla operazione'),()=>cancel(job)));
      list.append(item);
    }
    archive.append(list);panel.append(archive);
  }
}
