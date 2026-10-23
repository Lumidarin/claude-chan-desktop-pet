#!/usr/bin/env node
// ============================================================
//  把桌宠的 hook 合并进 Claude Code 的用户配置 %USERPROFILE%\.claude\settings.json
//
//    node install-hooks.js              安装（重复运行不会装两份）
//    node install-hooks.js --uninstall  卸载（只删命令里含 pet-hook.js 的条目）
//
//  改之前先把原文件备份成 settings.json.bak-<时间>；其他 hook 和设置原样保留。
// ============================================================
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

const SETTINGS = path.join(os.homedir(), '.claude', 'settings.json');
const HOOK = path.join(__dirname, 'pet-hook.js').replace(/\\/g, '/');
const MARK = 'pet-hook.js';
const COMMAND = 'node "' + HOOK + '"';

// 带 matcher 的是工具类事件，"*" = 所有工具
const EVENTS = {
  SessionStart: null,
  UserPromptSubmit: null,
  PreToolUse: '*',
  PostToolUse: '*',
  PostToolUseFailure: '*',
  Notification: null,
  Stop: null,
  PreCompact: null,
  SessionEnd: null
};

const uninstall = process.argv.includes('--uninstall');

let settings = {};
if (fs.existsSync(SETTINGS)) {
  const text = fs.readFileSync(SETTINGS, 'utf8');
  try {
    settings = text.trim() ? JSON.parse(text) : {};
  } catch (e) {
    console.error('settings.json 不是合法 JSON，没有改动它：' + SETTINGS);
    process.exit(1);
  }
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  fs.copyFileSync(SETTINGS, SETTINGS + '.bak-' + stamp);
  console.log('已备份：' + SETTINGS + '.bak-' + stamp);
}

const hooks = settings.hooks || {};

// 先把旧的桌宠条目全部拿掉（装、卸都一样），再按需加回去 → 天然去重
let removed = 0;
Object.keys(hooks).forEach((ev) => {
  hooks[ev] = (hooks[ev] || []).map((group) => {
    const kept = (group.hooks || []).filter((h) => !(h.command || '').includes(MARK));
    removed += (group.hooks || []).length - kept.length;
    return Object.assign({}, group, { hooks: kept });
  }).filter((group) => group.hooks.length > 0);
  if (hooks[ev].length === 0) delete hooks[ev];
});

if (!uninstall) {
  Object.keys(EVENTS).forEach((ev) => {
    const group = { hooks: [{ type: 'command', command: COMMAND, timeout: 5 }] };
    if (EVENTS[ev]) group.matcher = EVENTS[ev];
    (hooks[ev] = hooks[ev] || []).push(group);
  });
}

if (Object.keys(hooks).length) settings.hooks = hooks; else delete settings.hooks;
fs.mkdirSync(path.dirname(SETTINGS), { recursive: true });
fs.writeFileSync(SETTINGS, JSON.stringify(settings, null, 2) + '\n', 'utf8');

if (uninstall) console.log('已卸载桌宠 hook（删除 ' + removed + ' 条）。');
else console.log('已安装桌宠 hook：' + Object.keys(EVENTS).length + ' 个事件 → ' + COMMAND);
console.log('新开的 Claude Code 会话生效。');
