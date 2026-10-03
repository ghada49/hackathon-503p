const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const { resolve } = require('node:path');
const { pathToFileURL } = require('node:url');

test.beforeAll(() => {
  for (const name of ['attention','entropy','generic','iterative','piecewise','markov','graph','recurrence']) {
    execFileSync('python',['-m','playground.renderer','--fixture',`tests/fixtures/${name}_ir.json`,'--output',`out/${name}.html`]);
    execFileSync('python',['-m','playground.renderer','--fixture',`tests/fixtures/${name}_ir.json`,'--experience',`examples/experiences/${name}.json`,'--output',`out/${name}-directed.html`]);
    execFileSync('python',['-c',`import json; from pathlib import Path; from playground.renderer import render_to_file; ir=json.loads(Path('tests/fixtures/${name}_ir.json').read_text(encoding='utf-8')); ir['experience']={'story':'cause_and_effect','layout':'controls_left','hero_visual':next('visual_'+str(i) for i,v in enumerate(ir['visuals']) if v['type']!='formula'),'guided_mode':[{'target':t,'instruction':'Inspect '+t} for t in [ir['controls'][0]['id'],'main_visual','what_changed','source_grounding']],'annotations':[{'target':'main_visual','kind':'insight','text':'Follow the evaluated values.'}]}; render_to_file(ir,'out/${name}-shared.html'); ir['experience']['hero_visual']='missing'; render_to_file(ir,'out/${name}-shared-invalid.html'); ir.pop('experience'); render_to_file(ir,'out/${name}-shared-absent.html')`]);
  }
});

