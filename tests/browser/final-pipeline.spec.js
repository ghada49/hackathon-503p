const {test,expect}=require('@playwright/test');
const {execFileSync}=require('node:child_process');
const {resolve}=require('node:path');
const {pathToFileURL}=require('node:url');
const {existsSync}=require('node:fs');

test.beforeAll(()=>{
  const venv=resolve('.venv/Scripts/python.exe');
  execFileSync(process.env.PYTHON || (existsSync(venv)?venv:'python'),['tests/make_browser_artifacts.py']);
});

for(const name of ['attention','entropy','generic'])for(const mode of ['canonical','shared','invalid']){
  test(`agent output ${name}/${mode} opens offline and recomputes`,async({page,context})=>{
    await context.setOffline(true);
    const errors=[],requests=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
    await page.goto(pathToFileURL(resolve(`out/browser/${name}-${mode}/index.html`)).href);
    const stage=mode==='shared'?'#experience-stage':'#canonical-stage';
    await expect(page.locator(stage)).toBeVisible();
    await expect(page.locator('#runtime-error')).toBeHidden();
    for(const id of ['overview','intermediates','changes','explorations','limitations','source'])
      await expect(page.locator(`#${id}`)).toBeVisible();
    await expect(page.locator('#source-card')).toContainText(name==='generic' && mode==='invalid' ?
      `https://example.org/${name}` : `Browser test source: ${name}`);
    await expect(page.locator('#source-card a')).toHaveAttribute('href',`https://example.org/${name}`);
    await expect(page.locator('#source-excerpts')).not.toBeEmpty();
    const before=await page.evaluate(()=>PlaygroundUI.getValues());
    const output=name==='attention'?'attention_output':name==='entropy'?'entropy':'posterior';
    const input=page.getByLabel(name==='attention'?'Query matrix Q, row 1, column 1':name==='entropy'?'Outcome weights, entry 1':'Prior probability',{exact:true});
    const visual=page.locator(mode==='shared'?`${stage} .primary-visual`:'#main-visual');
    const initialVisual=await visual.innerHTML();
    await input.fill(name==='attention'?'3':name==='entropy'?'0.5':'0.6');
    await expect.poll(()=>page.evaluate(id=>PlaygroundUI.getValues()[id],output)).not.toEqual(before[output]);
    await expect.poll(()=>visual.innerHTML()).not.toBe(initialVisual);
    await expect(page.locator('#change-path')).not.toBeEmpty();
    await expect(page.locator('#runtime-error')).toBeHidden();
    if(mode==='shared'){
      await page.getByRole('button',{name:'Guide me'}).click();
      for(let i=0;i<4;i++){
        await expect(page.locator('.guide-target')).toHaveCount(1);
        if(i<3)await page.getByRole('button',{name:'Next'}).click();
      }
      await page.keyboard.press('Escape');
      await expect(page.getByRole('button',{name:'Guide me'})).toBeFocused();
    }
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`out/browser/${name}-${mode}/mobile.png`,fullPage:true});
    expect(errors).toEqual([]);expect(requests).toEqual([]);
  });
}
