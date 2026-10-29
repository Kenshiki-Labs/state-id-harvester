'use strict';
const $ = id => document.getElementById(id);
let report, indices = [], localIndex = 0, playing = false, timer, selectionEpoch = 0;
let startMark = null, endMark = null, playbackWall = 0, playbackHost = 0, frameReady = false;
const number = value => typeof value === 'number' && Number.isFinite(value);
const display = value => value == null ? 'Unavailable' : number(value) ? String(Number(value.toFixed(6))) : String(value);
function current() { return report.frames[indices[localIndex]]; }
function stop() { playing = false; clearTimeout(timer); $('play').textContent = 'Play segment'; if (report) marks(); }
function fail(error) { stop(); $('error').textContent = String(error.message || error); }
function gapDescription(gap) {
  const delta = number(gap.hostTimeDeltaSeconds) ? ` · host-clock delta ${display(gap.hostTimeDeltaSeconds)} s` : '';
  return gap.reason === 'separate_recording_segments'
    ? `Separate recording segments${delta} · continuity unestablished; this is not a measured missing-capture duration`
    : `${gap.reason}${delta}`;
}
function reviewIntervals() {
  $('review-intervals').replaceChildren();
  for (const observation of report.assessment.observations || []) {
    const container = document.createElement('article'), title = document.createElement('p');
    title.textContent = `${observation.kind} · ${observation.outcome || report.assessment.status}: ${observation.note}`;
    container.append(title);
    for (const [label, frameID] of [['View reviewed interval start', observation.startFrameID], ['View reviewed interval end', observation.endFrameID]]) {
      const button = document.createElement('button'); button.textContent = label;
      button.disabled = !report.frames.some(f => f.recordID === frameID && f.recordingID === observation.recordingID);
      button.onclick = () => { $('segment').value = observation.recordingID; selectSegment(frameID); $('viewport').scrollIntoView({block:'center'}); };
      container.append(button);
    }
    $('review-intervals').append(container);
  }
}
function rows(values) {
  $('metadata').replaceChildren();
  for (const [key, value] of Object.entries(values)) {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = key; dd.textContent = display(value); $('metadata').append(dt, dd);
  }
}
function plot() {
  const canvas = $('motion-chart'), c = canvas.getContext('2d');
  c.clearRect(0, 0, canvas.width, canvas.height);
  const points = indices.map(i => report.frames[i]);
  const valid = points.filter(f => number(f.phoneMotion?.gyroDegreesPerSecond) && number(f.relativeTimeSeconds));
  if (!valid.length) { c.fillStyle = '#b2c1cd'; c.fillText('No aligned rotation-rate samples', 12, 30); return; }
  const start = points[0].relativeTimeSeconds, end = points.at(-1).relativeTimeSeconds;
  const max = Math.max(1, ...valid.map(f => f.phoneMotion.gyroDegreesPerSecond));
  c.fillStyle = '#7bd8cc';
  for (const f of valid) {
    const x = 12 + (f.relativeTimeSeconds - start) / Math.max(0.001, end - start) * (canvas.width - 24);
    const y = 120 - f.phoneMotion.gyroDegreesPerSecond / max * 95;
    c.beginPath(); c.arc(x, y, 2, 0, Math.PI * 2); c.fill();
  }
  c.fillStyle = '#b2c1cd'; c.fillText(`0–${max.toFixed(1)} °/s · dots are aligned samples`, 12, 14);
}
function show(value) {
  const epoch = ++selectionEpoch;
  renderFrame(value, epoch).catch(error => { if (epoch === selectionEpoch) fail(error); });
}
async function renderFrame(value, epoch) {
  localIndex = Math.max(0, Math.min(indices.length - 1, value));
  const frame = current();
  frameReady = false; $('frame').hidden = true; marks();
  if (!frame) { $('position').textContent = 'No retained frames'; rows({}); $('motion').textContent = 'Unavailable'; $('camera').textContent = ''; $('measurements').textContent = ''; $('gap').textContent = ''; return; }
  $('seek').value = localIndex;
  $('previous').disabled = localIndex === 0; $('next').disabled = localIndex === indices.length - 1;
  $('position').textContent = `Frame ${localIndex + 1} / ${indices.length} · segment time ${display(frame.relativeTimeSeconds)} s`;
  const gaps = (report.coverage.gaps || []).filter(g => g.beforeFrameID === frame.recordID || g.afterFrameID === frame.recordID);
  $('gap').textContent = gaps.length ? gaps.map(gapDescription).join(' · ') : '';
  rows({'Record ID': frame.recordID, 'Sequence': frame.sequenceNumber, 'Host timestamp (s)': frame.hostTimeSeconds,
    'Native dimensions': `${frame.width} × ${frame.height}`, 'Presentation': frame.imagePresentation,
    'Previous interval (s)': frame.intervalSeconds, 'Source SHA-256': frame.sourceSHA256});
  const hand = frame.handLandmarks;
  $('hand-status').textContent = hand ? `${hand.status} · ${(hand.resultIDs || []).length} source-bound result(s)` : 'Unavailable · no retained hand analysis';
  $('hand-overlay').disabled = !frame.handOverlayImage;
  $('motion').textContent = frame.phoneMotion?.status === 'aligned'
    ? `Rotation ${display(frame.phoneMotion.gyroDegreesPerSecond)} °/s · motion host ${display(frame.phoneMotion.sampleHostTimeSeconds)} s · alignment Δ ${display(frame.phoneMotion.alignmentDeltaSeconds)} s`
    : 'Phone motion unavailable for this frame';
  $('camera').textContent = JSON.stringify({hostTimeSeconds: frame.hostTimeSeconds, timestamp: frame.timestamp, relativeTimeSeconds: frame.relativeTimeSeconds, camera: frame.camera, geometry: frame.geometry}, null, 2);
  $('measurements').textContent = JSON.stringify(frame.metrics, null, 2);
  // Decode a new image first; a late response cannot overwrite a newer selection.
  const image = new Image();
  const handOverlay = $('hand-overlay').checked && frame.handOverlayImage;
  image.src = `/${handOverlay ? 'hand-frame' : 'frame'}/${indices[localIndex]}`;
  try { await image.decode(); } catch { if (epoch === selectionEpoch) fail('Frame unavailable or evidence changed. Playback stopped.'); return; }
  if (epoch !== selectionEpoch) return;
  image.id = 'frame'; image.alt = handOverlay ? 'Derived hand landmarks on uncropped native frame' : 'Selected uncropped native frame';
  $('frame').replaceWith(image);
  frameReady = true; marks();
  if (playing) {
    const next = report.frames[indices[localIndex + 1]];
    if (!next) { stop(); return; }
    const delay = next.hostTimeSeconds - frame.hostTimeSeconds;
    if (!number(frame.hostTimeSeconds) || !number(next.hostTimeSeconds) || delay <= 0) {
      fail('Playback stopped: missing or non-increasing capture timestamps. Use individual frames.'); return;
    }
    const target = playbackWall + (next.hostTimeSeconds - playbackHost) * 1000;
    timer = setTimeout(() => show(localIndex + 1), Math.max(0, target - performance.now()));
  }
}
function selectSegment(frameID = null) {
  frameReady = false; stop(); ++selectionEpoch;
  indices = report.frames.flatMap((frame, i) => frame.recordingID === $('segment').value ? [i] : []);
  $('seek').max = Math.max(0, indices.length - 1);
  for (const id of ['play', 'previous', 'next', 'seek', 'mark-start', 'mark-end']) $(id).disabled = !indices.length;
  const events = (report.events || []).filter(event => event.recordingID === $('segment').value);
  $('event-count').textContent = `${events.length} raw retained events`;
  $('events').textContent = JSON.stringify(events, null, 2);
  startMark = null; endMark = null; marks(); plot();
  show(Math.max(0, indices.findIndex(i => report.frames[i].recordID === frameID)));
}
function marks() {
  $('mark-start').disabled = !frameReady; $('mark-end').disabled = !frameReady;
  $('play').disabled = !frameReady || !number(current()?.hostTimeSeconds) || (!playing && localIndex >= indices.length - 1);
  $('marks').textContent = startMark || endMark ? `Start ${startMark || 'unset'} → End ${endMark || 'unset'}` : 'No interval marked';
  const start = indices.findIndex(i => report.frames[i].recordID === startMark);
  const end = indices.findIndex(i => report.frames[i].recordID === endMark);
  let issue = '';
  if (!frameReady) issue = 'Wait for a verified frame to finish loading.';
  else if (start < 0 || end < 0) issue = 'Mark the start and end of an interval.';
  else if (end < start) issue = 'The end must follow the start within this recording.';
  else if (!$('reviewer').value.trim() || !$('note').value.trim()) issue = 'Enter a reviewer and observation note.';
  else if ($('outcome').value === 'observed') {
    const kinds = ['object_lift', 'turnover', 'relative_scene_motion'];
    if (!kinds.includes($('kind').value)) issue = 'Positive handling requires object lift, turnover or relative scene motion; contact alone is insufficient.';
    else if (end === start) issue = 'Positive handling requires more than one retained frame.';
    else if ((report.coverage.gaps || []).some(g => {
      const before = indices.findIndex(i => report.frames[i].recordID === g.beforeFrameID);
      const after = indices.findIndex(i => report.frames[i].recordID === g.afterFrameID);
      return before >= start && after <= end && before >= 0 && after >= 0;
    })) issue = 'This interval crosses a coverage gap. Choose a continuous interval or an indeterminate outcome.';
  }
  $('review-issue').textContent = issue;
  $('download').disabled = Boolean(issue);
}
async function init() {
  const response = await fetch('/api/report'); if (!response.ok) throw Error('Report admission failed'); report = await response.json();
  for (const recording of report.recordings) {
    const option = document.createElement('option'); option.value = recording.recordingID;
    option.textContent = `${recording.recordingID} · ${recording.status} · ${recording.frameCount} frames`; $('segment').append(option);
  }
  $('coverage').textContent = `${report.coverage.status} · ${report.coverage.frameCount} frames · ${report.coverage.motionSampleCount} motion samples · ${report.coverage.recordingCount} recording segments`;
  $('gaps').textContent = (report.coverage.gaps || []).map(gapDescription).join('\n');
  $('selection-scope').textContent = report.source.selectionScope === 'selected_still_segments'
    ? 'Selected still-linked segments only · legacy export does not establish a complete recording inventory.'
    : `Selection scope: ${report.source.selectionScope || 'unavailable'}`;
  reviewIntervals();
  $('method').textContent = `${report.method.id} · Measurements describe retained inputs; they do not assign physical authenticity.`;
  $('assessment').textContent = `${report.assessment.status} · ${report.assessment.method} · reviewer: ${report.assessment.reviewerType || 'none'}`;
  $('observations').textContent = JSON.stringify(report.assessment.observations, null, 2);
  selectSegment();
}
$('segment').onchange = () => selectSegment();
$('play').onclick = () => { if (playing) stop(); else { playing = true; playbackWall = performance.now(); playbackHost = current().hostTimeSeconds; $('play').textContent = 'Pause'; show(localIndex); } };
$('previous').onclick = () => { stop(); show(localIndex - 1); };
$('next').onclick = () => { stop(); show(localIndex + 1); };
$('seek').oninput = () => { stop(); show(Number($('seek').value)); };
$('native').onchange = () => $('viewport').classList.toggle('native', $('native').checked);
$('mark-start').onclick = () => { startMark = current()?.recordID; marks(); };
$('mark-end').onclick = () => { endMark = current()?.recordID; marks(); };
for (const id of ['reviewer', 'kind', 'note', 'outcome']) $(id).oninput = marks;
$('download').onclick = () => {
  const first = report.frames.find(f => f.recordID === startMark);
  const last = report.frames.find(f => f.recordID === endMark);
  const draft = {schema: 'id_cadastral_temporal_review_v1', sourceIndexSHA256: report.source.indexSHA256,
    method: 'visual_review', reviewerType: 'human', reviewer: $('reviewer').value.trim(),
    reviewedAt: new Date().toISOString(), status: $('outcome').value,
    observations: [{kind: $('kind').value, outcome: $('outcome').value, recordingID: $('segment').value,
      startFrameID: startMark, endFrameID: endMark, startFrameSHA256: first.sourceSHA256,
      endFrameSHA256: last.sourceSHA256, note: $('note').value.trim()}]};
  const blob = new Blob([JSON.stringify(draft, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = url; anchor.download = 'temporal-review.json'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
init().catch(fail);

$('hand-overlay').onchange = () => { stop(); show(localIndex); };
