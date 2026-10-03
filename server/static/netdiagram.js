/* 单线图渲染：母线、支路、潮流方向箭头、越限着色。 */
(function (global) {
  'use strict';

  const R = 2.2;

  function esc(text) {
    return String(text).replace(/[&<>]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]));
  }

  function layout(caseData) {
    const buses = caseData.buses || [];
    const xs = buses.map((bus) => bus.x || 0);
    const ys = buses.map((bus) => bus.y || 0);
    const minX = Math.min(...xs, 0), maxX = Math.max(...xs, 100);
    const minY = Math.min(...ys, 0), maxY = Math.max(...ys, 100);
    const spanX = Math.max(maxX - minX, 1);
    const spanY = Math.max(maxY - minY, 1);
    const map = {};
    buses.forEach((bus, index) => {
      const rawX = bus.x !== undefined ? bus.x : (index % 5) * 20 + 10;
      const rawY = bus.y !== undefined ? bus.y : Math.floor(index / 5) * 22 + 12;
      map[bus.id] = {
        x: 8 + (rawX - minX) / spanX * 84,
        y: 10 + (rawY - minY) / spanY * 78,
        bus,
      };
    });
    return map;
  }

  function render(svg, caseData, result, options) {
    options = options || {};
    if (!caseData) { svg.innerHTML = ''; return; }
    const nodes = layout(caseData);
    const busResult = {};
    (result && result.buses ? result.buses : []).forEach((item) => { busResult[item.id] = item; });
    const branchResult = {};
    (result && result.branches ? result.branches : []).forEach((item) => {
      branchResult[`${item.from}-${item.to}`] = item;
      branchResult[`${item.to}-${item.from}`] = item;
    });

    const parts = [];
    parts.push('<defs><marker id="flowArrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path class="flow-arrow" d="M0,0 L6,3 L0,6 z"/></marker></defs>');

    (caseData.branches || []).forEach((branch) => {
      const from = nodes[branch.fbus];
      const to = nodes[branch.tbus];
      if (!from || !to) return;
      const flow = branchResult[`${branch.fbus}-${branch.tbus}`];
      let cls = 'branch-line';
      if (!branch.status) cls += ' offline';
      if (flow) {
        if (flow.loading > 100) cls += ' overload';
        else if (flow.loading > 80) cls += ' heavy';
      }
      const dash = branch.status ? '' : ' stroke-dasharray="2 2" stroke="#c3ccd6"';
      parts.push(`<line class="${cls}" x1="${from.x.toFixed(2)}" y1="${from.y.toFixed(2)}" x2="${to.x.toFixed(2)}" y2="${to.y.toFixed(2)}"${dash}/>`);

      if (flow && branch.status) {
        const power = flow.p_from !== undefined ? flow.p_from : 0;
        const forward = power >= 0;
        const x1 = forward ? from.x : to.x;
        const y1 = forward ? from.y : to.y;
        const x2 = forward ? to.x : from.x;
        const y2 = forward ? to.y : from.y;
        const t0 = 0.3, t1 = 0.7;
        parts.push(`<line x1="${(x1 + (x2 - x1) * t0).toFixed(2)}" y1="${(y1 + (y2 - y1) * t0).toFixed(2)}" x2="${(x1 + (x2 - x1) * t1).toFixed(2)}" y2="${(y1 + (y2 - y1) * t1).toFixed(2)}" stroke="#2f7fd1" stroke-width="1.1" marker-end="url(#flowArrow)" opacity="0.85"/>`);
        const midX = (from.x + to.x) / 2;
        const midY = (from.y + to.y) / 2;
        parts.push(`<text class="edge-label" x="${midX.toFixed(2)}" y="${(midY - 1.4).toFixed(2)}" text-anchor="middle">${flow.loading.toFixed(0)}%</text>`);
      } else if (branch.is_transformer) {
        const midX = (from.x + to.x) / 2;
        const midY = (from.y + to.y) / 2;
        parts.push(`<text class="edge-label" x="${midX.toFixed(2)}" y="${(midY - 1.4).toFixed(2)}" text-anchor="middle">k=${branch.tap}</text>`);
      }
    });

    (caseData.buses || []).forEach((entry) => {
      const node = nodes[entry.id];
      if (!node) return;
      const info = busResult[entry.id];
      const kind = (entry.type || 'PQ').toLowerCase();
      const vm = info ? info.vm : entry.vm;
      const violate = info && (vm < (entry.vmin || 0.9) - 1e-9 || vm > (entry.vmax || 1.1) + 1e-9);
      const cls = `bus-node ${kind}${violate ? ' violate' : ''}`;
      const radius = entry.type === 'SLACK' ? R * 1.15 : R;
      parts.push(`<g class="${cls}">`);
      parts.push(`<circle class="shell" cx="${node.x.toFixed(2)}" cy="${node.y.toFixed(2)}" r="${radius.toFixed(2)}"/>`);
      parts.push(`<text x="${node.x.toFixed(2)}" y="${(node.y + 0.85).toFixed(2)}">${entry.id}</text>`);
      parts.push(`<text class="vm" x="${node.x.toFixed(2)}" y="${(node.y + radius + 2.6).toFixed(2)}">${vm.toFixed(3)}</text>`);
      if (options.showNames !== false && entry.name) {
        parts.push(`<text class="vm" x="${node.x.toFixed(2)}" y="${(node.y - radius - 1.4).toFixed(2)}">${esc(entry.name)}</text>`);
      }
      parts.push('</g>');
    });

    svg.innerHTML = parts.join('');
  }

  global.NetDiagram = { render, layout };
})(window);
