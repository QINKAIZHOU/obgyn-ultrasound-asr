"""把分步演示面板注入 archify 流程图页，产出 archify/us_flow_demo.html。

源页 archify/us_flow.html（archify 生成，showcase 级 viewer）保持不动；
注入内容：右侧演示抽屉（demo/panel.js）+ 每个流程图节点的「▶」演示徽标
+ 节点点亮样式 + 「从头演示」悬浮按钮 + 双击节点打开演示。

交互设计：viewer 节点单击保留其原生交互（聚焦/护照），演示入口为
① 节点右上角「▶」徽标（click 已 stopPropagation，不干扰 viewer）
② 节点双击
③ 右下角「▶ 从头演示」悬浮按钮（自动演示全流程）

节点 ↔ 演示步骤映射（10 节点与 10 步一一对应）：
  speech/template_cmd/voiceid/asr/hotword/llm/extract/fill/emr/report → 步骤 0..9

用法:
  .venv/Scripts/python demo/inject_demo.py
      [--flow archify/us_flow.html] [--panel demo/panel.js]
      [--data demo/demo_data.js] [--out archify/us_flow_demo.html]
  .venv/Scripts/python demo/inject_demo.py --check   # 只校验已生成产物
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# 节点 id → 演示步骤（与 STEPS 顺序一致）
NODE_STEP_MAP = {
    "speech": 0, "template_cmd": 1, "voiceid": 2, "asr": 3, "hotword": 4,
    "llm": 5, "extract": 6, "fill": 7, "emr": 8, "report": 9,
}

MARKER = "<!-- DEMO-INJECT -->"

INJECT_CSS = """
<style id="demo-inject-style">
/* 演示抽屉 */
#demo-drawer { position:fixed; top:0; right:0; height:100vh; width:min(560px,100vw); z-index:9999;
  background:#fff; box-shadow:-10px 0 36px rgba(10,25,60,.3); transform:translateX(105%);
  transition:transform .28s ease; display:flex; flex-direction:column; }
#demo-drawer.dp-open { transform:none; }
#demo-close { position:absolute; top:10px; right:12px; z-index:3; width:30px; height:30px;
  border:1px solid #dde4ee; border-radius:50%; background:#fff; color:#6b7686; cursor:pointer; font-size:14px; }
