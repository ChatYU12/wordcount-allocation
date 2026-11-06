/* 静态演示版的 API 垫片：把 /api/* 请求接到预置快照上 */
(function () {
  'use strict';
  window.__STATIC_DEMO__ = true;

  var bundlePromise = null;
  function loadBundle() {
    if (!bundlePromise) {
      bundlePromise = fetch('./demo-bundle.json').then(function (r) { return r.json(); });
    }
    return bundlePromise;
  }
  function json(obj) {
    return new Response(JSON.stringify(obj), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
  }
  var origFetch = window.fetch.bind(window);

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.indexOf('/api/default-people') >= 0) {
      return loadBundle().then(function (b) { return json({ people: b.people }); });
    }
    if (url.indexOf('/api/allocate') >= 0) {
      return loadBundle().then(function (b) { return json(b.result); });
    }
    if (url.indexOf('/api/parse') >= 0) {
      return Promise.resolve(json({ detail: '在线演示版不支持上传 PDF，请下载源码在本地运行完整版。' }));
    }
    if (url.indexOf('/api/import-people') >= 0) {
      return Promise.resolve(json({ ok: false, error: '在线演示版不支持导入名单，请下载源码在本地运行完整版。' }));
    }
    if (url.indexOf('/api/people-template') >= 0) {
      window.location.href = './编写名单模板.xlsx';
      return Promise.resolve(new Response('', { status: 204 }));
    }
    if (url.indexOf('/api/export') >= 0) {
      // 演示版：直接给一份预先生成的示例表格
      return origFetch('./字数分配表-示例.xlsx').then(function (r) {
        if (r.ok) { setTimeout(function () { /* 前端会自己下载 */ }, 0); }
        return r;
      });
    }
    return origFetch(input, init);
  };

  // 打开页面即载入示例，省得用户面对空白表单
  window.addEventListener('load', function () {
    setTimeout(function () {
      if (typeof loadDemo === 'function') loadDemo();
    }, 30);
  });
})();
