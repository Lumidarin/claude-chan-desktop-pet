// ============================================================
//  2.5D 模式驱动器 —— 用 Anime2.5DRig（web/rig/，MIT）显示自动绑定好的角色，
//  再按桌宠状态控制她的表情。
//
//  Anime2.5DRig 的 OBS 显示页（?obs=1）背景完全透明，并监听同源 BroadcastChannel
//  'anime25d-camera' 上的 face 消息（本来是摄像头面部追踪）：
//    { type:'face', at:Date.now(), cam:{ live:true, ax,ay,az(头角度 -1~1), eL,eR(眼开 0~1),
//                                      mo(嘴开 0~1), ex,ey(视线 -1~1), br(眉 -1~1), mf(嘴型 -1~1) } }
//  只要持续发（20Hz），表情就完全由我们决定；它自带的眨眼/口パク会让位，所以眨眼、
//  说话时动嘴、轻微摆头都在这里自己做。
//
//  BroadcastChannel 要求同源：页面必须经 http 打开（electron-app/main.js 起了本机静态服务器）。
//
//  配置（model-config.js 的 rig 字段）：
//    src     iframe 地址（相对 pet.html）
//    layout  { widthFrac, anchorX } 同立绘模式
//    faces   表情名 -> 上面那些 cam 值的子集（没写的用中性值）
// ============================================================
(function () {
  'use strict';

  var NEUTRAL = { ax: 0, ay: 0, az: 0, eL: 1, eR: 1, mo: 0, ex: 0, ey: 0, br: 0, mf: 0 };
  var HZ = 20;
  // 说话时的元音口型：mo 开合（渲染器在 ~0.15 以上才开始显示张嘴图），mf 嘴角上扬(+)/下垂(-)
  var VOWELS = [
    { mo: 0.95, mf: 0.1 },    // a：张大
    { mo: 0.35, mf: 0.75 },   // i：扁，嘴角上扬
    { mo: 0.3,  mf: -0.55 },  // u：小，收拢
    { mo: 0.55, mf: 0.45 },   // e：中等，略扬
    { mo: 0.65, mf: -0.85 }   // o：中等，嘴角下垂成圆
  ];
  var CLOSED = { mo: 0, mf: 0 };

  // ---- 动作 ----------------------------------------------------------
  // 平时只有很小的底噪晃动，“做动作”时才明显。动作 = 一段关键帧：[[秒, {量: 偏移}], …]，
  // 从 0 开始、最后一帧回到 {}，帧间平滑插值，偏移叠加在当前表情上。能动的量：
  //   bob 整体上下(px，负 = 往上)  tilt 整体摇摆(度，正 = 顺时针)
  //   ax 头左右  ay 头上下(正 = 低头)  az 歪头    ex/ey 视线(ey 正 = 往下看)
  //   eL/eR 眼开（负 = 眯 / 闭）  br 眉(正 = 扬)  mf 嘴角(正 = 笑)  mo 张嘴
  //   armY 抬手(0~1) —— 经 'pose' 消息设 Anime2.5DRig 的手臂滑杆（从肩到手逐渐加权，肩那头不动）。
  //   不用 armPos（腕位置補正）：它把整条手臂连肩膀一起往下平移，手臂会和身体脱开
  //   能抬手是因为模型层序是“深色剪影 → 补全的桌子 → 补全的书 → 人物”（desk_layers.py / make_rig_psd.py）：
  //   手一抬露出完整书页，缝里是深色底，不会裂开。身体倾斜滑杆（body）仍不用。
  var ACT_KEYS = ['bob', 'tilt', 'ax', 'ay', 'az', 'ex', 'ey', 'eL', 'eR', 'br', 'mf', 'mo', 'armY'];
  var GESTURES = {
    // 通用
    lookAround: [[0.6, { ax: -0.25, ex: -0.6 }], [1.0, { ax: -0.25, ex: -0.6 }],
                 [1.8, { ax: 0.25, ex: 0.6 }], [2.2, { ax: 0.25, ex: 0.6 }], [2.9, {}]],          // 左右张望
    glance:     [[0.3, { ex: 0.5, ey: -0.25 }], [1.4, { ex: 0.5, ey: -0.25, mf: 0.3 }], [1.8, {}]], // 抬眼看你
    smile:      [[0.4, { mf: 0.6, br: 0.2 }], [1.8, { mf: 0.6, br: 0.2 }], [2.3, {}]],
    hum:        [[0.3, { az: 0.07, mf: 0.3 }], [0.7, { az: -0.07, mf: 0.3 }], [1.1, { az: 0.07, mf: 0.3 }],
                 [1.5, { az: -0.05, mf: 0.3 }], [1.9, {}]],                                       // 哼歌轻晃
    nod:        [[0.25, { ay: 0.25 }], [0.5, { ay: 0 }], [0.75, { ay: 0.2 }], [1.1, {}]],          // 点头
    // 待机
    stretch:    [[0.6, { bob: -6, eL: -0.7, eR: -0.7, br: 0.3, az: -0.08, armY: 0.9 }],
                 [1.5, { bob: -6, eL: -0.7, eR: -0.7, br: 0.3, az: -0.08, armY: 0.9 }], [2.2, {}]], // 伸懒腰
    yawn:       [[0.5, { mo: 0.8, mf: -0.4, eL: -0.7, eR: -0.7, az: 0.1, bob: -2 }],
                 [1.6, { mo: 0.9, mf: -0.4, eL: -0.8, eR: -0.8, az: 0.1, bob: -2 }], [2.3, {}]],  // 打哈欠
    // 看书
    readLines:  [[0.2, { ex: -0.5, ey: 0.4 }], [1.1, { ex: 0.5, ey: 0.4 }], [1.3, { ex: -0.5, ey: 0.5 }],
                 [2.2, { ex: 0.5, ey: 0.5 }], [2.4, { ex: -0.5, ey: 0.6 }], [3.3, { ex: 0.5, ey: 0.6 }],
                 [3.7, {}]],                                                                       // 一行行扫读
    turnPage:   [[0.35, { ax: 0.12, ex: 0.4, ey: 0.5, bob: 1, armY: 0.45 }],
                 [0.7, { ax: 0.18, ex: 0.5, ey: 0.5, bob: 2, armY: 0.4 }],
                 [1.0, { ax: 0.18, ex: 0.5, ey: 0.5, bob: 2, armY: 0.15 }], [1.5, {}]],   // 抬手翻页
    holdUp:     [[0.6, { armY: 0.35, ey: 0.35, ay: -0.05 }], [2.6, { armY: 0.35, ey: 0.4, ex: 0.2 }],
                 [3.2, {}]],                                                                       // 双手微抬捧着读
    // 写作
    writeFocus: [[0.3, { ey: 0.6, bob: 1.5, az: 0.05, armY: 0.12 }], [0.6, { ey: 0.6, bob: 1, az: -0.03, armY: 0.02 }],
                 [0.9, { ey: 0.6, bob: 1.5, az: 0.05, armY: 0.12 }], [1.2, { ey: 0.6, bob: 1, az: -0.03, armY: 0.02 }],
                 [1.6, {}]],                                                                       // 埋头写（手跟着动）
    lookUpThink:[[0.5, { ey: -0.6, ex: 0.4, br: 0.3, ax: 0.1 }], [1.8, { ey: -0.6, ex: 0.4, br: 0.3, ax: 0.1 }],
                 [2.3, {}]],                                                                       // 抬头想词
    // 沉思
    ponderUp:   [[0.6, { ey: -0.7, ex: 0.5, ax: 0.15, az: 0.1, br: 0.4 }],
                 [2.4, { ey: -0.7, ex: 0.5, ax: 0.15, az: 0.1, br: 0.4 }], [3.0, {}]],             // 望向斜上方
    hmm:        [[0.5, { mf: -0.4, br: -0.4, az: -0.1, eL: -0.3, eR: -0.3 }],
                 [1.8, { mf: -0.4, br: -0.4, az: -0.1, eL: -0.3, eR: -0.3 }], [2.3, {}]],          // 皱眉“嗯……”
    aha:        [[0.15, { br: 0.7, bob: -4, mf: 0.5, ey: -0.3, armY: 0.6 }], [0.9, { br: 0.6, mf: 0.5, armY: 0.4 }],
                 [1.3, {}]],                                                                       // 灵光一闪（手一抬）
    // 其他状态
    tap:        [[0.15, { bob: 1.5 }], [0.3, {}], [0.45, { bob: 1.5 }], [0.6, {}], [0.75, { bob: 1.5 }], [0.9, {}]],
    sigh:       [[0.6, { eL: -0.5, eR: -0.5, mo: 0.3, bob: 2, az: -0.05 }],
                 [1.5, { eL: -0.5, eR: -0.5, mo: 0.2, bob: 2 }], [2.1, {}]],                       // 叹气
    dozeNod:    [[1.0, { ay: 0.35, bob: 3 }], [1.3, { ay: 0.05 }], [1.6, {}]],                       // 打瞌睡点头
    hop:        [[0.25, { bob: -10, tilt: 2.5, az: 0.2, armY: 0.7 }], [0.6, { bob: -2, tilt: 1, armY: 0.3 }],
                 [1.0, {}]],                                                                       // 轻轻一跳（手也抬）
    slumpIn:    [[0.6, { bob: 4, tilt: -1.5, az: -0.12 }], [1.2, {}]],
    sway:       [[0.4, { tilt: 2.5, az: 0.2 }], [0.9, { tilt: -1, az: -0.05 }], [1.3, {}]],
    jolt:       [[0.2, { bob: -3 }], [0.5, {}]]
  };
  // 每种状态：hold 一直保持的姿态，enter 切换时做一次的动作，pool 每隔 every 秒随机挑一个（不连着重复）
  var MOTIONS = {
    calm:   { pool: ['lookAround', 'glance', 'smile', 'hum', 'glance', 'stretch', 'yawn'], every: [4, 8] },
    read:   { hold: { ey: 0.3 }, pool: ['readLines', 'readLines', 'turnPage', 'holdUp', 'nod', 'glance'], every: [2, 4.5] },
    write:  { hold: { ey: 0.4 }, pool: ['writeFocus', 'writeFocus', 'lookUpThink', 'nod', 'smile'], every: [2, 4.5] },
    ponder: { hold: { tilt: 1, az: 0.1 }, pool: ['ponderUp', 'hmm', 'aha', 'lookUpThink', 'hum'], every: [2, 4.5] },
    busy:   { enter: 'jolt', pool: ['tap', 'nod', 'lookAround', 'writeFocus'], every: [2.5, 5] },
    search: { enter: 'lookAround', pool: ['lookAround', 'readLines', 'glance'], every: [2, 4.5] },
    cheer:  { enter: 'hop', pool: ['smile', 'hum', 'hop'], every: [3, 6] },
    slump:  { hold: { bob: 4, tilt: -1 }, enter: 'slumpIn', pool: ['sigh', 'hmm'], every: [4, 7] },
    doze:   { hold: { bob: 5, tilt: -1.2 }, pool: ['dozeNod', 'dozeNod', 'yawn'], every: [3, 6] },
    wave:   { enter: 'sway', pool: ['glance', 'smile', 'sway'], every: [3, 6] }
  };
  var BASE_BOB = 0.8, BASE_TILT = 0.2;   // 平时的底噪幅度（px / 度）

  function smoothstep(x) { return x * x * (3 - 2 * x); }
  // 关键帧在 t 秒时的值（隐含 0 秒处全为 0）；超出最后一帧返回 null
  function sample(frames, t) {
    var prevT = 0, prev = {};
    for (var i = 0; i < frames.length; i++) {
      var ft = frames[i][0], fv = frames[i][1];
      if (t <= ft) {
        var k = smoothstep((t - prevT) / Math.max(1e-3, ft - prevT)), out = {};
        ACT_KEYS.forEach(function (key) { out[key] = (prev[key] || 0) + ((fv[key] || 0) - (prev[key] || 0)) * k; });
        return out;
      }
      prevT = ft; prev = fv;
    }
    return null;
  }

  function mount(cfg, container) {
    return new Promise(function (resolve, reject) {
      var frame = document.createElement('iframe');
      frame.id = 'rig';
      frame.src = cfg.src;
      frame.setAttribute('allowtransparency', 'true');
      // color-scheme 必须和 rig 页（<meta name="color-scheme" content="dark">）一致：
      // 不一致时 Chromium 会给 iframe 垫一层不透明底色，透明背景就变成黑块
      // bottom 负值：角色被画面底边切开，整体往上弹（bob 为负）时不能露出切口
      frame.style.cssText = 'position:absolute;bottom:-14px;border:0;background:transparent;pointer-events:none;' +
        'color-scheme:dark;';
      container.insertBefore(frame, container.firstChild);

      function layout() {
        var lay = cfg.layout || {};
        var W = window.innerWidth;
        var side = W * (lay.widthFrac || 1);          // 模型画布是正方形
        frame.style.width = side + 'px';
        frame.style.height = side + 'px';
        frame.style.left = (W / 2 - side * (lay.anchorX === undefined ? 0.5 : lay.anchorX)) + 'px';
      }
      layout();
      window.addEventListener('resize', layout);

      var channel;
      try { channel = new BroadcastChannel('anime25d-camera'); }
      catch (e) { reject(new Error('当前环境不支持 BroadcastChannel')); return; }

      var target = Object.assign({}, NEUTRAL);   // 当前表情要的值
      var cur = Object.assign({}, NEUTRAL);      // 平滑后实际发出的值
      var faceName = null;
      var blinkUntil = 0, nextBlink = performance.now() + 2500;
      var talkUntil = 0, nextSyl = 0, syl = CLOSED;
      var t0 = performance.now();

      function setFace(name) {
        faceName = name || null;
        target = Object.assign({}, NEUTRAL, (name && cfg.faces && cfg.faces[name]) || {});
      }

      function talk() { talkUntil = performance.now() + 900 + Math.random() * 500; }

      // 身体动作随状态切换；参数平滑过渡，不会突然跳
      // 动作调度：切状态时先做 enter，之后每隔 every 秒从 pool 里随机挑一个（不连着重复）
      var motion = MOTIONS.calm, playing = null, lastGesture = null;
      var nextGestureAt = performance.now() + 3000;
      function rand(r) { return r[0] + Math.random() * (r[1] - r[0]); }
      function play(name) { if (GESTURES[name]) { playing = { frames: GESTURES[name], at: performance.now() }; lastGesture = name; } }
      function setStatus(status) {
        var name = (cfg.motions && cfg.motions[status]) || 'calm';
        var next = MOTIONS[name] || MOTIONS.calm;
        if (next === motion) return;
        motion = next;
        playing = null;
        if (motion.enter) play(motion.enter);
        nextGestureAt = performance.now() + rand(motion.every || [4, 8]) * 1000 * 0.6;
      }
      function currentExtras() {
        var now = performance.now(), out = {};
        ACT_KEYS.forEach(function (k) { out[k] = (motion.hold && motion.hold[k]) || 0; });
        if (playing) {
          var v = sample(playing.frames, (now - playing.at) / 1000);
          if (v) ACT_KEYS.forEach(function (k) { out[k] += v[k]; });
          else { playing = null; nextGestureAt = now + rand(motion.every || [4, 8]) * 1000; }
        } else if (now > nextGestureAt && motion.pool && motion.pool.length) {
          var pool = motion.pool.filter(function (g) { return g !== lastGesture; });
          play((pool.length ? pool : motion.pool)[Math.floor(Math.random() * (pool.length || motion.pool.length))]);
        }
        return out;
      }

      // 整体起伏 / 摇摆：CSS 变换，绕画布底边中点转，平滑跟随
      // （用定时器而不是 requestAnimationFrame：页面不在前台时 rAF 会被暂停）
      var whole = { bob: 0, tilt: 0 };
      frame.style.transformOrigin = '50% 100%';
      setInterval(function wholeTick() {
        var t = (performance.now() - t0) / 1000, ex = currentExtras();   // 也负责推进动作调度
        var want = { bob: BASE_BOB * Math.sin(2 * Math.PI * 0.25 * t) + ex.bob,
                     tilt: BASE_TILT * Math.sin(2 * Math.PI * 0.18 * t + 1.7) + ex.tilt };
        whole.bob += (want.bob - whole.bob) * 0.15;
        whole.tilt += (want.tilt - whole.tilt) * 0.15;
        frame.style.transform = 'translateY(' + whole.bob.toFixed(2) + 'px) rotate(' + whole.tilt.toFixed(3) + 'deg)';
      }, 33);

      // 手臂：按当前动作经 'pose' 消息设 armY（平滑过渡）；armPos、身体倾斜 body 固定为 0
      var arm = { armY: 0 };
      setInterval(function poseTick() {
        var ex = currentExtras();
        arm.armY += (Math.max(0, Math.min(1, ex.armY)) - arm.armY) * 0.3;
        channel.postMessage({ type: 'pose', params: { body: 0, armY: +arm.armY.toFixed(3), armPos: 0 },
                              at: Date.now() });
      }, 66);

      function tick() {
        var now = performance.now(), t = (now - t0) / 1000;
        var want = Object.assign({}, target);

        // 摆头：很轻的底噪（最早那版的幅度），再叠当前动作的偏移（头、视线、眼、眉、嘴）
        var act = currentExtras();
        want.ax += Math.sin(t * 0.37) * 0.10 + Math.sin(t * 0.91) * 0.04;
        want.ay += Math.sin(t * 0.29 + 1.3) * 0.06;
        want.az += Math.sin(t * 0.23 + 0.7) * 0.05;
        ['ax', 'ay', 'az', 'ex', 'ey', 'eL', 'eR', 'br', 'mf', 'mo'].forEach(function (k) {
          if (k === 'mo' && now < talkUntil) return;   // 说话时嘴归说话管
          want[k] += act[k];
        });

        // 眨眼：表情本身没闭眼时才眨（闭眼笑、犯困就不眨了）
        var eyesOpen = target.eL > 0.6 && target.eR > 0.6;
        if (eyesOpen && now > nextBlink) {
          blinkUntil = now + 140;
          nextBlink = now + 2500 + Math.random() * 3500;
          if (Math.random() < 0.2) nextBlink = now + 320;     // 偶尔连眨两下
        }
        if (now < blinkUntil) { want.eL = 0; want.eR = 0; }

        // 说话：气泡换字时嘴动几下，每个音节换一个元音口型（它只有一张张嘴图，
        // 靠开合度 mo + 嘴型 mf 的组合变出 a/i/u/e/o），音节间偶尔闭一下；表情自己张着嘴时不动
        if (now < talkUntil && target.mo < 0.2) {
          if (now > nextSyl) {
            syl = Math.random() < 0.18 ? CLOSED : VOWELS[Math.floor(Math.random() * VOWELS.length)];
            nextSyl = now + 90 + Math.random() * 90;
          }
          want.mo = syl.mo;
          want.mf = target.mf + syl.mf;
        }

        // 平滑：眼睛和嘴快一点，头慢一点
        Object.keys(NEUTRAL).forEach(function (k) {
          var fast = (k === 'eL' || k === 'eR' || k === 'mo' || (k === 'mf' && now < talkUntil));
          var a = fast ? 0.55 : 0.12;
          cur[k] += (want[k] - cur[k]) * a;
        });
        var cam = { live: true };
        Object.keys(NEUTRAL).forEach(function (k) {
          var lo = (k === 'eL' || k === 'eR' || k === 'mo') ? 0 : -1;
          cam[k] = Math.max(lo, Math.min(1, cur[k]));
        });
        channel.postMessage({ type: 'face', cam: cam, at: Date.now() });
      }
      setInterval(tick, 1000 / HZ);

      frame.addEventListener('load', function () {
        resolve({ setFace: setFace, setStatus: setStatus, talk: talk, frame: frame, get face() { return faceName; } });
      });
      frame.addEventListener('error', function () { reject(new Error('加载失败：' + cfg.src)); });
    });
  }

  window.PetRig = { mount: mount };
})();
