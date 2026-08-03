"""Build an offline, human-controlled M1-A2 Oracle initial-review package.

The package creates browser-compatible local proxies from the already-pinned
analysis derivatives.  It makes no automatic Oracle decision: all saved rows
remain pending human initial review and are exported for later validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


WIDTH = 832
HEIGHT = 480
FPS = 16
EXPORT_COLUMNS = (
    "clip_id",
    "expected_scene_class",
    "start_frame",
    "end_frame",
    "region_state",
    "region_x",
    "region_y",
    "region_width",
    "region_height",
    "camera_motion",
    "occlusion",
    "disocclusion",
    "lighting_change",
    "scene_cut",
    "full_reobserve",
    "notes",
    "oracle_initial_pass",
    "verification_status",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def proxy_command(ffmpeg: Path, source: Path, output: Path) -> list[str]:
    return [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-n",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-map_metadata",
        "-1",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-fps_mode",
        "cfr",
        "-g",
        str(FPS),
        "-bf",
        "0",
        "-threads",
        "1",
        "-fflags",
        "+bitexact",
        "-movflags",
        "+faststart",
        "-metadata",
        "creation_time=",
        str(output),
    ]


def probe(ffprobe: Path, path: Path) -> dict[str, Any]:
    payload = json.loads(
        run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_frames",
                "-show_entries",
                "stream=codec_name,width,height,pix_fmt,avg_frame_rate,nb_read_frames",
                "-show_entries",
                "format=format_name,duration,size",
                "-of",
                "json",
                str(path),
            ]
        ).stdout
    )
    stream = payload["streams"][0]
    numerator, denominator = stream["avg_frame_rate"].split("/")
    return {
        "codec": stream["codec_name"],
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "pixel_format": stream["pix_fmt"],
        "fps": float(numerator) / float(denominator),
        "frame_count": int(stream["nb_read_frames"]),
        "container": payload["format"]["format_name"],
        "duration_seconds": float(payload["format"]["duration"]),
        "bytes": int(payload["format"]["size"]),
    }


def review_instructions() -> str:
    return """# M1-A2 Oracle 1차 시각 검수 사용법

## 시작

1. `oracle-review.html`을 Microsoft Edge 또는 Google Chrome으로 엽니다.
2. 상단의 영상 선택 메뉴에서 C01부터 C12까지 차례로 선택합니다.
3. 재생, 일시정지, `-1 프레임`, `+1 프레임` 버튼으로 변화를 확인합니다.
4. `A 캡처`와 `B 캡처`를 눌러 두 시점의 프레임을 나란히 비교합니다.

## 구간과 영역 기록

1. 변화가 시작되는 프레임에서 `구간 시작 설정`을 누릅니다.
2. 변화가 끝나는 프레임에서 `구간 끝 설정`을 누릅니다.
3. 영상 위에서 마우스로 영역을 드래그합니다. 전체 화면 판단이면
   `전체 화면 영역`을 누릅니다.
4. 영역 상태를 선택합니다.
   - `dirty`: 실제 변화가 있어 다시 관찰해야 하는 영역
   - `stable`: 해당 구간에서 정지한 영역
   - `uncertain`: 사람이 판단하기 어렵거나 추가 확인이 필요한 영역
5. 카메라 움직임, occlusion, disocclusion, 조명 변화, scene cut을
   선택하고 `검수 행 추가`를 누릅니다.

한 구간에 dirty/stable/uncertain 영역이 함께 있으면 같은 프레임 구간을
사용해 영역별로 여러 행을 추가합니다. 자동 제안은 제공되지 않으며,
모든 선택은 검수자의 직접 판단입니다.

## C07 hard cut

1. C07을 프레임 단위로 이동해 장면이 바뀌는 정확한 경계를 찾습니다.
2. cut 직전 프레임을 시작, cut 직후 프레임을 끝으로 지정합니다.
3. `scene cut`과 `full reobserve`를 선택하고 전체 화면을 `dirty`로
   기록합니다.
4. 메모에 cut 판단 근거를 적습니다.

## 저장과 제출

- `브라우저 임시 저장`은 현재 입력을 이 브라우저의 localStorage에
  보관합니다.
