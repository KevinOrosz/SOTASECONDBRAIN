#!/usr/bin/env python3
"""KB access layer — read-only parser + index + seed extractor + search dashboard.

Usage:  python3 tools/kb-index.py [--root R]   (from the package root or anywhere)
        --root re-roots WIKI, OUT and DASH together, so a fixture build never touches the live dashboard
Reads:  KB/wiki/**/*.md   (articles only; _index.md excluded; KB never modified)
Writes: KB/output/kb-index.json       — full machine-readable article index
        KB/output/content-seeds.json  — core-claim seed candidates for content mining
        <dashboard> (kb.json, default KB/output/kb-search.html) — self-contained search dashboard (zero deps)

Stdlib only. Regenerate any time the KB changes. Built 2026-06-09 (upgrade Rank 5).
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import html  # noqa: E402
import kb_config  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("kb_provenance", Path(__file__).resolve().parent / "kb-provenance.py")
prov = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prov)


def paths(root: Path):
    """WIKI, OUT, DASH under one root — they move together, never separately."""
    return root / "KB" / "wiki", root / "KB" / "output", kb_config.path(root, "dashboard")

META_RE = re.compile(r"^\*\*(Category|Sources|Updated):\*\*\s*(.+?)\s*$", re.M)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def parse_article(path: Path, root: Path = ROOT) -> dict:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    title_m = H1_RE.search(text)
    meta = {k.lower(): v for k, v in META_RE.findall(text)}
    # Core Claim = body between '## Core Claim' and the next '## '
    claim = ""
    cm = re.search(r"^##\s+Core Claim\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if cm:
        claim = " ".join(cm.group(1).split())
    links = [l.split("|")[0].strip() for l in LINK_RE.findall(text)]
    raw_sources = [l for l in links if l.startswith("RAW/")]
    wiki_links = [l for l in links if not l.startswith("RAW/") and not l.startswith("http")]
    return {
        "stem": path.stem,
        "category": path.parent.name,
        "path": str(path.relative_to(root)),
        "content_hash": hashlib.sha256(raw).hexdigest(),
        "title": title_m.group(1) if title_m else path.stem,
        "claim": claim,
        "updated": meta.get("updated", ""),
        "sources": raw_sources,
        "links": sorted(set(wiki_links)),
        "sections": SECTION_RE.findall(text),
        "words": len(text.split()),
    }


def build(root: Path = ROOT) -> int:
    WIKI, OUT, DASH = paths(root)
    if not WIKI.is_dir():
        print(f"FATAL: {WIKI} not found", file=sys.stderr)
        return 1
    articles, errors = [], []
    for p in sorted(WIKI.rglob("*.md")):
        if p.name == "_index.md":
            continue
        try:
            articles.append(parse_article(p, root))
        except Exception as e:  # noqa: BLE001 — report, never crash the run
            errors.append(f"{p}: {e}")

    OUT.mkdir(parents=True, exist_ok=True)
    index = {
        "generated": __import__("datetime").date.today().isoformat(),
        "inputs_hash": prov.inputs_hash(root),
        "article_count": len(articles),
        "categories": sorted({a["category"] for a in articles}),
        "articles": articles,
    }
    (OUT / "kb-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    seeds = [
        {
            "seed": a["claim"],
            "article": a["stem"],
            "category": a["category"],
            "path": a["path"],
            "sources": a["sources"],
        }
        for a in articles
        if a["claim"]
    ]
    (OUT / "content-seeds.json").write_text(
        json.dumps(
            {
                "generated": index["generated"],
                "inputs_hash": index["inputs_hash"],
                "note": "Mechanical extraction: every core claim = one seed candidate. "
                "Ranking and fit are judgment work, not script work.",
                "seed_count": len(seeds),
                "seeds": seeds,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    DASH.parent.mkdir(parents=True, exist_ok=True)
    DASH.write_text(dashboard_html(index, kb_config.load(root).get("title", "Knowledge Base")), encoding="utf-8")

    print(f"parsed:   {len(articles)} articles, {len(errors)} errors")
    for e in errors:
        print(f"  ERROR {e}")
    print(f"index:    {OUT / 'kb-index.json'}  ({(OUT / 'kb-index.json').stat().st_size // 1024}KB)")
    print(f"seeds:    {len(seeds)} -> {OUT / 'content-seeds.json'}")
    print(f"dashboard:{DASH}")
    return 0 if not errors else 1


def dashboard_html(index: dict, title: str = "Knowledge Base") -> str:
    data = json.dumps(
        [
            {k: a[k] for k in ("stem", "category", "path", "title", "claim", "updated", "sources", "links", "words")}
            for a in index["articles"]
        ],
        ensure_ascii=False,
    ).replace("</", "<\\/")
    cats = json.dumps(index["categories"])
    return (
        """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<!-- inputs_hash: """ + index["inputs_hash"] + """ -->
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KB Search — """ + str(index["article_count"]) + """ articles</title>
<style>
  :root{--ink:#0d0b07;--panel:#161208;--gold:#c9a14d;--gold-dim:#8a6f37;--text:#e8e0cf;--mut:#9a8f78}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--ink);color:var(--text);font:15px/1.55 Georgia,'Times New Roman',serif;min-height:100vh}
  header{padding:28px 24px 14px;border-bottom:1px solid #2a2310}
  h1{font-size:21px;color:var(--gold);font-weight:normal;letter-spacing:.06em}
  h1 small{color:var(--mut);font-size:13px;letter-spacing:0}
  .bar{display:flex;gap:10px;padding:14px 24px;flex-wrap:wrap;align-items:center}
  #q{flex:1;min-width:220px;background:var(--panel);border:1px solid var(--gold-dim);color:var(--text);
     padding:10px 14px;font:inherit;border-radius:3px;outline:none}
  #q:focus{border-color:var(--gold)}
  .chip{background:none;border:1px solid #3a3015;color:var(--mut);padding:5px 11px;border-radius:14px;
        font:13px Georgia,serif;cursor:pointer}
  .chip.on{border-color:var(--gold);color:var(--gold)}
  main{display:grid;grid-template-columns:minmax(300px,460px) 1fr;gap:0;min-height:60vh}
  #list{border-right:1px solid #2a2310;max-height:78vh;overflow-y:auto}
  .row{padding:11px 18px;border-bottom:1px solid #1d1709;cursor:pointer}
  .row:hover,.row.sel{background:var(--panel)}
  .row .t{color:var(--gold)}
  .row .c{font-size:12px;color:var(--mut);letter-spacing:.05em}
  #detail{padding:24px 30px;max-height:78vh;overflow-y:auto}
  #detail h2{color:var(--gold);font-weight:normal;font-size:19px;margin-bottom:4px}
  .meta{font-size:12.5px;color:var(--mut);margin-bottom:14px}
  .claim{border-left:2px solid var(--gold);padding:10px 16px;background:var(--panel);margin:12px 0;font-style:italic}
  .sec{margin-top:14px;font-size:13px;color:var(--mut)}
  .sec b{color:var(--text);font-weight:normal}
  .src{font-size:12.5px;color:var(--gold-dim);word-break:break-all}
  .lnk{display:inline-block;margin:2px 6px 2px 0;font-size:12.5px;color:var(--gold-dim);
       border:1px solid #2a2310;padding:1px 8px;border-radius:10px;cursor:pointer}
  .lnk:hover{color:var(--gold);border-color:var(--gold-dim)}
  #count{color:var(--mut);font-size:13px;padding:0 24px 8px}
  .empty{color:var(--mut);padding:40px;text-align:center;font-style:italic}
  @media(max-width:760px){main{grid-template-columns:1fr}#list{max-height:38vh}}
</style></head><body>
<header><h1>""" + html.escape(title.upper()) + """ — SEARCH <small>· """ + str(index["article_count"]) + """ articles · generated """ + index["generated"] + """ · read-only</small></h1></header>
<div class="bar"><input id="q" type="search" placeholder="search title, claim, category, slug — space = AND" autofocus>
<div id="chips"></div></div>
<div id="count"></div>
<main><div id="list"></div><div id="detail"><div class="empty">Select an article — or just start typing.</div></div></main>
<script>
const DATA=""" + data + """;
const CATS=""" + cats + """;
let activeCat=null,sel=null;
const $=id=>document.getElementById(id);
const norm=s=>(s||'').toLowerCase();
function hay(a){return norm(a.title+' '+a.claim+' '+a.category+' '+a.stem+' '+(a.links||[]).join(' '))}
function match(a,q){if(activeCat&&a.category!==activeCat)return false;
  if(!q)return true;const h=hay(a);return q.split(/\\s+/).every(t=>h.includes(t))}
function render(){const q=norm($('q').value.trim());
  const hits=DATA.filter(a=>match(a,q));
  $('count').textContent=hits.length+' of '+DATA.length+(activeCat?' · '+activeCat:'');
  $('list').innerHTML=hits.slice(0,400).map(a=>'<div class="row'+(sel===a.stem?' sel':'')+'" data-s="'+a.stem+'">'+
    '<div class="t">'+esc(a.title)+'</div><div class="c">'+a.category+' · '+a.words+'w</div></div>').join('')
    ||'<div class="empty">No hits. Loosen the query.</div>';}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;')}
function show(stem){sel=stem;const a=DATA.find(x=>x.stem===stem);if(!a)return;
  $('detail').innerHTML='<h2>'+esc(a.title)+'</h2>'+
  '<div class="meta">'+a.category+' · updated '+(a.updated||'?')+' · '+a.words+' words · <span class="src">'+esc(a.path)+'</span></div>'+
  (a.claim?'<div class="claim">'+esc(a.claim)+'</div>':'')+
  (a.sources&&a.sources.length?'<div class="sec"><b>Sources:</b><br>'+a.sources.map(s=>'<span class="src">'+esc(s)+'</span>').join('<br>')+'</div>':'')+
  (a.links&&a.links.length?'<div class="sec"><b>Connections:</b><br>'+a.links.map(l=>'<span class="lnk" data-l="'+esc(l)+'">'+esc(l)+'</span>').join('')+'</div>':'');
  render();}
$('chips').innerHTML=CATS.map(c=>'<button class="chip" data-c="'+c+'">'+c+'</button>').join('');
document.addEventListener('click',e=>{
  const r=e.target.closest('.row');if(r){show(r.dataset.s);return}
  const ch=e.target.closest('.chip');if(ch){activeCat=activeCat===ch.dataset.c?null:ch.dataset.c;
    document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('on',x.dataset.c===activeCat));render();return}
  const lk=e.target.closest('.lnk');if(lk){const t=lk.dataset.l.split('/').pop();
    const hit=DATA.find(x=>x.stem===t||x.stem===t.replace(/\\.md$/,''));if(hit)show(hit.stem);}});
$('q').addEventListener('input',render);
render();
</script></body></html>"""
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build kb-index.json, content-seeds.json and the search dashboard.")
    ap.add_argument("--root", default=str(ROOT), help="repo root; WIKI, OUT and DASH all resolve under it")
    sys.exit(build(Path(ap.parse_args().root).resolve()))
