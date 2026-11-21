import { newCommandId } from "./command-id.js";
import { visibleReferenceTokens, associatePicture, definitionPicture, subjectDefinition, imageGuideRoles, unitPictureIds } from "./reference-menu.js?v=scale-reference-role";
import { renderPhysicalDetails } from "./physical-details.js?v=scale-reference-role";
import { renderSubjectScale } from './subject-scale.js?v=scale-reference-role';
import { createStudioLayout } from "./studio-layout.js";
import { selectedAnalysis, analysisLabel, analysisProposals, renderAnalysisControls } from "./image-analysis.js?v=scale-reference-role";
import {renderLibraryRows} from './project-library.js';
import {renderParticipation,includedSubjectChoices} from './cut-participation.js';
import { cameraPreview, hasCameraSelection, cameraTag, shotPresetSnapshots } from "./direction.js?v=saved-shots";
import { applyUploadedAudio } from "./audio-upload.js";
import { audioTimeline } from "./audio-timeline.js";
import { requestShotSequence, appendRequestShot } from "./request-shots.js";
import { createUserSettings, serviceFor, modelLabel, eligibleModels } from "./user-settings.js?v=llm-connections";
import { createAppearance } from "./appearance.js?v=1";
import { diagnostic, t, tr, uiLanguage } from "./i18n.js";

const $ = (id) => document.getElementById(id);
const clone = (value) => structuredClone(value);
let timelineSeconds = new Intl.NumberFormat("it", { maximumFractionDigits: 3 });
let workspace = null;
let draft = null;
let draftTick = 0;
let draftDirty = false;
let commandBusy = false;
let manualDirty = false;
let manualBaseId = null;
let localError = null;
let pending = null;
let pollTimer = null;
let localBackup = null;
let defaultModel = null;
let compileFailure = null;
let projects = [];
let csrf = null;
let accessState = null;
let currentCutId = new URL(location.href).searchParams.get("cut");
let navigationBusy = false;
let closeCurrentDialog = () => {};
let assistanceModels = [];
let modelSettings = { revision: 0, text_model: null, vision_model: null };
let asrState = { available: false, message: t("ASR opzionale non configurato.") };
let assistanceTimer = null;
let refreshBusy = false;
let directionOptions = null;
let voiceOptions = null;
let imageAnalysisOptions = null;
let editingCameraPreset = null;
let connectionAvailable = null;
const lockedCutControls = new Set();
createAppearance(document, window, refreshLanguage);
timelineSeconds = new Intl.NumberFormat(uiLanguage(), { maximumFractionDigits: 3 });
let { roles, attributes, pictureRoles, videoRoles, cameraPhases, dialogueDeliveries, narratorVoices, languages, continuityModes } = makeUiChoices();
const studioLayout = createStudioLayout(document);
const userSettings = createUserSettings(document, { request, commandId: newCommandId,
  reloadModels: () => loadAssistance(false), accessChanged: async value => {
    csrf = value.csrf;
    accessState = await request('/api/access/status');
    $("logout").hidden = !accessState.authentication_required;
  } });

