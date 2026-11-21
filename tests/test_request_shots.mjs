import assert from 'node:assert/strict';
import test from 'node:test';

import {requestShotSequence, appendRequestShot} from '../app/static/request-shots.js';

test('aggiungere uno Shot a una richiesta esistente conserva il testo come Shot 1', () => {
  const request = appendRequestShot('Una stanza vuota.', 2, 'La ragazza entra.');
  assert.equal(request, '[Shot 1] Una stanza vuota.\n\n[Shot 2] At 00:02.000, La ragazza entra.');
  assert.deepEqual(requestShotSequence(request).map(shot => shot.at_s), [0, 2]);
  assert.throws(() => appendRequestShot(request, 1, 'Si siede.'), /dopo/);
  assert.throws(() => appendRequestShot(request, 10, 'Si siede.', '', 10), /fine/);
});

test('marcatori e inquadrature salvate contano come una sola sequenza', () => {
  let request = appendRequestShot('', 0, 'Anna si siede.', 'full');
  request = appendRequestShot(request, 3.5, 'Usa la battuta d1.', 'close');
  request = appendRequestShot(request, 7, 'Anna si alza.');
  assert.deepEqual(requestShotSequence(request).map(shot => shot.at_s), [0, 3.5, 7]);
  assert.equal(requestShotSequence('#full su Anna. A 3,5 secondi passa a #close su Anna.').length, 2);
  assert.throws(() => requestShotSequence('[Shot 1] La stanza. [Shot 3] At 00:03.000, La porta.'), /senza salti/);
});
