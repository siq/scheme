from datetime import date, datetime, time
from unittest2 import TestCase
from urllib import unquote

from scheme.formats import *

class TestStructuredText(TestCase):
    def assert_correct(self, pairs):
        for unserialized, serialized in pairs:
            self.assertEqual(StructuredText.serialize(unserialized), serialized)
            self.assertEqual(StructuredText.unserialize(serialized), unserialized)

    def test_booleans(self):
        self.assert_correct([
            (True, 'true'),
            (False, 'false'),
        ])
        self.assertEqual(StructuredText.unserialize('True'), True)
        self.assertEqual(StructuredText.unserialize('False'), False)

    def test_mappings(self):
        self.assert_correct([
            ({}, '{}'),
            ({'b': '1'}, '{b:1}'),
            ({'b': '1', 'c': '2'}, '{b:1,c:2}'),
            ({'b': True}, '{b:true}'),
            ({'b': 'a:b'}, '{b:a:b}'),
        ])

    def test_sequences(self):
        self.assert_correct([
            ([], '[]'),
            (['1'], '[1]'),
            (['1', '2'], '[1,2]'),
            ([True, False], '[true,false]'),
        ])

    def test_nested_structures(self):
        self.assert_correct([
            ({'b': {}}, '{b:{}}'),
            (['1', '2', ['3', []]], '[1,2,[3,[]]]'),
            ([True, {'b': [False, '1']}], '[true,{b:[false,1]}]'),
        ])

    def test_parsing_numbers(self):
        self.assertEqual(StructuredText.unserialize('1', True), 1)
        self.assertEqual(StructuredText.unserialize('{b:1.2}', True), {'b': 1.2})

    def test_parsing_escape_characters(self):
        self.assert_correct([
            ('{', '\{'),
            ('}', '\}'),
            ('{}', '\{\}'),
            ('{a}', '\{a\}'),
        ])
        self.assert_correct([
            ('[', '\['),
            (']', '\]'),
            ('[]', '\[\]'),
            ('[a]', '\[a\]'),
        ])
        self.assert_correct([
            ({'b': '{}'}, '{b:\{\}}'),
            ({'b': '[]'}, '{b:\[\]}'),
            ({'a': '[]', 'b': '{}', 'c': '1', 'd': [], 'e': {}}, '{a:\[\],b:\{\},c:1,d:[],e:{}}'),
        ])
        self.assert_correct([
            (['{}'], '[\{\}]'),
            (['[]'], '[\[\]]'),
            (['{}', '[]', 'b', [], {}], '[\{\},\[\],b,[],{}]'),
        ])
        self.assert_correct([
            (r'\\', r'\\'),
            (r'\\b', r'\\b'),
        ])

SINGLE_DICT = """a: 1
b: true
c: something"""

DICT_WITHIN_DICT = """a:
  b: 1
  c: true
d:
  e: 2
  f: false"""

SINGLE_LIST = """- 1
- 2
- 3"""

LIST_WITHIN_LIST = """- - 1
  - 2
- - 3
  - 4"""

DICT_WITHIN_LIST = """- a: 1
  b: true
- a: 2
  b: false"""

LIST_WITHIN_DICT = """a:
  - 1
  - 2
b:
  - 3
  - 4"""

class TestYaml(TestCase):
    def assert_correct(self, pairs):
        for unserialized, serialized in pairs:
            self.assertEqual(Yaml.serialize(unserialized), serialized)
            self.assertEqual(Yaml.unserialize(serialized), unserialized)

    def assert_serializes(self, unserialized, serialized):
        self.assertEqual(Yaml.serialize(unserialized), serialized)

    def _test_simple_values(self):
        self.assert_correct([
            (None, 'null'),
            (True, 'true'),
            (False, 'false'),
            (1, '1'),
            (1.0, '1.0'),
            (date(2000, 1, 1), '2000-01-01'),
            (datetime(2000, 1, 1, 0, 0, 0), '2000-01-01 00:00:00'),
        ])

    def _test_required_quotes(self):
        self.assert_correct([
            ('', "''"),
            ('null', "'null'"),
            ('Null', "'Null'"),
            ('NULL', "'NULL'"),
            ('~', "'~'"),
            ('true', "'true'"),
            ('True', "'True'"),
            ('TRUE', "'TRUE'"),
            ('false', "'false'"),
            ('False', "'False'"),
            ('FALSE', "'FALSE'"),
        ])

    def _test_empty_values(self):
        self.assert_correct([
            ({}, '{}'),
            ([], '[]'),
        ])

        self.assert_serializes(set(), '[]')
        self.assert_serializes((), '[]')

    def _test_complex_values(self):
        self.assert_correct([
            ({'a': 1, 'b': True, 'c': 'something'}, SINGLE_DICT),
            ({'a': {'b': 1, 'c': True}, 'd': {'e': 2, 'f': False}}, DICT_WITHIN_DICT),
            ([1, 2, 3], SINGLE_LIST),
            ([[1, 2], [3, 4]], LIST_WITHIN_LIST),
            ([{'a': 1, 'b': True}, {'a': 2, 'b': False}], DICT_WITHIN_LIST),
            ({'a': [1, 2], 'b': [3, 4]}, LIST_WITHIN_DICT),
        ])

        self.assert_serializes((1, 2, 3), SINGLE_LIST)