function makeUiChoices() {
  const roles = [["character", t("Personaggio")], ["environment", t("Ambiente")], ["object", t("Oggetto")]];
  const attributes = [["identity", t("Identità")], ["appearance", t("Aspetto")], ["outfit", t("Abito")], ["shoes", t("Scarpe")], ["environment", t("Ambiente")], ["object", t("Oggetto")]];
  const pictureRoles = [...attributes,["scale_reference",t("Riferimento dimensionale")],["style",t("Guida di stile")],["spatial_map",t("Mappa spaziale")],["composition_previz",t("Previz / composizione")],["initial_composition",t("Composizione iniziale")],["frame_anchor",t("Frame anchor esplicito")]];
  const videoRoles = [['continuation',t('Continuazione')],['camera',t('Guida sola camera')],['subject_motion',t('Guida movimento Subject')],['camera_and_subject_motion',t('Guida camera + Subject')]];
  const cameraPhases = [["as_requested",t("Come indicato nella richiesta")],["throughout",t("Per tutto il cut")],["opening",t("All’apertura")],["during_dialogue",t("Durante una battuta")],["after_dialogue",t("Dopo una battuta")]];
  const dialogueDeliveries = [["on_screen", t("In campo")], ["off_screen", t("Fuori campo")], ["narrator", t("Voce narrante")]];
  const narratorVoices = [["", t("Non specificata")], ["male", t("Maschile")], ["female", t("Femminile")]];
  const languages = [["English", t("Inglese")], ["Italian", t("Italiano")], ["French", t("Francese")], ["German", t("Tedesco")], ["Spanish", t("Spagnolo")]];
  const continuityModes = [["none", t("Nessuna continuità")], ["video_reference", t("Video reference in uno slot H3")], ["tail_frames", t("Frame di coda / percorso pixel")], ["latent", t("Motion context latente")]];
  return { roles, attributes, pictureRoles, videoRoles, cameraPhases, dialogueDeliveries, narratorVoices, languages, continuityModes };
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(text, className, action) {
  const node = el("button", className, text);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function field(label, value, change, options = {}) {
  const wrap = el("label", "field");
  wrap.append(el("span", "", label));
  const input = document.createElement(options.multiline ? "textarea" : "input");
  input.value = value ?? "";
  if (options.multiline) input.rows = options.rows || 2;
  else input.type = options.type || "text";
  if (options.placeholder) input.placeholder = options.placeholder;
  if (options.min !== undefined) input.min = options.min;
  if (options.max !== undefined) input.max = options.max;
  input.addEventListener("input", () => { change(input.value); if(options.draft !== false)markDraft(); });
  wrap.append(input);
  return wrap;
}

function selectField(label, value, choices, change, options = {}) {
  const wrap = el("label", "field");
  wrap.append(el("span", "", label));
  const input = document.createElement("select");
  for (const [key, name] of choices) input.append(new Option(name, String(key)));
  input.value = String(value ?? "");
  input.addEventListener("change", () => { change(input.value); if(options.draft !== false)markDraft(); });
  wrap.append(input);
  return wrap;
}

function checkbox(label, checked, change, options = {}) {
  const wrap = el("label", "check-label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(checked);
  input.addEventListener("change", () => { change(input.checked); if(options.draft !== false)markDraft(); });
  wrap.append(input, el("span", "", label));
  return wrap;
}

function markDraft() {
  const wasDirty = draftDirty;
  draftTick += 1;
  draftDirty = true;
  $("save-state").textContent = t("Modifiche locali · usa Salva bozza");
  updateButtons(); renderTokens(); refreshAssistancePanels();
  if (!wasDirty) renderNotice();
}

function normalizeDraft(input) {
  const result = clone(input);
  result.profile ??= "H3-Base-Ref2VA";
  result.request ??= "";
  result.active_units ??= [];
  result.pictures ??= [];
  result.dialogues ??= [];
  result.audio_references ??= [];
  result.videos ??= [];
  result.continuity ??= { mode: "none", declared_state: null };
  result.declared_duration_s ??= null;
  result.ambient_sound ??= true;
  result.camera ??= null;
  for (const unit of result.active_units) unit.definition_mode ??= "picture";
  return result;
}

function insertRequest(text) {
  const input = $("request");
  const start = input.selectionStart;
  const end = input.selectionEnd;
  const value = input.value;
  const before = start && !/\s$/.test(value.slice(0, start)) ? " " : "";
  const after = end < value.length && !/^\s/.test(value.slice(end)) ? " " : "";
  input.setRangeText(before + text + after, start, end, "end");
  draft.request = input.value;
  markDraft();
  input.focus();
}

async function addRequestShot() {
  const request = draft.request;
  const shots = requestShotSequence(request);
  const count = shots.length || (request.trim() ? 1 : 0);
  const cutId = workspace.id, tick = draftTick;
  const content = el("div");
  let at = count ? "" : 0;
  let description = "", tag = "";
  const time = field(t("Inizio nel cut · secondi"), at, value => { at = value === "" ? "" : Number(value); },
    {type:"number", min:count ? (shots.at(-1)?.at_s || 0) + 0.001 : 0, max:(draft.declared_duration_s ?? 15) - 0.001, draft:false});
  const timeInput = time.querySelector("input");
  timeInput.required = true; timeInput.step = "0.001"; timeInput.readOnly = !count;
  const action = field(t("Cosa accade nello Shot"), "", value => { description = value; },
    {multiline:true, rows:4, draft:false, placeholder:t("Descrivi inquadratura, azioni e battute da richiamare.")});
  action.querySelector("textarea").required = true;
  content.append(time, selectField(t("Inquadratura salvata · facoltativa"), "",
    [["", t("Come descritta qui sotto")], ...(workspace.camera_presets || []).map(p => [p.tag, p.name])],
    value => { tag = value; }, {draft:false}), action,
    el("p", "field-help", t("Lo Shot viene aggiunto in fondo alla richiesta. Il tempo indica il momento del cambio dall’inizio del cut.")));
  if (!shots.length && count) content.append(el("p", "field-help", t("Il testo già scritto diventa Shot 1, dall’inizio del cut.")));
  if (!await dialog(tr`Aggiungi Shot ${count + 1}`, content, t("Inserisci Shot"))) return;
  if (workspace.id !== cutId || draftTick !== tick) throw new Error(t("La richiesta è cambiata. Riapri + Shot per usare il testo aggiornato."));
  draft.request = appendRequestShot(request, at, description, tag, draft.declared_duration_s ?? 15);
  $("request").value = draft.request;
  markDraft();
  $("request").focus(); $("request").setSelectionRange(draft.request.length, draft.request.length);
  feedback(tr`Shot ${count + 1} inserito. Puoi modificare testo e tempo nella richiesta.`);
}

function referenceChoices() {
  return [...visibleReferenceTokens(workspace?.tokens || [], draft),
    ...(workspace?.camera_presets || []).map(preset => ({
      kind: "shot", id: preset.id, label: `${preset.name} · #${preset.tag}`, token: `#${preset.tag}`
    }))];
}

function renderTokens() {
  const tray = $("token-tray"); tray.replaceChildren();
  for (const candidate of referenceChoices()) {
    tray.append(button(candidate.label, "token-button", () => withCommand(() => chooseReference(candidate))));
  }
  for (const card of $("pictures").querySelectorAll("[data-picture]")) {
    const picture = draft.pictures.find(p => p.id === card.dataset.picture);
    const status = card.querySelector("[data-picture-usage]");
    const action = card.querySelector("[data-associate-picture]");
    if (!picture || !status || !action) continue;
    const users = draft.active_units.filter(u => !u.excluded && unitPictureIds(u).includes(picture.id));
    const onlyExcludedUsers = !users.length && draft.active_units.some(u=>u.excluded && unitPictureIds(u).includes(picture.id));
    const ready = picture.confirmed && picture.linked_to_h3 && picture.description_en?.trim();
    status.textContent = picture.excluded ? t("Esclusa da questo cut: resta disponibile, senza partecipare alla compilazione.") : imageGuideRoles.has(picture.role) ? picture.guidance?.enabled ? t("Guida attivata per questo cut: controlla descrizione, mapping e collegamento H3.") : t("Guida non attiva: resta nel catalogo e non entra nel prompt.") : users.length ? tr`Associata a ${users.map(u => `${u.name || t("Unità")} · Subject ${u.subject}`).join(", ")}.` : ready ? t("Pronta: scegli a quale Subject associarla per usarla nel cut.") : t("Completa descrizione e conferme per renderla disponibile nel cut.");
    if (!picture.excluded && picture.role === 'scale_reference') status.textContent = users.length ? tr`Riferimento dimensionale per ${users.map(u=>`${u.name||t('Unità')} · Subject ${u.subject}`).join(', ')}.` : t('Scegli questa Picture in Subject → Dimensioni e scala → Picture di riferimento dimensionale. Non crea un Subject e non trasferisce l’identità della persona fotografata.');
    action.hidden = picture.excluded || imageGuideRoles.has(picture.role) || picture.role === 'scale_reference' || Boolean(users.length) || !ready;
    if (!picture.excluded && !imageGuideRoles.has(picture.role) && onlyExcludedUsers) status.textContent = t('Non partecipa alla compilazione: i Subject che la usano sono esclusi da questo cut.');
    action.disabled = commandBusy;
  }
  studioLayout.update(draft, workspace);
}

async function chooseReference(candidate, selection = null) {
  const available = referenceChoices().find(c => c.kind === candidate.kind && c.id === candidate.id && c.token === candidate.token);
  if (!available) { feedback(t("Il riferimento è cambiato. Salva i nuovi slot e selezionalo nuovamente."), true); return; }
  const input = $("request");
  const range = selection || { start: input.selectionStart, end: input.selectionEnd };
  $("mention-menu").hidden = true;
  if (available.requiresAssociation && !await askPictureAssociation(available.id)) return;
  input.setSelectionRange(range.start, range.end);
  insertRequest(available.token);
}

async function askPictureAssociation(pictureId) {
  const picture = draft.pictures.find(p => p.id === pictureId);
  if (!picture) return false;
  const attribute = picture.role;
  const targets = draft.active_units.filter(u => !u.excluded && sourceAttributes(u, {}).some(([key]) => key === attribute));
  const content = el("div");
  content.append(el("p", "section-help", tr`Picture ${picture.slot} · ${picture.name || t("Immagine")}. ${picture.description_en}. Scegli esplicitamente il Subject e l’associazione da usare. Non verrà creato un nuovo Subject.`));
  if (!targets.length) {
    content.append(el("p", "issues", tr`Aggiungi prima un Subject compatibile nel pannello Personaggi e unità${["identity", "outfit", "shoes"].includes(attribute) ? t(": per questo riferimento serve un personaggio") : ""}.`));
    await dialog(t("Associa l’immagine al cut"), content, null); return false;
  }
  const targetField = el("label", "field"); targetField.append(el("span", "", ["outfit", "shoes"].includes(attribute) ? t("Chi lo indossa?") : t("Subject da associare")));
  const target = el("select"); target.required = true; target.append(new Option(t("Scegli un Subject"), ""));
  for (const unit of targets) target.append(new Option(`${unit.name || t("Unità")} · Subject ${unit.subject}`, unit.subject));
  targetField.append(target); content.append(targetField);
  const modeField = el("label", "field"); modeField.hidden = true; modeField.append(el("span", "", t("Come usare il riferimento")));
  const mode = el("select"); modeField.append(mode); content.append(modeField);
  const note = el("p", "field-help"); content.append(note);
  target.onchange = () => {
    const unit = targets.find(u => u.subject === Number(target.value));
    const existing = (unit?.sources || []).map((source, index) => ({source, index})).filter(({source}) => source.attribute === attribute);
    mode.replaceChildren(new Option(t("Scegli se aggiungere o sostituire"), ""), new Option(t("Aggiungi un’ulteriore sorgente"), "add"));
    for (const {source, index} of existing) {
      const old = draft.pictures.find(p => p.id === source.picture_id);
      mode.append(new Option(tr`Sostituisci ${old ? `Picture ${old.slot} · ${old.name || t("Immagine")}` : t("l’associazione incompleta")}`, String(index)));
    }
    modeField.hidden = !existing.length; mode.required = Boolean(existing.length); mode.value = existing.length ? "" : "add";
    note.textContent = unit ? tr`L’attributo è ${attributes.find(([key]) => key === attribute)?.[1] || attribute}. Controlla e riconferma il Subject dopo la modifica.` : "";
  };
  if (!await dialog(t("Associa l’immagine al cut"), content, t("Associa immagine"))) return false;
  associatePicture(draft, pictureId, Number(target.value), attribute, mode.value === "add" ? null : Number(mode.value));
  markDraft(); renderUnits(); renderTokens();
  studioLayout.selectSection('subjects');
  const card = $("units").querySelector(`[data-unit="${Number(target.value)}"]`); if (card) card.open = true;
  feedback(tr`Picture ${picture.slot} associata. Controlla e riconferma il Subject; poi salva la bozza o compila.`);
  return true;
}

function addParticipation(item,kind,card,heading,body) {
  card.classList.toggle('reference-excluded',Boolean(item.excluded));
  if(item.excluded)heading.append(el('span','excluded-badge',t('Escluso da questo cut')));
  body.append(renderParticipation(item,kind,{el,checkbox,changed:()=>{
    markDraft();renderPictures();renderUnits();renderTokens();updateSpeakerNames();renderDirection();renderAudio();
  }}));
}

function renderPictures() {
  const container = $("pictures");
  const openCards = new Map([...container.querySelectorAll("details[data-picture]")].map((card) => [card.dataset.picture, card.open]));
  container.replaceChildren();
  if (!draft.pictures.length) container.append(el("p", "empty-list", t("Nessuna Picture. Puoi aggiungere le immagini necessarie o usare il contesto dichiarato per i Subject in continuità.")));
  for (const picture of draft.pictures) {
    const card = el("details", "reference-card picture-card");
    card.dataset.picture = picture.id;
    card.open = openCards.get(picture.id) ?? !picture.confirmed;
    const heading = el("summary");
    const summary = el("span", "reference-summary");
    const slot = el("span", "reference-number picture-number", `Picture ${picture.slot}`);
    const name = el("span", "", picture.name || t("Nuova immagine"));
    summary.append(slot, name); heading.append(summary);
    const body = el("div", "item-body");
    addParticipation(picture,'picture',card,summary,body);
    const first = el("div", "two-fields");
    first.append(field(t("Nome dell’immagine"), picture.name, (value) => {
      picture.name = value;
      name.textContent = value || t("Nuova immagine");
      updatePictureChoices();
    }), selectField("Slot in H3", picture.slot, Array.from({ length: 9 }, (_, n) => [n + 1, `Picture ${n + 1}`]), (value) => {
      picture.slot = Number(value);
      picture.linked_to_h3 = false;
      link.querySelector("input").checked = false;
      slot.textContent = `Picture ${picture.slot}`;
      updatePictureChoices();
    }));
    const role = selectField(t("Ruolo dell’immagine"), picture.role, pictureRoles, value => {
      picture.role=value;picture.confirmed=false;
      if (!imageGuideRoles.has(value) && picture.guidance) picture.guidance.enabled=false;
      if (picture.guidance && value!=='frame_anchor') Object.assign(picture.guidance,{anchor:null,at_s:null,workflow:'',continuity_checked:false});
      if (picture.guidance && value==='style')picture.guidance.mappings=[];
      renderPictures();renderUnits();renderTokens();
    });
    const description = field(t("Descrizione dell’immagine · un paragrafo senza a capo"), picture.description_en, (value) => {
      picture.description_en = value;
      picture.confirmed = false;
      confirmation.querySelector("input").checked = false;
      renderUnits();
    }, { multiline:true, rows:4, placeholder: t("Descrivi soltanto gli attributi utili dell’immagine, senza inserire a capo.") });
    const confirmation = checkbox(imageGuideRoles.has(picture.role)?t("Ho controllato descrizione, ruolo e mapping della guida"):t("Ho controllato la descrizione dell’immagine"), picture.confirmed, (value) => {
      if (value && (picture.description_language || "English") !== "English" && !picture.use_original_language) {
        confirmation.querySelector("input").checked = false; feedback(t("Traduci esplicitamente la descrizione o scegli di usarla nella lingua originale."), true); return;
      }
      picture.confirmed = value;
    });
    const originalConsent = checkbox(t("Uso questa descrizione nella lingua scelta"), picture.use_original_language, value => { picture.use_original_language = value; picture.confirmed = false; confirmation.querySelector("input").checked = false; });
    originalConsent.hidden = (picture.description_language || "English") === "English";
    const language = selectField(t("Lingua della descrizione"), picture.description_language || "English", languages, value => {
      picture.description_language = value; picture.use_original_language = false; picture.confirmed = false;
      originalConsent.hidden = value === "English"; originalConsent.querySelector("input").checked = false; confirmation.querySelector("input").checked = false;
    });
    const link = checkbox(t("La collegherò a H3 nello slot Picture indicato"), picture.linked_to_h3, (value) => { picture.linked_to_h3 = value; });
    const bottom = el("div", "item-bottom");
    bottom.append(el("span", "field-help", picture.role === 'scale_reference' ? t('Usa questa foto solo per le proporzioni nel campo Dimensioni e scala del Subject.') : imageGuideRoles.has(picture.role) ? t("La guida usa il proprio ruolo: non crea un Subject.") : t("Una Picture può essere sorgente di più Subject.")), button(t("Rimuovi immagine"), "button subtle danger", () => {
      draft.pictures = draft.pictures.filter((item) => item.id !== picture.id);
      for (const unit of draft.active_units) if (unitPictureIds(unit).includes(picture.id)) unit.confirmed = false;
      markDraft(); renderPictures(); renderUnits();
    }));
    const media = workspace?.media_by_picture?.[picture.id];
    if (media) {
      const preview = el("img", "picture-preview"); preview.src = `/api/media/${media.id}`; preview.alt = picture.name || media.display_name;
      body.append(preview, el("p", "field-help", `${media.display_name} · ${media.width} × ${media.height}`));
    }
    const upload = el("label", "upload-control", media ? t("Sostituisci il file gestito") : t("Carica immagine di riferimento"));
    const file = el("input"); file.type = "file"; file.accept = "image/jpeg,image/png,image/webp";
    file.addEventListener("change", () => { const selected = file.files[0]; if (selected) withCommand(() => uploadPicture(picture.id, selected)); });
    upload.append(file);
    const usage = el("p", "field-help"); usage.dataset.pictureUsage = "true";
    if (workspace?.reference_updates?.includes(picture.id)) body.append(el("p", "issues", t("Questa Picture ha una versione più recente nella libreria del progetto. Apri «Dalla libreria del progetto» e scegli «Ricarica immagine» per aggiornare esplicitamente questo cut, poi controlla e riconferma i collegamenti. I prompt già salvati restano invariati.")));
    const associate = button(t("Associa a un Subject"), "button secondary small", () => withCommand(() => askPictureAssociation(picture.id)));
    associate.dataset.associatePicture = "true";
    enableDrop(body, files => { if (files.length !== 1) throw new Error(t("Trascina una sola immagine per sostituire questa Picture.")); return uploadPicture(picture.id, files[0]); });
    body.append(upload, first, role, language, description, originalConsent);
    body.append(renderAnalysisControls(picture,imageAnalysisOptions,{el,field,selectField,button,
      changed:()=>{markDraft();refreshAssistancePanels();updateAssistanceControls();},openSubjects:()=>studioLayout.selectSection('subjects')}));
    if (picture.original_description) body.append(el("p", "field-help", tr`Originale (${picture.original_language || t("lingua originale")}): ${picture.original_description}`));
    const actions = el("div", "navigation-actions");
    actions.append(serverButton(t("Analizza immagine"), () => requestAssistance("image_analyze", picture.id), "analyze", picture.id),
                   serverButton(t("Proponi traduzione inglese"), () => requestAssistance("description_translate", picture.id), "translate", picture.id));
    if (["identity", "appearance"].includes(picture.role)) {
      const sheet = serverButton(t("Analizza character sheet"), () => requestAssistance("image_character_sheet", picture.id), "character-sheet", picture.id);
      sheet.title = t("Usa il file completo della Picture per descrivere una sola persona attraverso tutte le viste");
      actions.insertBefore(sheet, actions.lastChild);
    }
    const reason = el("p", "field-help"); reason.dataset.analysisReason = picture.id;
    body.append(actions, reason, assistancePanel(picture.id), proxyControls(picture), confirmation, link, usage, associate, bottom);
    if(imageGuideRoles.has(picture.role))body.insertBefore(guideControls(picture,'picture',()=>{picture.confirmed=false;confirmation.querySelector('input').checked=false;}),confirmation);
    card.append(heading, body); container.append(card);
  }
  renderTokens(); updateAssistanceControls();
}

function pictureChoices(source) {
  const choices = [["", t("Scegli un’immagine del catalogo")], ...draft.pictures.filter(picture=>picture.role !== 'scale_reference' || picture.id === source.picture_id).map((picture) => [picture.id, `Picture ${picture.slot} · ${picture.name || t("Immagine senza nome")}${picture.excluded ? t(" · esclusa da questo cut") : ""}${picture.role === 'scale_reference' ? t(' · solo Dimensioni e scala') : ''}`])];
  if (source.picture_id && !draft.pictures.some((picture) => picture.id === source.picture_id)) choices.push([source.picture_id, t("Immagine rimossa · scegli un’altra Picture")]);
  return choices;
}

function renderSourceWarning(row, source) {
  if (source.origin === "context") {
    const missing = draft.continuity.mode === "none";
    row.classList.toggle("missing-source", missing);
    const warning = row.querySelector(".source-warning"); warning.hidden = false;
    warning.textContent = missing ? t("Scegli una modalità di continuità e dichiara lo stato iniziale per usare questa sorgente.") : t("Sorgente dal contesto dichiarato: nessuno slot Picture viene creato. Conferma separatamente gli attributi conservati.");
    return;
  }
  const missing = !source.picture_id || !draft.pictures.some((picture) => picture.id === source.picture_id);
  row.classList.toggle("missing-source", missing);
  const warning = row.querySelector(".source-warning");
  warning.hidden = !missing;
  warning.textContent = source.picture_id ? t("L’immagine associata è stata rimossa. Scegli una Picture: nessuna sostituzione viene fatta automaticamente.") : t("Scegli una Picture già registrata. Questa riga associa un’immagine al Subject, senza crearne una nuova.");
}

function updatePictureChoices() {
  for (const select of $("units").querySelectorAll("select[data-source-picture]")) {
    const unit = draft.active_units.find((item) => item.subject === Number(select.dataset.subject));
    const source = unit?.sources?.[Number(select.dataset.sourceIndex)];
    if (!source) continue;
    select.replaceChildren(...pictureChoices(source).map(([id, name]) => new Option(name, String(id))));
    select.value = source.picture_id || "";
    renderSourceWarning(select.closest(".source-row"), source);
  }
}

function unconfirmUnit(unit, card) {
  unit.confirmed = false;
  const check = card.querySelector("input[data-unit-confirmation]");
  if (check) check.checked = false;
}

function sourceAttributes(unit, source) {
  const allowed = { character: ["identity", "appearance", "outfit", "shoes"], environment: ["environment", "appearance"], object: ["object", "appearance"] }[unit.role] || [];
  const choices = attributes.filter(([key]) => allowed.includes(key));
  if (source.attribute && !allowed.includes(source.attribute)) choices.push([source.attribute, tr`${attributes.find(([key]) => key === source.attribute)?.[1] || source.attribute} · controlla il ruolo`]);
  return choices;
}

function renderUnits() {
  const container = $("units");
  const openCards = new Map([...container.querySelectorAll("details[data-unit]")].map((card) => [Number(card.dataset.unit), card.open]));
  container.replaceChildren();
  if (!draft.active_units.length) container.append(el("p", "empty-list", t("Nessun Subject. Aggiungi chi o cosa vuoi identificare oppure riprendi esplicitamente un Subject dal contesto del cut precedente.")));
  for (const unit of draft.active_units) {
    const card = el("details", "reference-card");
    card.dataset.unit = unit.subject;
    card.open = openCards.get(unit.subject) ?? !unit.confirmed;
    const summary = el("summary");
    const heading = el("span", "reference-summary");
    const name = el("span", "", unit.name || t("Nuovo Subject"));
    heading.append(el("span", "reference-number", `Subject ${unit.subject}`), name);
    summary.append(heading);
    const body = el("div", "item-body");
    addParticipation(unit,'unit',card,heading,body);
    const first = el("div", "two-fields");
    first.append(field(t("Nome del Subject"), unit.name, (value) => {
      unit.name = value;
      name.textContent = value || t("Nuovo Subject");
      renderTokens(); updateSpeakerNames();
    }), selectField(t("Ruolo nella scena"), unit.role, roles, (value) => {
      unit.role = value;
      unconfirmUnit(unit, card);
      if (value !== "character") {
        for (const dialogue of draft.dialogues) {
          if (dialogue.speaker_subject === unit.subject) { dialogue.speaker_subject = 0; dialogue.confirmed = false; }
        }
        for (const audio of draft.audio_references || []) if (audio.speaker_subject === unit.subject) { audio.speaker_subject = null; audio.confirmed = false; }
      }
      renderUnits(); renderDialogues(); renderAudio();
    }));
    const picture = definitionPicture(unit, draft.pictures);
    const followsPicture = unit.definition_mode !== "manual" && picture;
    const mode = selectField(t("Origine della definizione del Subject"), unit.definition_mode || "picture", [["picture",t("Dalla Picture identificativa")],["manual",t("Definizione manuale del Subject")]], value => {
      if (value === "manual" && !unit.description_en?.trim()) unit.description_en = subjectDefinition(unit, draft.pictures);
      unit.definition_mode = value; unconfirmUnit(unit, card); renderUnits();
    });
    const description = field(followsPicture ? t("Definizione usata nel prompt · dalla Picture") : t("Definizione · in inglese o nome proprio, su una sola riga"), subjectDefinition(unit, draft.pictures), (value) => {
      unit.description_en = value; unconfirmUnit(unit, card);
    }, { placeholder: t("Per una persona può bastare il nome, ad esempio Ann.") });
    description.querySelector("input").readOnly = Boolean(followsPicture);
    body.append(first, mode, description, el("p", "field-help", followsPicture ? tr`La definizione segue la descrizione controllata di Picture ${picture.slot}, comprese analisi LLM e correzioni successive. Per distinguere persone nella stessa immagine o usare un testo diverso, scegli la definizione manuale.` : unit.definition_mode === "manual" ? t("Questa definizione manuale prevale sulla descrizione della Picture. Le associazioni di identità, abiti e scarpe restano quelle scelte qui sotto.") : t("Senza una Picture identificativa la definizione proviene dal Subject o dal contesto dichiarato. Le immagini di abiti e scarpe restano associazioni separate.")));
    const confirmation = checkbox(t("Confermo definizione e associazioni di questo Subject"), unit.confirmed, (value) => { unit.confirmed = value; });
    confirmation.querySelector("input").dataset.unitConfirmation = "true";
    const sourcesTitle = el("div", "sources-heading");
    const addSourceButton = button(t("+ Sorgente"), "button subtle", () => withCommand(() => addSource(unit.subject)));
    addSourceButton.dataset.serverCommand = "true";
    addSourceButton.disabled = commandBusy;
    sourcesTitle.append(el("span", "", t("Sorgenti associate a questo Subject")), addSourceButton);
    body.append(sourcesTitle);
    if (!unit.sources?.length) body.append(el("p", "source-empty", t("Aggiungi una sorgente: una Picture oppure il contesto di continuità dichiarato.")));
    for (const [index, source] of (unit.sources || []).entries()) {
      const row = el("div", "source-row");
      const fields = el("div", "two-fields");
      fields.append(selectField(t("Origine della sorgente"), source.origin || "picture", [["picture", t("Immagine Picture")], ["context", t("Contesto di continuità")]], value => {
        source.origin = value; source.picture_id = null; source.picture_slot = null; source.linked_to_h3 = false;
        unconfirmUnit(unit, card); renderUnits(); renderTokens();
      }));
      const pictureChoice = selectField(t("Immagine del catalogo"), source.picture_id, pictureChoices(source), (value) => {
        source.picture_id = value || null;
        source.picture_slot = null;
        source.linked_to_h3 = false;
        unconfirmUnit(unit, card);
        renderUnits(); renderTokens();
      });
      const select = pictureChoice.querySelector("select");
      select.dataset.sourcePicture = "true";
      select.dataset.subject = unit.subject;
      select.dataset.sourceIndex = index;
      if (source.origin !== "context") fields.append(pictureChoice);
      fields.append(selectField(t("Attributo per questo Subject"), source.attribute, sourceAttributes(unit, source), (value) => {
        source.attribute = value; unconfirmUnit(unit, card); renderUnits(); renderTokens();
      }), button("×", "button subtle danger", () => {
        unit.sources.splice(index, 1); unconfirmUnit(unit, card); markDraft(); renderUnits();
      }));
      fields.lastChild.setAttribute("aria-label", tr`Rimuovi associazione ${index + 1} da Subject ${unit.subject}`);
      row.append(fields, el("p", "source-warning"));
      renderSourceWarning(row, source);
      body.append(row);
    }
    if (unit.role === 'character' || unit.physical_details?.length) body.append(renderPhysicalDetails(unit, draft.pictures, draft.continuity?.mode || 'none', {
      el, field, selectField, button,
      changed: () => { unconfirmUnit(unit, card); markDraft(); },
      redraw: () => { renderUnits(); renderTokens(); }
    }));
    body.append(renderSubjectScale(unit, draft.active_units, draft.pictures, workspace.unit_ids || {}, {
      el, field, selectField, button,
      changed: () => { unconfirmUnit(unit, card); markDraft(); },
      redraw: () => { renderUnits(); renderPictures(); renderTokens(); }
    }));
    body.append(confirmation);
    const bottom = el("div", "item-bottom");
    const insert = button(t("Inserisci nella richiesta"), "button subtle", () => insertRequest(`<Subject ${unit.subject}>`));
    insert.disabled = Boolean(unit.excluded);
    bottom.append(insert, button(t("Rimuovi Subject"), "button subtle danger", () => {
      draft.active_units = draft.active_units.filter((item) => item.subject !== unit.subject);
      for (const dialogue of draft.dialogues) {
        if (dialogue.speaker_subject === unit.subject) { dialogue.speaker_subject = 0; dialogue.confirmed = false; }
      }
      for (const audio of draft.audio_references || []) if (audio.speaker_subject === unit.subject) { audio.speaker_subject = null; audio.confirmed = false; }
      markDraft(); renderUnits(); renderDialogues(); renderAudio(); renderTokens();
    }));
    body.append(bottom);
    card.append(summary, body); container.append(card);
  }
}


function speakerChoices(dialogue) {
  const choices = [[0, t("Scegli chi parla")], ...draft.active_units.filter((u) => !u.excluded && u.role === "character").map((u) => [u.subject, `${u.name || t("Personaggio")} · Subject ${u.subject}`])];
  if (dialogue.speaker_subject && !choices.some(([id]) => id === dialogue.speaker_subject)) choices.push([dialogue.speaker_subject, tr`Subject ${dialogue.speaker_subject} · non disponibile`]);
  return choices;
}

function updateSpeakerNames() {
  // Aggiorna solo le opzioni: non ricostruisce un campo battuta che si sta editando.
  for (const select of $("dialogues").querySelectorAll("select[data-dialogue]")) {
    const dialogue = draft.dialogues.find((d) => d.id === select.dataset.dialogue);
    select.replaceChildren(...speakerChoices(dialogue).map(([id, name]) => new Option(name, String(id))));
    select.value = String(dialogue.speaker_subject || 0);
  }
}

function voiceControls(item, change, help) {
  const controls = el("div", "voice-controls");
  const choices = el("div", "two-fields");
  choices.append(
    selectField(t("Emozione della voce"), item.voice_emotion || "", [["", t("Non specificata")], ...(voiceOptions?.emotions || []).map(option => [option.value, t(option.label)])], value => change("voice_emotion", value)),
    selectField(t("Modalità della voce"), item.voice_mode || "", [["", t("Non specificata")], ...(voiceOptions?.modes || []).map(option => [option.value, t(option.label)])], value => change("voice_mode", value)));
  const tone = field(t("Tono e modalità della voce · dettagli liberi"), item.voice_tone || "", value => change("voice_tone", value),
    {placeholder:t("Ad esempio con rabbia trattenuta, accentuando le ultime parole.")});
  tone.querySelector("input").maxLength = 500;
  controls.append(choices, tone, el("p", "field-help", help));
  if (!voiceOptions) controls.append(el("p", "field-help", t("Elenco delle emozioni in caricamento. Se resta vuoto, ricarica la pagina.")));
  return controls;
}

function renderDialogues() {
  const container = $("dialogues");
  const openCards = new Map([...container.querySelectorAll("details[data-dialogue-card]")].map((card) => [card.dataset.dialogueCard, card.open]));
  container.replaceChildren();
  if (!draft.dialogues.length) container.append(el("p", "empty-list", t("Nessuna battuta. Il cut può restare senza dialogo.")));
  for (const dialogue of draft.dialogues) {
    const card = el("details", "dialogue-card");
    card.dataset.dialogueCard = dialogue.id;
    card.open = openCards.get(dialogue.id) ?? !dialogue.confirmed;
    const summary = el("summary");
    const modeLabel = el("span", "", "");
    summary.append(el("span", "reference-number", tr`Battuta ${dialogue.id}`), modeLabel);
    const body = el("div", "item-body");
    const fields = el("div", "two-fields");
    const speaker = selectField(t("Chi parla"), dialogue.speaker_subject || 0, speakerChoices(dialogue), (value) => { dialogue.speaker_subject = Number(value) || null; dialogue.confirmed = false; card.querySelector("input[type=checkbox]").checked = false; });
    speaker.querySelector("select").dataset.dialogue = dialogue.id;
    const voice = selectField(t("Voce narrante"), dialogue.narrator_voice, narratorVoices, (value) => {
      if (value) dialogue.narrator_voice = value;
      else delete dialogue.narrator_voice;
      dialogue.confirmed = false;
      confirmed.querySelector("input").checked = false;
      updateDelivery();
    });
    const delivery = selectField(t("Tipo di parlato"), dialogue.delivery ?? "on_screen", dialogueDeliveries, (value) => {
      dialogue.delivery = value;
      if (value === "narrator") {
        dialogue.speaker_subject = null;
        speaker.querySelector("select").value = "0";
      } else {
        delete dialogue.narrator_voice;
        voice.querySelector("select").value = "";
      }
      dialogue.confirmed = false;
      confirmed.querySelector("input").checked = false;
      updateDelivery();
      renderDirection();
    });
    const updateDelivery = () => {
      const value = dialogue.delivery ?? "on_screen";
      speaker.hidden = value === "narrator";
      voice.hidden = !speaker.hidden;
      const mode = dialogueDeliveries.find(([id]) => id === value)?.[1] || "";
      const voiceLabel = speaker.hidden && narratorVoices.find(([id]) => id === dialogue.narrator_voice)?.[1];
      modeLabel.textContent = ` · ${mode}${voiceLabel ? ` · ${voiceLabel}` : ""}`;
    };
    fields.append(delivery, selectField(t("Lingua del parlato"), dialogue.language, [["Italian", t("Italiano")], ["English", t("Inglese")], ["French", t("Francese")], ["Spanish", t("Spagnolo")], ["German", t("Tedesco")], ["Portuguese", t("Portoghese")], ...(!["Italian", "English", "French", "Spanish", "German", "Portuguese"].includes(dialogue.language) ? [[dialogue.language, dialogue.language]] : [])], (value) => { dialogue.language = value; dialogue.confirmed = false; card.querySelector("input[type=checkbox]").checked = false; }));
    body.append(fields, speaker, voice, field(t("Parole esatte della battuta"), dialogue.text, (value) => { dialogue.text = value; dialogue.confirmed = false; }, { multiline: true, rows: 3, placeholder: t("Il parlato nella sua lingua originale.") }));
    const confirmed = checkbox(t("Confermo testo, modalità e parlante"), dialogue.confirmed, (value) => { dialogue.confirmed = value; });
    updateDelivery();
    body.querySelector("textarea").addEventListener("input", () => { confirmed.querySelector("input").checked = false; });
    body.append(voiceControls(dialogue, (key, value) => {
      dialogue[key] = value;
      dialogue.confirmed = false;
      confirmed.querySelector("input").checked = false;
    }, t("Le scelte vengono inserite in inglese nell’introduzione di questa battuta e prevalgono su quelle dell’audio di riferimento. Con tutti i campi vuoti si usano le impostazioni del riferimento, se presente.")), confirmed);
    const actions = el("div", "item-bottom");
    actions.append(button(t("Richiama nella richiesta"), "button subtle", () => insertRequest(`battuta ${dialogue.id}`)), button(t("Rimuovi battuta"), "button subtle danger", () => {
      draft.dialogues = draft.dialogues.filter((item) => item.id !== dialogue.id);
      markDraft(); renderDialogues(); renderTokens();
    }));
    body.append(actions); card.append(summary, body); container.append(card);
  }
}

function renderDraft() {
  $("request").value = draft.request;
  $("duration").value = draft.declared_duration_s ?? "";
  $("ambient-sound").checked = draft.ambient_sound;
  $("soundscape-text").value = draft.soundscape_text ?? "";
  renderPictures(); renderUnits(); renderDialogues(); renderAudio(); renderVideos(); renderContinuity(); renderDirection(); renderTokens();
}

function version(id) { return workspace?.versions.find((item) => item.id === id) || null; }
function displayedProposal() { return version(workspace?.latest_job?.candidate_id) || version(workspace?.latest_candidate_id); }
function activeJob() { return ["queued", "running"].includes(workspace?.latest_job?.status); }

function showIssues(target, issues) {
  target.replaceChildren(...(issues || []).map((issue) => el("li", "", diagnostic(issue))));
  target.hidden = !issues?.length;
}

function updateButtons() {
  for (const node of lockedCutControls) node.disabled = false;
  lockedCutControls.clear();
  $("soundscape-text").disabled = !workspace || commandBusy || draft.ambient_sound;
  for (const id of ["add-unit", "add-dialogue", "import-dialogues", "save-draft", "add-shot"]) $(id).disabled = !workspace || commandBusy;
  $("add-audio").disabled = !workspace || commandBusy || (draft?.audio_references?.length || 0) >= 3;
  $("add-video").disabled = !workspace || commandBusy || finalizedScene() || (draft?.videos?.length || 0) >= 3;
  $("add-picture").disabled = !workspace || commandBusy || (draft?.pictures.length ?? 0) >= 9;
  $("add-picture").title = (draft?.pictures.length ?? 0) >= 9 ? t("Questo cut ammette al massimo nove immagini; la libreria del progetto può contenerne altre.") : t("Registra un’immagine senza creare un Subject");
  for (const button of document.querySelectorAll("[data-server-command]")) button.disabled = !workspace || commandBusy;
  for (const id of ["compile", "compile-top"]) {
    $(id).disabled = !workspace || commandBusy || navigationBusy || activeJob() || finalizedScene();
    $(id).replaceChildren(document.createTextNode(activeJob() ? t("Compilazione in corso…") : workspace?.versions.some((v) => v.origin === "generated") ? t("Ricompila prompt") : t("Compila prompt")), el("span", "", "↗"));
  }
  $("export-archive").disabled = !workspace || commandBusy;
  $("compact-subjects").disabled = !workspace || commandBusy || activeJob() || finalizedScene();
  $("edit-proposal").disabled = !displayedProposal() || manualDirty;
  $("edit-proposal").title = manualDirty ? t("Salva prima il testo manuale che stai modificando.") : t("Apri una copia separata nell’editor manuale");
  $("copy-proposal").disabled = !displayedProposal();
  $("save-manual").disabled = !workspace || commandBusy || !$("manual-text").value.length || !manualDirty;
  $("copy-manual").disabled = !workspace || !$("manual-text").value.length;
  $("cancel-job").hidden = !activeJob(); $("cancel-job").disabled = commandBusy;
  const finalized = Boolean(currentContext()?.scene.finalized);
  if (finalized) for (const id of ["add-picture", "add-unit", "add-dialogue", "add-shot", "import-dialogues", "add-audio", "save-draft", "compile", "save-manual", "edit-proposal", "open-library"]) $(id).disabled = true;
  $("manual-text").disabled = finalized || navigationBusy;
  $("open-library").disabled = !workspace || commandBusy || finalized;
  $("manage-library").disabled = !workspace || commandBusy;
  renderNavigation(); updateConfirmationButtons(); updateAssistanceControls();
  if (finalized || navigationBusy) for (const node of $("draft-fields").querySelectorAll('input, select, textarea, button')) {
    if (!node.closest('#settings-panel') && !node.disabled) { lockedCutControls.add(node); node.disabled = true; }
  }
}

function renderNotice() {
  const notice = $("notice");
  notice.className = "notice";
  let title = t("Prepara il tuo cut");
  let text = t("I riferimenti e le battute restano modificabili. Compila quando hai completato la richiesta.");
  let issues = [];
  const job = workspace?.latest_job;
  const result = job?.result;
  if (localError) {
    notice.classList.add("error"); title = localError.title || t("Operazione non completata"); text = localError.message;
    issues = localError.issues || [];
  } else if (workspace?.catalogue_issues?.length) {
    notice.classList.add("error"); title = t("Controlli da completare"); text = t("Completa questi punti prima di compilare.");
    issues = workspace.catalogue_issues;
  } else if (compileFailure) {
    notice.classList.add("error"); title = compileFailure.issues?.length ? t("Controlli da completare") : t("Compilazione non avviata"); text = compileFailure.message;
    issues = compileFailure.issues || [];
  } else if ((result?.status === "error" || job?.status === "failed") && (job?.stale || draftDirty)) {
    notice.classList.add("clarification"); title = t("Errore di una bozza precedente");
    text = t("L’ultimo errore riguarda una bozza precedente. Ricompila per verificare i dati attuali. ") + (result?.issues || []).map(diagnostic).join(" ");
  } else if (result?.status === "error" || job?.status === "failed") {
    notice.classList.add("error"); title = result?.error_code === "invalid_structure" ? t("Risposta del modello non valida") : t("Errore durante la compilazione");
    text = result?.issues?.map(diagnostic).join(" ") || t("La compilazione non è riuscita. Puoi riprovare.");
  } else if (result?.status === "clarification_needed") {
    notice.classList.add("clarification"); title = t("Serve un chiarimento"); text = result.interpretation?.question || result.issues?.join(" ");
  } else if (activeJob()) {
    notice.classList.add("processing"); title = job.status === "queued" ? t("In coda") : t("Compilazione in corso");
    text = t("Attendo il modello locale. Puoi continuare a modificare e salvare il tuo lavoro.");
  } else if (workspace?.state === "confirmed") {
    title = t("Cut confermato"); text = t("Versione e riferimenti approvati conservati. Una nuova bozza resterà separata.");
  } else if (job?.stale) {
    notice.classList.add("clarification"); title = t("Proposta da una bozza precedente"); text = t("I campi e il testo manuale attuali sono conservati. Rivedi la proposta prima di usarla oppure ricompila con la richiesta aggiornata.");
  } else if (displayedProposal()) {
    title = t("Proposta pronta da rivedere"); text = displayedProposal().structural_checks_passed ? t("Controlli strutturali superati. Controlla azioni, ordine e fedeltà prima di usare il prompt.") : t("La proposta richiede correzioni. Puoi conservarla e copiarla come bozza.");
  }
  if (issues.length) {
    if (draftDirty) {
      title = t("Modifiche da verificare");
      text = t("Questi punti si riferiscono all’ultimo controllo. Premi Compila per verificare le modifiche.");
    } else text = t("Completa questi punti prima di compilare.");
  }
  $("notice-title").textContent = title; $("notice-body").textContent = text;
  showIssues($("notice-issues"), issues);
  notice.open = Boolean(localError || compileFailure || issues.length || result?.status === "error" || result?.status === "clarification_needed");
}

function renderResults() {
  const proposal = displayedProposal();
  const job = workspace?.latest_job;
  const failed = Boolean(compileFailure) || Boolean(workspace?.catalogue_issues?.length) || (!job?.stale && (job?.result?.status === "error" || job?.status === "failed"));
  $("proposal-panel").classList.toggle("failed", failed);
  $("proposal-empty").hidden = Boolean(proposal);
  $("proposal-text").hidden = !proposal;
  $("proposal-text").textContent = proposal?.text || "";
  $("proposal-badge").textContent = failed && proposal ? t("Versione precedente") : proposal?.user_approved ? t("Confermata") : job?.stale && proposal ? t("Bozza precedente") : proposal ? t("Da rivedere") : t("Da compilare");
  $("proposal-meta").textContent = failed && proposal ? t("versione precedente: nessun nuovo risultato") : proposal ? `${proposal.duration_s ?? "—"} s · ${{ declared: t("durata dichiarata"), measured: t("durata da audio misurato") }[proposal.duration_origin] || t("durata stimata")} · ${proposal.structural_checks_passed ? t("controlli strutturali superati") : t("bozza da correggere")}` : t("Il prompt comparirà qui, in sei sezioni.");
  showIssues($("proposal-issues"), proposal?.issues);
  const metrics = job?.result?.metrics;
  $("metrics").hidden = !metrics;
  if (metrics) $("metrics-text").textContent = tr`${metrics.model} · ${metrics.inference_calls} chiamata · ${metrics.prompt_tokens ?? "—"} token in ingresso · ${metrics.output_tokens ?? "—"} in uscita · ${metrics.wall_s.toFixed(2)} s totali`;
  renderManualMeta(); renderNotice(); updateButtons(); updateConfirmationButtons(); refreshAssistancePanels(); renderContinuityPreview(); renderResultVideo();
  studioLayout.update(draft, workspace);
}

function renderManualMeta() {
  const saved = version(workspace?.manual_version_id);
  $("manual-badge").textContent = manualDirty ? t("Da salvare") : saved ? t("Salvata sul Mac") : t("Facoltativa");
  $("manual-state").textContent = manualDirty ? t("Modifiche manuali non ancora salvate. La copia userà questo testo come bozza.") : saved ? t("Versione manuale salvata su questo Mac. Il testo resta separato dalle nuove proposte.") : t("Nessuna versione manuale salvata.");
  showIssues($("manual-issues"), manualDirty ? [] : saved?.issues);
}

function feedback(text, error = false) { $("action-feedback").textContent = text; $("action-feedback").classList.toggle("error", error); }

function renderConnectionStatus() {
  $("connection").textContent = connectionAvailable === null
    ? t("Connessione al Mac…")
    : connectionAvailable
      ? t("Servizi LLM disponibili")
      : t("Servizi LLM da configurare o non raggiungibili · modifica manuale disponibile");
  $("connection").classList.toggle("available", connectionAvailable === true);
}

function refreshLanguage() {
  ({ roles, attributes, pictureRoles, videoRoles, cameraPhases, dialogueDeliveries, narratorVoices, languages, continuityModes } = makeUiChoices());
  timelineSeconds = new Intl.NumberFormat(uiLanguage(), { maximumFractionDigits: 3 });
  renderConnectionStatus();
  userSettings.refreshLanguage();
  fillModelChoices('model', 'text-service', 'completion', $("model").value);
  fillModelChoices('vision-model', 'vision-service', 'vision', $("vision-model").value);
  $("asr-status").textContent = diagnostic(asrState.message);
  $("access-settings").textContent = t('Impostazioni utente');
  $("save-state").textContent = draftDirty ? t("Modifiche locali · usa Salva bozza") : t("Bozza salvata su questo Mac");
  feedback("");
  if (workspace && draft) {
    renderDraft();
    renderResults();
    renderConfirmedCuts();
    refreshAssistancePanels();
  }
  updateAssistanceControls();
  studioLayout.update(draft, workspace);
}

class ApiError extends Error {
  constructor(message, code, status, issues = []) { super(message); this.code = code; this.status = status; this.issues = issues; }
}

async function request(path, options = {}, plain = false) {
  let response;
  try { response = await fetch(path, { cache: "no-store", ...options, headers: { ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(options.headers || {}) } }); }
  catch { throw new ApiError(t("Il servizio locale non risponde. Il testo che stai modificando è ancora qui."), "network", 0); }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    if (response.status === 401 && detail?.code === 'authentication_required') showLogin();
    throw new ApiError(typeof detail?.message === "string" ? diagnostic(detail.message) : t("Controlla i campi del cut e le conferme dei riferimenti e del parlato."), detail?.code || "invalid_input", response.status, detail?.issues || []);
  }
  return plain ? response.text() : response.json();
}

async function mutation(method, path, body, apply) {
  const command = { method, path, body: JSON.stringify(body), apply };
  return sendMutation(command);
}

async function sendMutation(command) {
  try {
    const view = await request(command.path, { method: command.method, headers: { "Content-Type": "application/json" }, body: command.body });
    pending = null; $("recovery").hidden = true; localError = null;
    await command.apply(view);
    renderResults();
    return view;
  } catch (error) {
    pending = error.code === "network" ? command : null;
    localError = { title: error.status === 409 ? t("Il salvataggio sul Mac è cambiato") : error.issues?.length ? t("Controlli da completare") : t("Operazione non completata"), message: error.message, issues:error.issues || [] };
    $("recovery").hidden = !pending && error.status !== 409;
    $("retry-command").hidden = !pending;
    renderNotice();
    throw error;
  }
}

async function withCommand(action) {
  if (commandBusy || !workspace) return;
  commandBusy = true; updateButtons();
  try { await action(); }
  catch (error) { feedback(error.message, true); }
  finally { commandBusy = false; updateButtons(); }
}

async function saveDraft() {
  const tick = draftTick;
  const input = clone(draft);
  try {
    const snapshots = shotPresetSnapshots(input.request, workspace.camera_presets || []);
    if (snapshots.length) input.shot_presets = clone(snapshots);
    else delete input.shot_presets;
  } catch {
    // Una richiesta con un tag ancora incompleto resta salvabile come bozza.
  }
  await mutation("PUT", `/api/cuts/${workspace.id}/draft`, { command_id: newCommandId(), expected_revision: workspace.revision, input }, (view) => {
    if (["incomplete_input", "invalid_input"].includes(compileFailure?.code)) compileFailure = null;
    workspace = view; renderTokens();
    if (draftTick === tick) { draftDirty = false; $("save-state").textContent = t("Bozza salvata su questo Mac"); renderContinuity(); renderContinuityPreview(); }
  });
  return tick === draftTick;
}

async function addItem(kind) {
  if (!await saveDraft()) throw new Error(t("I campi sono cambiati durante il salvataggio. Riprova dopo aver terminato la modifica."));
  const tick = draftTick;
  await mutation("POST", `/api/cuts/${workspace.id}/items`, { command_id: newCommandId(), expected_revision: workspace.revision, kind }, (view) => {
    adoptView(view, tick);
    studioLayout.selectSection({picture:'images', unit:'subjects', dialogue:'dialogues', audio:'audio', video:'video'}[kind]);
    feedback(kind === "picture" ? t("Immagine registrata. Puoi associarla a un Subject; nessun Subject è stato creato.") : kind === "unit" ? t("Subject aggiunto. Scegli le immagini o il contesto dichiarato come sorgenti.") : kind === "audio" ? t("Slot audio aggiunto. Carica il file e scegli il segmento.") : kind === "video" ? t("Slot Video aggiunto. Dichiara il file oppure caricalo per anteprima e misura; selezionalo nel raccordo quando serve.") : t("Battuta aggiunta. Scegli chi parla e inserisci il testo esatto."));
  });
}

async function addSource(subject) {
  if (!await saveDraft()) throw new Error(t("I campi sono cambiati durante il salvataggio. Riprova dopo aver terminato la modifica."));
  const serverUnit = workspace.draft_input.active_units?.find((unit) => unit.subject === subject);
  if (!serverUnit) return;
  const knownCount = serverUnit.sources?.length || 0;
  const tick = draftTick;
  await mutation("POST", `/api/cuts/${workspace.id}/sources`, { command_id: newCommandId(), expected_revision: workspace.revision, subject }, (view) => {
    if (draftTick !== tick) {
      const current = draft.active_units.find((unit) => unit.subject === subject);
      const updated = view.draft_input.active_units?.find((unit) => unit.subject === subject);
      if (current && updated) {
        current.sources ??= [];
        current.sources.push(...clone((updated.sources || []).slice(knownCount)));
        current.confirmed = false;
      }
    }
    adoptView(view, tick);
    feedback(t("Associazione aggiunta. Scegli una Picture esistente e l’attributo per questo Subject."));
  });
}

async function compile() {
  try {
    if (!$("model").value) throw new Error(t('Scegli un modello testo in Impostazioni utente prima di compilare.'));
    const projectId = workspace.project_id;
    const cutId = workspace.id;
    const library = await request(`/api/projects/${projectId}/library`);
    if (workspace.id !== cutId) return;
    workspace.camera_presets = library.camera_presets || [];
    const snapshots = shotPresetSnapshots(draft.request, workspace.camera_presets);
    if (snapshots.length) draft.shot_presets = clone(snapshots);
    else delete draft.shot_presets;
    if (!await saveDraft()) { feedback(t("La bozza è cambiata durante il salvataggio. Premi di nuovo Compila per usare gli ultimi campi.")); return; }
    const input = clone(draft);
    const tick = draftTick;
    await mutation("POST", `/api/cuts/${workspace.id}/compile`, { command_id: newCommandId(), cut_id: workspace.id, expected_revision: workspace.revision, input, model: $("model").value || null }, (job) => {
      compileFailure = null;
      workspace.revision = job.input_revision; workspace.latest_job = job;
      if (draftTick === tick) { draftDirty = false; $("save-state").textContent = t("Bozza salvata su questo Mac"); }
      feedback(t("Compilazione avviata. Puoi continuare a lavorare."));
      startPolling(job.id);
    });
  } catch (error) {
    // Anche un rifiuto prima dell'inferenza non produce un nuovo candidato.
    compileFailure = { message: error.message, code:error.code, issues:error.issues || [] };
    renderResults();
    throw error;
  }
}

async function importQuotedDialogues() {
  if(draft.dialogues.length || draft.audio_references?.some(a=>a.role==='speech')) {
    feedback(t('Sono già presenti battute: richiama i loro ID nella richiesta per evitare duplicati.'),true);return;
  }
  if(!await saveDraft())throw new Error(t('La bozza è cambiata durante il salvataggio. Riprova dopo aver terminato la modifica.'));
  const cut=workspace.id,tick=draftTick;
  const preview=await request(`/api/cuts/${cut}/dialogues/preview`);
  if(workspace.id!==cut || draftTick!==tick || preview.source_request!==draft.request || preview.revision!==workspace.revision)throw new Error(t('La richiesta è cambiata. Riapri il recupero delle battute.'));
  if(!preview.candidates.length){feedback(t('Nessuna citazione semplice riconosciuta dopo dice, aggiunge, risponde, chiede, esclama o sussurra. Usa + Battuta e richiama il suo ID nella richiesta.'));return;}
  const content=el('div');
  content.append(el('p','section-help',t('Questa è una proposta locale, senza chiamare il modello. Seleziona soltanto le frasi pronunciate: una scritta visibile non è un dialogo. Controlla testo, lingua, tipo di parlato e parlante. La richiesta richiamerà le battute tramite i loro ID.')));
  const characters=draft.active_units.filter(u=>!u.excluded && u.role==='character');
  const choices=[];
  for(const candidate of preview.candidates) {
    const row=el('div','mapping-row');
    const choice={index:candidate.index,text:candidate.text,language:'Italian',delivery:'on_screen',speaker_subject:characters.length===1?characters[0].subject:null,selected:true};choices.push(choice);
    row.append(el('p','field-help',candidate.context));
    const fields=el('div');
    const selected=checkbox(tr`Importa citazione ${candidate.index+1} come battuta`,true,value=>{choice.selected=value;for(const input of fields.querySelectorAll('input,textarea,select'))input.disabled=!value;},{draft:false});
    const text=field(tr`Testo esatto · citazione ${candidate.index+1}`,choice.text,value=>{choice.text=value;},{multiline:true,rows:2,draft:false});text.querySelector('textarea').required=true;
    const speaker=selectField(tr`Parlante · citazione ${candidate.index+1}`,choice.speaker_subject||'',[['',t('Scegli il parlante')],...characters.map(u=>[u.subject,`${u.name} · Subject ${u.subject}`])],value=>{choice.speaker_subject=Number(value)||null;},{draft:false});
    const speakerSelect=speaker.querySelector('select');speakerSelect.required=true;
    const voice=selectField(tr`Voce narrante · citazione ${candidate.index+1}`,'',narratorVoices,value=>{
      if(value) choice.narrator_voice=value;
      else delete choice.narrator_voice;
    },{draft:false});
    voice.hidden=true;
    const delivery=selectField(tr`Tipo di parlato · citazione ${candidate.index+1}`,choice.delivery,dialogueDeliveries,value=>{
      choice.delivery=value;
      speaker.hidden=value==='narrator';
      speakerSelect.required=!speaker.hidden;
      voice.hidden=!speaker.hidden;
      if(speaker.hidden){choice.speaker_subject=null;speakerSelect.value='';}
      else {delete choice.narrator_voice;voice.querySelector('select').value='';}
    },{draft:false});
    const routing=el('div','two-fields');routing.append(delivery,selectField(tr`Lingua · citazione ${candidate.index+1}`,choice.language,languages,value=>{choice.language=value;},{draft:false}));fields.append(text,routing,speaker,voice);
    row.append(selected,fields);content.append(row);
  }
  const checked=checkbox(t('Confermo testo, lingua, modalità e parlante delle battute selezionate'),false,()=>{},{draft:false});checked.querySelector('input').required=true;content.append(checked);
  if(!await dialog(t('Recupera il parlato dalla richiesta'),content,t('Importa battute controllate')))return;
  if(workspace.id!==cut || draftTick!==tick)throw new Error(t('La bozza è cambiata: rileggi le battute prima di importarle.'));
  const selected=choices.filter(c=>c.selected).map(({selected,...value})=>value);
  if(!selected.length){feedback(t('Nessuna battuta selezionata. La richiesta è conservata.'));return;}
  await mutation('POST',`/api/cuts/${cut}/dialogues/import`,{command_id:newCommandId(),expected_revision:preview.revision,source_request:preview.source_request,dialogues:selected,confirmed:true},view=>adoptView(view,tick));
  compileFailure=null;localError=null;renderResults();
  feedback(t('Battute recuperate con le parole controllate. La richiesta usa i loro ID; ora puoi compilare il prompt.'));
}

function startPolling(jobId) {
  clearTimeout(pollTimer);
  const cutId = workspace.id;
  const poll = async () => {
    try {
      const job = await request(`/api/jobs/${jobId}`);
      if (workspace.id !== cutId || workspace.latest_job?.id !== jobId) return;
      if (localError?.source === "poll") localError = null;
      workspace.latest_job = job;
      if (["queued", "running"].includes(job.status)) {
        renderResults(); pollTimer = setTimeout(poll, 900);
      } else {
        const view = await request(`/api/cuts/${cutId}`);
        if (workspace.id !== cutId) return;
        mergePolledView(view);
        await refreshProjects(); renderNavigation(); renderConfirmedCuts();
        // Non si ricaricano mai i campi e l'editor manuale dal polling.
        if ($("action-feedback").textContent === t("Compilazione avviata. Puoi continuare a lavorare.")) feedback("");
        renderResults();
      }
    } catch (error) {
      localError = { title: t("Aggiornamento sospeso"), message: error.message, source: "poll" };
      renderNotice();
      pollTimer = setTimeout(poll, 2500);
    }
  };
  pollTimer = setTimeout(poll, 250);
}

async function saveManual() {
  if (draftDirty && !await saveDraft()) throw new ApiError(t("La bozza è cambiata: salva prima gli ultimi campi."), "local_changes", 0);
  const text = $("manual-text").value;
  await mutation("PUT", `/api/cuts/${workspace.id}/manual`, { command_id: newCommandId(), expected_revision: workspace.revision, text, base_candidate_id: manualBaseId }, (view) => {
    workspace = view;
    if ($("manual-text").value === text) { manualDirty = false; manualBaseId = workspace.manual_version_id; }
    feedback(t("Versione manuale salvata su questo Mac, senza chiamare il modello."));
  });
  await refreshProjects(); renderNavigation(); renderConfirmedCuts();
}

async function copyText(text, label) {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
    else throw new Error("fallback");
  } catch {
    const focus = document.activeElement;
    const temporary = el("textarea");
    temporary.value = text;
    temporary.style.cssText = "position:fixed;left:-10000px;top:0";
    document.body.append(temporary); temporary.select();
    const copied = document.execCommand("copy");
    temporary.remove(); focus?.focus();
    if (!copied) { feedback(t("Copia non disponibile: seleziona e copia il testo dal riquadro."), true); return; }
  }
  feedback(label);
}

async function copyVersion(saved, label) {
  try { await copyText(await request(`/api/cuts/${workspace.id}/text?version_id=${encodeURIComponent(saved.id)}`, {}, true), label); }
  catch (error) { feedback(error.message, true); }
}

async function loadWorkspace(initial = false) {
  const view = await request(currentCutId ? `/api/cuts/${currentCutId}` : "/api/workspace");
  applyWorkspace(view, initial);
}

function applyWorkspace(view, initial = false) {
  if (workspace?.id !== view.id) editingCameraPreset = null;
  currentCutId = view.id;
  $("application").hidden = false;
  workspace = view; draft = normalizeDraft(view.draft_input); draftDirty = false; draftTick += 1;
  renderDraft(); renderNavigation(); renderConfirmedCuts();
  if (initial || !manualDirty) {
    const saved = version(view.manual_version_id);
    $("manual-text").value = saved?.text || "";
    manualBaseId = saved?.id || null;
    manualDirty = false;
  }
  for (const id of ["request", "duration", "model", "manual-text"]) $(id).disabled = false;
  $("save-state").textContent = t("Bozza salvata su questo Mac");
  localError = null; compileFailure = null; $("recovery").hidden = true;
  renderResults();
  if (activeJob()) startPolling(view.latest_job.id);
  startAssistancePolling();
}

async function refreshCurrentCut(explicit = false) {
  if (refreshBusy || commandBusy || navigationBusy || pending || !workspace || $("application").hidden || (!explicit && (document.hidden || $("action-dialog").open))) return;
  refreshBusy = true; $("refresh-cut").disabled = true;
  const cutId = workspace.id, tick = draftTick, manualText = $("manual-text").value;
  const revision = workspace.revision, candidateId = workspace.latest_candidate_id, jobStatus = workspace.latest_job?.status;
  try {
    const [view, updatedProjects] = await Promise.all([request(`/api/cuts/${cutId}`).catch(error => {
      if (error.code === "cut_trashed") return null;
      throw error;
    }), request("/api/projects")]);
    if (workspace.id !== cutId || commandBusy || navigationBusy || workspace.revision !== revision || workspace.latest_candidate_id !== candidateId || workspace.latest_job?.status !== jobStatus) return;
    projects = updatedProjects;
    if (!view) {
      if (draftDirty || manualDirty || draftTick !== tick || $("manual-text").value !== manualText) {
        feedback(t("Il cut è nel cestino. Ripristinalo da «Gestisci nomi e cestino» per recuperare le modifiche aperte."), true);
      } else {
        const next = firstAvailableCut();
        if (next) await switchCut(next);
        else await showEmptyArchive();
      }
      return;
    }
    if (JSON.stringify(view.camera_presets) !== JSON.stringify(workspace.camera_presets)) {
      workspace.camera_presets = view.camera_presets;
      renderSavedCameras(); renderTokens();
    }
    const changed = view.revision !== workspace.revision || view.latest_candidate_id !== workspace.latest_candidate_id || view.latest_job?.status !== workspace.latest_job?.status || view.confirmed_version_id !== workspace.confirmed_version_id;
    if (!changed) { renderNavigation(); if (explicit) feedback(t("Il cut è già aggiornato con il Mac centrale.")); return; }
    if (draftDirty || manualDirty || draftTick !== tick || $("manual-text").value !== manualText) {
      localError = {title:t("Il cut è stato aggiornato da un altro browser"),message:t("Le tue modifiche locali sono conservate. Carica la bozza salvata sul Mac per vedere immagini e prompt aggiornati; puoi poi ripristinare i campi locali.")};
      $("recovery").hidden = false; renderNotice(); return;
    }
    applyWorkspace(view, true);
    feedback(t("Immagini, bozza e prompt del cut aggiornati dal Mac centrale."));
  } catch (error) { if (explicit) feedback(error.message, true); }
  finally { refreshBusy = false; $("refresh-cut").disabled = false; }
}

$("refresh-cut").onclick = () => refreshCurrentCut(true);
window.addEventListener("focus", () => refreshCurrentCut());
window.addEventListener("pageshow", () => refreshCurrentCut());
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshCurrentCut(); });
setInterval(() => refreshCurrentCut(), 5000);