test('final shared ExperienceSpec works across eight mechanisms with offline guides and canonical recovery',async ({page})=>{
  const errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
  for(const name of ['attention','entropy','generic','iterative','piecewise','markov','graph','recurrence']) {
    await open(page,`${name}-shared`);
    expect(await page.evaluate(()=>JSON.parse(document.querySelector('#playground-data').textContent).experience.contract)).toBe('shared');
    await expect(page.locator('#experience-stage')).toBeVisible();
    await page.getByRole('button',{name:'Guide me'}).click();
    for(let step=0;step<4;step++) {
      await expect(page.locator('.guide-target')).toHaveCount(1);
      if(step<3)await page.getByRole('button',{name:'Next'}).click();
    }
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button',{name:'Guide me'})).toBeFocused();
    const control=page.locator('#experience-stage input[type="number"], #experience-stage input[type="range"]').first();
    const before=await page.evaluate(()=>JSON.stringify(PlaygroundUI.getValues()));
    const old=Number(await control.inputValue());
    const step=Number(await control.getAttribute('step')) || 0.1;
    await control.fill(String(old+step));
    await expect.poll(()=>page.evaluate(()=>JSON.stringify(PlaygroundUI.getValues()))).not.toBe(before);
    await expect(page.locator('#change-path')).not.toBeEmpty();
    await expect(page.locator('#experience-stage .primary-visual')).not.toBeEmpty();
    for(const suffix of ['shared-invalid','shared-absent']) {
      await open(page,`${name}-${suffix}`);
      await expect(page.locator('#canonical-stage')).toBeVisible();
      await expect(page.locator('#experience-stage')).toBeHidden();
      await expect(page.locator('#main-visual')).not.toBeEmpty();
    }
  }
  expect(errors).toEqual([]);expect(requests).toEqual([]);
});
test('directed experiences have distinct compositions and preserve mandatory sections',async ({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(const name of ['attention','entropy','generic']) {
    await open(page,`${name}-directed`);
    await expect(page.locator('#experience-stage')).toBeVisible();
    await expect(page.locator('#canonical-stage')).toBeHidden();
    for(const id of ['overview','intermediates','changes','explorations','limitations','source'])await expect(page.locator(`#${id}`)).toBeVisible();
    await expect(page.locator('#experience-stage .control')).toHaveCount(name==='attention' ? 4 : 2);
    await page.screenshot({path:`out/${name}-directed-preview.png`,fullPage:true});
  }
  await expect(page.locator('#experience-stage>.layout-equation_first')).toBeVisible();
  await open(page,'entropy-directed');await expect(page.locator('#experience-stage [data-experience-target="entropy"] .big-value')).toHaveText('2 bits');
  await expect(page.locator('#experience-stage .before-after-grid')).toBeVisible();
  expect(errors).toEqual([]);
});
test('first viewport contains orientation, a control, and primary visual without website chrome',async ({page})=>{
  for(const viewport of [{width:1280,height:800},{width:390,height:844},{width:320,height:800}]) {
    await page.setViewportSize(viewport);
    for(const [name,value] of [['attention','weights'],['entropy','contributions'],['generic','posterior_distribution']]) {
      for(const directed of [false,true]) {
        await open(page,`${name}${directed ? '-directed' : ''}`);
        await expect(page.locator('nav, .sidebar, .topbar, .brand, .offline, .experience-hero')).toHaveCount(0);
        const visual=directed ? page.locator(`#experience-stage [data-experience-target="${value}"]`).first() : page.locator('#main-visual');
        const control=page.locator(`${directed ? '#experience-stage' : '#controls'} input, ${directed ? '#experience-stage' : '#controls'} select`).first();
        for(const locator of [page.locator('h1'),page.locator('#idea'),control,visual]) {
          const box=await locator.boundingBox();expect(box).not.toBeNull();
          expect(box.y).toBeGreaterThanOrEqual(0);expect(box.y+box.height).toBeLessThanOrEqual(viewport.height);
        }
        await page.screenshot({path:`out/${name}-${directed ? 'directed' : 'canonical'}-${viewport.width}-viewport.png`});
      }
    }
  }
});
test('guided walkthrough is reversible, escapable, and allows live control edits',async ({page})=>{
  await open(page,'attention-directed');
  await page.evaluate(async()=>{await window.PlaygroundUI.setEvaluator({evaluate:()=>({scores:[[1,0],[0,1]],scaled_scores:[[1,0],[0,1]],weights:[[.7,.3],[.3,.7]],attention_output:[[1,2],[3,4]]})});});
  await page.getByRole('button',{name:'Guide me'}).click();
  await expect(page.locator('#guide-progress')).toHaveText('Step 1 of 3');
  await expect(page.locator('.control.guide-target')).toHaveCount(1);
  await page.getByLabel('Query matrix Q, row 1, column 1',{exact:true}).fill('4');
  expect(await page.evaluate(()=>window.PlaygroundUI.getState().Q[0][0])).toBe(4);
  await page.getByRole('button',{name:'Next'}).click();await expect(page.locator('#guide-progress')).toHaveText('Step 2 of 3');
  await expect(page.locator('.guide-target')).toHaveCount(1);
  await page.getByRole('button',{name:'Back',exact:true}).click();await expect(page.locator('#guide-progress')).toHaveText('Step 1 of 3');
  await page.keyboard.press('Escape');await expect(page.locator('#guided-walkthrough')).toBeHidden();
  await expect(page.getByRole('button',{name:'Guide me'})).toBeFocused();
});
test('conditional callouts, causal deltas, and before/after use actual runtime values',async ({page})=>{
  await open(page,'generic-directed');await attachMock(page);
  await expect(page.locator('#experience-annotations .experience-callout')).toBeHidden();
  await page.getByLabel('Prior probability',{exact:true}).fill('0.9');
  await expect(page.locator('#experience-annotations')).toContainText('above 0.8');
  await expect(page.locator('#experience-annotations .experience-callout')).toBeVisible();
  await expect(page.locator('#change-path')).toContainText('Δ 0.6');
  await expect(page.locator('#change-path')).toContainText('Belief in the hypothesis');
  await page.locator('#before-after summary').click();
  await expect(page.locator('#before-after-values')).toContainText('posterior: 0.3');
  await expect(page.locator('#before-after-values')).toContainText('posterior: 0.9');
  await page.getByLabel('Prior probability',{exact:true}).fill('0.3');
  await expect(page.locator('#experience-annotations .experience-callout')).toBeHidden();
});
test('comparison snapshots share chart scales when runtime values change',async ({page})=>{
  await open(page,'generic-directed');
  await page.evaluate(async()=>{await window.PlaygroundUI.setEvaluator({evaluate:(_,c)=>({posterior_distribution:c.prior===.3 ? [.2,.8] : [.9,.1]})});});
  await page.getByLabel('Prior probability',{exact:true}).fill('0.6');
  const descriptions=await page.locator('#experience-stage .before-after-grid svg desc').allTextContents();
  expect(descriptions).toHaveLength(2);
  expect(descriptions[0]).toContain('Range 0 to 0.9');expect(descriptions[1]).toContain('Range 0 to 0.9');
  expect(descriptions[0]).toContain('H: 0.2');expect(descriptions[1]).toContain('H: 0.9');
});
test('invalid experience keeps canonical controls, visuals, and science metadata',async ({page})=>{
  const code="import json; from pathlib import Path; from playground.renderer import render_to_file; ir=json.loads(Path('tests/fixtures/generic_ir.json').read_text(encoding='utf-8')); render_to_file(ir,'out/invalid-experience.html',experience={'tree':{'type':'script','text':'window.injected=true'}})";
  execFileSync('python',['-c',code]);await open(page,'invalid-experience');
  await expect(page.locator('#canonical-stage')).toBeVisible();await expect(page.locator('#experience-stage')).toBeHidden();
  await expect(page.locator('#controls .control')).toHaveCount(2);await expect(page.locator('#evidence')).not.toBeEmpty();
  expect(await page.evaluate(()=>window.injected)).toBeUndefined();
});
test('presentation failure restores canonical controls and preserves evaluated output',async ({page})=>{
  await open(page,'generic-directed');
  await page.evaluate(async()=>{
    const original=window.PlaygroundVisuals.render;
    window.PlaygroundVisuals.render=(spec,...args)=>{if(spec.type==='bar_chart')throw new Error('Simulated component failure');return original(spec,...args);};
    await window.PlaygroundUI.setEvaluator({evaluate:()=>({prior_odds:1,posterior_odds:2,posterior:.42,posterior_distribution:[.42,.58]})});
  });
  await expect(page.locator('#canonical-stage')).toBeVisible();await expect(page.locator('#experience-stage')).toBeHidden();
  await expect(page.locator('#controls .control')).toHaveCount(2);
  expect(await page.evaluate(()=>window.PlaygroundUI.getValues().posterior)).toBe(.42);
  await page.getByLabel('Prior probability',{exact:true}).fill('0.6');
  expect(await page.evaluate(()=>window.PlaygroundUI.getState().prior)).toBe(.6);
  await expect(page.locator('#runtime-error')).toBeHidden();
});
test('directed compositions and guided toolbar fit compact and large-text screens',async ({page})=>{
  await page.emulateMedia({colorScheme:'dark',reducedMotion:'reduce'});
  for(const name of ['attention','entropy','generic']) {
    await page.setViewportSize({width:320,height:800});await open(page,`${name}-directed`);
    await page.getByRole('button',{name:'Guide me'}).click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
    await page.getByRole('button',{name:'End guide',exact:true}).click();
    await page.addStyleTag({content:':root{font-size:200%}'});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  }
});
test('semantic scenes lay out objects without model-authored coordinates',async ({page})=>{
  await open(page);
  const count=await page.evaluate(()=>{
    const ir=JSON.parse(document.getElementById('playground-data').textContent).ir;
    const spec={type:'scene',title:'Input to output',options:{layout:'horizontal_flow',objects:[{id:'input',shape:'circle',label:'Input'},{id:'transform',shape:'process',label:'Transformation'},{id:'output',shape:'circle',label:'Output'}],links:[{from:'input',to:'transform'},{from:'transform',to:'output'}]}};
    const result=window.PlaygroundVisuals.render(spec,{},ir);document.getElementById('main-visual').replaceChildren(result);return result.querySelectorAll('g').length;
  });expect(count).toBe(3);await expect(page.locator('#main-visual')).toContainText('Transformation');
});
async function open(page,name='generic') { await page.goto(pathToFileURL(resolve(`out/${name}.html`)).href); }
async function attachMock(page) {
  // UI transport stub, deliberately not a science interpreter. Its output makes
  // the last submitted prior inspectable so tests can verify data plumbing.
  await page.evaluate(async () => {
    await window.PlaygroundUI.setEvaluator({evaluate: (_ir,controls) => ({prior_odds:1,posterior_odds:2,posterior:controls.prior,posterior_distribution:[.5,.5]})});
  });
}
test('all fixtures open offline with distinct control and visual types',async ({page}) => {
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for (const [name,title] of [['attention','Scaled Dot-Product Attention'],['entropy','Shannon Entropy'],['generic','Bayesian Update with Odds']]) {
    const network=[];page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
    await open(page,name);await expect(page.locator('h1')).toHaveText(title);
    await expect(page.locator('#controls input, #controls select').first()).toBeEnabled();
    await expect(page.locator('#exploration-cards article')).toHaveCount(2);
    await expect(page.locator('#evidence')).not.toBeEmpty();
    expect(network).toEqual([]);
    await page.screenshot({path:`out/${name}-preview.png`,fullPage:true});
  }
  expect(errors).toEqual([]);
});
test('adapter updates outputs, dependency highlights, and reset',async ({page}) => {
  await open(page);await attachMock(page);
  const slider=page.getByLabel('Prior probability',{exact:true});
  await slider.fill('0.6');
  await expect(page.locator('#change-summary')).toContainText('0.3 → 0.6');
  expect(await page.evaluate(()=>window.PlaygroundUI.getState().prior)).toBe(.6);
  await expect(page.locator('#dependency-graph [data-node="posterior"]')).toHaveClass(/affected/);
  await page.getByRole('button',{name:'Reset values'}).click();
  expect(await page.evaluate(()=>window.PlaygroundUI.getState().prior)).toBe(.3);
});
test('exploration restores defaults before applying its structured setup',async ({page}) => {
  await open(page);await attachMock(page);
  await page.getByLabel('Prior probability',{exact:true}).fill('0.8');
  await page.locator('[data-exploration="0"]').click();
  const state=await page.evaluate(()=>window.PlaygroundUI.getState());
  expect(state.prior).toBe(.3);expect(state.likelihood_ratio).toBe(1);
});
test('evaluation failure keeps previous successful values',async ({page}) => {
  await open(page);await attachMock(page);
  await page.evaluate(async ()=>{await window.PlaygroundUI.setEvaluator({evaluate:()=>{throw new Error('Invalid test input');}});});
  await expect(page.getByRole('alert')).toContainText('Previous values are preserved');
  expect(await page.evaluate(()=>window.PlaygroundUI.getValues().posterior)).toBe(.3);
});
test('rapid edits preserve both controls and discard stale async results',async ({page}) => {
  await open(page);await attachMock(page);
  await page.evaluate(()=>{
    window.pending=[];
    window.PlaygroundUI.setEvaluator({evaluate:(_,c)=>new Promise(resolve=>window.pending.push({controls:c,resolve}))});
    const inputs=document.querySelectorAll('#controls input');
    inputs[0].value='.6';inputs[0].dispatchEvent(new Event('input'));
    inputs[1].value='9';inputs[1].dispatchEvent(new Event('input'));
    window.pending[2].resolve({posterior:.9});
  });
  await expect(page.locator('#change-summary')).toContainText('0.3 → 0.9');
  expect(await page.evaluate(()=>window.PlaygroundUI.getState())).toEqual({prior:.6,likelihood_ratio:9});
  await page.evaluate(()=>{window.pending[1].resolve({posterior:.1});window.pending[0].resolve({posterior:.2});});
  expect(await page.evaluate(()=>window.PlaygroundUI.getValues().posterior)).toBe(.9);
});
test('keyboard tabs work and a malformed visual falls back',async ({page}) => {
  await open(page);
  await page.getByRole('tab').first().focus();await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab').nth(1)).toBeFocused();await expect(page.getByRole('tab').nth(1)).toHaveAttribute('aria-selected','true');
  await page.evaluate(()=>{
    const ir=JSON.parse(document.getElementById('playground-data').textContent).ir;
    document.getElementById('main-visual').replaceChildren(window.PlaygroundVisuals.render({type:'scene',options:{elements:[{type:'script',text:'attack'}]}},{},ir));
  });
  await expect(page.locator('#main-visual')).toContainText('Showing the calculation path');
  await expect(page.locator('#main-visual .pipeline-node')).not.toHaveCount(0);
});
test('compact, dark, and large-text layouts stay within the viewport',async ({page}) => {
  await page.emulateMedia({colorScheme:'dark',reducedMotion:'reduce'});
  for (const width of [320,390,768,1440]) {
    await page.setViewportSize({width,height:900});await open(page,'attention');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  }
  await page.setViewportSize({width:390,height:900});
  await page.addStyleTag({content:':root{font-size:200%}'});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  expect(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior)).toBe('auto');
});
test('matrix edits and numeric select values reach the adapter unchanged',async ({page}) => {
  await open(page,'attention');
  await page.evaluate(async ()=>{window.lastControls=null;await window.PlaygroundUI.setEvaluator({evaluate:(_,c)=>{window.lastControls=c;return {};}});});
  await page.getByLabel('Query matrix Q, row 1, column 1',{exact:true}).fill('4');
  expect(await page.evaluate(()=>window.lastControls.Q[0][0])).toBe(4);
  await open(page,'entropy');
  await page.evaluate(async ()=>{await window.PlaygroundUI.setEvaluator({evaluate:(_,c)=>{window.lastControls=c;return {};}});});
  await page.getByLabel('Number of outcomes',{exact:true}).selectOption('0');
  expect(await page.evaluate(()=>window.lastControls.num_outcomes)).toBe(2);
});
test('IR strings stay inert in browser DOM',async ({page}) => {
  const code="import json; from pathlib import Path; from playground.renderer import render_to_file; ir=json.loads(Path('tests/fixtures/generic_ir.json').read_text(encoding='utf-8')); ir['teaching']['idea']='<img src=x onerror=window.injected=true>'; render_to_file(ir,'out/security.html',source={'url':'javascript:window.injected=true','title':'</script><script>window.injected=true</script>'})";
  execFileSync('python',['-c',code]);
  await page.goto(pathToFileURL(resolve('out/security.html')).href);
  await expect(page.locator('#idea')).toHaveText('<img src=x onerror=window.injected=true>');
  await expect(page.locator('#idea img')).toHaveCount(0);await expect(page.locator('#source-card a')).toHaveCount(0);
  expect(await page.evaluate(()=>window.injected)).toBeUndefined();
});
test('standard charts, graph, and restricted scene render data safely',async ({page}) => {
  await open(page);
  const report=await page.evaluate(()=>{
    const ir=JSON.parse(document.getElementById('playground-data').textContent).ir;
    const cases=[
      {type:'bar_chart',value:'vector'}, {type:'line_chart',value:'vector'},
      {type:'scatter',value:'pairs'},
      {type:'nodes_edges',options:{nodes:[{id:'a'},{id:'b'}],edges:[{source:'a',target:'b'}]}},
      {type:'scene',options:{elements:[{type:'circle',cx:{ref:'radius'},cy:50,r:10},{type:'text',x:20,y:100,text:'<script>inert</script>'}]}}
    ];
    return cases.map(spec=>{const result=window.PlaygroundVisuals.render(spec,{vector:[-1,2,3],pairs:[[0,1],[2,3]],radius:40},ir);return {svg:!!result.querySelector('svg') || result.tagName.toLowerCase()==='svg',fallback:result.textContent.includes('Showing the calculation path')};});
  });
  expect(report.every(r=>r.svg && !r.fallback)).toBe(true);
});

