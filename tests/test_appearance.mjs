import assert from 'node:assert/strict';
import test from 'node:test';
import { appearanceKey, createAppearance, readAppearance } from '../app/static/appearance.js';
import { diagnostic, setUiLanguage, t, tr } from '../app/static/i18n.js';

function browser(initial) {
  let stored = initial;
  const win = { localStorage: {
    getItem: key => key === appearanceKey ? stored : null,
    setItem: (key, value) => { assert.equal(key, appearanceKey); stored = value; }
  } };
  const controls = Object.fromEntries(['color-scheme', 'ui-language'].map(id => [id, {
    value: '', addEventListener(event, callback) { this[event] = callback; }
  }]));
  const heading = { data: 'Impostazioni utente', parentElement: { closest: () => null } };
  const draft = { value: 'Impostazioni utente' };
  const doc = {
    documentElement: { lang: 'it', dataset: {} }, body: {},
    getElementById: id => controls[id],
    createTreeWalker() {
      const nodes = [heading];
      return { nextNode: () => nodes.shift() || null };
    },
    querySelectorAll: () => []
  };
  return { doc, win, controls, heading, draft };
}

test('theme and language apply separately, persist, and leave user input intact', () => {
  const { doc, win, controls, heading, draft } = browser('{"theme":"dark","language":"en"}');
  let languageChanges = 0;
  createAppearance(doc, win, () => { languageChanges++; });
  assert.equal(doc.documentElement.dataset.theme, 'dark');
  assert.equal(doc.documentElement.lang, 'en');
  assert.equal(heading.data, 'User settings');
  assert.equal(draft.value, 'Impostazioni utente');
  controls['color-scheme'].value = 'light';
  controls['color-scheme'].change();
  assert.equal(languageChanges, 0);
  controls['ui-language'].value = 'it';
  controls['ui-language'].change();
  assert.equal(languageChanges, 1);
  assert.equal(heading.data, 'Impostazioni utente');
  assert.deepEqual(readAppearance(win), { theme: 'light', language: 'it' });
});

test('localized diagnostics keep user-provided names and values as written', () => {
  setUiLanguage('en');
  try {
    assert.equal(t('  Impostazioni utente  '), '  User settings  ');
    assert.equal(tr`Scena ${2} · ${'La mia scena'} / Cut ${1} · ${'Tazza $& {0}'}`,
      'Scene 2 · La mia scena / Cut 1 · Tazza $& {0}');
    assert.equal(diagnostic('Durata utile totale selezionata: 5 s.'), 'Total selected running time: 5 s.');
    assert.equal(diagnostic('Unknown upstream message'), 'Unknown upstream message');
  } finally {
    setUiLanguage('it');
  }
});
