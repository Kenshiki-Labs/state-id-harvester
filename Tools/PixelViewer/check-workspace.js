// Run with playwright-cli run-code --filename Tools/PixelViewer/check-workspace.js
// Requires edges, topology and measurement packages; optional branches remain explicit. Checks presentation, not physical accuracy.
async page => {
  await page.waitForFunction(() => window.workspaceCapabilities?.allRetained);
  const required = ['edges-visible', 'measure-diagonals', 'measure-lines', 'measure-radii'];
  const missing = await page.evaluate(() => Object.entries({edges, topology, measurements})
    .filter(([, value]) => !value).map(([name]) => name));
  if (missing.length) throw Error('Incomplete viewer launch: ' + missing.join(', '));
  await page.waitForFunction(() => window.analysisInventory);
  const before = await page.evaluate(() => JSON.stringify({
    original: [views.original.scale, views.original.tx, views.original.ty],
    rectified: [views.rectified.scale, views.rectified.tx, views.rectified.ty], pinned,
    values: Array.from(document.querySelectorAll('input,select')).map(e => [e.id, e.value, e.checked])
  }));
  for (const name of ['Layers', 'Measure', 'Analyze', 'Data', 'Inspect']) {
    await page.getByRole('tab', {name, exact: true}).click();
    for (const id of required) {
      if (!await page.locator('#' + id).isVisible()) throw Error('Hidden overlay control: ' + id);
    }
    const after = await page.evaluate(() => JSON.stringify({
      original: [views.original.scale, views.original.tx, views.original.ty],
      rectified: [views.rectified.scale, views.rectified.tx, views.rectified.ty], pinned,
      values: Array.from(document.querySelectorAll('input,select')).map(e => [e.id, e.value, e.checked])
    }));
    if (before !== after) throw Error('Tab switch changed inspection state: ' + name);
  }
  // Overlay comparisons use the same registered image on both sides of the test.
  await page.locator('#rectification-version').selectOption('boundary');
  const rendered = [];
  for (const [id, pane] of [['edges-visible', 'original'], ['measure-diagonals', 'rectified'],
                            ['measure-lines', 'rectified'], ['measure-radii', 'rectified']]) {
    const control = page.locator('#' + id), saved = await control.isChecked();
    // Read every displayed canvas pixel. This does not sample or alter analysis inputs.
    const fingerprint = () => page.evaluate(name => {
      const v = views[name]; v.draw();
      const bytes = v.ctx.getImageData(0, 0, v.canvas.width, v.canvas.height).data;
      let hash = 2166136261;
      for (const byte of bytes) hash = Math.imul(hash ^ byte, 16777619) >>> 0;
      return hash;
    }, pane);
    try {
      // Warm up canvas readback before the comparison (browser GPU/CPU transition).
      await fingerprint(); await fingerprint();
      await control.setChecked(false); const off = await fingerprint();
      await control.setChecked(true); const on = await fingerprint();
      await control.setChecked(false); const restored = await fingerprint();
      if (on === off || restored !== off) throw Error('Overlay rendering regression: ' + id);
      rendered.push({id, off, on, restored});
    } finally { await control.setChecked(saved); }
  }
  await page.getByRole('tab', {name: 'Measure', exact: true}).click();
  const geometry = await page.locator('#measure-model-details').textContent();
  if (!geometry.includes('3–4–5') || !geometry.includes('Corner radii')) throw Error('Missing geometry diagnostics');
  const savedMeasurement = await page.evaluate(() => ({
    axis: document.getElementById('measure-axis').value,
    index: document.getElementById('measure-index').value,
    position: document.getElementById('measure-position').value,
    selection: measurementSelection,
    details: document.getElementById('measure-details').textContent
  }));
  try {
    for (const axis of ['x', 'y']) {
      await page.locator('#measure-axis').selectOption(axis);
      const index = await page.evaluate(a => Math.floor(measurements.manifest.grids.rectified[a === 'x' ? 'height' : 'width'] / 2), axis);
      await page.locator('#measure-index').fill(String(index));
      await page.locator('#measure-select').click();
      const details = await page.locator('#measure-details').textContent();
      if (!details.includes('outer span') || !details.includes('mm')) throw Error('Scanline measurement missing: ' + axis);
    }
  } finally {
    await page.evaluate(saved => {
      document.getElementById('measure-axis').value = saved.axis;
      document.getElementById('measure-index').value = saved.index;
      document.getElementById('measure-position').value = saved.position;
      document.getElementById('measure-details').textContent = saved.details;
      measurementSelection = saved.selection;
      views.rectified.draw();
    }, savedMeasurement);
  }
  await page.getByRole('tab', {name: 'Inspect', exact: true}).click();
  return {retained: await page.evaluate(() => window.workspaceCapabilities), tabs: 5, rendered};
}
