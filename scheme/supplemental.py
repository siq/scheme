import re
from string import whitespace
from types import ModuleType

from scheme.exceptions import *
from scheme.fields import Field, FieldError, Text
from scheme.util import construct_all_list, identify_object, import_object

__all__ = ('Email',)

EMAIL_EXPR = (
    r"([-!#$%&'*+/=?^_`{}|~0-9a-zA-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9a-zA-Z]+)*"
    r'|"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-\011\013\014\016-\177])*"'
    r')@([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,6}')
EMAIL_ADDRESS_EXPR = re.compile(r'^(%s)?$' % EMAIL_EXPR)
EXTENDED_EMAIL_ADDRESS_EXPR = re.compile(r'^(("[^"]+"[ ]+<%s>)|([^<]+[ ]+<%s>)|(%s))?$'
    % (EMAIL_EXPR, EMAIL_EXPR, EMAIL_EXPR))
EMAIL_LIST_EXPR = re.compile(r'^(%s(,%s)*)?$' % (EMAIL_EXPR, EMAIL_EXPR))

SEPARATOR_EXPR = re.compile(r'[\s,;:]+')
SEPARATORS = whitespace + ',;:'

class Email(Text):
    """A field for one or more email addresses, separated by whitespace, commas, semicolons
    or colons."""

    single_errors = [FieldError('pattern', 'invalid value', '%(field)s must be a valid email address')]
    multiple_errors = [FieldError('pattern', 'invalid value', '%(field)s must be a list of valid email addresses')]
    parameters = {'extended': False, 'multiple': False, 'strip': False, 'escape_html_entities': False}

    def __init__(self, multiple=False, extended=False, pattern=None, strip=None, errors=None, **params):
        if multiple:
            errors = self.multiple_errors
            if not extended:
                pattern = EMAIL_LIST_EXPR
            else:
                raise TypeError('field does not support multiple=True and extended=True')
        else:
            errors = self.single_errors
            if not extended:
                pattern = EMAIL_ADDRESS_EXPR
            else:
                pattern = EXTENDED_EMAIL_ADDRESS_EXPR

        self.extended = extended
        self.multiple = multiple
        params['escape_html_entities'] = False
        super(Email, self).__init__(errors=errors, strip=False, pattern=pattern, **params)

    def __repr__(self):
        aspects = []
        if self.multiple:
            aspects.append('multiple=True')
        if self.extended:
            aspects.append('extended=True')
        return super(Email, self).__repr__(aspects)

    def preprocessor(self, value):
        if self.extended:
            return value
        
        value = value.strip(SEPARATORS).lower()
        if self.multiple:
            value = SEPARATOR_EXPR.sub(',', value)

        return value.lower()

class ObjectReference(Field):
    """A resource field for references to python objects."""

    errors = [
        FieldError('invalid', 'invalid value', '%(field)s must be a python object'),
        FieldError('import', 'object import', '%(field)s specifies %(value)r, which cannot be imported'),
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

    def __init__(self, **params):
        errors = [
            FieldError('pattern', 'invalid value', '%(field)s must be a valid URL')
        ]
        pattern = re.compile('(?i)'
            r'^(?:([^:]+)://)?'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$'
        )
        params['escape_html_entities'] = False
        super(Url, self).__init__(errors=errors, strip=False, pattern=pattern, **params)


__all__ = construct_all_list(locals(), Field)
