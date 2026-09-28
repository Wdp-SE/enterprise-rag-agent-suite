from __future__ import annotations

import copy
import json
import unittest

import run_quality_v3 as v3


class QualityV3Test(unittest.TestCase):
    def test_locked_inputs_and_evidence_validate(self) -> None:
        cases, split, lock, index = v3.load_locked()
        self.assertEqual((len(cases), len(index.manifest["sources"]), len(index.chunks)), (72, 132, 1322))
        self.assertEqual((len(split["dev"]), len(split["holdout"])), (36, 36))
        self.assertEqual(lock["top_k"], 5)

    def test_scenario_families_do_not_cross_split(self) -> None:
        cases = v3.read_cases()
        split = v3.split_cases(cases)
        by_id = {case["query_id"]: case for case in cases}
        for category in {case["category"] for case in cases}:
            dev = {
                by_id[case_id]["family"] for case_id in split["dev"]
                if by_id[case_id]["category"] == category
            }
            holdout = {
                by_id[case_id]["family"] for case_id in split["holdout"]
                if by_id[case_id]["category"] == category
            }
            self.assertEqual((len(dev), len(holdout)), (2, 2))
            self.assertFalse(dev & holdout)

    def test_annotation_rejects_marker_missing_from_pinned_source(self) -> None:
        cases = copy.deepcopy(v3.read_cases())
        cases[0]["expected_markers"]["3.4.3|zh|guide/parameter/project-parameter"] = [
            "not-present-in-the-fixed-official-source"
        ]
        with self.assertRaisesRegex(ValueError, "marker absent from source"):
            v3.validate_cases(cases, v3.PublicKnowledgeIndex())

    def test_hit_is_not_misreported_as_source_recall(self) -> None:
        case = {
            "query_id": "example", "category": "cross_document", "family": "example",
            "answerable": True, "version_scope": "3.4.3", "language": "en",
            "expected_markers": {
                "3.4.3|en|one": ["first fact"],
                "3.4.3|en|two": ["second fact"],
            },
        }
        hit = {
            "version": "3.4.3", "language": "en", "document_key": "one",
            "document_title": "One", "heading": "", "heading_path": [],
            "content": "first fact", "chunk_id": "one:1", "retrieval_score": 2.0,
        }
        result = v3._case_result(case, [hit, {**hit, "chunk_id": "one:2"}], 1.0)
        self.assertTrue(result["source_hit_at_5"])
        self.assertEqual(result["source_recall_at_5"], 0.5)
        self.assertFalse(result["complete_source_at_5"])
        self.assertEqual(result["evidence_marker_recall_at_5"], 0.5)
        self.assertEqual(result["top5_source_ids"], ["3.4.3|en|one"])

    def test_no_answer_has_no_retrieval_ground_truth(self) -> None:
        case = {
            "query_id": "unknown", "category": "no_answer", "family": "example",
            "answerable": False, "version_scope": "3.4.3", "language": "en",
            "expected_markers": {},
        }
        result = v3._case_result(case, [], 1.0)
        self.assertIsNone(result["source_hit_at_5"])
        self.assertIsNone(result["source_recall_at_5"])
        self.assertIsNone(result["evidence_marker_recall_at_5"])
        self.assertEqual(v3.summarize([result])["no_answer_count"], 1)

    def test_archived_holdout_matches_one_shot_selection(self) -> None:
        lock = json.loads((v3.ROOT / "selection_lock.json").read_text(encoding="utf-8"))
        selection = json.loads((v3.ROOT / "candidate_selection.json").read_text(encoding="utf-8"))
        execution = json.loads((v3.ROOT / "holdout_execution.json").read_text(encoding="utf-8"))
        result = json.loads((v3.ROOT / "results" / "holdout__bm25.json").read_text(encoding="utf-8"))
        self.assertEqual(selection["policy"], execution["policy"])
        self.assertEqual(selection["policy"], result["policy"])
        self.assertEqual(result["split"], "holdout")
        self.assertEqual(selection["candidate_fingerprint"], execution["candidate_fingerprint"])
        self.assertEqual(selection["candidate_fingerprint"], result["candidate_fingerprint"])
        self.assertEqual(selection["input_sha256"], lock["sha256"])
        self.assertEqual(execution["input_sha256"], lock["sha256"])
        self.assertEqual(result["input_sha256"], lock["sha256"])
        self.assertEqual(
            selection["dev_result_sha256"],
            v3.sha256(v3.ROOT / "results" / "dev__bm25.json"),
        )
        self.assertLess(selection["selected_at_utc"], execution["opened_at_utc"])


if __name__ == "__main__":
    unittest.main()
