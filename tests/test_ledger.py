import copy
import tempfile
import unittest
from pathlib import Path

from engine.ledger import GENESIS_HASH, EvidenceLedger, load_ledger, verify_chain


def sample(n=5):
    ledger = EvidenceLedger()
    for i in range(n):
        ledger.append("event", f"2026-10-01T00:00:{i:02d}Z", {"i": i, "note": "é"})
    return ledger


class TestLedger(unittest.TestCase):
    def test_chain_links_and_verifies(self):
        entries = sample().entries
        self.assertEqual(entries[0]["prev_hash"], GENESIS_HASH)
        self.assertEqual(entries[3]["prev_hash"], entries[2]["entry_hash"])
        self.assertTrue(verify_chain(entries).valid)

    def test_edited_payload_detected(self):
        entries = copy.deepcopy(sample().entries)
        entries[2]["payload"]["i"] = 99
        check = verify_chain(entries)
        self.assertFalse(check.valid)
        self.assertEqual(check.first_bad_seq, 2)

    def test_edit_with_recomputed_hash_still_breaks_next_link(self):
        from engine.ledger import _entry_hash
        entries = copy.deepcopy(sample().entries)
        entries[2]["payload"]["i"] = 99
        entries[2]["entry_hash"] = _entry_hash(entries[2])
        check = verify_chain(entries)
        self.assertFalse(check.valid)
        self.assertEqual(check.first_bad_seq, 3)

    def test_deleted_and_reordered_entries_detected(self):
        entries = copy.deepcopy(sample().entries)
        self.assertFalse(verify_chain(entries[:2] + entries[3:]).valid)
        self.assertFalse(verify_chain([entries[1], entries[0]] + entries[2:]).valid)

    def test_file_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "l.jsonl"
            ledger = EvidenceLedger(path)
            ledger.append("event", "2026-10-01T00:00:00Z", {"x": 1.5})
            ledger.append("event", "2026-10-01T00:00:02Z", {"x": None})
            ledger.close()
            loaded = load_ledger(path)
            self.assertEqual(loaded, ledger.entries)
            self.assertTrue(verify_chain(loaded).valid)


if __name__ == "__main__":
    unittest.main()
