"""Portable linked-data save-as regressions for upstream issues #90/#201."""
import ast
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from veusz import document, qtall as qt, setting
from veusz.dataimport.base import LinkedFileBase, ImportParamsBase


class DocumentPathsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def setUp(self):
        old = setting.settingdb['docfile_addimportpaths']
        self.addCleanup(setting.settingdb.__setitem__, 'docfile_addimportpaths', old)
        setting.settingdb['docfile_addimportpaths'] = True
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'MixedCaseProject'
        self.project.mkdir()
        (self.project / 'data.txt').write_text('x\n1\n2\n', encoding='utf-8')
        self.original = self.project / 'original.vsz'
        self.original.write_text("ImportFileCSV('data.txt', linked=True)\n", encoding='utf-8')

    def load(self, filename):
        doc = document.Document()
        doc.load(str(filename))
        self.assertEqual(doc.data['x'].data.tolist(), [1., 2.])
        return doc

    def assertImportPath(self, filename, expected):
        calls = [n.value for n in ast.parse(Path(filename).read_text(encoding='utf-8')).body
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Name)
                 and n.value.func.id == 'ImportFileCSV']
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.literal_eval(calls[0].args[0]), expected)

    def test_same_directory_save_as_reload_and_move(self):
        for addpaths in (False, True):
            with self.subTest(add_import_paths=addpaths):
                old = setting.settingdb['docfile_addimportpaths']
                try:
                    setting.settingdb['docfile_addimportpaths'] = addpaths
                    doc = self.load(self.original)
                    saved = self.project / 'renamed.vsz'
                    doc.save(str(saved))
                    self.assertImportPath(saved, 'data.txt')
                    self.load(saved).save(str(saved))
                    self.assertImportPath(saved, 'data.txt')
                    moved = self.root / ('Moved' + str(addpaths))
                    shutil.move(str(self.project), str(moved))
                    loaded = self.load(moved / saved.name)
                    self.assertEqual(loaded.reloadLinkedDatasets(), (['x'], {}))
                    loaded.save(str(moved / 'again.vsz'))
                    self.assertImportPath(moved / 'again.vsz', 'data.txt')
                    shutil.move(str(moved), str(self.project))
                finally:
                    setting.settingdb['docfile_addimportpaths'] = old

    def test_copied_project_prefers_local_data_over_saved_import_path(self):
        doc = self.load(self.original)
        saved = self.project / 'saved.vsz'
        doc.save(str(saved))
        self.assertIn('AddImportPath(', saved.read_text(encoding='utf-8'))
        copied = self.root / 'Copy'
        shutil.copytree(self.project, copied)
        (copied / 'data.txt').write_text('x\n7\n8\n', encoding='utf-8')
        loaded = document.Document()
        loaded.load(str(copied / 'saved.vsz'))
        self.assertEqual(loaded.data['x'].data.tolist(), [7., 8.])

    def test_save_as_in_subdirectory_keeps_relative_link(self):
        doc = self.load(self.original)
        subdir = self.project / 'plots'
        subdir.mkdir()
        doc.save(str(subdir / 'plot.vsz'))
        self.assertImportPath(subdir / 'plot.vsz', '../data.txt')
        moved = self.root / 'Moved'
        shutil.move(str(self.project), str(moved))
        self.load(moved / 'plots' / 'plot.vsz')

    @unittest.skipUnless(os.name == 'nt', 'case-insensitive Windows path semantics')
    def test_same_directory_with_different_case_then_move(self):
        doc = self.load(self.original)
        # The spelling differs, but both paths address the same directory.
        case_variant = self.root / self.project.name.swapcase()
        if not case_variant.is_dir():
            self.skipTest('temporary directory is case-sensitive')
        saved = str(case_variant / 'renamed.vsz')
        doc.save(saved)
        moved = self.root / 'Moved'
        shutil.move(str(self.project), str(moved))
        # Loading must work after the original directory no longer exists,
        # not merely while a redundant '../OldName/' path still resolves.
        self.load(moved / 'renamed.vsz')
        self.assertImportPath(moved / 'renamed.vsz', 'data.txt')

    def test_save_link_relative_to_filesystem_root(self):
        filename = str(self.project / 'data.txt')
        root = Path(filename).anchor
        link = LinkedFileBase(ImportParamsBase(filename=filename))
        expected = os.path.relpath(filename, root)
        if os.name == 'nt':
            expected = expected.replace('\\', '/')
        self.assertEqual(link._getSaveFilename(root), expected)

    @unittest.skipUnless(os.name == 'nt', 'Windows drive letters')
    def test_case_only_drive_difference_is_relative(self):
        link = LinkedFileBase(ImportParamsBase(filename='C:\\Data\\data.txt'))
        self.assertEqual(link._getSaveFilename('c:\\Data'), 'data.txt')

    @unittest.skipUnless(os.name == 'nt', 'Windows UNC shares')
    def test_cross_share_link_remains_absolute(self):
        link = LinkedFileBase(ImportParamsBase(filename=r'\\server\data\data.txt'))
        self.assertEqual(
            link._getSaveFilename(r'\\server\plots'), '//server/data/data.txt')

    @unittest.skipUnless(os.name != 'nt', 'POSIX path policy')
    def test_distinct_top_level_directories_remain_absolute(self):
        link = LinkedFileBase(ImportParamsBase(filename='/data/data.txt'))
        self.assertEqual(link._getSaveFilename('/plots'), '/data/data.txt')

    @unittest.skipUnless(os.name == 'nt', 'Windows drive letters')
    def test_cross_drive_link_remains_absolute(self):
        link = LinkedFileBase(ImportParamsBase(filename='Z:\\Data\\data.txt'))
        self.assertEqual(link._getSaveFilename('C:\\Plots'), 'Z:/Data/data.txt')


if __name__ == '__main__':
    unittest.main()
