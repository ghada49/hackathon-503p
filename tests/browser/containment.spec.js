const {test,expect}=require('@playwright/test');
const {resolve}=require('node:path');
const {pathToFileURL}=require('node:url');

test('wide values scroll locally with keyboard access on mobile',async({page,context})=>{
  await context.setOffline(true);
  await page.setViewportSize({width:390,height:844});
  await page.goto(pathToFileURL(resolve('out/browser/attention-canonical/index.html')).href);
  await page.evaluate(()=>{
    const matrix=Array.from({length:2},()=>Array.from({length:20},(_,i)=>i+.123));
    document.querySelector('#main-visual').replaceChildren(PlaygroundVisuals.table(matrix,'Wide matrix'));
    const card=document.querySelector('.intermediate-card');
    card.replaceChildren(Object.assign(document.createElement('div'),{className:'big-value',textContent:'0.123456789012345678901234567890123456789'}));
  });
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
  const scroll=page.getByRole('region',{name:'Wide matrix'});
  await scroll.focus();await page.keyboard.press('ArrowRight');
  await expect.poll(()=>scroll.evaluate(e=>e.scrollLeft)).toBeGreaterThan(0);
  await page.evaluate(()=>document.documentElement.style.fontSize='200%');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
});
