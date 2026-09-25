"""Relocating an import while loading must enable saving the repaired document."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from veusz import document, datasets, qtall as qt, widgets, dataimport
from veusz.windows.mainwindow import MainWindow


class RelocatedImportsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def new_document(self):
        with patch.object(document.Document, 'loadPlugins'):
            return document.Document()

    def fixture(self, folder, mode):
        original = folder/'original.csv'
        original.write_text('x,y\n1,2\n3,4\n', encoding='utf-8')
        source = folder/'plot.vsz'
        source.write_text("ImportFileCSV('original.csv', linked=True)\n", encoding='utf-8')
        if mode == 'hdf5':
            try:
                import h5py
            except ImportError:
                self.skipTest('h5py unavailable')
            doc = self.new_document()
            doc.load(str(source))
            doc.setData('embedded', datasets.Dataset([11., 12.]))
            doc.data['embedded'].tags.add('preserved')
            source = folder/'plot.vszh5'
            doc.save(str(source), mode='hdf5')
        return original, source

    def test_normal_load_stays_clean(self):
        for mode in ('vsz', 'hdf5'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                original, source = self.fixture(Path(tmp), mode)
                doc = self.new_document()
                callback = Mock()
                doc.load(str(source), mode=mode, callbackimporterror=callback)
                callback.assert_not_called()
                self.assertFalse(doc.isModified())
                self.assertEqual(doc.historyundo, [])
                if mode == 'hdf5':
                    self.assertEqual(doc.data['embedded'].data.tolist(), [11., 12.])
                    self.assertIn('preserved', doc.data['embedded'].tags)

    def test_relocation_enables_save_and_persists_new_link(self):
        for mode in ('vsz', 'hdf5'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                original, source = self.fixture(Path(tmp), mode)
                replacement = original.with_name('replacement.csv')
                original.rename(replacement)
                doc = self.new_document()
                save, reload = qt.QAction(None), qt.QAction(None)
                window = SimpleNamespace(filename=str(source), vzactions={
                    'file.save': save, 'file.reload': reload})
                doc.signalModified.connect(lambda changed: MainWindow.slotModifiedDoc(window, changed))
                callback = Mock(return_value=str(replacement))
                doc.load(str(source), mode=mode, callbackimporterror=callback)
                callback.assert_called_once()
                self.assertTrue(doc.isModified())
                self.assertTrue(save.isEnabled())
                self.assertEqual(doc.historyundo, [])
                self.assertEqual(Path(doc.data['x'].linked.filename), replacement)
                saved = Path(tmp)/('repaired.vszh5' if mode=='hdf5' else 'repaired.vsz')
                doc.save(str(saved), mode=mode)
                self.assertFalse(doc.isModified())
                self.assertFalse(save.isEnabled())
                loaded = self.new_document()
                no_repair = Mock(side_effect=AssertionError('Repair should persist'))
                loaded.load(str(saved), mode=mode, callbackimporterror=no_repair)
                self.assertFalse(loaded.isModified())
                self.assertEqual(loaded.data['x'].data.tolist(), [1.,3.])
                if mode == 'hdf5':
                    self.assertEqual(loaded.data['embedded'].data.tolist(), [11., 12.])
                    self.assertIn('preserved', loaded.data['embedded'].tags)

    def test_success_after_multiple_replacement_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            original, source = self.fixture(Path(tmp), 'vsz')
            replacement = original.with_name('replacement.csv')
            original.rename(replacement)
            callback = Mock(side_effect=[str(Path(tmp)/'still-missing.csv'), str(replacement)])
            doc = self.new_document()
            doc.load(str(source), callbackimporterror=callback)
            self.assertEqual(callback.call_count, 2)
            self.assertTrue(doc.isModified())

    def test_ignored_failed_replacement_does_not_count_as_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            original, source = self.fixture(Path(tmp), 'vsz')
            original.unlink()
            doc = self.new_document()
            callback = Mock(side_effect=[str(Path(tmp)/'also-missing.csv'), False])
            doc.load(str(source), callbackimporterror=callback)
            self.assertEqual(doc.data, {})
            self.assertFalse(doc.isModified())

    def test_successful_repair_followed_by_ignored_import_stays_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            original, source = self.fixture(Path(tmp), 'vsz')
            replacement = original.with_name('replacement.csv')
            original.rename(replacement)
            with source.open('a', encoding='utf-8') as stream:
                stream.write("ImportFileCSV('another-missing.csv', prefix='ignored_')\n")
            doc = self.new_document()
            callback = Mock(side_effect=[str(replacement), False])
            doc.load(str(source), callbackimporterror=callback)
            self.assertEqual(callback.call_count, 2)
            self.assertTrue(doc.isModified())
            self.assertEqual(sorted(doc.data), ['x', 'y'])

    def test_cancel_preserves_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            original, source = self.fixture(Path(tmp), 'vsz')
            original.unlink()
            with self.assertRaises(document.LoadError):
                self.new_document().load(str(source), callbackimporterror=lambda *args: None)

    def test_recovering_original_path_is_not_a_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            original, source = self.fixture(Path(tmp), 'vsz')
            original.unlink()
            calls = []
            def recover(filename, error):
                calls.append(filename)
                if len(calls) == 1:
                    return str(Path(tmp)/'missing-again.csv')
                original.write_text('x,y\n1,2\n3,4\n', encoding='utf-8')
                return calls[0]
            doc = self.new_document()
            doc.load(str(source), callbackimporterror=recover)
            self.assertEqual(len(calls), 2)
            self.assertFalse(doc.isModified())
            self.assertEqual(doc.data['x'].data.tolist(), [1.,3.])


if __name__ == '__main__':
    unittest.main()
