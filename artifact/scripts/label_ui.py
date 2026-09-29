#!/usr/bin/env python3
"""Local labeling UI for negatives_triaged.jsonl. Stdlib only.

  uv run --no-project python3 scripts/label_ui.py          # http://localhost:8765
  uv run --no-project python3 scripts/label_ui.py --blind  # hide suggestions

Writes labels back to the JSONL atomically on every change. Keys:
j/k next/prev · a accept suggestion · A accept for whole group ·
n quick-label non-semantic/equivalent · x clear label · e edit panel ·
f cycle filter (unlabeled → semantic → all) · b toggle blind.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO  # noqa: E402

DATA = REPO / "data/negatives_triaged.jsonl"


def load() -> list[dict]:
    return [json.loads(l) for l in DATA.open()]


def save(records: list[dict]) -> None:
    fd, tmp = tempfile.mkstemp(dir=DATA.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, DATA)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>negative labeler</title>
<style>
:root { color-scheme: light dark;
        --bg:#fafaf7; --fg:#1a1a1a; --dim:#666; --card:#fff; --line:#ddd;
        --add:#e6ffe6; --del:#ffe6e6; --acc:#2b6cb0; --chipbg:#eee;
        --sembg:#fde8e8; --refbg:#e8f0fe; --donel:#2f855a; --ctext:#333; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181d; --fg:#e6e6e3; --dim:#9a9a94; --card:#1f232b; --line:#363b45;
          --add:#173822; --del:#3d1f22; --acc:#5b9dd9; --chipbg:#2a2f38;
          --sembg:#42272b; --refbg:#243247; --donel:#48a56f; --ctext:#c9c9c4; }
}
body { margin:0; font:14px/1.45 -apple-system,system-ui,sans-serif;
       background:var(--bg); color:var(--fg); }
#top { position:sticky; top:0; background:var(--card); border-bottom:1px solid var(--line);
       padding:8px 16px; display:flex; gap:16px; align-items:center; z-index:2; }
#top .id { font-family:ui-monospace,monospace; font-size:12px; color:var(--dim);
           overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
.badge { padding:1px 8px; border-radius:9px; font-size:12px; background:var(--chipbg); }
.badge.semantic-suspect { background:var(--sembg); }
.badge.refactor-rename { background:var(--refbg); }
main { max-width:1100px; margin:0 auto; padding:16px; }
section { background:var(--card); border:1px solid var(--line); border-radius:8px;
          padding:12px 16px; margin-bottom:12px; }
h3 { margin:0 0 6px; font-size:12px; text-transform:uppercase; letter-spacing:.05em;
     color:var(--dim); }
pre { margin:0; white-space:pre-wrap; word-break:break-word;
      font:12.5px/1.5 ui-monospace,monospace; }
.diff .add { background:var(--add); display:block; }
.diff .del { background:var(--del); display:block; }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.comment { border-left:3px solid var(--line); padding:4px 10px; margin:6px 0;
           color:var(--ctext); }
.comment .who { font-size:12px; color:var(--dim); }
.sug { border-left:4px solid var(--acc); }
.sug.hidden-note { color:var(--dim); font-style:italic; }
.chip { display:inline-block; margin:2px; padding:2px 10px; border:1px solid var(--line);
        border-radius:12px; cursor:pointer; user-select:none; font-size:13px; }
.chip.on { background:var(--acc); color:#fff; border-color:var(--acc); }
.lab-done { border-left:4px solid var(--donel); }
#editor textarea { width:100%; box-sizing:border-box; font:13px ui-monospace,monospace; }
button { font:13px system-ui; padding:4px 12px; border-radius:6px; border:1px solid var(--line);
         background:var(--card); cursor:pointer; }
button.primary { background:var(--acc); color:#fff; border-color:var(--acc); }
kbd { background:var(--chipbg); border-radius:3px; padding:0 4px; font-size:11px; }
textarea, button { background:var(--card); color:var(--fg); border:1px solid var(--line); }
#help { color:var(--dim); font-size:12px; }
a { color:var(--acc); }
</style></head><body>
<div id="top">
  <span id="pos"></span>
  <span class="badge" id="bucket"></span>
  <span class="id" id="rid"></span>
  <span id="filter"></span>
  <span id="progress"></span>
</div>
<main id="main"></main>
<div id="help" style="padding:0 16px 24px; max-width:1100px; margin:0 auto">
<kbd>j</kbd>/<kbd>k</kbd> next/prev · <kbd>a</kbd> accept suggestion ·
<kbd>A</kbd> accept for group · <kbd>n</kbd> non-semantic ·
<kbd>x</kbd> clear · <kbd>e</kbd> edit · <kbd>f</kbd> filter · <kbd>b</kbd> blind
</div>
<script>
const CLASSES = ["wrong-quantifier","missing-hypothesis","extraneous-hypothesis",
 "wrong-type-or-domain","wrong-referent","wrong-constant-or-bound","wrong-connective",
 "wrong-answer-marker","junk-value-trap","definitional-mismatch","vacuous-or-trivial",
 "non-semantic","informal-changed","other"];
const DIRS = ["before-weaker","before-stronger","incomparable","equivalent","unclear"];
const CONFS = ["high","medium","low"];
let recs = [], idx = 0, filter = 0, blind = BLIND_DEFAULT, editing = false;
const FILTERS = ["unlabeled","semantic","all"];

function visible() {
  return recs.filter(r => r.bucket !== "duplicate").filter(r => {
    if (FILTERS[filter] === "unlabeled") return !r.label;
    if (FILTERS[filter] === "semantic")
      return !(r.label_suggested && r.label_suggested.classes.length === 1 &&
               r.label_suggested.classes[0] === "non-semantic");
    return true;
  });
}
function esc(s){ return (s??"").replace(/[&<>]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
function diffHtml(d){
  return d.split("\n").map(l=>{
    if (l.startsWith("+++")||l.startsWith("---")||l.startsWith("@@")) return `<span style="color:#888">${esc(l)}</span>\n`;
    if (l.startsWith("+")) return `<span class="add">${esc(l)}</span>`;
    if (l.startsWith("-")) return `<span class="del">${esc(l)}</span>`;
    return esc(l) + "\n";
  }).join("");
}
function labelBox(r){
  if (r.label) return `<section class="lab-done"><h3>your label</h3>
    <b>${r.label.classes.join(", ")}</b> · ${r.label.direction} · ${r.label.confidence}
    <div>${esc(r.label.rationale)}</div></section>`;
  return "";
}
function sugBox(r){
  let out = "";
  for (const p of (r.prior_labels || [])) {
    out += `<section class="sug"><h3>${esc(p.name)} (${p.label.confidence})</h3>
      <b>${p.label.classes.join(", ")}</b> · ${p.label.direction}
      <div>${esc(p.label.rationale)}</div></section>`;
  }
  if (blind) return out + `<section class="sug hidden-note">suggestion hidden (blind mode)</section>`;
  const s = r.label_suggested;
  if (!s) return out;
  return out + `<section class="sug"><h3>suggested (${s.confidence})</h3>
    <b>${s.classes.join(", ")}</b> · ${s.direction}
    <div>${esc(s.rationale)}</div></section>`;
}
function render(){
  const v = visible();
  if (!v.length) { document.getElementById("main").innerHTML =
      "<section>nothing matches this filter 🎉</section>"; updateTop(v); return; }
  if (idx >= v.length) idx = v.length - 1;
  const r = v[idx];
  const sibs = recs.filter(x => x.group === r.group && x.bucket !== "duplicate").length;
  document.getElementById("main").innerHTML = `
    ${labelBox(r)} ${sugBox(r)}
    <section><h3>informal (docstring at merge)</h3><pre>${esc(r.informal ?? "(none)")}</pre></section>
    <section><h3>diff · <a target="_blank" href="https://github.com/google-deepmind/formal-conjectures/pull/${r.pr}">PR #${r.pr}</a>
      · group ${esc(r.group)} (${sibs} record${sibs>1?"s":""})</h3>
      <pre class="diff">${diffHtml(r.unified_diff)}</pre></section>
    <div class="cols">
      <section><h3>before (first push)</h3><pre>${esc(r.formal_before)}</pre></section>
      <section><h3>after (merged)</h3><pre>${esc(r.formal_after)}</pre></section>
    </div>
    ${r.review_comments?.length ? `<section><h3>reviewer comments (same file)</h3>` +
      r.review_comments.map(c=>`<div class="comment"><div class="who">${esc(c.author)} · line ${c.line??"?"}</div>${esc(c.body)}</div>`).join("") + `</section>` : ""}
    <section id="editor" style="display:${editing?"block":"none"}">
      <h3>edit label</h3>
      <div id="chips">${CLASSES.map(c=>`<span class="chip" data-c="${c}">${c}</span>`).join("")}</div>
      <div style="margin:6px 0">${DIRS.map(d=>`<span class="chip dir" data-d="${d}">${d}</span>`).join("")}
        &nbsp;|&nbsp; ${CONFS.map(c=>`<span class="chip conf" data-f="${c}">${c}</span>`).join("")}</div>
      <textarea id="rat" rows="2" placeholder="rationale (one sentence)"></textarea>
      <div style="margin-top:6px"><button class="primary" onclick="saveEdit()">save (⏎)</button>
      <button onclick="editing=false;render()">cancel (esc)</button></div>
    </section>`;
  if (editing) initEditor(r);
  updateTop(v, r);
}
function updateTop(v, r){
  const labeled = recs.filter(x=>x.bucket!=="duplicate" && x.label).length;
  const total = recs.filter(x=>x.bucket!=="duplicate").length;
  document.getElementById("pos").textContent = v.length ? `${idx+1}/${v.length}` : "–";
  document.getElementById("rid").textContent = r ? r.id : "";
  const b = document.getElementById("bucket");
  b.textContent = r ? r.bucket : ""; b.className = "badge " + (r ? r.bucket : "");
  document.getElementById("filter").textContent = `filter: ${FILTERS[filter]}${blind?" · BLIND":""}`;
  document.getElementById("progress").textContent = `labeled ${labeled}/${total}`;
}
let edit = null;
function initEditor(r){
  const base = r.label ?? (blind ? null : r.label_suggested);
  edit = base ? JSON.parse(JSON.stringify(base))
              : {classes:[],direction:"unclear",confidence:"high",rationale:""};
  document.getElementById("rat").value = edit.rationale;
  syncChips();
  document.querySelectorAll("#chips .chip").forEach(el=>el.onclick=()=>{
    const c = el.dataset.c;
    edit.classes = edit.classes.includes(c) ? edit.classes.filter(x=>x!==c) : [...edit.classes,c];
    syncChips(); });
  document.querySelectorAll(".chip.dir").forEach(el=>el.onclick=()=>{ edit.direction=el.dataset.d; syncChips(); });
  document.querySelectorAll(".chip.conf").forEach(el=>el.onclick=()=>{ edit.confidence=el.dataset.f; syncChips(); });
}
function syncChips(){
  document.querySelectorAll("#chips .chip").forEach(el=>el.classList.toggle("on", edit.classes.includes(el.dataset.c)));
  document.querySelectorAll(".chip.dir").forEach(el=>el.classList.toggle("on", edit.direction===el.dataset.d));
  document.querySelectorAll(".chip.conf").forEach(el=>el.classList.toggle("on", edit.confidence===el.dataset.f));
}
async function setLabel(r, label){
  r.label = label;
  await fetch("/api/label", {method:"POST", headers:{"content-type":"application/json"},
    body: JSON.stringify({id:r.id, label})});
}
async function saveEdit(){
  edit.rationale = document.getElementById("rat").value.trim();
  if (!edit.classes.length) { alert("pick at least one class"); return; }
  const v = visible(); await setLabel(v[idx], edit); editing = false;
  if (FILTERS[filter]!=="unlabeled" && idx < v.length-1) idx++;
  render();
}
document.addEventListener("keydown", async e=>{
  if (editing) {
    if (e.key==="Escape"){ editing=false; render(); }
    if (e.key==="Enter" && !e.shiftKey && document.activeElement.id!=="rat"){ e.preventDefault(); saveEdit(); }
    return;
  }
  const v = visible(); if (!v.length && !"fb".includes(e.key)) return;
  const r = v[idx];
  if (e.key==="j"){ idx=Math.min(idx+1,v.length-1); render(); }
  else if (e.key==="k"){ idx=Math.max(idx-1,0); render(); }
  else if (e.key==="a" && r.label_suggested && !blind){ await setLabel(r, r.label_suggested); afterLabel(); }
  else if (e.key==="A" && r.label_suggested && !blind){
    for (const s of recs.filter(x=>x.group===r.group && x.bucket!=="duplicate"))
      await setLabel(s, r.label_suggested);
    afterLabel(); }
  else if (e.key==="n"){ await setLabel(r, {classes:["non-semantic"],direction:"equivalent",
      confidence:"high",rationale:"Confirmed non-semantic by hand."}); afterLabel(); }
  else if (e.key==="x"){ await setLabel(r, null); render(); }
  else if (e.key==="e"){ editing=true; render(); }
  else if (e.key==="f"){ filter=(filter+1)%FILTERS.length; idx=0; render(); }
  else if (e.key==="b"){ blind=!blind; render(); }
});
function afterLabel(){ const v=visible(); if (FILTERS[filter]==="unlabeled") { /* list shrank */ }
  else if (idx < v.length-1) idx++; render(); }
fetch("/api/records").then(r=>r.json()).then(d=>{ recs=d; render(); });
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    records: list[dict] = []
    blind = False

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            page = PAGE.replace("BLIND_DEFAULT", "true" if self.blind else "false")
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/records":
            self._send(200, json.dumps(self.records, ensure_ascii=False).encode(),
                       "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/label":
            self._send(404, b"not found", "text/plain")
            return
        n = int(self.headers.get("content-length", 0))
        req = json.loads(self.rfile.read(n))
        for r in self.records:
            if r["id"] == req["id"]:
                r["label"] = req["label"]
                save(self.records)
                self._send(200, b"{}", "application/json")
                return
        self._send(404, b"unknown id", "text/plain")

    def log_message(self, *args):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--blind", action="store_true",
                    help="start with suggestions hidden (anchoring check)")
    ap.add_argument("--data", default=None,
                    help="alternative JSONL to label (default: negatives_triaged)")
    args = ap.parse_args()
    if args.data:
        global DATA
        DATA = REPO / args.data
    Handler.records = load()
    Handler.blind = args.blind
    print(f"labeling {DATA.relative_to(REPO)} at http://localhost:{args.port}"
          f"{'  (blind)' if args.blind else ''}")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