test('eight unrelated mechanisms compute offline and both inputs update their outputs',async ({page,context})=>{
  await context.setOffline(true);
  const errors=[],network=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
  const cases=[
    ['attention','attention_output',[[1.660476901,2.660476901],[2.339523099,3.339523099]],['Query matrix Q, row 1, column 1','3'],['Value matrix V, row 1, column 1','5']],
    ['entropy','entropy',2,['Outcome weights, entry 1','0.5'],['Number of outcomes','select']],
    ['generic','posterior',.5625,['Prior probability','0.6'],['Likelihood ratio','6']],
    ['iterative','final',.7119140625,['Initial state','6'],['Update fraction','0.5']],
    ['piecewise','clipped',[-1,-.5,.5,1],['Input values, entry 1','0'],['Symmetric bound','2']],
    ['markov','distribution',[.562,.438],['Initial distribution, row 1, column 1','0.5'],['Transition count','1']],
    ['graph','output',[1,2,1],['Node features, row 1, column 1','3'],['Message gain','1']],
    ['recurrence','final',.07776,['Input sequence, entry 1','2'],['Retention factor','0.8']]
  ];
  for(const [name,output,expected,...edits] of cases) {
    await open(page,`${name}-directed`);
    const actual=await page.evaluate(id=>window.PlaygroundUI.getValues()[id],output);
    const flat=v=>Array.isArray(v) ? v.flat(Infinity) : [v];
    flat(actual).forEach((v,i)=>expect(v).toBeCloseTo(flat(expected)[i],8));
    await expect(page.locator('#runtime-error')).toBeHidden();
    await expect(page.locator('#experience-stage')).toBeVisible();
    await expect(page.locator('#exploration-cards article')).toHaveCount(2);
    for(const edit of edits) {
      const before=await page.evaluate(id=>window.PlaygroundUI.getValues()[id],output);
      const input=page.getByLabel(edit[0],{exact:true});
      const disclosure=input.locator('xpath=ancestor::details');if(await disclosure.count())await disclosure.evaluate(n=>{n.open=true;});
      if(edit[1]==='select')await input.selectOption('0');else await input.fill(edit[1]);
      await expect(page.locator('#runtime-error')).toBeHidden();
      const after=await page.evaluate(id=>window.PlaygroundUI.getValues()[id],output);
      expect(after).not.toEqual(before);
      await expect(page.locator('#change-path')).not.toBeEmpty();
      await page.getByRole('button',{name:'Reset values'}).click();
    }
    await page.getByRole('button',{name:'Guide me'}).click();
    await expect(page.locator('#guide-progress')).toHaveText('Step 1 of 3');
    await page.getByRole('button',{name:'Next'}).click();
    await expect(page.locator('#guide-progress')).toHaveText('Step 2 of 3');
    await page.keyboard.press('Escape');
    await page.setViewportSize({width:320,height:800});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.setViewportSize({width:1440,height:1000});
    await page.screenshot({path:`out/${name}-live-preview.png`,fullPage:true});
  }
  expect(errors).toEqual([]);expect(network).toEqual([]);
});

