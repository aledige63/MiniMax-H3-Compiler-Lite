// La timeline usa gli intervalli dei segmenti collocati nel cut, in secondi.
export function audioTimeline(audioReferences, declaredDuration) {
  const declared = Number.isFinite(declaredDuration) && declaredDuration >= 4 && declaredDuration <= 15;
  const limit = declared ? declaredDuration : 15;
  const tracks = [];
  for (const audio of audioReferences) {
    if ((audio.role ?? "speech") !== "speech" || !audio.media_id) continue;
    const sourceStart = audio.segment_start_s ?? 0;
    const sourceEnd = audio.segment_end_s ?? audio.measured_duration_s;
    const start = audio.offset_s ?? 0;
    const sample = audio.sample_rate > 0 ? 1 / audio.sample_rate : 0;
    const duration = sourceEnd - sourceStart;
    const end = start + duration;
    if (![sourceStart, sourceEnd, audio.measured_duration_s, start, end].every(Number.isFinite)
        || sourceStart < 0 || duration <= 0 || sourceEnd > audio.measured_duration_s + sample || start < 0) continue;
    tracks.push({ audio, start, end, overrun: end > limit + sample });
  }
  tracks.sort((a, b) => a.start - b.start || a.audio.slot - b.audio.slot);
  const overlaps = [];
  for (const [index, first] of tracks.entries()) {
    for (const second of tracks.slice(index + 1)) {
      const end = Math.min(first.end, second.end);
      // Tollera solo gli artefatti del calcolo in virgola mobile, non il parlato sovrapposto.
      if (end - second.start > 1e-9) overlaps.push({ first, second, start: second.start, end });
    }
  }
  return { declared, limit, tracks, overlaps };
}
