/* Standalone control-coverage viewer for alignment HTML reports. */
(() => {
  'use strict';

  function init() {
    const $ = id => document.getElementById(id);
    const section = $('coverageAudit'), canvas = $('coverageMap');
    const flightInput = $('coverageFlight'), roleInput = $('coverageRole');
    const detail = $('coverageDetail'), pointTable = $('coveragePointTable');
    const counter = $('coverageMapCount');
    if (!section || !canvas || !flightInput || !roleInput || !detail || !pointTable || !counter) return;

    const data = window.alignmentReportData?.control_coverage || {};
    const points = Array.isArray(data.points) ? data.points : [];
    const flights = Array.isArray(data.flights) ? data.flights : [];
    const units = String(data.units || window.alignmentReportData?.units || 'project units');
    const roles = {
      fitting_control: {label: 'Fitting control', color: '#783f9a', shape: 'square'},
      reference: {label: 'Reference', color: '#b17a19', shape: 'diamond'},
      independent: {label: 'Independent', color: '#1b7894', shape: 'triangle'},
      excluded: {label: 'Excluded', color: '#6d7781', shape: 'cross'}
    };
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
    const finite = value => typeof value === 'number' && Number.isFinite(value);
    const number = value => finite(value) ? value.toFixed(4) : 'Unavailable';
    const list = value => Array.isArray(value) ? value : [];
    const roleName = role => roles[role]?.label || String(role || 'Unspecified');
    const sourceLabels = {
      control_csv: 'Reference PID CSV',
      report_checkpoints: 'Report check CSV',
      fitting_control_array: 'Supplied fitting controls'
    };
    const sourceName = value => String(value ?? '').split(' + ').map(part => {
      const code = part.trim();
      return Object.prototype.hasOwnProperty.call(sourceLabels, code) ? sourceLabels[code] : code;
    }).join(' + ');
    const pointName = index => String(points[index]?.id ?? ('Mark ' + (index + 1)));
    const flightKey = value => String(value);
    const roleNote = point => {
      const note = String(point?.role_note || '').trim();
      return point?.role_conflict === true ?
        'Warning: role conflict. ' + (note || 'Conflicting source roles reported.') : note;
    };
    const table = (headers, rows) => '<table><thead><tr>' +
      headers.map(h => '<th scope="col">' + esc(h) + '</th>').join('') +
      '</tr></thead><tbody>' + rows.map(row => '<tr>' +
        row.map(cell => '<td>' + esc(cell) + '</td>').join('') +
      '</tr>').join('') + '</tbody></table>';

    let selected = points.length ? 0 : -1, shown = [], hits = [], framePending = false;
    let flight = 'all', role = 'all';
    // Keep the CSS box independent of the high-DPI backing bitmap.
    const initialHeight = canvas.clientHeight || 310;
    if (!canvas.style.width) canvas.style.width = '100%';
    if (!canvas.style.height) canvas.style.height = initialHeight + 'px';
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'North-up control coverage; use the mark table to select a mark.');

    function readFilters() {
      const value = String(flightInput.value).trim();
      flight = /^-?\d+$/.test(value) ? value : 'all';
      role = Object.prototype.hasOwnProperty.call(roles, roleInput.value) ? roleInput.value : 'all';
    }

    function localSupport(point) {
      let supported = 0, rejected = 0, returns = 0, matched = 0, reasons = [];
      for (const record of list(point?.flights)) {
        if (!record || (flight !== 'all' && flightKey(record.strip) !== flight)) continue;
        matched++;
        if (record.supported === true) supported++;
        else rejected++;
        if (finite(record.n) && record.n > 0) returns += record.n;
        if (record.supported !== true) reasons.push(
          (flight === 'all' ? 'Flight ' + record.strip + ': ' : '') +
          String(record.reason || 'No local support.')
        );
      }
      return {
        supported: supported > 0, returns,
        status: !matched ? 'No local support record' :
          flight === 'all' ? supported + ' supported / ' + rejected + ' rejected' :
            supported ? 'Supported' : 'Rejected / unsupported',
        reason: !matched ? (flight === 'all' ? 'No local support records supplied.' :
          'No local support record for flight ' + flight + '.') : reasons.join(' · ')
      };
    }

    function flightRows() {
      const rows = [];
      for (const entry of flights) {
        if (!entry || (flight !== 'all' && flightKey(entry.strip) !== flight)) continue;
        const counts = Object.keys(roles).map(key => {
          const count = entry.counts?.[key] || {};
          return (count.supported ?? 0) + ' supported / ' + (count.rejected ?? 0) + ' rejected' +
            (count.eligible_sites == null ? '' : ' / ' + count.eligible_sites + ' eligible sites');
        });
        rows.push([
          entry.strip, sourceName(entry.source_id), list(entry.clouds).join(' · '), entry.trajectory_path,
          entry.basis ? roleName(entry.basis) : 'Unavailable', entry.usable_sites ?? 0,
          list(entry.flags).join(' · ') || 'None', ...counts
        ]);
      }
      return rows;
    }

    function renderDetail() {
      let html = '';
      if (selected >= 0) {
        const point = points[selected] || {}, support = localSupport(point);
        const hidden = role !== 'all' && point.role !== role;
        html += '<p><strong>' + esc(pointName(selected)) + '</strong> · ' +
          esc(roleName(point.role)) + ' · source: ' + esc(sourceName(point.source) || 'Unavailable') +
          ' · E ' + esc(number(point.easting)) + ' · N ' + esc(number(point.northing)) +
          ' · survey Z ' + esc(number(point.survey_z)) + ' ' + esc(units) + '. ' +
          esc(flight === 'all' ? 'All flights: ' : 'Flight ' + flight + ': ') +
          esc(support.status) + '. ' + esc(support.reason) +
          (hidden ? ' Selected mark is hidden by the role filter.' : '') +
          (!finite(point.easting) || !finite(point.northing) ?
            ' This mark has no valid XY coordinates and is available in the table.' : '') + '</p>';
        const note = roleNote(point);
        if (note) {
          html += point.role_conflict === true ?
            '<p class="notice"><strong>' + esc(note) + '</strong></p>' : '<p>' + esc(note) + '</p>';
        }
        const records = [], recorded = new Set();
        for (const record of list(point.flights)) {
          if (!record) continue;
          const key = flightKey(record.strip);
          recorded.add(key);
          records.push([
            key + (key === flight ? ' (selected)' : ''), record.n ?? 0,
            record.supported === true ? 'Supported' : 'Rejected / unsupported',
            record.reason || (record.supported === true ? 'Local support available.' : 'No local support.')
          ]);
        }
        const missing = new Set();
        for (const entry of flights) if (entry) missing.add(flightKey(entry.strip));
        if (flight !== 'all') missing.add(flight);
        for (const key of missing) if (!recorded.has(key)) {
          records.push([key + (key === flight ? ' (selected)' : ''), 0,
            'Unsupported', 'No local support record supplied.']);
        }
        html += table(['Flight', 'Returns', 'Local support', 'Reason'], records);
      } else {
        html += '<p>No survey marks supplied.</p>';
      }
      const metadata = flightRows();
      html += '<details' + (flight !== 'all' ? ' open' : '') +
        '><summary>Flight coverage, sources and flags (' + metadata.length + ')</summary>';
      html += metadata.length ? table([
        'Flight', 'Source', 'Clouds', 'Trajectory', 'Coverage basis', 'Usable sites', 'Flags',
        'Fitting control', 'Reference', 'Independent', 'Excluded'
      ], metadata) : '<p>No flight metadata supplied for this selection.</p>';
      html += '</details>';
      detail.innerHTML = html;
    }

    function renderPoints() {
      const headers = ['Mark', 'Source', 'Role', 'Role warning / note', 'Easting', 'Northing', 'Survey Z',
        flight === 'all' ? 'Local support across flights' : 'Local support: flight ' + flight,
        'Returns', 'Rejection / reason'];
      let html = '<table><thead><tr>' + headers.map(h => '<th scope="col">' +
        esc(h) + '</th>').join('') + '</tr></thead><tbody>';
      for (const index of shown) {
        const point = points[index] || {}, support = localSupport(point);
        html += '<tr' + (index === selected ? ' style="background:#eaf2f7"' : '') +
          '><td><button type="button" data-coverage-index="' + index +
          '" aria-pressed="' + (index === selected) + '">' + esc(pointName(index)) +
          '</button></td>' + [
            sourceName(point.source), roleName(point.role), roleNote(point), number(point.easting), number(point.northing),
            number(point.survey_z), support.status, support.returns, support.reason
          ].map(cell => '<td>' + esc(cell) + '</td>').join('') + '</tr>';
      }
      html += '</tbody></table>';
      if (!shown.length) html += '<p>' + (points.length ?
        'No marks match the role filter.' : 'No survey marks supplied.') + '</p>';
      pointTable.innerHTML = html;
    }

    function bounds() {
      // Reduce in place: no argument spreading or temporary coordinate arrays.
      let minE = Infinity, maxE = -Infinity, minN = Infinity, maxN = -Infinity;
      function add(e, n) {
        if (!finite(e) || !finite(n)) return;
        if (e < minE) minE = e;
        if (e > maxE) maxE = e;
        if (n < minN) minN = n;
        if (n > maxN) maxN = n;
      }
      for (const index of shown) {
        const point = points[index];
        if (point) add(point.easting, point.northing);
      }
      for (const entry of flights) {
        if (!entry || (flight !== 'all' && flightKey(entry.strip) !== flight)) continue;
        for (const corner of list(entry.extent)) if (Array.isArray(corner)) add(corner[0], corner[1]);
      }
      return minE === Infinity ? null : {minE, maxE, minN, maxN};
    }

    function marker(g, x, y, point, support, active) {
      const style = roles[point?.role] || {color: '#526c7e', shape: 'circle'};
      const radius = active ? 6 : 4;
      g.setLineDash([]);
      if (active) {
        g.beginPath(); g.arc(x, y, 11, 0, Math.PI * 2);
        g.fillStyle = '#fff'; g.fill(); g.lineWidth = 2;
        g.strokeStyle = '#193548'; g.stroke();
      }
      g.beginPath();
      if (style.shape === 'square') g.rect(x - radius, y - radius, radius * 2, radius * 2);
      else if (style.shape === 'diamond') {
        g.moveTo(x, y - radius - 1); g.lineTo(x + radius + 1, y);
        g.lineTo(x, y + radius + 1); g.lineTo(x - radius - 1, y); g.closePath();
      } else if (style.shape === 'triangle') {
        g.moveTo(x, y - radius - 1); g.lineTo(x + radius + 1, y + radius);
        g.lineTo(x - radius - 1, y + radius); g.closePath();
      } else if (style.shape === 'cross') {
        g.moveTo(x - radius, y - radius); g.lineTo(x + radius, y + radius);
        g.moveTo(x - radius, y + radius); g.lineTo(x + radius, y - radius);
      } else g.arc(x, y, radius, 0, Math.PI * 2);
      g.fillStyle = style.color; g.strokeStyle = style.color; g.lineWidth = 2;
      if (support && style.shape !== 'cross') g.fill();
      g.stroke();
      if (!support) {
        g.beginPath(); g.arc(x, y, active ? 14 : 8, 0, Math.PI * 2);
        g.strokeStyle = '#b65d40'; g.lineWidth = 1.5; g.setLineDash([3, 2]); g.stroke();
      }
      g.setLineDash([]);
    }

    function draw() {
      hits = [];
      const w = Math.max(1, canvas.clientWidth || canvas.getBoundingClientRect().width || 640);
      const h = Math.max(1, canvas.clientHeight || initialHeight);
      const ratio = finite(window.devicePixelRatio) && window.devicePixelRatio > 0 ?
        Math.min(window.devicePixelRatio, 4) : 1;
      canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio);
      const g = canvas.getContext('2d');
      let mapped = 0;
      for (const index of shown) if (finite(points[index]?.easting) && finite(points[index]?.northing)) mapped++;
      counter.textContent = shown.length + ' / ' + points.length + ' marks · ' + mapped + ' mapped';
      if (!g) return;
      g.setTransform(ratio, 0, 0, ratio, 0, 0);
      g.fillStyle = '#f5f8fa'; g.fillRect(0, 0, w, h);
      g.font = '11px system-ui'; g.fillStyle = '#526c7e';
      const box = bounds();
      if (!box || w < 130 || h < 130) {
        g.fillText(!box ? (points.length ? 'No valid XY coordinates in this view.' :
          'No survey marks or flight extents supplied.') : 'Enlarge the map to view coverage.', 12, 30);
        return;
      }
      const left = Math.min(100, w * 0.31), right = w - 22, top = 36, bottom = h - 48;
      const cx = left + (right - left) / 2, cy = top + (bottom - top) / 2;
      const ce = box.minE / 2 + box.maxE / 2, cn = box.minN / 2 + box.maxN / 2;
      const halfE = box.maxE / 2 - box.minE / 2, halfN = box.maxN / 2 - box.minN / 2;
      const minimum = Math.max(0.5, Math.abs(ce) * Number.EPSILON * 16,
        Math.abs(cn) * Number.EPSILON * 16);
      // One world-units-per-pixel factor for BOTH axes; north increases upward.
      const step = Math.max(Math.max(halfE, minimum) / ((right - left) / 2),
        Math.max(halfN, minimum) / ((bottom - top) / 2)) * 1.12;
      const x = e => cx + ((e / 2 - ce / 2) / step) * 2;
      const y = n => cy - ((n / 2 - cn / 2) / step) * 2;
      const decimals = Math.min(6, Math.max(0, 1 - Math.floor(Math.log10(step * (right - left) / 4))));
      const tick = value => {
        if (!finite(value)) return '';
        const label = value.toFixed(decimals);
        return label.length > 13 ? value.toExponential(3) : label;
      };
      g.lineWidth = 1; g.strokeStyle = '#dbe4e9';
      for (let j = 0; j <= 4; j++) {
        const px = left + (right - left) * j / 4, py = top + (bottom - top) * j / 4;
        g.beginPath(); g.moveTo(px, top); g.lineTo(px, bottom);
        g.moveTo(left, py); g.lineTo(right, py); g.stroke();
        g.fillStyle = '#526c7e'; g.textAlign = 'center';
        g.fillText(tick(ce + (px - cx) * step), px, bottom + 17, Math.max(1, (right - left) / 4 - 3));
        g.textAlign = 'right';
        g.fillText(tick(cn + (cy - py) * step), left - 7, py + 4, Math.max(1, left - 28));
      }
      g.save(); g.beginPath(); g.rect(left, top, right - left, bottom - top); g.clip();
      for (const entry of flights) {
        if (!entry || (flight !== 'all' && flightKey(entry.strip) !== flight)) continue;
        const extent = list(entry.extent);
        if (extent.length !== 4 || extent.some(corner =>
          !Array.isArray(corner) || !finite(corner[0]) || !finite(corner[1]))) continue;
        // Coordinate extrema position the label; preserve the footprint's corner order.
        let minE = Infinity, maxN = -Infinity;
        for (const corner of extent) {
          minE = Math.min(minE, corner[0]); maxN = Math.max(maxN, corner[1]);
        }
        const flagged = list(entry.flags).length > 0;
        const ex = x(minE), ey = y(maxN);
        g.fillStyle = flagged ? 'rgba(182,93,64,0.055)' : 'rgba(75,112,134,0.035)';
        g.strokeStyle = flagged ? '#b65d40' : '#9dAFba'; g.lineWidth = flagged ? 2 : 1;
        g.setLineDash(flagged ? [6, 3] : [3, 4]);
        g.beginPath();
        extent.forEach((corner, index) => {
          if (index === 0) g.moveTo(x(corner[0]), y(corner[1]));
          else g.lineTo(x(corner[0]), y(corner[1]));
        });
        g.closePath(); g.fill(); g.stroke();
        g.setLineDash([]); g.fillStyle = flagged ? '#a44830' : '#627e90'; g.textAlign = 'left';
        g.fillText('Flight ' + entry.strip + (flagged ? ' · flagged' : ''), ex + 4, ey + 13,
          Math.max(1, right - ex - 4));
      }
      // Gap segments use the same extent-derived, north-up map transform.
      g.strokeStyle = '#b23b3b'; g.lineWidth = 2; g.setLineDash([6, 4]);
      for (const entry of flights) {
        if (!entry || (flight !== 'all' && flightKey(entry.strip) !== flight)) continue;
        for (const gap of list(entry.long_gaps)) {
          const segment = gap?.segment;
          if (!Array.isArray(segment) || segment.length !== 2) continue;
          const start = segment[0], end = segment[1];
          if (!Array.isArray(start) || !Array.isArray(end) ||
              !finite(start[0]) || !finite(start[1]) || !finite(end[0]) || !finite(end[1])) continue;
          g.beginPath(); g.moveTo(x(start[0]), y(start[1]));
          g.lineTo(x(end[0]), y(end[1])); g.stroke();
        }
      }
      g.setLineDash([]);
      let active = null;
      for (const index of shown) {
        const point = points[index];
        if (!finite(point?.easting) || !finite(point?.northing)) continue;
        const px = x(point.easting), py = y(point.northing), supported = localSupport(point).supported;
        hits.push({index, x: px, y: py});
        if (index === selected) active = {point, x: px, y: py, supported};
        else marker(g, px, py, point, supported, false);
      }
      if (active) marker(g, active.x, active.y, active.point, active.supported, true);
      g.restore();
      g.fillStyle = '#526c7e'; g.textAlign = 'center';
      g.fillText('Easting (' + units + ')', cx, h - 9, Math.max(1, right - left));
      g.save(); g.translate(13, cy); g.rotate(-Math.PI / 2);
      g.fillText('Northing (' + units + ')', 0, 0, Math.max(1, bottom - top)); g.restore();
      g.textAlign = 'left';
      g.fillText('Hollow = unsupported · dashed red = projected gaps', left, 17, Math.max(1, right - left - 35));
      g.strokeStyle = '#193548'; g.lineWidth = 1.5; g.beginPath();
      g.moveTo(right - 7, 28); g.lineTo(right - 7, 13);
      g.moveTo(right - 11, 18); g.lineTo(right - 7, 13); g.lineTo(right - 3, 18); g.stroke();
      g.fillStyle = '#193548'; g.textAlign = 'right'; g.fillText('N', right - 15, 22);
    }

    function scheduleDraw() {
      if (framePending) return;
      framePending = true;
      const request = window.requestAnimationFrame || (callback => window.setTimeout(callback, 0));
      request(() => { framePending = false; draw(); });
    }

    function render() {
      readFilters();
      shown = [];
      // A flight chooses the local-support context. Outside/rejected marks, including
      // marks without any flight record, remain inspectable rather than disappearing.
      for (let index = 0; index < points.length; index++) {
        if (role === 'all' || points[index]?.role === role) shown.push(index);
      }
      renderPoints(); renderDetail(); draw();
    }

    function select(index) {
      if (!Number.isInteger(index) || index < 0 || index >= points.length) return;
      selected = index;
      renderPoints(); renderDetail(); draw();
    }

    pointTable.addEventListener('click', event => {
      const button = event.target.closest?.('button[data-coverage-index]');
      if (button && pointTable.contains(button)) select(Number(button.dataset.coverageIndex));
    });
    canvas.addEventListener('click', event => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const px = (event.clientX - rect.left) * (canvas.clientWidth || rect.width) / rect.width;
      const py = (event.clientY - rect.top) * (canvas.clientHeight || rect.height) / rect.height;
      let best = Infinity, nearest = [];
      for (const hit of hits) {
        const distance = Math.hypot(hit.x - px, hit.y - py);
        if (distance > 16) continue;
        if (distance < best - 0.5) { best = distance; nearest = [hit.index]; }
        else if (Math.abs(distance - best) <= 0.5) nearest.push(hit.index);
      }
      // Repeated clicks cycle coincident marks; all are also reachable in the table.
      if (nearest.length) select(nearest[(nearest.indexOf(selected) + 1) % nearest.length]);
    });
    flightInput.addEventListener('change', render);
    roleInput.addEventListener('change', render);
    if (typeof window.ResizeObserver === 'function') new window.ResizeObserver(scheduleDraw).observe(section);
    window.addEventListener('resize', scheduleDraw);
    window.controlCoverage = {
      select,
      state: () => ({
        total: points.length, selected: selected < 0 ? null : pointName(selected),
        flight, role, shown: shown.length
      })
    };
    render();
  }

  if (document.readyState === 'loading' && !document.getElementById('coverageMap')) {
    document.addEventListener('DOMContentLoaded', init, {once: true});
  } else init();
})();