$("request").addEventListener("input", () => { draft.request = $("request").value; markDraft(); });
$("duration").addEventListener("input", () => {
  draft.declared_duration_s = $("duration").value === "" ? null : Number($("duration").value);
  renderAudioTimeline();
  markDraft();
});
$("ambient-sound").addEventListener("change", () => { draft.ambient_sound = $("ambient-sound").checked; markDraft(); });
$("soundscape-text").addEventListener("input", () => {
  const value = $("soundscape-text").value;
  if (value) draft.soundscape_text = value;
  else delete draft.soundscape_text;
  markDraft();
});
$("manual-text").addEventListener("input", () => { manualDirty = true; renderManualMeta(); updateButtons(); });
$("save-draft").addEventListener("click", () => withCommand(async () => {
  const saved = await saveDraft();
  feedback(saved ? t("Bozza salvata sul Mac centrale e disponibile agli altri browser.") : t("Hai modificato altri campi durante il salvataggio. Premi di nuovo Salva bozza per condividerli."));
}));
$("add-picture").addEventListener("click", () => withCommand(() => addItem("picture")));
$("add-unit").addEventListener("click", () => withCommand(() => addItem("unit")));
$("add-dialogue").addEventListener("click", () => withCommand(() => addItem("dialogue")));
$("import-dialogues").addEventListener("click", () => withCommand(importQuotedDialogues));
for (const id of ["compile", "compile-top"]) $(id).addEventListener("click", () => withCommand(compile));
$("add-shot").addEventListener("click", () => withCommand(addRequestShot));
$("save-manual").addEventListener("click", () => withCommand(saveManual));
$("edit-proposal").addEventListener("click", () => {
  const proposal = displayedProposal();
  if (!proposal || manualDirty) return;
  $("manual-text").value = proposal.text; manualBaseId = proposal.id; manualDirty = true;
  renderManualMeta(); updateButtons(); $("manual-text").focus();
  feedback(t("Copia della proposta aperta nell’editor. La proposta originale è conservata."));
});
$("copy-proposal").addEventListener("click", () => { const proposal = displayedProposal(); if (proposal) copyVersion(proposal, proposal.structural_checks_passed ? t("Proposta copiata. Rivedila prima dell’uso in H3.") : t("Proposta copiata come bozza da correggere.")); });
$("copy-manual").addEventListener("click", () => {
  if (manualDirty) copyText($("manual-text").value, t("Bozza manuale copiata; le modifiche non sono ancora salvate."));
  else { const saved = version(workspace.manual_version_id); if (saved) copyVersion(saved, saved.structural_checks_passed ? t("Versione manuale salvata copiata.") : t("Versione manuale copiata come bozza da correggere.")); }
});
$("retry-command").addEventListener("click", () => withCommand(async () => { if (pending) await sendMutation(pending); }));
$("load-server").addEventListener("click", () => withCommand(async () => {
  localBackup = clone(draft);
  await loadWorkspace();
  $("restore-local").hidden = false; $("recovery").hidden = false;
  feedback(t("Bozza salvata caricata. Puoi ripristinare i campi precedenti con il pulsante dedicato."));
}));
$("restore-local").addEventListener("click", () => {
  if (!localBackup) return;
  draft = localBackup; localBackup = null; markDraft(); renderDraft();
  $("recovery").hidden = true;
  feedback(t("Campi precedenti ripristinati localmente. Salvali per conservarli sul Mac."));
});
window.addEventListener("beforeunload", (event) => {
  if (draftDirty || manualDirty) { event.preventDefault(); event.returnValue = ""; }
});