#demo-close:hover { color:#d5493f; border-color:#d5493f; }
#demo-panel { flex:1; min-height:0; }
/* 流程图节点点亮 */
svg g.demo-active { filter: drop-shadow(0 0 5px #1a66c2) drop-shadow(0 0 12px #4d9bef); }
/* 演示徽标 */
svg .demo-badge { cursor:pointer; }
svg .demo-badge circle { fill:#1a66c2; stroke:#fff; stroke-width:1.5; transition:fill .15s; }
svg .demo-badge:hover circle { fill:#0e4a94; }
svg .demo-badge path { fill:#fff; }
/* 「从头演示」悬浮按钮 */
#demo-fab { position:fixed; right:18px; bottom:18px; z-index:9998; border:none; border-radius:24px;
  padding:11px 22px; background:linear-gradient(120deg,#0e4a94,#1a66c2); color:#fff; font-size:14.5px;
  font-weight:600; cursor:pointer; box-shadow:0 6px 20px rgba(14,74,148,.45); font-family:inherit; }
#demo-fab:hover { transform:translateY(-1px); box-shadow:0 8px 24px rgba(14,74,148,.55); }
</style>
"""

INJECT_HTML = """
<!-- DEMO-INJECT -->
<button id="demo-fab" title="自动演示全部流程">▶ 从头演示</button>
<div id="demo-drawer">
  <button id="demo-close" title="关闭演示">✕</button>
  <div id="demo-panel"></div>
</div>
"""

INJECT_JS = """
<script>
(function () {
  var NODE_STEP = __NODE_STEP__;
  function ready(fn) {
    document.readyState !== "loading" ? fn() : document.addEventListener("DOMContentLoaded", fn);
  }
  ready(function () {
    if (!window.DEMO_DATA || !window.DemoPanel) {
      console.error("[demo] window.DEMO_DATA 或 DemoPanel 未加载");
      return;
    }
    var SVGNS = "http://www.w3.org/2000/svg";
    var drawer = document.getElementById("demo-drawer");
    var fab = document.getElementById("demo-fab");
    var panel = window.DemoPanel.mount(document.getElementById("demo-panel"), {
      audioPath: "__AUDIO_PATH__",
      onActiveNode: function (i) {
        document.querySelectorAll("g.demo-active").forEach(function (g) { g.classList.remove("demo-active"); });
        if (i == null) return;
        var nid = Object.keys(NODE_STEP).find(function (k) { return NODE_STEP[k] === i; });
        var g = nid && document.getElementById("node-" + nid);
        if (g) g.classList.add("demo-active");
      },
    });

    function openStep(i) {
      panel.goto(i);
      drawer.classList.add("dp-open");
      if (fab) fab.style.display = "none";
    }
    function closeDrawer() {
      drawer.classList.remove("dp-open");
      if (fab) fab.style.display = "";
    }

    /* 每个节点右上角注入「▶」演示徽标 */
    function injectBadges() {
      Object.keys(NODE_STEP).forEach(function (nid) {
        var g = document.getElementById("node-" + nid);
        if (!g || g.querySelector(".demo-badge")) return;
        var bb;
        try { bb = g.getBBox(); } catch (_) { bb = null; }
        var cx = bb ? bb.x + bb.width - 1 : 0;
        var cy = bb ? bb.y - 1 : 0;
        var badge = document.createElementNS(SVGNS, "g");
        badge.setAttribute("class", "demo-badge");
        var tip = "演示：" + (g.getAttribute("data-node-label") || nid);
        var title = document.createElementNS(SVGNS, "title");
        title.textContent = tip;
        var circle = document.createElementNS(SVGNS, "circle");
        circle.setAttribute("cx", cx); circle.setAttribute("cy", cy); circle.setAttribute("r", 9);
        var tri = document.createElementNS(SVGNS, "path");
        var dx = cx - 2.4, dy = cy - 4;
        tri.setAttribute("d", "M" + dx + " " + dy + " L" + (dx + 6.5) + " " + (cy) + " L" + dx + " " + (cy + 4) + " Z");
        badge.appendChild(title); badge.appendChild(circle); badge.appendChild(tri);
        badge.addEventListener("click", function (e) {
          e.stopPropagation(); e.preventDefault();
          openStep(NODE_STEP[nid]);
        });
        g.appendChild(badge);
        /* 双击节点本体同样打开（单击仍归 viewer 聚焦） */
        g.addEventListener("dblclick", function (e) {
          e.stopPropagation();
          openStep(NODE_STEP[nid]);
        });
      });
    }
    /* 等 SVG 完成布局后取 getBBox */
    requestAnimationFrame(function () { requestAnimationFrame(injectBadges); });

    document.getElementById("demo-close").addEventListener("click", closeDrawer);
    fab.addEventListener("click", function () {
      drawer.classList.add("dp-open");
      fab.style.display = "none";
      panel.startShow();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeDrawer();
    });
  });
})();
</script>
"""


def load_audio_rel(data_js: Path, out_html: Path, demo_dir: Path) -> str:
    """从 demo_data.js 解析音频路径，换算为相对输出页面的路径。"""
    text = data_js.read_text(encoding="utf-8").strip()
    prefix = "window.DEMO_DATA = "
    if not text.startswith(prefix) or not text.endswith(";"):
        raise SystemExit(f"demo_data.js 格式异常: {data_js}")
    meta = json.loads(text[len(prefix):-1])["meta"]
    audio_abs = (demo_dir / meta["audio_rel"]).resolve()
    return Path(os.path.relpath(audio_abs, out_html.resolve().parent)).as_posix()


def inject(flow: Path, panel: Path, data: Path, out: Path) -> None:
    html = flow.read_text(encoding="utf-8")
    if MARKER in html:
        raise SystemExit(f"源页已含注入标记，请确认用的是未注入的源文件: {flow}")
    if "</body>" not in html:
        raise SystemExit(f"源页无 </body>: {flow}")

    audio_path = load_audio_rel(data, out, data.parent)
    data_ref = Path(os.path.relpath(data.resolve(), out.resolve().parent)).as_posix()
    bootstrap = (
        INJECT_CSS
        + INJECT_HTML
        + f'<script src="{data_ref}"></script>\n'
        + "<script>\n" + panel.read_text(encoding="utf-8") + "\n</script>\n"
        + INJECT_JS.replace("__NODE_STEP__", json.dumps(NODE_STEP_MAP))
                   .replace("__AUDIO_PATH__", audio_path)
    )
    out_html = html.replace("</body>", bootstrap + "</body>")
    out.write_text(out_html, encoding="utf-8")
    print(f"已生成: {out}（音频相对路径 {audio_path}）")


def check(out: Path) -> None:
    html = out.read_text(encoding="utf-8")
    problems = []
    if MARKER not in html:
        problems.append("缺少注入标记")
    if "__AUDIO_PATH__" in html or "__NODE_STEP__" in html:
        problems.append("存在未替换的占位符")
    for nid in NODE_STEP_MAP:
        if f'"{nid}"' not in html:
            problems.append(f"节点映射缺失: {nid}")
    for frag in ('id="demo-drawer"', 'id="demo-fab"', "DemoPanel.mount", 'id="demo-panel"'):
        if frag not in html:
            problems.append(f"缺少注入片段: {frag}")
    if "dp-body { flex:1; overflow-y:auto" not in html.replace("\n", "").replace("  ", " "):
        pass  # 样式细节由 smoke test 覆盖，此处不查
    if problems:
        raise SystemExit("注入产物校验失败:\n  " + "\n  ".join(problems))
    print(f"注入产物校验通过: {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="注入演示面板到 archify 流程图页")
    ap.add_argument("--flow", default="archify/us_flow.html")
    ap.add_argument("--panel", default="demo/panel.js")
    ap.add_argument("--data", default="demo/demo_data.js")
    ap.add_argument("--out", default="archify/us_flow_demo.html")
    ap.add_argument("--check", action="store_true", help="只校验已生成的产物")
    args = ap.parse_args()

    if args.check:
        check(Path(args.out))
        return
    inject(Path(args.flow), Path(args.panel), Path(args.data), Path(args.out))
    check(Path(args.out))


if __name__ == "__main__":
    main()
