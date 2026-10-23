#!/usr/bin/env node
// ============================================================
//  Claude Code hook → 桌宠状态文件
//
//  Claude Code 每个 hook 事件都会把一段 JSON 从 stdin 传进来。这里把它翻译成
//  桌宠能懂的 { title, bubble, status, progress, tool, ts, turnStart }，
//  原子写入 $CLAUDE_PET_STATE（默认 %USERPROFILE%\.claude\pet\state.json）。
//
//  铁律：永远 exit 0、永远不往 stdout/stderr 输出任何东西。
//  hook 的输出会被 Claude Code 当成反馈塞回对话，非 0 退出码还可能挡住工具调用；
//  桌宠只是旁观者，出任何错都必须悄悄吞掉。
//
//  跨调用的计数（连续成功 / 同一工具连续失败 / 本轮开始时间）存在同目录 hook-mem.json。
// ============================================================
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

const PET_DIR = path.join(os.homedir(), '.claude', 'pet');
const STATE_FILE = (process.env.CLAUDE_PET_STATE || '').trim() || path.join(PET_DIR, 'state.json');
const MEM_FILE = path.join(path.dirname(STATE_FILE), 'hook-mem.json');
const TITLE = 'Claude';

const PROUD_STREAK = 3;     // 连续成功几次算“很顺利”
const STRUGGLE_FAILS = 2;   // 同一工具连错几次算“不太顺”

function finish() { process.exit(0); }
process.on('uncaughtException', finish);
setTimeout(finish, 3000).unref();   // stdin 迟迟不结束也别卡住 Claude Code

function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (e) { return fallback; }
}

// 先写临时文件再改名：桌宠轮询时永远读不到写了一半的 JSON
function writeAtomic(file, obj) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = file + '.' + process.pid + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(obj), 'utf8');
  fs.renameSync(tmp, file);
}

function loadToolMap() {
  const map = readJson(path.join(__dirname, 'tool-map.json'), {});
  const byTool = {};
  Object.keys(map).forEach((status) => {
    if (Array.isArray(map[status])) map[status].forEach((t) => { byTool[t] = status; });
  });
  return byTool;
}

function clip(s, n) {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function fileName(input) {
  const p = input.file_path || input.notebook_path || input.path || '';
  return p ? path.basename(String(p)) : clip(input.pattern || '', 30);
}

function hostOf(url) {
  try { return new URL(url).hostname; } catch (e) { return clip(url, 30); }
}

function preToolBubble(status, tool, input) {
  switch (status) {
    case 'reading':    return '正在读 ' + (fileName(input) || '文件');
    case 'writing':    return '正在写 ' + (fileName(input) || '文件');
    case 'running':    return '正在跑命令：' + clip(input.command || input.description || tool, 40);
    case 'searching':  return '正在查：' + (input.query ? clip(input.query, 30) : hostOf(input.url || ''));
    case 'delegating': return '派了个帮手：' + clip(input.description || input.subagent_type || '', 30);
    case 'planning':   return '正在列计划';
    case 'waiting':    return '有事想问你';
    default:
      // mcp__server__tool → tool，名字太长气泡放不下
      return '正在用 ' + (tool.startsWith('mcp__') ? tool.split('__').pop() : tool);
  }
}

// PostToolUse 里判断“这次其实失败了”：不同工具的返回格式不一样，能认的都认
function looksFailed(resp) {
  if (!resp) return false;
  if (typeof resp === 'string') return /^(error|failed)\b/i.test(resp.trim());
  if (resp.is_error === true || resp.isError === true || resp.success === false) return true;
  if (resp.error) return true;
  if (typeof resp.exitCode === 'number' && resp.exitCode !== 0) return true;
  return false;
}

function handle(ev) {
  const now = Date.now();
  const name = ev.hook_event_name || '';
  const tool = ev.tool_name || '';
  const input = ev.tool_input || {};
  const mem = readJson(MEM_FILE, {});
  const prev = readJson(STATE_FILE, {});
  let turnStart = mem.turnStart || prev.turnStart || 0;
  let status = null, bubble = '', progress = typeof prev.progress === 'number' ? prev.progress : 0;

  switch (name) {
    case 'SessionStart':
      status = 'idle'; bubble = '我在这儿，开工的时候叫我。'; progress = 0;
      Object.assign(mem, { okStreak: 0, failTool: '', failCount: 0, tools: 0 });
      break;
    case 'UserPromptSubmit':
      status = 'thinking'; bubble = '收到，正在想…'; progress = 0.05;
      turnStart = now;
      Object.assign(mem, { okStreak: 0, failTool: '', failCount: 0, tools: 0 });
      break;
    case 'PreToolUse': {
      status = loadToolMap()[tool] || 'working';
      bubble = preToolBubble(status, tool, input);
      mem.tools = (mem.tools || 0) + 1;
      progress = Math.round(Math.min(0.9, 0.1 + 0.04 * mem.tools) * 100) / 100;   // 只是个大概，让进度条动起来
      break;
    }
    case 'PostToolUse':
    case 'PostToolUseFailure': {
      const failed = name === 'PostToolUseFailure' || looksFailed(ev.tool_response);
      if (failed) {
        mem.okStreak = 0;
        mem.failCount = mem.failTool === tool ? (mem.failCount || 0) + 1 : 1;
        mem.failTool = tool;
        if (mem.failCount >= STRUGGLE_FAILS) { status = 'struggling'; bubble = '这一步不太顺…'; }
      } else {
        mem.failTool = ''; mem.failCount = 0;
        mem.okStreak = (mem.okStreak || 0) + 1;
        // 正好第 3 次时亮一下，下一个 PreToolUse 自然覆盖掉
        if (mem.okStreak === PROUD_STREAK) { status = 'proud'; bubble = '很顺利'; }
      }
      break;
    }
    case 'Notification':
      status = 'waiting'; bubble = clip(ev.message || '有事想问你', 40);
      break;
    case 'Stop':
      status = 'done'; bubble = '这一轮完成了'; progress = 1;
      break;
    case 'PreCompact':
      status = 'working'; bubble = '整理一下记忆…';
      break;
    case 'SessionEnd':
      status = 'idle'; bubble = ''; progress = 0; turnStart = 0;
      break;
  }

  mem.turnStart = turnStart;
  try { writeAtomic(MEM_FILE, mem); } catch (e) { /* 计数丢了也无所谓 */ }
  if (!status) return;   // 普通的成功 PostToolUse：不改状态，只更新计数

  const next = { title: TITLE, bubble, status, progress, tool, ts: now, turnStart };
  // 去重：和上一次完全一样且 2 秒内，就不写（Read 连读同一个文件时不刷屏）
  if (prev.status === next.status && prev.bubble === next.bubble && prev.tool === next.tool &&
      now - (prev.ts || 0) < 2000) return;
  writeAtomic(STATE_FILE, next);
}

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  // 去掉 BOM：从 PowerShell 管道手动测试时会带上
  try { handle(JSON.parse(raw.replace(/^﻿/, '') || '{}')); } catch (e) { /* 吞掉 */ }
  finish();
});
process.stdin.on('error', finish);
