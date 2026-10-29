import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.record_daily import InputError, normalize, write_event


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class ProjectContractTests(unittest.TestCase):
    def test_exam_catalog_and_explicit_synthetic_metadata(self):
        catalog = read_json("data/exams/catalog.json")
        cases = read_json("tests/fixtures/acceptance_cases.json")
        expected = {"GK", "ZJ_GWY", "JX_GWY", "ZJ_SY", "JX_SY"}
        self.assertEqual({exam["id"] for exam in catalog["exams"]}, expected)
        self.assertEqual({case["exam_type"] for case in cases["exam_metadata"]}, expected)
        self.assertTrue(all(case["source_type"] == "synthetic_metadata_fixture" for case in cases["exam_metadata"]))
        self.assertTrue(all(case["official_source"] is False for case in cases["exam_metadata"]))
        self.assertTrue(all(case["year"] is None and case["paper_type"] is None for case in cases["exam_metadata"]))

    def test_provisional_taxonomy_and_relations_have_valid_ids(self):
        taxonomy = read_json("data/knowledge/index.json")
        relations = read_json("data/knowledge/relations.json")["relations"]
        nodes = {node["id"]: node for node in taxonomy["nodes"]}
        self.assertTrue(nodes)
        self.assertTrue(all(node["status"] == "provisional" for node in nodes.values()))
        self.assertTrue(all(node["source"] for node in nodes.values()))
        self.assertTrue(all(rel["from"] in nodes and rel["to"] in nodes for rel in relations))
        self.assertIn("DA-03-TWO-PERIOD-SHARE", nodes)

    def test_two_period_base_share_fixture_math_and_diagnosis_evidence(self):
        case = read_json("tests/fixtures/acceptance_cases.json")["data_analysis"]
        values = case["values"]
        prior = values["2023"]["sector"] / values["2023"]["whole"]
        current = values["2024"]["sector"] / values["2024"]["whole"]
        self.assertAlmostEqual(prior, 0.20)
        self.assertAlmostEqual(current, 0.24)
        self.assertAlmostEqual((current - prior) * 100, 4.0)
        self.assertEqual(case["expected_answer"], "A")
        self.assertEqual(case["diagnosis_probe"]["expected_error_reason"], "概念混淆")
        self.assertIn("明确说", case["diagnosis_probe"]["reason_evidence"])

    def test_original_cloze_answer_and_explanation_are_present(self):
        case = read_json("tests/fixtures/acceptance_cases.json")["cloze"]
        self.assertEqual(case["expected_answer"], "A")
        self.assertEqual(set(case["options"]), {"A", "B", "C", "D"})
        self.assertTrue(case["verified_explanation"])
        probe = case["diagnosis_probe"]
        self.assertEqual(probe["user_answer"], "C")
        self.assertEqual(probe["expected_error_reason"], "选项辨析不足")
        self.assertEqual(probe["skill_diagnosis_label"], "词义与搭配核验失误")
        self.assertIn("用户明确", probe["reason_evidence"])

    def test_implication_necessary_sufficient_contrapositive_and_contradiction(self):
        # P -> Q means P is sufficient for Q and Q is necessary for P.
        for p in (False, True):
            for q in (False, True):
                implication = (not p) or q
                contrapositive = q or (not p)  # not Q -> not P
                self.assertEqual(implication, contrapositive)
                self.assertEqual(not implication, p and (not q))
        p, q = False, True
        self.assertTrue((not p) or q)  # P -> Q
        self.assertFalse((not q) or p)  # Q -> P is not equivalent

    def test_no_verified_cross_exam_questions_are_claimed(self):
        case = read_json("tests/fixtures/acceptance_cases.json")["cross_exam_query"]
        self.assertEqual(case["verified_question_ids"], [])
        self.assertIn("不编造真题", case["expected_behavior"])
        self.assertFalse(any(p.is_file() and p.name != "README.md" and p.name != ".gitkeep" for p in (ROOT / "data/questions").iterdir()))

    def test_incomplete_items_and_skill_route_block_confirmed_writeback(self):
        cases = read_json("tests/fixtures/acceptance_cases.json")["incomplete_cases"]
        self.assertEqual({case["id"] for case in cases}, {"BLURRY", "MISSING_UNIT", "ANSWER_CONFLICT"})
        rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        xingce = (ROOT / ".agents/skills/xingce-review-pro/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("停止确定性判断及写回", rules)
        self.assertIn("只有用户答案已核验为错误", rules)
        self.assertIn("答案冲突", xingce)
        self.assertIn("不得" + "写", xingce)

    def test_cold_start_profile_is_persistent_but_has_no_assumed_goal(self):
        profile = (ROOT / "data/profile.md").read_text(encoding="utf-8")
        self.assertIn("当前目标考试：未知", profile)
        self.assertTrue((ROOT / "data/knowledge/index.json").is_file())
        self.assertTrue((ROOT / "data/reviews/README.md").is_file())

    def test_routing_uses_one_question_skill_and_separates_daily_summary(self):
        rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("行测单题讲解", rules)
        self.assertIn("只选一个主讲解 Skill", rules)
        self.assertIn("不能相加", rules)
        self.assertIn("scripts/record_daily.py", rules)

    def test_empty_acceptance_data_does_not_turn_fixtures_into_real_stats(self):
        fixture = read_json("tests/fixtures/acceptance_cases.json")
        self.assertIn("不计入个人学习档案", fixture["notice"])
        self.assertEqual(fixture["report_expectation"]["actual_study_records"], 0)
        self.assertIn("暂无真实学习数据", fixture["report_expectation"]["expected_behavior"])

    def test_daily_writer_is_idempotent_and_counts_independent_events_once(self):
        base = {
            "date": "2026-10-13",
            "event_id": "BATCH-20261013-A",
            "exam_type": "ZJ_SY",
            "province": "浙江",
            "source": "原创验收用模考A",
            "source_type": "training_simulation",
            "modules": {"职测": {"wrong": 3, "total": 20, "duration_minutes": 24}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            event = normalize(base)
            first = write_event(data_dir, event)
            duplicate = write_event(data_dir, normalize(base))
            path = data_dir / "daily/2026-10-13.json"
            day = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(day["schema_version"], 1)
            self.assertEqual(first["status"], "written")
            self.assertEqual(duplicate["status"], "noop")
            self.assertEqual(len(day["events"]), 1)
            self.assertEqual(day["modules"]["职测"]["wrong"], 3)
            self.assertEqual(day["modules"]["职测"]["accuracy_complete"], 1)

            second_batch = dict(base, event_id="BATCH-20261013-B", source="原创验收用模考B")
            write_event(data_dir, normalize(second_batch))
            day = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(day["events"]), 2)
            self.assertEqual(day["modules"]["职测"]["wrong"], 6)
            self.assertEqual(day["modules"]["职测"]["total"], 40)
            self.assertEqual(day["modules"]["职测"]["accuracy_complete"], 1)

    def test_daily_writer_upserts_same_event_and_keeps_different_dates_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            first = {"date": "2026-10-13", "event_id": "SESSION-1", "modules": {"资料分析": {"wrong": 2, "total": 10}}}
            write_event(data_dir, normalize(first))
            revised = dict(first, modules={"资料分析": {"wrong": 1, "total": 10}})
            receipt = write_event(data_dir, normalize(revised))
            self.assertEqual(receipt["status"], "updated")
            day1 = json.loads((data_dir / "daily/2026-10-13.json").read_text(encoding="utf-8"))
            self.assertEqual(len(day1["events"]), 1)
            self.assertEqual(day1["modules"]["资料分析"]["wrong"], 1)

            next_date = dict(first, date="2026-10-14", event_id="SESSION-2")
            write_event(data_dir, normalize(next_date))
            self.assertTrue((data_dir / "daily/2026-10-14.json").is_file())
            reused_id = dict(first, date="2026-10-14")
            with self.assertRaises(InputError):
                write_event(data_dir, normalize(reused_id))

    def test_daily_writer_upgrades_legacy_day_files_without_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            daily = data_dir / "daily"
            daily.mkdir(parents=True)
            legacy = {
                "date": "2026-10-12",
                "events": [{"date": "2026-10-12", "event_id": "LEGACY-1", "kind": "practice_batch", "exam_type": None, "province": None, "year": None, "paper_type": None, "source": None, "source_type": "unknown", "modules": {"言语理解": {"wrong": 2, "total": 10}}, "note": "", "recorded_at": "2026-10-12T20:00:00+08:00"}],
                "event_ids": ["LEGACY-1"],
                "modules": {"言语理解": {"wrong": 2, "total": 10, "accuracy_complete": 1}},
            }
            (daily / "2026-10-12.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            receipt = write_event(data_dir, normalize({"date": "2026-10-12", "event_id": "SESSION-2", "modules": {"资料分析": {"wrong": 1, "total": 5}}}))
            day = json.loads((daily / "2026-10-12.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "written")
            self.assertEqual(day["schema_version"], 1)
            self.assertEqual([item["event_id"] for item in day["events"]], ["LEGACY-1", "SESSION-2"])

    def test_daily_writer_rejects_unknown_newer_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            daily = data_dir / "daily"
            daily.mkdir(parents=True)
            future = {"schema_version": 2, "date": "2026-10-12", "events": [], "event_ids": [], "modules": {}}
            (daily / "2026-10-12.json").write_text(json.dumps(future, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(InputError):
                write_event(data_dir, normalize({"date": "2026-10-12", "event_id": "SESSION-X", "modules": {"资料分析": {"wrong": 1, "total": 5}}}))
            self.assertEqual(json.loads((daily / "2026-10-12.json").read_text(encoding="utf-8"))["schema_version"], 2)

    def test_exam_research_mount_links_resolve_when_mount_installed(self):
        mount = ROOT / ".agents/skills/xingce-review-pro/references/method-libraries/exam-research"
        index = mount / "INDEX.md"
        if not index.is_file():
            self.skipTest("exam-research mount 未安装（新克隆）；恢复流程见 README")
        self.assertFalse(index.is_symlink(), "INDEX.md 应是仓库内实体文件而非软链接")
        dangling = sorted(p.name for p in mount.iterdir() if p.is_symlink() and not p.exists())
        self.assertEqual(dangling, [], f"挂载软链接失效，故障会拖到讲题中途才暴露: {dangling}")

    def test_daily_writer_blocks_invalid_inputs_without_creating_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            for payload in (
                {"date": "2026-02-30", "modules": {"行测": {"wrong": 1}}},
                {"date": "2026-10-13", "exam_type": "UNKNOWN", "modules": {"行测": {"wrong": 1}}},
                {"date": "2026-10-13", "modules": {"行测": {"wrong": 4, "total": 3}}},
            ):
                with self.assertRaises(InputError):
                    normalize(payload)
            self.assertFalse((data_dir / "daily").exists())

    def test_xingce_writer_uses_data_directory_and_is_idempotent(self):
        script = ROOT / ".agents/skills/xingce-review-pro/scripts/writeback.py"
        payload = {
            "schema_version": 1,
            "event_id": "ACCEPTANCE-WRONG-001",
            "action": "wrong_answer",
            "date": "2026-10-13",
            "module": "资料分析",
            "question_type": "两期比重变化",
            "weakness_key": "DA-03-TWO-PERIOD-SHARE",
            "question_text": "验收用原创题：请计算两期占比变化。",
            "user_answer": "D",
            "verified_answer": "A",
            "error_reason": "把现期比重当成两期变化量；仅验收夹具，不计入真实学习数据。",
            "explanation_completed": True,
            "method_refs": ["am-card-0338"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "data"
            cwd.mkdir()
            payload_path = Path(tmp) / "payload.json"
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            def run():
                result = subprocess.run(
                    [sys.executable, str(script), "--cwd", str(cwd), "--payload", str(payload_path)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return json.loads(result.stdout.splitlines()[-1])

            first = run()
            second = run()
            state = cwd / "复盘引擎"
            cards = list((state / "错因卡").glob("*.md"))
            events = (state / ".writeback/events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(first["status"], "written")
            self.assertEqual(second["status"], "noop")
            self.assertEqual(len(cards), 1)
            self.assertEqual(len(events), 1)
            self.assertFalse((Path(tmp) / "复盘引擎").exists())


if __name__ == "__main__":
    unittest.main()
