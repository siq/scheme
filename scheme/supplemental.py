import re
from types import ModuleType

from scheme.exceptions import *
from scheme.fields import Field, Error, Text
from scheme.util import construct_all_list, identify_object, import_object

EMAIL_EXPR = (
    r"([-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"
    r'|"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-\011\013\014\016-\177])*"'
    r')@(?:[A-Z0-9-]+\.)+[A-Z]{2,6}')

class ObjectReference(Field):
    """A resource field for references to python objects."""

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a python object'),
        Error('import', 'object import', '%(field)s specifies %(value)r, which cannot be imported'),
    ]

    def get_default(self):
        return self.default

    def _serialize_value(self, value):
        return identify_object(value)

    def _unserialize_value(self, value, ancestry):
        if isinstance(value, basestring):
            try:
                return import_object(value)
            except ImportError:
                error = ValidationError(identity=ancestry, field=self, value=value).construct(
                    'import', value=value)
                raise error.capture()
        else:
            return value

class Url(Text):
    """A resource field for urls."""

    pattern = re.compile('(?i)'
        r'^([^:]+)://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$'
    )

__all__ = construct_all_list(locals(), Field)
