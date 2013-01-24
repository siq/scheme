import re
from string import whitespace
from types import ModuleType

from scheme.exceptions import *
from scheme.fields import Field, Error, Text
from scheme.util import construct_all_list, identify_object, import_object

EMAIL_EXPR = (
    r"([-!#$%&'*+/=?^_`{}|~0-9a-zA-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9a-zA-Z]+)*"
    r'|"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-\011\013\014\016-\177])*"'
    r')@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,6}')
EMAIL_ADDRESS_EXPR = re.compile(r'^(?:%s)?$' % EMAIL_EXPR)
EMAIL_LIST_EXPR = re.compile(r'^(?:%s(?:,%s)*)?$' % (EMAIL_EXPR, EMAIL_EXPR))

SEPARATOR_EXPR = re.compile(r'[\s,;:]+')
SEPARATORS = whitespace + ',;:'

class Email(Text):
    """A field for one or more email addresses, separated by whitespace, commas, semicolons
    or colons."""

    single_error = Error('pattern', 'invalid value', '%(field)s must be a valid email address')
    multiple_error = Error('pattern', 'invalid value', '%(field)s must be a list of valid email addresses')

    def __init__(self, multiple=False, **params):
        self.multiple = multiple
        if multiple:
            super(Email, self).__init__(errors=[self.multiple_error], strip=False,
                pattern=EMAIL_LIST_EXPR, **params)
        else:
            super(Email, self).__init__(errors=[self.single_error], strip=False,
                pattern=EMAIL_ADDRESS_EXPR, **params)

    @staticmethod
    def preprocessor(value):
        return SEPARATOR_EXPR.sub(',', value.strip(SEPARATORS)).lower()

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

    errors = [
        Error('pattern', 'invalid value', '%(field)s must be a valid URL')
    ]
    pattern = re.compile('(?i)'
        r'^(?:([^:]+)://)?'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$'
    )

__all__ = construct_all_list(locals(), Field)
