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
