// ============================================================
//  Claude娘 桌宠  --  Electron 宿主
//
//  读 Claude Code hook（hooks/pet-hook.js）写的状态文件
//    $CLAUDE_PET_STATE  ->  %USERPROFILE%\.claude\pet\state.json
//
//  状态由主进程读文件、走 IPC 推给页面。不要让页面自己 fetch() 文件：
//  Chromium 会拦 file:// 请求（即使 webSecurity:false），气泡会一直显示默认文字。
//
//  交互：
//    - 在桌宠身上拖动可以移动窗口
//    - 右键菜单：置顶开关、重新载入、关闭
// ============================================================

const { app, BrowserWindow, screen, Menu, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');

const W = 380;
const H = 600;
const MARGIN = 24;

const STATE_FILE = (process.env.CLAUDE_PET_STATE || '').trim() ||
  path.join(os.homedir(), '.claude', 'pet', 'state.json');

// 页面经本机 http 打开，不用 file://：2.5D 模式（web/rig-driver.js）靠同源 BroadcastChannel
// 控制 iframe 里的角色，file:// 页面彼此不算同源。只监听 127.0.0.1、随机端口、只读 web/ 目录。
const WEB_ROOT = path.join(__dirname, '..', 'web');
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml',
  '.psd': 'application/octet-stream', '.moc3': 'application/octet-stream', '.wasm': 'application/wasm'
};

function startWebServer() {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      let rel;
      try { rel = decodeURIComponent(new URL(req.url, 'http://x').pathname); } catch (e) { rel = '/'; }
      const file = path.normalize(path.join(WEB_ROOT, rel === '/' ? 'pet.html' : rel));
      // 只许读 web/ 里面的文件
      if (!file.startsWith(WEB_ROOT + path.sep)) { res.writeHead(403); res.end(); return; }
      fs.readFile(file, (err, data) => {
        if (err) { res.writeHead(404); res.end(); return; }
        res.writeHead(200, { 'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream',
                             'Cache-Control': 'no-cache' });
        res.end(data);
      });
    });
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(server.address().port));
  });
}

let win = null;
let pinned = true;
let lastRaw = '';

function readState() {
  try {
    const raw = fs.readFileSync(STATE_FILE, 'utf8');
    if (!raw || raw === lastRaw) return null;
    lastRaw = raw;
    return JSON.parse(raw);
  } catch (e) {
    return null;   // 文件还没有，或者正好在改名；跳过这一拍
  }
}

function num(v, d) { return typeof v === 'number' && isFinite(v) ? v : d; }

function pushState() {
  const s = readState();
  if (!s || !win || win.isDestroyed()) return;
  // ts / turnStart 给 pet.html 的 watchdog 判断“长任务打瞌睡”和“被打断”
  const safe = {
    title: typeof s.title === 'string' ? s.title : 'Claude',
    bubble: typeof s.bubble === 'string' ? s.bubble : '',
    status: typeof s.status === 'string' ? s.status : 'idle',
    progress: num(s.progress, 0),
    tool: typeof s.tool === 'string' ? s.tool : '',
    ts: num(s.ts, Date.now()),
    turnStart: num(s.turnStart, 0)
  };
  win.webContents.send('pet-state', safe);
}

function buildMenu() {
  return Menu.buildFromTemplate([
    {
      label: pinned ? '取消置顶' : '保持置顶',
      click: () => { pinned = !pinned; win.setAlwaysOnTop(pinned, 'screen-saver'); }
    },
    { type: 'separator' },
    { label: '重新载入', click: () => win.webContents.reload() },
    { label: '关闭桌宠', click: () => app.quit() }
  ]);
}

function createWindow(port) {
  const wa = screen.getPrimaryDisplay().workArea;

  win = new BrowserWindow({
    width: W,
    height: H,
    x: wa.x + wa.width - W - MARGIN,
    y: wa.y + MARGIN,
    show: false,
    useContentSize: true,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    hasShadow: false,
    focusable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      backgroundThrottling: false,
      spellcheck: false
    }
  });

  win.setAlwaysOnTop(true, 'screen-saver');
  win.webContents.setBackgroundThrottling(false);

  win.webContents.on('context-menu', (event) => {
    event.preventDefault();
    buildMenu().popup({ window: win });
  });

  if (port) win.loadURL(`http://127.0.0.1:${port}/pet.html`);
  else win.loadFile(path.join(WEB_ROOT, 'pet.html'));   // 服务器起不来时退回 file://（立绘 / Live2D 模式仍可用）
  win.once('ready-to-show', () => win.show());

  // 每次载入都推一次，之后轮询
  win.webContents.on('did-finish-load', () => {
    lastRaw = '';          // 重新载入后强制重发
    setTimeout(pushState, 400);
  });
}

ipcMain.on('pet:quit', () => app.quit());

// 双击两次启动脚本只开一只
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady()
    .then(() => startWebServer().catch(() => 0))
    .then((port) => {
      createWindow(port);
      setInterval(pushState, 300);
    });
}

app.on('window-all-closed', () => app.quit());
