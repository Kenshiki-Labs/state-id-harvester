// Execute this expression with Playwright browser_evaluate against a reviewed report.
// No artifact is modified and no review is submitted or downloaded.
async () => {
  const byID = id => document.getElementById(id);
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const until = async predicate => {
    const deadline = performance.now() + 10000;
    while (!predicate()) { if (performance.now() > deadline) throw Error('Browser condition timed out'); await new Promise(r => setTimeout(r, 20)); }
  };
  const data = await (await fetch('/api/report')).json();
  const observation = data.assessment.observations[0];
  assert(observation, 'Reviewed interval required');
  const buttons = document.querySelectorAll('#review-intervals button');
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const decode = Image.prototype.decode;
  try {
    Image.prototype.decode = function() { return Promise.all([decode.call(this), gate]).then(() => undefined); };
    buttons[0].click();
    assert(byID('play').disabled && byID('mark-start').disabled, 'Controls enabled during decode');
  } finally { Image.prototype.decode = decode; release(); }
  await until(() => !byID('mark-start').disabled);
  assert(document.querySelector('#metadata dd').textContent === observation.startFrameID, 'Wrong start endpoint');
  const first = data.frames.find(f => f.recordID === observation.startFrameID);
  assert(byID('frame').naturalWidth === first.width && byID('frame').naturalHeight === first.height, 'Native dimensions changed');
  byID('mark-start').click();
  // End jump intentionally resets draft marks as it selects a segment again.
  buttons[1].click();
  await until(() => !byID('mark-end').disabled);
  assert(document.querySelector('#metadata dd').textContent === observation.endFrameID, 'Wrong end endpoint');
  assert(byID('download').disabled, 'Jump retained stale draft marks');
  assert(byID('assessment').textContent.includes(data.assessment.reviewerType), 'Reviewer attribution absent');
  if (data.source.selectionScope === 'selected_still_segments') assert(byID('selection-scope').textContent.includes('does not establish a complete'), 'Selection scope missing');
  const events = data.events.filter(e => e.recordingID === first.recordingID);
  assert(byID('event-count').textContent.startsWith(String(events.length)), 'Events not segment scoped');
  const gap = data.coverage.gaps.find(g => g.reason === 'separate_recording_segments' && g.beforeFrameID === observation.endFrameID);
  if (gap) assert(byID('gap').textContent.includes('continuity unestablished') && byID('gap').textContent.includes('host-clock delta'), 'Boundary overclaimed');
  assert(!byID('error').textContent, 'Viewer error');
  buttons[0].click();
  await until(() => !byID('mark-start').disabled);
  return {status:'passed', nativeDimensions:[first.width,first.height], checks:['decode admission','review endpoint jumps','reviewer attribution','selection scope','event scope','segment clock label']};
}