async function initialize() {
  try {
    accessState = await request("/api/access/status"); csrf = accessState.csrf;
    if (!accessState.authenticated) { showLogin(); return; }
    $("application").hidden = false; $("login-panel").hidden = true;
    $("logout").hidden = !accessState.authentication_required;
    await refreshProjects();
    if (currentCutId && !findCut(currentCutId)) currentCutId = null;
    if (!currentCutId) currentCutId = firstAvailableCut();
    if (!currentCutId) { await showEmptyArchive(); return; }
    await loadWorkspace(true);
  }
  catch (error) { localError = { title: t("Impossibile aprire il cut"), message: error.message }; renderNotice(); $("connection").textContent = t("Servizio non raggiungibile"); return; }
  const [healthResult, directionResult, voiceResult, imageResult] = await Promise.allSettled([request("/api/health"),request('/static/direction-options.json'),request('/static/voice-options.json'),request('/static/image-analysis-options.json')]);
  if(directionResult.status==='fulfilled'){directionOptions=directionResult.value;renderDirection();}
  if(voiceResult.status==='fulfilled'){voiceOptions=voiceResult.value;renderAudio();renderDialogues();}
  if(imageResult.status==='fulfilled'){imageAnalysisOptions=imageResult.value;renderPictures();}
  connectionAvailable = healthResult.status === "fulfilled" && healthResult.value.ollama_available;
  renderConnectionStatus();
  defaultModel = healthResult.status === "fulfilled" ? healthResult.value.default_model : null;
  await loadAssistance();
  await userSettings.load();
}


function findCut(id) {
  for (const project of projects) for (const scene of project.scenes) {
    const cut = scene.cuts.find(c => c.id === id);
    if (cut && !project.trashed && !scene.trashed) return { project, scene, cut };
  }
  return null;
}
function currentContext() { return findCut(workspace?.id); }
function firstAvailableCut() {
  for (const p of projects.filter(p => !p.trashed)) for (const s of p.scenes.filter(s => !s.trashed)) if (s.cuts.length) return s.cuts[0].id;
  return null;
}
async function refreshProjects() { projects = await request("/api/projects"); }
function fillSelect(id, values, selected, label) {
  const select = $(id); select.replaceChildren(...values.map(v => new Option(label(v), v.id))); select.value = selected || "";
}
function renderNavigation() {
  const context = currentContext();
  if (!context) return;
  const { project, scene, cut } = context;
  fillSelect("project-select", projects.filter(p => !p.trashed), project.id, p => p.name);
  fillSelect("scene-select", project.scenes.filter(s => !s.trashed), scene.id, s => `${s.number}. ${s.title}${s.finalized ? t(" · terminata") : ""}`);
  fillSelect("cut-select", scene.cuts, workspace.id, c => `${c.number}. ${c.title}${c.confirmed_version_id ? t(" · confermato") : ""}`);
  $("workspace-path").textContent = tr`${project.name} / Scena ${scene.number} · ${scene.title}`;
  $("cut-title").textContent = workspace.title;
  $("cut-number").textContent = `Cut ${workspace.number}`;
  $("finalize-scene").textContent = scene.finalized ? t("Riapri la scena") : t("Termina e salva scena");
  $("new-cut").disabled = scene.finalized;
  $("finalize-scene").disabled = commandBusy;
  for (const id of ["project-select", "scene-select", "cut-select"]) $(id).disabled = navigationBusy || commandBusy;
}

function dialog(title, content, submit = t("Continua")) {
  return new Promise(resolve => {
    const panel = $("action-dialog");
    $("dialog-title").textContent = title; $("dialog-content").replaceChildren(content);
    $("dialog-error").textContent = ""; $("dialog-submit").textContent = submit; $("dialog-submit").hidden = !submit;
    $("dialog-submit").disabled = false;
    const finish = value => { panel.close(); $("dialog-form").onsubmit = null; panel.oncancel = null; resolve(value); };
    closeCurrentDialog = () => finish(false);
    $("dialog-form").onsubmit = event => { event.preventDefault(); finish(true); };
    $("dialog-cancel").onclick = () => finish(false);
    panel.oncancel = event => { event.preventDefault(); finish(false); };
    panel.showModal();
  });
}
async function askName(title, value = "", extra = null) {
  const label = el("label", "field"); label.append(el("span", "", t("Nome")));
  const input = el("input"); input.value = value; input.required = true; input.maxLength = 120; label.append(input);
  const content = extra ? el("div") : label;
  if (extra) content.append(label, extra);
  const accepted = await dialog(title, content, extra ? t("Crea cut") : t("Salva nome"));
  return accepted ? input.value : null;
}

async function preserveEdits() {
  if (draftDirty && !await saveDraft()) throw new Error(t("I campi sono cambiati durante il salvataggio. Riprova dopo aver terminato la modifica."));
  if (manualDirty) await saveManual();
}
async function switchCut(id) {
  if (navigationBusy || id === workspace?.id) { renderNavigation(); return; }
  navigationBusy = true;
  updateButtons();
  try {
    await preserveEdits();
    if (draftDirty || manualDirty) throw new Error(t("Restano modifiche locali: salvale prima di cambiare cut."));
    await refreshProjects();
    const view = await request(`/api/cuts/${id}`);
    clearTimeout(pollTimer); clearTimeout(assistanceTimer); manualDirty = false; localError = null; compileFailure = null;
    applyWorkspace(view, true);
    const url = new URL(location.href); url.searchParams.set("cut", id); history.replaceState(null, "", url);
    feedback(t("Cut aperto. Ogni cut conserva la propria bozza e le proprie versioni."));
  } catch (error) { feedback(error.message, true); }
  finally { navigationBusy = false; updateButtons(); }
}
function adoptView(view, tick) {
  workspace = view;
  if (tick === draftTick) { draft = normalizeDraft(view.draft_input); draftDirty = false; }
  else {
    for (const key of ["pictures", "active_units", "dialogues", "audio_references", "videos"]) {
      const identity = key === "active_units" ? "subject" : "id";
      for (const item of view.draft_input[key] || []) if (!draft[key].some(v => v[identity] === item[identity])) draft[key].push(clone(item));
    }
  }
  renderDraft(); renderResults();
}
async function uploadPicture(pictureId, file) {
  if (!await saveDraft()) return;
  const tick = draftTick;
  const media = await request("/api/media", { method: "POST", headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name) }, body: file });
  await mutation("PUT", `/api/cuts/${workspace.id}/pictures/${pictureId}/media`, {
    command_id: newCommandId(), expected_revision: workspace.revision, media_id: media.id
  }, view => {
    adoptView(view, tick);
    const local = draft.pictures.find(p => p.id === pictureId);
    if (local) { local.confirmed = false; local.linked_to_h3 = false; renderPictures(); }
    feedback(t("Immagine archiviata sul Mac. Puoi analizzarla su richiesta, correggere e confermare la descrizione e il collegamento a H3."));
  });
}

async function openLibrary() {
  if (draftDirty && !await saveDraft()) return;
  const projectId = workspace.project_id, sceneId = workspace.scene_id;
  const url = `/api/projects/${projectId}/library?scene_id=${sceneId}`;
  let library = await request(url);
  const content = el("div");
  content.append(el("p", "section-help", t("Scegli un’immagine o un Subject da usare nel cut, oppure spostalo nel cestino della libreria. Il cestino conserva gli usi già presenti nei cut e nelle versioni; puoi ripristinare gli elementi.")));
  const tabs = el('div','navigation-actions');
  const list = el("div", "library-list"); content.append(tabs,list);
  let chosen = null, showTrash = false, busy = false, libraryOpen = true;
  const draw = () => {
    chosen = null; $("dialog-submit").hidden = true;
    const count = (library.trashed_units?.length || 0) + (library.trashed_pictures?.length || 0);
    const active = button(t('Disponibili'),'button secondary small',()=>{showTrash=false;draw();});
    const trash = button(tr`Cestino della libreria · ${count}`,'button secondary small',()=>{showTrash=true;draw();});
    const refresh = button(t('Aggiorna elenco'),'button subtle small',async()=>{
      if(busy)return;
      busy=true; draw();
      try {library=await request(url); if(libraryOpen)$("dialog-error").textContent='';}
      catch(error){if(libraryOpen)$("dialog-error").textContent=error.message;}
      finally{busy=false;if(libraryOpen)draw();}
    });
    active.disabled = trash.disabled = refresh.disabled = busy;
    active.setAttribute('aria-pressed',String(!showTrash)); trash.setAttribute('aria-pressed',String(showTrash));
    tabs.replaceChildren(active,trash,refresh);
    list.replaceChildren(...renderLibraryRows(library,{
      trashed:showTrash,busy,canReuse:!currentContext()?.scene.finalized,
      unitIds:new Set(Object.values(workspace.unit_ids || {})),pictureIds:new Set(draft.pictures.map(p=>p.id))
    },{el,button,choose,setTrash,roleLabel:role=>roles.find(r=>r[0]===role)?.[1] || role}));
  };
  const setTrash = async(kind,item,trashed) => {
    if(busy)return;
    const command={command_id:newCommandId(),expected_revision:library.revision,expected_reference_revision:item.revision,trashed};
    busy=true;draw();
    try {
      await mutation('PUT',`/api/projects/${projectId}/library/${kind}/${item.id}/trash`,command,()=>{});
      library=await request(url);
      projects=await request('/api/projects');
      if(libraryOpen)$("dialog-error").textContent='';
      feedback(trashed ? t('Elemento spostato nel cestino della libreria. I cut conservano i propri riferimenti.') : t('Elemento ripristinato nella libreria.'));
    } catch(error) {
      if(libraryOpen)$("dialog-error").textContent=error.message;
      try {library=await request(url);} catch {}
    } finally {busy=false;if(libraryOpen)draw();}
  };
  const choose = (kind, item) => {
    chosen = { kind, item }; $("dialog-submit").hidden = false; $("dialog-submit").textContent = t("Usa nel cut");
    const dependencies = kind === "picture" ? [item.id] : unitPictureIds(item);
    const missing = dependencies.filter(id => !draft.pictures.some(p => p.id === id));
    list.replaceChildren(button(t('Torna all’elenco'),'button subtle small',draw),el("p", "section-help", tr`Riuso di ${item.name || (kind === "unit" ? `Subject ${item.subject || ''}` : "immagine")}. Assegna gli slot delle immagini necessarie.`));
    const used = new Set(draft.pictures.map(p => p.slot)); const available = Array.from({ length: 9 }, (_, i) => i + 1).filter(i => !used.has(i));
    if (missing.length > available.length) { list.append(el("p", "issues", t("Gli slot liberi non bastano. Rimuovi prima dal cut le immagini non utilizzate."))); chosen = null; $("dialog-submit").hidden = true; return; }
    chosen.slots = {};
    missing.forEach((id, index) => {
      const picture = library.pictures.find(p => p.id === id);
      const wrap = el("label", "field"); wrap.append(el("span", "", picture?.name || t("Immagine")));
      const select = el("select"); available.forEach(slot => select.append(new Option(`Picture ${slot}`, slot))); select.value = available[index];
      chosen.slots[id] = Number(select.value); select.onchange = () => { chosen.slots[id] = Number(select.value); };
      wrap.append(select); list.append(wrap);
    });
    if (!missing.length) list.append(el("p", "field-help", t("Gli slot già presenti restano quelli dichiarati. Ricarica immagine aggiorna esplicitamente descrizione e file dalla libreria; controlla di nuovo il collegamento H3.")));
  };
  draw();
  const accepted = await dialog(t("Libreria del progetto"), content, null);
  libraryOpen=false;
  if (!accepted || !chosen) return;
  const tick = draftTick;
  await mutation("POST", `/api/cuts/${workspace.id}/reuse`, { command_id: newCommandId(), expected_revision: workspace.revision,
    kind: chosen.kind, reference_id: chosen.item.id, slots: chosen.slots }, view => adoptView(view, tick));
  feedback(t("Riferimento riusato. Controlla gli slot e dichiara il collegamento a H3 nel nuovo cut."));
}

