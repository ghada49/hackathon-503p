/* Person 3: data-only DOM/SVG renderers. No expression evaluation. */
(function (global) {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = String(text); if (cls) n.className = cls; return n; };
  const svgEl = (tag, attrs = {}, text) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v)); if (text != null) n.textContent = String(text); return n; };
  const format = v => typeof v === 'number' ? (Number.isFinite(v) ? Number(v.toFixed(3)).toString() : 'Unavailable') : String(v ?? 'Not evaluated');
  function table(value, title, heatmap = false, domain = null) {
    if (!Array.isArray(value) || !value.length) return el('p', 'No evaluated data yet.', 'hint');
    const rows = Array.isArray(value[0]) ? value : [value];
    if (rows.some(row => !Array.isArray(row) || row.length !== rows[0].length)) throw new Error('Expected a rectangular matrix');
    const wrap = el('div', null, 'heatmap-wrap');
    wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label',title || 'Scrollable values');
    const t = el('table', null, `data-table${heatmap ? ' heatmap' : ''}`);
    t.append(el('caption', title));
    const head = el('tr'); head.append(el('th', ''));
    rows[0].forEach((_, i) => { const th = el('th', i + 1); th.scope = 'col'; head.append(th); });
    const thead = el('thead'); thead.append(head); t.append(thead);
    const nums = rows.flat().filter(v => typeof v === 'number' && Number.isFinite(v));
    const shared=Array.isArray(domain) && domain.length===2 && domain.every(Number.isFinite) && domain[1]>=domain[0];
    const lo = shared ? domain[0] : nums.length ? Math.min(0, ...nums) : 0, hi = shared ? domain[1] : nums.length ? Math.max(...nums) : 1;
    const body = el('tbody');
    rows.forEach((row, r) => {
      const tr = el('tr'), th = el('th', r + 1); th.scope = 'row'; tr.append(th);
      row.forEach(v => {
        const td = el('td', format(v));
        if (heatmap && typeof v === 'number' && Number.isFinite(v)) {
          const ratio = hi === lo ? 0 : Math.max(0,Math.min(1,(v - lo) / (hi - lo)));
          const rgb = [237,243,231].map((start, i) => Math.round(start + ([36,85,72][i] - start) * ratio));
          td.style.backgroundColor = `rgb(${rgb.join(',')})`;
          // Compute actual WCAG relative luminance instead of estimating contrast.
          const lin = rgb.map(c => c / 255 <= .04045 ? c / 255 / 12.92 : ((c / 255 + .055) / 1.055) ** 2.4);
          const l = lin[0] * .2126 + lin[1] * .7152 + lin[2] * .0722;
          td.style.color = (1.05 / (l + .05) >= (l + .05) / .05) ? '#ffffff' : '#000000';
        }
        tr.append(td);
      }); body.append(tr);
    }); t.append(body); wrap.append(t);
    if (heatmap) { const key = el('div', null, 'heatmap-key'); key.append(el('span', format(lo)), el('i'), el('span', format(hi))); wrap.append(key); }
    return wrap;
  }
  function pipeline(ir, values, bindings, affected = new Set()) {
    const wrap = el('div', null, 'pipeline');
    const entries=[...(ir.controls || []),...(ir.computation?.nodes || [])];
    const labels=new Map(entries.map(n=>[n.id,n.label || n.id]));
    if (!bindings || !Object.keys(bindings).length) {
      wrap.style.display = 'block';
      const collect = (v, set = new Set()) => {
        if (Array.isArray(v)) v.forEach(x => collect(x,set));
        else if (v && typeof v === 'object') {
          if (typeof v.ref === 'string') set.add(v.ref);
          Object.entries(v).forEach(([key,x]) => { if (key.endsWith('_ref') && typeof x === 'string') set.add(x); else collect(x,set); });
        } return set;
      };
      (ir.computation?.nodes || []).forEach(n => {
        const row = el('div',null,'pipeline');
        const sources = [...collect([n.inputs,n.params])].filter(id=>labels.has(id));
        if (sources.length) { row.append(el('span',sources.map(id=>labels.get(id)).join(', '),'hint'),el('span','→','pipeline-arrow')); }
        const box = el('div',null,`pipeline-node${affected.has(n.id) ? ' affected' : ''}`);box.dataset.node=n.id;
        box.append(el('strong',n.label || n.id),el('div',Array.isArray(values[n.id]) ? 'See intermediate values' : format(values[n.id])));
        if (affected.has(n.id)) box.append(el('small','Affected by your change'));
        row.append(box);wrap.append(row);
      });
      return wrap;
    }
    const ids = bindings && Object.keys(bindings).length ? Object.values(bindings) : (ir.computation?.nodes || []).map(n => n.id);
    const downstream=global.PaperComputation?.deriveDependencies(ir) || {};
    ids.forEach((id, i) => {
      if (i && downstream[ids[i-1]]?.includes(id)) { const arrow = el('span', '→', 'pipeline-arrow'); arrow.setAttribute('aria-hidden', 'true'); wrap.append(arrow); }
      const label = [...(ir.controls || []), ...(ir.computation?.nodes || [])].find(n => n.id === id)?.label || id;
      const box = el('div', null, `pipeline-node${affected.has(id) ? ' affected' : ''}`); box.dataset.node = id;
      box.append(el('strong', label), el('div', Array.isArray(values[id]) ? 'See intermediate values' : format(values[id])));
      if (affected.has(id)) box.append(el('small', 'Affected by your change'));
      wrap.append(box);
    }); return wrap;
  }
  function chart(kind, data, options, title) {
    if (!Array.isArray(data) || !data.length) throw new Error('Chart needs a nonempty numeric array');
    let points;
    if (kind === 'scatter') {
      if (!data.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) throw new Error('Scatter needs [x, y] pairs');
      points = data;
    } else {
      if (!data.every(Number.isFinite)) throw new Error('Chart needs finite numeric values');
      points = data.map((v, i) => [i, v]);
    }
    const domain = d => Array.isArray(d) && d.length===2 && d.every(Number.isFinite) && d[0]<d[1];
    const xlo = domain(options.x_domain) ? options.x_domain[0] : Math.min(...points.map(p => p[0]));
    const xhi = domain(options.x_domain) ? options.x_domain[1] : Math.max(xlo + 1, ...points.map(p => p[0]));
    const ylo = domain(options.domain) ? options.domain[0] : Math.min(0, ...points.map(p => p[1]));
    const yhi = domain(options.domain) ? options.domain[1] : Math.max(ylo + .001, ...points.map(p => p[1]));
    const x = v => 55 + (v - xlo) / (xhi - xlo) * 360, y = v => 210 - (v - ylo) / (yhi - ylo) * 165;
    const wrap = el('div'); wrap.style.width = '100%';
    const s = svgEl('svg', {viewBox:'0 0 470 255', class:'chart', role:'img'});
    s.append(svgEl('title', {}, title), svgEl('desc', {}, `X: ${options.x_label || 'item'}. Y: ${options.y_label || 'value'}. Range ${format(ylo)} to ${format(yhi)}. ${points.map((p,i) => `${options.labels?.[i] ?? p[0] + 1}: ${format(p[1])}`).join('; ')}`));
    [ylo, (ylo+yhi)/2, yhi].forEach(v => { s.append(svgEl('line', {x1:45,y1:y(v),x2:450,y2:y(v),stroke:'currentColor',opacity:.15}), svgEl('text',{x:5,y:y(v)+4},format(v))); });
    if (kind === 'line_chart') s.append(svgEl('polyline', {points:points.map(p => `${x(p[0])},${y(p[1])}`).join(' '), fill:'none', stroke:'currentColor','stroke-width':2}));
    points.forEach((p,i) => {
      const px = kind === 'bar_chart' ? 65 + (i + .5) * 360 / points.length : x(p[0]);
      if (kind === 'bar_chart') s.append(svgEl('rect',{x:px - 90/points.length,y:Math.min(y(p[1]),y(0)),width:180/points.length,height:Math.abs(y(p[1])-y(0)),rx:3,fill:'currentColor'}));
      else s.append(svgEl('circle',{cx:px,cy:y(p[1]),r:4,fill:'currentColor'}));
      if (options.show_values !== false) s.append(svgEl('text',{x:px,y:y(p[1])-9,'text-anchor':'middle'},format(p[1])));
      s.append(svgEl('text',{x:px,y:235,'text-anchor':'middle'},options.labels?.[i] ?? (kind === 'scatter' ? format(p[0]) : i+1)));
    }); wrap.append(s);
    const details = el('details'); details.append(el('summary', 'View chart values'), table(points, title)); wrap.append(details); return wrap;
  }
  function scene(spec, values) {
    const options = spec.options || {}, items = options.elements;
    if(options.objects) return semanticScene(spec,values);
    if (!Array.isArray(items)) throw new Error('Scene elements unavailable');
    const s = svgEl('svg',{viewBox:'0 0 500 300',class:'chart',role:'img'}); s.append(svgEl('title',{},spec.title || 'Mechanism scene'));
    const allowed = {line:['x1','y1','x2','y2'],arrow:['x1','y1','x2','y2'],circle:['cx','cy','r'],rect:['x','y','width','height','rx'],point:['cx','cy','r'],polyline:['points'],text:['x','y'],axis:['x1','y1','x2','y2'],group:[]};
    function add(item, parent, depth = 0) {
      if (depth > 10 || !Object.hasOwn(allowed,item.type)) throw new Error('Unsupported scene element');
      const attrs = {stroke:'currentColor',fill:item.type === 'text' ? 'currentColor' : 'none'};
      for (const key of allowed[item.type]) {
        let v = item[key];
        if (v && typeof v === 'object' && typeof v.ref === 'string') v = values[v.ref];
        if (key === 'points') {
          if (!Array.isArray(v) || !v.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) throw new Error('Invalid polyline');
          attrs[key] = v.map(p => p.join(',')).join(' ');
        } else if (v != null) { if (!Number.isFinite(v)) throw new Error('Invalid scene coordinate'); attrs[key] = v; }
      }
      const tags = {point:'circle',axis:'line',group:'g',arrow:'line'};
      const node = svgEl(tags[item.type] || item.type, attrs, item.type === 'text' ? item.text || '' : undefined); parent.append(node);
      if (item.type === 'arrow') {
        const a = Math.atan2(attrs.y2-attrs.y1,attrs.x2-attrs.x1);
        node.parentNode.append(svgEl('polyline',{points:`${attrs.x2-8*Math.cos(a-.5)},${attrs.y2-8*Math.sin(a-.5)} ${attrs.x2},${attrs.y2} ${attrs.x2-8*Math.cos(a+.5)},${attrs.y2-8*Math.sin(a+.5)}`,stroke:'currentColor',fill:'none'}));
      }
      if (item.type === 'group') (item.elements || []).forEach(child => add(child,node,depth+1));
    }
    items.forEach(item => add(item,s)); return s;
  }
  function semanticScene(spec,values) {
    const options=spec.options || {}, objects=options.objects, links=options.links || [];
    if(!['horizontal_flow','vertical_flow','radial','grid'].includes(options.layout) || !Array.isArray(objects) || !objects.length || objects.length>24 || !Array.isArray(links) || links.length>48)throw new Error('Invalid semantic scene');
    const ids=new Set();objects.forEach(o=>{if(typeof o.id!=='string' || ids.has(o.id) || !['circle','process','rect','point'].includes(o.shape))throw new Error('Invalid semantic object');ids.add(o.id);});
    const s=svgEl('svg',{viewBox:'0 0 600 360',class:'chart',role:'img'});
    s.append(svgEl('title',{},spec.title || 'Mechanism scene'),svgEl('desc',{},objects.map(o=>o.label || o.id).join(' → ')));
    const positions=new Map(objects.map((o,i)=>{
      let x,y;
      if(options.layout==='horizontal_flow'){x=60+(i+.5)*480/objects.length;y=170;}
      if(options.layout==='vertical_flow'){x=300;y=30+(i+.5)*300/objects.length;}
      if(options.layout==='radial'){x=300+190*Math.cos(i*2*Math.PI/objects.length);y=175+115*Math.sin(i*2*Math.PI/objects.length);}
      if(options.layout==='grid'){const cols=Math.ceil(Math.sqrt(objects.length));x=60+(i%cols+.5)*480/cols;y=30+(Math.floor(i/cols)+.5)*280/Math.ceil(objects.length/cols);}
      return [o.id,{x,y}];
    }));
    links.forEach(link=>{
      const a=positions.get(link.from),b=positions.get(link.to);if(!a || !b)throw new Error('Unknown semantic link');
      const angle=Math.atan2(b.y-a.y,b.x-a.x), end={x:b.x-30*Math.cos(angle),y:b.y-30*Math.sin(angle)};
      s.append(svgEl('line',{x1:a.x,y1:a.y,x2:end.x,y2:end.y,stroke:'currentColor',opacity:.5}),svgEl('polyline',{points:`${end.x-8*Math.cos(angle-.5)},${end.y-8*Math.sin(angle-.5)} ${end.x},${end.y} ${end.x-8*Math.cos(angle+.5)},${end.y-8*Math.sin(angle+.5)}`,stroke:'currentColor',fill:'none'}));
    });
    objects.forEach(o=>{
      const p=positions.get(o.id),g=svgEl('g');
      const shape=['circle','point'].includes(o.shape) ? svgEl('circle',{cx:p.x,cy:p.y,r:o.shape==='point' ? 8 : 25,fill:'currentColor',opacity:.15}) : svgEl('rect',{x:p.x-36,y:p.y-22,width:72,height:44,rx:8,fill:'currentColor',opacity:.15});
      g.append(shape,svgEl('text',{x:p.x,y:p.y+42,'text-anchor':'middle'},o.label || o.id));
      if(o.value)g.append(svgEl('text',{x:p.x,y:p.y+4,'text-anchor':'middle'},format(values[o.value])));
      s.append(g);
    });return s;
  }
  function nodesEdges(spec, values) {
    const {nodes, edges} = spec.options || {};
    if (!Array.isArray(nodes) || !Array.isArray(edges)) throw new Error('Graph nodes or edges unavailable');
    const s = svgEl('svg',{viewBox:'0 0 500 300',class:'chart',role:'img'}); s.append(svgEl('title',{},spec.title || 'Nodes and edges'));
    const positions = new Map(nodes.map((n,i) => [n.id,{x:250+100*Math.cos(i*2*Math.PI/nodes.length),y:145+95*Math.sin(i*2*Math.PI/nodes.length)}]));
    edges.forEach(e => { const a=positions.get(e.source), b=positions.get(e.target); if (!a || !b) throw new Error('Unknown graph endpoint'); s.append(svgEl('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'currentColor',opacity:.45})); });
    nodes.forEach(n => { const p=positions.get(n.id); s.append(svgEl('circle',{cx:p.x,cy:p.y,r:18,fill:'currentColor',opacity:.2}),svgEl('text',{x:p.x,y:p.y+32,'text-anchor':'middle'},n.label || n.id)); }); return s;
  }
  function render(spec, values, ir, affected = new Set()) {
    const v = values[spec.value], options = spec.options || {};
    try {
      switch (spec.type) {
        case 'heatmap': case 'matrix': case 'table': case 'vector': return table(v,spec.title || spec.value,spec.type === 'heatmap',options.domain);
        case 'number': return el('div', `${format(v)}${options.suffix || ''}`, 'big-value');
        case 'formula': return el('p',options.display || '', 'formula');
        case 'pipeline': return pipeline(ir,values,spec.bindings,affected);
        case 'bar_chart': case 'line_chart': case 'scatter': return chart(spec.type,v,options,spec.title || spec.value);
        case 'scene': return scene(spec,values);
        case 'nodes_edges': return nodesEdges(spec,values);
        default: throw new Error('Unsupported visualization');
      }
    } catch (_) {
      // Recover through compatible trusted charts before the generic diagram.
      try {
        if(typeof v==='number' && Number.isFinite(v))return el('div',format(v),'big-value');
        if(Array.isArray(v) && v.length && v.every(Number.isFinite))return chart('bar_chart',v,{},spec.title || spec.value);
        if(Array.isArray(v) && v.length && v.every(row=>Array.isArray(row) && row.length===v[0].length && row.every(Number.isFinite)))return table(v,spec.title || spec.value,true);
      } catch (_) { /* Retain the final meaningful diagram fallback. */ }
      const fallback = el('div'); fallback.append(el('p','Showing the calculation path for this visual.', 'hint'),pipeline(ir,values,null,affected));
      if (Array.isArray(v)) {try {fallback.append(table(v,spec.title || spec.value));}catch(_){fallback.append(el('p',JSON.stringify(v)));}}
      else if (v != null) fallback.append(el('p',format(v)));
      return fallback;
    }
  }
  global.PlaygroundVisuals = {render,table,pipeline,format};
})(globalThis);
