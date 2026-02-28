import math
import unittest

from inspirations.feature_vectors import ALL_DIMS, _apply_high_df_idf


class TestFeatureVectorsIdf(unittest.TestCase):
    def test_downweights_dimensions_above_threshold(self):
        vectors = [
            [1.0, 1.0, 0.0],
            [0.9, 0.5, 0.0],
            [0.8, 0.0, 1.0],
            [0.7, 1.0, 1.0],
        ]

        applied = _apply_high_df_idf(vectors, threshold_ratio=0.5)

        self.assertIn(ALL_DIMS[0], applied)  # df=4/4 -> log(1)=0
        self.assertIn(ALL_DIMS[1], applied)  # df=3/4 -> log(4/3)
        self.assertNotIn(ALL_DIMS[2], applied)  # df=2/4 -> not above threshold

        self.assertAlmostEqual(applied[ALL_DIMS[0]], 0.0, places=6)
        self.assertAlmostEqual(applied[ALL_DIMS[1]], math.log(4 / 3), places=6)

        for vec in vectors:
            self.assertAlmostEqual(vec[0], 0.0, places=6)

        self.assertAlmostEqual(vectors[0][1], 1.0 * math.log(4 / 3), places=6)
        self.assertAlmostEqual(vectors[1][1], 0.5 * math.log(4 / 3), places=6)
        self.assertAlmostEqual(vectors[3][1], 1.0 * math.log(4 / 3), places=6)
        self.assertEqual(vectors[0][2], 0.0)
        self.assertEqual(vectors[1][2], 0.0)
        self.assertEqual(vectors[2][2], 1.0)
        self.assertEqual(vectors[3][2], 1.0)

    def test_keeps_dimensions_at_or_below_threshold(self):
        vectors = [
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
            [0.0, 0.0],
        ]
        before = [row[:] for row in vectors]

        applied = _apply_high_df_idf(vectors, threshold_ratio=0.5)

        self.assertEqual(applied, {})
        self.assertEqual(vectors, before)


if __name__ == "__main__":
    unittest.main()
