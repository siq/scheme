from scheme.supplemental import *
from scheme.util import StructureFormatter
from tests.test_fields import FieldTestCase

class TestEmail(FieldTestCase):
    def test_single_processing(self):
        field = Email()
        self.assert_processed(field, None, '', 'alpha@test.com')
        self.assert_not_processed(field, 'pattern', 'not an email')
        self.assertEqual(field.process('  alpha@TEST.com'), 'alpha@test.com')

        field = Email(nonempty=True)
        self.assert_processed(field, 'alpha@test.com')
        self.assert_not_processed(field, 'nonnull', None)
        self.assert_not_processed(field, 'min_length', '')

    def test_multiple_processing(self):
        field = Email(multiple=True)
        self.assert_processed(field, None, '', 'alpha@test.com', 'alpha@test.com,beta@test.com')
        self.assert_not_processed(field, 'pattern', 'not an email', 'alpha@test.com,not an email')
        self.assertEqual(field.process('  alpha@TEST.com'), 'alpha@test.com')
        self.assertEqual(
            field.process('   alpha@test.com, beta@test.com;gamma@test.com   delta@test.com:eplison@test.com;;,iota@test.com,'),
            'alpha@test.com,beta@test.com,gamma@test.com,delta@test.com,eplison@test.com,iota@test.com')

        field = Email(multiple=True, nonempty=True)
        self.assert_processed(field, 'alpha@test.com', 'alpha@test.com,beta@test.com')
        self.assert_not_processed(field, 'nonnull', None)
        self.assert_not_processed(field, 'min_length', '')

    def test_extended_processing(self):
        field = Email(extended=True)
        self.assert_processed(field, None, '', 'alpha@test.com', 'Alpha <alpha@test.com>',
            '"Alpha" <alpha@test.com>', '"Alpha < Beta" <alpha@test.com>')
        self.assert_not_processed(field, 'pattern', 'not an email', 'Alpha < Beta <alpha@test.com>')

class TestObjectReference(FieldTestCase):
    def _test_processing(self):
        field = ObjectReference()
        self.assert_not_processed(field, 'invalid', True)
        self.assert_processed(field, None, (StructureFormatter, 'scheme.util.StructureFormatter'))