function updateConfirmationButtons() {
  for (const [id, saved] of [["proposal", displayedProposal()], ["manual", version(workspace?.manual_version_id)]]) {
    const issues = saved ? workspace.confirmation_issues?.[saved.id] || [] : [t("Nessuna versione salvata da confermare.")];
    const local = draftDirty || (id === "manual" && manualDirty);
    const already = saved && workspace?.confirmed_version_id === saved.id && workspace?.state === "confirmed";
    $( `confirm-${id}` ).disabled = !saved || already || Boolean(issues.length) || local || commandBusy || activeJob() || currentContext()?.scene.finalized;
    $( `confirm-${id}-reason` ).textContent = already ? t("Questa versione è già confermata.") : local ? t("Salva prima le modifiche locali per confermare una versione precisa.") : issues.join(" ");
  }
}
async function confirmVersion(saved) {
  const content = el("div");
  content.append(el("p", "section-help", tr`Confermi questa versione ${saved.origin === "manual" ? t("manuale") : t("generata")}, della durata di ${saved.duration_s} secondi. Il testo resterà esattamente quello mostrato.`));
  const list = el("ul", "snapshot-list");
  for (const picture of saved.input_snapshot?.pictures || []) {
    const media = saved.media_snapshot?.[picture.id];
    list.append(el("li", "", `Picture ${picture.slot} · ${picture.name || t("Immagine")}: ${picture.description_en}${media ? t(" · file gestito conservato") : t(" · riferimento dichiarato senza file")}`));
  }
  for (const unit of saved.input_snapshot?.active_units || []) {
    const mappings = (unit.sources || []).map(s => {
      if (s.origin === "context") return tr`${attributes.find(a => a[0] === s.attribute)?.[1] || s.attribute} dal contesto dichiarato`;
      const picture = (saved.input_snapshot.pictures || []).find(p => p.id === s.picture_id);
      return tr`${attributes.find(a => a[0] === s.attribute)?.[1] || s.attribute} da Picture ${picture?.slot ?? "?"}`;
    });
    list.append(el("li", "", `Subject ${unit.subject} · ${unit.name}: ${mappings.join(", ")}`));
    if (unit.scale) {
      const scale = unit.scale;
      const picture = saved.input_snapshot.pictures?.find(p => p.id === scale.picture_id);
      list.append(el('li', '', tr`Dimensioni e scala: ${scale.measurements || ''} · ${scale.comparison || ''}${scale.reference_subject ? tr` · rispetto a Subject ${scale.reference_subject}` : ''}${picture ? ` · Picture ${picture.slot}` : ''}`));
    }
    for (const detail of unit.physical_details || []) {
      const picture = saved.input_snapshot.pictures?.find(p => p.id === detail.picture_id);
      const operation = {add:t('Aggiunta'), replace:t('Sostituzione'), modify:t('Modifica')}[detail.operation] || t('Dettaglio');
      list.append(el('li', '', `${operation} · ${detail.body_location}: ${detail.description}${picture ? ` · Picture ${picture.slot}` : detail.origin === 'context' ? t(' · dal contesto') : ''}`));
    }
  }
  for (const video of saved.input_snapshot?.videos || []) if (video.id === saved.input_snapshot?.continuity?.video_id) list.append(el("li", "", `Video ${video.slot} · ${video.name || t("Sorgente di continuazione")} · ${video.duration_s} s ${video.duration_origin === "measured" ? t("misurati") : t("dichiarati")}`));
  if(saved.input_snapshot?.camera && hasCameraSelection(saved.input_snapshot.camera))list.append(el('li','',tr`Regia: ${cameraPreview(saved.input_snapshot.camera,directionOptions)} · ${cameraPhases.find(([key])=>key===saved.input_snapshot.camera.placement)?.[1] || t('Come indicato nella richiesta')}${saved.input_snapshot.camera.dialogue_id?' · '+saved.input_snapshot.camera.dialogue_id:''}${saved.input_snapshot.camera.notes?' · '+saved.input_snapshot.camera.notes:''}`));
  for(const [kind,refs] of [['Picture',saved.input_snapshot?.pictures||[]],['Video',saved.input_snapshot?.videos||[]]])for(const ref of refs)if(ref.guidance?.enabled) {
    const role=(kind==='Picture'?pictureRoles:videoRoles).find(([key])=>key===ref.role)?.[1] || ref.role;
    const mappings=(ref.guidance.mappings||[]).map(m=>`${m.figure} → ${m.subject?'Subject '+m.subject: m.role==='camera_start'?t('Punto iniziale camera'):t('Direzione camera')}`).join('; ');
    const anchor={first:t('Primo frame'),last:t('Ultimo frame'),keyframe:t('Keyframe intermedio')}[ref.guidance.anchor];
    list.append(el('li','',tr`Guida ${kind} ${ref.slot} · ${role}${kind==='Video'?' · '+ref.duration_s+' s':''}${mappings?': '+mappings:''}${anchor?' · '+anchor:''}${ref.guidance.at_s!=null?' · '+ref.guidance.at_s+' s':''}${ref.guidance.workflow?' · '+ref.guidance.workflow:''}${ref.guidance.prompt_en?t(' · Prompt guida: ')+ref.guidance.prompt_en:''}`));
  }
  if (saved.input_snapshot?.continuity?.mode !== "none" && saved.input_snapshot?.continuity) list.append(el("li", "", tr`Continuità ${saved.input_snapshot.continuity.mode}: ${saved.input_snapshot.continuity.declared_state || "stato mancante"}`));
  content.append(list);
  const check = el("label", "check-label"); const input = el("input"); input.type = "checkbox"; input.required = true;
  check.append(input, el("span", "", t("Ho controllato il testo e le sorgenti di immagini, video e continuità, anche se differiscono dalla bozza o dalla versione di origine."))); content.append(check);
  if (!await dialog(t("Conferma il cut"), content, t("Conferma versione"))) return;
  await mutation("POST", `/api/cuts/${workspace.id}/confirm`, { command_id: newCommandId(), expected_revision: workspace.revision,
    version_id: saved.id, acknowledge_reference_changes: input.checked }, async view => {
      workspace = view; await refreshProjects(); renderNavigation(); renderConfirmedCuts();
    });
  feedback(workspace.state === "confirmed" ? t("Cut confermato. Testo e snapshot conservati sul Mac.") : t("Versione confermata e conservata. La bozza più recente resta separata e da rivedere."));
}
async function renderConfirmedCuts() {
  const context = currentContext(); const target = $("confirmed-cuts"); target.replaceChildren();
  if (!context) return;
  const currentId = workspace.id;
  const cuts = context.scene.cuts;
  const known = cuts.filter(c=>c.duration_s != null);
  const total = known.reduce((sum,c)=>sum+c.duration_s,0);
  target.append(el("p","section-help",tr`Durata utile prevista: ${Number(total.toFixed(2))} s${known.length<cuts.length?tr` · incompleta (${cuts.length-known.length} cut senza durata)`:""}. Le durate dei file video restano separate; nessun trim viene sottratto automaticamente.`));
  for (const cut of cuts) {
    const details = el("details", "confirmed-card");
    details.append(el("summary", "", `Cut ${cut.number} · ${cut.title} · ${cut.duration_s ?? "—"} s ${cut.duration_origin === "declared" ? t("dichiarati") : cut.duration_origin === "measured" ? t("da audio misurato") : t("stimati")} · ${cut.state === "confirmed" ? t("confermato") : t("da rivedere")}${cut.output_duration_s != null ? tr` · file video ${cut.output_duration_s.toFixed(3)} s` : ""}`));
    const body = el("div"); details.append(body); target.append(details);
    details.addEventListener("toggle", async () => {
      if (!details.open || body.children.length) return;
      try {
        const view = await request(`/api/cuts/${cut.id}`); if (workspace.id !== currentId) return;
        const saved = view.versions.find(v => v.id === (cut.selected_version_id || cut.confirmed_version_id));
        if (!saved) {body.append(el("p","field-help",t("Nessuna versione conservata per questo cut.")));return;}
        if(view.output_by_version?.[saved.id])body.append(videoPreview(view.output_by_version[saved.id]));
        body.append(el("pre", "prompt-text", saved.text), button(cut.confirmed_version_id === saved.id ? t("Copia confermato") : t("Copia versione da rivedere"), "button secondary small", async () => {
          try { const text = await request(`/api/cuts/${cut.id}/text?version_id=${saved.id}`, {}, true); await copyText(text, cut.confirmed_version_id === saved.id ? t("Prompt confermato copiato.") : t("Versione da rivedere copiata.")); } catch (error) { feedback(error.message, true); }
        }));
      } catch (error) { body.append(el("p", "issues", error.message)); }
    });
  }
}

async function createNamed(kind) {
  const context = currentContext();
  const label = { project: t("Nuovo progetto"), scene: t("Nuova scena"), cut: t("Nuovo cut") }[kind];
  let inheritReferences = true;
  const inheritance = kind === "cut" ? checkbox(t("Eredita Picture e Subject dall’ultimo cut della scena"), true,
    value => { inheritReferences = value; }, { draft: false }) : null;
  const name = await askName(label, "", inheritance); if (name === null) return;
  await preserveEdits();
  const path = kind === "project" ? "/api/projects" : kind === "scene" ? `/api/projects/${context.project.id}/scenes` : `/api/scenes/${context.scene.id}/cuts`;
  const expected = kind === "project" ? 0 : kind === "scene" ? context.project.revision : context.scene.revision;
  const command = { command_id: newCommandId(), expected_revision: expected, name };
  if (kind === "cut") command.inherit_references = inheritReferences;
  await mutation("POST", path, command, async result => {
    await refreshProjects();
    const id = kind === "project" ? result.scenes[0].cuts[0].id : kind === "scene" ? result.cuts[0].id : result.id;
    await switchCut(id);
    if (kind === "cut") {
      studioLayout.selectSection('continuity');
      const pictures = result.draft_input.pictures.length, subjects = result.draft_input.active_units.length;
      const inherited = pictures || subjects ? tr`Riferimenti ereditati dall’ultimo cut (${pictures} Picture, ${subjects} Subject). ` : t("Nuovo cut pronto. ");
      feedback(inherited + (pictures ? t("Verifica il collegamento delle Picture a H3. ") : "") + t("Il cut precedente è nella sezione Continuità per impostare il raccordo."));
    }
  });
}
async function showEmptyArchive() {
  $("application").hidden = true;
  const text = el("p", "section-help", t("Non ci sono progetti attivi. Puoi crearne uno o ripristinare dal cestino un progetto esistente."));
  const actions = el("div"); actions.append(text, button(t("Nuovo progetto"), "button primary", async () => {
    closeCurrentDialog(); const name = await askName(t("Nuovo progetto")); if (name === null) return initialize();
    await request("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ command_id: newCommandId(), expected_revision: 0, name }) });
    await initialize();
  }), button(t("Apri cestino"), "button secondary", () => { closeCurrentDialog(); manageArchive(); }),
  button(t('Impostazioni utente'), 'button secondary', async () => {
    closeCurrentDialog(); $("application").hidden = false; workspace = null;
    await accessSettings(); updateButtons();
  }));
  await dialog(t("Archivio"), actions, null);
}
async function manageArchive() {
  await refreshProjects();
  const content = el("div"); const context = currentContext();
  const addRow = (table, item, label) => {
    const row = el("div", "archive-row"); row.append(el("p", "", `${label}${item.trashed ? t(" · nel cestino") : ""}`));
    if (!item.trashed) row.append(button(t("Rinomina"), "button secondary small", async () => {
      closeCurrentDialog(); const name = await askName(t("Rinomina"), table === "projects" ? item.name : item.title); if (name === null) return;
      try { await preserveEdits(); await request(`/api/${table}/${item.id}/name`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ command_id: newCommandId(), expected_revision: table === "cuts" ? workspace.revision : item.revision, name }) }); await refreshProjects(); if (workspace) { workspace = await request(`/api/cuts/${workspace.id}`); renderNavigation(); } } catch (error) { feedback(error.message, true); }
    }));
    row.append(button(item.trashed ? t("Ripristina") : t("Sposta nel cestino"), "button subtle danger", async () => {
      closeCurrentDialog();
      if (!item.trashed) {
        const explanation = el("p", "section-help", t("Il contenuto resta conservato e potrà essere ripristinato dal cestino."));
        if (!await dialog(tr`Spostare ${label} nel cestino?`, explanation, t("Sposta nel cestino"))) return;
      }
      try {
        const currentCut = table === "cuts" && item.id === workspace?.id;
        if (workspace && !(currentCut && item.trashed)) await preserveEdits();
        const expected_revision = currentCut && !item.trashed ? workspace.revision : item.revision;
        const result = await request(`/api/${table}/${item.id}/trash`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ command_id: newCommandId(), expected_revision, trashed: !item.trashed }) });
        await refreshProjects();
        if (!findCut(workspace?.id)) {
          const next = (table === "cuts" && result.cuts[0]?.id) || firstAvailableCut();
          if (next) await switchCut(next);
          else { workspace = null; draft = null; await showEmptyArchive(); }
        } else { renderNavigation(); renderConfirmedCuts(); }
      } catch (error) { feedback(error.message, true); }
    }));
    if(item.trashed)row.append(button(t('Elimina definitivamente'),'button subtle danger',async()=>{closeCurrentDialog();try{await purgeArchive({scope:table.slice(0,-1),resource_id:item.id});}catch(error){feedback(error.message,true);}}));
    content.append(row);
  };
  if (context) { addRow("projects", context.project, context.project.name); addRow("scenes", context.scene, tr`Scena ${context.scene.number} · ${context.scene.title}`); addRow("cuts", workspace, `Cut ${workspace.number} · ${workspace.title}`); }
  for (const p of projects) {
    if (p.trashed) addRow("projects", p, p.name);
    else for (const s of p.scenes) {
      if (s.trashed) addRow("scenes", s, `${p.name} / ${s.title}`);
      else for (const cut of s.trashed_cuts || []) addRow("cuts", {...cut, trashed:true}, `${p.name} / ${s.title} / Cut ${cut.number} · ${cut.title}`);
    }
  }
  if(projects.some(p=>p.trashed||p.scenes.some(s=>s.trashed||s.trashed_cuts?.length)))content.append(button(t('Svuota il cestino'),'button subtle danger',async()=>{closeCurrentDialog();try{await purgeArchive({scope:'trash'});}catch(error){feedback(error.message,true);}}));
  await dialog(t("Nomi e cestino"), content, null);
}

function showLogin() { $("application").hidden = true; $("login-panel").hidden = false; clearTimeout(pollTimer); $("login-password").focus(); }
async function accessSettings() {
  studioLayout.selectSection('settings', {focus: true});
  if (!workspace) { await userSettings.load(); await loadAssistance(); }
}

