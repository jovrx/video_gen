const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const source = readFileSync(require('node:path').join(__dirname,'../app/static/i18n.js'),'utf8');
function load(saved, blocked=false) {
  const storage = {getItem:()=>{if(blocked) throw new Error('disabled'); return saved;},setItem:()=>{if(blocked) throw new Error('disabled');}};
  return runInNewContext(source+'; I18n', {document:{documentElement:{}},localStorage:storage,window:{dispatchEvent:()=>{}},Event:class {}});
}
test('default and unsupported preferences use English, even without storage',()=>{
  for (const value of [null,'invalid','zh','en-US']) assert.equal(load(value).language,'en');
  const i18n=load(null,true);
  assert.equal(i18n.t('创建视频'),'Create Video');
  i18n.setLanguage('zh-CN');
  assert.equal(i18n.t('创建视频'),'创建视频');
});
test('parameterized messages retain counts, IDs and external error detail',()=>{
  const i18n=load(null);
  assert.equal(i18n.message('素材上传 10/20'),'Uploading assets 10/20');
  assert.equal(i18n.message('提交过于频繁，请等待 123 秒后再试'),'Submitting too frequently. Wait 123 seconds and try again.');
  assert.equal(i18n.message('映射无效：节点字段不存在：240.value'),'Invalid mapping: Node field does not exist: 240.value');
  assert.equal(i18n.message('Custom platform detail: <unknown>'),'Custom platform detail: <unknown>');
});
test('visible application messages can be translated back to Chinese',()=>{
  const i18n=load(null);
  const error=i18n.t('当前配置最多接受 {max} 张参考图。',{max:9});
  i18n.setLanguage('zh-CN');
  assert.equal(i18n.message(error),'当前配置最多接受 9 张参考图。');
});
test('interpolated filenames and workflow field names are preserved',()=>{
  const i18n=load(null);
  const error=i18n.t('{name} 需要小于 30MB。',{name:'参考图.png'});
  assert.equal(i18n.message(error),'参考图.png must be under 30MB.');
  assert.equal(i18n.message('映射无效：节点字段不存在：240.提示词'),'Invalid mapping: Node field does not exist: 240.提示词');
  i18n.setLanguage('zh-CN');
  assert.equal(i18n.message(error),'参考图.png 需要小于 30MB。');
});
test('English counts use singular and plural forms',()=>{
  const i18n=load(null);
  assert.equal(i18n.t('{count} 张图',{count:1}),'1 image');
  assert.equal(i18n.t('{count} 张图',{count:2}),'2 images');
  assert.equal(i18n.t('共 {total} 条生成记录',{total:1}),'1 generation record');
  i18n.setLanguage('zh-CN');
  assert.equal(i18n.message('1 generation record'),'共 1 条生成记录');
});