- C01-C12를 모두 검수한 뒤 `JSON 내보내기`와 `CSV 내보내기`를 각각
  누릅니다.
- 다운로드된 두 파일은 자동 정답이 아니며 `pending_review` 상태입니다.
- 두 파일을 M1-A2 검수 담당 작업에 전달하십시오. JSON이나 좌표를
  직접 편집하지 마십시오.

이 단계는 Oracle 1차 검수만 준비합니다. blind 재검수, adjudication,
최종 verified 판정은 별도 단계이며 자동으로 완료되지 않습니다.
"""


def render_html(clips: list[dict[str, Any]]) -> str:
    clip_payload = json.dumps(clips, ensure_ascii=False, separators=(",", ":"))
    html = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HIVEFRAME M1-A2 Oracle 1차 검수</title>
<style>
:root{font-family:system-ui,sans-serif;color:#172033;background:#f3f6fb}body{margin:0}
header{background:#16213a;color:white;padding:18px 24px}header h1{margin:0 0 6px;font-size:22px}
.warn{background:#fff4ce;border:1px solid #e8bd38;padding:10px;border-radius:8px;color:#563e00}
main{max-width:1420px;margin:auto;padding:18px}.grid{display:grid;grid-template-columns:minmax(600px,2fr) minmax(360px,1fr);gap:16px}
.card{background:white;border:1px solid #d9e0ec;border-radius:10px;padding:14px;box-shadow:0 2px 8px #0000000d}
.stage{position:relative;width:100%;aspect-ratio:832/480;background:#111;overflow:hidden;border-radius:8px}
video,.stage canvas{position:absolute;width:100%;height:100%;inset:0}.stage canvas{cursor:crosshair}
button,select,input,textarea{font:inherit}button{padding:8px 11px;margin:3px;border:1px solid #9aa7ba;border-radius:7px;background:#f8fafc;cursor:pointer}button.primary{background:#2457d6;color:white;border-color:#2457d6}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}.field{display:grid;gap:4px;margin:8px 0}.checks{display:grid;grid-template-columns:1fr 1fr;gap:5px}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:8px}.compare canvas{width:100%;background:#111;border-radius:6px}.status{font-family:ui-monospace,monospace;background:#eef2f8;padding:8px;border-radius:6px}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{border:1px solid #dce2ed;padding:5px;text-align:left}tbody tr:nth-child(even){background:#f7f9fc}.scroll{overflow:auto;max-height:340px}
@media(max-width:980px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><h1>HIVEFRAME M1-A2 Oracle 1차 시각 검수</h1><div>자동 정답 없음 · 모든 결과 pending_review · JSON 직접 편집 불필요</div></header>
<main>
<p class="warn">이 도구는 사람의 1차 검수 입력만 저장합니다. blind 재검수, adjudication, verified 판정, corpus admission 또는 topology 실행을 수행하지 않습니다.</p>
<div class="grid">
<section class="card">
<div class="row"><label>영상 <select id="clip"></select></label><strong id="scene"></strong></div>
<div class="stage"><video id="video" controls preload="metadata"></video><canvas id="overlay" width="832" height="480"></canvas></div>
<div class="row"><button id="back">-1 프레임</button><button id="forward">+1 프레임</button><button id="captureA">A 캡처</button><button id="captureB">B 캡처</button><span id="position" class="status"></span></div>
<div class="compare"><div><b>A 기준 프레임</b><canvas id="canvasA" width="832" height="480"></canvas></div><div><b>B 현재 프레임</b><canvas id="canvasB" width="832" height="480"></canvas></div></div>
</section>
<section class="card">
<h2>구간·영역 판정</h2>
<div class="row"><button id="setStart">구간 시작 설정</button><button id="setEnd">구간 끝 설정</button><button id="full">전체 화면 영역</button></div>
<div id="range" class="status"></div>
<div id="rect" class="status">영역: 아직 선택하지 않음</div>
<div class="field"><label>영역 상태<select id="regionState"><option value="dirty">dirty — 변화</option><option value="stable">stable — 정지</option><option value="uncertain" selected>uncertain — 판단 어려움</option></select></label></div>
<div class="field"><label>전체 카메라 움직임<select id="camera"><option value="uncertain">판단 어려움</option><option value="yes">있음</option><option value="no">없음</option></select></label></div>
<div class="checks"><label><input id="occ" type="checkbox"> occlusion</label><label><input id="disocc" type="checkbox"> disocclusion</label><label><input id="light" type="checkbox"> 조명 변화</label><label><input id="cut" type="checkbox"> scene cut</label><label><input id="reobserve" type="checkbox"> full reobserve</label></div>
<div class="field"><label>메모<textarea id="notes" rows="4" placeholder="판단 근거와 애매한 점을 기록"></textarea></label></div>
<div class="row"><button class="primary" id="add">검수 행 추가</button><button id="save">브라우저 임시 저장</button></div>
<div id="c07" class="warn" hidden>C07에서는 정확한 hard-cut 경계를 찾아 전체 화면 dirty + scene cut + full reobserve로 기록하세요.</div>
</section>
</div>
<section class="card" style="margin-top:16px"><div class="row"><h2 style="margin-right:auto">기록된 검수 행</h2><button id="exportJson">JSON 내보내기</button><button id="exportCsv">CSV 내보내기</button><button id="clear">현재 영상 행 삭제</button></div><div class="scroll"><table><thead><tr><th>clip</th><th>frames</th><th>state</th><th>region</th><th>camera</th><th>flags</th><th>삭제</th></tr></thead><tbody id="rows"></tbody></table></div></section>
</main>
<script>
const CLIPS=__CLIPS__;
const FPS=16,W=832,H=480,KEY='hiveframe-m1-a2-oracle-initial-v1';
const $=id=>document.getElementById(id);let entries=JSON.parse(localStorage.getItem(KEY)||'[]');let start=0,end=0,rect=null,drag=null;
const video=$('video'),overlay=$('overlay'),ctx=overlay.getContext('2d');
function clip(){return CLIPS.find(x=>x.clip_id===$('clip').value)}
function frame(){return Math.max(0,Math.round(video.currentTime*FPS))}
function refreshPos(){ $('position').textContent=`${video.currentTime.toFixed(3)}초 · frame ${frame()}`;$('range').textContent=`구간: ${start} → ${end}`;drawRect() }
function loadClip(){const c=clip();video.src=c.proxy;$('scene').textContent=c.clip_id.toUpperCase()+' · '+c.scene_class;$('c07').hidden=c.clip_id!=='c07';start=end=0;rect=null;refreshPos();renderRows()}
function step(n){video.pause();video.currentTime=Math.max(0,Math.min(video.duration||1e9,video.currentTime+n/FPS))}
function capture(id){const c=$(id).getContext('2d');c.drawImage(video,0,0,W,H)}
function drawRect(){ctx.clearRect(0,0,W,H);if(!rect)return;ctx.strokeStyle=$('regionState').value==='dirty'?'#ff3b30':$('regionState').value==='stable'?'#32d74b':'#ffd60a';ctx.lineWidth=4;ctx.strokeRect(rect.x,rect.y,rect.w,rect.h);$('rect').textContent=`영역: x=${rect.x}, y=${rect.y}, w=${rect.w}, h=${rect.h}`}
function point(e){const b=overlay.getBoundingClientRect();return{x:Math.round((e.clientX-b.left)*W/b.width),y:Math.round((e.clientY-b.top)*H/b.height)}}
overlay.onmousedown=e=>{drag=point(e);rect={x:drag.x,y:drag.y,w:0,h:0};drawRect()};overlay.onmousemove=e=>{if(!drag)return;const p=point(e);rect={x:Math.min(drag.x,p.x),y:Math.min(drag.y,p.y),w:Math.abs(p.x-drag.x),h:Math.abs(p.y-drag.y)};drawRect()};overlay.onmouseup=()=>{drag=null};
function add(){if(!rect||rect.w<1||rect.h<1)return alert('영상 위에서 영역을 드래그하거나 전체 화면 영역을 선택하세요.');if(end<start)return alert('구간 끝은 시작보다 앞설 수 없습니다.');const c=clip();entries.push({clip_id:c.clip_id,expected_scene_class:c.scene_class,start_frame:start,end_frame:end,region_state:$('regionState').value,region_x:rect.x,region_y:rect.y,region_width:rect.w,region_height:rect.h,camera_motion:$('camera').value,occlusion:$('occ').checked,disocclusion:$('disocc').checked,lighting_change:$('light').checked,scene_cut:$('cut').checked,full_reobserve:$('reobserve').checked,notes:$('notes').value.trim(),oracle_initial_pass:'pending_review',verification_status:'pending_review',input_method:'direct_human_visual_review'});save();renderRows()}
function save(){localStorage.setItem(KEY,JSON.stringify(entries));$('save').textContent='저장됨';setTimeout(()=>$('save').textContent='브라우저 임시 저장',900)}
function flags(e){return ['occlusion','disocclusion','lighting_change','scene_cut','full_reobserve'].filter(k=>e[k]).join(', ')}
function renderRows(){$('rows').innerHTML='';entries.filter(e=>e.clip_id===clip().clip_id).forEach((e,i)=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${e.clip_id}</td><td>${e.start_frame}-${e.end_frame}</td><td>${e.region_state}</td><td>${e.region_x},${e.region_y},${e.region_width},${e.region_height}</td><td>${e.camera_motion}</td><td>${flags(e)}</td><td><button data-i="${i}">삭제</button></td>`;tr.querySelector('button').onclick=()=>{const actual=entries.indexOf(entries.filter(x=>x.clip_id===clip().clip_id)[i]);entries.splice(actual,1);save();renderRows()};$('rows').appendChild(tr)})}
function download(name,type,text){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
function exportJson(){download('m1-a2-oracle-initial-review.pending.json','application/json',JSON.stringify({schema_version:'review-draft-0.1.0',review_phase:'oracle_initial_pass',verification_status:'pending_review',blind_re_review:'pending_review',adjudication:'pending_review',final_status:'pending_review',records:entries},null,2)+'\n')}
function csvCell(v){const s=String(v??'');return /[",\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s}
function exportCsv(){const cols=['clip_id','expected_scene_class','start_frame','end_frame','region_state','region_x','region_y','region_width','region_height','camera_motion','occlusion','disocclusion','lighting_change','scene_cut','full_reobserve','notes','oracle_initial_pass','verification_status'];download('m1-a2-oracle-initial-review.pending.csv','text/csv;charset=utf-8','\ufeff'+cols.join(',')+'\n'+entries.map(e=>cols.map(k=>csvCell(e[k])).join(',')).join('\n')+'\n')}
CLIPS.forEach(c=>{const o=document.createElement('option');o.value=c.clip_id;o.textContent=c.clip_id.toUpperCase()+' — '+c.scene_class;$('clip').appendChild(o)});
$('clip').onchange=loadClip;video.ontimeupdate=refreshPos;video.onseeked=refreshPos;$('back').onclick=()=>step(-1);$('forward').onclick=()=>step(1);$('captureA').onclick=()=>capture('canvasA');$('captureB').onclick=()=>capture('canvasB');$('setStart').onclick=()=>{start=frame();if(end<start)end=start;refreshPos()};$('setEnd').onclick=()=>{end=frame();refreshPos()};$('full').onclick=()=>{rect={x:0,y:0,w:W,h:H};drawRect()};$('regionState').onchange=drawRect;$('cut').onchange=()=>{if($('cut').checked)$('reobserve').checked=true};$('add').onclick=add;$('save').onclick=save;$('exportJson').onclick=exportJson;$('exportCsv').onclick=exportCsv;$('clear').onclick=()=>{if(confirm('현재 영상의 검수 행을 모두 삭제할까요?')){entries=entries.filter(e=>e.clip_id!==clip().clip_id);save();renderRows()}};loadClip();
</script>
</body></html>'''
    return html.replace("__CLIPS__", clip_payload)


def plan(config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    return {
        "execution_started": False,
        "clips": len(config["clips"]),
        "output_reference": "approved-asset:m1-a2/review-package/oracle-initial-review",
        "browser_proxy": {"codec": "h264", "resolution": [WIDTH, HEIGHT], "fps": FPS},
        "automatic_oracle_suggestions": False,
        "oracle_initial_pass": "pending_review",
        "blind_re_review": "pending_review",
        "adjudication": "pending_review",
        "final_status": "pending_review",
        "model_loads": 0,
        "cuda_runs": 0,
        "topology_performance_runs": 0,
        "expected_artifacts": [
            str(output_dir / "oracle-review.html"),
            str(output_dir / "사용방법.md"),
            str(output_dir / "oracle-review-template.csv"),
            str(output_dir / "package-receipt.json"),
            str(output_dir / "proxies" / "c01-review.mp4") + " ... c12-review.mp4",
        ],
    }


def create(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    output_dir = args.output_dir
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite Oracle review package: {output_dir}")
    output_dir.mkdir(parents=True)
    proxy_dir = output_dir / "proxies"
    proxy_dir.mkdir()
    receipts: list[dict[str, Any]] = []
    clips: list[dict[str, Any]] = []
    for item in config["clips"]:
        clip_id = item["clip_id"]
        source = args.derivative_dir / f"{clip_id}-analysis-832x480-16fps-ffv1.mkv"
        if not source.is_file():
            raise FileNotFoundError(f"analysis derivative missing: {clip_id}")
        output = proxy_dir / f"{clip_id}-review.mp4"
        command = proxy_command(args.ffmpeg, source, output)
        run(command)
        metadata = probe(args.ffprobe, output)
        if (
            metadata["codec"] != "h264"
            or metadata["width"] != WIDTH
            or metadata["height"] != HEIGHT
            or abs(metadata["fps"] - FPS) > 1e-9
            or metadata["frame_count"] < 2
        ):
            raise ValueError(f"review proxy contract mismatch: {clip_id}: {metadata}")
        run(
            [
                str(args.ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(output),
                "-map",
                "0:v:0",
                "-f",
                "null",
                "NUL",
            ]
        )
        receipts.append(
            {
                "clip_id": clip_id,
                "proxy_sha256": sha256_file(output),
                "metadata": metadata,
                "source_derivative_sha256": sha256_file(source),
                "command_template": (
                    "<ffmpeg> -i <analysis-derivative> -map 0:v:0 -an -map_metadata -1 "
                    "-c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -r 16 "
                    "-fps_mode cfr -g 16 -bf 0 -threads 1 -fflags +bitexact "
                    "-movflags +faststart <review-proxy>"
                ),
                "purpose": "local human visual review convenience only",
                "evidence_eligibility": False,
            }
        )
        clips.append(
            {
                "clip_id": clip_id,
                "scene_class": item["scene_class"],
                "proxy": f"proxies/{clip_id}-review.mp4",
                "frame_count": metadata["frame_count"],
            }
        )

    html = render_html(clips)
    if "https://" in html or "http://" in html:
        raise ValueError("offline review HTML must not use network resources")
    (output_dir / "oracle-review.html").write_text(html, encoding="utf-8", newline="\n")
    (output_dir / "사용방법.md").write_text(
        review_instructions(), encoding="utf-8", newline="\n"
    )
    with (output_dir / "oracle-review-template.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
    receipt = {
        "schema_version": "0.1.0",
        "package_kind": "m1_a2_oracle_initial_human_review",
        "review_status": "pending_review",
        "automatic_suggestion_method": {
            "value": None,
            "status": "not_collected",
            "reason": "The v1 package uses direct human comparison without automated labels.",
            "method": "offline review package generator",
        },
        "verified_oracles": 0,
        "eligible_clips": 0,
        "proxies": receipts,
        "execution_counts": {
            "model_downloads": 0,
            "model_loads": 0,
            "cuda_runs": 0,
            "paid_external_service_calls": 0,
            "external_customer_or_personal_data_transfers": 0,
            "backend_integration_runs": 0,
            "topology_performance_runs": 0,
        },
    }
    (output_dir / "package-receipt.json").write_text(
        canonical_json(receipt), encoding="utf-8", newline="\n"
    )
    return {
        "package_created": True,
        "proxies": len(receipts),
        "full_decode_passed": len(receipts),
        "oracle_initial_pass": "pending_review",
        "verified_oracles": 0,
        "eligible_clips": 0,
        "topology_performance_runs": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--derivative-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = plan(config, args.output_dir) if args.plan else create(args, config)
    print(canonical_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
