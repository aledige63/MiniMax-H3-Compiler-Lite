// I metadati del file devono arrivare anche se nel frattempo si modifica il cut.
export function applyUploadedAudio(current, uploaded, original) {
  for (const key of ["media_id", "measured_duration_s", "sample_rate", "sample_count", "channels"]) {
    current[key] = uploaded[key];
  }
  for (const key of ["name", "segment_start_s", "segment_end_s", "transcript"]) {
    if (current[key] === original[key]) current[key] = uploaded[key];
  }
  current.confirmed = false;
  current.linked_to_h3 = false;
}
