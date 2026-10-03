/* Person 3 UI runtime. Computation is delegated to Person 2's evaluator. */
(function (global) {
  'use strict';
  const payload = JSON.parse(document.getElementById('playground-data').textContent);
  const ir = payload.ir, V = global.PlaygroundVisuals;
  const byId = id => document.getElementById(id);
  const el = (tag, text, cls) => { const n=document.createElement(tag); if(text != null)n.textContent=String(text); if(cls)n.className=cls; return n; };
  const clone = value => JSON.parse(JSON.stringify(value));
  const defaults = () => Object.fromEntries((ir.controls || []).map(c => [c.id,clone(c.default)]));
  let state = defaults(), desiredState = clone(state), values = {...state,...payload.values}, evaluator = global.PlaygroundEvaluator || global.PaperComputation;
  let selected = 0, affected = new Set(), revision = 0;
  let experienceUI=null, baseline=clone(values), beforeValues=clone(values);
  const experiencePlan=payload.experience?.mode === 'directed' ? payload.experience.plan : null;
  const widgets = new Map();
  const nodes = ir.computation?.nodes || [];
  let dependencies=payload.dependencies;
  if(!dependencies && global.PaperComputation?.deriveDependencies)dependencies=global.PaperComputation.deriveDependencies(ir);
  const visuals = (ir.visuals || []).filter(v => v.type !== 'formula');
  if (!visuals.length) visuals.push({type:'pipeline',title:'Calculation path'});
  const formula = (ir.visuals || []).find(v => v.type === 'formula');
  function text(id,value) { byId(id).textContent=value || ''; }
  text('concept-title',ir.teaching?.title); text('idea',ir.teaching?.idea); text('why',ir.teaching?.why); text('mental-model',ir.teaching?.mental_model);
  // On compact screens, teach through the controls first and keep the context
  // nearby. Move the actual section so visual and screen-reader order agree.
  const compact=global.matchMedia('(max-width: 700px)');
  function placeContext() { (compact.matches ? byId('changes') : byId('overview')).after(byId('context')); }
  placeContext();compact.addEventListener('change',placeContext);
  const reference=[payload.source?.title,payload.source?.section,payload.source?.equation].filter(Boolean).join(' · ');
  text('paper-label',reference);byId('paper-label').hidden=!reference;
  (ir.symbols || []).forEach(s => byId('symbols').append(el('dt',s.symbol),el('dd',`${s.meaning}${s.units ? ` · ${s.units}` : ''}`)));
  if(formula) { byId('formula-strip').hidden=false; text('formula',formula.options?.display); }
  text('limitation-text',ir.limitation?.text);
  (ir.evidence || []).forEach(e => { const li=el('li',e.claim); li.append(el('span',`Evidence: ${(e.blocks || []).join(', ')}`, 'evidence-ref')); byId('evidence').append(li); });
  [...(ir.provenance?.simplifications || []),...(ir.provenance?.toy_examples || [])].forEach(s => byId('simplifications').append(el('li',s)));
  const source=payload.source || {}, sourceText=el('div');
  sourceText.append(el('h3',source.title || source.url || 'Source evidence'),el('p',source.authors || 'Evidence block IDs are provided below.'));
  if(source.section)sourceText.append(el('p',source.section));
  byId('source-card').append(sourceText);
  const sourceBlocks=Array.isArray(source.blocks) ? source.blocks : [], SOURCE_PREVIEW_CHARS=600;
  const evidenceIds=new Set((ir.evidence || []).flatMap(e=>e.blocks || []));
  sourceBlocks.filter(block=>evidenceIds.has(block.id)).forEach(block=>{
    const card=el('article',null,'source-excerpt');
    card.append(el('h4',block.section || 'From the provided excerpt'));
    const meta=[block.section_number != null ? `Section ${block.section_number}` : null,
      block.equation_number != null ? `Eq. ${block.equation_number}` : null,
      block.page != null ? `Page ${block.page}` : null].filter(Boolean).join(' · ');
    if(meta)card.append(el('p',meta,'evidence-ref'));
    // Presentation only: show a short preview and keep the exact extracted
    // text, artifacts included, behind a collapsed disclosure.
    const full=String(block.text || ''), chars=Array.from(full);
    if(chars.length > SOURCE_PREVIEW_CHARS) {
      let cut=chars.slice(0,SOURCE_PREVIEW_CHARS).join('');
      const space=cut.search(/\s\S*$/);
      if(space > SOURCE_PREVIEW_CHARS-120)cut=cut.slice(0,space);
      card.append(el('p',`${cut.trimEnd()} …`,'source-preview'));
      const details=el('details',null,'source-full');
      details.append(el('summary','View full extracted source'),el('p',full));
      card.append(details);
    } else card.append(el('p',full));
    card.append(el('small',`${block.type || 'Excerpt'} · ${block.id}`));
    byId('source-excerpts').append(card);
  });
  if(source.url) { try { const url=new URL(source.url); if(['https:','http:'].includes(url.protocol)) { const a=el('a','Open paper ↗'); a.href=url.href; a.target='_blank'; a.rel='noopener noreferrer'; byId('source-card').append(a); } } catch (_) { /* Invalid URL stays inert. */ } }
  // Walk references only, never execute AST nodes. Params such as end_ref also
  // contribute to the visible dependency path.
  function refs(value,found=new Set()) {
    if(Array.isArray(value))value.forEach(v => refs(v,found));
    else if(value && typeof value === 'object') {
      if(typeof value.ref === 'string')found.add(value.ref);
      for(const [key,v] of Object.entries(value)) {
        if(key.endsWith('_ref') && typeof v === 'string')found.add(v);
        else refs(v,found);
      }
    } return found;
  }
  function dependencyPath(ids) {
    if(dependencies) {
      const result=new Set(ids);ids.forEach(id=>(dependencies[id] || []).forEach(target=>result.add(target)));return result;
    }
    const result=new Set(ids); let changed=true;
    while(changed) { changed=false; nodes.forEach(n => { if(!result.has(n.id) && [...refs([n.inputs,n.params])].some(id => result.has(id))) {result.add(n.id);changed=true;} }); }
    return result;
  }
  function error(message) { const box=byId('runtime-error'); box.hidden=!message; box.textContent=message || ''; }
  function numeric(c,input) {
    const n=input.valueAsNumber;
    if(!Number.isFinite(n) || !input.checkValidity()) { input.setAttribute('aria-invalid','true'); throw new Error(`Enter a valid value for ${c.label}${c.min != null || c.max != null ? ` (${c.min ?? 'no minimum'} to ${c.max ?? 'no maximum'})` : ''}.`); }
    input.removeAttribute('aria-invalid'); return n;
  }
  function numericAttrs(input,c) { for(const attr of ['min','max','step']) if(c[attr] != null)input.setAttribute(attr,c[attr]); if(c.step == null)input.step='any'; }
  let complexControls=0;
  function addControl(c,index) {
    const group=el('div',null,'control'), head=el('div',null,'control-head');
    group.dataset.controlKind=c.type;
    const label=el('label',c.label), id=`control-${index}`, helpId=`help-${index}`; label.htmlFor=id; head.append(label); group.append(head);
    let sync, inputs=[];
    const onChange=(input,read) => input.addEventListener('input',() => { try { const next=read(); change({[c.id]:next},c.label); } catch(e) { error(e.message); } });
    if(['matrix_editor','vector_editor','sequence_editor'].includes(c.type)) {
      const grid=el('div',null,'matrix-editor'), rows=c.type === 'matrix_editor' ? c.default : [c.default];
      grid.setAttribute('role','group'); grid.setAttribute('aria-label',c.label); grid.id=id;
      const matrix=c.type==='matrix_editor';
      grid.style.gridTemplateColumns=`${matrix ? '1rem ' : ''}repeat(${rows[0]?.length || 1},minmax(2.6rem,1fr))`;
      if(matrix) {
        const shape=el('span',`${rows.length} × ${rows[0]?.length || 0}`,'control-shape');head.append(shape);
        grid.append(el('span','', 'matrix-axis'));
      }
      (rows[0] || []).forEach((_,col)=>grid.append(el('span',col+1,'matrix-axis')));
      const cells=[];
      rows.forEach((row,r) => { if(!Array.isArray(row))throw new Error(`Invalid editor shape: ${c.id}`); if(matrix)grid.append(el('span',r+1,'matrix-axis')); row.forEach((v,col) => {
        const input=el('input'); input.type='number'; input.value=v; numericAttrs(input,c); input.setAttribute('aria-label',`${c.label}, ${c.type === 'matrix_editor' ? `row ${r+1}, column ${col+1}` : `entry ${col+1}`}`); input.setAttribute('aria-describedby',helpId);
        cells.push({input,r,col});inputs.push(input);grid.append(input);
        onChange(input,() => { const next=clone(desiredState[c.id]), n=numeric(c,input); if(c.type === 'matrix_editor')next[r][col]=n;else next[col]=n;return next; });
      }); });
      group.append(grid); sync=() => cells.forEach(({input,r,col}) => { input.value=c.type === 'matrix_editor' ? desiredState[c.id][r][col] : desiredState[c.id][col]; input.removeAttribute('aria-invalid'); });
    } else {
      const input=el(c.type === 'select' ? 'select' : 'input'); input.id=id;input.setAttribute('aria-describedby',helpId);inputs=[input];
      if(c.type === 'checkbox') { input.type='checkbox';head.append(input);sync=() => {input.checked=Boolean(desiredState[c.id]);};onChange(input,() => input.checked); }
      else if(c.type === 'select') { (c.options || []).forEach((option,i) => { const o=el('option',typeof option === 'object' ? option.label : option); o.value=i;input.append(o); });group.append(input); const optionValue=o => typeof o === 'object' && o != null ? o.value : o;sync=() => {input.value=c.options.findIndex(o => JSON.stringify(optionValue(o)) === JSON.stringify(desiredState[c.id]));};onChange(input,() => optionValue(c.options[Number(input.value)])); }
      else if(['slider','number'].includes(c.type)) {
        input.type=c.type === 'slider' ? 'range' : 'number';numericAttrs(input,c);group.append(input);
        const output=el('output',null,'control-value');output.htmlFor=id;head.append(output);
        sync=() => {input.value=desiredState[c.id];output.textContent=V.format(desiredState[c.id]);input.removeAttribute('aria-invalid');};onChange(input,() => numeric(c,input));
        if(c.type === 'slider') { const bounds=el('div',null,'range-bounds');bounds.append(el('span',c.min),el('span',c.max));group.append(bounds); }
      } else { group.append(el('p',`Unsupported control: ${c.type}`,'hint'));input.disabled=true;sync=() => {}; }
    }
    const help=el('p',c.help || '', 'control-help'); help.id=helpId;group.append(help);
    let mount=group;
    if(['matrix_editor','vector_editor','sequence_editor'].includes(c.type) && complexControls++ > 0) {
      mount=el('details',null,'control-disclosure');mount.append(el('summary',c.label),group);
      mount.dataset.controlKind=c.type;
      const regular=global.matchMedia('(min-width: 701px)');mount.open=regular.matches;
      regular.addEventListener('change',event=>{mount.open=event.matches;});
    }
    byId('controls').append(mount);
    group.dataset.experienceTarget=c.id;
    sync();widgets.set(c.id,{sync,inputs,group,mount});
  }
  function interactive(enabled) {
    widgets.forEach(w => w.inputs.forEach(input => {input.disabled=!enabled;}));
    document.querySelectorAll('[data-exploration]').forEach(b => {b.disabled=!enabled;});
    byId('reset').disabled=!enabled;
    byId('presentation-status').hidden=enabled || !experienceUI?.active;
  }
  function draw() {
    const spec=visuals[selected]; byId('main-visual').replaceChildren(V.render(spec,values,ir,affected));
    byId('main-visual').dataset.visualId=payload.visual_ids[ir.visuals.indexOf(spec)];
    byId('main-visual').setAttribute('aria-labelledby',`visual-tab-${selected}`);
    text('visual-caption',evaluator?.evaluate ? 'Change an input to observe the result.' : 'Reference values · editing is unavailable in this preview.');
    byId('intermediate-values').replaceChildren();
    const stories=experiencePlan?.calculation_story || [];
    const ordered=[...stories.map(s=>nodes.find(n=>n.id===s.node)),...nodes.filter(n=>n.display && !stories.some(s=>s.node===n.id))];
    ordered.forEach(n => {
      const story=stories.find(s=>s.node===n.id);
      const card=el('div',null,'panel intermediate-card');card.dataset.node=n.id;card.append(el('h3',n.label || n.id));
      card.append(story ? V.render({type:story.presentation==='metric' ? 'number' : story.presentation,value:n.id,title:n.label || n.id},values,ir,affected) : Array.isArray(values[n.id]) ? V.table(values[n.id],n.id) : el('div',V.format(values[n.id]),'big-value'));
      if(story?.annotation)card.append(el('p',story.annotation,'calculation-annotation'));
      byId('intermediate-values').append(card);
    });
    if(stories.length) {
      byId('intermediate-values').classList.add('calculation-sequence');
      const cards=[...byId('intermediate-values').children];
      stories.forEach((story,index)=>{
        const card=cards[index];
        if(experiencePlan.emphasis_nodes?.includes(story.node))card.classList.add('emphasized-node');
        if(affected.has(story.node))card.classList.add('changed-node');
        if(index && dependencyPath([stories[index-1].node]).has(story.node)) {
          const arrow=el('span','→','calculation-arrow');arrow.setAttribute('aria-label',`${nodes.find(n=>n.id===stories[index-1].node)?.label || stories[index-1].node} influences ${nodes.find(n=>n.id===story.node)?.label || story.node}`);
          card.prepend(arrow);
        }
        if(affected.has(story.node) && JSON.stringify(beforeValues[story.node])!==JSON.stringify(values[story.node]))card.append(el('p',deltaDescription(beforeValues[story.node],values[story.node]),'value-change'));
      });
    }
    byId('dependency-graph').replaceChildren(V.pipeline(ir,values,null,affected));
    experienceUI?.update({values,baseline,before:beforeValues,affected});
  }
  function deltaDescription(before,after) {
    if(typeof before==='number' && typeof after==='number')return `${V.format(before)} → ${V.format(after)} (Δ ${V.format(after-before)})`;
    if(Array.isArray(before) && Array.isArray(after)) {
      const a=before.flat(Infinity),b=after.flat(Infinity);
      if(a.length!==b.length)return `Size changed: ${a.length} → ${b.length} entries`;
      const deltas=b.map((v,i)=>typeof v==='number' && typeof a[i]==='number' ? Math.abs(v-a[i]) : null).filter(v=>v != null);
      const count=b.filter((v,i)=>JSON.stringify(v)!==JSON.stringify(a[i])).length;
      return `${count} of ${b.length} entries changed${deltas.length ? ` · largest |Δ| ${V.format(Math.max(...deltas))}` : ''}`;
    }
    return `${V.format(before)} → ${V.format(after)}`;
  }
  function drawChanges(previous,next) {
    byId('change-path').replaceChildren();
    const ids=[...(ir.controls || []).map(c=>c.id),...nodes.filter(n=>n.display).map(n=>n.id)];
    const changedIds=ids.filter(id=>affected.has(id) && JSON.stringify(previous[id])!==JSON.stringify(next[id]));
    changedIds.forEach((id,index)=>{
      const label=[...(ir.controls || []),...nodes].find(n=>n.id===id)?.label || id;
      const row=el('div',null,'delta-step');row.dataset.node=id;
      const predecessor=changedIds.slice(0,index).reverse().find(source=>dependencyPath([source]).has(id));
      if(predecessor) {
        const from=[...(ir.controls || []),...nodes].find(n=>n.id===predecessor)?.label || predecessor;
        row.append(el('small',`${from} → ${label}`,'causal-link'));
      }
      row.append(el('strong',label),el('span',deltaDescription(previous[id],next[id])));
      const meaning=experiencePlan?.calculation_story.find(s=>s.node===id)?.meaning;
      if(meaning)row.append(el('small',meaning));byId('change-path').append(row);
    });
    byId('before-after').hidden=false;byId('before-after-values').replaceChildren();
    for(const [label,snapshot] of [['Before your change',previous],['After your change',next]]) {
      const column=el('div');column.append(el('h4',label));
      (ir.computation?.outputs || []).forEach(id=>{
        column.append(Array.isArray(snapshot[id]) ? V.table(snapshot[id],id) : el('p',`${id}: ${V.format(snapshot[id])}`));
      });byId('before-after-values').append(column);
    }
  }
  function compare(previous,next) {
    return (ir.computation?.outputs || []).filter(id => JSON.stringify(previous[id]) !== JSON.stringify(next[id])).map(id => {
      const label=nodes.find(n => n.id === id)?.label || id;
      return Array.isArray(next[id]) ? `${label} updated` : `${label}: ${V.format(previous[id])} → ${V.format(next[id])}`;
    }).join('; ') || 'The displayed outputs stayed the same.';
  }
  async function change(patch,label,reset = false) {
    if(!evaluator?.evaluate)return;
    const ticket=++revision, previousValues=clone(values), previousState=clone(state);
    const proposed=reset ? defaults() : {...desiredState,...clone(patch)};
    desiredState=clone(proposed);widgets.forEach(w => w.sync());
    error('');
    try {
      const result=await evaluator.evaluate(ir,clone(proposed));
      if(ticket !== revision)return;
      if(!result || typeof result !== 'object' || Array.isArray(result))throw new Error('The computation runtime must return a values object.');
      state=proposed;values={...state,...result};beforeValues=previousValues;
      const changedControls=Object.keys(state).filter(id=>JSON.stringify(previousState[id])!==JSON.stringify(state[id]));
      affected=new Set([...dependencyPath(changedControls)].filter(id=>JSON.stringify(previousValues[id])!==JSON.stringify(values[id])));
      if(label==='Initial values')baseline=clone(values);
      widgets.forEach(w => w.sync());draw();
      text('change-summary',label==='Initial values' ? 'Change an input to follow its effect through the calculation. Your previous and current results will appear here.' : `${label}. ${compare(previousValues,values)}`);
      if(label!=='Initial values')drawChanges(previousValues,values);
    } catch(e) {
      if(ticket !== revision)return;
      state=previousState;desiredState=clone(state);widgets.forEach(w => w.sync());
      error(`${e.message || 'The calculation could not be completed.'} Previous values are preserved. Adjust the controls and try again.`);
    }
  }
  function activateTab(i,focus=false) {
    selected=i;document.querySelectorAll('[role=tab]').forEach((b,j) => {b.setAttribute('aria-selected',String(i===j));b.tabIndex=i===j ? 0 : -1;if(focus && i===j)b.focus();});draw();
  }
  visuals.forEach((v,i) => {
    const button=el('button',v.title || v.type,'tab');button.id=`visual-tab-${i}`;button.type='button';button.setAttribute('role','tab');button.setAttribute('aria-controls','main-visual');button.setAttribute('aria-selected',String(i===0));button.tabIndex=i===0 ? 0 : -1;
    button.addEventListener('click',() => activateTab(i));button.addEventListener('keydown',e => {let next;if(e.key === 'ArrowRight')next=(i+1)%visuals.length;if(e.key === 'ArrowLeft')next=(i+visuals.length-1)%visuals.length;if(e.key === 'Home')next=0;if(e.key === 'End')next=visuals.length-1;if(next != null){e.preventDefault();activateTab(next,true);} });byId('visual-tabs').append(button);
  });
  (ir.explorations || []).forEach((exploration,i) => {
    const card=el('article',null,'panel exploration-card'), head=el('div',null,'exploration-header');
    card.dataset.experienceTarget=`exploration_${i}`;
    head.append(el('span',i+1,'exploration-number'),el('h3',exploration.title));card.append(head);
    const explanation=el('dl',null,'exploration-description');
    for(const [label,description] of [['Change',exploration.change?.instructions],['Observe',exploration.observe],['Why',exploration.why]])explanation.append(el('dt',label),el('dd',description));
    card.append(explanation);
    const button=el('button','Try this setup ↗','quiet-button');button.dataset.exploration=i;
    button.addEventListener('click',() => {
      // Each exploration starts from defaults; its expectation refers to that
      // baseline, rather than arbitrary edits left by a previous exploration.
      const setup={...defaults(),...clone(exploration.change?.suggested_values || {})};
      change(setup,`Applied: ${exploration.title}`);
    }); card.append(button);byId('exploration-cards').append(card);
  });
  (ir.controls || []).forEach(addControl);
  experienceUI=global.PlaygroundExperience.create(payload,ir,V,{widgets,getValues:()=>values,dependencyPath,
    calculationSteps:()=>byId('intermediate-values').cloneNode(true)});
  byId('reset').addEventListener('click',() => change(defaults(),'Reset to the original values',true));
  function setEvaluator(next) { evaluator=next;interactive(Boolean(evaluator?.evaluate));if(evaluator?.evaluate) return change(defaults(),'Initial values',true); }
  global.PlaygroundUI={setEvaluator,getState:() => clone(state),getValues:() => clone(values),dependencyPath};
  draw();interactive(Boolean(evaluator?.evaluate));
  if(evaluator?.evaluate)change(defaults(),'Initial values',true);
  else { text('change-summary','Reference setup shown. Connect evaluated results to explore changes.'); }
})(globalThis);
