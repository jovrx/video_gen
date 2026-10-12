// Controlled transport chunks exercise the real UI before a response is complete.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const {join} = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    await context.route('**/api/**',async route => {
      const path = new URL(route.request().url()).pathname;
      const payload = path==='/api/creation/config'?{configured:true,model:'stream-writer'}:
        path==='/api/config'?{key_configured:false,mapping_ready:false}:
        path==='/api/client-status'?{server_time:0,next_submit_at:0,queue:{active:0,waiting:0,unknown:0,limit:3}}:
        path==='/api/jobs/history'?{items:[],total:0,page:1,counts:{all:0,active:0,succeeded:0,attention:0}}:null;
      if (payload) return route.fulfill({json:payload});
      if (path==='/api/events') return route.fulfill({contentType:'text/event-stream',body:''});
      return route.fulfill({status:404,json:{detail:'Unexpected endpoint'}});
    });
    await context.addInitScript(() => {
      const realFetch = window.fetch.bind(window);
      window.fetch = (url,options) => {
        if (!String(url).endsWith('/stream')) return realFetch(url,options);
        window.streamPayload = JSON.parse(options.body);
        const body = new ReadableStream({start(controller) {window.streamController=controller;}});
        return Promise.resolve(new Response(body,{headers:{'Content-Type':'text/event-stream'}}));
      };
      window.emitStream = (name,data) => {
        const bytes=new TextEncoder().encode(`event: ${name}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`);
        for(let i=0;i<bytes.length;i+=7) window.streamController.enqueue(bytes.slice(i,i+7));
      };
    });
    const page = await context.newPage(), errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(process.env.STUDIO_URL || 'http://127.0.0.1:8770');
    await page.locator('#open-creation').click();
    await page.locator('#creation-config-status').filter({hasText:'stream-writer'}).waitFor();
    await page.locator('#creation-prompt').fill('A cat adventure');
    await page.locator('#creation-script').fill('Original screenplay');
    await page.locator('#shot-count').fill('2');
    await page.locator('#target-model').selectOption('generic');
    await page.locator('#generate-storyboard').click();
    await page.waitForFunction(()=>Boolean(window.streamController),{},{timeout:2000});
    await page.evaluate(()=>emitStream('preview',{shots:[{number:1,title:'开场',duration:8,visual:'猫咪出发'}]}));
    await page.waitForFunction(()=>document.querySelector('[data-shot-field="visual"]')?.value==='猫咪出发');
    assert.equal(await page.locator('[data-shot-field="visual"]').first().isDisabled(),true);
    assert.equal(await page.locator('#generate-storyboard').isDisabled(),true);
    assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('h3-studio-creation-v1')).shots.length),0);
    await page.evaluate(()=>emitStream('preview',{shots:[{number:1,title:'开场',duration:8,visual:'猫咪出发去花园',camera:'Tracking',audio:'Birds',prompt:'A cat walks.'},
      {number:2,title:'花园',duration:8,visual:'<img src=x onerror="window.bad=true">'}]}));
    await page.locator('.shot-card').nth(1).waitFor();
    assert.equal(await page.locator('#creation-shots img').count(),0);
    assert.equal(await page.locator('[data-shot-field="visual"]').first().inputValue(),'猫咪出发去花园');
    await page.evaluate(()=>I18n.setLanguage('zh-CN'));
    assert.match(await page.locator('#creation-stream-status').innerText(),/2/);
    const shots=[1,2].map(number=>({number,title:`Shot ${number}`,duration:8,visual:'A cat in a garden',camera:'Tracking',audio:'Birds',prompt:`Prompt ${number}`}));
    await page.evaluate(shots=>{emitStream('result',{shots});streamController.close();window.streamController=null;},shots);
    await page.waitForFunction(()=>!document.querySelector('#generate-storyboard').disabled);
    assert.equal(await page.locator('[data-shot-field="prompt"]').first().inputValue(),'Prompt 1');
    const appearance=await page.locator('.shot-card').evaluateAll(cards=>cards.map(card=>({
      background:getComputedStyle(card).backgroundColor,border:getComputedStyle(card).borderLeftWidth,
      rect:{top:card.getBoundingClientRect().top,bottom:card.getBoundingClientRect().bottom},
      header:Boolean(card.querySelector('.shot-header'))})));
    assert.notEqual(appearance[0].background,appearance[1].background);
    assert.ok(appearance.every(card=>card.header && parseFloat(card.border)>=3));
    assert.ok(appearance[1].rect.top-appearance[0].rect.bottom>=20);
    await page.screenshot({path:join(__dirname,'../.playwright-mcp/creation-stream-separated.png')});
    for (const number of [1,2]) {
      const card = page.locator('.shot-card').nth(number-1);
      await card.evaluate(el=>el.scrollIntoView({block:'start'}));
      await card.screenshot({path:join(__dirname,`../.playwright-mcp/creation-stream-shot-${number}.png`)});
    }
    await page.locator('[data-shot-field="prompt"]').first().fill('Saved edited prompt');
    for(const mode of ['error','disconnect']) {
      await page.locator('#generate-storyboard').click();
      await page.waitForFunction(()=>Boolean(window.streamController));
      await page.evaluate(()=>emitStream('preview',{shots:[{number:1,visual:'Replacement partial'}]}));
      await page.waitForFunction(()=>document.querySelector('[data-shot-field="visual"]').value==='Replacement partial');
      await page.evaluate(mode=>{if(mode==='error')emitStream('error',{detail:'文本模型流式输出中断，请重试；原草稿已保留'});streamController.close();window.streamController=null;},mode);
      await page.waitForFunction(()=>!document.querySelector('#generate-storyboard').disabled);
      assert.equal(await page.locator('[data-shot-field="prompt"]').first().inputValue(),'Saved edited prompt');
      assert.equal(await page.locator('#creation-error').isVisible(),true);
    }
    await page.locator('#generate-script').click();
    await page.waitForFunction(()=>Boolean(window.streamController));
    await page.evaluate(()=>emitStream('preview',{title:'小猫',content:'猫咪说：你好\n'}));
    await page.waitForFunction(()=>document.querySelector('#creation-script').value==='猫咪说：你好\n');
    assert.equal(await page.locator('#creation-script').isDisabled(),true);
    await page.evaluate(()=>{emitStream('result',{title:'小猫',content:'猫咪说：你好\n踏上旅程。'});streamController.close();window.streamController=null;});
    await page.waitForFunction(()=>!document.querySelector('#generate-script').disabled);
    assert.equal(await page.locator('#creation-script').inputValue(),'猫咪说：你好\n踏上旅程。');
    assert.deepEqual(errors,[]);
    console.log('Streaming browser: partial shots/script, UTF-8 framing, final save, rollback, separation passed');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
