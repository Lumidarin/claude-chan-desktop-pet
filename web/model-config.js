// ============================================================
//  Claude娘 模型配置
//
//  现在跑的是“立绘模式”（下面的 sprite 字段）：Live2D 模型还没绑好，
//  先用定稿立绘 + 表情差分图层显示（web/sprite.js）。
//  Live2D 绑好、导出到 path 指向的位置后，删掉 sprite 字段即切回 Live2D。
//  开发期占位的鲸鱼娘配置在 model-config.whale.js（模型不随项目分发）。
//
//  ★ 这份文件同时是给 Cubism 绑定的“参数约定”：
//    下面 EXPR 里出现的每个参数名，绑定时都要在模型里建出来，名字一字不差；
//    值的含义见注释。标准参数（ParamEyeLOpen 等）用 Cubism 默认名即可。
//    美术素材：art/Claude娘_拆层起点_4096.psd（定稿底图 + 9 个差分图层，逐像素对齐）。
//
//  桌宠本体（pet.html）只认 window.PET_MODEL；字段含义同 model-config.js。
// ============================================================
(function () {
  // Claude 橙作主色；其余状态色和气泡、进度条一起用
  var ACCENT = { idle: '#9A8F86', working: '#D97757', done: '#5DAE6B', error: '#E5534B', waiting: '#E8A33D' };

  // 标准参数的静止值：换表情前会先把用到的参数全部复位到这里
  var STOCK_REST = {
    ParamEyeLOpen: 1, ParamEyeROpen: 1,
    ParamEyeBallX: 0, ParamEyeBallY: 0,
    ParamBrowLY: 0, ParamBrowRY: 0, ParamBrowLForm: 0, ParamBrowRForm: 0,
    ParamMouthForm: 0, ParamMouthOpenY: 0,
    ParamCheek: 0
  };

  // ==================================================================
  //  表情 = 一组参数值（同步直写，不用 model.expression()，原因见 model-config.js）
  //
  //  对应差分素材（art/差分/精选/）：
  //    闭眼 / 半闭眼   → ParamEyeL/ROpen        0 / 0.5
  //    微笑           → ParamMouthForm          1
  //    张嘴a / 张嘴o   → ParamMouthOpenY + Form  （a 张大说话；o 小圆嘴 Form=-1）
  //    脸红           → ParamCheek              1   （Cubism 标准“脸颊泛红”）
  //    星星眼 / 爱心眼 / 晕圈眼 → 自定义参数，0=普通瞳孔，1=换成对应瞳孔图层
  // ==================================================================
  var EXPR = {
    '闭眼':   { ParamEyeLOpen: 0, ParamEyeROpen: 0 },
    '半闭眼': { ParamEyeLOpen: 0.5, ParamEyeROpen: 0.5 },
    '微笑':   { ParamMouthForm: 1 },
    '张嘴a':  { ParamMouthOpenY: 1, ParamMouthForm: 0.3 },
    '张嘴o':  { ParamMouthOpenY: 0.6, ParamMouthForm: -1 },
    '脸红':   { ParamCheek: 1 },
    '星星眼': { ParamEyeStar: 1 },
    '爱心眼': { ParamEyeHeart: 1, ParamCheek: 1 },
    '晕圈眼': { ParamEyeSpiral: 1, ParamMouthOpenY: 0.4, ParamMouthForm: -1 },
    // 组合表情：完成时闭眼笑；打瞌睡半闭眼 + 头低一点由呼吸动作负责
    '开心':   { ParamEyeLOpen: 0, ParamEyeROpen: 0, ParamMouthForm: 1, ParamCheek: 0.6 },
    '困':     { ParamEyeLOpen: 0.15, ParamEyeROpen: 0.15, ParamBrowLY: -0.4, ParamBrowRY: -0.4 },
    '疑问':   { ParamMouthOpenY: 0.6, ParamMouthForm: -1, ParamBrowLY: 0.5, ParamBrowRY: 0.5 },
    '专注':   { ParamEyeLOpen: 0.8, ParamEyeROpen: 0.8, ParamEyeBallY: -0.6 },
    '为难':   { ParamEyeLOpen: 0.5, ParamEyeROpen: 0.5, ParamMouthOpenY: 0.4, ParamMouthForm: -1, ParamBrowLY: -0.5, ParamBrowRY: -0.5 }
  };

  // ==================================================================
  //  立绘模式：表情名 -> 差分图层（同一套表情名，Live2D 用上面的 EXPR，立绘用这里）
  //  图层来自 art/差分/精选，经 tools/本地生图/make_sprite.py 生成到 web/sprite/claude/
  // ==================================================================
  var SPRITE = {
    dir: 'sprite/claude/',
    // 立绘比窗口略宽，脸对准窗口中线；两侧的书桌和长发被窗口裁掉一点
    layout: { widthFrac: 1.28, anchorX: 0.47 },
    groups: {
      eyes:  ['闭眼', '半闭眼', '星星眼', '爱心眼', '晕圈眼'],
      mouth: ['微笑', '张嘴a', '张嘴o'],
      cheek: ['脸红']
    },
    faces: {
      '闭眼':   ['闭眼'],
      '半闭眼': ['半闭眼'],
      '微笑':   ['微笑'],
      '张嘴a':  ['张嘴a'],
      '张嘴o':  ['张嘴o'],
      '脸红':   ['脸红'],
      '星星眼': ['星星眼'],
      '爱心眼': ['爱心眼', '脸红'],
      '晕圈眼': ['晕圈眼', '张嘴o'],
      '开心':   ['闭眼', '微笑', '脸红'],
      '困':     ['闭眼'],
      '疑问':   ['张嘴o'],
      '专注':   [],                 // 底图本身就是沉静专注的神态
      '为难':   ['半闭眼', '张嘴o']
    },
    blink: '闭眼',
    talk: ['张嘴a', '张嘴o']
  };

  // ==================================================================
  //  2.5D 模式（优先）：Anime2.5DRig 自动绑定的分层模型（web/rig/claude.psd）。
  //  表情 = 发给它的 face 值：eL/eR 眼开 0~1，mo 嘴开 0~1，mf 嘴型 -1(o)~1(笑)，
  //  br 眉 -1(皱)~1(扬)，ax/ay/az 头角度 -1~1，ex/ey 视线 -1~1。没写的用中性值。
  //  星星眼/爱心眼/晕圈眼这类“换瞳孔图层”的表情它做不了，用相近的神态代替。
  // ==================================================================
  var RIG = {
    src: 'rig/index.html?obs=1&model=claude.psd',
    layout: { widthFrac: 1.32, anchorX: 0.47 },
    // 状态 -> 身体动作（动作定义见 rig-driver.js 的 MOTIONS）
    motions: {
      idle: 'calm', thinking: 'ponder', planning: 'ponder', waiting: 'ponder',
      reading: 'read', writing: 'write', running: 'busy', working: 'busy',
      searching: 'search', delegating: 'wave', done: 'cheer', proud: 'cheer',
      error: 'slump', struggling: 'slump', interrupted: 'slump', longtask: 'doze'
    },
    faces: {
      '闭眼':   { eL: 0, eR: 0 },
      '半闭眼': { eL: 0.6, eR: 0.6 },    // 低于 ~0.3 它就渲染成闭眼了，半闭眼要 0.55~0.6
      '微笑':   { mf: 0.8 },
      '张嘴a':  { mo: 0.8, mf: 0.2 },
      '张嘴o':  { mo: 0.5, mf: -0.6 },
      '脸红':   { mf: 0.4, br: 0.2, az: 0.08 },
      '星星眼': { br: 0.7, mf: 0.6, mo: 0.2 },
      '爱心眼': { eL: 0, eR: 0, mf: 0.9, br: 0.4, az: 0.1 },
      '晕圈眼': { eL: 0.55, eR: 0.55, mo: 0.4, mf: -0.6, br: -0.5, az: 0.15 },
      '开心':   { eL: 0, eR: 0, mf: 0.9, br: 0.45 },
      '困':     { eL: 0.12, eR: 0.12, br: -0.3, ay: 0.35 },
      '疑问':   { mo: 0.35, mf: -0.4, br: 0.7, az: 0.12 },
      '专注':   { eL: 0.85, eR: 0.85, ey: 0.5 },
      '为难':   { eL: 0.6, eR: 0.6, mo: 0.3, mf: -0.6, br: -0.6 }
    }
  };

  // ==================================================================
  //  16 个状态 → 表情 / 动作
  //  动作组还没做（motion 全是 null = 只在 Idle 循环里呼吸）。
  //  绑好 Tap 动作（翻书、写字、托腮……）后在 MOTION_NAME 登记，再把下标填进 motion。
  //  状态的触发条件见 CLAUDE.md 第 6 节；longtask / interrupted 由 pet.html 的 watchdog 判断。
  // ==================================================================
  var STATE_MAP = {
    idle:        { expr: null,     motion: null, symbol: null, interval: 3.0, wear: [] },
    thinking:    { expr: '半闭眼', motion: null, symbol: null, interval: 4.0, wear: [] },
    waiting:     { expr: '疑问',   motion: null, symbol: null, interval: 3.6, wear: [] },
    working:     { expr: '专注',   motion: null, symbol: null, interval: 2.4, wear: [] },
    done:        { expr: '开心',   motion: null, symbol: null, interval: 3.6, wear: [] },
    error:       { expr: '晕圈眼', motion: null, symbol: null, interval: 4.0, wear: [] },
    reading:     { expr: '专注',   motion: null, symbol: null, interval: 4.4, wear: [] },
    writing:     { expr: '专注',   motion: null, symbol: null, interval: 3.0, wear: [] },
    running:     { expr: '专注',   motion: null, symbol: null, interval: 2.4, wear: [] },
    searching:   { expr: '星星眼', motion: null, symbol: null, interval: 4.0, wear: [] },
    delegating:  { expr: '微笑',   motion: null, symbol: null, interval: 2.6, wear: [] },
    planning:    { expr: '半闭眼', motion: null, symbol: null, interval: 3.0, wear: [] },
    proud:       { expr: '爱心眼', motion: null, symbol: null, interval: 3.6, wear: [] },
    struggling:  { expr: '为难',   motion: null, symbol: null, interval: 4.2, wear: [] },
    interrupted: { expr: '张嘴o',  motion: null, symbol: null, interval: 4.0, wear: [] },
    longtask:    { expr: '困',     motion: null, symbol: null, interval: 5.5, wear: [] }
  };

  window.PET_MODEL = {
    name: 'Claude娘',
    title: 'Claude',
    accent: ACCENT,
    // 绑定导出的 model3.json 放到 live2d/claude/ 下（相对 web/pet.html）
    path: '../live2d/claude/claude.model3.json',
    rig: RIG,           // 2.5D 模式（要经 http 打开）；不可用时退回下面的立绘
    sprite: SPRITE,     // 立绘模式；rig 和 sprite 都删掉就用 Live2D（path）
    layout: { heightFrac: 0.78, xFrac: 0.5 },
    stockRest: STOCK_REST,
    expr: EXPR,
    symbolIds: [],
    states: STATE_MAP,
    slots: [],          // 换装以后再加（发饰 / 眼镜 / 桌面小物）
    motionNames: [],
    hots: []
  };
})();
