"""Source .vsz round trips for unlinked numeric datasets (#696).

Run with QT_QPA_PLATFORM=offscreen and VEUSZ_RESOURCE_DIR at the source root.
Non-NaN float64 bits (including signed zero and infinities), NaN positions,
column presence and row order must survive. NaN payloads/signs are not promised.
Error signs are compared after Dataset's existing constructor normalization.
"""
import io
import itertools
import os
import tempfile
import unittest
from unittest.mock import patch

# Import real Qt before document/widgets (no replacement Qt modules).
from veusz import qtall as qt
from veusz import datasets, document, widgets, dataimport
import numpy as np


def precision_values():
    """Explicit boundaries plus deterministic random binary64 bit patterns."""
    info = np.finfo(np.float64)
    explicit = [60000.12345, 60000.12346, 0.1, -0.1, np.pi,
                1., np.nextafter(1., 0.), np.nextafter(1., 2.),
                0., -0., info.max, -info.max, info.tiny, -info.tiny,
                np.nextafter(info.tiny, 0.), np.nextafter(0., 1.),
                -np.nextafter(0., 1.), np.nan, np.inf, -np.inf]
    magnitudes = [sign * float('1.2345678901234567e%d' % exponent)
                  for exponent in (-320, -300, -100, -10, 10, 100, 300)
                  for sign in (-1, 1)]
    rng = np.random.default_rng(696)
    random = np.frombuffer(rng.bytes(4096 * 8), dtype=np.float64)
    return np.concatenate((explicit, magnitudes, random))


class DatasetPrecisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def new_document(self):
        with patch.object(document.Document, 'loadPlugins'):
            return document.Document()

    def roundtrip(self, entries):
        original = self.new_document()
        for name, ds in entries.items():
            original.setData(name, ds)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'precision.vsz')
            original.save(path)
            loaded = self.new_document()
            loaded.load(path)
        self.assertEqual(set(entries), set(loaded.data))
        return loaded

    def assert_float64_identical(self, expected, actual):
        self.assertEqual(expected.dtype, np.dtype('float64'))
        self.assertEqual(actual.dtype, expected.dtype)
        self.assertEqual(actual.shape, expected.shape)
        nan = np.isnan(expected)
        np.testing.assert_array_equal(np.isnan(actual), nan)
        np.testing.assert_array_equal(actual[~nan].view(np.uint64),
                                      expected[~nan].view(np.uint64))

    def assert_dataset_identical(self, expected, actual):
        for column in expected.columns:
            before, after = getattr(expected, column), getattr(actual, column)
            if before is None:
                self.assertIsNone(after)
            else:
                self.assert_float64_identical(before, after)

    def test_mjd_points_remain_distinct(self):
        ds = datasets.Dataset([60000.12345, 60000.12346])
        loaded = self.roundtrip({'mjd': ds})
        self.assert_dataset_identical(ds, loaded.data['mjd'])
        self.assertNotEqual(*loaded.data['mjd'].data)

    def test_all_float64_values_and_error_column_combinations(self):
        values = precision_values()
        entries = {}
        # Cover all eight combinations, including one-sided errors. Distinct
        # column orders catch swapped descriptors as well as precision loss.
        for flags in itertools.product((False, True), repeat=3):
            errors = {col: np.roll(values, shift)
                      for col, shift, present in zip(
                          ('serr', 'perr', 'nerr'), (1, 7, 19), flags)
                      if present}
            entries['values %s' % (flags,)] = datasets.Dataset(values, **errors)
        loaded = self.roundtrip(entries)
        for name, ds in entries.items():
            with self.subTest(name=name):
                self.assert_dataset_identical(ds, loaded.data[name])

    def test_single_row(self):
        entries = {'single': datasets.Dataset([60000.12345], serr=[0.12345678901234567])}
        loaded = self.roundtrip(entries)
        for name, ds in entries.items():
            self.assert_dataset_identical(ds, loaded.data[name])

    def test_empty_dump_is_unchanged(self):
        # Existing ImportString behavior omits datasets with no rows; fixing
        # that is separate from numeric serialization precision.
        ds = datasets.Dataset([], serr=[], perr=[], nerr=[])
        output = io.StringIO()
        ds.saveToFile(output, 'empty')
        self.assertEqual(output.getvalue(),
                         "ImportString('empty(numeric),+-,+,-','''\n''')\n")

    def test_2d_and_nd_values_and_shapes(self):
        values = precision_values()
        entries = {
            'image': datasets.Dataset2D(values.reshape(2, -1)),
            'cube': datasets.DatasetND(values.reshape(2, 5, -1)),
            'singleton': datasets.DatasetND(values.reshape(1, 2, -1)),
        }
        loaded = self.roundtrip(entries)
        for name, ds in entries.items():
            with self.subTest(name=name):
                self.assertIsInstance(loaded.data[name], type(ds))
                self.assert_float64_identical(ds.data, loaded.data[name].data)

    def test_2d_coordinate_metadata(self):
        values = np.arange(9., dtype=np.float64).reshape(3, 3)
        entries = {
            'ranges': datasets.Dataset2D(values,
                xrange=(60000.12345, 60000.12346),
                yrange=(-0.12345678901234567, 0.12345678901234567)),
            'edges': datasets.Dataset2D(values,
                xedge=[60000.12345, 60000.12346, 60000.23456789, 60001.123456789],
                yedge=[0.12345678901234567, 1.2345678901234567,
                       9.876543210987654, 20.123456789012345]),
            'centres': datasets.Dataset2D(values,
                xcent=[60000.12345, 60000.12346, 60001.23456789],
                ycent=[1.2345678901234567, 9.876543210987654, 20.123456789012345]),
        }
        loaded = self.roundtrip(entries)
        for name, ds in entries.items():
            for field in ('xrange', 'yrange', 'xedge', 'yedge', 'xcent', 'ycent'):
                with self.subTest(name=name, field=field):
                    before = getattr(ds, field)
                    after = getattr(loaded.data[name], field)
                    if before is None:
                        self.assertIsNone(after)
                    else:
                        self.assert_float64_identical(
                            np.asarray(before, dtype=np.float64),
                            np.asarray(after, dtype=np.float64))

    def test_display_and_user_export_format_are_unchanged(self):
        ds = datasets.Dataset([60000.12345], serr=[0.123456789])
        self.assertEqual(ds.datasetAsText(), '60000.1\t0.123457\n')
        self.assertEqual(ds.datasetAsText(fmt='%.2f', join=','), '60000.12,0.12\n')
        self.assertEqual(ds.datasetAsText(fmt='%e', join=' '),
                         '6.000012e+04 1.234568e-01\n')
        for cls in (datasets.Dataset2D, datasets.DatasetND):
            ds = cls([[60000.12345, 0.123456789]])
            self.assertEqual(ds.datasetAsText(), '60000.1\t0.123457\n')
            self.assertEqual(ds.datasetAsText(fmt='%.2f', join=','),
                             '60000.12,0.12\n')

    def test_linked_numeric_data_are_not_dumped(self):
        ds = datasets.Dataset([60000.12345], linked=object())
        with patch.object(ds, 'saveDataDumpToText') as dump:
            output = io.StringIO()
            ds.saveToFile(output, 'linked')
            dump.assert_not_called()
            self.assertEqual(output.getvalue(), '')

    def test_hdf5_dispatch_does_not_use_text_dump(self):
        ds = datasets.Dataset([60000.12345])
        group = object()
        with patch.object(ds, 'saveDataDumpToText') as text, \
                patch.object(ds, 'saveDataDumpToHDF5') as hdf:
            ds.saveToFile(io.StringIO(), 'numeric', mode='hdf5', hdfgroup=group)
            text.assert_not_called()
            hdf.assert_called_once_with(group, 'numeric')

    def test_date_and_related_numeric_dataset_types(self):
        # Date serialization must retain its date descriptor/ISO formatting,
        # not reinterpret epoch seconds as ordinary numeric data.
        date = datasets.DatasetDateTime([0., 1.25, 60000.123456])
        dump = io.StringIO()
        date.saveToFile(dump, 'dates')
        self.assertIn('(date)', dump.getvalue())
        self.assertIn('2009-01-01T00:00:00', dump.getvalue())
        self.assertNotIn('(numeric)', dump.getvalue())
        ranged = datasets.DatasetRange(3, (60000.12345, 60000.12346))
        entries = {'dates': date, 'range': ranged, 'unlinked': ranged.returnCopy()}
        loaded = self.roundtrip(entries)
        self.assertIsInstance(loaded.data['dates'], datasets.DatasetDateTime)
        self.assertIsInstance(loaded.data['range'], datasets.DatasetRange)
        self.assertIsInstance(loaded.data['unlinked'], datasets.Dataset)
        for name, ds in entries.items():
            self.assert_dataset_identical(ds, loaded.data[name])


if __name__ == '__main__':
    unittest.main()
