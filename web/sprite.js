// ============================================================
//  立绘模式渲染器 —— Live2D 模型绑好之前，用立绘 + 表情差分图层直接显示角色
//
//  素材由 tools/本地生图/make_sprite.py 生成：base.png + 每个差分一张透明 PNG +
//  manifest.js（各图层在底图上的位置）。差分图层和底图逐像素对齐，叠上去就是换表情。
//
//  配置（model-config.js 里的 sprite 字段）：
//    dir      素材目录（相对 pet.html）
//    layout   { widthFrac: 立绘宽 / 窗口宽, anchorX: 立绘上哪一点对准窗口中线(0~1) }
//    groups   互斥的图层组：同组同时只显示一张（眼睛一组、嘴一组；脸红单独叠加）
//    faces    表情名 -> 图层名列表（表情名和 Live2D 的 expr 共用同一套）
//    blink    眨眼用的图层；talk 说话时轮换的嘴型图层
//
//  动起来的部分：呼吸起伏（CSS）、随机眨眼、气泡换字时动几下嘴。
//  当前表情已经占用眼睛 / 嘴时，就不眨眼 / 不动嘴，免得盖掉表情。
// ============================================================
(function () {
  'use strict';

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error('加载失败：' + src)); };
      document.head.appendChild(s);
    });
  }

  function mount(cfg, container) {
    var dir = cfg.dir || '';
    // file:// 下不能 fetch JSON，manifest 写成脚本，加载后挂在 window.PET_SPRITE
    return loadScript(dir + 'manifest.js').then(function () {
      var man = window.PET_SPRITE;
      if (!man) throw new Error('manifest.js 里没有 PET_SPRITE');

      var root = document.createElement('div');
      root.id = 'sprite';
      root.style.cssText = 'position:absolute;bottom:0;pointer-events:none;';
      var body = document.createElement('div');
      body.className = 'sprite-body';
      body.style.cssText = 'position:relative;width:100%;height:100%;transform-origin:50% 100%;' +
        'animation:sprite-breathe 4.2s ease-in-out infinite;';
      root.appendChild(body);

      var style = document.createElement('style');
      style.textContent = '@keyframes sprite-breathe{0%,100%{transform:translateY(0) scaleY(1)}' +
        '50%{transform:translateY(-1.5px) scaleY(1.006)}}';
      document.head.appendChild(style);

      function addImg(src, x, y, w, h) {
        var im = document.createElement('img');
        im.src = dir + src;
        im.draggable = false;
        // 百分比定位：窗口缩放时图层跟着底图一起缩
        im.style.cssText = 'position:absolute;left:' + (x / man.w * 100) + '%;top:' + (y / man.h * 100) +
          '%;width:' + (w / man.w * 100) + '%;height:' + (h / man.h * 100) + '%;';
        body.appendChild(im);
        return im;
      }
      addImg(man.base, 0, 0, man.w, man.h);
      var layers = {};
      Object.keys(man.layers).forEach(function (name) {
        var L = man.layers[name];
        var im = addImg(L.src, L.x, L.y, L.w, L.h);
        im.style.display = 'none';
        layers[name] = im;
      });
      container.insertBefore(root, container.firstChild);

      function layout() {
        var lay = cfg.layout || {};
        var W = window.innerWidth;
        var sw = W * (lay.widthFrac || 1);
        var sh = sw * man.h / man.w;
        root.style.width = sw + 'px';
        root.style.height = sh + 'px';
        root.style.left = (W / 2 - sw * (lay.anchorX === undefined ? 0.5 : lay.anchorX)) + 'px';
      }
      layout();
      window.addEventListener('resize', layout);

      // ---- 表情 / 眨眼 / 动嘴 -----------------------------------------
      var groups = cfg.groups || {};
      var groupOf = {};
      Object.keys(groups).forEach(function (g) { groups[g].forEach(function (n) { groupOf[n] = g; }); });
      var face = [];          // 当前表情的图层
      var temp = {};          // group -> 临时覆盖的图层（眨眼 / 说话）

      function render() {
        var want = {};
        face.forEach(function (n) { want[n] = true; });
        Object.keys(temp).forEach(function (g) {
          if (!temp[g]) return;
          // 临时图层顶掉同组的表情图层
          Object.keys(want).forEach(function (n) { if (groupOf[n] === g) delete want[n]; });
          want[temp[g]] = true;
        });
        Object.keys(layers).forEach(function (n) { layers[n].style.display = want[n] ? '' : 'none'; });
      }

      function faceUses(group) {
        return face.some(function (n) { return groupOf[n] === group; });
      }

      function setFace(name) {
        face = (name && cfg.faces && cfg.faces[name]) ? cfg.faces[name].slice() : [];
        temp = {};
        render();
      }

      // 眨眼：2.5~6 秒一次，偶尔连眨两下；表情已经在用眼睛（闭眼、星星眼…）时跳过
      var blinkName = cfg.blink;
      function scheduleBlink() {
        setTimeout(function () {
          if (blinkName && layers[blinkName] && !faceUses(groupOf[blinkName])) {
            var g = groupOf[blinkName];
            var twice = Math.random() < 0.2;
            temp[g] = blinkName; render();
            setTimeout(function () {
              temp[g] = null; render();
              if (twice) setTimeout(function () {
                if (faceUses(g)) return;
                temp[g] = blinkName; render();
                setTimeout(function () { temp[g] = null; render(); }, 110);
              }, 170);
            }, 120);
          }
          scheduleBlink();
        }, 2500 + Math.random() * 3500);
      }
      scheduleBlink();

      // 说话：气泡换字时嘴动 3~5 下；表情自己带嘴型（微笑、张嘴…）时不动
      var talkTimer = null;
      function talk() {
        var talkLayers = (cfg.talk || []).filter(function (n) { return layers[n]; });
        if (!talkLayers.length) return;
        var g = groupOf[talkLayers[0]];
        if (faceUses(g)) return;
        clearTimeout(talkTimer);
        var steps = 6 + Math.floor(Math.random() * 4);
        (function step(i) {
          if (i >= steps || faceUses(g)) { temp[g] = null; render(); return; }
          temp[g] = (i % 2 === 0) ? talkLayers[Math.floor(Math.random() * talkLayers.length)] : null;
          render();
          talkTimer = setTimeout(function () { step(i + 1); }, 90 + Math.random() * 70);
        })(0);
      }

      return { setFace: setFace, talk: talk, layers: layers, get face() { return face.slice(); } };
    });
  }

  window.PetSprite = { mount: mount };
})();
