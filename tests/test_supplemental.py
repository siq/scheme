from scheme.supplemental import *
from scheme.util import StructureFormatter
from tests.test_fields import FieldTestCase

class TestObjectReference(FieldTestCase):
    def _test_processing(self):
        field = ObjectReference()
        self.assert_not_processed(field, 'invalid', True)
        self.assert_processed(field, None, (StructureFormatter, 'scheme.util.StructureFormatter'))
