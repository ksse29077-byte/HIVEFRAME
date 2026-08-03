"""Build the model-free M1-A2 guided human Oracle review package.

Adjacent-frame grayscale differences produce conservative proposals.  They are
never Oracle truth: every proposal and every export remains pending human and
later blind/adjudication review.  Media and per-frame proposals stay outside
Git; the repository receives only a sanitized method/count receipt.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable

import numpy as np


WIDTH = 832
HEIGHT = 480
FPS = 16
LOW_WIDTH = 208
LOW_HEIGHT = 120
TILE = 8
PIXEL_THRESHOLD = 16
TILE_CHANGE_RATIO = 0.10
TILE_MEAN_THRESHOLD = 8.0
STRONG_TILE_MEAN = 18.0
PROPOSAL_INTERVAL_TRANSITIONS = 16
CUT_CANDIDATE_COUNT = 8

CAMERA_DEFAULT_CLIPS = {"c04", "c05", "c06", "c12"}
OCCLUSION_DEFAULT_CLIPS = {"c08"}
LIGHTING_DEFAULT_CLIPS = {"c11"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        input=input_bytes,
        check=True,
        capture_output=True,
    )


def decode_grayscale(ffmpeg: Path, source: Path) -> np.ndarray:
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"scale={LOW_WIDTH}:{LOW_HEIGHT}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    raw = run(command).stdout
    frame_bytes = LOW_WIDTH * LOW_HEIGHT
    if not raw or len(raw) % frame_bytes:
        raise ValueError(f"unexpected grayscale decode size for {source.name}: {len(raw)}")
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, LOW_HEIGHT, LOW_WIDTH)
    if len(frames) < 2:
        raise ValueError(f"at least two frames are required: {source.name}")
    return frames


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    seen = np.zeros(mask.shape, dtype=bool)
    found: list[list[tuple[int, int]]] = []
    for row, col in zip(*np.nonzero(mask)):
        if seen[row, col]:
            continue
        stack = [(int(row), int(col))]
        seen[row, col] = True
        component: list[tuple[int, int]] = []
        while stack:
            current_row, current_col = stack.pop()
            component.append((current_row, current_col))
            for next_row, next_col in (
                (current_row - 1, current_col),
                (current_row + 1, current_col),
                (current_row, current_col - 1),
                (current_row, current_col + 1),
            ):
                if (
                    0 <= next_row < mask.shape[0]
                    and 0 <= next_col < mask.shape[1]
                    and mask[next_row, next_col]
                    and not seen[next_row, next_col]
                ):
                    seen[next_row, next_col] = True
                    stack.append((next_row, next_col))
        found.append(component)
    return found


def _boxes_touch(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return not (
        left["x"] + left["width"] < right["x"]
        or right["x"] + right["width"] < left["x"]
        or left["y"] + left["height"] < right["y"]
        or right["y"] + right["height"] < left["y"]
    )


def merge_boxes(boxes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [copy.deepcopy(box) for box in boxes]
    changed = True
    while changed:
        changed = False
        output: list[dict[str, Any]] = []
        while merged:
            current = merged.pop(0)
            index = next(
                (i for i, other in enumerate(merged) if _boxes_touch(current, other)),
                None,
            )
            if index is None:
                output.append(current)
                continue
            other = merged.pop(index)
            x0 = min(current["x"], other["x"])
            y0 = min(current["y"], other["y"])
            x1 = max(current["x"] + current["width"], other["x"] + other["width"])
            y1 = max(current["y"] + current["height"], other["y"] + other["height"])
            score = max(float(current["score"]), float(other["score"]))
            merged.append(
                {
                    "x": x0,
                    "y": y0,
                    "width": x1 - x0,
                    "height": y1 - y0,
                    "state": "dirty" if score >= 24.0 else "uncertain",
                    "source": "automatic_adjacent_frame_difference_proposal",
                    "score": score,
                }
            )
            changed = True
        merged = output + merged
    merged.sort(key=lambda box: (box["y"], box["x"], box["height"], box["width"]))
    for index, box in enumerate(merged):
        box["box_id"] = f"box-{index + 1:02d}"
    return merged


def transition_features(frames: np.ndarray) -> list[dict[str, Any]]:
    if frames.ndim != 3 or frames.shape[1:] != (LOW_HEIGHT, LOW_WIDTH):
        raise ValueError("grayscale frame tensor shape mismatch")
    differences = np.abs(np.diff(frames.astype(np.int16), axis=0))
    signed = np.diff(frames.astype(np.int16), axis=0)
    rows = LOW_HEIGHT // TILE
    cols = LOW_WIDTH // TILE
    x_scale = WIDTH / LOW_WIDTH
    y_scale = HEIGHT / LOW_HEIGHT
    records: list[dict[str, Any]] = []
    for frame_index, (difference, signed_difference) in enumerate(zip(differences, signed)):
        tiles = (
            difference.reshape(rows, TILE, cols, TILE)
            .transpose(0, 2, 1, 3)
            .reshape(rows, cols, TILE * TILE)
        )
        tile_mean = tiles.mean(axis=2)
        tile_ratio = (tiles >= PIXEL_THRESHOLD).mean(axis=2)
        active = ((tile_ratio >= TILE_CHANGE_RATIO) & (tile_mean >= TILE_MEAN_THRESHOLD)) | (
            tile_mean >= STRONG_TILE_MEAN
        )
        boxes: list[dict[str, Any]] = []
        for component in _components(active):
            component_score = max(float(tile_mean[row, col]) for row, col in component)
            min_row = max(0, min(row for row, _ in component) - 1)
            max_row = min(rows, max(row for row, _ in component) + 2)
            min_col = max(0, min(col for _, col in component) - 1)
            max_col = min(cols, max(col for _, col in component) + 2)
            x0 = round(min_col * TILE * x_scale)
            y0 = round(min_row * TILE * y_scale)
            x1 = round(max_col * TILE * x_scale)
            y1 = round(max_row * TILE * y_scale)
            boxes.append(
                {
                    "x": x0,
                    "y": y0,
                    "width": min(WIDTH, x1) - x0,
                    "height": min(HEIGHT, y1) - y0,
                    "state": "dirty" if component_score >= 24.0 else "uncertain",
                    "source": "automatic_adjacent_frame_difference_proposal",
                    "score": round(component_score, 6),
                }
            )
        mean_absolute = float(difference.mean())
        changed_ratio = float((difference >= PIXEL_THRESHOLD).mean())
        signed_mean = float(signed_difference.mean())
        records.append(
            {
                "transition_frame": frame_index,
                "next_frame": frame_index + 1,
                "mean_absolute_difference": round(mean_absolute, 6),
                "changed_pixel_ratio": round(changed_ratio, 6),
                "signed_mean_difference": round(signed_mean, 6),
                "global_motion_signal": changed_ratio >= 0.30,
                "lighting_signal": abs(signed_mean) >= 7.0 and mean_absolute >= 7.0,
                "cut_score": round(mean_absolute * (0.25 + changed_ratio), 6),
                "boxes": merge_boxes(boxes),
            }
        )
    return records


def build_proposals(
    features: list[dict[str, Any]], clip_id: str, scene_class: str
) -> dict[str, Any]:
    if not features:
        raise ValueError("transition features cannot be empty")
    ranked = sorted(
        features,
        key=lambda item: (-float(item["cut_score"]), int(item["transition_frame"])),
    )
    cut_candidates = [
        {
            "transition_frame": int(item["transition_frame"]),
            "next_frame": int(item["next_frame"]),
            "score": float(item["cut_score"]),
            "source": "largest_adjacent_frame_difference_proposal",
        }
        for item in ranked[:CUT_CANDIDATE_COUNT]
    ] if clip_id == "c07" else []

    # Fixed one-second windows keep review effort bounded and deterministic.
    # Semantic flags are aggregated inside each window rather than splitting a
    # clip whenever a noisy threshold toggles at one transition.
    groups = [
        features[index : index + PROPOSAL_INTERVAL_TRANSITIONS]
        for index in range(0, len(features), PROPOSAL_INTERVAL_TRANSITIONS)
    ]

    proposals: list[dict[str, Any]] = []
    cut_frames = {item["transition_frame"] for item in cut_candidates}
    for index, group in enumerate(groups):
        boxes = merge_boxes(box for item in group for box in item["boxes"])
        active = bool(boxes)
        cut_frames_in_group = sorted(
            int(item["transition_frame"])
            for item in group
            if item["transition_frame"] in cut_frames
        )
        proposals.append(
            {
                "proposal_id": f"{clip_id}-proposal-{index + 1:03d}",
                "start_frame": int(group[0]["transition_frame"]),
                "end_frame": int(group[-1]["next_frame"]),
                "source": "automatic_model_free_proposal",
                "review_status": "pending_review",
                "human_decision": "unreviewed",
                "boxes": boxes,
                "derived_stable": "full_canvas_complement_of_dirty_and_uncertain",
                "flags": {
                    "camera_motion": (
                        "candidate"
                        if active
                        and (
                            clip_id in CAMERA_DEFAULT_CLIPS
                            or any(item["global_motion_signal"] for item in group)
                        )
                        else "not_suggested"
                    ),
                    "occlusion": "candidate" if active and clip_id == "c08" else "not_suggested",
                    "disocclusion": "candidate" if active and clip_id == "c08" else "not_suggested",
                    "lighting_change": (
                        "candidate"
                        if active
                        and (
                            clip_id == "c11" or any(item["lighting_signal"] for item in group)
                        )
                        else "not_suggested"
                    ),
                    "scene_cut": "candidate" if cut_frames_in_group else "not_suggested",
                    "full_reobserve": "not_suggested",
                },
                "cut_candidate_frames": cut_frames_in_group,
                "metrics": {
                    "mean_absolute_difference_p50": round(
                        float(np.median([item["mean_absolute_difference"] for item in group])), 6
                    ),
                    "mean_absolute_difference_max": round(
                        max(float(item["mean_absolute_difference"]) for item in group), 6
                    ),
                    "changed_pixel_ratio_max": round(
                        max(float(item["changed_pixel_ratio"]) for item in group), 6
                    ),
                },
            }
        )

    validate_temporal_coverage(proposals, len(features) + 1)
    return {
        "clip_id": clip_id,
        "scene_class": scene_class,
        "frame_count": len(features) + 1,
        "fps": FPS,
        "proposal_status": "automatic_suggestion_pending_human_review",
        "review_progress": "unreviewed",
        "oracle_initial_pass": "pending_review",
        "blind_re_review": "pending_review",
        "adjudication": "pending_review",
        "final_status": "pending_review",
        "hard_cut_selected": None,
        "cut_candidates": cut_candidates,
        "proposals": proposals,
    }


def validate_temporal_coverage(proposals: list[dict[str, Any]], frame_count: int) -> None:
    if frame_count < 2 or not proposals:
        raise ValueError("temporal coverage requires proposals and at least two frames")
    expected = 0
    for proposal in proposals:
        start = int(proposal["start_frame"])
        end = int(proposal["end_frame"])
        if start != expected or end <= start or end >= frame_count:
            raise ValueError(f"invalid or missing proposal interval: expected {expected}, got {start}-{end}")
        expected = end
    if expected != frame_count - 1:
        raise ValueError(f"proposal intervals stop at {expected}, expected {frame_count - 1}")


def rectangles_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return not (
        left["x"] + left["width"] <= right["x"]
        or right["x"] + right["width"] <= left["x"]
        or left["y"] + left["height"] <= right["y"]
        or right["y"] + right["height"] <= left["y"]
    )


def derive_partition(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for box in boxes:
        if (
            box["state"] not in {"dirty", "uncertain"}
            or box["width"] <= 0
            or box["height"] <= 0
            or box["x"] < 0
            or box["y"] < 0
            or box["x"] + box["width"] > WIDTH
            or box["y"] + box["height"] > HEIGHT
        ):
            raise ValueError(f"invalid proposal box: {box}")
    for index, left in enumerate(boxes):
        for right in boxes[index + 1 :]:
            if rectangles_overlap(left, right):
                raise ValueError("dirty/uncertain boxes overlap")
    x_edges = sorted({0, WIDTH, *(int(box["x"]) for box in boxes), *(int(box["x"] + box["width"]) for box in boxes)})
    y_edges = sorted({0, HEIGHT, *(int(box["y"]) for box in boxes), *(int(box["y"] + box["height"]) for box in boxes)})
    partition: list[dict[str, Any]] = []
    for y0, y1 in zip(y_edges, y_edges[1:]):
        for x0, x1 in zip(x_edges, x_edges[1:]):
            middle_x = (x0 + x1) / 2
            middle_y = (y0 + y1) / 2
            owner = next(
                (
                    box
                    for box in boxes
                    if box["x"] <= middle_x < box["x"] + box["width"]
                    and box["y"] <= middle_y < box["y"] + box["height"]
                ),
                None,
            )
            partition.append(
                {
                    "x": x0,
                    "y": y0,
                    "width": x1 - x0,
                    "height": y1 - y0,
                    "state": owner["state"] if owner else "stable",
                    "source": "human_confirmed_or_derived_stable_complement",
                }
            )
    if sum(item["width"] * item["height"] for item in partition) != WIDTH * HEIGHT:
        raise AssertionError("derived partition does not cover the full canvas")
    return partition


def render_html(clips: list[dict[str, Any]]) -> str:
    payload = json.dumps(clips, ensure_ascii=False, separators=(",", ":"))
    html = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HIVEFRAME M1-A2 안내형 Oracle 1차 검수</title>
<style>
:root{font-family:system-ui,"Malgun Gothic",sans-serif;color:#172033;background:#eef2f7}*{box-sizing:border-box}body{margin:0}header{padding:18px 24px;background:#10213d;color:#fff}header h1{margin:0 0 8px;font-size:23px}main{max-width:1500px;margin:auto;padding:18px}.notice{background:#fff4ce;border:1px solid #d8ad22;border-radius:9px;padding:11px;margin:0 0 14px}.steps{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:12px 0}.steps div{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:9px;text-align:center;font-size:13px}.layout{display:grid;grid-template-columns:minmax(680px,2fr) minmax(390px,1fr);gap:14px}.card{background:#fff;border:1px solid #d8e0eb;border-radius:11px;padding:14px;box-shadow:0 2px 8px #0000000b}.row{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:8px 0}button,select,textarea{font:inherit}button{border:1px solid #93a1b5;background:#f8fafc;border-radius:7px;padding:8px 11px;cursor:pointer}button.primary{background:#2457d6;border-color:#2457d6;color:#fff}button.good{background:#e6f7ea;border-color:#55a868}button.warn{background:#fff4ce;border-color:#d8ad22}button.bad{background:#fdeaea;border-color:#d45b5b}button:disabled{opacity:.45;cursor:not-allowed}.badge{padding:5px 8px;border-radius:999px;background:#e8eef7;font-size:12px;font-weight:700}.badge.done{background:#dff4e5;color:#155724}.badge.edit{background:#fff0d4;color:#744c00}.compare{display:grid;grid-template-columns:1fr 1fr;gap:10px}.frame{position:relative;aspect-ratio:832/480;background:#111;border-radius:8px;overflow:hidden}.frame canvas{width:100%;height:100%}.overlay{position:absolute;inset:0}.box{position:absolute;border:3px solid #ff3b30;background:#ff3b3022;cursor:move;min-width:8px;min-height:8px}.box.uncertain{border-color:#ffd60a;background:#ffd60a33}.box.selected{outline:3px solid #2b6fff}.handle{position:absolute;width:14px;height:14px;right:-7px;bottom:-7px;background:#fff;border:2px solid currentColor;cursor:nwse-resize}.video-wrap{margin-top:10px}video{width:100%;max-height:330px;background:#111;border-radius:8px}.status{background:#f0f4fa;border-radius:7px;padding:8px;font-family:ui-monospace,monospace;font-size:13px}.decision{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.flags{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin:9px 0}.flags label{border:1px solid #d7deea;border-radius:6px;padding:7px}.cut-list{display:grid;grid-template-columns:1fr 1fr;gap:5px}.cut-list button.selected{background:#dfeaff;border-color:#2457d6}.progress{height:10px;background:#e7ebf2;border-radius:99px;overflow:hidden}.progress span{display:block;height:100%;background:#2d6cdf}.errors{color:#9b1c1c;white-space:pre-wrap}.ok{color:#166534}.small{font-size:12px;color:#536178}.proposal-list{max-height:210px;overflow:auto;border:1px solid #d8e0eb;border-radius:7px}.proposal-list button{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid #e5e9f0;border-radius:0}.proposal-list button.active{background:#e5edff}.exports{margin-top:14px}.hidden{display:none}@media(max-width:1050px){.layout{grid-template-columns:1fr}.steps{grid-template-columns:1fr}.compare{grid-template-columns:1fr}}
</style></head><body>
<header><h1>HIVEFRAME M1-A2 안내형 Oracle 1차 검수</h1><div>자동 변화 후보를 확인하고 필요한 부분만 고치세요. 자동 제안은 정답이 아니며 모든 출력은 pending_review입니다.</div></header>
<main>
<p class="notice"><b>중요:</b> 권리·장면·개인정보 1차 검수 12/12는 보존됩니다. 이 화면은 Oracle 초안을 사람이 확인하기 위한 도구입니다. verified, eligible, blind 재검수, adjudication 또는 topology 실행을 만들지 않습니다.</p>
<div class="steps"><div>1. 영상 선택</div><div>2. 후보 재생·A/B 비교</div><div>3. 맞음/수정/어려움 선택</div><div>4. 필요한 박스만 조정</div><div>5. 클립 완료 후 내보내기</div></div>
<div class="layout"><section class="card">
<div class="row"><label>영상 <select id="clip"></select></label><span id="clipStatus" class="badge"></span><span id="scene" class="small"></span></div>
<div class="progress"><span id="progressBar"></span></div><div id="progressText" class="small"></div>
<div class="row"><button id="prevProposal">이전 후보</button><button id="nextProposal">다음 후보</button><button id="playProposal" class="primary">후보 구간 재생</button><span id="range" class="status"></span></div>
<div class="compare"><div><b>A 이전 프레임</b><div class="frame"><canvas id="frameA" width="832" height="480"></canvas></div></div><div><b>B 이후 프레임 + 자동 후보</b><div class="frame" id="frameBWrap"><canvas id="frameB" width="832" height="480"></canvas><div id="boxes" class="overlay"></div></div></div></div>
<div class="video-wrap"><video id="video" controls preload="metadata"></video><div class="row"><button id="back">-1 프레임</button><button id="forward">+1 프레임</button><span id="videoPos" class="status"></span></div></div>
</section><aside class="card">
<h2>현재 자동 제안</h2><div id="metrics" class="status"></div>
<div class="decision"><button id="accept" class="good">제안이 맞음</button><button id="edit" class="warn">수정 필요</button><button id="uncertain" class="bad">판단 어려움</button></div>
<p class="small">박스를 클릭해 선택한 뒤 드래그로 이동하고 오른쪽 아래 손잡이로 크기를 조절합니다. 좌표를 입력할 필요가 없습니다.</p>
<div class="row"><button id="addDirty">dirty 박스 추가</button><button id="addUncertain">uncertain 박스 추가</button><button id="deleteBox">선택 박스 삭제</button></div>
<div class="flags"><label><input id="camera" type="checkbox"> 카메라 전역 움직임</label><label><input id="occ" type="checkbox"> occlusion</label><label><input id="disocc" type="checkbox"> disocclusion</label><label><input id="lighting" type="checkbox"> 조명 변화</label><label><input id="sceneCut" type="checkbox"> scene cut</label><label><input id="reobserve" type="checkbox"> full reobserve</label></div>
<label>메모<textarea id="notes" rows="3" style="width:100%" placeholder="판단 근거나 수정 이유를 적습니다."></textarea></label>
<div id="c07Panel" class="notice hidden"><b>C07 hard-cut 후보</b><p class="small">차이가 큰 전환을 순서대로 제시합니다. 정확한 한 지점을 선택하세요.</p><div id="cutCandidates" class="cut-list"></div><button id="selectCurrentCut">현재 재생 위치의 전환 선택</button><div id="cutSelected" class="status"></div></div>
<h3>후보 목록</h3><div id="proposalList" class="proposal-list"></div>
<button id="completeClip" class="primary" style="width:100%;margin-top:10px">클립 1차 검수 완료</button><div id="validation" class="errors"></div>
</aside></div>
<section class="card exports"><div class="row"><b id="allStatus">전체 진행 상태</b><button id="exportJson">JSON 내보내기</button><button id="exportCsv">CSV 내보내기</button><button id="reset">모든 입력 초기화</button></div><p class="small">C01-C12 모두 완료되어야 내보낼 수 있습니다. 출력의 oracle_initial_pass, blind_re_review, adjudication, final_status는 계속 pending_review입니다.</p></section>
<video id="videoA" class="hidden" muted preload="auto"></video><video id="videoB" class="hidden" muted preload="auto"></video>
<script>
const SOURCE_CLIPS=__CLIPS__,W=832,H=480,FPS=16,KEY='hiveframe-m1-a2-guided-oracle-v2';
const $=id=>document.getElementById(id),clone=x=>JSON.parse(JSON.stringify(x));
let clips=JSON.parse(localStorage.getItem(KEY)||'null')||clone(SOURCE_CLIPS),proposalIndex=0,selectedBox=null,drag=null;
const video=$('video'),videoA=$('videoA'),videoB=$('videoB');
function clip(){return clips.find(x=>x.clip_id===$('clip').value)} function proposal(){return clip().proposals[proposalIndex]}
function save(){localStorage.setItem(KEY,JSON.stringify(clips));renderProgress()}
function clipLabel(c){const done=c.review_progress==='initial_review_complete';const edit=c.proposals.some(p=>p.human_decision==='needs_edit');return done?'1차 검수 완료':edit?'수정 필요':c.proposals.some(p=>p.human_decision!=='unreviewed')?'검수 중':'미검수'}
function loadClip(){const c=clip();proposalIndex=0;selectedBox=null;const src=c.proxy;video.src=src;videoA.src=src;videoB.src=src;$('scene').textContent=c.scene_class;$('c07Panel').classList.toggle('hidden',c.clip_id!=='c07');renderAll()}
function seekDraw(v,canvas,frame){const draw=()=>canvas.getContext('2d').drawImage(v,0,0,W,H);v.onseeked=draw;if(v.readyState>=1){v.currentTime=Math.min((v.duration||1)-.001,frame/FPS)}else{v.onloadedmetadata=()=>{v.currentTime=Math.min((v.duration||1)-.001,frame/FPS)}}}
function renderFrames(){const p=proposal();seekDraw(videoA,$('frameA'),p.start_frame);seekDraw(videoB,$('frameB'),p.end_frame);$('range').textContent=`${p.start_frame} → ${p.end_frame} 프레임`;renderBoxes()}
function renderBoxes(){$('boxes').innerHTML='';proposal().boxes.forEach((b,i)=>{const d=document.createElement('div');d.className='box '+(b.state==='uncertain'?'uncertain ':'')+(selectedBox===i?'selected':'');d.style.left=100*b.x/W+'%';d.style.top=100*b.y/H+'%';d.style.width=100*b.width/W+'%';d.style.height=100*b.height/H+'%';d.title=`${b.state} 자동 제안`;d.onpointerdown=e=>startDrag(e,i,false);const h=document.createElement('span');h.className='handle';h.onpointerdown=e=>startDrag(e,i,true);d.appendChild(h);$('boxes').appendChild(d)})}
function startDrag(e,index,resize){e.preventDefault();e.stopPropagation();selectedBox=index;const b=proposal().boxes[index];drag={index,resize,startX:e.clientX,startY:e.clientY,box:clone(b)};document.onpointermove=moveDrag;document.onpointerup=endDrag;renderBoxes()}
function moveDrag(e){if(!drag)return;const r=$('boxes').getBoundingClientRect(),dx=(e.clientX-drag.startX)*W/r.width,dy=(e.clientY-drag.startY)*H/r.height,b=proposal().boxes[drag.index];if(drag.resize){b.width=Math.max(8,Math.min(W-drag.box.x,Math.round(drag.box.width+dx)));b.height=Math.max(8,Math.min(H-drag.box.y,Math.round(drag.box.height+dy)))}else{b.x=Math.max(0,Math.min(W-b.width,Math.round(drag.box.x+dx)));b.y=Math.max(0,Math.min(H-b.height,Math.round(drag.box.y+dy)))}renderBoxes()}
function endDrag(){if(drag){proposal().human_decision='modified';proposal().source='human_modified_automatic_proposal';clip().review_progress='in_progress';save()}drag=null;document.onpointermove=null;document.onpointerup=null;renderAll()}
function renderFlags(){const f=proposal().flags;$('camera').checked=f.camera_motion==='confirmed'||f.camera_motion==='candidate';$('occ').checked=f.occlusion==='confirmed'||f.occlusion==='candidate';$('disocc').checked=f.disocclusion==='confirmed'||f.disocclusion==='candidate';$('lighting').checked=f.lighting_change==='confirmed'||f.lighting_change==='candidate';$('sceneCut').checked=f.scene_cut==='confirmed';$('reobserve').checked=f.full_reobserve==='confirmed';$('notes').value=proposal().notes||''}
function storeFlags(){const p=proposal();p.flags={camera_motion:$('camera').checked?'confirmed':'not_confirmed',occlusion:$('occ').checked?'confirmed':'not_confirmed',disocclusion:$('disocc').checked?'confirmed':'not_confirmed',lighting_change:$('lighting').checked?'confirmed':'not_confirmed',scene_cut:$('sceneCut').checked?'confirmed':'not_confirmed',full_reobserve:$('reobserve').checked?'confirmed':'not_confirmed'};p.notes=$('notes').value.trim();if(p.human_decision==='unreviewed')p.human_decision='modified';clip().review_progress='in_progress';save()}
function renderMetrics(){const m=proposal().metrics;$('metrics').textContent=`자동 제안 · 변화량 max ${m.mean_absolute_difference_max.toFixed(2)} · changed ratio max ${(100*m.changed_pixel_ratio_max).toFixed(1)}% · 박스 ${proposal().boxes.length}개 · stable은 여집합 자동 생성`}
function renderList(){$('proposalList').innerHTML='';clip().proposals.forEach((p,i)=>{const b=document.createElement('button');b.className=i===proposalIndex?'active':'';b.textContent=`${i+1}. ${p.start_frame}→${p.end_frame} · ${p.human_decision==='unreviewed'?'미검수':p.human_decision}`;b.onclick=()=>{proposalIndex=i;selectedBox=null;renderAll()};$('proposalList').appendChild(b)})}
function renderCut(){if(clip().clip_id!=='c07')return;$('cutCandidates').innerHTML='';clip().cut_candidates.forEach(c=>{const b=document.createElement('button');b.textContent=`${c.transition_frame}→${c.next_frame}`;b.className=clip().hard_cut_selected===c.transition_frame?'selected':'';b.onclick=()=>selectCut(c.transition_frame);$('cutCandidates').appendChild(b)});$('cutSelected').textContent=clip().hard_cut_selected===null?'아직 선택하지 않음':`선택: ${clip().hard_cut_selected}→${clip().hard_cut_selected+1}`}
function selectCut(frame){clip().hard_cut_selected=frame;clip().hard_cut_override={start_frame:frame,end_frame:frame+1,partition:[{x:0,y:0,width:W,height:H,state:'dirty',source:'human_selected_hard_cut'}],scene_cut:true,full_reobserve:true,review_status:'pending_review'};clip().review_progress='in_progress';clip().proposals.forEach(x=>{x.flags.scene_cut='not_confirmed';x.flags.full_reobserve='not_confirmed'});const p=clip().proposals.find(x=>x.start_frame<=frame&&frame<x.end_frame);if(p){p.flags.scene_cut='confirmed';p.flags.full_reobserve='confirmed';p.human_decision=p.human_decision==='unreviewed'?'modified':p.human_decision}save();renderAll()}
function renderProgress(){const c=clip(),done=c.proposals.filter(p=>p.human_decision!=='unreviewed').length,total=c.proposals.length;$('progressBar').style.width=100*done/total+'%';$('progressText').textContent=`후보 ${done}/${total} 확인`;$('clipStatus').textContent=clipLabel(c);$('clipStatus').className='badge '+(c.review_progress==='initial_review_complete'?'done':c.proposals.some(p=>p.human_decision==='needs_edit')?'edit':'');const allDone=clips.filter(x=>x.review_progress==='initial_review_complete').length;$('allStatus').textContent=`C01-C12 중 ${allDone}/12 클립 1차 검수 완료`}
function renderAll(){renderFrames();renderFlags();renderMetrics();renderList();renderCut();renderProgress();$('validation').textContent=''}
function decide(value){const p=proposal();clip().review_progress='in_progress';if(value==='accepted'){p.human_decision=(p.source==='human_modified_automatic_proposal'||p.human_decision==='modified')?'modified':'accepted';Object.keys(p.flags).forEach(k=>p.flags[k]=p.flags[k]==='candidate'?(clip().clip_id==='c07'&&k==='scene_cut'?'not_confirmed':'confirmed'):p.flags[k]==='not_suggested'?'not_confirmed':p.flags[k])}else if(value==='uncertain'){p.human_decision='uncertain';p.boxes=[{box_id:'human-uncertain-full',x:0,y:0,width:W,height:H,state:'uncertain',source:'human_uncertain_decision'}];Object.keys(p.flags).forEach(k=>p.flags[k]='uncertain')}else{p.human_decision='needs_edit'}save();if(value!=='needs_edit'&&proposalIndex<clip().proposals.length-1)proposalIndex++;renderAll()}
function addBox(state){const p=proposal();p.boxes.push({box_id:'human-'+Date.now(),x:Math.round(W*.3),y:Math.round(H*.3),width:Math.round(W*.4),height:Math.round(H*.4),state,source:'human_added'});p.human_decision='modified';p.source='human_modified_automatic_proposal';clip().review_progress='in_progress';selectedBox=p.boxes.length-1;save();renderAll()}
function deleteBox(){if(selectedBox===null)return;proposal().boxes.splice(selectedBox,1);proposal().human_decision='modified';proposal().source='human_modified_automatic_proposal';selectedBox=null;save();renderAll()}
function overlap(a,b){return !(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y)}
function partition(boxes){for(let i=0;i<boxes.length;i++){const b=boxes[i];if(!['dirty','uncertain'].includes(b.state)||b.x<0||b.y<0||b.width<=0||b.height<=0||b.x+b.width>W||b.y+b.height>H)throw Error('박스 범위가 올바르지 않습니다.');for(let j=i+1;j<boxes.length;j++)if(overlap(b,boxes[j]))throw Error('dirty/uncertain 박스가 겹칩니다. 박스를 이동하거나 삭제하세요.')}const xs=[...new Set([0,W,...boxes.flatMap(b=>[b.x,b.x+b.width])])].sort((a,b)=>a-b),ys=[...new Set([0,H,...boxes.flatMap(b=>[b.y,b.y+b.height])])].sort((a,b)=>a-b),out=[];for(let yi=0;yi<ys.length-1;yi++)for(let xi=0;xi<xs.length-1;xi++){const x=xs[xi],y=ys[yi],w=xs[xi+1]-x,h=ys[yi+1]-y,mx=x+w/2,my=y+h/2,owner=boxes.find(b=>b.x<=mx&&mx<b.x+b.width&&b.y<=my&&my<b.y+b.height);out.push({x,y,width:w,height:h,state:owner?owner.state:'stable',source:owner?'human_confirmed_or_modified_proposal':'derived_stable_complement'})}if(out.reduce((s,r)=>s+r.width*r.height,0)!==W*H)throw Error('전체 화면 분할에 누락이 있습니다.');return out}
function validateClip(c){const errors=[];let expected=0;c.proposals.forEach((p,i)=>{if(p.start_frame!==expected||p.end_frame<=p.start_frame||p.end_frame>=c.frame_count)errors.push(`후보 ${i+1}: 프레임 범위/누락 오류`);expected=p.end_frame;if(p.human_decision==='unreviewed'||p.human_decision==='needs_edit')errors.push(`후보 ${i+1}: 확인 또는 수정 완료 필요`);if(Object.values(p.flags).includes('candidate'))errors.push(`후보 ${i+1}: 의미 후보를 맞음/수정/어려움으로 확인해야 합니다.`);try{p.derived_partition=partition(p.boxes)}catch(e){errors.push(`후보 ${i+1}: ${e.message}`)}});if(expected!==c.frame_count-1)errors.push('마지막 프레임 전환까지 검수되지 않았습니다.');if(c.clip_id==='c07'){const confirmedCuts=c.proposals.filter(p=>p.flags.scene_cut==='confirmed'&&p.flags.full_reobserve==='confirmed');if(c.hard_cut_selected===null)errors.push('C07 hard-cut 한 지점을 선택해야 합니다.');else if(confirmedCuts.length!==1)errors.push('C07 scene cut과 full reobserve는 선택한 한 구간에만 있어야 합니다.');else{c.hard_cut_override={start_frame:c.hard_cut_selected,end_frame:c.hard_cut_selected+1,partition:[{x:0,y:0,width:W,height:H,state:'dirty',source:'human_selected_hard_cut'}],scene_cut:true,full_reobserve:true,review_status:'pending_review'}}}return errors}
function completeClip(){const errors=validateClip(clip());if(errors.length){clip().review_progress=clip().proposals.some(p=>p.human_decision==='needs_edit')?'needs_edit':'in_progress';$('validation').className='errors';$('validation').textContent=errors.join('\n');save();return}clip().review_progress='initial_review_complete';$('validation').className='ok';$('validation').textContent='이 클립의 1차 입력이 완성되었습니다. 상태는 여전히 pending_review입니다.';save();renderProgress()}
function exported(){return {schema_version:'guided-review-draft-0.2.0',review_phase:'oracle_initial_pass',proposal_method:'model_free_adjacent_frame_difference',automatic_proposals_are_truth:false,verification_status:'pending_review',oracle_initial_pass:'pending_review',blind_re_review:'pending_review',adjudication:'pending_review',final_status:'pending_review',eligible_clips:0,verified_oracles:0,clips:clips.map(c=>{c.proposals.forEach(p=>p.derived_partition=partition(p.boxes));return c})}}
function ensureAll(){const incomplete=clips.filter(c=>c.review_progress!=='initial_review_complete');if(incomplete.length){alert(`먼저 모든 클립을 완료하세요: ${incomplete.map(c=>c.clip_id.toUpperCase()).join(', ')}`);return false}return true}
function download(name,type,text){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
function exportJson(){if(!ensureAll())return;download('m1-a2-guided-oracle-initial.pending.json','application/json',JSON.stringify(exported(),null,2)+'\n')}
function csvCell(v){const s=String(v??'');return /[",\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s}
function exportCsv(){if(!ensureAll())return;const rows=[],cols=['clip_id','proposal_id','start_frame','end_frame','human_decision','region_state','region_x','region_y','region_width','region_height','camera_motion','occlusion','disocclusion','lighting_change','scene_cut','full_reobserve','review_progress','oracle_initial_pass','verification_status'];exported().clips.forEach(c=>c.proposals.forEach(p=>p.derived_partition.forEach(r=>rows.push({clip_id:c.clip_id,proposal_id:p.proposal_id,start_frame:p.start_frame,end_frame:p.end_frame,human_decision:p.human_decision,region_state:r.state,region_x:r.x,region_y:r.y,region_width:r.width,region_height:r.height,camera_motion:p.flags.camera_motion,occlusion:p.flags.occlusion,disocclusion:p.flags.disocclusion,lighting_change:p.flags.lighting_change,scene_cut:p.flags.scene_cut,full_reobserve:p.flags.full_reobserve,review_progress:c.review_progress,oracle_initial_pass:'pending_review',verification_status:'pending_review'}))));download('m1-a2-guided-oracle-initial.pending.csv','text/csv;charset=utf-8','\ufeff'+cols.join(',')+'\n'+rows.map(r=>cols.map(k=>csvCell(r[k])).join(',')).join('\n')+'\n')}
clips.forEach(c=>{const o=document.createElement('option');o.value=c.clip_id;o.textContent=c.clip_id.toUpperCase();$('clip').appendChild(o)});$('clip').onchange=loadClip;$('prevProposal').onclick=()=>{proposalIndex=Math.max(0,proposalIndex-1);selectedBox=null;renderAll()};$('nextProposal').onclick=()=>{proposalIndex=Math.min(clip().proposals.length-1,proposalIndex+1);selectedBox=null;renderAll()};$('playProposal').onclick=()=>{video.currentTime=proposal().start_frame/FPS;video.play()};video.ontimeupdate=()=>{if(video.currentTime>=proposal().end_frame/FPS)video.pause();$('videoPos').textContent=`${video.currentTime.toFixed(3)}초 · frame ${Math.round(video.currentTime*FPS)}`};$('back').onclick=()=>{video.pause();video.currentTime=Math.max(0,video.currentTime-1/FPS)};$('forward').onclick=()=>{video.pause();video.currentTime=Math.min(video.duration||1e9,video.currentTime+1/FPS)};$('accept').onclick=()=>decide('accepted');$('edit').onclick=()=>decide('needs_edit');$('uncertain').onclick=()=>decide('uncertain');$('addDirty').onclick=()=>addBox('dirty');$('addUncertain').onclick=()=>addBox('uncertain');$('deleteBox').onclick=deleteBox;['camera','occ','disocc','lighting','sceneCut','reobserve'].forEach(id=>$(id).onchange=storeFlags);$('notes').onchange=storeFlags;$('selectCurrentCut').onclick=()=>selectCut(Math.max(0,Math.min(clip().frame_count-2,Math.round(video.currentTime*FPS)-1)));$('completeClip').onclick=completeClip;$('exportJson').onclick=exportJson;$('exportCsv').onclick=exportCsv;$('reset').onclick=()=>{if(confirm('저장된 모든 검수 입력을 초기화할까요?')){localStorage.removeItem(KEY);clips=clone(SOURCE_CLIPS);proposalIndex=0;$('clip').value='c01';loadClip()}};loadClip();
</script></main></body></html>'''
    return html.replace("__CLIPS__", payload)


def method_receipt(clips: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "package_kind": "m1_a2_guided_human_oracle_review",
        "supersedes": "m1_a2_oracle_initial_human_review_v1_manual_entry_ui",
        "proposal_status": "automatic_suggestion_only",
        "automatic_proposals_are_truth": False,
        "review_status": "pending_review",
        "oracle_initial_pass": "pending_review",
        "blind_re_review": "pending_review",
        "adjudication": "pending_review",
        "final_status": "pending_review",
        "eligible_clips": 0,
        "verified_oracles": 0,
        "gate": "RIGHTS_REVIEW_BLOCKED",
        "results_eligible_for_topology_performance": False,
        "method": {
            "decoder": "FFmpeg CPU grayscale rawvideo",
            "comparison": "adjacent-frame absolute grayscale difference",
            "low_resolution": [LOW_WIDTH, LOW_HEIGHT],
            "pixel_threshold": PIXEL_THRESHOLD,
            "tile_size": TILE,
            "tile_change_ratio": TILE_CHANGE_RATIO,
            "tile_mean_threshold": TILE_MEAN_THRESHOLD,
            "strong_tile_mean": STRONG_TILE_MEAN,
            "proposal_interval_transitions": PROPOSAL_INTERVAL_TRANSITIONS,
            "region_extraction": "thresholded tiles, four-connected components, padded bounding boxes, overlap merge",
            "stable_semantics": "derived full-canvas complement of non-overlapping dirty/uncertain boxes",
            "cut_candidates": "largest adjacent-frame cut scores; human selects exactly one C07 transition",
            "limitations": [
                "Compression noise, shadows, reflections, and texture may create false positives.",
                "Small or low-contrast motion may be missed or marked uncertain.",
                "Camera, lighting, occlusion, and cut flags are review suggestions, not semantic inference truth.",
                "Bounding boxes are coarse low-resolution proposals and require human confirmation or correction.",
            ],
        },
        "clips": clips,
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


def plan(config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    return {
        "execution_started": False,
        "clips": len(config["clips"]),
        "output_reference": "approved-asset:m1-a2/review-package/oracle-guided-review-v2",
        "output_exists": output_dir.exists(),
        "automatic_proposals": "model_free_adjacent_frame_difference_suggestions",
        "automatic_proposals_are_truth": False,
        "oracle_initial_pass": "pending_review",
        "blind_re_review": "pending_review",
        "adjudication": "pending_review",
        "final_status": "pending_review",
        "eligible_clips": 0,
        "verified_oracles": 0,
        "gate": "RIGHTS_REVIEW_BLOCKED",
        "model_loads": 0,
        "cuda_runs": 0,
        "backend_integration_runs": 0,
        "topology_performance_runs": 0,
    }


def create(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite guided review package: {args.output_dir}")
    temporary = args.output_dir.with_name(args.output_dir.name + ".building")
    if temporary.exists():
        raise FileExistsError(f"temporary package already exists: {temporary}")
    temporary.mkdir(parents=True)
    try:
        clips: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        for item in config["clips"]:
            clip_id = item["clip_id"]
            derivative = args.derivative_dir / f"{clip_id}-analysis-832x480-16fps-ffv1.mkv"
            proxy = args.proxy_dir / f"{clip_id}-review.mp4"
            if not derivative.is_file() or not proxy.is_file():
                raise FileNotFoundError(f"required derivative or proxy missing: {clip_id}")
            features = transition_features(decode_grayscale(args.ffmpeg, derivative))
            clip = build_proposals(features, clip_id, item["scene_class"])
            clip["proxy"] = f"../oracle-initial-review/proxies/{clip_id}-review.mp4"
            clips.append(clip)
            summaries.append(
                {
                    "clip_id": clip_id,
                    "source_derivative_sha256": sha256_file(derivative),
                    "frame_count": clip["frame_count"],
                    "proposal_intervals": len(clip["proposals"]),
                    "dirty_boxes": sum(
                        box["state"] == "dirty"
                        for proposal in clip["proposals"]
                        for box in proposal["boxes"]
                    ),
                    "uncertain_boxes": sum(
                        box["state"] == "uncertain"
                        for proposal in clip["proposals"]
                        for box in proposal["boxes"]
                    ),
                    "cut_candidates": len(clip["cut_candidates"]),
                    "proposal_status": "automatic_suggestion_pending_human_review",
                    "review_status": "pending_review",
                    "eligible": False,
                }
            )
        proposal_document = {
            "schema_version": "guided-proposal-0.2.0",
            "proposal_method": "model_free_adjacent_frame_difference",
            "automatic_proposals_are_truth": False,
            "oracle_initial_pass": "pending_review",
            "blind_re_review": "pending_review",
            "adjudication": "pending_review",
            "final_status": "pending_review",
            "clips": clips,
        }
        (temporary / "proposals.pending.json").write_text(
            canonical_json(proposal_document), encoding="utf-8", newline="\n"
        )
        html = render_html(clips)
        if "https://" in html or "http://" in html:
            raise ValueError("guided review HTML must remain offline")
        (temporary / "oracle-review.html").write_text(html, encoding="utf-8", newline="\n")
        receipt = method_receipt(summaries)
        receipt["proposal_document_sha256"] = sha256_file(temporary / "proposals.pending.json")
        (temporary / "package-receipt.json").write_text(
            canonical_json(receipt), encoding="utf-8", newline="\n"
        )
        (temporary / "사용방법.md").write_text(
            "# M1-A2 안내형 Oracle 1차 검수\n\n"
            "1. `oracle-review.html`을 Edge 또는 Chrome으로 엽니다.\n"
            "2. C01부터 선택하고 `후보 구간 재생`으로 A/B 및 overlay를 봅니다.\n"
            "3. `제안이 맞음`, `수정 필요`, `판단 어려움` 중 하나를 누릅니다.\n"
            "4. 수정 시 박스를 드래그·크기 조절·삭제·추가합니다. stable은 자동 여집합입니다.\n"
            "5. C07에서는 정확한 hard-cut 한 지점을 선택합니다.\n"
            "6. 각 클립에서 `클립 1차 검수 완료`를 누릅니다.\n"
            "7. 12개가 모두 완료되면 JSON과 CSV를 내보냅니다.\n\n"
            "자동 제안과 내보낸 결과는 verified 정답이 아니며 계속 `pending_review`입니다.\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(args.output_dir)
        args.public_receipt.write_text(
            canonical_json(receipt), encoding="utf-8", newline="\n"
        )
        args.superseded_marker.write_text(
            "# Superseded review UI\n\n"
            "This manual-entry v1 UI is preserved as usability evidence and must not be used for new Oracle input.\n"
            "Use the sibling `oracle-guided-review-v2/oracle-review.html` package instead. "
            "No v1 review row or export was supplied by the reviewer.\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "package_created": True,
            "clips": len(clips),
            "proposal_intervals": sum(len(clip["proposals"]) for clip in clips),
            "dirty_boxes": sum(item["dirty_boxes"] for item in summaries),
            "uncertain_boxes": sum(item["uncertain_boxes"] for item in summaries),
            "c07_cut_candidates": len(next(clip for clip in clips if clip["clip_id"] == "c07")["cut_candidates"]),
            "automatic_proposals_are_truth": False,
            "oracle_initial_pass": "pending_review",
            "eligible_clips": 0,
            "verified_oracles": 0,
            "gate": "RIGHTS_REVIEW_BLOCKED",
            "topology_performance_runs": 0,
        }
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--derivative-dir", type=Path, required=True)
    parser.add_argument("--proxy-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--public-receipt", type=Path, required=True)
    parser.add_argument("--superseded-marker", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = plan(config, args.output_dir) if args.plan else create(args, config)
    print(canonical_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
