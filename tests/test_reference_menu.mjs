import assert from "node:assert/strict";
import test from "node:test";

import { visibleReferenceTokens, associatePicture, definitionPicture, subjectDefinition } from '../app/static/reference-menu.js';
const tokens = [1, 2, 3].map(slot => ({ kind: "picture", id: `p${slot}`, token: `<Picture ${slot}>`, label: "Etichetta precedente" }));
const fixture = () => ({ pictures: [1, 2, 3].map(slot => ({ id: `p${slot}`, slot, name: `Immagine ${slot}`, role: slot === 1 ? "identity" : "outfit", description_en: "a skirt", confirmed: true, linked_to_h3: true })),
  active_units: [{ subject: 1, name: "Ann", role: "character", confirmed: true, sources: [{ picture_id: "p1", attribute: "identity" }, { picture_id: "p2", attribute: "outfit" }] }], dialogues: [] });

test("audio disponibile soltanto con file, conferme e slot corrente", () => {
  const draft = fixture();
  const candidate = {kind:"audio",id:"a1",token:"<Audio 1>"};
  draft.audio_references = [{id:"a1",slot:1,media_id:"file",confirmed:true,linked_to_h3:true}];
  assert.equal(visibleReferenceTokens([candidate],draft).length,1);
  for (const [key,value] of [["confirmed",false],["linked_to_h3",false],["media_id",null],["slot",3]]) {
    const copy = structuredClone(draft); copy.audio_references[0][key] = value;
    assert.equal(visibleReferenceTokens([candidate],copy).length,0);
  }
});

test("Video disponibile solo nello slot scelto per il raccordo e confermato", () => {
  const draft=fixture();draft.videos=[{id:"v1",slot:2,file_exists:true,confirmed:true,linked_to_h3:true}];
  draft.continuity={mode:"video_reference",video_id:"v1"};
  const token={kind:"video",id:"v1",token:"<Video 2>"};
  assert.equal(visibleReferenceTokens([token],draft).length,1);
  for(const [key,value] of [["file_exists",false],["confirmed",false],["linked_to_h3",false],["slot",1]]){
    const copy=structuredClone(draft);copy.videos[0][key]=value;assert.equal(visibleReferenceTokens([token],copy).length,0);
  }
  draft.continuity.mode="latent";assert.equal(visibleReferenceTokens([token],draft).length,0);
});

test("una nuova Picture abito pronta compare senza creare o assegnare Subject", () => {
  const draft = fixture(); const original = structuredClone(draft);
  const available = visibleReferenceTokens(tokens, draft);
  assert.equal(available.length, 3);
  assert.equal(available[2].requiresAssociation, true);
  assert.match(available[2].label, /Picture 3 · da associare/);
  assert.deepEqual(draft, original);
});

test("conferme locali aggiornano subito il menu; token rimossi o di slot vecchi non compaiono", () => {
  const draft = fixture(); draft.pictures[2].confirmed = false;
  assert.equal(visibleReferenceTokens(tokens, draft).length, 2);
  draft.pictures[2].confirmed = true;
  assert.equal(visibleReferenceTokens(tokens, draft).length, 3);
  draft.pictures[2].linked_to_h3 = false;
  assert.equal(visibleReferenceTokens(tokens, draft).length, 2);
  draft.pictures[2].linked_to_h3 = true; draft.pictures[2].slot = 7;
  assert.equal(visibleReferenceTokens(tokens, draft).length, 2);
  draft.pictures.pop(); assert.equal(visibleReferenceTokens(tokens, draft).length, 2);
});

test("sostituzione esplicita cambia solo l'abito del Subject scelto e richiede riconferma", () => {
  const draft = fixture(); draft.active_units.push({ subject: 2, role: "character", sources: [{ picture_id: "p2", attribute: "outfit" }] });
  associatePicture(draft, "p3", 1, "outfit", 1);
  assert.deepEqual(draft.active_units[0].sources, [{ picture_id: "p1", attribute: "identity" }, { picture_id: "p3", attribute: "outfit" }]);
  assert.equal(draft.active_units[0].confirmed, false);
  assert.deepEqual(draft.active_units[1].sources, [{ picture_id: "p2", attribute: "outfit" }]);
  assert.equal(draft.pictures.length, 3);
  assert.equal(visibleReferenceTokens(tokens, draft)[2].requiresAssociation, false);
});

test("aggiungere una sorgente non sostituisce altre associazioni; duplicati e target incompatibili bloccati", () => {
  const draft = fixture(); associatePicture(draft, "p3", 1, "outfit");
  assert.equal(draft.active_units[0].sources.length, 3);
  assert.throws(() => associatePicture(draft, "p3", 1, "outfit"), /già presente/);
  assert.throws(() => associatePicture(fixture(), "p3", 1, "outfit", 0), /da sostituire/);
  draft.active_units[0].role = "object";
  assert.throws(() => associatePicture(draft, "p3", 1, "outfit"), /compatibile/);
});


test("la definizione segue la Picture aggiornata senza duplicare testo nel Subject", () => {
  const draft = fixture(); const unit = draft.active_units[0];
  unit.role="character"; unit.description_en="old red hair";unit.sources=[{picture_id:"p1",attribute:"identity"}];
  draft.pictures[0].description_en="brown hair";
  assert.equal(subjectDefinition(unit,draft.pictures),"brown hair");
  draft.pictures[0].description_en="corrected black hair";
  assert.equal(subjectDefinition(unit,draft.pictures),"corrected black hair");
  unit.definition_mode="manual";
  assert.equal(subjectDefinition(unit,draft.pictures),"old red hair");
});

test("l'identità dal contesto non prende per errore la descrizione dell'abito", () => {
  const draft=fixture();const unit={role:"character",description_en:"Ann from context",sources:[{origin:"context",attribute:"identity"},{picture_id:"p2",attribute:"outfit"}]};
  assert.equal(definitionPicture(unit,draft.pictures),null);
  assert.equal(subjectDefinition(unit,draft.pictures),"Ann from context");
});
