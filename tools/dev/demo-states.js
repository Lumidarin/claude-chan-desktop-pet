// Dev demo: cycle the pet through its states so each action set can be watched.
// Writes the same state.json the Claude Code hook writes (atomic rename). Ctrl-C to stop early.
//   node tools/dev/demo-states.js [seconds-per-state]
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');

const FILE = (process.env.CLAUDE_PET_STATE || '').trim() || path.join(os.homedir(), '.claude', 'pet', 'state.json');
const SEC = Number(process.argv[2]) || 15;
const STEPS = [
  ['reading',   '正在读 pet.html（演示：看书）'],
  ['writing',   '正在写 rig-driver.js（演示：写作）'],
  ['thinking',  '收到，正在想…（演示：沉思）'],
  ['searching', '正在查：Live2D 教程（演示：查资料）'],
  ['done',      '这一轮完成了（演示：完成）'],
  ['idle',      '我在这儿，开工的时候叫我。（演示：待机）']
];

function write(status, bubble, progress) {
  const now = Date.now();
  const tmp = FILE + '.' + process.pid + '.tmp';
  fs.mkdirSync(path.dirname(FILE), { recursive: true });
  fs.writeFileSync(tmp, JSON.stringify({ title: 'Claude', bubble, status, progress, tool: 'demo', ts: now, turnStart: now }));
  fs.renameSync(tmp, FILE);
}

let i = 0;
(function next() {
  if (i >= STEPS.length) { console.log('演示结束'); return; }
  const [status, bubble] = STEPS[i];
  console.log(`[${i + 1}/${STEPS.length}] ${status}  ${SEC}s`);
  write(status, bubble, status === 'done' ? 1 : (i + 1) / STEPS.length);
  i++;
  setTimeout(next, SEC * 1000);
})();