test('trusted dependency paths distinguish inputs and omit unchanged computations',async ({page})=>{
  await open(page,'attention-directed');
  await page.getByLabel('Value matrix V, row 1, column 1',{exact:true}).fill('5');
  await expect(page.locator('#change-path')).toContainText('Weighted output');
  await expect(page.locator('#change-path')).not.toContainText('Similarity scores');
  await expect(page.locator('#dependency-graph [data-node="scores"]')).not.toHaveClass(/affected/);
  await expect(page.locator('#dependency-graph [data-node="attention_output"]')).toHaveClass(/affected/);
  await page.getByLabel('Query matrix Q, row 1, column 1',{exact:true}).fill('3');
  await expect(page.locator('#change-path')).toContainText('Similarity scores');
  await expect(page.locator('#dependency-graph [data-node="scores"]')).toHaveClass(/affected/);
  await open(page,'graph-directed');
  await page.getByLabel('Message gain',{exact:true}).fill('1');
  await expect(page.locator('#change-path')).toContainText('Scaled messages');
  await expect(page.locator('#change-path')).not.toContainText('Neighbor sums');
  await expect(page.locator('#intermediate-values [data-node="aggregate"]')).not.toHaveClass(/changed-node/);
  await page.getByRole('button',{name:'Guide me'}).click();
  await expect(page.locator('.guided-dependency')).not.toHaveCount(0);
});

