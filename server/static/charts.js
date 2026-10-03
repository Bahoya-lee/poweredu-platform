/* 轻量 SVG 绘图库：折线、柱状、对数收敛曲线。无任何外部依赖。 */
(function (global) {
  'use strict';

  const PALETTE = ['#2f7fd1', '#d64545', '#12a594', '#d9822b', '#7a5af8', '#0f8f3f'];

  function size(svg) {
    const box = (svg.getAttribute('viewBox') || '0 0 640 220').split(/\s+/).map(Number);
    return { w: box[2] || 640, h: box[3] || 220 };
  }

  function esc(text) {
    return String(text).replace(/[&<>]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]));
  }

  function niceTicks(min, max, count) {
    if (min === max) { max = min + 1; }
    const raw = (max - min) / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
    const start = Math.ceil(min / step) * step;
    const ticks = [];
    for (let value = start; value <= max + step * 0.001; value += step) {
      ticks.push(Math.round(value / step) * step);
    }
    return ticks;
  }

  function frame(svg, opts) {
    const { w, h } = size(svg);
    const pad = Object.assign({ l: 40, r: 14, t: 12, b: 26 }, opts.pad || {});
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    let parts = '';
    return { w, h, pad, plotW, plotH, parts };
  }

  function axisTicks(f, opts) {
    let out = '';
    const xTicks = opts.xTicks || niceTicks(opts.xMin, opts.xMax, opts.xCount || 5);
    const yTicks = opts.yTicks || niceTicks(opts.yMin, opts.yMax, opts.yCount || 4);
    const sx = (v) => f.pad.l + (v - opts.xMin) / (opts.xMax - opts.xMin || 1) * f.plotW;
    const sy = (v) => f.pad.t + f.plotH - (v - opts.yMin) / (opts.yMax - opts.yMin || 1) * f.plotH;
    yTicks.forEach((tick) => {
      out += `<line class="chart-grid" x1="${f.pad.l}" y1="${sy(tick).toFixed(2)}" x2="${f.pad.l + f.plotW}" y2="${sy(tick).toFixed(2)}"/>`;
      out += `<text class="chart-label" x="${f.pad.l - 5}" y="${(sy(tick) + 3).toFixed(2)}" text-anchor="end">${opts.yFormat ? opts.yFormat(tick) : tick}</text>`;
    });
    xTicks.forEach((tick) => {
      out += `<line class="chart-grid" x1="${sx(tick).toFixed(2)}" y1="${f.pad.t}" x2="${sx(tick).toFixed(2)}" y2="${f.pad.t + f.plotH}"/>`;
      out += `<text class="chart-label" x="${sx(tick).toFixed(2)}" y="${f.pad.t + f.plotH + 14}" text-anchor="middle">${opts.xFormat ? opts.xFormat(tick) : tick}</text>`;
    });
    out += `<line class="chart-axis" x1="${f.pad.l}" y1="${f.pad.t + f.plotH}" x2="${f.pad.l + f.plotW}" y2="${f.pad.t + f.plotH}"/>`;
    out += `<line class="chart-axis" x1="${f.pad.l}" y1="${f.pad.t}" x2="${f.pad.l}" y2="${f.pad.t + f.plotH}"/>`;
    if (opts.xLabel) out += `<text class="chart-label" x="${f.pad.l + f.plotW / 2}" y="${f.h - 3}" text-anchor="middle">${esc(opts.xLabel)}</text>`;
    if (opts.yLabel) out += `<text class="chart-label" x="10" y="${f.pad.t + 8}" text-anchor="start">${esc(opts.yLabel)}</text>`;
    return { out, sx, sy };
  }

  function line(svg, series, opts) {
    opts = opts || {};
    const f = frame(svg, opts);
    const points = series.flatMap((item) => item.points || []);
    if (!points.length) { svg.innerHTML = '<text class="chart-label" x="20" y="40">暂无数据</text>'; return; }
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const xMin = opts.xMin !== undefined ? opts.xMin : Math.min(...xs);
    const xMax = opts.xMax !== undefined ? opts.xMax : Math.max(...xs);
    const yMin = opts.yMin !== undefined ? opts.yMin : Math.min(...ys);
    const yMax = opts.yMax !== undefined ? opts.yMax : Math.max(...ys);
    const range = Object.assign({}, opts, { xMin, xMax, yMin, yMax });
    const { out, sx, sy } = axisTicks(f, range);
    let body = out;
    series.forEach((item, index) => {
      const color = item.color || PALETTE[index % PALETTE.length];
      const path = (item.points || []).map((point, i) =>
        `${i === 0 ? 'M' : 'L'}${sx(point[0]).toFixed(2)},${sy(point[1]).toFixed(2)}`).join(' ');
      body += `<path d="${path}" fill="none" stroke="${color}" stroke-width="${item.width || 1.6}"/>`;
    });
    let legend = '';
    series.forEach((item, index) => {
      const color = item.color || PALETTE[index % PALETTE.length];
      legend += `<g transform="translate(${f.pad.l + index * 78},${f.pad.t - 2})">`
        + `<rect width="8" height="3" y="-3" fill="${color}"/>`
        + `<text class="chart-label" x="11" y="0">${esc(item.name || '')}</text></g>`;
    });
    svg.innerHTML = body + legend;
  }

  function bar(svg, labels, values, opts) {
    opts = opts || {};
    const f = frame(svg, Object.assign({ pad: { l: 34, r: 10, t: 16, b: 34 } }, opts));
    if (!values.length) { svg.innerHTML = '<text class="chart-label" x="20" y="40">暂无数据</text>'; return; }
    const maxValue = Math.max(opts.yMax || 0, ...values.map((v) => Math.abs(v))) * 1.15 || 1;
    const range = { xMin: 0, xMax: labels.length, yMin: 0, yMax: maxValue };
    const { out, sx, sy } = axisTicks(f, Object.assign({}, opts, range, {
      xTicks: labels.map((_, i) => i + 0.5),
      xFormat: (v) => esc(labels[Math.round(v - 0.5)] || ''),
    }));
    let body = out;
    const slot = f.plotW / labels.length;
    values.forEach((value, index) => {
      const x = sx(index + 0.5) - slot * 0.32;
      const width = slot * 0.64;
      const y = sy(Math.max(value, 0));
      const height = Math.abs(sy(0) - sy(value));
      const color = opts.colorFor ? opts.colorFor(value, index) : PALETTE[0];
      body += `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${width.toFixed(2)}" height="${height.toFixed(2)}" rx="1.5" fill="${color}"/>`;
      if (opts.showValue) {
        body += `<text class="chart-label" x="${(x + width / 2).toFixed(2)}" y="${(y - 2).toFixed(2)}" text-anchor="middle">${value.toFixed(1)}</text>`;
      }
    });
    svg.innerHTML = body;
  }

  function convergence(svg, history) {
    if (!history || !history.length) { svg.innerHTML = '<text class="chart-label" x="20" y="40">暂无迭代数据</text>'; return; }
    const floor = 1e-12;
    const points = history.map((item) => [item.iter, Math.max(item.mismatch, floor)]);
    const top = Math.max(...points.map((p) => p[1]));
    line(svg, [{ name: '最大不平衡量', points, color: '#2f7fd1' }], {
      xLabel: '迭代次数', yLabel: '不平衡量(p.u.)',
      xMin: 1, xMax: points[points.length - 1][0],
      yMin: floor, yMax: top * 2,
      yTicks: [1e-12, 1e-9, 1e-6, 1e-3, 1].filter((v) => v >= floor && v <= top * 2),
      yFormat: (v) => (v >= 0.001 ? v.toExponential(0) : `1e${Math.round(Math.log10(v))}`),
    });
  }

  global.Charts = { line, bar, convergence, PALETTE };
})(window);
