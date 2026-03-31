// Shared UI utilities used by dashboard modules.
(function () {
  function renderSVGSparkline(svgElem, data) {
    const width = 400;
    const height = 48;
    if (!svgElem) return;
    svgElem.innerHTML = '';
    if (!data || data.length < 1) return;
    const allSame = data.every(v => v === data[0]);
    if (data.length === 1 || allSame) {
      const y = height / 2;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', `M0,${y} L${width},${y}`);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', '#8cf04a');
      path.setAttribute('stroke-width', '2');
      svgElem.appendChild(path);
      return;
    }
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const step = width / (data.length - 1);
    let d = '';
    data.forEach((val, i) => {
      const x = i * step;
      const y = height - ((val - min) / range) * (height - 6) - 3;
      d += (i === 0 ? 'M' : 'L') + x.toFixed(2) + ',' + y.toFixed(2) + ' ';
    });

    const fillD = d + `L ${width},${height} L 0,${height} Z`;
    const fill = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    fill.setAttribute('d', fillD);
    fill.setAttribute('fill', 'rgba(140,240,74,0.15)');
    svgElem.appendChild(fill);

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', '#8cf04a');
    path.setAttribute('stroke-width', '2');
    path.setAttribute('stroke-linejoin', 'round');
    svgElem.appendChild(path);
  }

  window.renderSVGSparkline = renderSVGSparkline;
})();
