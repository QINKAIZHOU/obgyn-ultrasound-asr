/* AI 超声语音助手 · 分步演示面板（宿主无关，注入 archify 流程图页使用）
 *
 * 用法：
 *   const panel = DemoPanel.mount(containerEl, {
 *     audioPath: "../data/0911-案例/xxx.wav",   // 相对于页面的音频路径
 *     onActiveNode: (stepIndex | null) => {},    // 演示推进回调（宿主用于点亮流程图节点）
 *   });
 *   panel.goto(3);          // 打开第 4 步
 *   panel.startShow();      // 自动演示（播放音频同步识别 → 后续步骤自动推进）
 *   panel.open()/close();   // 面板显示/隐藏
 *
 * 数据：window.DEMO_DATA（collect_demo.py 生成）
 * 样式：mount 时注入一次 <style>，全部类名 dp- 前缀，不污染宿主 viewer
 */
"use strict";
(function () {
  const DATA = window.DEMO_DATA;

  const STEPS = [
    { t: "① 语音输入",        sub: "医生对着工作站麦克风口述检查所见与诊断", branch: false },
    { t: "② 语音指令·指定模板", sub: "自然语言切换模板，系统加载对应报告骨架", branch: false },
    { t: "③ 声纹识别",        sub: "识别前确认说话医生身份，绑定书写权限", branch: true },
    { t: "④ 实时语音转写",     sub: "SeACo-Paraformer 非自回归模型，边说边出字（与音频同步）", branch: false },
    { t: "⑤ 医疗热词库",      sub: "999 条专科热词做解码偏置，从源头减少同音错字", branch: false },
    { t: "⑥ LLM 术语纠正",    sub: "大模型把口语化表达、同音误识纠正为规范术语", branch: false },
    { t: "⑦ 报告内容提取",     sub: "剔除闲聊与指示，只保留报告成分", branch: false },
    { t: "⑧ 填充报告模板",     sub: "结构化内容按妇科超声模板分节落位", branch: false },
    { t: "⑨ 接入电子病历 EMR", sub: "调取患者既往史与 PACS 影像回填", branch: true },
    { t: "⑩ 生成结构化报告",   sub: "可直接签发的报告，并与实际报告比对", branch: false },
  ];

  const CSS = `
  .dp-root { --blue:#1a66c2; --blue-dk:#0e4a94; --blue-bg:#eaf2fc; --green:#1e9e63; --green-bg:#e7f6ee;
    --red:#d5493f; --red-bg:#fdeceb; --amber:#b97a12; --amber-bg:#fdf4e3;
    --gray:#6b7686; --line:#dde4ee; background:#fff; color:#22293a; font-size:15px;
    font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;
    display:flex; flex-direction:column; height:100%; }
  .dp-root * { box-sizing:border-box; margin:0; padding:0; }
  .dp-head { padding:12px 16px 6px; }
  .dp-title { font-size:18px; color:var(--blue-dk); display:inline; }
  .dp-sub { font-size:12.5px; color:var(--gray); margin-left:10px; }
  .dp-body { flex:1; overflow-y:auto; padding:4px 16px 10px; min-height:0; }
  .dp-body::-webkit-scrollbar { width:8px; } .dp-body::-webkit-scrollbar-thumb { background:#ccd6e4; border-radius:4px; }
  .dp-card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:12px 14px; margin-bottom:10px; box-shadow:0 1px 3px rgba(20,40,80,.05); }
  .dp-card h4 { font-size:13.5px; color:var(--blue-dk); margin-bottom:8px; }
  .dp-note { font-size:12px; color:var(--amber); background:var(--amber-bg); border-radius:6px; padding:4px 10px; display:inline-block; margin-top:8px; }
  .dp-tip { font-size:12px; color:var(--gray); }
  .dp-kv { display:flex; gap:22px; flex-wrap:wrap; }
  .dp-kv .dp-item b { display:block; font-size:11.5px; color:var(--gray); font-weight:600; margin-bottom:2px; }
  .dp-kv .dp-item span { font-size:14.5px; }
  .dp-dock { display:flex; align-items:center; gap:10px; padding:8px 14px; border-top:1px solid var(--line); }
  .dp-dock.hidden { display:none; }
  .dp-dock button.dp-big { width:36px; height:36px; border-radius:50%; border:none; background:var(--blue); color:#fff; font-size:14px; cursor:pointer; flex:none; }
  .dp-dock button.dp-big:hover { background:var(--blue-dk); }
  .dp-dock .dp-time { font-variant-numeric:tabular-nums; font-size:12.5px; color:var(--gray); flex:none; }
  .dp-dock input[type=range] { flex:1; accent-color:var(--blue); min-width:60px; }
  .dp-dock select { border:1px solid var(--line); border-radius:6px; padding:3px 5px; font-size:12.5px; }
  .dp-dock .dp-skip { border:1px solid var(--line); background:#fff; color:var(--gray); border-radius:6px; padding:4px 10px; font-size:12.5px; cursor:pointer; }
  .dp-sent { display:flex; gap:9px; padding:6px 9px; border-radius:8px; align-items:baseline; border:1px solid transparent; }
  .dp-sent:hover { background:var(--blue-bg); }
  .dp-sent .dp-ts { font-variant-numeric:tabular-nums; font-size:11.5px; color:var(--gray); flex:none; width:58px; }
  .dp-sent .dp-play { border:1px solid var(--line); background:#fff; border-radius:50%; width:22px; height:22px; font-size:9px; color:var(--blue); cursor:pointer; flex:none; align-self:center; }
  .dp-sent .dp-play:hover { background:var(--blue); color:#fff; }
  .dp-sent .dp-txt { line-height:1.6; font-size:14px; overflow-wrap:anywhere; }
  .dp-sent.dim { opacity:.45; }
  .dp-sent.active { background:var(--blue-bg); border-color:#bcd2f0; }
  .dp-sent .dp-tag { font-size:11px; color:var(--gray); background:#eef1f6; border-radius:4px; padding:1px 6px; margin-left:8px; flex:none; }
  .dp-sent .dp-tag.dp-keep { color:var(--green); background:var(--green-bg); }
  .dp-arrow { color:var(--blue); font-weight:700; padding:0 5px; }
  .dp-root mark.dp-w { background:var(--red-bg); color:var(--red); border-radius:3px; padding:0 2px; text-decoration:line-through; }
  .dp-root mark.dp-r { background:var(--green-bg); color:var(--green); border-radius:3px; padding:0 2px; font-weight:600; }
  .dp-root mark.dp-hw { background:var(--red-bg); color:var(--red); border-radius:3px; padding:0 2px; font-weight:600; }
  .dp-sent .dp-col { flex:1; min-width:0; }
  .dp-proc { font-size:12px; color:var(--gray); line-height:1.5; }
  .dp-proc del { color:var(--red); margin-right:4px; }
  .dp-res { margin-top:2px; display:flex; align-items:baseline; gap:6px; flex-wrap:wrap; }
  .dp-chips { display:flex; flex-wrap:wrap; gap:7px; }
  .dp-chip { background:var(--blue-bg); color:var(--blue-dk); border-radius:14px; padding:3px 11px; font-size:13px; }
  .dp-chip b { font-size:11.5px; color:var(--gray); font-weight:400; margin-left:3px; }
  .dp-chip.dp-fix { background:var(--red-bg); color:var(--red); }
  .dp-filters { display:flex; gap:8px; margin-bottom:10px; }
  .dp-filters button { border:1px solid var(--line); background:#fff; border-radius:14px; padding:2px 13px; font-size:12.5px; color:var(--gray); cursor:pointer; }
  .dp-filters button.on { background:var(--blue); border-color:var(--blue); color:#fff; }
  .dp-form { background:#fff; border:1px solid var(--line); border-radius:12px; padding:12px 16px; }
  .dp-form .dp-row { font-size:14px; line-height:1.95; padding:0 8px; border-left:3px solid transparent; overflow-wrap:anywhere; }
  .dp-form .dp-row.dp-filled { border-left-color:var(--green); color:#223349; }
  .dp-form .dp-row.dp-filled b { color:var(--green); }
  .dp-form .dp-row.dp-omit { color:#a5aeba; }
  .dp-form .dp-row.dp-head { font-weight:700; margin-top:5px; }
  .dp-form .dp-row.dp-head.dp-filled { color:var(--blue-dk); border-left-color:var(--blue); }
  .dp-form .dp-row.dp-extra { border-left-color:var(--blue); color:#223349; }
  .dp-form .dp-row.dp-extra::before { content:"＋"; color:var(--blue); font-weight:700; margin-right:4px; }
  .dp-fake { display:flex; gap:13px; align-items:center; }
  .dp-fake .dp-avatar { width:48px; height:48px; border-radius:50%; background:linear-gradient(135deg,var(--blue),#6ea3e8); color:#fff; display:flex; align-items:center; justify-content:center; font-size:20px; flex:none; }
  .dp-fake .dp-info b { font-size:15px; }
  .dp-fake .dp-info div { font-size:12.5px; color:var(--gray); margin-top:3px; }
  .dp-meter { height:7px; background:#e7ecf4; border-radius:4px; overflow:hidden; margin-top:6px; width:190px; }
  .dp-meter i { display:block; height:100%; background:var(--green); }
  .dp-cmp { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .dp-cmp .dp-col h5 { font-size:12.5px; margin-bottom:5px; color:var(--gray); }
  .dp-cmp .dp-col.dp-golden h5 { color:var(--red); }
  .dp-cmp .dp-col.dp-ours h5 { color:var(--green); }
  .dp-cmp .dp-txtbox { background:#fbfcfe; border:1px solid var(--line); border-radius:10px; padding:10px 12px; font-size:12.5px; line-height:1.75; white-space:pre-wrap; overflow-wrap:anywhere; }
  .dp-cmp del { background:var(--red-bg); color:var(--red); text-decoration:line-through; border-radius:3px; padding:0 1px; }
  .dp-cmp ins { background:var(--green-bg); color:var(--green); text-decoration:none; border-radius:3px; padding:0 1px; font-weight:600; }
  .dp-metrics { display:flex; flex-wrap:wrap; gap:8px; }
  .dp-metrics .dp-m { background:#fff; border:1px solid var(--line); border-radius:10px; padding:6px 12px; min-width:110px; }
  .dp-metrics .dp-m b { display:block; font-size:18px; color:var(--blue-dk); }
  .dp-metrics .dp-m span { font-size:11.5px; color:var(--gray); }
  .dp-metrics .dp-m small { display:block; font-size:11px; color:#96a1b2; margin-top:1px; }
  .dp-report { white-space:pre-wrap; font-size:13.5px; line-height:1.85; overflow-wrap:anywhere; }
  .dp-controls { display:flex; align-items:center; gap:8px; border-top:1px solid var(--line); padding:9px 14px; }
  .dp-controls button { border:1px solid var(--line); background:#fff; border-radius:8px; padding:6px 14px; font-size:13px; cursor:pointer; color:#333; }
  .dp-controls button:hover { border-color:var(--blue); color:var(--blue); }
  .dp-controls button.dp-primary { background:var(--blue); border-color:var(--blue); color:#fff; font-weight:600; }
  .dp-controls button.dp-primary:hover { background:var(--blue-dk); }
  .dp-controls .dp-pos { margin-left:auto; font-size:12px; color:var(--gray); }
  .dp-fade { animation:dpFadeUp .4s ease both; }
  @keyframes dpFadeUp { from { opacity:0; transform:translateY(7px); } to { opacity:1; transform:none; } }
  .dp-hidden { display:none !important; }
  `;

  function mount(container, opts) {
    opts = opts || {};
    /* 样式只注入一次 */
    if (!document.getElementById("dp-style")) {
      const st = document.createElement("style");
      st.id = "dp-style";
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    container.innerHTML = "";
    container.classList.add("dp-root");

    const root = container;
    root.innerHTML = `
      <div class="dp-head"><h3 class="dp-title"></h3><span class="dp-sub"></span></div>
      <div class="dp-body"></div>
      <div class="dp-dock dp-hidden">
        <button class="dp-big">▶</button>
        <span class="dp-time">00:00 / 00:00</span>
        <input type="range" min="0" max="1000" value="0">
        <select><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select>
        <button class="dp-skip">跳过音频 ▸</button>
      </div>
      <div class="dp-controls">
        <button class="dp-start dp-primary">▶ 开始演示</button>
        <button class="dp-prev">⟨</button>
        <button class="dp-next">⟩</button>
        <button class="dp-replay">重播本步</button>
        <span class="dp-pos"></span>
      </div>
      <audio preload="auto"></audio>`;

    const $ = sel => root.querySelector(sel);
    const body = $(".dp-body"), dock = $(".dp-dock"), audio = $("audio");
    audio.src = encodeURI(opts.audioPath || DATA.meta.audio_rel);

    let cur = 0, showMode = false, showTimers = [], fragStop = null, sentSync = false;

    /* ---------- 工具 ---------- */
    const fmt = ms => { const s = ms / 1000;
      return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(Math.floor(s % 60)).padStart(2, "0"); };
    const esc = s => (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const fmtAgo = sec => { sec = Math.max(0, sec);
      return String(Math.floor(sec / 60)).padStart(2, "0") + ":" + String(Math.floor(sec % 60)).padStart(2, "0"); };

    /* ---------- 音频坞 ---------- */
    $(".dp-big").onclick = () => { audio.paused ? audio.play() : audio.pause(); };
    audio.onplay = () => { $(".dp-big").textContent = "⏸"; };
    audio.onpause = () => { $(".dp-big").textContent = "▶"; };
    audio.ontimeupdate = () => {
      $(".dp-time").textContent = fmtAgo(audio.currentTime) + " / " + fmtAgo(audio.duration || DATA.meta.duration_sec);
      const bar = $(".dp-dock input");
      if (audio.duration) bar.value = Math.round(audio.currentTime / audio.duration * 1000);
      if (fragStop != null && audio.currentTime >= fragStop) { audio.pause(); fragStop = null; }
      if (sentSync && cur === 3) syncSentences();
    };
    $(".dp-dock input").oninput = e => { if (audio.duration) audio.currentTime = e.target.value / 1000 * audio.duration; };
    $(".dp-dock select").onchange = e => { audio.playbackRate = Number(e.target.value); };
    $(".dp-skip").onclick = () => { audio.pause(); if (showMode) phaseB(); };
    function showDock(v) { dock.classList.toggle("dp-hidden", !v); }

    /* ---------- 渲染器 ---------- */
    const RENDER = [];

    RENDER[0] = () => {                                   // ① 语音输入
      showDock(true); sentSync = false;
      const m = DATA.meta;
      body.innerHTML = `
        <div class="dp-card dp-fade"><h4>本次演示案例</h4>
          <div class="dp-kv">
            <div class="dp-item"><b>检查项目</b><span>${esc(m.item)}</span></div>
            <div class="dp-item"><b>检查时间</b><span>${esc(m.exam_time)}</span></div>
            <div class="dp-item"><b>音频时长</b><span>${m.duration_sec} 秒</span></div>
            <div class="dp-item"><b>检查医生</b><span>${esc(DATA.voiceprint.doctor)}</span></div>
          </div></div>
        <div class="dp-card dp-fade"><h4>发生了什么</h4>
          <p style="line-height:1.85">医生在超声检查过程中自然口述：既有<b>报告内容</b>（脏器大小、回声、测量数值、诊断提示），
          也混杂着大量对患者的指示与医患对话。整个检查过程的语音被工作站麦克风持续采集，送往院内语音识别服务。</p>
          <span class="dp-note">点击下方「▶ 开始演示」，或直接播放音频体验"同步识别"</span></div>`;
    };

    RENDER[1] = () => {                                   // ② 语音指令·指定模板
      showDock(true); sentSync = false;
      const vc = DATA.voice_command;
      body.innerHTML = `
        <div class="dp-card dp-fade"><h4>医生口述指令</h4>
          <p style="font-size:17px;line-height:1.7">「${esc(vc.asr_text)}」</p>
          ${vc.t0 != null ? `<p class="dp-tip" style="margin-top:6px">本段录音中的相关口述（ASR 原文，点击可听）：</p>
            <div class="dp-sent" style="margin-top:4px">
              <span class="dp-ts">${fmt(vc.t0)}</span>
              <button class="dp-play" data-frag="${vc.t0},${vc.t1}">▶</button>
              <span class="dp-txt">${esc(vc.raw_snippet)}</span>
            </div>` : ""}</div>
        <div class="dp-card dp-fade"><h4>系统响应 · 加载报告模板</h4>
          <div class="dp-kv"><div class="dp-item"><b>已加载模板</b><span>${esc(vc.template_name)}</span></div></div>
          <p class="dp-tip" style="margin-top:8px">模板定义报告骨架：${DATA.template_skeleton.map(esc).join(" / ")}，
          后续识别内容按此落位。</p></div>
        <span class="dp-note">示意环节：实际系统中由语音指令引擎实时检测模板切换词</span>`;
    };

    RENDER[2] = () => {                                   // ③ 声纹识别
      showDock(true); sentSync = false;
      const vp = DATA.voiceprint;
      body.innerHTML = `
        <div class="dp-card dp-fade"><div class="dp-fake">
          <div class="dp-avatar">🩺</div>
          <div class="dp-info">
            <b>${esc(vp.doctor)} · 声纹鉴权${vp.passed ? "通过 ✓" : "未通过"}</b>
            <div>声纹相似度 ${(vp.similarity * 100).toFixed(0)}%，书写权限已绑定</div>
            <div class="dp-meter"><i style="width:${vp.similarity * 100}%"></i></div>
          </div></div>
          <span class="dp-note">示意数据：实际系统中由声纹模型在识别前完成身份确认</span></div>`;
    };

    RENDER[3] = () => {                                   // ④ 实时语音转写（与音频同步）
      showDock(true);
      sentSync = !audio.paused || audio.currentTime > 0;
      body.innerHTML = `
        <div class="dp-card dp-fade"><h4>SeACo-Paraformer 实时转写（${DATA.sentences.length} 句）</h4>
          <p class="dp-tip">识别结果随医生讲话逐句浮现（token 级时间对齐）。点击 ▶ 回放任意一句；拖动进度条可跳转，转写随之同步。</p></div>
        <div id="dp-sent-list">${DATA.sentences.map(s => `
          <div class="dp-sent" id="dp-sn${s.i}" style="display:none">
            <span class="dp-ts">${s.t0 != null ? fmt(s.t0) : "--:--"}</span>
            ${s.t1 != null ? `<button class="dp-play" data-frag="${s.t0},${s.t1}">▶</button>` : ""}
            <span class="dp-txt">${esc(s.raw)}</span>
          </div>`).join("")}</div>`;
      if (sentSync) syncSentences(); else revealAll();
    };
    function revealAll() {
      body.querySelectorAll(".dp-sent[id^='dp-sn']").forEach(el => el.style.display = "flex");
    }
    function syncSentences() {                            // 浮现完全由 currentTime 驱动：拖动/倍速/回退自然同步
      const t = audio.currentTime * 1000;
      let last = -1;
      DATA.sentences.forEach(s => {
        const el = document.getElementById("dp-sn" + s.i);
        if (!el) return;
        const on = s.t0 != null && s.t0 <= t;
        el.style.display = on ? "flex" : "none";
        el.classList.remove("active");
        if (on) last = s.i;
      });
      if (last >= 0) {
        const el = document.getElementById("dp-sn" + last);
        el.classList.add("active");
        el.scrollIntoView({ block: "nearest" });
      }
    }
    root.addEventListener("click", e => {                 // 统一处理片段播放按钮
      const btn = e.target.closest("[data-frag]");
      if (!btn) return;
      const [t0, t1] = btn.dataset.frag.split(",").map(Number);
      audio.currentTime = t0 / 1000;
      fragStop = isNaN(t1) ? null : t1 / 1000;
      audio.play();
      audio.playbackRate = Number($(".dp-dock select").value);
      root.querySelectorAll("[data-frag]").forEach(b => { if (b !== btn) b.textContent = "▶"; });
      btn.textContent = "⏸";
    });

    RENDER[4] = () => {                                   // ⑤ 医疗热词库
      showDock(true); sentSync = false;
      const h = DATA.hotwords;
      const hl = (raw, word) => esc(raw).split(esc(word)).join(`<mark class="dp-hw">${esc(word)}</mark>`);
      const ctx = h.hits.map(x => ({
        word: x.word, count: x.count,
        rows: DATA.sentences.filter(s => s.raw.includes(x.word)).map(s => `
          <div class="dp-sent"><span class="dp-ts">${fmt(s.t0)}</span>
            ${s.t1 != null ? `<button class="dp-play" data-frag="${s.t0},${s.t1}">▶</button>` : ""}
            <span class="dp-txt">${hl(s.raw, x.word)}</span></div>`).join(""),
      }));
      const groups = ctx.filter(c => c.rows).map(c => `
        <div class="dp-card dp-fade"><h4>${esc(c.word)}
          <b style="color:var(--gray);font-weight:400;font-size:12.5px">×${c.count}</b></h4>${c.rows}</div>`).join("");
      const missing = ctx.filter(c => !c.rows)
        .map(c => `<span class="dp-chip">${esc(c.word)}<b>×${c.count}</b></span>`).join("");
      body.innerHTML = `
        <div class="dp-card dp-fade"><h4>热词偏置 · 本次命中 ${h.hits.length} 个</h4>
          <p style="line-height:1.85">系统内置 <b>${h.total}</b> 条超声/妇产科/乳腺专科热词，在识别解码阶段做语义偏置——
          「卵巢」「肌层」「宫腔」等术语即使发音模糊也能被优先召回，从<b>源头</b>减少同音错字。</p>
          <p class="dp-tip">下方按命中热词列出原始识别文字，点击 ▶ 可回放对应语音片段（热词标红）。</p>
          ${missing ? `<div class="dp-chips" style="margin-top:10px">${missing}</div>` : ""}</div>
        ${groups || "<div class='dp-card'><span class='dp-tip'>本段音频未命中热词上下文</span></div>"}`;
    };

    RENDER[5] = () => {                                   // ⑥ LLM 术语纠正
      showDock(true); sentSync = false;
      const corr = DATA.corrections;
      const chips = corr.slice(0, 20).map(c => `<span class="dp-chip dp-fix">${esc(c.wrong)} → ${esc(c.right)}<b>×${c.count}</b></span>`).join("");
      const rows = DATA.sentences.filter(s => s.optimized !== s.raw).map(s => {
        let rawHtml = esc(s.raw), optHtml = esc(s.optimized);
        if (s.diff && s.diff.length) {                    // 字级 diff 突出（collect_demo 预计算）
          s.diff.forEach(d => {
            if (d.a) rawHtml = rawHtml.split(esc(d.a)).join(`<mark class="dp-w">${esc(d.a)}</mark>`);
            if (d.b) optHtml = optHtml.split(esc(d.b)).join(`<mark class="dp-r">${esc(d.b)}</mark>`);
          });
        } else {                                          // 旧数据回退：纠错映射匹配
          const hit = corr.find(c => s.raw.includes(c.wrong));
          if (hit) {
            rawHtml = rawHtml.split(esc(hit.wrong)).join(`<mark class="dp-w">${esc(hit.wrong)}</mark>`);
            optHtml = optHtml.split(esc(hit.right)).join(`<mark class="dp-r">${esc(hit.right)}</mark>`);
          }
        }
        return `<div class="dp-sent dp-fade"><span class="dp-ts">${fmt(s.t0)}</span>
          ${s.t1 != null ? `<button class="dp-play" data-frag="${s.t0},${s.t1}">▶</button>` : ""}
          <span class="dp-txt">${rawHtml}<span class="dp-arrow">⇒</span>${optHtml}</span></div>`;
      }).join("");
      body.innerHTML = `
        <div class="dp-card dp-fade"><h4>术语纠正 · ${DATA.sentences.filter(s => s.optimized !== s.raw).length} 句被修改</h4>
          <p style="line-height:1.85">漏过热词层的同音错字（「前臂」应为<b>前壁</b>、「回升」应为<b>回声</b>这类需要上下文判断的错误），
          由本地大模型逐句纠正，且绝不改动数值与左右侧等关键信息。</p>
          <p class="dp-tip">红色删除线为原文、绿色为纠正后，点击 ▶ 可回放对应语音片段。</p>
          ${chips ? `<div class="dp-chips" style="margin-top:10px">${chips}</div>` : ""}</div>
        ${rows || "<div class='dp-card'><span class='dp-tip'>本段音频无需要纠正的句子</span></div>"}`;
    };

    RENDER[6] = () => {                                   // ⑦ 报告内容提取
      showDock(true); sentSync = false;
      const items = DATA.report_items;
      const nKeep = items.filter(s => s.is_report).length;
      const rows = items.map(s => {
        const cls = DATA.sentences.filter(c => c.si === s.i);
        const raw = cls.map(c => c.raw).join("");
        const opt = cls.map(c => c.optimized).join("");
        const corrected = opt !== raw;
        const lastT1 = cls.length && cls[cls.length - 1].t1 != null ? cls[cls.length - 1].t1 : null;
        const proc = corrected
          ? `<del>${esc(raw)}</del>⇒ ${esc(opt)}`
          : esc(raw);
        return `<div class="dp-sent ${s.is_report ? "" : "dim"} dp-fade">
          <span class="dp-ts">${fmt(s.t0)}</span>
          ${lastT1 != null ? `<button class="dp-play" data-frag="${s.t0},${lastT1}">▶</button>` : ""}
          <div class="dp-col">
            <div class="dp-proc">${proc}</div>
            <div class="dp-res">${s.is_report
              ? `<span class="dp-tag dp-keep">进入报告</span><span class="dp-txt"><b>${esc(s.enhanced)}</b></span>`
              : `<span class="dp-tag">【非报告内容】已剔除</span>`}</div>
          </div></div>`;
      }).join("");
      body.innerHTML = `
        <div class="dp-card dp-fade"><h4>报告内容提取 · ${nKeep} / ${items.length} 句进入报告</h4>
          <p style="line-height:1.85">全链路结果汇聚于此：<b>识别 ${DATA.sentences.length} 短句</b>合并成 ${items.length} 句 →
          <b>LLM 术语纠正</b>（红划线为识别原文，⇒ 后为纠正结果）→
          <b>LLM 内容提取</b>：报告成分（含残缺的测量报读）保留为规范的提取文本，闲聊、对患者的指示与杂音全部剔除。</p></div>
        <div class="dp-filters">
          <button class="on" data-f="all">全部</button>
          <button data-f="keep">仅报告内容</button>
          <button data-f="drop">仅剔除项</button>
        </div>
        <div id="dp-sent-list">${rows}</div>`;
    };
    body.addEventListener("click", e => {                 // 第 7 步过滤器
      const btn = e.target.closest("[data-f]");
      if (!btn) return;
      btn.parentElement.querySelectorAll("button").forEach(b => b.classList.remove("on"));
      btn.classList.add("on");
      const mode = btn.dataset.f;
      body.querySelectorAll("#dp-sent-list .dp-sent").forEach((el, i) => {
        el.style.display = mode === "all" || (mode === "keep") === DATA.report_items[i].is_report ? "flex" : "none";
      });
    });

    RENDER[7] = () => {                                   // ⑧ 填充报告模板
      showDock(false); sentSync = false;
      const sections = {};
      let curSec = null;
      (DATA.report.final || "").split("\n").forEach(ln => {
        const t = ln.trim();
        if (!t) return;
        const m = t.match(/^【(子宫|附件|盆腔积液|超声提示)/);
        if (m) { curSec = m[1]; sections[curSec] = sections[curSec] || []; }
        if (curSec) sections[curSec].push(t);
      });
      const pull = (sec, prefix) => {
        const hit = (sections[sec] || []).find(l => l.startsWith(prefix));
        return hit ? hit.slice(prefix.length).replace(/^[：:]\s*/, "") : null;
      };
      const rest = sec => (sections[sec] || []).filter(l =>
        !/^【/.test(l) && !["子宫位置", "子宫形态", "右卵巢", "左卵巢"].some(p => l.startsWith(p)));
      const row = (label, val, cls) =>
        `<div class="dp-row ${cls || (val != null ? "dp-filled" : "dp-omit")}"><b>${esc(label)}</b>` +
        (val != null ? esc(val) : "（口述中未提及，省略）") + "</div>";
      const zi = sections["子宫"], fu = sections["附件"], pj = sections["盆腔积液"];
      let html = `<div class="dp-form">`;
      html += row("【子宫】【经阴道】", zi ? "" : null, zi ? "dp-head dp-filled" : "dp-head dp-omit");
      if (zi) {
        html += row("子宫位置：", pull("子宫", "子宫位置"));
        html += row("子宫形态：", pull("子宫", "子宫形态"));
        rest("子宫").forEach(l => html += `<div class="dp-row dp-extra">${esc(l)}</div>`);
      } else html += row("子宫位置：", null) + row("子宫形态：", null);
      html += row("【附件】", fu ? "" : null, fu ? "dp-head dp-filled" : "dp-head dp-omit");
      if (fu) {
        html += row("右卵巢：", pull("附件", "右卵巢"));
        html += row("左卵巢：", pull("附件", "左卵巢"));
        rest("附件").forEach(l => html += `<div class="dp-row dp-extra">${esc(l)}</div>`);
      } else html += row("右卵巢：", null) + row("左卵巢：", null);
      html += row("【盆腔积液】：", pj ? (pull("盆腔积液", "【盆腔积液】") ?? "") : null, pj ? "dp-filled" : "dp-omit");
      const tip = sections["超声提示"];
      if (tip && tip.length) html += row("【超声提示】", tip.slice(1).join(" ") || tip[0], "dp-head dp-filled");
      html += `</div>`;
      body.innerHTML = `
        <div class="dp-card dp-fade"><h4>模板落位 · ${esc(DATA.meta.template_name)}</h4>
          <p style="line-height:1.85">提取的报告内容按医院报告模板逐项落位（<b style="color:var(--green)">绿</b>=已填充，
          <b style="color:var(--blue)">蓝</b>=模板外补充内容）；<b>未口述的项目一律省略，绝不按模板补写默认值</b>。</p></div>
        ${html}`;
    };

    RENDER[8] = () => {                                   // ⑨ 接入 EMR
      showDock(false); sentSync = false;
      const e = DATA.emr;
      body.innerHTML = `
        <div class="dp-card dp-fade"><div class="dp-fake">
          <div class="dp-avatar">📋</div>
          <div class="dp-info"><b>患者 ${esc(e.patient)} · 检查号 ${esc(e.exam_no)}</b>
            <div>${esc(e.history)}</div><div>${esc(e.images)}</div></div></div>
          <p class="dp-tip" style="margin-top:10px">报告生成时自动调取既往史与影像上下文，辅助医生核对，减少漏项。</p>
          <span class="dp-note">示意数据：实际系统通过院内内网对接 EMR / PACS，数据不出公网</span></div>`;
    };

    RENDER[9] = () => {                                   // ⑩ 生成结构化报告 + 比对
      showDock(false); sentSync = false;
      stopShow();
      const m = DATA.metrics, g = DATA.golden;
      let gold = "", ours = "";
      DATA.diff.forEach(d => {
        if (d.op === "=") { gold += esc(d.text); ours += esc(d.text); }
        else if (d.op === "-") gold += `<del>${esc(d.text)}</del>`;
        else ours += `<ins>${esc(d.text)}</ins>`;
      });
      const pct = x => (x * 100).toFixed(0) + "%";
      body.innerHTML = `
        <div class="dp-card dp-fade"><h4>最终结构化报告（可直接签发）</h4>
          <pre class="dp-report">${esc(DATA.report.final)}</pre></div>
        <div class="dp-card dp-fade"><h4>与实际报告（医生签发金标准）逐字比对</h4>
          <div class="dp-cmp">
            <div class="dp-col dp-golden"><h5>实际报告（金标准）<span class="dp-tip">｜红=AI 报告缺失</span></h5><div class="dp-txtbox">${gold}</div></div>
            <div class="dp-col dp-ours"><h5>AI 生成报告<span class="dp-tip">｜绿=AI 多写</span></h5><div class="dp-txtbox">${ours}</div></div>
          </div></div>
        <div class="dp-card dp-fade"><h4>量化指标（口径同金标准评测）</h4>
          <div class="dp-metrics">
            <div class="dp-m"><b>${m.cer_ours.toFixed(2)}</b><span>报告字符错误率 CER ↓</span><small>基线系统 ${m.cer_baseline.toFixed(2)}</small></div>
            <div class="dp-m"><b>${pct(m.meas_recovery_ours)}</b><span>测量值还原率 ↑</span><small>基线 ${pct(m.meas_recovery_baseline)}</small></div>
            <div class="dp-m"><b>${m.halluc_ours.length}</b><span>幻觉数值 ↓</span><small>基线 ${m.halluc_baseline.length}</small></div>
            <div class="dp-m"><b>${pct(m.key_items_ours)}</b><span>模板关键项覆盖 ↑</span><small>基线 ${pct(m.key_items_baseline)}</small></div>
            <div class="dp-m"><b>${pct(m.concl_ours)}</b><span>结论词覆盖 ↑</span><small>基线 ${pct(m.concl_baseline)}</small></div>
            <div class="dp-m"><b>${m.asr_bad_ours}</b><span>ASR 已知错字 ↓</span><small>基线 ${m.asr_bad_baseline}</small></div>
          </div>
          <p class="dp-tip" style="margin-top:10px">CER 为相对比较：金标准是医生签发终稿措辞，与检查中的实时口述存在合理差异；
          测量值还原率衡量口述数值被完整保留进报告的比例。</p></div>`;
    };

    /* ---------- 步骤切换与自动演示 ---------- */
    function goto(i) {
      cur = Math.max(0, Math.min(STEPS.length - 1, i));
      $(".dp-title").textContent = STEPS[cur].t;
      $(".dp-sub").textContent = STEPS[cur].sub;
      $(".dp-pos").textContent = `步骤 ${cur + 1} / ${STEPS.length}`;
      RENDER[cur]();
      body.scrollTop = 0;
      if (opts.onActiveNode) opts.onActiveNode(cur);
    }
    const later = (ms, fn) => showTimers.push(setTimeout(() => { if (showMode) fn(); }, ms));
    function startShow() {                                // 阶段 A：播放音频同步识别；阶段 B：后续步骤自动推进
      stopShow();
      showMode = true;
      $(".dp-start").textContent = "⏸ 暂停演示";
      goto(0);
      audio.playbackRate = Number($(".dp-dock select").value);
      audio.play().catch(() => {});
      later(2500, () => goto(1));
      later(5000, () => goto(2));
      later(7000, () => { goto(3); sentSync = true; });
    }
    function phaseB() {
      sentSync = false;
      let i = 4;
      const advance = () => {
        if (!showMode) return;
        if (i >= STEPS.length) { showMode = false; $(".dp-start").textContent = "▶ 重新演示"; if (opts.onActiveNode) opts.onActiveNode(null); return; }
        goto(i++);
        later(3500 + Math.min(body.scrollHeight, 900), advance);
      };
      advance();
    }
    function stopShow() {
      showTimers.forEach(clearTimeout);
      showTimers = [];
      if (showMode) { showMode = false; $(".dp-start").textContent = "▶ 开始演示"; }
    }
    $(".dp-start").onclick = () => { showMode ? stopShow() : startShow(); };
    $(".dp-next").onclick = () => { stopShow(); if (cur < STEPS.length - 1) goto(cur + 1); };
    $(".dp-prev").onclick = () => { stopShow(); if (cur > 0) goto(cur - 1); };
    $(".dp-replay").onclick = () => { stopShow(); goto(cur); };
    const keyHandler = e => {
      if (e.key === "ArrowRight") { stopShow(); if (cur < STEPS.length - 1) goto(cur + 1); }
      if (e.key === "ArrowLeft") { stopShow(); if (cur > 0) goto(cur - 1); }
    };
    document.addEventListener("keydown", keyHandler);

    goto(0);
    return {
      goto, startShow, stopShow,
      open() { container.classList.remove("dp-hidden"); },
      close() { stopShow(); audio.pause(); container.classList.add("dp-hidden"); },
      destroy() { stopShow(); audio.pause(); document.removeEventListener("keydown", keyHandler); container.innerHTML = ""; },
    };
  }

  window.DemoPanel = { mount };
})();