test('zero probabilities are finite and invalid normalization preserves the last result',async ({page})=>{
  await open(page,'entropy');
  await page.locator('[data-exploration="0"]').click();
  expect(await page.evaluate(()=>window.PlaygroundUI.getValues().entropy)).toBe(0);
  const state=await page.evaluate(()=>window.PlaygroundUI.getState());
  for(let i=3;i>=0;i--)await page.getByLabel(`Outcome weights, entry ${i+1}`,{exact:true}).fill('0');
  await expect(page.locator('#runtime-error')).toContainText('Previous values are preserved');
  expect(await page.evaluate(()=>window.PlaygroundUI.getValues().entropy)).toBe(0);
  expect(await page.evaluate(()=>window.PlaygroundUI.getState())).toEqual(state);
  await page.getByLabel('Outcome weights, entry 1',{exact:true}).fill('0.5');
  await expect(page.locator('#runtime-error')).toBeHidden();
});

test('heterogeneous source excerpts are safe and optional metadata is graceful',async ({page})=>{
  const blocks=['heading','paragraph','equation','algorithm','table','list','caption'].map((type,i)=>({id:`b${i}`,type,text:i===0 ? '</script><img src=x onerror=window.injected=true>' : `Example ${type}`,order:i,...(i===2 ? {section_number:'3.2',equation_number:4,page:9} : {})}));
  const source={title:'Synthetic source metadata',blocks};
  const code=`import json; from pathlib import Path; from playground.renderer import render_to_file; ir=json.loads(Path('tests/fixtures/generic_ir.json').read_text(encoding='utf-8')); source=json.loads(${JSON.stringify(JSON.stringify(source))}); ir['evidence'][0]['blocks']=[b['id'] for b in source['blocks']]; render_to_file(ir,'out/source-types.html',source=source)`;
  execFileSync('python',['-c',code]);await open(page,'source-types');
  await expect(page.locator('#source-excerpts article')).toHaveCount(7);
  await expect(page.locator('#source-excerpts')).toContainText('From the provided excerpt');
  await expect(page.locator('#source-excerpts')).toContainText('Section 3.2 · Eq. 4 · Page 9');
  await expect(page.locator('#source-excerpts img')).toHaveCount(0);
  expect(await page.evaluate(()=>window.injected)).toBeUndefined();
});

