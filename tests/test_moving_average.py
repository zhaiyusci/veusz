"""Moving-average contracts, including exact (zero-error) observations.

Positive infinite weights represent exact observations. Within each window
these dominate finite weights and are averaged equally if they disagree: the
limit of giving all exact observations the same error tending to zero.
Nonfinite data never contribute, even with infinite weight. NaN and negative
infinite weights are ignored. Finite signed weights retain the historical
algebraic average (including NaN when their sum is zero).
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from veusz.helpers import qtloops
from veusz.plugins.datasetplugin import Dataset1D, MovingAveragePlugin


class RollingAverageTests(unittest.TestCase):
    def check_average(self, data, weights, width, expected):
        result = qtloops.rollingAverage(
            np.asarray(data, dtype=float),
            None if weights is None else np.asarray(weights, dtype=float),
            width)
        np.testing.assert_allclose(result, expected, equal_nan=True)

    def test_one_exact_observation(self):
        self.check_average([1, 100, 3], [1, np.inf, 1], 1, [100]*3)

    def test_multiple_exact_observations(self):
        self.check_average([10, 1000, 30, 50],
                           [np.inf, 1, np.inf, np.inf], 1,
                           [10, 20, 40, 40])

    def test_equal_exact_observations(self):
        self.check_average([4, 99, 4], [np.inf, 1, np.inf], 2, [4]*3)

    def test_exact_observation_leaves_window(self):
        self.check_average([100, 2, 4, 6, 8], [np.inf, 1, 1, 1, 1],
                           1, [100, 100, 4, 6, 7])

    def test_nonfinite_data_never_contribute(self):
        for invalid in (np.nan, np.inf, -np.inf):
            with self.subTest(invalid=invalid):
                self.check_average([2, invalid, 4], [1, np.inf, 1],
                                   1, [2, 3, 4])
                self.check_average([2, invalid, 4], None, 1, [2, 3, 4])

    def test_invalid_weights_are_ignored(self):
        self.check_average([1, 100, 200, 4], [1, np.nan, -np.inf, 1],
                           4, [2.5]*4)

    def test_no_contributing_points(self):
        for weights in (None, [1, 1], [np.inf, np.inf]):
            with self.subTest(weights=weights):
                self.check_average([np.nan, np.inf], weights, 2,
                                   [np.nan, np.nan])
        for weights in ([0, 0], [np.nan, -np.inf], [1, -1]):
            with self.subTest(weights=weights):
                self.check_average([2, 4], weights, 1, [np.nan]*2)

    def test_zero_and_signed_weights_preserve_algebraic_average(self):
        self.check_average([1, 100, 4], [2, 0, -1], 2, [-2]*3)
        self.check_average([1, 100, 4], [2, np.inf, -1], 2, [100]*3)

    def test_unweighted_and_finite_weighted_edges(self):
        self.check_average([1, 2, 4], None, 1, [1.5, 7/3, 3])
        self.check_average([1, 2, 4], [1, 2, 1], 1, [5/3, 9/4, 8/3])
        self.check_average([1, 2, 4], None, 10, [7/3]*3)

    def test_zero_width(self):
        self.check_average([1, 2, 3, 4], [1, np.inf, 0, np.nan],
                           0, [1, 2, np.nan, np.nan])
        self.check_average([1, np.nan, 3], None, 0, [1, np.nan, 3])

    def test_random_windows_against_reference(self):
        rng = np.random.default_rng(89)
        for _ in range(100):
            size = int(rng.integers(1, 30))
            data = rng.normal(size=size)
            data[rng.random(size) < 0.15] = np.nan
            weights = rng.choice([0., 1., 2., np.inf, -np.inf, np.nan],
                                 size=size)
            width = int(rng.integers(0, size+3))
            expected = []
            for i in range(size):
                window = slice(max(0, i-width), min(size, i+width+1))
                values, w = data[window], weights[window]
                exact = np.isfinite(values) & np.isposinf(w)
                finite = np.isfinite(values) & np.isfinite(w)
                if exact.any():
                    expected.append(values[exact].mean())
                elif w[finite].sum() != 0:
                    expected.append(np.average(values[finite], weights=w[finite]))
                else:
                    expected.append(np.nan)
            self.check_average(data, weights, width, expected)

    def test_empty_singleton_and_mismatched_lengths(self):
        self.check_average([], None, 1, [])
        self.check_average([1], [], 1, [])
        self.check_average([5], [np.inf], 9, [5])
        self.check_average([1, 3, 99], [1, 1], 1, [2, 2])
        self.check_average([1, 3], [1, 1, np.inf], 1, [2, 2])


class MovingAveragePluginTests(unittest.TestCase):
    def average(self, data, width=1, weighted=True, **errors):
        dataset = Dataset1D('input', data=data, **errors)
        original = dataset.data.copy()
        plugin = MovingAveragePlugin()
        fields = dict(ds_in='input', ds_out='output', width=width,
                      weighterrors=weighted)
        output, = plugin.getDatasets(fields)
        helper = SimpleNamespace(getDataset=lambda name: dataset)
        # Zero errors are supported input, not a floating-point warning.
        with np.errstate(all='raise'):
            plugin.updateDatasets(fields, helper)
        np.testing.assert_array_equal(dataset.data, original)
        self.assertIsNone(output.serr)
        self.assertIsNone(output.perr)
        self.assertIsNone(output.nerr)
        return output.data

    def test_document_plugin_recomputes_after_input_change(self):
        from veusz import document, qtall as qt, widgets  # register widgets

        app = qt.QApplication.instance() or qt.QApplication([])
        self.assertIsNotNone(app)
        with patch.object(document.Document, 'loadPlugins'):
            doc = document.Document()
        commands = document.CommandInterface(doc)
        commands.SetData('input', [1, 100, 3], symerr=[1, 0, 1])
        with np.errstate(all='raise'):
            commands.DatasetPlugin('MovingAverage', dict(
                ds_in='input', ds_out='output', width=1, weighterrors=True))
            np.testing.assert_allclose(doc.data['output'].data, [100]*3)
            commands.SetData('input', [10, 99, 30], symerr=[0, 1, 0])
            np.testing.assert_allclose(doc.data['output'].data, [10, 20, 30])

    def test_zero_symmetric_error(self):
        np.testing.assert_allclose(
            self.average([1, 100, 3], serr=[1, 0, 1]), [100]*3)

    def test_multiple_zero_errors(self):
        np.testing.assert_allclose(
            self.average([10, 999, 30], serr=[0, 1, 0]), [10, 20, 30])

    def test_epsilon_error_limit(self):
        np.testing.assert_allclose(
            self.average([1, 100, 3], serr=[1, 1e-10, 1]), [100]*3)

    def test_asymmetric_both_sides_must_be_zero(self):
        np.testing.assert_allclose(
            self.average([1, 100, 3], perr=[1, 0, 1], nerr=[-1, 0, -1]),
            [100]*3)
        np.testing.assert_allclose(
            self.average([1, 100, 3], perr=[1, 0, 1], nerr=[-1, -2, -1]),
            [34, 54/2.5, 106/3])

    def test_symmetric_errors_take_precedence(self):
        np.testing.assert_allclose(
            self.average([1, 100, 3], serr=[1, 0, 1],
                         perr=[0, 1, 0], nerr=[0, -1, 0]), [100]*3)

    def test_nonfinite_errors_and_data(self):
        np.testing.assert_allclose(
            self.average([2, 99, 99, 4], width=4,
                         serr=[1, np.nan, np.inf, 1]), [3]*4)
        np.testing.assert_allclose(
            self.average([2, np.nan, 4], serr=[1, 0, 1]), [2, 3, 4])

    def test_errors_disabled_missing_or_one_sided(self):
        for errors in ({}, {'perr': [1, 0, 1]}, {'nerr': [-1, 0, -1]}):
            with self.subTest(errors=errors):
                np.testing.assert_allclose(
                    self.average([1, 100, 3], **errors), [50.5, 104/3, 51.5])
        np.testing.assert_allclose(
            self.average([1, 100, 3], weighted=False, serr=[1, 0, 1]),
            [50.5, 104/3, 51.5])

    def test_finite_errors_and_sign(self):
        np.testing.assert_allclose(
            self.average([1, 2, 4], serr=[1, -2, 1]), [1.2, 22/9, 3.6])


if __name__ == '__main__':
    unittest.main()