class TestUrlEncoded(TestCase):
    def assert_correct(self, pairs):
        for unserialized, serialized in pairs:
            self.assertEqual(unquote(UrlEncoded.serialize(unserialized)), serialized)
            self.assertEqual(UrlEncoded.unserialize(serialized), unserialized)

    def test_invalid_data(self):
        self.assertRaises(ValueError, lambda: UrlEncoded.serialize(True))
        self.assertRaises(ValueError, lambda: UrlEncoded.unserialize(True))

    def test_booleans(self):
        self.assert_correct([
            ({'a': True}, 'a=true'),
            ({'a': False}, 'a=false'),
        ])

    def test_mappings(self):
        self.assert_correct([
            ({'a': {}}, 'a={}'),
            ({'a': {'b': '1'}}, 'a={b:1}'),
            ({'a': {'b': '1', 'c': '2'}}, 'a={b:1,c:2}'),
            ({'a': {'b': True}}, 'a={b:true}'),
        ])

    def test_sequences(self):
        self.assert_correct([
            ({'a': []}, 'a=[]'),
            ({'a': ['1']}, 'a=[1]'),
            ({'a': ['1', '2']}, 'a=[1,2]'),
            ({'a': [True]}, 'a=[true]'),
        ])

    def test_nested_structures(self):
        self.assert_correct([
            ({'a': {'b': {}}}, 'a={b:{}}'),
            ({'a': ['1', '2', ['3', []]]}, 'a=[1,2,[3,[]]]'),
            ({'a': [True, {'b': [False, '1']}]}, 'a=[true,{b:[false,1]}]'),
        ])

    def test_escaped_characters(self):
        self.assert_correct([
            ({'a': {'b': '{}'}}, 'a={b:\{\}}'),
            ({'a': '{b:c}'}, 'a=\{b:c\}'),
            ({'a': ['1', '2', ['3', '[]']]}, 'a=[1,2,[3,\[\]]]'),
            ({'a': ['1', '2', '[', '4']}, 'a=[1,2,\[,4]'),
            ({'a': ['{}', {}, '[]', []]}, 'a=[\{\},{},\[\],[]]'),
        ])

class TestXml(TestCase):
    def assert_correct(self, pairs):
        for unserialized, serialized in pairs:
            self.assertEqual(Xml.serialize(unserialized, preamble=False), serialized)
            self.assertEqual(Xml.unserialize(serialized), unserialized)

    def assert_serializes(self, unserialized, serialized):
        self.assertEqual(Xml.serialize(unserialized, preamble=False), serialized)

    def test_simple_values(self):
        self.assert_correct([
            (None, '<root>null</root>'),
            (True, '<root>true</root>'),
            (False, '<root>false</root>'),
            (1, '<root>1</root>'),
            (1.0, '<root>1.0</root>'),
            ('testing', '<root>testing</root>'),
            ('', '<root />'),
        ])

    def test_empty_values(self):
        self.assert_correct([
            ({}, '<root type="struct" />'),
            ([], '<root type="list" />'),
        ])

        self.assert_serializes(set(), '<root type="list" />')
        self.assert_serializes((), '<root type="list" />')

    def test_complex_values(self):
        self.assert_correct([
            ({'a': 1, 'b': True, 'c': 'something'}, '<root><a>1</a><b>true</b><c>something</c></root>'),
            ({'a': {'b': 1, 'c': True}, 'd': {'e': 2, 'f': False}},
                '<root><a><b>1</b><c>true</c></a><d><e>2</e><f>false</f></d></root>'),
            ([1, 2, 3], '<root><_>1</_><_>2</_><_>3</_></root>'),
            ([[1, 2], [3, 4]], '<root><_><_>1</_><_>2</_></_><_><_>3</_><_>4</_></_></root>'),
            ([{'a': 1, 'b': True}, {'a': 2, 'b': False}],
                '<root><_><a>1</a><b>true</b></_><_><a>2</a><b>false</b></_></root>'),
            ({'a': [1, 2], 'b': [3, 4]}, '<root><a><_>1</_><_>2</_></a><b><_>3</_><_>4</_></b></root>'),
        ])

        self.assert_serializes((1, 2, 3), '<root><_>1</_><_>2</_><_>3</_></root>')
