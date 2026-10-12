// Run with Playwright installed and the studio running at STUDIO_URL (default :8765).
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const now = Math.floor(Date.now() / 1000);
const settings = {max_concurrent_generations:3, client_cooldown_seconds:60};
const client = {server_time:now, next_submit_at:now + 60, retry_after:60,
  queue:{active:2, waiting:1, unknown:1, limit:3}, system_settings:settings};
const mapping = {prompt:{node_id:'20',field_name:'prompt'}, duration:{node_id:'20',field_name:'duration'},
  images:[{node_id:'10',field_name:'image'}], image_mode:'slots', min_images:1,max_images:1,min_duration:1,max_duration:10};
const config = {key_configured:true,mapping_ready:true,graph_loaded:true,workflow_id:'demo',mapping,
  nodes:[{id:'10',name:'LoadImage',fields:[{name:'image',type:'str'}]},
    {id:'20',name:'H3',fields:[{name:'prompt',type:'str'},{name:'duration',type:'int'}]}]};
const records = ['running','waiting','submission_unknown','download_failed','succeeded'].map((phase,index) => ({
  id:`demo${index}`,phase,prompt:'用户的中文提示词保持原样',duration:5,image_count:1,created_at:now-120,updated_at:now,
  progress:{node_percent:25,completed_nodes:['10']},video_ready:phase==='succeeded',queue_position:1,
  notice:index===0?'素材上传 1/2':null,error:index===3?'视频下载失败，可重试下载，无需重新生成':null
}));
(async () => {
  const browser = await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
  try {
    const context = await browser.newContext({locale:'zh-CN',viewport:{width:1440,height:1000}});
    const page = await context.newPage();
    const errors = []; page.on('pageerror',error => errors.push(error.message));
    await context.route('**/api/**',route => {
      const path = new URL(route.request().url()).pathname;
      const payload = path==='/api/config'?config:path==='/api/client-status'?client:path==='/api/system-settings'?settings:
        path==='/api/jobs/history'?{items:records,total:5,page:1,page_size:12,counts:{all:5,active:2,succeeded:1,attention:2}}:null;
      if (payload) return route.fulfill({json:payload});
      if (path==='/api/events') return route.fulfill({contentType:'text/event-stream',body:''});
      return route.fulfill({status:403,json:{detail:'请从本机工作台页面打开目录'}});
    });
    await page.goto(process.env.STUDIO_URL || 'http://127.0.0.1:8765/');
    await page.locator('.job-card').first().waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    assert.equal(await page.title(),'H3 Video Studio');
    assert.match(await page.locator('#queue-overview').innerText(),/Generation slots/);
    assert.match(await page.locator('#generate-button').innerText(),/Wait \d+s/);
    assert.match(await page.locator('#jobs-container').innerText(),/Uploading assets 1\/2/);
    assert.equal(await page.locator('#results-heading [data-i18n]').evaluate(element=>getComputedStyle(element).fontSize),
      await page.locator('#results-heading').evaluate(element=>getComputedStyle(element).fontSize));
    await page.locator('#prompt').fill('保留我的中文输入');
    await page.locator('#image-input').setInputFiles({name:'reference.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=','base64')});
    await page.locator('video').evaluate(video => { window.testVideo=video; });
    await page.locator('#open-settings').click();
    await page.locator('#max-images').fill('7');
    await page.locator('#close-settings').click();
    await page.locator('#open-resource-directory').click();
    await page.locator('#toast').waitFor({state:'visible'});
    assert.match(await page.locator('#toast').innerText(),/local studio/);
    await page.locator('#language-select').selectOption('zh-CN');
    assert.equal(await page.locator('html').getAttribute('lang'),'zh-CN');
    assert.equal(await page.locator('#composer-heading').innerText(),'创建视频');
    assert.match(await page.locator('#queue-overview').innerText(),/等待队列/);
    assert.equal(await page.locator('#prompt').inputValue(),'保留我的中文输入');
    assert.equal(await page.locator('#image-list img').count(),1);
    assert.equal(await page.locator('#max-images').inputValue(),'7');
    assert.equal(await page.evaluate(()=>window.testVideo===document.querySelector('video')),true);
    assert.match(await page.locator('#toast').innerText(),/请从本机工作台/);
    await page.locator('[data-job-action="details"]').first().click();
    assert.match(await page.locator('#job-details-content').innerText(),/任务 ID/);
    await page.locator('#close-job-details').click();
    await page.reload();
    await page.locator('.job-card').first().waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'),'zh-CN');
    await page.locator('#language-select').selectOption('en');
    const attachDialog = page.waitForEvent('dialog');
    const attachClick = page.locator('[data-job-action="attach"]').click();
    const attach = await attachDialog;
    assert.match(attach.message(),/Verify this submission/);
    await attach.dismiss();
    await attachClick;
    await page.locator('#open-system-settings').click();
    assert.equal(await page.locator('#system-settings-title').innerText(),'System Settings');
    assert.match(await page.locator('#save-system-settings').innerText(),/Save System Settings/);
    await page.locator('#close-system-settings').click();
    await page.locator('#open-settings').click();
    const text = await page.locator('body').innerText();
    assert.equal(/[\p{Script=Han}]/u.test(text.replaceAll('用户的中文提示词保持原样','').replaceAll('简体中文','')),false,text);
    assert.equal(await page.locator('#image-bindings select').getAttribute('aria-label'),'Image input field');
    await page.locator('#close-settings').click();
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    for (const width of [1920,1440,1366,1280,1024]) {
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`Desktop overflow at ${width}`);
      const composer=await page.locator('.composer').boundingBox();
      const library=await page.locator('.results').boundingBox();
      assert.ok(library.x>=composer.x+composer.width,`Two panes at ${width}`);
    }
    const mobile=await browser.newContext({isMobile:true,hasTouch:true,viewport:{width:390,height:844}});
    const mobilePage=await mobile.newPage();
    await mobilePage.goto(process.env.STUDIO_URL || 'http://127.0.0.1:8765/');
    assert.equal(await mobilePage.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Mobile overflow');
    await mobile.close();
    await page.evaluate(()=>localStorage.setItem('h3-studio-language','invalid'));
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    assert.deepEqual(errors,[]);
    console.log('PASS: English default, Chinese/English switch, persistence, dynamic states, errors, dialogs, draft and video preservation.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
