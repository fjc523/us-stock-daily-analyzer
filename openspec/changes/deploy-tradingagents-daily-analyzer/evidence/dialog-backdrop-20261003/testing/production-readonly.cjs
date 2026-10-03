// 仅在经理明确通知部署完成后运行：生产只读真实点击，不修改配置或启动分析。
const fs=require('fs'),assert=require('assert/strict');
const {chromium}=require('/tmp/us-stock-dialog-testing-20261003-tools/node_modules/playwright');
const base=process.argv[2],out=process.argv[3];
if(!base||!out||!/^http:\/\/127\.0\.0\.1:\d+\/?$/.test(base))throw Error('必须由经理提供确切本机生产URL和证据目录');
const origin=base.replace(/\/$/,''),checks=[],requests=[],errors=[],blocked=[];
function pass(name,details={}){checks.push({name,status:'PASS',...details});console.log('PASS '+name);}
(async()=>{
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
try{
const ctx=await browser.newContext({viewport:{width:1280,height:1000}});
await ctx.route('**/*',route=>{const r=route.request(),url=new URL(r.url());const item={url:r.url(),method:r.method()};requests.push(item);
if(url.origin!==origin||r.method()!=='GET'||url.pathname==='/api/instruments'){blocked.push(item);return route.abort();}
return route.continue();});
const page=await ctx.newPage();page.on('pageerror',e=>errors.push(String(e)));await page.goto(origin+'/');await page.waitForTimeout(150);
const html=await page.content();fs.writeFileSync(out+'/production-page.html',html);
pass('生产页面已加载',{base:origin,backdropLogic:html.includes('backdropPointer'),dialogRefreshGuard:html.includes('querySelector("dialog[open]")')});
assert(html.includes('backdropPointer'));assert(html.includes('querySelector("dialog[open]")'));
const entries=[{kind:'管理订阅',trigger:'#manage-watchlist',dialog:'#watchlist-manager'},{kind:'分析参数',trigger:'#manage-settings',dialog:'#settings-manager'}];
const extra=await page.locator('[data-comparison],[data-source-open]').evaluateAll(xs=>xs.map((x,i)=>({i,kind:x.hasAttribute('data-comparison')?'走势比较':'数据源详情',source:x.dataset.sourceOpen})));
pass('生产弹窗入口枚举',{management:entries,details:extra});
for(const kind of ['走势比较','数据源详情']){const first=extra.find(e=>e.kind===kind);if(first)entries.push(first);else checks.push({name:kind+' 生产样本缺失',status:'NOT_TESTED'});}
let serial=0;
for(const e of entries){const trigger=e.trigger?page.locator(e.trigger):page.locator('[data-comparison],[data-source-open]').nth(e.i);
if(!(await trigger.count())){checks.push({name:e.kind+' 生产入口缺失',status:'NOT_TESTED'});continue;}
const d=e.dialog?page.locator(e.dialog):e.source?page.locator('#'+e.source):trigger.locator('..').locator('dialog');
await trigger.click();await d.waitFor({state:'visible'});await page.waitForTimeout(120);const b=await d.boundingBox();
await page.mouse.click(b.x+2,b.y+2);assert(await d.evaluate(x=>x.open));await d.locator('h2').first().click();assert(await d.evaluate(x=>x.open));
if(await d.locator('svg').count()){await d.locator('svg').first().click({position:{x:100,y:90}});assert(await d.evaluate(x=>x.open));}
if(e.kind==='分析参数'){const input=d.locator('input[name=parallel]');const value=await input.inputValue();await input.click();assert.equal(await input.inputValue(),value);assert(await d.evaluate(x=>x.open));}
pass(e.kind+' 内部空白内容操作保持打开且未改值');
await page.screenshot({path:out+'/production-opened-'+(++serial)+'.png'});
const point=[{x:b.x-8,y:b.y+5},{x:b.x+b.width+8,y:b.y+5},{x:b.x+5,y:b.y-8}].find(p=>p.x>=1&&p.x<1280&&p.y>=1&&p.y<1000);assert(point,'页面没有可点击背景区域');
await page.mouse.move(b.x+10,b.y+10);await page.mouse.down();await page.mouse.move(point.x,point.y,{steps:10});await page.mouse.up();assert(await d.evaluate(x=>x.open));pass(e.kind+' 内部开始拖到背景保持打开');
const before=requests.length;await page.mouse.click(point.x,point.y);await page.waitForTimeout(100);assert(!(await d.evaluate(x=>x.open)));
assert(!requests.slice(before).some(x=>!x.url.endsWith('/api/analysis')));pass(e.kind+' 外部关闭未新增业务请求');await page.screenshot({path:out+'/production-closed-'+serial+'.png'});
await trigger.click();await d.waitFor({state:'visible'});await page.keyboard.press('Escape');assert(!(await d.evaluate(x=>x.open)));pass(e.kind+' 重开及Esc关闭');
await trigger.click();await d.waitFor({state:'visible'});await d.getByRole('button',{name:'关闭',exact:true}).click();assert(!(await d.evaluate(x=>x.open)));pass(e.kind+' 原关闭按钮');
}
assert.deepEqual(blocked,[]);assert.deepEqual(errors,[]);pass('无被拦截请求或页面错误，无POST/身份/外网请求');
fs.writeFileSync(out+'/production-results.json',JSON.stringify({base:origin,checks,requests,errors,blocked},null,2));
}finally{await browser.close();}
})().catch(e=>{fs.writeFileSync(out+'/production-results.json',JSON.stringify({base:origin,checks,requests,errors,blocked,error:String(e),stack:e.stack},null,2));console.error(e);process.exit(1);});