$("project-select").onchange = () => {
  const project = projects.find(p => p.id === $("project-select").value);
  const scene = project?.scenes.find(s => !s.trashed && s.cuts.length); if (scene) withCommand(() => switchCut(scene.cuts[0].id)); else renderNavigation();
};
$("scene-select").onchange = () => {
  const scene = currentContext()?.project.scenes.find(s => s.id === $("scene-select").value);
  if (scene?.cuts.length) withCommand(() => switchCut(scene.cuts[0].id));
};
$("cut-select").onchange = event => {
  // withCommand ridisegna i menu: acquisire la destinazione prima di bloccarli.
  const cutId = event.currentTarget.value;
  withCommand(() => switchCut(cutId));
};
for (const kind of ["project", "scene", "cut"]) $( `new-${kind}` ).onclick = () => withCommand(() => createNamed(kind));
$("open-library").onclick = () => withCommand(openLibrary);
$("manage-library").onclick = () => withCommand(openLibrary);
$("cancel-job").onclick = () => withCommand(async () => {
  await mutation("POST", `/api/jobs/${workspace.latest_job.id}/cancel`, { command_id: newCommandId(), expected_revision: workspace.revision }, view => { workspace = view; clearTimeout(pollTimer); });
  feedback(t("Proposta annullata; campi e versioni già salvate restano conservati."));
});
$("confirm-proposal").onclick = () => withCommand(() => confirmVersion(displayedProposal()));
$("confirm-manual").onclick = () => withCommand(() => confirmVersion(version(workspace.manual_version_id)));
$("manage-archive").onclick = () => withCommand(manageArchive);
$("access-settings").textContent = t('Impostazioni utente');
$("access-settings").onclick = () => accessSettings().catch(error => feedback(error.message, true));
$("finalize-scene").onclick = () => withCommand(async () => {
  await preserveEdits(); const { scene } = currentContext();
  await mutation("PUT", `/api/scenes/${scene.id}/finalize`, { command_id: newCommandId(), expected_revision: scene.revision, finalized: !scene.finalized }, async () => {
    await refreshProjects(); renderNavigation(); renderResults();
  });
  feedback(scene.finalized ? t("Scena riaperta: puoi modificare i cut.") : t("Scena terminata e salvata senza chiamare il modello."));
});
$("login-form").onsubmit = async event => {
  event.preventDefault();
  try {
    const result = await request("/api/access/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("login-password").value }) });
    const local = workspace ? { id: workspace.id, input: clone(draft), dirty: draftDirty, manual: $("manual-text").value, manualDirty, base: manualBaseId } : null;
    $("login-password").value = ""; csrf = result.csrf; $("login-error").textContent = ""; await initialize();
    if (local && local.id === workspace?.id) {
      if (local.dirty) { draft = local.input; markDraft(); renderDraft(); }
      if (local.manualDirty) { $("manual-text").value = local.manual; manualDirty = true; manualBaseId = local.base; }
      renderResults();
    }
  } catch (error) { $("login-error").textContent = error.message; }
};
$("logout").onclick = async () => {
  try { await preserveEdits(); await request("/api/access/logout", { method: "POST" }); showLogin(); }
  catch (error) { feedback(error.message, true); }
};

let mentionStart = null;
$("request").addEventListener("input", () => {
  const input = $("request"); const before = input.value.slice(0, input.selectionStart); const match = before.match(/(?:^|\s)#([^\s<>]*)$/);
  const menu = $("mention-menu"); menu.replaceChildren();
  if (!match) { menu.hidden = true; mentionStart = null; return; }
  mentionStart = before.lastIndexOf("#");
  const query = match[1].toLowerCase();
  for (const candidate of referenceChoices().filter(c => c.label.toLowerCase().includes(query))) {
    const range = { start: mentionStart, end: input.selectionStart };
    menu.append(button(candidate.label, "button subtle", () => withCommand(() => chooseReference(candidate, range))));
  }
  if (!menu.children.length) menu.append(el("p", "field-help", t("Nessun richiamo salvato corrispondente. Salva la bozza dopo aver aggiunto le associazioni.")));
  menu.hidden = false;
});
$("request").addEventListener("keydown", event => {
  if (event.key === "Escape") $("mention-menu").hidden = true;
  if (event.key === "ArrowDown" && !$("mention-menu").hidden) { event.preventDefault(); $("mention-menu").querySelector("button")?.focus(); }
});


function serverButton(label, action, kind = "", target = "") {
  const node = button(label, "button secondary small", () => withCommand(action));
  node.dataset.serverCommand = "true"; node.dataset.assistanceAction = kind; node.dataset.target = target;
  node.disabled = commandBusy || Boolean(currentContext()?.scene.finalized);
  return node;
}
function assistancePanel(targetId) {
  const node = el("div", "assistance-proposals"); node.dataset.assistanceFor = targetId; return node;
}
function proxyControls(picture) {
  const details = el("details", "proxy-controls"); details.append(el("summary", "", t("Proxy di analisi · facoltativo")));
  const proxy = workspace?.proxy_by_picture?.[picture.id];
  details.append(el("p", "field-help", proxy ? tr`L’analisi usa ${proxy.display_name}. Il file destinato a H3 rimane separato.` : t("L’analisi usa il file della Picture. Puoi scegliere una foto semplice come proxy, mantenendo il character sheet o altro file finale per H3.")));
  if (proxy) {
    const preview = el("img", "picture-preview"); preview.src = `/api/media/${proxy.id}`; preview.alt = t("Proxy di analisi"); details.append(preview);
    details.append(serverButton(t("Analizza il file finale invece del proxy"), async () => {
      if (draftDirty && !await saveDraft()) return;
      const tick = draftTick;
      await mutation("POST", `/api/cuts/${workspace.id}/pictures/${picture.id}/proxy/reset`, { command_id: newCommandId(), expected_revision: workspace.revision }, view => adoptView(view, tick));
    }));
  }
  const label = el("label", "upload-control", t("Scegli immagine proxy")); const input = el("input"); input.type = "file"; input.accept = "image/jpeg,image/png,image/webp";
  input.onchange = () => { if (input.files[0]) withCommand(() => uploadProxy(picture.id, input.files[0])); }; label.append(input); details.append(label);
  return details;
}
async function uploadProxy(pictureId, file) {
  if (draftDirty && !await saveDraft()) return;
  const media = await request("/api/media", { method: "POST", headers: { "X-File-Name": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" }, body: file });
  const tick = draftTick;
  await mutation("PUT", `/api/cuts/${workspace.id}/pictures/${pictureId}/proxy`, { command_id: newCommandId(), expected_revision: workspace.revision, media_id: media.id }, view => adoptView(view, tick));
  feedback(t("Proxy impostato per l’analisi. Il file finale e le associazioni H3 restano quelli dichiarati."));
}
async function loadAssistance(initial = true) {
  const result = await Promise.allSettled([request("/api/assistance/models"), request("/api/assistance/settings"), request("/api/assistance/asr")]);
  if (result[0].status === "fulfilled") assistanceModels = result[0].value;
  if (result[1].status === "fulfilled") modelSettings = result[1].value;
  if (result[2].status === "fulfilled") asrState = result[2].value;
  const selected = initial ? modelSettings.vision_model || '' : $("vision-model").value;
  const text = initial ? modelSettings.text_model || '' : $("model").value;
  if (initial) { $("text-service").value = serviceFor(text); $("vision-service").value = serviceFor(selected); }
  fillModelChoices('model', 'text-service', 'completion', text);
  fillModelChoices('vision-model', 'vision-service', 'vision', selected);
  $("asr-status").textContent = diagnostic(asrState.message);
  updateAssistanceControls(); refreshAssistancePanels();
}
function fillModelChoices(id, serviceId, capability, selected = '') {
  const values = eligibleModels(assistanceModels, $(serviceId).value, capability);
  const choices = values.map(m => new Option(`${modelLabel(m)}${capability === 'vision' ? m.vision_tested ? t(' · verificato') : t(' · da verificare') : ''}`, m.name));
  if (selected && !values.some(m => m.name === selected)) choices.push(new Option(tr`${modelLabel({name:selected})} · non disponibile`, selected));
  $(id).replaceChildren(new Option(capability === 'vision' ? t('Scegli un modello vision') : t('Scegli un modello testo'), ''), ...choices);
  $(id).value = selected;
  $(id).disabled = false;
}
function updateAssistanceControls() {
  if (!$("vision-model")) return;
  const chosen = assistanceModels.find(m => m.name === $("vision-model").value);
  const finalized = Boolean(currentContext()?.scene.finalized);
  $("save-models").disabled = commandBusy || !$("model").value || !$("vision-model").value;
  $("test-vision").disabled = !chosen || commandBusy;
  $("test-text").disabled = !$("model").value || commandBusy;
  $("model-destination").textContent = tr`Testo → ${$("text-service").value === 'openai' ? t('OpenAI · servizio remoto') : t('server Ollama configurato')}. Immagini → ${$("vision-service").value === 'openai' ? t('OpenAI · servizio remoto') : t('server Ollama configurato')}.`;
  const saved = modelSettings.text_model === $("model").value && (modelSettings.vision_model || '') === $("vision-model").value;
  const textAvailable = assistanceModels.some(m => m.name === $("model").value && m.capabilities.includes('completion'));
  $("configuration-state").textContent = !saved ? t('Selezioni modificate: salva per renderle persistenti.') : chosen?.vision_tested && textAvailable ? t('Configurazione completa: modello vision selezionato e verificato.') : t('Configurazione incompleta: servono un modello testo disponibile e un modello vision selezionato e verificato.');
  $("vision-status").textContent = chosen ? chosen.vision_tested ? t("Modello vision verificato con un’immagine di prova. Ogni analisi produce una proposta da rivedere.") : t("Capacità vision dichiarata. Premi Verifica modello vision prima dell’analisi delle tue immagini.") : t("Scegli un modello vision separato dal modello testo.");
  if (chosen?.capabilities_unknown && !chosen.vision_tested) $("vision-status").textContent = t('Il servizio non dichiara la capacità visiva nella lista modelli. Esegui la verifica con un’immagine sintetica prima di analizzare le tue foto.');
  if (chosen?.capabilities.includes("thinking")) $("vision-status").textContent += t(" L’app richiede una risposta diretta. Se il modello continua a ragionare, l’analisi può essere più lenta o esaurire il limite senza una descrizione. In quel caso puoi scegliere un altro modello oppure la variante instruct se già installata.");
  for (const node of document.querySelectorAll("[data-assistance-action]")) {
    let enabled = true;
    if (node.dataset.assistanceAction === "analyze") enabled = Boolean(chosen?.vision_tested && (workspace?.proxy_by_picture?.[node.dataset.target] || workspace?.media_by_picture?.[node.dataset.target]));
    if (node.dataset.assistanceAction === "character-sheet") enabled = Boolean(chosen?.vision_tested && workspace?.media_by_picture?.[node.dataset.target] && selectedAnalysis(draft.pictures.find(p=>p.id===node.dataset.target),imageAnalysisOptions).category === 'character');
    if (node.dataset.assistanceAction === "translate") enabled = textAvailable && (draft?.pictures.find(p => p.id === node.dataset.target)?.description_language || "English") !== "English";
    if (node.dataset.assistanceAction === "asr") enabled = asrState.available && Boolean(draft?.audio_references.find(a => a.id === node.dataset.target)?.media_id);
    if (node.dataset.assistanceAction === "apply") enabled = !draftDirty && !(workspace?.assistance_jobs || []).find(j => j.id === node.dataset.job)?.stale;
    if (node.dataset.assistanceAction === "context_subject") enabled = Boolean(draft?.continuity.previous_version_id) && !draft?.active_units.some(u=>u.subject===Number(node.dataset.target));
    node.disabled = !enabled || commandBusy || finalized;
  }
  for (const reason of document.querySelectorAll("[data-analysis-reason]")) {
    const hasFile = workspace?.proxy_by_picture?.[reason.dataset.analysisReason] || workspace?.media_by_picture?.[reason.dataset.analysisReason];
    reason.textContent = !hasFile ? t("Carica il file della Picture o un proxy per l’analisi; la descrizione manuale resta disponibile.") : !chosen ? t("Scegli il modello vision in Impostazioni.") : !chosen.vision_tested ? t("Verifica prima il modello vision selezionato.") : "";
  }
  for (const input of document.querySelectorAll('input[type="file"]')) input.disabled = commandBusy || (finalized && !input.dataset.resultVideo);
}
async function requestAssistance(kind, targetId = null, force = false) {
  if (draftDirty && !await saveDraft()) { feedback(t("Salva prima gli ultimi campi.")); return; }
  const model = kind === "audio_asr" ? "local-whisper" : kind === "description_translate" ? $("model").value : $("vision-model").value;
  if (!model) throw new Error(t("Scegli prima il modello da usare."));
  await mutation("POST", `/api/cuts/${workspace.id}/assistance`, { command_id: newCommandId(), expected_revision: workspace.revision, kind, target_id: targetId, model, force }, job => {
    workspace.assistance_jobs = [...(workspace.assistance_jobs || []).filter(j => j.id !== job.id), job];
    startAssistancePolling(); refreshAssistancePanels();
  });
  feedback(t("Richiesta conservata. La descrizione o trascrizione corrente resta modificabile."));
}
function mergePolledView(view) {
  if (view.id !== workspace?.id) return;
  const base = workspace.revision;
  workspace = view;
  if (view.revision !== base) {
    workspace.revision = base;
    localError = { title: t("La bozza sul Mac è cambiata"), message: t("I campi locali sono conservati. Recupera la versione server prima di salvarli.") };
    $("recovery").hidden = false;
  }
}
function startAssistancePolling() {
  clearTimeout(assistanceTimer);
  if (!(workspace?.assistance_jobs || []).some(j => ["queued", "running"].includes(j.status))) return;
  const cutId = workspace.id;
  assistanceTimer = setTimeout(async () => {
    try {
      const before = workspace.assistance_jobs || [];
      const view = await request(`/api/cuts/${cutId}`); if (workspace.id !== cutId) return;
      mergePolledView(view);
      if (before.some(j => j.kind === "vision_trial" && ["queued", "running"].includes(j.status)) && !view.assistance_jobs.some(j => j.kind === "vision_trial" && ["queued", "running"].includes(j.status))) await loadAssistance(false);
      renderResults(); startAssistancePolling();
    } catch (error) {
      $("assistance-status").textContent = error.message;
      if (workspace?.id === cutId) assistanceTimer = setTimeout(startAssistancePolling, 1500);
    }
  }, 800);
}
function refreshAssistancePanels() {
  const jobs = workspace?.assistance_jobs || [];
  const trial = jobs.filter(j => j.kind === "vision_trial").at(-1);
  $("assistance-status").textContent = trial ? ["queued", "running"].includes(trial.status) ? tr`Verifica vision ${trial.status === "queued" ? t("in coda") : t("in corso")}…` : trial.status === "succeeded" ? t("Prova vision superata: forme e colori riconosciuti.") : (trial.result?.issues || []).map(diagnostic).join(" ") : "";
  for (const panel of document.querySelectorAll("[data-assistance-for]")) {
    panel.replaceChildren();
    const matching = jobs.filter(j => j.target_id === panel.dataset.assistanceFor);
    // Ultime varianti per profilo/livello; lavori attivi sempre annullabili.
    const picture = draft?.pictures.find(p=>p.id === panel.dataset.assistanceFor);
    for (const job of analysisProposals(matching,picture,imageAnalysisOptions)) {
      const box = el("div", "analysis-proposal");
      const title = { image_analyze: t("Analisi immagine"), image_character_sheet: t("Analisi character sheet"), description_translate: t("Traduzione"), audio_asr: t("Trascrizione") }[job.kind];
      box.append(el("strong", "", `${title} · ${job.model}`));
      if(job.analysis)box.append(el('p','field-help',analysisLabel(job.analysis,imageAnalysisOptions)));
      if (["queued", "running"].includes(job.status)) {
        box.append(el("p", "field-help", job.status === "queued" ? t("In coda…") : t("Elaborazione in corso…")), serverButton(t("Annulla operazione"), () => cancelAssistance(job)));
      }
      else if (job.result?.text) {
        box.append(el("p", "proposed-description", job.result.text));
        for (const warning of job.result.warnings || []) box.append(el('p','analysis-warning',warning));
        const metrics = job.result.metrics;
        box.append(el("p", "field-help", `${metrics?.cache_hit ? t("Analisi riusata dalla cache · nessuna inferenza") : tr`${metrics?.inference_calls ?? "—"} chiamata · ${metrics?.wall_s?.toFixed(2) ?? "—"} s`}${job.stale ? t(" · riferimento modificato: testo attuale conservato") : ""}`));
        const apply = serverButton(t("Usa proposta nei campi"), () => applyAssistance(job));
        apply.dataset.assistanceAction = "apply"; apply.dataset.job = job.id;
        apply.disabled = commandBusy || job.stale || draftDirty || Boolean(currentContext()?.scene.finalized);
        box.append(apply);
        if (draftDirty && !job.stale) box.append(el("p", "field-help", t("Salva la bozza per verificare che questa proposta sia ancora attuale.")));
        if (job.analysis && job.stale) box.append(el('p','field-help',t('Per riproporre un livello già analizzato, selezionalo e premi Analizza. La cache verrà riusata se immagine e impostazioni corrispondono.')));
        box.append(serverButton(job.analysis ? t("Analizza selezione attuale senza cache") : t("Nuova analisi senza cache"), () => requestAssistance(job.kind, job.target_id, true)));
      } else {
        // Le ricevute storiche restano intatte: chiarisci anche i vecchi errori
        // M3 che esponevano un messaggio generico pur registrando la troncatura.
        const message = job.result?.metrics?.error_code === "truncated_response" ? t("Risposta del modello interrotta al limite di output: nessuna proposta completa. Riprova esplicitamente o scegli un altro modello.") : (job.result?.issues || [t("Operazione non disponibile.")]).map(diagnostic).join(" ");
        box.append(el("p", "issues", message));
      }
      panel.append(box);
    }
  }
}
async function cancelAssistance(job) {
  await mutation("POST", `/api/cuts/${workspace.id}/assistance/${job.id}/cancel`, { command_id: newCommandId(), expected_revision: workspace.revision }, value => {
    workspace.assistance_jobs = workspace.assistance_jobs.map(j => j.id === value.id ? value : j); refreshAssistancePanels();
  });
}
async function applyAssistance(job) {
  if (draftDirty) throw new Error(t("Salva la bozza prima di applicare una proposta."));
  const tick = draftTick;
  await mutation("POST", `/api/cuts/${workspace.id}/assistance/${job.id}/apply`, { command_id: newCommandId(), expected_revision: workspace.revision }, view => adoptView(view, tick));
  feedback(t("Proposta applicata ai campi come testo da controllare. Correggila e confermala prima della compilazione."));
}
function enableDrop(node, upload) {
  node.addEventListener("dragover", event => { if ([...(event.dataTransfer?.types || [])].includes("Files")) { event.preventDefault(); event.stopPropagation(); node.classList.add("dragging"); } });
  node.addEventListener("dragleave", () => node.classList.remove("dragging"));
  node.addEventListener("drop", event => {
    const files = [...(event.dataTransfer?.files || [])]; if (!files.length) return;
    event.preventDefault(); event.stopPropagation(); node.classList.remove("dragging");
    withCommand(() => upload(files));
  });
}
async function uploadFiles(kind, files) {
  const items = kind === "picture" ? draft.pictures : draft.audio_references;
  const limit = kind === "picture" ? 9 : 3;
  const used = kind === "audio" ? items.filter(audio => audio.media_id).length : items.length;
  if (used + files.length > limit) throw new Error(tr`Nel cut restano ${limit - used} slot liberi. Scegli meno file.`);
  for (const file of files) {
    // Validare il file prima di creare una traccia, riusando prima quelle vuote.
    const media = kind === "audio" ? await uploadAudioMedia(file) : null;
    const key = kind === "picture" ? "pictures" : "audio_references";
    const known = new Set(draft[key].map(item => item.id));
    let item = kind === "audio" ? draft.audio_references.find(audio => !audio.media_id) : null;
    if (!item) {
      await addItem(kind);
      item = draft[key].find(item => !known.has(item.id));
    }
    if (kind === "picture") await uploadPicture(item.id, file); else await uploadAudio(item.id, file, media);
  }
  feedback(tr`${files.length} file archiviati. Ruoli, descrizioni, segmenti e collegamenti H3 restano da controllare e confermare.`);
}
async function uploadAudioMedia(file) {
  const status = $("audio-upload-status");
  status.textContent = tr`Caricamento di ${file.name}…`;
  status.className = "field-help";
  try {
    return await request("/api/audio-media", { method: "POST", headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name) }, body: file });
  } catch (error) {
    status.textContent = tr`File non caricato · ${file.name}. ${error.message}`;
    status.className = "issues";
    throw error;
  }
}
async function uploadAudio(id, file, uploadedMedia = null) {
  const cutId = workspace.id;
  const target = draft.audio_references.find(audio => audio.id === id);
  if (!target) throw new Error(t("La traccia audio da caricare non è più presente nel cut."));
  const original = clone(target);
  if (draftDirty) await saveDraft();
  const tick = draftTick;
  const media = uploadedMedia || await uploadAudioMedia(file);
  if (workspace.id !== cutId || !draft.audio_references.some(audio => audio.id === id)) {
    throw new Error(t("La traccia audio è stata rimossa o il cut è cambiato durante il caricamento."));
  }
  await mutation("PUT", `/api/cuts/${cutId}/audio/${id}/media`, { command_id: newCommandId(), expected_revision: workspace.revision, media_id: media.id }, view => {
    if (workspace.id !== cutId) return;
    const current = draft.audio_references.find(audio => audio.id === id);
    if (tick === draftTick) adoptView(view, tick);
    else {
      workspace = view;
      if (current) applyUploadedAudio(current, view.draft_input.audio_references.find(audio => audio.id === id), original);
      renderDraft(); renderResults();
    }
  });
  $("audio-upload-status").textContent = tr`File associato · ${file.name}. Puoi ascoltarlo con il lettore.`;
  $("audio-upload-status").className = "field-help";
  studioLayout.selectSection('audio'); feedback(t("Audio misurato dai campioni e conservato. Seleziona ruolo, segmento e parlante prima di confermare."));
}
function renderAudioTimeline() {
  const panel = $("audio-timeline");
  const { declared, limit, tracks, overlaps } = audioTimeline(draft.audio_references, draft.declared_duration_s);
  panel.hidden = tracks.length === 0;
  const label = ({ audio }) => audio.name ? `Audio ${audio.slot} · ${audio.name}` : `Audio ${audio.slot}`;
  const seconds = (value) => `${timelineSeconds.format(value)} s`;
  const range = ({ start, end }) => `${seconds(start)} – ${seconds(end)}`;
  const scale = Math.max(limit, ...tracks.map(track => track.end));
  $("audio-timeline-limit").textContent = `${declared ? t("Durata dichiarata del cut") : t("Limite del cut")} · ${seconds(limit)}`;
  $("audio-timeline-reference").hidden = !tracks.some(({ audio }) => audio.mode === "reference");
  $("audio-timeline-scale-end").textContent = seconds(scale);
  $("audio-timeline-tracks").replaceChildren(...tracks.map(track => {
    const row = el("li", "audio-timeline-row");
    const title = el("div", "audio-timeline-label");
    title.append(el("strong", "", label(track)), el("span", "audio-timeline-range", range(track)));
    const rail = el("div", "audio-timeline-rail");
    rail.setAttribute("aria-hidden", "true");
    const bar = el("span", track.overrun ? "audio-timeline-bar overrun" : "audio-timeline-bar");
    bar.style.left = `${100 * (track.start / scale)}%`;
    bar.style.width = `${100 * ((track.end - track.start) / scale)}%`;
    rail.append(bar);
    if (scale > limit) {
      const boundary = el("span", "audio-timeline-boundary");
      boundary.style.left = `${100 * (limit / scale)}%`;
      rail.append(boundary);
    }
    row.append(title, rail);
    return row;
  }));
  const warnings = [
    ...overlaps.map(({ first, second, start, end }) => tr`${label(first)} e ${label(second)} si sovrappongono tra ${seconds(start)} e ${seconds(end)}. Se devono parlare in sequenza, controlla «Inizio nel cut».`),
    ...tracks.filter(track => track.overrun).map(track => tr`${label(track)} termina a ${seconds(track.end)}, oltre ${declared ? "la durata dichiarata" : "il limite del cut"} (${seconds(limit)}).`),
  ];
  showIssues($("audio-timeline-warnings"), warnings);
}

function renderAudio() {
  renderAudioTimeline();
  const target = $("audio-references");
  const open = new Map([...target.querySelectorAll("[data-audio]")].map(node => [node.dataset.audio, node.open]));
  target.replaceChildren();
  for (const audio of draft.audio_references || []) {
    const item = el("section", "audio-item");
    const media = workspace?.audio_media?.[audio.id];
    if (media) {
      const playback = el("div", "audio-playback");
      playback.append(el("strong", "", tr`Ascolta Audio ${audio.slot} · ${media.display_name}`));
      const player = el("audio"); player.controls = true; player.preload = "metadata";
      player.setAttribute("aria-label", tr`Ascolta Audio ${audio.slot} · ${media.display_name}`);
      player.src = `/api/audio-media/${media.id}`;
      player.onerror = () => {
        if (!playback.querySelector(".audio-error")) playback.append(el("p", "issues audio-error", t("Audio non riproducibile. Ricarica il cut oppure carica nuovamente il file.")));
      };
      playback.append(player, el("p", "field-help", tr`${media.duration_s.toFixed(3)} s · ${media.sample_rate} Hz · ${media.channels} canali`));
      if (media.content_type === "audio/aac") {
        playback.append(el("p", "field-help", t("Il file contiene AAC. Per H3 usa la copia WAV compatibile.")));
        const download = el("a", "button secondary small", t("Scarica WAV per H3"));
        download.href = `/api/audio-media/${media.id}`;
        download.download = media.display_name.replace(/\.[^.]+$/, "") + ".wav";
        playback.append(download);
      }
      item.append(playback);
    }
    const card = el("details", "reference-card"); card.dataset.audio = audio.id; card.open = open.get(audio.id) ?? !audio.confirmed;
    card.append(el("summary", "", `Audio ${audio.slot} · ${audio.name || t("Nuova traccia")}`));
    const body = el("div", "item-body"); card.append(body);
    const change = (key, value) => {
      audio[key] = value;
      audio.confirmed = false;
      const confirmation = card.querySelector("[data-audio-confirmation]");
      if (confirmation) confirmation.checked = false;
      if (["name", "segment_start_s", "segment_end_s", "offset_s"].includes(key)) renderAudioTimeline();
    };
    const label = el("label", "upload-control", t("Carica o sostituisci WAV/MP3")); const input = el("input"); input.type = "file"; input.accept = "audio/wav,audio/mpeg";
    input.onchange = () => { const file = input.files[0]; if (file) withCommand(() => uploadAudio(audio.id, file)); }; label.append(input); body.append(label);
    if (!media) body.append(el("p", "field-help", t("Nessun file associato a questa traccia. Carica un WAV o MP3 per ascoltarlo e trascriverlo.")));
    enableDrop(body, files => { if (files.length !== 1) throw new Error(t("Scegli un solo file per questo slot audio.")); return uploadAudio(audio.id, files[0]); });
    body.append(field(t("Nome audio"), audio.name, value => change("name", value)), selectField(t("Slot audio in H3"), audio.slot, [1, 2, 3].map(n => [n, `Audio ${n}`]), value => { change("slot", Number(value)); audio.linked_to_h3 = false; renderAudio(); }));
    body.append(selectField(t("Modalità audio"), audio.mode, [["copy", t("Copia del segnale")], ["reference", t("Riferimento per nuova performance")]], value => { change("mode", value); if (audio.role === "voice") audio.mode = "reference"; if (audio.mode !== "copy") audio.exclusive_full_track = false; renderAudio(); }),
      selectField(t("Ruolo audio"), audio.role, [["speech", t("Parlato con parole verificate")], ["sound", t("Suono / layer sonoro")], ["voice", t("Solo timbro, parole dalle battute native")]], value => { change("role", value); if (value === "voice") { audio.mode = "reference"; audio.exclusive_full_track = false; } renderAudio(); }));
    const segment = el("div", "three-fields");
    segment.append(field(t("Inizio sorgente · s"), audio.segment_start_s, value => change("segment_start_s", Number(value)), {type:"number",min:0}),
      field(t("Fine sorgente · s"), audio.segment_end_s, value => change("segment_end_s", value === "" ? null : Number(value)), {type:"number",min:0,placeholder:t("Intero file")}),
      field(t("Inizio nel cut · s"), audio.offset_s, value => change("offset_s", Number(value)), {type:"number",min:0}));
    for (const item of segment.querySelectorAll("input")) item.step = "0.01";
    body.append(segment);
    if (audio.role !== "sound") body.append(selectField(t("Parlante dell’audio"), audio.speaker_subject || '', includedSubjectChoices(draft.active_units,audio.speaker_subject,t('Scegli il parlante'),true), value => change("speaker_subject", Number(value) || null)));
    if (audio.mode === "reference" && audio.role !== "sound") {
      body.append(voiceControls(audio, change, audio.role === "voice"
        ? t("Impostazioni generali del riferimento. Puoi personalizzarle per ogni frase in Dialoghi nativi → Battuta.")
        : t("Le scelte e i dettagli vengono inseriti in inglese nell’introduzione di questa battuta.")));
    }
    if (audio.role === "speech") {
      body.append(selectField(t("Lingua del parlato"), audio.language, languages, value => change("language", value)), field(t("Trascrizione verificata · testo esatto"), audio.transcript, value => change("transcript", value), {multiline:true,rows:3}),
        serverButton(t("Trascrivi audio"), () => requestAssistance("audio_asr", audio.id), "asr", audio.id), assistancePanel(audio.id));
    }
    if (audio.role === "sound") body.append(field(t("Uso sonoro richiesto · in inglese"), audio.description_en, value => change("description_en", value)));
    const fullTrack = checkbox(t("Questa è l’intera traccia finale, senza altri suoni"), audio.exclusive_full_track, value => change("exclusive_full_track", value)); fullTrack.hidden = audio.mode !== "copy" || audio.role === "voice"; body.append(fullTrack);
    const confirmation = checkbox(t("Confermo contenuto, segmento e parlante audio"), audio.confirmed, value => { audio.confirmed = value; }); confirmation.querySelector("input").dataset.audioConfirmation = "true";
    body.append(confirmation, checkbox(media?.content_type === "audio/aac" ? t("Collegherò la copia WAV a H3 nello slot Audio indicato") : t("Collegherò il file originale a H3 nello slot Audio indicato"), audio.linked_to_h3, value => { audio.linked_to_h3 = value; }));
    body.append(button(t("Rimuovi audio dal cut"), "button subtle danger", () => { draft.audio_references = draft.audio_references.filter(a => a.id !== audio.id); markDraft(); renderAudio(); renderTokens(); }));
    item.append(card); target.append(item);
  }
  if (draft.audio_references?.length) $("audio-panel").open = true;
  updateAssistanceControls(); refreshAssistancePanels();
}
$("vision-model").onchange = updateAssistanceControls;
$("model").onchange = updateAssistanceControls;
$("text-service").onchange = () => { fillModelChoices('model', 'text-service', 'completion'); updateAssistanceControls(); };
$("vision-service").onchange = () => { fillModelChoices('vision-model', 'vision-service', 'vision'); updateAssistanceControls(); };
$("save-models").onclick = async () => {
  try {
  await mutation("PUT", "/api/assistance/settings", {command_id:newCommandId(), expected_revision:modelSettings.revision,
    text_model:$("model").value, vision_model:$("vision-model").value || null}, value => { modelSettings = value; feedback(t("Selezioni testo e vision salvate.")); updateAssistanceControls(); });
  } catch (error) { feedback(error.message, true); }
};
$("test-vision").onclick = () => userSettings.trial('vision', $("vision-model").value);
$("test-text").onclick = () => userSettings.trial('text', $("model").value);
$("add-audio").onclick = () => withCommand(() => addItem("audio"));
$("image-files").onchange = () => { const files = [...$("image-files").files]; if (files.length) withCommand(() => uploadFiles("picture", files)); };
$("audio-files").onchange = () => { const files = [...$("audio-files").files]; if (files.length) withCommand(() => uploadFiles("audio", files)); };
enableDrop($("image-drop"), files => uploadFiles("picture", files));
enableDrop($("audio-drop"), files => uploadFiles("audio", files));

async function saveCameraPreset() {
  const camera = clone(draft.camera);
  if (!hasCameraSelection(camera)) return;
  camera.subject = null;
  camera.placement = "as_requested";
  camera.dialogue_id = null;
  const previous = editingCameraPreset;
  const content = el("div");
  let name = previous?.name || "";
  let tag = previous?.tag || "";
  let customTag = Boolean(previous);
  const tagField = field(t("Tag dell’inquadratura"), tag, value => { tag = value; customTag = true; }, {draft:false});
  const tagInput = tagField.querySelector("input");
  tagInput.required = true; tagInput.pattern = "[a-z][a-z0-9_]{0,59}";
  const nameField = field(t("Nome dell’inquadratura"), name, value => {
    name = value;
    if (!customTag) { tag = cameraTag(value); tagInput.value = tag; }
  }, {draft:false});
  nameField.querySelector("input").required = true;
  if (previous) tagInput.readOnly = true;
  content.append(nameField, tagField, el("p", "field-help",
    t("Si salvano inquadratura, angolazione, movimento e note. Indica il Subject e il tempo quando richiami il tag nella richiesta.")));
  if (previous) content.append(el("p", "field-help", t("Le modifiche saranno usate nelle nuove compilazioni che richiamano questo tag.")));
  if (!await dialog(previous ? tr`Modifica #${previous.tag}` : t("Salva inquadratura nel progetto"), content, t("Salva inquadratura"))) return;
  const projectId = workspace.project_id, cutId = workspace.id, tick = draftTick;
  const latestProjects = await request("/api/projects");
  const project = latestProjects.find(value => value.id === projectId);
  if (!project || workspace.id !== cutId) throw new Error(t("Il progetto selezionato è cambiato."));
  await mutation("PUT", `/api/projects/${projectId}/camera-presets/${encodeURIComponent(tag)}`, {
    command_id:newCommandId(), expected_revision:project.revision,
    expected_preset_revision:previous?.revision || 0, name, camera
  }, async value => {
    workspace.camera_presets = value.camera_presets;
    editingCameraPreset = null;
    projects = await request("/api/projects");
    if (draftTick === tick) {
      draft.camera = null;
      markDraft();
      await saveDraft();
    }
    renderDirection(); renderTokens(); renderNavigation();
  });
  feedback(tr`Inquadratura #${tag} salvata nella libreria del progetto. Richiamala nella richiesta e indica i tempi dei cambi successivi.`);
}

function renderSavedCameras() {
  const target = $("saved-cameras");
  target.replaceChildren();
  const presets = workspace?.camera_presets || [];
  if (!presets.length) return;
  target.append(el("h3", "", t("Inquadrature del progetto")));
  for (const preset of presets) {
    const row = el("div", "mapping-row");
    row.append(el("strong", "", `${preset.name} · #${preset.tag}`));
    if (directionOptions) row.append(el("p", "direction-preview", cameraPreview(preset.camera, directionOptions)));
    if (preset.camera.notes) row.append(el("p", "field-help", preset.camera.notes));
    row.append(button(t("Richiama nella richiesta"), "button subtle", () => insertRequest(`#${preset.tag}`)),
      button(t("Modifica inquadratura"), "button subtle", () => {
        if (hasCameraSelection(draft.camera)) {
          feedback(t("Salva o rimuovi prima le scelte di regia correnti."), true); return;
        }
        editingCameraPreset = clone(preset);
        draft.camera = clone(preset.camera);
        markDraft(); renderDirection();
      }));
    target.append(row);
  }
}

function renderDirection() {
  renderSavedCameras();
  const target=$("direction-fields");target.replaceChildren();
  if(!directionOptions){target.append(el("p","field-help",t("Caricamento dei controlli di regia…")));return;}
  const c=draft.camera || {framing:null,angle:null,movement:null,amplitude:null,speed:null,subject:null,placement:"as_requested",dialogue_id:null,notes:""};
  if(hasCameraSelection(c))$("direction-panel").open=true;
  const change=(key,value)=>{c[key]=value||null;draft.camera=c;};
  const fields=el("div","two-fields camera-choice-grid");
  for(const [key,label] of [["framing",t("Inquadratura")],["angle",t("Angolazione / punto di vista")],["movement",t("Movimento camera")]])fields.append(selectField(label,c[key]||"",[["",t("Non specificato")],...directionOptions[key].map(v=>[v.value,t(v.label)])],value=>{
    change(key,value);if(key==='movement'&&(!value||value==='static')){c.amplitude=null;c.speed=null;}renderDirection();
  }));target.append(fields);
  const hints=["framing","angle","movement"].map(key=>directionOptions[key].find(v=>v.value===c[key])?.hint).filter(Boolean);
  if(hints.length)target.append(el("p","field-help",hints.map(t).join(' ')));
  if(c.movement && c.movement!=='static') {
    const motion=el("div","two-fields");
    for(const [key,label] of [["amplitude",t("Ampiezza del movimento")],["speed",t("Velocità del movimento")]])motion.append(selectField(label,c[key]||"",[["",t("Non specificata")],...directionOptions[key].map(v=>[v.value,t(v.label)])],value=>{change(key,value);renderDirection();}));
    target.append(motion);
  }
  const phase=el("div","two-fields");
  phase.append(selectField(t("Soggetto della ripresa / del movimento"),c.subject||"",includedSubjectChoices(draft.active_units,c.subject,t('Come nella richiesta')),value=>change('subject',value?Number(value):null)),
    selectField(t("Quando applicare la regia"),c.placement||'as_requested',cameraPhases,value=>{change('placement',value);if(!['during_dialogue','after_dialogue'].includes(value))c.dialogue_id=null;renderDirection();}));target.append(phase);
  if(['during_dialogue','after_dialogue'].includes(c.placement)) {
    const dialogues=[...draft.dialogues,...(draft.audio_references||[]).filter(a=>a.role==='speech')];
    target.append(selectField(t("Battuta di riferimento per la camera"),c.dialogue_id||"",[["",t("Scegli la battuta")],...dialogues.map(d=>[d.id,`${d.id} · ${d.delivery === 'narrator' ? t('Voce narrante') : draft.active_units.find(u=>u.subject===d.speaker_subject)?.name||t('Parlante da scegliere')}`])],value=>change('dialogue_id',value)));
  }
  target.append(field(t("Note di regia · facoltative, in italiano"),c.notes||"",value=>{c.notes=value;draft.camera=c;},{multiline:true,rows:2,placeholder:t("Per esempio: ripresa frontale; la camera inizia a seguire Anna solo quando entra.")}));
  if(hasCameraSelection(c)) {
    const preview=cameraPreview(c,directionOptions);if(preview)target.append(el("p","direction-preview",preview));
    target.append(button(t("Rimuovi le scelte di regia"),"button subtle",()=>{draft.camera=null;editingCameraPreset=null;markDraft();renderDirection();}));
    const save = button(editingCameraPreset ? tr`Salva modifiche a #${editingCameraPreset.tag}` : t("Salva come inquadratura"),
      "button secondary small", () => withCommand(saveCameraPreset));
    save.dataset.serverCommand = "true";
    target.append(save);
    if (editingCameraPreset) target.append(button(t("Annulla modifica inquadratura"), "button subtle", () => {
      editingCameraPreset = null; draft.camera = null; markDraft(); renderDirection();
    }));
  }
  const source=el('a','field-help',t('Lessico dei movimenti: guida ufficiale MiniMax H3 §4.3'));source.href=directionOptions.source;source.target='_blank';source.rel='noopener noreferrer';target.append(source);
  if((draft.videos||[]).some(v=>['camera','camera_and_subject_motion'].includes(v.role)&&v.guidance?.enabled))target.append(el('p','field-help',t('La camera ha una guida Video attiva. Lascia il movimento del menu non specificato per usare quella guida; inquadratura e angolazione restano selezionabili.')));
}

function guideControls(ref,kind,invalidate) {
  const body=el('div','guide-controls');
  body.setAttribute('role','group');body.setAttribute('aria-label',tr`Guida ${kind==='video'?'Video':'Picture'} ${ref.slot}`);
  const g=ref.guidance ||= {enabled:false,mappings:[],prompt_en:'',anchor:null,at_s:null,workflow:'',continuity_checked:false};
  g.mappings ||= [];
  const rerender=()=>{kind==='video'?renderVideos():renderPictures();renderDirection();renderTokens();};
  const changed=()=>{invalidate();renderTokens();};
  body.append(checkbox(t("Usa questa guida nel cut"),g.enabled,value=>{g.enabled=value;changed();renderDirection();}));
  const descriptions={style:t('Fornisce soltanto lo stile visivo; non crea Subject o presenze.'),spatial_map:t('Il significato dei segni viene dal mapping: punto iniziale, destinazione e camera sono distinti.'),composition_previz:t('Guida di composizione, senza imporre identità, vestiti o fotogrammi identici.'),initial_composition:t('Posizioni iniziali delle figure mappate; identità e abiti provengono dai Subject. Non è un frame anchor.'),frame_anchor:t('Primo, ultimo o keyframe esplicito per il workflow indicato. Nessuna esecuzione automatica del workflow.'),camera:t('Trasferisce soltanto il movimento camera, senza aspetto, sfondo o audio.'),subject_motion:t('Trasferisce soltanto il movimento delle figure mappate, senza aspetto, sfondo, rigidità o audio.'),camera_and_subject_motion:t('Camera e movimento dei Subject in un solo slot Video; identità, abiti, sfondo e audio restano separati.')};
  body.append(el('p','field-help',descriptions[ref.role]||''));
  if(!['style','camera'].includes(ref.role)) {
    body.append(el('strong','',t('Mapping delle figure / dei segni')));
    for(const [index,m] of g.mappings.entries()) {
      const row=el('div','mapping-row');
      row.append(field(t('Figura o segno nella guida · inglese'),m.figure,value=>{m.figure=value;changed();},{placeholder:'the left figure / the red circle'}));
      const roles=kind==='video'?[['motion',t('Movimento Subject')]]:ref.role==='spatial_map'?[['figure',t('Figura')],['start',t('Punto iniziale Subject')],['destination',t('Destinazione Subject')],['camera_start',t('Punto iniziale camera')],['camera_direction',t('Direzione camera')]]:[['figure',t('Figura / posizione Subject')]];
      row.append(selectField(t('Significato del segno'),m.role,roles,value=>{m.role=value;if(value.startsWith('camera_'))m.subject=null;changed();rerender();}));
      if(!m.role?.startsWith('camera_'))row.append(selectField(t('Subject assegnato alla figura'),m.subject||'',includedSubjectChoices(draft.active_units,m.subject,t('Scegli il Subject')),value=>{m.subject=value?Number(value):null;changed();}));
      row.append(button(t('Rimuovi mapping'),'button subtle danger',()=>{g.mappings.splice(index,1);changed();markDraft();rerender();}));body.append(row);
    }
    body.append(button(t('+ Figura / segno'),'button secondary small',()=>{g.mappings.push({figure:'',role:kind==='video'?'motion':'figure',subject:null});changed();markDraft();rerender();}));
  }
  if(ref.role==='frame_anchor') {
    body.append(selectField(t('Posizione del frame anchor'),g.anchor||'',[["",t("Scegli il ruolo del frame")],['first',t('Primo frame')],['last',t('Ultimo frame')],['keyframe',t('Keyframe intermedio')]],value=>{g.anchor=value||null;if(value!=='keyframe')g.at_s=null;changed();rerender();}));
    if(g.anchor==='keyframe')body.append(field(t('Tempo del keyframe · secondi'),g.at_s,value=>{g.at_s=value===''?null:Number(value);changed();},{type:'number',min:0,max:15}));
    body.append(field(t('Workflow compatibile per il frame anchor · dichiarato'),g.workflow,value=>{g.workflow=value;changed();},{placeholder:t('Nome o descrizione del workflow che userai')}));
    if(draft.continuity.seamless)body.append(checkbox(t('Ho verificato che il frame anchor è compatibile con il raccordo seamless'),g.continuity_checked,value=>{g.continuity_checked=value;changed();}));
  }
  body.append(field(t('Prompt guida · inglese, facoltativo, conservato esattamente'),g.prompt_en,value=>{g.prompt_en=value;changed();},{multiline:true,rows:3,placeholder:t('Istruzioni già in inglese per questa guida: saranno inserite una sola volta, senza riscrittura.')}));
  return body;
}

function finalizedScene() { return Boolean(currentContext()?.scene.finalized); }
function changeContinuityMode(mode) {
  const old = draft.continuity;
  if (mode === "none") draft.continuity = {mode:"none", declared_state:null};
  else {
    const previous = workspace.previous_cut;
    const keepExternal = old.mode !== "none" && !old.previous_cut_id;
    draft.continuity = {...old, mode, declared_state:old.declared_state || "",
      previous_cut_id:old.previous_cut_id || (!keepExternal ? previous?.id || null : null),
      previous_version_id:old.previous_version_id || (!keepExternal && (!old.previous_cut_id || old.previous_cut_id===previous?.id) ? previous?.version?.id || null : null),
      external_source:old.external_source || null,
      video_id:mode === "video_reference" ? old.video_id || null : null,
      context_media_id:mode === "video_reference" ? null : old.context_media_id || null,
      context_media_kind:mode === "video_reference" ? null : old.context_media_kind || null};
    if (mode === "latent" || mode === "tail_frames") draft.continuity.window_frames ??= 39;
    else {draft.continuity.window_frames=null;draft.continuity.trim_frames=null;draft.continuity.sampling_prefix_frames=null;}
  }
  renderContinuity(); renderUnits(); renderTokens(); renderContinuityPreview();
}
function renderContinuity() {
  const target = $("continuity-fields"); target.replaceChildren();
  const c = draft.continuity;
  target.append(selectField(t("Modalità di continuità"), c.mode, continuityModes, changeContinuityMode));
  if (c.mode === "none") { target.append(el("p", "field-help", t("Questo cut parte senza contesto precedente. Se devi proseguire un video, scegli il percorso e dichiara lo stato effettivo."))); return; }
  $("continuity-panel").open = true;
  const scene = currentContext()?.scene;
  const earlier = (scene?.cuts || []).filter(v => v.number < workspace.number).map(v => [v.id, `Cut ${v.number} · ${v.title}`]);
  const archivedSource = scene?.trashed_cuts?.find(v => v.id === c.previous_cut_id);
  if (archivedSource) earlier.push([archivedSource.id, tr`Cut ${archivedSource.number} · ${archivedSource.title} · nel cestino`]);
  target.append(selectField(t("Origine della continuità"), c.previous_cut_id || "external", [["external", t("Sorgente esterna dichiarata")], ...earlier], value => {
    c.previous_cut_id = value === "external" ? null : value; c.previous_version_id = null; c.external_source = value === "external" ? "" : null;
    c.context_media_id = null; c.context_media_kind = null; renderContinuity(); renderContinuityPreview();
  }));
  if (!c.previous_cut_id) target.append(field(t("Nome della sorgente esterna · facoltativo"), c.external_source, value => {c.external_source=value || null;}));
  const previous = workspace.previous_cut;
  if (c.previous_cut_id && previous?.id === c.previous_cut_id && previous.versions.length) {
    target.append(selectField(t("Versione del cut di origine"), c.previous_version_id || "", [["",t("Scegli esplicitamente la versione di origine")],...previous.versions.map((v,i) => [v.id, `${i+1} · ${v.origin === "manual" ? t("manuale") : t("generata")} · ${v.duration_s ?? "—"} s${v.id === previous.confirmed_version_id ? t(" · confermata") : ""}`])], value => {
      c.previous_version_id=value || null; renderContinuityPreview();
    }));
  }
  target.append(field(t("Stato iniziale effettivo · dichiaralo in italiano"), c.declared_state, value => {c.declared_state=value;}, {multiline:true,rows:3,placeholder:t("Descrivi solo ciò che hai verificato nel video o nel contesto da cui proseguire.")}));
  target.append(el("p", "field-help", t("Il prompt precedente non prova lo stato finale del video. Lo stato dichiarato viene tradotto una sola volta nella sequenza dettagliata; audio e dialoghi non vengono ereditati.")));
  if (c.mode === "video_reference") target.append(selectField(t("Video selezionato per la continuazione"), c.video_id || "", [["", t("Scegli uno slot Video")], ...draft.videos.filter(v=>v.role==='continuation').map(v => [v.id, `Video ${v.slot} · ${v.name || t("Sorgente")}`])], value => {c.video_id=value || null;renderTokens();}));
  if (c.mode === "tail_frames" || c.mode === "latent") {
    target.append(selectField(t("Preset finestra di contesto"), [39,90,141].includes(c.window_frames) ? c.window_frames : "custom", [[39,t("39 frame")],[90,t("90 frame")],[141,t("141 frame")],["custom",t("Valore personalizzato")]], value => {c.window_frames=value === "custom" ? null : Number(value);renderContinuity();}));
    target.append(el("p", "field-help", t("Parametri del tuo workflow: 39 è un preset, non un limite H3. Finestra, trim e prefisso restano distinti e non vengono convertiti in durata utile.")));
    const numbers=el("div","three-fields");
    for (const [key,label,min] of [["window_frames",t("Finestra di contesto · frame"),1],["trim_frames",t("Trim dichiarato · frame"),0],["sampling_prefix_frames",t("Prefisso di sampling · frame"),0]]) numbers.append(field(label,c[key],value=>{c[key]=value===""?null:Number(value);},{type:"number",min}));
    target.append(numbers);
    const context=workspace.context_media;
    if(context && context.id===c.context_media_id) target.append(context.kind === "video" ? videoPreview(context) : contextImage(context));
    if(previous?.output && previous.id === c.previous_cut_id) target.append(button(t("Usa il video risultato precedente come contesto"), "button secondary small",()=>{c.context_media_id=previous.output.id;c.context_media_kind="video";markDraft();renderContinuity();}));
    const uploads=el("div","two-fields");
    for(const [kind,label,accept] of [["video",t("Video di contesto · facoltativo"),"video/mp4,video/quicktime,video/webm"],["image",t("Frame di contesto · facoltativo"),"image/jpeg,image/png,image/webp"]]) {
      const wrap=el("label","upload-control",label);const input=el("input");input.type="file";input.accept=accept;
      input.onchange=()=>{if(input.files[0])withCommand(()=>uploadContextMedia(kind,input.files[0]));};wrap.append(input);uploads.append(wrap);
    }
    target.append(uploads);
    if(c.context_media_id) target.append(button(t("Scollega il media di contesto"), "button subtle",()=>{c.context_media_id=null;c.context_media_kind=null;markDraft();renderContinuity();}));
  }
  target.append(checkbox(t("Raccordo seamless · senza reset o stacchi aggiunti"), c.seamless, value=>{c.seamless=value;}));
  if(c.previous_cut_id && (previous?.id !== c.previous_cut_id || c.previous_version_id && previous?.version?.id !== c.previous_version_id)) target.append(el("p","field-help",t("Salva la bozza per aggiornare l’anteprima della sorgente scelta.")));
  updateAssistanceControls();
}
function contextImage(media) {
  const image=el("img","picture-preview");image.src=`/api/media/${media.id}`;image.alt=t("Frame di contesto dichiarato");return image;
}
function videoPreview(media) {
  const box=el("div","video-preview");
  const player=el("video");player.controls=true;player.muted=true;player.preload="none";player.src=`/api/video-media/${media.id}`;player.poster=`/api/video-media/${media.id}?frame=first`;
  player.onerror=()=>{if(!box.querySelector(".video-error"))box.append(el("p","field-help video-error",t("Il browser non riproduce questo codec. Originale e metadati restano conservati; primo e ultimo frame sono disponibili.")));};
  box.append(player,el("p","field-help",tr`${media.display_name} · ${media.duration_s.toFixed(3)} s del file · ${media.frame_count} fotogrammi · ${media.variable_fps ? "fps variabile" : `${media.fps?.toFixed(3) ?? "—"} fps`} · ${media.width} × ${media.height}. L’audio del video non crea un riferimento Audio.`));
  const frames=el("details","frame-preview");frames.append(el("summary","",t("Primo e ultimo fotogramma · verifica visiva")));const images=el("div","two-fields");
  for(const [frame,label] of [["first",t("Primo fotogramma")],["last",t("Ultimo fotogramma")]]){const image=el("img");image.src=`/api/video-media/${media.id}?frame=${frame}`;image.alt=label;image.loading="lazy";images.append(image);}
  frames.append(images);box.append(frames);return box;
}
async function uploadContextMedia(kind,file) {
  if(draftDirty && !await saveDraft())return;
  const cut=workspace.id,tick=draftTick;
  const media=await request(kind==="video"?"/api/video-media":"/api/media",{method:"POST",headers:{"Content-Type":"application/octet-stream","X-File-Name":encodeURIComponent(file.name)},body:file});
  if(workspace.id!==cut || draftTick!==tick){feedback(t("File archiviato. Il contesto è cambiato durante il caricamento: i tuoi campi sono conservati, senza applicare il risultato."));return;}
  draft.continuity.context_media_id=media.id;draft.continuity.context_media_kind=kind;markDraft();await saveDraft();renderContinuity();feedback(t("Media di contesto conservato. Nessuno slot Video o Picture è stato creato."));
}
function renderVideos() {
  const target=$("video-references");const opened=new Map([...target.querySelectorAll("[data-video]")].map(n=>[n.dataset.video,n.open]));target.replaceChildren();
  for(const video of draft.videos) {
    const videoLabel={continuation:t("Sorgente di continuazione"),camera:t("Guida sola camera"),subject_motion:t("Guida movimento Subject"),camera_and_subject_motion:t("Guida camera + Subject")}[video.role || "continuation"];
    const card=el("details","reference-card");card.dataset.video=video.id;card.open=opened.get(video.id)??!video.confirmed;card.append(el("summary","",`Video ${video.slot} · ${video.name || videoLabel}`));
    const body=el("div","item-body");const change=(key,value)=>{video[key]=value;video.confirmed=false;const check=card.querySelector("[data-video-confirmation]");if(check)check.checked=false;};
    const media=workspace.video_media?.[video.id];if(media)body.append(videoPreview(media));
    const upload=el("label","upload-control",t("Carica o sostituisci video locale · facoltativo"));const input=el("input");input.type="file";input.accept="video/mp4,video/quicktime,video/webm";input.onchange=()=>{if(input.files[0])withCommand(()=>uploadVideoReference(video.id,input.files[0]));};upload.append(input);body.append(upload);
    enableDrop(body,files=>{if(files.length!==1)throw new Error(t("Scegli un video per questo slot."));return uploadVideoReference(video.id,files[0]);});
    body.append(field(t("Nome del riferimento Video"),video.name,value=>change("name",value)),selectField(t("Slot Video in H3"),video.slot,[1,2,3].map(n=>[n,`Video ${n}`]),value=>{change("slot",Number(value));video.linked_to_h3=false;renderVideos();renderContinuity();}),
      selectField(t('Ruolo del Video'),video.role,videoRoles,value=>{
        change('role',value);if(draft.continuity.video_id===video.id&&value!=='continuation')draft.continuity.video_id=null;
        if(value==='continuation'&&video.guidance)video.guidance.enabled=false;
        if(value==='camera'&&video.guidance)video.guidance.mappings=[];
        if(video.description_en==='the source clip for continuation'&&value!=='continuation')video.description_en='the declared motion guide';
        renderVideos();renderContinuity();renderDirection();renderTokens();
      }),field(t("Descrizione del Video · inglese"),video.description_en,value=>change("description_en",value)));
    if(video.role!=='continuation')body.append(guideControls(video,'video',()=>change('confirmed',false)));
    const duration=field(media?t("Durata del file Video · misurata, secondi"):t("Durata effettiva del Video · dichiarata, secondi"),video.duration_s,value=>{change("duration_s",value===""?null:Number(value));video.duration_origin="declared";},{type:"number",min:2,max:15});duration.querySelector("input").readOnly=Boolean(media);duration.querySelector("input").step="0.01";body.append(duration);
    if(video.duration_s && (video.duration_s<2 || video.duration_s>15))body.append(el("p","issues",t("Il file non rientra nei 2–15 secondi per un ingresso Video H3. Prepara esplicitamente un file compatibile nel workflow esterno; l’app non lo taglia automaticamente.")));
    body.append(checkbox(t("Il file Video esiste nel mio workflow"),video.file_exists,value=>{video.file_exists=value;}));
    const check=checkbox(t("Confermo ruolo, descrizione, durata e mapping del Video"),video.confirmed,value=>{video.confirmed=value;});check.querySelector("input").dataset.videoConfirmation="true";body.append(check,checkbox(t("Collegherò il file a H3 nello slot Video indicato"),video.linked_to_h3,value=>{video.linked_to_h3=value;}));
    if(video.role==='continuation')body.append(button(t("Usa questo Video per la continuazione"),"button secondary small",()=>{changeContinuityMode("video_reference");draft.continuity.video_id=video.id;markDraft();renderContinuity();renderTokens();}));
    body.append(button(t("Rimuovi Video dal cut"),"button subtle danger",()=>{draft.videos=draft.videos.filter(v=>v.id!==video.id);if(draft.continuity.video_id===video.id)draft.continuity.video_id=null;markDraft();renderVideos();renderContinuity();renderDirection();renderTokens();}));
    card.append(body);target.append(card);
  }
  if(draft.videos.length)$("video-panel").open=true;updateAssistanceControls();
}
async function uploadVideoReference(id,file) {
  if(draftDirty && !await saveDraft())return;const tick=draftTick;
  const media=await request("/api/video-media",{method:"POST",headers:{"Content-Type":"application/octet-stream","X-File-Name":encodeURIComponent(file.name)},body:file});
  await mutation("PUT",`/api/cuts/${workspace.id}/videos/${id}/media`,{command_id:newCommandId(),expected_revision:workspace.revision,media_id:media.id},view=>adoptView(view,tick));
  feedback(t("Video misurato e conservato, senza analisi LLM. Conferma i dati e il collegamento H3."));
}
function renderContinuityPreview() {
  const target=$("previous-cut-view"),previous=workspace?.previous_cut;$("previous-cut-panel").hidden=!previous;
  const key=JSON.stringify([uiLanguage(),workspace?.id,previous?.id,previous?.version?.id,previous?.output?.id,draft?.continuity.mode,draft?.continuity.previous_cut_id,draft?.active_units.map(u=>u.subject)]);
  if(target.dataset.renderKey===key)return;target.dataset.renderKey=key;target.replaceChildren();if(!previous)return;
  const details=el("details","confirmed-card");details.open=true;details.append(el("summary","",tr`Cut ${previous.number} · ${previous.title} · ${previous.version?.duration_s ?? "—"} s utili ${previous.version?.id===previous.confirmed_version_id ? t("· versione confermata") : t("· da rivedere")}`));
  details.append(el("p","field-help",t("Anteprima della sorgente. Lo stato effettivo da cui proseguire va dichiarato nel cut corrente; il prompt non dimostra come termini il video.")));
  if(previous.output)details.append(videoPreview(previous.output));else details.append(el("p","field-help",t("Nessun video risultato associato a questa versione.")));
  if(previous.version){const prompt=el("details","confirmed-card");prompt.append(el("summary","",t("Prompt della versione precedente")),el("pre","prompt-text",previous.version.text));details.append(prompt);}
  if(!previous.snapshot_known)details.append(el("p","issues",t("Snapshot storico sconosciuto: i Subject non vengono ricostruiti dal catalogo corrente.")));
  if(draft.continuity.mode!=="none" && draft.continuity.previous_cut_id===previous.id)for(const unit of previous.units) {
    const reuse=serverButton(tr`Riprendi ${unit.name} · Subject ${unit.subject} dal contesto`,async()=>{
      if(draftDirty && !await saveDraft())return;const tick=draftTick;
      await mutation("POST",`/api/cuts/${workspace.id}/context-subject`,{command_id:newCommandId(),expected_revision:workspace.revision,subject:unit.subject},view=>adoptView(view,tick));
      feedback(t("Subject ripreso dal contesto senza nuove Picture. Controlla attributi e definizione; dichiara separatamente lo stato iniziale."));
    },"context_subject",String(unit.subject));reuse.disabled=commandBusy||finalizedScene()||!draft.continuity.previous_version_id||draft.active_units.some(u=>workspace.unit_ids?.[String(u.subject)]===unit.project_unit_id);details.append(reuse);
  }
  target.append(details);
}
function renderResultVideo() {
  const target=$("result-video-view");const key=JSON.stringify([uiLanguage(),workspace?.id,workspace?.versions.map(v=>v.id),workspace?.confirmed_version_id,workspace?.output_by_version]);
  if(target.dataset.renderKey===key)return;target.dataset.renderKey=key;
  const versionKey=JSON.stringify([workspace?.id,workspace?.versions.map(v=>v.id)]);
  const old=target.dataset.versionKey===versionKey?target.querySelector("select")?.value:null;target.dataset.versionKey=versionKey;target.replaceChildren();
  if(!workspace?.versions.length){target.append(el("p","field-help",t("Conserva prima una versione del prompt, poi associa il video generato nel workflow esterno.")));return;}
  const select=el("select");select.setAttribute("aria-label",t("Versione del prompt associata al risultato video"));
  for(const [i,v] of workspace.versions.entries())select.append(new Option(`${i+1} · ${v.origin==="manual"?t("manuale"):t("generata")} · ${v.duration_s??"—"} s${v.id===workspace.confirmed_version_id?t(" · confermata"):""}`,v.id));
  select.value=workspace.versions.some(v=>v.id===old)?old:(workspace.state==="confirmed"?workspace.confirmed_version_id:null)||workspace.versions.at(-1).id;
  const wrap=el("label","field");wrap.append(el("span","",t("Versione del prompt associata al risultato video")),select);target.append(wrap);
  const body=el("div");const show=()=>{body.replaceChildren();const output=workspace.output_by_version?.[select.value];if(output)body.append(videoPreview(output));body.append(el("p","field-help",t("Il video è un risultato associato alla versione selezionata. Durata del file e durata utile prevista sono distinte; l’app non deduce lo stato finale e non esegue trim automatici.")));};select.onchange=show;show();
  const upload=el("label","upload-control",t("Associa il video generato a questa versione"));const input=el("input");input.type="file";input.accept="video/mp4,video/quicktime,video/webm";input.dataset.resultVideo="true";input.disabled=commandBusy;
  input.onchange=()=>{if(input.files[0])withCommand(()=>uploadResultVideo(select.value,input.files[0]));};upload.append(input);target.append(body,upload);
}
async function uploadResultVideo(versionId,file) {
  if(draftDirty && !await saveDraft())return;const cut=workspace.id,tick=draftTick;
  const media=await request("/api/video-media",{method:"POST",headers:{"Content-Type":"application/octet-stream","X-File-Name":encodeURIComponent(file.name)},body:file});
  if(workspace.id!==cut)return;
  await mutation("PUT",`/api/cuts/${cut}/output`,{command_id:newCommandId(),expected_revision:workspace.revision,version_id:versionId,media_id:media.id},view=>adoptView(view,tick));
  await refreshProjects();renderNavigation();renderConfirmedCuts();feedback(t("Risultato video associato alla versione scelta. Il prompt e il suo snapshot sono conservati."));
}
$("add-video").onclick=()=>withCommand(()=>addItem("video"));
initialize();

// M6: scelte locali dell'export e conferma del piano di cancellazione.
async function exportArchive() {
  await preserveEdits();
  const context=currentContext();if(!context)return;
  let scope='scene',policy='confirmed',notes=true,epoch=0,prepared=null,choices={};
  const content=el('div');content.append(el('p','section-help',t('Esporta le versioni salvate che scegli qui. Nessuna chiamata al modello. Il TXT di un singolo cut contiene soltanto il prompt esatto; scena e progetto includono numerazione, stato e durata.')));
  const fields=el('div','two-fields'),list=el('div','export-list');
  const selection=()=>({scope,resource_id:scope==='cut'?workspace.id:scope==='scene'?context.scene.id:context.project.id,policy,reference_notes:notes});
  const render=async()=>{
    const requestEpoch=++epoch;prepared=null;choices={};list.replaceChildren(el('p','field-help',t('Caricamento versioni…')));$('dialog-submit').disabled=true;
    try {
      const result=await request('/api/exports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selection())});
      if(requestEpoch!==epoch)return;prepared=result;list.replaceChildren();
      for(const item of result.items) {
        const row=el('div','export-row');row.append(el('p','',tr`Scena ${item.scene_number} · ${item.scene_title} / Cut ${item.number} · ${item.title}`));
        const status=el('p','field-help',item.status);
        if(item.versions.length) {
          const options=item.versions.map(v=>[v.id,`${v.number} · ${v.origin==='manual'?t('manuale'):t('generata')} · ${v.duration_s??'—'} s${v.approved?t(' · approvata'):''}`]);
          if(!item.version_id)options.unshift(['',t('Nessuna versione confermata')]);
          row.append(selectField(tr`Versione · scena ${item.scene_number} cut ${item.number}`,item.version_id||'',options,value=>{if(value)choices[item.cut_id]=value;else delete choices[item.cut_id];status.textContent=value===item.version_id?item.status:item.versions.find(v=>v.id===value)?.approved?t('Approvata in precedenza'):value?t('Da rivedere'):t('Nessuna versione selezionata');},{draft:false}));
          if(item.version_id)choices[item.cut_id]=item.version_id;
        } else row.append(el('p','field-help',t('Nessun prompt salvato: verrà segnalato nella raccolta.')));
        row.append(status);list.append(row);
      }
      if(!result.items.length)list.append(el('p','field-help',t('Nessun cut in questo ambito.')));
    } catch(error){if(requestEpoch===epoch)list.replaceChildren(el('p','issues',error.message));}
    finally{if(requestEpoch===epoch)$('dialog-submit').disabled=!prepared;}
  };
  fields.append(selectField(t('Ambito dell’esportazione'),scope,[['cut',t('Questo cut')],['scene',t('Questa scena')],['project',t('Questo progetto')]],value=>{scope=value;render();},{draft:false}),selectField(t('Versioni iniziali'),policy,[['confirmed',t('Confermate')],['latest',t('Più recenti, anche da rivedere')]],value=>{policy=value;render();},{draft:false}));
  content.append(fields,checkbox(t('Includi note dei riferimenti nelle raccolte e nella stampa'),notes,value=>{notes=value;},{draft:false}),list);
  const pendingDialog=dialog(t('Esporta e stampa'),content,t('Prepara TXT e stampa'));await render();
  const accepted=await pendingDialog;epoch++;$('dialog-submit').disabled=false;
  if(!accepted||!prepared)return;
  const result=await request('/api/exports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...selection(),versions:choices})});
  const output=el('div');output.append(el('p','',result.title),el('p','section-help',t('File e stampa usano le versioni selezionate, anche se in seguito modifichi i cut. I collegamenti scadono dopo 30 minuti.')));
  for(const [suffix,label] of [['txt',t('Scarica TXT')],['print',t('Apri stampa / salva PDF')]]) {
    if(suffix==='txt' && result.scope==='cut' && !result.items[0]?.text)continue;
    const link=el('a','button secondary',label);link.href=`/api/exports/${result.id}/${suffix}`;
    if(suffix==='print'){link.target='_blank';link.rel='noopener';}else link.download='';
    output.append(link);
  }
  for(const item of result.items)if(!item.text)output.append(el('p','issues',tr`Scena ${item.scene_number}, cut ${item.number}: nessun prompt selezionato.`));
  await dialog(t('Esportazione pronta'),output,null);
}

async function purgeArchive(selection) {
  let cancelled=false;
  const preparing=dialog(t('Preparazione del cestino'),el('p','section-help',t('Caricamento dell’anteprima. Nessun elemento viene eliminato prima della conferma.')),null);
  const closePreparation=closeCurrentDialog;
  preparing.then(()=>{cancelled=true;});
  let plan;
  try {
    if(workspace)await preserveEdits();
    if(cancelled)return;
    plan=await request('/api/trash/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selection)});
  } catch(error) {
    if(cancelled)return;
    closePreparation();
    await dialog(t('Anteprima del cestino non disponibile'),el('p','issues',error.message),null);
    return;
  }
  if(cancelled)return;
  closePreparation();
  const content=el('div');content.append(el('p','section-help',t('Questa operazione elimina definitivamente gli elementi selezionati e le loro versioni. Puoi ancora annullare. I file gestiti vengono eliminati soltanto se non servono ad altri contenuti conservati.')));
  for(const label of plan.labels)content.append(el('p','',diagnostic(label)));
  content.append(el('p','',tr`${plan.projects} progetti · ${plan.scenes} scene · ${plan.cuts} cut · ${plan.versions} versioni · ${plan.files_to_remove} file da eliminare. ${plan.media_retained} media condivisi o protetti conservati.`));
  for(const warning of plan.warnings)content.append(el('p','field-help',warning));
  if(plan.blockers.length){for(const issue of plan.blockers)content.append(el('p','issues',issue));await dialog(t('Cancellazione non disponibile'),content,null);return;}
  const phrase=field(t('Scrivi ELIMINA per confermare'),'',()=>{},{draft:false});phrase.querySelector('input').required=true;phrase.querySelector('input').pattern='ELIMINA';phrase.querySelector('input').autocomplete='off';
  const check=checkbox(t('Confermo la cancellazione definitiva degli elementi elencati'),false,()=>{},{draft:false});check.querySelector('input').required=true;content.append(phrase,check);
  if(!await dialog(t('Elimina definitivamente'),content,t('Elimina definitivamente')))return;
  let result;
  try {
    result=await request('/api/trash/purge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command_id:newCommandId(),selection,plan_hash:plan.plan_hash,confirmed:true,confirmation:'ELIMINA'})});
  } catch(error) {
    const message=el('div');message.append(el('p','issues',error.message));
    if(error.code==='network')message.append(el('p','field-help',t('L’esito non è stato ricevuto: riapri il cestino per verificare gli elementi rimasti prima di riprovare.')));
    await dialog(t('Problema durante la cancellazione'),message,null);
    return;
  }
  await refreshProjects();
  if(!findCut(workspace?.id)) {
    clearTimeout(pollTimer);clearTimeout(assistanceTimer);currentCutId=firstAvailableCut();draftDirty=false;manualDirty=false;workspace=null;draft=null;
    if(currentCutId)await loadWorkspace(true);else await showEmptyArchive();
  }else renderNavigation();
  if(result.pending_files) {
    const pending=el('div');pending.append(el('p','field-help',tr`${result.pending_files} file non sono stati rimossi. Restano in una coda di pulizia, senza cancellare percorsi esterni o file modificati.`),button(t('Riprova pulizia dei file'),'button secondary',async()=>{try{const value=await request('/api/trash/cleanup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command_id:newCommandId(),expected_revision:0})});feedback(tr`${value.pending_files} file ancora in attesa.`);}catch(error){feedback(error.message,true);}}));await dialog(t('Elementi eliminati · pulizia da completare'),pending,null);
  }else feedback(t('Elementi del cestino eliminati. I file ancora referenziati sono conservati.'));
}
$('export-archive').onclick=()=>withCommand(exportArchive);
$('compact-subjects').onclick=()=>withCommand(async()=>{
  await preserveEdits();
  const content=el('p','section-help',t('Rinumera da 1 i Subject usati nelle bozze di tutti i cut della scena, aggiornando richiami, speaker e mapping. Le versioni già salvate conservano il testo e la numerazione originali; i cut modificati tornano da rivedere.'));
  if(!await dialog(t('Rinumera i Subject della scena'),content,t('Rinumera le bozze')))return;
  const context=currentContext();
  await request(`/api/scenes/${context.scene.id}/subjects/compact`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command_id:newCommandId(),expected_revision:context.scene.revision})});
  await refreshProjects();await loadWorkspace(true);
  feedback(t('Numerazione della scena aggiornata. Controlla le bozze e ricompila esplicitamente se vuoi nuovi prompt.'));
});
