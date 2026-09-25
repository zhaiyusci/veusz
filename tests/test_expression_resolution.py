"""Regressions for literal shielding (#529) and context constants (#731).

Run with QT_QPA_PLATFORM=offscreen and VEUSZ_RESOURCE_DIR set to the checkout.
Import Qt before document so the source checkout's Qt extensions use its DLLs.
"""
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

from veusz import qtall as qt
from veusz import datasets, document, setting
from veusz.datasets.expression import substituteDatasets


class ExpressionResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def setUp(self):
        self.doc = document.Document()
        self.ci = document.CommandInterface(self.doc)

    def array(self, expr, **kwargs):
        return setting.DatasetExtended('probe', expr, **kwargs).getFloatArray(
            self.doc)

    def test_setting_path_before_and_after_dataset_creation(self):
        self.ci.Add('page', name='page1')
        self.ci.To('/page1')
        self.ci.Add('graph', name='var2')
        self.ci.Set('/page1/var2/aspect', 8)
        expr = '2/SETTING("/page1/var2/aspect")'
        self.assertEqual(self.array(expr).tolist(), [.25])
        self.ci.SetData('var2', [1, 2])
        self.assertEqual(self.array(expr).tolist(), [.25])
        self.assertEqual(substituteDatasets(self.doc.data, expr, 'data'),
                         (expr, []))
        self.ci.Set('/page1/var2/aspect', 4)
        self.assertEqual(self.array(expr).tolist(), [.5])

    def test_document_serialization_preserves_setting_expressions(self):
        # Register the file import commands, as the application does at startup.
        from veusz import dataimport  # noqa: F401

        self.ci.Add('page', name='page1')
        self.ci.To('/page1')
        self.ci.Add('graph', name='var2')
        self.ci.To('/page1/var2')
        self.ci.Set('aspect', 8)
        self.ci.Add('xy', name='curve')
        self.ci.SetData('var2', [10])
        self.ci.AddCustom('constant', 'Planck_const', '6.62607015e-34')
        expr = '2/SETTING("/page1/var2/aspect")'
        self.ci.Set('curve/xData', expr)
        self.ci.Set('curve/yData', 'Planck_const')
        self.ci.SetDataExpression('linked', expr, linked=True)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            filename = str(Path(tmp) / 'expressions.vsz')
            self.doc.save(filename)
            restored = document.Document()
            restored.load(filename)
        curve = restored.resolveWidgetPath(None, '/page1/var2/curve')
        self.assertEqual(curve.settings.get('xData').val, expr)
        self.assertEqual(curve.settings.get('xData').getFloatArray(
            restored).tolist(), [.25])
        self.assertEqual(curve.settings.get('yData').getFloatArray(
            restored).tolist(), [6.62607015e-34])
        self.assertEqual(restored.data['linked'].data.tolist(), [.25])

    def test_literal_forms_are_opaque_and_not_dependencies(self):
        literals = [
            "'a + b'", '"a + b"',
            "'''a +\nb'''", '"""a +\nb"""',
            r"'a \' + b'", r'"a \" + b"',
            r"'''a \' + b'''", r'"""a \" + b"""',
            "'`missing` + a_serr'", '"`a` + b"',
        ]
        prefixes = ['', 'r', 'R', 'u', 'U', 'b', 'B', 'br', 'Rb',
                    'f', 'F', 'fr', 'RF', 't', 'T', 'tr', 'RT']
        names = {'a', 'b', 'r', 'R', 'u', 'U', 'f', 'F', 'br', 'Rb',
                 'fr', 'RF', 't', 'T', 'tr', 'RT', 'missing'}
        for literal in literals:
            for prefix in prefixes:
                with self.subTest(prefix=prefix, literal=literal):
                    expr = prefix + literal + ' + a_serr'
                    actual, refs = substituteDatasets(names, expr, 'data')
                    self.assertEqual(actual, prefix + literal +
                                     " + _DS_('a', 'serr')")
                    self.assertEqual(refs, ['a'])

    def test_adjacent_literals_and_escaped_braces_are_opaque(self):
        for expr in ['"a + b" \'b + a\'', 'f"a + {{a}}"',
                     'rf"a + {{a}}"', '"""a \' b"""']:
            self.assertEqual(substituteDatasets({'a', 'b'}, expr, 'data'),
                             (expr, []))

    def assertTextExpression(self, expr, expected, references):
        actual, refs = substituteDatasets(self.doc.data, expr, 'data')
        self.assertEqual(refs, references)
        result = self.doc.evaluate.evalDatasetExpression(
            '[' + expr + ']', datatype='text')
        self.assertIsNotNone(result, actual)
        self.assertEqual(result.data, [expected])

    def test_formatted_fields_preserve_dataset_evaluation(self):
        self.ci.SetData('x', [1, 2, 3])
        for expr, expected in [
                ('f"{sum(x)}"', '6.0'),
                ('f"{(x)}"', '[1. 2. 3.]'),
                ('f"x + {{x}} {sum(x)!s}"', 'x + {x} 6.0'),
                ('rf"x + {{x}} {float(sum(x))!a:>6}"', 'x + {x}    6.0'),
                ('f"{int(sum(x))!r}"', '6'),
                ('f"{sum(x):x>8.1f}"', 'xxxxx6.0'),
                ('f"{sum(x[1:]):.1f}"', '5.0'),
                ('f"{dict(a=sum(x))[\'a\']:.1f}"', '6.0'),
                ('f"{({\'x\': sum(x)})[\'x\']:.1f}"', '6.0'),
                (r'f"\N{GREEK SMALL LETTER ALPHA} {sum(x)}"', 'α 6.0'),
                (r'rf"\{sum(x)}"', '\\6.0')]:
            with self.subTest(expr=expr):
                self.assertTextExpression(expr, expected, ['x'])
        self.assertEqual(self.array('f"{sum(x)}"').tolist(), [6.0])

    def test_formatted_field_strings_and_setting_paths_are_not_references(self):
        self.ci.Add('page', name='page1')
        self.ci.To('/page1')
        self.ci.Add('graph', name='var2')
        self.ci.Set('/page1/var2/aspect', 8)
        self.ci.SetData('var2', [10])
        self.ci.SetData('x', [1, 2, 3])
        self.assertTextExpression(
            'f"x + var2 {sum(x) / SETTING(\'/page1/var2/aspect\')}"',
            'x + var2 0.75', ['x'])
        self.assertTextExpression('f"{len(\'x + var2\') + sum(x)}"',
                                  '14.0', ['x'])

    def test_format_specs_preserve_unicode_names_and_escape_pairs(self):
        self.ci.SetData('x', [1, 2, 3])
        self.ci.SetData('SPACE', [7])
        expr = r'f"{sum(x):\N{SPACE}>10}"'
        self.assertTextExpression(expr, '       6.0', ['x'])
        self.assertEqual(self.array(expr).tolist(), [6.0])

        class EchoSpec:
            def __format__(self, spec):
                return spec

        # Observe the evaluated spec itself, including ones that aren't valid
        # numeric format mini-language strings. This changes no evaluator policy.
        self.doc.evaluate.context['spec_echo'] = EchoSpec()
        for expr, expected, refs in [
                (r'f"{spec_echo:\N{SPACE}>10}"', ' >10', []),
                (r'rf"{spec_echo:\N{SPACE}>10}"', r'\N[7.]>10', ['SPACE']),
                (r'f"{spec_echo:\\N{SPACE}>10}"', r'\N[7.]>10', ['SPACE']),
                (r'rf"{spec_echo:\\N{SPACE}>10}"', r'\\N[7.]>10', ['SPACE']),
                (r'f"{spec_echo:{spec_echo:\N{SPACE}>10}}"', ' >10', [])]:
            with self.subTest(expr=expr):
                self.assertTextExpression(expr, expected, refs)
        if sys.version_info >= (3, 12):
            self.assertTextExpression(
                r'rf"{spec_echo:{spec_echo:\N{SPACE}>10}}"',
                r'\N[7.]>10', ['SPACE'])

    def test_nested_format_spec_fields_resolve_datasets(self):
        self.ci.SetData('x', [1, 2, 3])
        self.ci.SetData('width', [8])
        self.ci.SetData('precision', [2])
        self.assertTextExpression(
            'f"{sum(x):{int(sum(width))}.{int(sum(precision))}f}"',
            '    6.00', ['x', 'width', 'precision'])

    @unittest.skipIf(sys.version_info < (3, 12), 'PEP 701 requires Python 3.12')
    def test_pep701_nested_same_quotes_and_comments(self):
        self.ci.SetData('x', [1, 2, 3])
        self.ci.SetData('a"b', [4])
        self.assertTextExpression('f"{len("x + x") + sum(x)}"',
                                  '11.0', ['x'])
        self.assertTextExpression('f"{f"{sum(x)}"}"', '6.0', ['x'])
        self.assertTextExpression('f"{sum(`a"b`)}"', '4.0', ['a"b'])
        self.assertTextExpression('f"{sum(x) # x + } is a comment\n}"',
                                  '6.0', ['x'])

    def test_template_prefix_and_fields_follow_literal_grammar(self):
        expr = 't"t + x {sum(x)}"'
        actual, refs = substituteDatasets({'t', 'x'}, expr, 'data')
        self.assertEqual(actual, 't"t + x {sum(_DS_(\'x\', \'data\'))}"')
        self.assertEqual(refs, ['x'])
        if sys.version_info >= (3, 14):
            self.ci.SetData('t', [1])
            self.ci.SetData('x', [1, 2, 3])
            with mock.patch.object(self.doc, 'log'):
                # A template is not numeric; do not relax result validation.
                self.assertIsNone(self.array(expr))

    def test_malformed_literals_return_to_checked_compiler(self):
        for expr in ['"x + x', 'f"{sum(x)', 'f"{x!s',
                     'f"{x:{width}', 'f"{([x)}"', 'f"' + '{' * 2000,
                     'f"{' * 1000]:
            with self.subTest(expr=expr[:60]):
                actual, refs = substituteDatasets({'x', 'width'}, expr, 'data')
                self.assertIsInstance(actual, str)
                with mock.patch.object(self.doc, 'log'):
                    self.assertIsNone(self.array(expr))

    def test_comments_cannot_open_literals_or_add_dependencies(self):
        self.ci.SetData('x', [1])
        self.ci.SetData('y', [2])
        self.ci.SetData('a#b', [3], symerr=[.5])
        for comment in ['# a " quote', "# x + ''' + y",
                        '# `missing` + a#b', '# f"{sum(x)}']:
            for newline in ['\n', '\r', '\r\n']:
                expr = '(x + 1 ' + comment + newline + ' + y )'
                with self.subTest(comment=comment, newline=newline):
                    actual, refs = substituteDatasets(self.doc.data, expr, 'data')
                    self.assertIn(comment + newline, actual)
                    self.assertEqual(refs, ['x', 'y'])
                    self.assertEqual(self.array(expr).tolist(), [4])
        # Hashes within recognized legacy dataset tokens are not comments.
        expr = '(a#b + a#b_serr # " a#b + x\n + y )'
        actual, refs = substituteDatasets(self.doc.data, expr, 'data')
        self.assertEqual(refs, ['a#b', 'a#b', 'y'])
        self.assertEqual(self.array(expr).tolist(), [5.5])

    def test_backticks_and_error_columns_keep_existing_grammar(self):
        expr = '`a-b` + `a"b` + a_serr + a_perr + a_nerr + a_data'
        actual, refs = substituteDatasets({'a'}, expr, 'data')
        self.assertEqual(refs, ['a-b', 'a"b', 'a', 'a', 'a', 'a'])
        self.assertEqual(actual,
                         "_DS_('a-b', 'data') + _DS_('a\"b', 'data') + "
                         "_DS_('a', 'serr') + _DS_('a', 'perr') + "
                         "_DS_('a', 'nerr') + _DS_('a', 'data')")
        self.assertEqual(substituteDatasets({'a'}, '`a_serr`', 'nerr'),
                         ("_DS_('a_serr', 'nerr')", ['a_serr']))
        # Preserve also the nonidentifier names accepted without backticks by
        # the old split grammar; no Python identifier/AST redesign here.
        for name in ['a:b', '$a', 'a#b', 'α']:
            self.assertEqual(substituteDatasets({name}, name, 'data'),
                             ("_DS_(%r, 'data')" % name, [name]))
        self.ci.SetData('a-b', [2, 4], symerr=[.1, .2])
        self.ci.SetData('a', [1, 2], symerr=[.3, .4])
        self.assertEqual(self.array('`a-b` + a_serr').tolist(), [2.3, 4.4])
        linked = datasets.DatasetExpression(data='`a-b`', serr='`a-b`')
        self.doc.setData('linked', linked)
        self.assertEqual(linked.data.tolist(), [2, 4])
        self.assertEqual(linked.serr.tolist(), [.1, .2])

    def test_linked_expression_and_text_evaluation_share_shielding(self):
        self.ci.SetData('a', [1, 2])
        self.ci.SetDataExpression('linked', 'a + len("a + a")', linked=True)
        self.assertEqual(self.doc.data['linked'].data.tolist(), [6, 7])
        text = self.doc.evaluate.evalDatasetExpression(
            '["a + a", "`a`"]', datatype='text')
        self.assertEqual(text.data, ['a + a', '`a`'])
        self.assertEqual(substituteDatasets(
            self.doc.data, 'a + len("a + a")', 'data')[1], ['a'])

    def test_constant_bare_and_parenthesized_then_dataset_precedence(self):
        self.ci.AddCustom('constant', 'Planck_const', '6.62607015e-34')
        for expr in ['Planck_const', '(Planck_const)']:
            self.assertEqual(self.array(expr).tolist(), [6.62607015e-34])
        self.ci.SetData('Planck_const', [2, 3])
        for expr in ['Planck_const', '(Planck_const)']:
            self.assertEqual(self.array(expr).tolist(), [2, 3])

    def test_existing_wrong_type_or_dimension_does_not_use_constant(self):
        self.ci.AddCustom('constant', 'Planck_const', '6.62607015e-34')
        for ds in [datasets.DatasetText(['text']), datasets.Dataset2D([[1]])]:
            self.doc.setData('Planck_const', ds)
            with mock.patch.object(self.doc, 'log') as log:
                self.assertIsNone(self.array('Planck_const'))
                log.assert_not_called()

    def test_unknown_bare_names_remain_silent(self):
        with mock.patch.object(self.doc, 'log') as log:
            self.assertIsNone(self.array('missing_dataset'))
            log.assert_not_called()

    def test_context_values_undergo_normal_result_validation(self):
        self.ci.AddCustom('constant', 'text_constant', "'not numeric'")
        self.ci.AddCustom('constant', 'scalar_constant', '3')
        self.ci.AddCustom('constant', 'matrix_constant', '[[1,2],[3,4]]')
        with mock.patch.object(self.doc, 'log'):
            self.assertIsNone(self.array('text_constant'))
            self.assertIsNone(self.array('scalar_constant', dimensions=2))
        self.assertEqual(self.array('matrix_constant', dimensions=2).tolist(),
                         [[1, 2], [3, 4]])

    def test_constant_fallback_uses_checked_compilation(self):
        self.ci.AddCustom('constant', 'Planck_const', '6.62607015e-34')
        with mock.patch.object(self.doc.evaluate, 'compileCheckedExpression',
                               return_value=None) as compile_checked:
            self.assertIsNone(self.array('Planck_const'))
            compile_checked.assert_called_once_with(
                'Planck_const', origexpr='Planck_const')
        self.doc.evaluate.setSecurity(False)
        with mock.patch.object(self.doc, 'log'):
            self.assertIsNone(self.array('__import__("os")'))


if __name__ == '__main__':
    unittest.main()
