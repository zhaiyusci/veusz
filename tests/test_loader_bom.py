"""Source-loader regressions for #813 (no issue attachments executed)."""

import ast
import itertools
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest

# Import Qt before the document package/native helpers on Windows.
from veusz import qtall as qt
from veusz import document, dataimport  # register ImportString
from veusz.document import loader


ROOT = Path(__file__).resolve().parents[1]


def legacy_remove_boms(script):
    """Reference implementation, used only on bounded short strings."""
    def replacer(match):
        backslashes = match.group(2)
        if len(backslashes) % 2 == 0:
            return match.group(0)
        return match.group(1) + backslashes[1:] + match.group(3)
    return re.sub(r'(.*?)(\\+)ufeff(.*?)', replacer, script)


class RemoveBOMsTest(unittest.TestCase):
    def test_semantics(self):
        cases = [
            ('', ''),
            ('ufeff', 'ufeff'),
            ('\ufeffα\n漢字🙂', '\ufeffα\n漢字🙂'),
            (r'\uFEFF\U0000feff\ufef', r'\uFEFF\U0000feff\ufef'),
            (r'A\ufeffB\ufeffC', 'ABC'),
            (r'\ufeff\ufeff', ''),
            (r'\\ufeff\ufeff', r'\\ufeff'),
            ('α\\ufeff\n漢字\\ufeff\r\n🙂', 'α\n漢字\r\n🙂'),
            (r'\ufeffufeff', 'ufeff'),
            # Do not reprocess pairs exposed by an earlier removal.
            (r'\\\ufeffufeff', r'\\ufeff'),
        ]
        for count in range(20):
            source = 'prefix' + '\\' * count + 'ufeff' + '\\' * count
            expected = ('prefix' + '\\' * (count - 1) if count % 2
                        else 'prefix' + '\\' * count + 'ufeff')
            cases.append((source, expected + '\\' * count))
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(loader.removeBOMs(script=source), expected)

    def test_exhaustive_short_token_strings(self):
        tokens = ('a', '\\', 'ufeff', '\n', '\ufeff', '🙂')
        for length in range(6):
            for parts in itertools.product(tokens, repeat=length):
                source = ''.join(parts)
                self.assertEqual(loader.removeBOMs(source), legacy_remove_boms(source),
                                 repr(source))

    def test_seeded_random_reference(self):
        rng = random.Random(813)
        tokens = ('a', 'u', 'f', 'e', '\\', '\\\\', 'ufeff', '\\ufeff',
                  '\r', '\n', '\x00', '漢字', '🙂', '\ufeff', 'UFEFF', "'")
        for _ in range(5000):
            source = ''.join(rng.choices(tokens, k=rng.randrange(60)))
            self.assertEqual(loader.removeBOMs(source), legacy_remove_boms(source),
                             repr(source))

    def test_python_literal_interpretation(self):
        # Audit the source transformation AND what Python subsequently decodes.
        for count in range(1, 12):
            source = "'left" + '\\' * count + "ufeffright'"
            transformed = loader.removeBOMs(source)
            expected = ('left' + '\\' * (count // 2)
                        + ('' if count % 2 else 'ufeff') + 'right')
            self.assertEqual(ast.literal_eval(transformed), expected)
        for value in (r'C:\ufeff\a.csv', r'\ufeff\ufeff'):
            self.assertEqual(ast.literal_eval(loader.removeBOMs(repr(value))), value)
        # repr escapes an actual BOM, so the resulting source IS stripped;
        # directly embedding the code point in source leaves it unchanged.
        value = 'α\ufeff漢字🙂'
        self.assertEqual(ast.literal_eval(loader.removeBOMs(repr(value))), 'α漢字🙂')
        self.assertEqual(ast.literal_eval(loader.removeBOMs("'" + value + "'")), value)
        self.assertEqual(ast.literal_eval(loader.removeBOMs(r"r'\ufeff'")), '')

    def test_large_inputs_with_watchdog(self):
        # A separate process is essential: a pathological regex can hold the GIL.
        # Inherit stdio (no pipes); timeout is only a generous hang watchdog,
        # not an assertion about machine-dependent timing or scaling ratios.
        probe = r'''
from veusz import qtall
from veusz.document.loader import removeBOMs
from pathlib import Path
import statistics
import time
import veusz.document.loader as loader
assert Path(loader.__file__).resolve() == Path('veusz/document/loader.py').resolve()
for kind in ('plain', 'present', 'slashes', 'repeated', 'bare-needles'):
    for n in (64000, 256000, 1024000):
        if kind == 'plain':
            source = expected = 'x' * n
        elif kind == 'present':
            source = 'x' * n + r'\ufeff' + 'y' * n
            expected = 'x' * n + 'y' * n
        elif kind == 'slashes':
            source = '\\' * (n + 1) + 'ufeff' + '\\' * n + 'x'
            expected = '\\' * (2 * n) + 'x'
        elif kind == 'repeated':
            source = (r'a\ufeff\\ufeff' + '\n🙂') * (n // 16)
            expected = (r'a\\ufeff' + '\n🙂') * (n // 16)
        else:
            source = expected = 'ufeff' * (n // 5)
        times = []
        for _ in range(3):
            start = time.perf_counter()
            result = removeBOMs(source)
            times.append(time.perf_counter() - start)
            assert result == expected, kind
        print('BOM scaling', kind, len(source), statistics.median(times), flush=True)
'''
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen',
                   VEUSZ_RESOURCE_DIR=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
        subprocess.run([sys.executable, '-B', '-c', probe], cwd=ROOT,
                       env=env, timeout=30, check=True)


class DocumentBOMsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def setUp(self):
        output = ROOT / 'artifacts' / 'round3-bom'
        output.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def script_and_expected(self):
        # Handwritten source: repr() would escape the very sequences under test.
        source = r'''SetDataText('text', ['left\ufeffright', 'C:\\ufeff\\a.csv', '\\\ufeff', '\ufeff\ufeff', 'α漢字🙂'])
'''
        # Real U+FEFF inside a string remains data, as in the old implementation.
        source += "SetDataText('unicode', ['α\ufeff漢字🙂'])\n"
        source += "ImportString('x', '" + r'1\n' * 40000 + "')\n"
        return source, ['leftright', r'C:\ufeff\a.csv', '\\', '', 'α漢字🙂']

    def check_document(self, filename, mode):
        doc = document.Document()
        doc.load(str(filename), mode=mode)
        self.assertEqual(doc.data['text'].data, self.script_and_expected()[1])
        self.assertEqual(doc.data['unicode'].data, ['α\ufeff漢字🙂'])
        self.assertEqual(len(doc.data['x'].data), 40000)
        self.assertTrue((doc.data['x'].data == 1).all())
        self.assertFalse(doc.isModified())
        self.assertEqual(doc.filename, str(filename))

    def test_vsz_source_loader(self):
        filename = self.directory / 'bom.vsz'
        filename.write_text(self.script_and_expected()[0], encoding='utf-8')
        self.check_document(filename, 'vsz')

    def test_hdf5_source_loader(self):
        try:
            import h5py
        except ImportError:
            self.skipTest('h5py unavailable')
        filename = self.directory / 'bom.vszh5'
        with h5py.File(filename, 'w') as handle:
            group = handle.create_group('Veusz')
            group.attrs['vsz_format'] = 1
            group.attrs['vsz_version'] = 'test'
            group.create_group('Data')
            docgroup = group.create_group('Document')
            docgroup.create_group('Tags')
            docgroup['document'] = [self.script_and_expected()[0].encode('utf-8')]
        self.check_document(filename, 'hdf5')


if __name__ == '__main__':
    unittest.main()
