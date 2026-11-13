from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from screen_literal_barrier_abstracts import literal_gate


class LiteralBarrierGateTests(unittest.TestCase):
    def test_accepts_separate_terms(self):
        self.assertTrue(literal_gate("First-order barriers are external; second order barriers are internal."))

    def test_accepts_coordinated_terms(self):
        self.assertTrue(literal_gate("We investigate first- and second-order barriers to use."))
        self.assertTrue(literal_gate("First and second order barriers were compared."))

    def test_rejects_single_order_and_digital_divide_levels(self):
        self.assertFalse(literal_gate("Only first-order barriers were measured."))
        self.assertFalse(literal_gate("First- and second-level digital divides were studied."))


if __name__ == "__main__":
    unittest.main()
