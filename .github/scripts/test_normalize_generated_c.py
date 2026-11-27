import unittest

from normalize_generated_c import (
    PREFIX,
    normalize,
)


class GeneratedCContractTests(unittest.TestCase):
    def test_review_metadata_is_normalized(self):
        source = 'CPy_AddTraceback("a.py", "f", 52, globals); CPyStatics[19];\n'
        expected = (
            'CPy_AddTraceback("a.py", "f", DIFFCHECK_PLACEHOLDER, globals); '
            "CPyStatics[DIFFCHECK_PLACEHOLDER];\n"
        )
        self.assertEqual(normalize(source), PREFIX + expected)

    def test_normalization_is_idempotent(self):
        source = 'CPy_AddTraceback("a.py", "f", 52, globals);\n'
        self.assertEqual(normalize(normalize(source)), normalize(source))

    def test_runtime_operations_are_preserved(self):
        source = "value = 3; table[29] = value;\n"
        self.assertEqual(normalize(source), PREFIX + source)
