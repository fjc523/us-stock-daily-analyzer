// 使用真实 Chrome 点击隔离生成页面，禁止外网和分析写请求。
const fs=require('fs'),assert=require('assert/strict');
const cfg=JSON.parse(fs.readFileSync(process.argv[2]));
const {chromium}=require(cfg.tools+'/node_modules/playwright');
const checks=[],requests=[],errors=[];
function record(name,details={}){checks.push({name,status:'PASS',...details});console.log('PASS '+name);}
(async()=>{
const browser=await chromium.launch({executablePath:cfg.chrome,headless:true});
const ctx=await browser.newContext({viewport:{width:1280,height:1000}});
await ctx.route('**/*',async route=>{const r=route.request(),url=r.url();requests.push({url,method:r.method(),body:r.postData()});
if(url.startsWith('http')&&!url.startsWith(cfg.base)){errors.push('禁止外网 '+url);return route.abort();}
if(r.method()==='POST'&&(!url.endsWith('/api/watchlist')||!r.postData()?.includes('toggle'))){errors.push('禁止写请求 '+url);return route.abort();}
return route.continue();});
let page=await ctx.newPage();page.on('pageerror',e=>errors.push(String(e)));
const paths=['/','/days/2026-10-01/index.html','/days/2026-10-01/NVDA.html','/symbols/NVDA.html'];
let serial=0;
async function isOpen(d){return d.evaluate(x=>x.open);}
async function outside(d){const b=await d.boundingBox();return {x:Math.max(2,b.x-10),y:Math.max(2,b.y-10)};}
async function exercise(trigger,dialog,label){
await trigger.click();await dialog.waitFor({state:'visible'});
const b=await dialog.boundingBox();
await page.mouse.click(b.x+2,b.y+2);assert(await isOpen(dialog));record(label+' 内部边缘空白');
const heading=dialog.locator('h2').first();await heading.click();assert(await isOpen(dialog));record(label+' 内部内容');
if(await dialog.locator('svg').count()){await dialog.locator('svg').click({position:{x:100,y:90}});assert(await isOpen(dialog));record(label+' 图表点击');}
const out=await outside(dialog);await page.mouse.move(b.x+10,b.y+10);await page.mouse.down();await page.mouse.move(out.x,out.y,{steps:10});await page.mouse.up();assert(await isOpen(dialog));record(label+' 内部开始拖到外部');
const before=requests.length;await page.mouse.click(out.x,out.y);await page.waitForTimeout(70);assert(!(await isOpen(dialog)));assert.equal(requests.length,before);record(label+' 外部关闭且无新增请求');
await page.screenshot({path:cfg.evidence+'/closed-'+(++serial)+'.png'});
await trigger.click();await dialog.waitFor({state:'visible'});await page.screenshot({path:cfg.evidence+'/opened-'+serial+'.png'});await page.keyboard.press('Escape');assert(!(await isOpen(dialog)));record(label+' 重开及 Esc');
await trigger.click();await dialog.waitFor({state:'visible'});await dialog.getByRole('button',{name:'关闭',exact:true}).click();assert(!(await isOpen(dialog)));record(label+' 关闭按钮');
}
for(const mode of ['HTTP','FILE'])for(const path of paths){
const url=mode==='HTTP'?cfg.base+path:'file://'+cfg.root+'/site'+(path==='/'?'/index.html':path);
await page.goto(url);await page.waitForTimeout(150);
const entries=await page.locator('[data-comparison],[data-source-open]').evaluateAll(xs=>xs.map((x,i)=>({i,kind:x.hasAttribute('data-comparison')?'comparison':'source',source:x.dataset.sourceOpen})));
record(mode+' '+path+' 入口枚举',{entries});
for(const entry of entries){const t=page.locator('[data-comparison],[data-source-open]').nth(entry.i);const d=entry.kind==='comparison'?t.locator('..').locator('dialog'):page.locator('#'+entry.source);await exercise(t,d,mode+' '+path+' '+entry.kind+' '+entry.i);}
}
await page.goto(cfg.base);await page.waitForTimeout(150);
await exercise(page.locator('#manage-watchlist'),page.locator('#watchlist-manager'),'HTTP 管理订阅');
await exercise(page.locator('#manage-settings'),page.locator('#settings-manager'),'HTTP 分析参数');
await page.locator('#manage-watchlist').click();await page.locator('#manager-list button').first().waitFor();
await page.locator('#watchlist-form summary').click();await page.locator('#watchlist-form [name=name]').fill('未提交的名字');await page.locator('#watchlist-form [name=symbol]').fill('ZZZZ');
let before=requests.length;await page.mouse.click(...Object.values(await outside(page.locator('#watchlist-manager'))));await page.waitForTimeout(650);
assert(!requests.slice(before).some(x=>x.method==='POST'||x.url.includes('/api/instruments')));record('未提交订阅表单外部关闭不保存且不新增验证请求');
await page.locator('#manage-settings').click();await page.locator('#settings-form [name=parallel]').fill('4');
before=requests.length;await page.mouse.click(...Object.values(await outside(page.locator('#settings-manager'))));await page.waitForTimeout(100);
assert(!requests.slice(before).some(x=>x.method==='POST'));record('未提交参数表单外部关闭不保存');
await page.locator('#manage-settings').click();await page.locator('#settings-form [name=quick_effort]').selectOption('medium');assert(await isOpen(page.locator('#settings-manager')));record('参数输入和下拉保持打开');await page.keyboard.press('Escape');
await page.locator('#manage-watchlist').click();await page.locator('#manager-list button').first().waitFor();
await page.locator('#manager-list button').first().click();await page.locator('#manager-message').filter({hasText:'已暂停'}).waitFor();assert(await isOpen(page.locator('#watchlist-manager')));record('隔离订阅成功修改保持打开');
const nav=page.waitForEvent('framenavigated',f=>f===page.mainFrame());await page.mouse.click(...Object.values(await outside(page.locator('#watchlist-manager'))));await nav;assert(!(await isOpen(page.locator('#watchlist-manager'))));record('隔离修改后外部 native close 刷新首页');
await page.locator('#manage-watchlist').click();await page.locator('#manager-list button').first().waitFor();await page.locator('#manager-list button').first().click();await page.locator('#manager-message').filter({hasText:'已恢复'}).waitFor();const restoreNav=page.waitForEvent('framenavigated',f=>f===page.mainFrame());await page.keyboard.press('Escape');await restoreNav;record('隔离订阅恢复后关闭刷新，后续入口重新可用');
// 浏览器时钟加速仅用于证明既有自动刷新在全部四类弹窗打开时延后。
for(const [trigger,selector,label] of [['#manage-watchlist','#watchlist-manager','管理'],['#manage-settings','#settings-manager','参数'],['[data-comparison]','.comparison-dialog','图表'],['[data-source-open]','.source-dialog','来源']]){
await page.close();page=await ctx.newPage();page.on('pageerror',e=>errors.push(String(e)));await page.clock.install();await page.goto(cfg.base);await page.locator(trigger).first().click();const d=page.locator(selector).first();await d.waitFor({state:'visible'});let navs=0;const fn=f=>{if(f===page.mainFrame())navs++;};page.on('framenavigated',fn);await page.clock.fastForward(301000);assert(await isOpen(d));assert.equal(navs,0);record(label+' 打开期间定时刷新延后');await page.keyboard.press('Escape');await page.clock.fastForward(11000);await page.waitForTimeout(300);assert(navs>=1);record(label+' 关闭后定时刷新恢复');page.off('framenavigated',fn);}
for(const [trigger,selector,label] of [['#manage-watchlist','#watchlist-manager','管理'],['#manage-settings','#settings-manager','参数'],['[data-comparison]','.comparison-dialog','图表'],['[data-source-open]','.source-dialog','来源']]){
await page.close();page=await ctx.newPage();let polls=0;await page.route('**/api/analysis',route=>{requests.push({url:route.request().url(),method:'GET',isolated_response:true});return route.fulfill({json:{busy:++polls===1,items:{}}});});await page.clock.install();await page.goto(cfg.base);await page.waitForTimeout(100);await page.locator(trigger).first().click();const d=page.locator(selector).first();await d.waitFor({state:'visible'});let navs=0;const fn=f=>{if(f===page.mainFrame())navs++;};page.on('framenavigated',fn);await page.clock.fastForward(3100);await page.waitForTimeout(100);assert(await isOpen(d));assert.equal(navs,0);record(label+' 分析完成刷新在打开期间延后');await page.keyboard.press('Escape');await page.clock.fastForward(3100);await page.waitForTimeout(100);assert(navs>=1);record(label+' 关闭后分析完成刷新恢复');page.off('framenavigated',fn);
}
for(const [trigger,selector,label] of [['[data-comparison]','.comparison-dialog','图表'],['[data-source-open]','.source-dialog','来源']]){
await page.close();page=await ctx.newPage();await page.clock.install();await page.goto('file://'+cfg.root+'/site/index.html');assert.equal(await page.locator('meta[http-equiv=refresh]').count(),0);await page.locator(trigger).first().click();const d=page.locator(selector).first();let navs=0;page.on('framenavigated',f=>{if(f===page.mainFrame())navs++;});await page.clock.fastForward(301000);assert(await isOpen(d));assert.equal(navs,0);record('离线 '+label+' 无meta抢先刷新且JS打开期间延后');await page.keyboard.press('Escape');await page.clock.fastForward(11000);await page.waitForTimeout(300);assert(navs>=1);record('离线 '+label+' 关闭后JS定时刷新恢复');
}
assert.deepEqual(errors,[]);assert(!requests.some(x=>x.method==='POST'&&x.url.endsWith('/api/analysis')));record('没有分析写请求或外网请求');
await browser.close();fs.writeFileSync(cfg.evidence+'/browser-results.json',JSON.stringify({checks,requests,errors,browser:'Chrome',config:cfg},null,2));
})().catch(e=>{fs.writeFileSync(cfg.evidence+'/browser-results.json',JSON.stringify({checks,requests,errors,error:String(e),stack:e.stack},null,2));console.error(e);process.exit(1);});
