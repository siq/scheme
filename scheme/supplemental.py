from scheme.exceptions import *
from scheme.fields import Field
from scheme.util import construct_all_list, identify_class, import_object

class ObjectReference(Field):
    """A resource field for references to python objects."""

    errors = {
        'invalid': '%(field)s must be a python object',
        'import': '%(field)s specifies a python object which cannot be imported',
    }

    def _serialize_value(self, value):
        return identify_class(value)

    def _unserialize_value(self, value):
        if not isinstance(value, basestring):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        try:
            return import_object(value)
        except ImportError:
            raise ValidationError(value=value).construct(self, 'import')

    def _validate_value(self, value):
        if not isinstance(value, type):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

__all__ = construct_all_list(locals(), Field)
