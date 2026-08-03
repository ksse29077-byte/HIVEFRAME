from __future__ import annotations

import json
from pathlib import Path
import unittest

from hive_benchmarks.m1_a2_oracle_review import (
    plan,
    proxy_command,
    render_html,
    review_instructions,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "configs" / "m1-a2-assets.json").read_text(encoding="utf-8"))


class M1A2OracleReviewTests(unittest.TestCase):
    def test_proxy_command_is_cpu_local_nonoverwriting_and_audio_free(self) -> None:
        command = proxy_command(Path("ffmpeg"), Path("input.mkv"), Path("output.mp4"))
        rendered = " ".join(map(str, command))
        self.assertIn("-n", command)
        self.assertNotIn("-y", command)
        self.assertIn("libx264", command)
        self.assertIn("-an", command)
        self.assertIn("-threads 1", rendered)
        self.assertNotIn("cuda", rendered.lower())
        self.assertNotIn("model", rendered.lower())

    def test_html_is_offline_human_controlled_and_pending(self) -> None:
        clips = [
            {
                "clip_id": item["clip_id"],
                "scene_class": item["scene_class"],
                "proxy": f"proxies/{item['clip_id']}-review.mp4",
                "frame_count": 20,
            }
            for item in CONFIG["clips"]
        ]
        html = render_html(clips)
        self.assertNotIn("https://", html)
        self.assertNotIn("http://", html)
        self.assertIn("-1 프레임", html)
        self.assertIn("+1 프레임", html)
        self.assertIn("dirty — 변화", html)
        self.assertIn("stable — 정지", html)
        self.assertIn("uncertain — 판단 어려움", html)
        self.assertIn("occlusion", html)
        self.assertIn("disocclusion", html)
        self.assertIn("scene cut", html)
        self.assertIn("full reobserve", html)
        self.assertIn("JSON 내보내기", html)
        self.assertIn("CSV 내보내기", html)
        self.assertIn("pending_review", html)
        self.assertIn("C07에서는 정확한 hard-cut", html)
        self.assertNotIn("verified_oracle", html)

    def test_plan_never_starts_review_or_topology(self) -> None:
        payload = plan(CONFIG, Path("review"))
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["clips"], 12)
        self.assertFalse(payload["automatic_oracle_suggestions"])
        self.assertEqual(payload["oracle_initial_pass"], "pending_review")
        self.assertEqual(payload["blind_re_review"], "pending_review")
        self.assertEqual(payload["adjudication"], "pending_review")
        self.assertEqual(payload["final_status"], "pending_review")
        self.assertEqual(payload["model_loads"], 0)
        self.assertEqual(payload["cuda_runs"], 0)
        self.assertEqual(payload["topology_performance_runs"], 0)

    def test_korean_instructions_require_human_cut_and_later_review(self) -> None:
        instructions = review_instructions()
        self.assertIn("C07 hard cut", instructions)
        self.assertIn("JSON이나 좌표를", instructions)
        self.assertIn("blind 재검수", instructions)
        self.assertIn("자동으로 완료되지 않습니다", instructions)


if __name__ == "__main__":
    unittest.main()