test('visual recovery selects compatible charts before the final computation diagram',async ({page})=>{
  await open(page);
  const results=await page.evaluate(()=>{
    const ir=JSON.parse(document.getElementById('playground-data').textContent).ir;
    return [[1,2,3],[[1,2],[3,4]],[[1],[2,3]]].map(value=>{
      const result=window.PlaygroundVisuals.render({type:'unknown',value:'v'},{v:value},ir);
      return {svg:!!result.querySelector('svg') || result.tagName.toLowerCase()==='svg',heatmap:!!result.querySelector('.heatmap-key'),diagram:!!result.querySelector('.pipeline-node')};
    });
  });
  expect(results[0].svg).toBe(true);expect(results[1].heatmap).toBe(true);expect(results[2].diagram).toBe(true);
});

test('calculation components bind live stages and connect only real dependencies',async ({page})=>{
  const experience={story:'build_step_by_step',calculation_order:['prior_odds','posterior_odds','posterior'],tree:{type:'split',children:[{type:'control_group',controls:['prior','likelihood_ratio']},{type:'calculation_steps'}]}};
  const code=`import json; from pathlib import Path; from playground.renderer import render_to_file; ir=json.loads(Path('tests/fixtures/generic_ir.json').read_text(encoding='utf-8')); render_to_file(ir,'out/calculation-component.html',experience=json.loads(${JSON.stringify(JSON.stringify(experience))}))`;
  execFileSync('python',['-c',code]);await open(page,'calculation-component');
  await expect(page.locator('#experience-stage .calculation-arrow')).toHaveCount(2);
  await expect(page.locator('#experience-stage .pipeline-node')).not.toHaveCount(0);
  await page.getByLabel('Likelihood ratio',{exact:true}).fill('6');
  await expect(page.locator('#experience-stage [data-node="posterior_odds"] .value-change')).not.toBeEmpty();
  await expect(page.locator('#experience-stage [data-node="prior_odds"] .value-change')).toHaveCount(0);
  const duplicateIds=await page.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(n=>n.id);return ids.filter((id,i)=>ids.indexOf(id)!==i);});
  expect(duplicateIds).toEqual([]);
  await open(page,'iterative-directed');
  // History and final are independent calculations from the same inputs.
  await expect(page.locator('#intermediate-values .calculation-arrow')).toHaveCount(0);
});

test('heatmap comparisons keep a shared numerical color domain',async ({page})=>{
  const experience={story:'compare_cases',layout:'comparison',hero_visual:'weights'};
  const code=`import json; from pathlib import Path; from playground.renderer import render_to_file; ir=json.loads(Path('tests/fixtures/attention_ir.json').read_text(encoding='utf-8')); render_to_file(ir,'out/heatmap-comparison.html',experience=json.loads(${JSON.stringify(JSON.stringify(experience))}))`;
  execFileSync('python',['-c',code]);await open(page,'heatmap-comparison');
  await page.getByLabel('Query matrix Q, row 1, column 1',{exact:true}).fill('4');
  const legends=await page.locator('#experience-stage .heatmap-key').allTextContents();
  expect(legends).toHaveLength(2);expect(legends[0]).toEqual(legends[1]);
});
