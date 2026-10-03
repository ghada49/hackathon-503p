/* Person 3: compile normalized presentation data into trusted components. */
(function (global) {
  'use strict';
  const el = (tag,text,cls) => {const n=document.createElement(tag);if(text != null)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const byId = id => document.getElementById(id);
  const condition = (rule,values) => {
    if(!rule)return true;
    const v=values[rule.value];if(typeof v !== 'number' || !Number.isFinite(v))return false;
    if(rule.op === 'less_than')return v < rule.threshold;
    if(rule.op === 'greater_than')return v > rule.threshold;
    return rule.op === 'equal' && v === rule.threshold;
  };
  function create(payload,ir,V,context) {
    const compiled=payload.experience;
    if(compiled?.mode !== 'directed')return {update:()=>{},active:false};
    const plan=compiled.plan, tasks=[],controls=context.widgets;
    const registry=new Map();
    (ir.visuals || []).forEach((v,i)=>{let key=compiled.contract==='shared' ? payload.visual_ids[i] : v.id || v.value || `${v.type}_${i}`;if(registry.has(key))key=`${key}_${i}`;registry.set(key,v);});
    const componentIds={teaching:'overview',idea:'idea',why:'why',mental_model:'mental-model',symbols:'symbols',
      controls:'controls',main_visual:'main-visual',equation:'formula-strip',intermediates:'intermediates',
      what_changed:'changes',explorations:'explorations',limitation:'limitations',source_grounding:'source'};
    let guideIndex=-1;
    const targets=()=>[...document.querySelectorAll('[data-experience-target], [data-node]')];
    const clearHighlight=()=>document.querySelectorAll('.guide-target, .guided-dependency').forEach(n=>n.classList.remove('guide-target','guided-dependency'));
    function targetFor(id) {
      const control=controls.get(id)?.group;
      if(control)return control;
      if(id==='controls')return byId('experience-stage').querySelector('.experience-controls') || byId('controls');
      if(id==='main_visual')return byId('experience-stage').querySelector('.primary-visual, .experience-visual') || byId('main-visual');
      if(id==='equation') {
        const mounted=byId('experience-stage').querySelector('.formula');
        if(mounted)return mounted;
        if(byId('formula-strip').hidden)return byId('playground');
      }
      if(componentIds[id])return byId(componentIds[id]);
      const node=targets().find(n=>n.dataset.experienceTarget===id || n.dataset.node===id);
      if(node)return node;
      const visual=[...registry.entries()].find(([key,spec])=>key===id || spec.value===id);
      if(visual) {
        const host=byId('guide-visual');host.hidden=false;
        const current=context.getValues();host.replaceChildren(V.render(visual[1],current,ir));return host;
      }
      return null;
    }
    function guideHighlight(scroll) {
      clearHighlight();byId('guide-visual').hidden=true;if(guideIndex<0)return;
      const target=targetFor(plan.guided_mode[guideIndex].target);
      if(!target)return;
      target.classList.add('guide-target');
      const step=plan.guided_mode[guideIndex];
      if(step.highlight_dependency_path) {
        const id=registry.get(step.target)?.value || step.target;
        const path=context.dependencyPath([id]);
        targets().filter(n=>path.has(n.dataset.node || n.dataset.experienceTarget)).forEach(n=>n.classList.add('guided-dependency'));
      }
      if(scroll) {
        const disclosure=target.closest('details');if(disclosure)disclosure.open=true;
        target.tabIndex=-1;target.focus({preventScroll:true});
        target.scrollIntoView({block:'center',behavior:global.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
      }
    }
    function showGuide(index) {
      guideIndex=index;byId('guided-walkthrough').hidden=false;
      document.body.classList.add('guide-active');
      byId('guide-start').hidden=true;
      byId('guide-progress').textContent=`Step ${index+1} of ${plan.guided_mode.length}`;
      byId('guide-message').textContent=plan.guided_mode[index].instruction;
      byId('guide-back').disabled=index===0;
      byId('guide-next').textContent=index===plan.guided_mode.length-1 ? 'Finish guide' : 'Next →';
      guideHighlight(true);
    }
    function endGuide() {
      guideIndex=-1;clearHighlight();document.body.classList.remove('guide-active');byId('guided-walkthrough').hidden=true;byId('guide-start').hidden=false;byId('guide-start').focus();
    }
    function visualTask(spec,host,target) {
      host.dataset.experienceTarget=target || spec.value || '';
      const index=ir.visuals.indexOf(spec);
      if(index>=0)host.dataset.visualId=payload.visual_ids[index];
      tasks.push(({values,affected})=>host.replaceChildren(V.render(spec,values,ir,affected)));
    }
    function build(node) {
      if(['split','stack','grid','visual_first','equation_first','pipeline','focus'].includes(node.type)) {
        const host=el('div',null,`experience-layout layout-${node.type}`);
        if(node.type==='split')host.dataset.ratio=node.ratio;
        if(node.type==='grid')host.dataset.columns=node.columns;
        node.children.forEach(child=>host.append(build(child)));return host;
      }
      const card=el('div',null,'panel experience-component');
      if(node.title)card.append(el('h3',node.title));
      if(node.type==='control_group') {
        if(!node.title)card.append(el('h3','Try it','eyebrow'));
        const group=el('div',null,'experience-controls');
        node.controls.forEach(id=>{const widget=controls.get(id);if(!widget)throw new Error('Control missing');group.append(widget.mount);});card.append(group);
      } else if(node.type==='callout') {
        card.classList.add('experience-callout');card.append(el('p',node.text));tasks.push(({values})=>{card.hidden=!condition(node.when,values);});
      } else if(node.type==='symbol_legend') {
        const list=el('dl');(ir.symbols || []).forEach(s=>list.append(el('dt',s.symbol),el('dd',s.meaning)));card.append(list);
      } else if(node.type==='calculation_steps') {
        const host=el('div');card.append(host);
        tasks.push(({values,affected})=>{const copy=context.calculationSteps();copy.removeAttribute('id');host.replaceChildren(copy,V.pipeline(ir,values,null,affected));});
      } else if(node.type==='comparison') {
        const spec=registry.get(node.visual);if(!spec)throw new Error('Visual missing');
        if(!node.title && spec.title)card.append(el('h3',spec.title));
        const grid=el('div',null,'before-after-grid'), before=el('div'),after=el('div'),a=el('div'),b=el('div');
        before.append(el('h3','Original setup'),a);after.append(el('h3','Current setup'),b);grid.append(before,after);card.append(grid);
        card.dataset.experienceTarget=node.visual;
        tasks.push(({values,baseline,affected})=>{
          let shared=spec;
          if(['bar_chart','line_chart','scatter'].includes(spec.type)) {
            const points=[...(baseline[spec.value] || []),...(values[spec.value] || [])];
            const ys=(spec.type==='scatter' ? points.map(p=>p[1]) : points).filter(Number.isFinite);
            if(ys.length) {
              const lo=Math.min(0,...ys),hi=Math.max(lo+.001,...ys),options={...spec.options,domain:[lo,hi]};
              if(spec.type==='scatter'){const xs=points.map(p=>p[0]).filter(Number.isFinite);if(xs.length)options.x_domain=[Math.min(...xs),Math.max(Math.min(...xs)+1,...xs)];}
              shared={...spec,options};
            }
          }
          if(spec.type==='heatmap') {
            const nums=[baseline[spec.value],values[spec.value]].flat(Infinity).filter(Number.isFinite);
            if(nums.length)shared={...spec,options:{...spec.options,domain:[Math.min(0,...nums),Math.max(...nums)]}};
          }
          a.replaceChildren(V.render(shared,baseline,ir));b.replaceChildren(V.render(shared,values,ir,affected));
        });
      } else {
        const host=el('div',null,'experience-visual');card.append(host);
        let spec;
        if(node.type==='dependency_graph')spec={type:'pipeline',title:node.title || 'Dependency path'};
        else if(node.visual)spec=registry.get(node.visual);
        else spec={type:node.type==='metric' ? 'number' : node.type,value:node.value,title:node.title || node.value};
        if(!spec)throw new Error('Visual missing');
        if(!node.title && spec.title)card.insertBefore(el('h3',spec.title),host);
        visualTask(spec,host,node.visual || node.value);
      }
      return card;
    }
    function fallback() {
      clearHighlight();document.body.classList.remove('guide-active');controls.forEach(w=>byId('controls').append(w.mount));
      byId('canonical-stage').hidden=false;
      for(const id of ['experience-stage','experience-summary','experience-annotations','guided-walkthrough','guide-start']) {byId(id).hidden=true;}
      byId('experience-stage').replaceChildren();
      byId('formula-strip').hidden=!(ir.visuals || []).some(v=>v.type==='formula');
      return {update:()=>{},active:false};
    }
    try {
      byId('experience-stage').append(build(plan.tree));byId('experience-stage').hidden=false;
      byId('experience-stage').className=`experience-stage density-${plan.density}`;
      byId('canonical-stage').hidden=true;
      const hasFormula=node=>node.type==='formula' || (node.children || []).some(hasFormula);
      if(hasFormula(plan.tree))byId('formula-strip').hidden=true;
      if(plan.hero) {
        const card=el('div',null,`panel experience-summary emphasis-${plan.hero.emphasis}`),host=el('div');
        card.append(el('p',registry.get(plan.hero.visual).title || 'The idea in view','eyebrow'),host);
        byId('experience-summary').append(card);byId('experience-summary').hidden=false;visualTask(registry.get(plan.hero.visual),host,plan.hero.visual);
      }
      plan.annotations.forEach(note=>{
        const card=el('aside',null,`experience-callout panel annotation-${note.kind}`);
        card.append(el('span',`${note.kind} · ${note.target}`,'eyebrow'),el('p',note.text));
        byId('experience-annotations').append(card);
        tasks.push(({values})=>{card.hidden=!condition(note.when,values);});
      });
      byId('experience-annotations').hidden=!plan.annotations.length;
      if(plan.guided_mode.length) {
        byId('guide-start').hidden=false;
        byId('guide-start').addEventListener('click',()=>showGuide(0));
        byId('guide-back').addEventListener('click',()=>showGuide(Math.max(0,guideIndex-1)));
        byId('guide-next').addEventListener('click',()=>guideIndex===plan.guided_mode.length-1 ? endGuide() : showGuide(guideIndex+1));
        byId('guide-end').addEventListener('click',endGuide);
        document.addEventListener('keydown',e=>{if(e.key==='Escape' && guideIndex>=0)endGuide();});
      }
      const controller={active:true,update(data) {
        if(!controller.active)return;
        try {
          tasks.forEach(task=>task(data));
          targets().forEach(n=>{
            n.classList.toggle('primary-visual',n.dataset.experienceTarget===plan.primary_visual);
            n.closest('.experience-component')?.classList.toggle('primary-component',n.dataset.experienceTarget===plan.primary_visual);
            n.classList.toggle('emphasized-node',plan.emphasis_nodes?.includes(n.dataset.node || n.dataset.experienceTarget));
          });
          guideHighlight(false);
        } catch(_) {fallback();controller.active=false;}
      }};
      return controller;
    } catch(_) {return fallback();}
  }
  global.PlaygroundExperience={create,condition};
})(globalThis);
