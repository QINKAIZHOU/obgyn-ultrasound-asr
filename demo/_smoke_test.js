// panel.js 冒烟测试：极简 DOM 桩 + 真实 demo_data.js，跑通全部 10 个渲染器与同步逻辑
// 运行: node demo/_smoke_test.js
"use strict";
const fs = require("fs");

global.window = {};
eval(fs.readFileSync("demo/demo_data.js", "utf8"));
if (!window.DEMO_DATA) throw new Error("demo_data.js 未定义 window.DEMO_DATA");

/* ---------- DOM 桩 ---------- */
function classListStub() {
  const s = new Set();
  return {
    add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c),
    toggle(c, f) { if (f === undefined) { s.has(c) ? s.delete(c) : s.add(c); } else { f ? s.add(c) : s.delete(c); } },
  };
}
function makeEl(tag) {
  return {
    tagName: (tag || "div").toUpperCase(), children: [], style: {}, dataset: {},
    classList: classListStub(), innerHTML: "", textContent: "", value: "1",
    scrollTop: 0, scrollHeight: 300, parentNode: null,
    setAttribute() {}, getAttribute: () => null, appendChild(c) { this.children.push(c); },
    addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    closest: () => null, scrollIntoView() {}, getBBox: () => ({ x: 0, y: 0, width: 100, height: 40 }),
    onclick: null, onplay: null, onpause: null, ontimeupdate: null, onended: null,
    paused: true, currentTime: 0, duration: 329, playbackRate: 1,
    play: async () => {}, pause: () => {},
  };
}
const byId = new Map();
const audioEl = makeEl("audio");
global.document = {
  readyState: "complete",
  head: makeEl("head"),
  getElementById: id => {
    if (id === "dp-style") return byId.get("dp-style") || null;   // 样式标签由 mount 创建
    if (!byId.has(id)) byId.set(id, makeEl());
    return byId.get(id);
  },
  createElement: tag => makeEl(tag),
  addEventListener() {}, removeEventListener() {},
  querySelectorAll: () => [],
};

const bySel = new Map();
function makeRoot() {
  const root = makeEl("div");
  root.querySelector = sel => {
    if (sel === "audio") return audioEl;
    if (!bySel.has(sel)) bySel.set(sel, makeEl());
    return bySel.get(sel);
  };
  return root;
}

/* ---------- 挂载并驱动 ---------- */
eval(fs.readFileSync("demo/panel.js", "utf8"));
if (!window.DemoPanel) throw new Error("panel.js 未定义 window.DemoPanel");

const container = makeRoot();
const activeSteps = [];
const panel = window.DemoPanel.mount(container, {
  audioPath: "../data/0911-案例/2026-07-20-15-12-39.wav",
  onActiveNode: i => activeSteps.push(i),
});

for (let i = 0; i < 10; i++) panel.goto(i);
console.log("步骤 1-10 渲染无异常；onActiveNode 调用", activeSteps.length, "次");

/* 第 7 步过滤器按钮路径（closest 桩返回 null 即安全跳过） */
panel.goto(6);

/* ---------- 同步识别逻辑（currentTime 驱动） ---------- */
panel.goto(3);                                  // audio.currentTime=0 且 paused → 全量显示
audioEl.paused = false;
audioEl.currentTime = 100;
panel.goto(3);                                  // currentTime>0 → 同步模式
const vis = () => [...byId.keys()].filter(id => /^dp-sn\d+$/.test(id)
  && byId.get(id).style.display === "flex").length;
const v100 = vis();
audioEl.ontimeupdate();                         // t=100s
const v100b = vis();
audioEl.currentTime = 200; audioEl.ontimeupdate();
const v200 = vis();
audioEl.currentTime = 30; audioEl.ontimeupdate();
const v30 = vis();
console.log(`可见句数: t=100s→${v100}/${v100b}  t=200s→${v200}  回退t=30s→${v30}`);
if (!(v100 > 0 && v200 > v100 && v30 < v100)) throw new Error("同步显现逻辑不符合预期");

/* ---------- 开合控制 ---------- */
panel.open(); panel.close(); panel.open();
console.log("SMOKE_OK");
