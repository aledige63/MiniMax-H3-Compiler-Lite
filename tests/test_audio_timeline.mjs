import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../app/static/audio-timeline.js', import.meta.url));
const { audioTimeline } = await import(`data:text/javascript;base64,${source.toString('base64')}`);
const track = (slot, settings = {}) => ({
  slot, media_id: `file-${slot}`, role: 'speech', measured_duration_s: 3,
  sample_rate: 24000, offset_s: 0, ...settings,
});

test('la timeline usa durata del segmento e inizio nel cut, indipendentemente dallo slot', () => {
  const later = track(1, { measured_duration_s: 9, segment_start_s: 4, segment_end_s: 6.5, offset_s: 3 });
  const earlier = track(2);
  const result = audioTimeline([later, earlier], 6);
  assert.deepEqual(result.tracks.map(({ audio, start, end }) => [audio.slot, start, end]), [[2, 0, 3], [1, 3, 5.5]]);
  assert.deepEqual(result.overlaps, []);
  assert.equal(audioTimeline([later, { ...earlier, offset_s: 1 }], 6).overlaps[0].end, 4);
});

test('distingue battute adiacenti, sovrapposte e tracce senza evento parlato', () => {
  const first = track(2, { offset_s: 0.1, measured_duration_s: 0.2 });
  const second = track(1, { offset_s: 0.3 });
  assert.equal(audioTimeline([first, second], null).overlaps.length, 0);
  const tracks = [
    track(1), track(2, { measured_duration_s: 5.155 }),
    track(3, { role: 'voice' }), track(4, { role: 'sound' }),
    track(5, { media_id: null }), track(6, { segment_end_s: 10 }),
  ];
  const result = audioTimeline(tracks, 6);
  assert.equal(result.tracks.length, 2);
  assert.deepEqual(result.overlaps.map(({ start, end }) => [start, end]), [[0, 3]]);
});

test('segnala la fine oltre il cut dichiarato e usa il limite di 15 s per durata automatica', () => {
  const audio = track(1, { offset_s: 5 });
  assert.equal(audioTimeline([audio], 8).tracks[0].overrun, false);
  assert.equal(audioTimeline([audio], 7).tracks[0].overrun, true);
  assert.equal(audioTimeline([audio], 8 - 1 / 48000).tracks[0].overrun, false);
  const automatic = audioTimeline([track(2, { offset_s: 14 })], null);
  assert.equal(automatic.declared, false);
  assert.equal(automatic.limit, 15);
  assert.equal(automatic.tracks[0].overrun, true);
});
