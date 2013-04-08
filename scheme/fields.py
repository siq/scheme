import os
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from copy import deepcopy
from datetime import datetime, date, time
from decimal import Decimal as decimal
from time import mktime, strptime

from scheme.exceptions import *
from scheme.formats import Format
from scheme.interpolation import interpolate_parameters, UndefinedValueError
from scheme.timezone import LOCAL, UTC
from scheme.util import *

try:
    from collections import OrderedDict
except ImportError:
    OrderedDict = dict

NATIVELY_SERIALIZABLE = (basestring, bool, float, int, long, type(None), dict, list, tuple)
PATTERN_TYPE = type(re.compile(''))

INCOMING = 'incoming'
OUTGOING = 'outgoing'

class CannotDescribeError(Exception):
    """Raised when a parameter to a field cannot be described for serialization."""

class FieldExcludedError(Exception):
    """Raised when a field is excluded during the extraction of a value."""

class Error(object):
    """A field error."""

    def __init__(self, token, title, message, show_field=True, show_value=True):
        self.message = message
        self.show_field = show_field
        self.show_value = show_value
        self.title = title
        self.token = token

    def format(self, field, params):
        if 'field' not in params:
            params['field'] = field.name or 'unknown-field'
        return self.message % params

class FieldMeta(type):
    def __new__(metatype, name, bases, namespace):
        declared_errors = namespace.pop('errors', ())
        declared_parameters = namespace.pop('parameters', ())

        field = type.__new__(metatype, name, bases, namespace)
        field.type = name.lower()

        errors = {}
        parameters = set()

        for base in reversed(bases):
            inherited_errors = getattr(base, 'errors', None)
            if inherited_errors:
                errors.update(inherited_errors)
            inherited_parameters = getattr(base, 'parameters', None)
            if inherited_parameters:
                parameters.update(inherited_parameters)

        field.errors = errors
        for error in declared_errors:
            errors[error.token] = error

        parameters.update(declared_parameters)
        field.parameters = parameters

        field.types[field.type] = field
        return field

    def reconstruct(field, specification):
        """Reconstructs the field described by ``specification``."""

        if isinstance(specification, Field):
            return specification
        if specification is not None:
            constructor = field.types[specification.pop('__type__')]
            return constructor.construct(specification)

class Field(object):
    """A resource field.

    :param string name: The name of this field.

    :param string description: Optional, default is ``None``; a concise description
        of this field, used prominently in generated documentation.

    :param default: Optional, default is ``None``; if specified, indicates
        the default value for this field when no value is present in a
        request to the associated resource. Only applicable when this field
        is part of a ``Structure``.

    :param boolean nonnull: Optional, default is ``False``; if ``True``, indicates
        this field must have a value other than ``None`` when present in a
        request to the associated resource.

    :param boolean ignore_null: Optional, default is ``False``; if ``True``, indicates
        a null value for this field will be treated as if a value wasn't specified
        when processing a ``Structure`` value.

    :param boolean required: Optional, default is ``False``; if ``True``, indicates
        this field is required to be present in a request to the associated
        resource. Only applicable when this field is part of a ``Structure``.

    :param constant: Optional, default is ``None``; if specified, constrains this
        field to only accept this exact value.

    :param dict errors: Optional, default is ``None``; specifies custom error
        strings for this field.

    :param string title: Optional, default is ``None``; a public title for this field,
        for when a more civilized age is longed for.

    :param string notes: Optional, notes of any length concerning the use of
        this field, used primarily for documentation.

    :param boolean nonempty: Optional, default is ``False``; if ``True``, is
        equivalent at a minimum to ``nonnull=True`` and ``required=True``;
        subclasses may add behavior.

    :param instantiator: Optional, default is ``None``; specifies an instantiation
        callback for this field.

    :param extractor: Optional, default is ``None``; specifies an extraction
        callback for this field.

    :param preprocessor: Optional, default is ``None``; specifies a preprocessor
        function for this field, which will be given a value to preprocess after
        unserialization but before validation.

    :param dict aspects: Optional, default is ``None``; if specified, a dictionary
        with string keys containing extension aspects for this field.
    """

    __metaclass__ = FieldMeta
    types = {}

    errors = [
        Error('invalid', 'invalid value', '%(field)s is an invalid value'),
        Error('nonnull', 'null value', '%(field)s must be a non-null value'),
    ]
    equivalent = None
    parameters = ('name', 'constant', 'description', 'default', 'nonnull',
        'ignore_null', 'required', 'title', 'notes', 'structural')
    preprocessor = None
    structural = False

    def __init__(self, name=None, description=None, default=None, nonnull=False,
        ignore_null=False, required=False, constant=None, errors=None, title=None,
        notes=None, nonempty=False, instantiator=None, extractor=None,
        preprocessor=None, aspects=None, **params):

        if nonempty:
            nonnull = required = True

        if isinstance(instantiator, basestring):
            instantiator = import_object(instantiator)
        if instantiator:
            instantiator = getattr(instantiator, '__instantiate__', instantiator)

        if isinstance(extractor, basestring):
            extractor = import_object(extractor)
        if extractor:
            extractor = getattr(extractor, '__extract__', extractor)

        self.aspects = aspects or {}
        self.constant = constant
        self.default = default
        self.description = description
        self.extractor = extractor
        self.ignore_null = ignore_null
        self.instantiator = instantiator
        self.name = name
        self.notes = notes
        self.nonnull = nonnull
        self.required = required
        self.title = title

        if preprocessor is not None:
            self.preprocessor = preprocessor

        if errors:
            self.errors = self.errors.copy()
            for error in errors:
                self.errors[error.token] = error

        for attr, value in params.iteritems():
            if attr[0] != '_' and value is not None:
                self.aspects[attr] = value

    def __repr__(self, params=None, structure=None):
        aspects = []
        if self.name:
            aspects.append('name=%r' % self.name)
        if params:
            aspects.extend(params)
        if self.constant:
            aspects.append('constant=True')
        if self.default is not None:
            aspects.append('default=%r' % self.default)
        if self.nonnull:
            aspects.append('nonnull=True')
        if self.required:
            aspects.append('required=True')
        if self.title:
            aspects.append('title=%r' % self.name)
        if structure:
            aspects.append(structure)
        return '%s(%s)' % (type(self).__name__, ', '.join(aspects))

    def __deepcopy__(self, memo):
        return self.clone()

    def __getattr__(self, name):
        try:
            return super(Field, self).__getattr__(name)
        except AttributeError:
            try:
                return self.aspects[name]
            except KeyError:
                return None

    @property
    def guaranteed_name(self):
        return self.name or '(%s)' % self.type

    def clone(self, **params):
        """Clones this field by deep copying it. Keyword parameters are applied to the cloned
        field before returning it."""

        if 'default' not in params:
            params['default'] = self.default

        for key, value in self.__dict__.iteritems():
            if key not in params:
                try:
                    value = deepcopy(value)
                except TypeError:
                    pass
                params[key] = value

        return type(self)(**params)

    @classmethod
    def construct(cls, specification):
        """Constructs an instance of this field using ``specification``, which should be a
        dictionary of field parameters."""

        parameters = cls._construct_parameter(specification)
        return cls(**parameters)

    def describe(self, parameters=None, **params):
        """Constructs a serializable description of this field as a dictionary, which will
        contain enough information to reconstruct this field in another context. Any keyword
        parameters are mixed into the description."""

        description = {'__type__': self.type}
        for attr, value in self.aspects.iteritems():
            if value is not None:
                try:
                    description[attr] = self._describe_parameter(value)
                except CannotDescribeError:
                    pass

        for source in (self.parameters, parameters):
            if not source:
                continue
            for parameter in source:
                if parameter not in params:
                    value = getattr(self, parameter, None)
                    if value is not None:
                        try:
                            description[parameter] = self._describe_parameter(value)
                        except CannotDescribeError:
                            pass

        for name, value in params.iteritems():
            if value is not None:
                try:
                    description[name] = self._describe_parameter(value)
                except CannotDescribeError:
                    pass

        return description

    def extract(self, subject, **params):
        """Attempts to extract a valid value for this field from ``subject``."""

        if params and not self.screen(**params):
            raise FieldExcludedError(self)
        if subject is not None and self.extractor:
            return self.extractor(self, subject)
        else:
            return subject

    def filter(self, exclusive=False, **params):
        """Filters this field based on the tests given in ``params``."""

        included = (not exclusive)
        for attr, value in params.iteritems():
            if value is True:
                if getattr(self, attr, False):
                    included = True
            elif value is False:
                if getattr(self, attr, False):
                    included = False
                    break
                else:
                    included = True
        if included:
            return self

    def get_default(self):
        """Returns the default value for this field."""

        default = self.default
        if callable(default):
            default = default()
        return default

    def instantiate(self, value, key=None):
        """Instantiates ``value``, which will be a valid for this field, into another
        representation, as controlled by the ``instantiator`` aspect."""

        if value is not None and self.instantiator:
            return self.instantiator(self, value, key)
        else:
            return value

    def interpolate(self, subject, parameters, interpolator=None):
        equivalent = self.equivalent
        if subject is None or (equivalent and isinstance(subject, equivalent)):
            return subject
        else:
            return interpolate_parameters(subject, parameters, interpolator, True)

    def process(self, value, phase=INCOMING, serialized=False, ancestry=None):
        """Processes ``value`` for this field.

        :param value: The value to process.

        :param string phase: The phase for this particular processing; either ``incoming``,
            to indicate the value is coming into the framework, or ``outgoing``, to indicate
            the value is leaving the framework.

        :param boolean serialized: Optional, defaults to ``False``; if ``True``, indicates
            ``value`` should either be unserialized before validation, if ``phase`` is
            ``incoming``, or serialized after validation, if ``phase`` is ``outgoing``.
        """

        if not ancestry:
            ancestry = [self.guaranteed_name]

        if self._is_null(value, ancestry):
            return None
        if serialized and phase == INCOMING:
            value = self._unserialize_value(value, ancestry)
        if self.preprocessor:
            value = self.preprocessor(value)
        if self.constant is not None and value != self.constant:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

        candidate = self._validate_value(value, ancestry)
        if candidate is not None:
            value = candidate

        if serialized and phase == OUTGOING:
            value = self._serialize_value(value)

        return value

    def read(self, path, **params):
        """Reads the content of the file at ``path``, unserializes it, then processes it
        as an incoming value for this field."""

        data = Format.read(path, **params)
        return self.process(data, INCOMING, True)

    def screen(self, **params):
        """Screens this field against the specified tests."""

        for attr, value in params.iteritems():
            if value is not None:
                if getattr(self, attr, None) != value:
                    return False
        else:
            return True

    def serialize(self, value, format=None, **params):
        """Serializes ``value`` to ``format``, if specified, after processing it
        as an outgoing value for this field."""

        value = self.process(value, OUTGOING, True)
        if format:
            value = Format.formats[format].serialize(value, **params)
        return value

    def unserialize(self, value, format=None, **params):
        """Unserializes ``value`` from ``format``, if specified, before processing
        it as an incoming value for this field."""

        if format:
            value = Format.formats[format].unserialize(value, **params)
        return self.process(value, INCOMING, True)

    @classmethod
    def visit(cls, specification, callback):
        return cls.types[specification['__type__']]._visit_field(specification, callback)

    def write(self, path, value, format=None, **params):
        value = self.process(value, OUTGOING, True)
        Format.write(path, value, format, **params)

    @classmethod
    def _construct_parameter(cls, parameter):
        if isinstance(parameter, dict):
            if '__type__' in parameter:
                return Field.reconstruct(parameter)
            else:
                return dict((k, cls._construct_parameter(v)) for k, v in parameter.iteritems())
        elif isinstance(parameter, (list, tuple)):
            description = [cls._construct_parameter(item) for item in parameter]
            if isinstance(parameter, list):
                return description
            else:
                return tuple(description)
        else:
            return parameter

    def _describe_parameter(self, parameter):
        if isinstance(parameter, dict):
            return dict((k, self._describe_parameter(v)) for k, v in parameter.iteritems())
        elif isinstance(parameter, (list, tuple)):
            description = [self._describe_parameter(item) for item in parameter]
            if isinstance(parameter, list):
                return description
            else:
                return tuple(description)
        elif isinstance(parameter, Field):
            return parameter.describe()
        elif isinstance(parameter, NATIVELY_SERIALIZABLE):
            return parameter
        else:
            raise CannotDescribeError(parameter)

    def _is_null(self, value, ancestry):
        if value is None:
            if self.nonnull:
                raise ValidationError(identity=ancestry, field=self).construct('nonnull')
            else:
                return True

    def _serialize_value(self, value):
        """Serializes and returns ``value``, if necessary."""

        return value

    def _unserialize_value(self, value, ancestry):
        return value

    def _validate_value(self, value, ancestry):
        """Validates ``value`` according to the parameters of this field."""

        return value

    @classmethod
    def _visit_field(cls, specification, callback):
        return {}

class Binary(Field):
    """A resource field for binary values."""

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a binary value'),
        Error('min_length', 'minimum length', '%(field)s must contain at least %(min_length)d %(noun)s'),
        Error('max_length', 'maximum length', '%(field)s must contain at most %(max_length)d %(noun)s'),
    ]
    parameters = ('max_length', 'min_length')

    def __init__(self, min_length=None, max_length=None, nonempty=False, **params):
        if nonempty:
            params.update(required=True, nonnull=True)
            if min_length is None:
                min_length = 1

        super(Binary, self).__init__(**params)
        if min_length is None or (isinstance(min_length, int) and min_length >= 0):
            self.min_length = min_length
        else:
            raise SchemeError('min_length must be an integer >= 0, if specified')

        if max_length is None or (isinstance(max_length, int) and max_length >= 0):
            self.max_length = max_length
        else:
            raise SchemeError('max_length must be an integer >= 0, if specified')

    def _serialize_value(self, value):
        return urlsafe_b64encode(str(value))

    def _unserialize_value(self, value, ancestry):
        if not isinstance(value, basestring):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        return urlsafe_b64decode(str(value))

    def _validate_value(self, value, ancestry):
        if not isinstance(value, basestring):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

        min_length = self.min_length
        if min_length is not None and len(value) < min_length:
            noun = 'byte'
            if min_length > 1:
                noun = 'bytes'
            raise ValidationError(identity=ancestry, field=self, value=value).construct(
                'min_length', min_length=min_length, noun=noun)

        max_length = self.max_length
        if max_length is not None and len(value) > max_length:
            noun = 'byte'
            if max_length > 1:
                noun = 'bytes'
            raise ValidationError(identity=ancestry, field=self, value=value).construct(
                'max_length', max_length=max_length, noun=noun)

class Boolean(Field):
    """A resource field for ``boolean`` values."""

    equivalent = bool
    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a boolean value'),
    ]

    def _validate_value(self, value, ancestry):
        if not isinstance(value, bool):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

class Date(Field):
    """A resource field for ``date`` values.

    :param minimum: Optional, default is ``None``; the earliest valid value for this field, as
        either a ``date`` or a callable which returns a ``date``.
    :param maximum: Optional, default is ``None``; the latest valid value for this field, as
        either a ``date`` or a callable which returns a ``date``.
    """


    equivalent = date
    parameters = ('maximum', 'minimum')
    pattern = '%Y-%m-%d'

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a date value'),
        Error('minimum', 'minimum value', '%(field)s must not occur before %(minimum)s'),
        Error('maximum', 'maximum value', '%(field)s must not occur after %(maximum)s'),
    ]

    def __init__(self, minimum=None, maximum=None, **params):
        super(Date, self).__init__(**params)
        self.maximum = maximum
        self.minimum = minimum

    def __repr__(self):
        aspects = []
        if self.minimum is not None:
            aspects.append('minimum=%r' % self.minimum)
        if self.maximum is not None:
            aspects.append('maximum=%r' % self.maximum)
        return super(Date, self).__repr__(aspects)

    def _serialize_value(self, value):
        return value.strftime(self.pattern)

    def _unserialize_value(self, value, ancestry):
        if isinstance(value, date):
            return value

        try:
            return date(*strptime(value, self.pattern)[:3])
        except Exception:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

    def _validate_value(self, value, ancestry):
        if not isinstance(value, date):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

        minimum = self.minimum
        if minimum is not None:
            if callable(minimum):
                minimum = minimum()
            if value < minimum:
                raise ValidationError(identity=ancestry, field=self, value=value).construct(
                    'minimum', minimum=minimum.strftime(self.pattern))

        maximum = self.maximum
        if maximum is not None:
            if callable(maximum):
                maximum = maximum()
            if value > maximum:
                raise ValidationError(identity=ancestry, field=self, value=value).construct(
                    'maximum', maximum=maximum.strftime(self.pattern))

class DateTime(Field):
    """A resource field for ``datetime`` values.

    :param minimum: Optional, default is ``None``; the earliest valid value for this field,
        as either a ``datetime`` or a callable which returns a ``datetime``. In either case,
        a naive value will be assumed to be in the timezone set for this field, and will have
        that timezone applied to it.

    :param maximum: Optional, default is ``None``; the latest valid value for this field,
        as either a ``datetime`` or a callable which returns a ``datetime``. In either case,
        a naive value will be assumed to be in the timezone set for this field, and will have
        that timezone applied to it.

    :param boolean utc: Optional, default is ``False``; if ``True``, this field will expect
        incoming values to be in UTC, and will return values in UTC.

    Values are serialized according to ISO-8601, in UTC time. A naive ``datetime`` (one with
    no ``tzinfo``) will be assumed to be in the default timezone for the field, and will be
    converted to UTC after having that timezone applied to it. On unserialization, values will
    be converted back to the default timezone (typically local).
    """

    equivalent = datetime
    parameters = ('maximum', 'minimum', 'utc')
    pattern = '%Y-%m-%dT%H:%M:%SZ'

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a datetime value'),
        Error('minimum', 'minimum value', '%(field)s must not occur before %(minimum)s'),
        Error('maximum', 'maximum value', '%(field)s must not occur after %(maximum)s'),
    ]

    def __init__(self, minimum=None, maximum=None, utc=False, **params):
        super(DateTime, self).__init__(**params)
        self.utc = utc
        if utc:
            self.timezone = UTC
        else:
            self.timezone = LOCAL

        if isinstance(minimum, datetime):
            minimum = self._normalize_value(minimum)
        if isinstance(maximum, datetime):
            maximum = self._normalize_value(maximum)

        self.maximum = maximum
        self.minimum = minimum

    def __repr__(self):
        aspects = []
        if self.minimum is not None:
            aspects.append('minimum=%r' % self.minimum)
        if self.maximum is not None:
            aspects.append('maximum=%r' % self.maximum)
        return super(DateTime, self).__repr__(aspects)

    def _normalize_value(self, value):
        if value.tzinfo is not None:
            return value.astimezone(self.timezone)
        else:
            return value.replace(tzinfo=self.timezone)

    def _serialize_value(self, value):
        return value.astimezone(UTC).strftime(self.pattern)

    def _unserialize_value(self, value, ancestry):
        if isinstance(value, datetime):
            return value

        try:
            unserialized = datetime(*strptime(value, self.pattern)[:6])
            return unserialized.replace(tzinfo=UTC)
        except Exception:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

    def _validate_value(self, value, ancestry):
        if not isinstance(value, datetime):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

        value = self._normalize_value(value)

        minimum = self.minimum
        if minimum is not None:
            if callable(minimum):
                minimum = self._normalize_value(minimum())
            if value < minimum:
                raise ValidationError(identity=ancestry, field=self, value=value).construct(
                    'minimum', minimum=minimum.strftime(self.pattern))

        maximum = self.maximum
        if maximum is not None:
            if callable(maximum):
                maximum = self._normalize_value(maximum())
            if value > maximum:
                raise ValidationError(identity=ancestry, field=self, value=value).construct(
                    'maximum', maximum=maximum.strftime(self.pattern))

        return value

class Decimal(Field):
    """A resource field for decimal values."""

    equivalent = decimal
    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a decimal value'),
        Error('minimum', 'minimum value', '%(field)s must be greater then or equal to %(minimum)s'),
        Error('maximum', 'maximum value', '%(field)s must be less then or equal to %(maximum)s'),
    ]

    def __init__(self, minimum=None, maximum=None, **params):
        super(Decimal, self).__init__(**params)
        if minimum is None or isinstance(minimum, decimal):
            self.minimum = minimum
        else:
            raise TypeError(minimum)

        if maximum is None or isinstance(maximum, decimal):
            self.maximum = maximum
        else:
            raise TypeError(maximum)

    def __repr__(self):
        aspects = []
        if self.minimum is not None:
            aspects.append('minimum=%s' % self.minimum)
        if self.maximum is not None:
            aspects.append('maximum=%s' % self.maximum)
        return super(Decimal, self).__repr__(aspects)

    def _serialize_value(self, value):
        return str(value)

    def _unserialize_value(self, value, ancestry):
        if isinstance(value, decimal):
            return value

        try:
            return decimal(value)
        except Exception:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

    def _validate_value(self, value, ancestry):
        if not isinstance(value, decimal):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

        minimum = self.minimum
        if minimum is not None and value < minimum:
            raise ValidationError(identity=ancestry, field=self, value=value).construct(
                'minimum', minimum=minimum)

        maximum = self.maximum
        if maximum is not None and value > maximum:
            raise ValidationError(identity=ancestry, field=self, value=value).construct(
                'maximum', maximum=maximum)

class Definition(Field):
    """A field for field definitions."""

    equivalent = Field
    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a field definition'),
        Error('invalidfield', 'invalid field', '%(field)s must be one of %(fields)s'),
    ]

    def __init__(self, fields=None, **params):
        super(Definition, self).__init__(**params)
        if fields:
            fields = tuple(fields)
            for field in fields:
                if not (isinstance(field, type) and issubclass(field, Field)):
                    raise ValueError(fields)

        self.fields = fields
        if self.fields:
            self.representation = ', '.join(sorted(field.__name__ for field in self.fields))

    def _serialize_value(self, value):
        return value.describe()

    def _unserialize_value(self, value, ancestry):
        try:
            return Field.reconstruct(value)
        except Exception:
            raise ValidationError(identity=ancestry, field=self, value=value).construct('invalid')

    def _validate_value(self, value, ancestry):
        if not isinstance(value, Field):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        if self.fields and not isinstance(value, self.fields):
            raise ValidationError(identity=ancestry, field=self, value=value).construct(
                'invalidfield', fields=self.representation)

class Enumeration(Field):
    """A resource field for enumerated values.

    :param list enumeration: The list of valid values for this field, all of which must be
        natively serializable (i.e., a ``bool``, ``float``, ``integer`` or ``string``). Can
        also be specified as a single space-delimited string.
    """

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be one of %(values)s')
    ]
    parameters = ('enumeration',)

    def __init__(self, enumeration, **params):
        super(Enumeration, self).__init__(**params)
        if isinstance(enumeration, basestring):
            enumeration = enumeration.split(' ')
        if isinstance(enumeration, list):
            for value in enumeration:
                if not isinstance(value, NATIVELY_SERIALIZABLE):
                    raise SchemeError('Enumeration values must be natively serializable')
        else:
            raise SchemeError('enumeration must be a list of natively serializable values')

        self.enumeration = enumeration
        self.representation = ', '.join([repr(value) for value in enumeration])

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None or subject in self.enumeration:
            return subject

        value = interpolate_parameters(subject, parameters, interpolator, True)
        if value in self.enumeration:
            return value
        else:
            raise ValueError(subject)

    def __repr__(self):
        return super(Enumeration, self).__repr__(['enumeration=[%s]' % self.representation])

    def _validate_value(self, value, ancestry):
        if value not in self.enumeration:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid',
                values=self.representation)

class Float(Field):
    """A resource field for ``float`` values.

    :param float minimum: Optional, default is ``None``; the minimum valid value
        for this field.

    :param float maximum: Optional, default is ``None``; the maximum valid value
        for this field.
    """

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a floating-point number'),
        Error('minimum', 'minimum value', '%(field)s must be greater then or equal to %(minimum)f'),
        Error('maximum', 'maximum value', '%(field)s must be less then or equal to %(maximum)f'),
    ]
    parameters = ('maximum', 'minimum')

    def __init__(self, minimum=None, maximum=None, **params):
        super(Float, self).__init__(**params)
        if minimum is None or isinstance(minimum, float):
            self.minimum = minimum
        else:
            raise SchemeError('Float.minimum must be a float if specified')

        if maximum is None or isinstance(maximum, float):
            self.maximum = maximum
        else:
            raise SchemeError('Float.maximum must be a float if specified')

    def __repr__(self):
        aspects = []
        if self.minimum is not None:
            aspects.append('minimum=%r' % self.minimum)
        if self.maximum is not None:
            aspects.append('maximum=%r' % self.maximum)
        return super(Float, self).__repr__(aspects)

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return None
        elif isinstance(subject, (float, int, long)):
            return float(subject)
        else:
            return float(interpolate_parameters(subject, parameters, interpolator, True))

    def _unserialize_value(self, value, ancestry):
        if isinstance(value, float):
            return value

        try:
            return float(value)
        except Exception:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

    def _validate_value(self, value, ancestry):
        if not isinstance(value, float):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

        minimum = self.minimum
        if minimum is not None and value < minimum:
            raise ValidationError(identity=ancestry, field=self, value=value).construct(
                'minimum', minimum=minimum)

        maximum = self.maximum
        if maximum is not None and value > maximum:
            raise ValidationError(identity=ancestry, field=self, value=value).construct(
                'maximum', maximum=maximum)

class Integer(Field):
    """A resource field for ``integer`` values.

    :param integer minimum: Optional, default is ``None``; the minimum valid value
        for this field.

    :param integer maximum: Optional, default is ``None``; the maximum valid value
        for this field.
    """

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be an integer'),
        Error('minimum', 'minimum value', '%(field)s must be greater then or equal to %(minimum)d'),
        Error('maximum', 'maximum value', '%(field)s must be less then or equal to %(maximum)d'),
    ]
    parameters = ('maximum', 'minimum')

    def __init__(self, minimum=None, maximum=None, **params):
        super(Integer, self).__init__(**params)
        if minimum is None or isinstance(minimum, (int, long)):
            self.minimum = minimum
        else:
            raise SchemeError('Integer.minimum must be an integer if specified')

        if maximum is None or isinstance(maximum, (int, long)):
            self.maximum = maximum
        else:
            raise SchemeError('Integer.maximum must be an integer if specified')

    def __repr__(self):
        aspects = []
        if self.minimum is not None:
            aspects.append('minimum=%r' % self.minimum)
        if self.maximum is not None:
            aspects.append('maximum=%r' % self.maximum)
        return super(Integer, self).__repr__(aspects)

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return None
        elif isinstance(subject, (float, int, long)):
            return int(subject)
        else:
            return int(interpolate_parameters(subject, parameters, interpolator, True))

    def _unserialize_value(self, value, ancestry):
        if value is True or value is False:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        elif isinstance(value, int):
            return value

        try:
            return int(value)
        except Exception:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

    def _validate_value(self, value, ancestry):
        if value is True or value is False or not isinstance(value, (int, long)):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

        minimum = self.minimum
        if minimum is not None and value < minimum:
            raise ValidationError(identity=ancestry, field=self, value=value).construct('minimum',
                minimum=minimum)

        maximum = self.maximum
        if maximum is not None and value > maximum:
            raise ValidationError(identity=ancestry, field=self, value=value).construct('maximum',
                maximum=maximum)

class Map(Field):
    """A resource field for mappings of key/value pairs.

    :param Field value: A :class:`Field` which specifies the values this map can contain;
        can only be ``None`` when instantiating a subclass which specifies ``value`` at
        the class level.

    :param list required_keys: Optional, default is ``None``; a list of keys which are
        required to be present in this map. Can also be specified as a single space-delimited
        string.
    """

    key = None
    value = None
    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a map'),
        Error('invalidkeys', 'invalid keys', '%(field)s must have valid keys'),
        Error('required', 'required key', "%(field)s is missing required key '%(name)s'"),
    ]
    parameters = ('required_keys',)
    structural = True

    def __init__(self, value=None, key=None, required_keys=None, **params):
        super(Map, self).__init__(**params)
        if value is not None:
            self.value = value
        if isinstance(self.value, Undefined):
            if self.value.field:
                self.value = self.value.field
            else:
                self.value.register(self._define_undefined_field)
        elif not isinstance(self.value, Field):
            raise SchemeError('Map(value) must be a Field instance')

        if key is not None:
            self.key = key
        if self.key and not isinstance(self.key, Field):
            raise SchemeError('Map(key) must be a Field instance')

        self.required_keys = required_keys
        if isinstance(self.required_keys, basestring):
            self.required_keys = self.required_keys.split(' ')
        if self.required_keys is not None and not isinstance(self.required_keys, (list, tuple)):
            raise SchemeError('Map(required_keys) must be a list of strings')

    def describe(self, parameters=None):
        if not isinstance(self.value, Field):
            return SchemeError()

        default = None
        if self.default:
            default = {}
            for key, value in self.default.iteritems():
                default[key] = self.value.process(value, OUTGOING, True)

        params = {'value': self.value.describe(parameters), 'default': default}
        if self.key:
            params['key'] = self.key.describe(parameters)
        return super(Map, self).describe(parameters, **params)

    def extract(self, subject, **params):
        if params and not self.screen(**params):
            raise FieldExcludedError(self)

        definition = self.value
        if subject is None:
            return subject
        if self.extractor:
            subject = self.extractor(self, subject)
        if not isinstance(subject, dict):
            raise ValueError(subject)

        extraction = {}
        for key, value in subject.iteritems():
            try:
                extraction[key] = definition.extract(value, **params)
            except FieldExcludedError:
                pass
        return extraction

    def instantiate(self, value, key=None):
        if value is None:
            return None

        instantiate = self.value.instantiate
        value = dict((k, instantiate(v, k)) for k, v in value.iteritems())
        return super(Map, self).instantiate(value, key)

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return subject
        if isinstance(subject, basestring):
            subject = interpolate_parameters(subject, parameters, interpolator, True)
        if not isinstance(subject, dict):
            raise ValueError(subject)

        definition = self.value
        interpolation = {}

        for key, value in subject.iteritems():
            interpolation[key] = definition.interpolate(value, parameters, interpolator)
        return interpolation
        
    def process(self, value, phase=INCOMING, serialized=False, ancestry=None):
        if not ancestry:
            ancestry = [self.guaranteed_name]

        if self._is_null(value, ancestry):
            return None
        if not isinstance(value, dict):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        if self.preprocessor:
            value = self.preprocessor(value)

        valid = True
        key_field = self.key
        value_field = self.value

        map = {}
        for name, subvalue in value.iteritems():
            if key_field:
                try:
                    name = key_field.process(name, phase, serialized, ancestry + ['[%s]' % name])
                except StructuralError, exception:
                    raise ValidationError(identity=ancestry, field=self, value=value).construct('invalidkeys')
            elif not isinstance(name, basestring):
                raise ValidationError(identity=ancestry, field=self, value=value).construct('invalidkeys')

            try:
                map[name] = value_field.process(subvalue, phase, serialized, ancestry + ['[%s]' % name])
            except StructuralError, exception:
                valid = False
                map[name] = exception

        if self.required_keys:
            for name in self.required_keys:
                if name not in map:
                    valid = False
                    map[name] = ValidationError(identity=ancestry, field=self).construct(
                        'required', name=name)

        if not valid:
            raise ValidationError(identity=ancestry, field=self, value=value, structure=map)

        return map

    def _define_undefined_field(self, field):
        self.value = field

    @classmethod
    def _visit_field(cls, specification, callback):
        params = {'value': callback(specification['value'])}
        if 'key' in specification:
            params['key'] = callback(specification['key'])
        return params

class Object(Field):
    """A resource field for references to python objects."""

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a python object'),
        Error('import', 'object import', 'cannot import %(value)r'),
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
                error = ValidationError(identity=ancestry, field=self, value=value)
                raise error.construct('import', value=value).capture()
        else:
            return value

class Sequence(Field):
    """A resource field for sequences of items.

    :param item: A :class:`Field` which specifies the items this sequence can contain;
        can only be ``None`` when instantiating a subclass which specifies ``item`` at
        the class level.

    :param integer min_length: Optional, defaults to ``None``; the minimum length
        of this sequence.

    :param integer max_length: Optional, defaults to ``None``; the maximum length
        of this sequence.

    :param boolean unique: Optional, defaults to ``False``; if ``True``, indicates
        the sequence cannot contain duplicate values.
    """

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a sequence'),
        Error('min_length', 'minimum length', '%(field)s must have at least %(min_length)d %(noun)s'),
        Error('max_length', 'maximum length', '%(field)s must have at most %(max_length)d %(noun)s'),
        Error('duplicate', 'duplicate value', '%(field)s must not have duplicate values'),
    ]
    item = None
    parameters = ('min_length', 'max_length', 'unique')
    structural = True

    def __init__(self, item=None, min_length=None, max_length=None, unique=False, **params):
        super(Sequence, self).__init__(**params)
        self.unique = unique

        if item is not None:
            self.item = item
        if isinstance(self.item, Undefined):
            if self.item.field:
                self.item = self.item.field
            else:
                self.item.register(self._define_undefined_field)
        elif not isinstance(self.item, Field):
            raise SchemeError('Sequence.item must be a Field instance')

        if min_length is None or (isinstance(min_length, int) and min_length >= 0):
            self.min_length = min_length
        else:
            raise SchemeError('Sequence.min_length must be an integer if specified')

        if max_length is None or (isinstance(max_length, int) and max_length >= 0):
            self.max_length = max_length
        else:
            raise SchemeError('Sequence.max_length must be an integer if specified')

    def describe(self, parameters=None):
        if not isinstance(self.item, Field):
            raise SchemeError()

        default = None
        if self.default:
            default = [self.item.process(value, OUTGOING, True) for value in self.default]

        return super(Sequence, self).describe(parameters, item=self.item.describe(parameters),
            default=default)

    def extract(self, subject, **params):
        if params and not self.screen(**params):
            raise FieldExcludedError(self)

        definition = self.item
        if subject is None:
            return subject
        if self.extractor:
            subject = self.extractor(self, subject)
        if not isinstance(subject, (list, tuple)):
            raise ValueError(subject)

        extraction = []
        for item in subject:
            try:
                extraction.append(definition.extract(item, **params))
            except FieldExcludedError:
                pass
        return extraction

    def filter(self, exclusive=False, **params):
        if not super(Sequence, self).filter(exclusive, **params):
            return None
        if self.item and self.item.structural:
            return self.clone(item=self.item.filter(exclusive, **params))
        else:
            return self

    def instantiate(self, value, key=None):
        if value is None:
            return None

        instantiate = self.item.instantiate
        value = [instantiate(v) for v in value]
        return super(Sequence, self).instantiate(value, key)

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return None
        if isinstance(subject, basestring):
            subject = interpolate_parameters(subject, parameters, interpolator, True)
        if not isinstance(subject, (list, tuple)):
            raise ValueError(subject)

        definition = self.item
        interpolation = []

        for item in subject:
            interpolation.append(definition.interpolate(item, parameters, interpolator))
        return interpolation

    def process(self, value, phase=INCOMING, serialized=False, ancestry=None):
        if not ancestry:
            ancestry = [self.guaranteed_name]

        if self._is_null(value, ancestry):
            return None
        if not isinstance(value, list):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        if self.preprocessor:
            value = self.preprocessor(value)

        min_length = self.min_length
        if min_length is not None and len(value) < min_length:
            raise ValidationError(identity=ancestry, field=self, value=value).construct('min_length',
                min_length=min_length, noun=pluralize('item', min_length))

        max_length = self.max_length
        if max_length is not None and len(value) > max_length:
            raise ValidationError(identity=ancestry, field=self, value=value).construct('max_length',
                max_length=max_length, noun=pluralize('item', max_length))

        valid = True
        item = self.item

        sequence = []
        for i, subvalue in enumerate(value):
            try:
                sequence.append(item.process(subvalue, phase, serialized, ancestry + ['[%s]' % i]))
            except StructuralError, exception:
                valid = False
                sequence.append(exception)

        if not valid:
            raise ValidationError(identity=ancestry, field=self, value=value, structure=sequence)
        elif self.unique and len(set(sequence)) != len(sequence):
            raise ValidationError(identity=ancestry, field=self, value=value).construct('duplicate')
        else:
            return sequence

    def _define_undefined_field(self, field):
        self.item = field

    @classmethod
    def _visit_field(cls, specification, callback):
        return {'item': callback(specification['item'])}

class Structure(Field):
    """A resource field for structures of key/value pairs.

    A structure has an explicit set of key strings, each related to a :class:`Field`
    specifying the potential value for that key. During validation, a :exc:`ValidationError`
    will be raised if unknown keys are present in the value being processed.

    :param dict structure: A ``dict`` containing ``string`` keys and :class:`Field` values;
        can be ``None`` only when instantiating a subclass of ``Structure`` which specifies
        ``structure`` at the class level.

    :param boolean strict: Optional, defaults to ``True``; if ``False``, key/value pairs
        which aren't present in ``structure`` will be silently ignored during validation
        instead of causing a :exc:`ValidationError` to be raised.

    :param Field polymorphic_on: Optional, defaults to ``None``; if specified, should be
        a :class:`Field` instance which establishes the discriminator field for this
        structure, which is thusly considered polymorphic.

    :param boolean generate_default: Optional, defaults to ``False``; if ``True``, a
        default value for this field is dynamically constructed by collecting the default
        values, if any, of the fields specified within ``structure`` into a ``dict``.
    """

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a structure'),
        Error('required', 'required field', "%(field)s is missing required field '%(name)s'"),
        Error('unknown', 'unknown field', "%(field)s includes an unknown field '%(name)s'"),
        Error('unrecognized', 'unrecognized polymorphic identity',
            "%(field)s must specify a recognized polymorphic identity"),
    ]
    parameters = ('strict',)
    structure = None
    structural = True

    def __init__(self, structure=None, strict=True, polymorphic_on=None, generate_default=False, 
            key_order=None, **params):
        
        if polymorphic_on:
            if isinstance(polymorphic_on, basestring):
                polymorphic_on = Enumeration((structure or self.structure).keys(),
                    name=polymorphic_on, nonempty=True)
            if not isinstance(polymorphic_on, Field):
                raise SchemeError()
            if not polymorphic_on.required:
                polymorphic_on = polymorphic_on.clone(required=True)

        if isinstance(key_order, basestring):
            key_order = key_order.split(' ')

        super(Structure, self).__init__(**params)
        self.key_order = key_order
        self.polymorphic_on = polymorphic_on
        self.strict = strict

        if structure is not None:
            self.structure = structure
        if not isinstance(self.structure, dict):
            raise SchemeError()

        if polymorphic_on:
            for identity, candidate in self.structure.iteritems():
                self._prevalidate_structure(candidate, identity)
                if polymorphic_on in candidate:
                    raise SchemeError()
                else:
                    candidate[polymorphic_on.name] = polymorphic_on.clone(constant=identity)
        else:
            self._prevalidate_structure(self.structure)

        if generate_default and not self.default:
            self.default = self.generate_default()

    @property
    def has_required_fields(self):
        if self.polymorphic_on:
            return True

        for field in self.structure.itervalues():
            if field.required and field.default is None:
                return True
        else:
            return False

    @property
    def polymorphic(self):
        return (self.polymorphic_on is not None)

    def describe(self, parameters=None):
        polymorphic_on = self.polymorphic_on
        if polymorphic_on:
            default = None
            if self.default:
                identity = self.default.get(polymorphic_on.name)
                if identity is not None:
                    definition = self.structure.get(identity)
                    if definition:
                        default = self._describe_default(definition, self.default)
                    else:
                        raise Exception()
                else:
                    raise Exception()

            structure = {}
            for identity, candidate in self.structure.iteritems():
                identity = polymorphic_on._serialize_value(identity)
                structure[identity] = self._describe_structure(candidate, parameters)

            return super(Structure, self).describe(parameters,
                default=default,
                polymorphic_on=polymorphic_on.describe(parameters),
                structure=structure)
        else:
            default = None
            if self.default:
                default = self._describe_default(self.structure, self.default)

            return super(Structure, self).describe(parameters,
                default=default,
                polymorphic_on=None,
                structure = self._describe_structure(self.structure, parameters))

    def extract(self, subject, **params):
        if params and not self.screen(**params):
            raise FieldExcludedError(self)

        if subject is None:
            return subject
        if self.extractor:
            subject = self.extractor(self, subject)
        if not isinstance(subject, dict):
            raise ValueError(subject)

        definition = self._get_definition(subject)
        extraction = {}

        for name, field in definition.iteritems():
            try:
                value = subject[name]
                if value is None:
                    continue
            except KeyError:
                continue

            try:
                extraction[name] = field.extract(value, **params)
            except FieldExcludedError:
                pass

        return extraction

    def filter(self, exclusive=False, **params):
        if not super(Structure, self).filter(exclusive, **params):
            return None

        if self.polymorphic_on:
            structure = {}
            for identity, candidate in self.structure.iteritems():
                structure[identity] = self._filter_structure(candidate, exclusive, params)
        else:
            structure = self._filter_structure(self.structure, exclusive, params)
        
        return self.clone(structure=structure)

    def generate_default(self, sparse=True):
        if self.polymorphic:
            default = {}
            for identity, structure in self.structure.iteritems():
                default[identity] = self._generate_default_values(structure, sparse)
            return default
        else:
            return self._generate_default_values(self.structure, sparse)

    def get(self, key, default=None):
        return self.structure.get(key, default)

    def insert(self, field, overwrite=False):
        if not isinstance(field, Field):
            raise TypeError(field)
        if not field.name:
            raise ValueError(field)
        if field.name in self.structure and not overwrite:
            return
        self.structure[field.name] = field

    def instantiate(self, value, key=None):
        if value is None:
            return None

        definition = self._get_definition(value)
        value = dict((k, definition[k].instantiate(v)) for k, v in value.iteritems())
        return super(Structure, self).instantiate(value, key)

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return subject
        if isinstance(subject, basestring):
            subject = interpolate_parameters(subject, parameters, interpolator, True)
        if not isinstance(subject, dict):
            raise ValueError(subject)

        definition = self._get_definition(subject)
        interpolation = {}

        for name, field in definition.iteritems():
            try:
                value = subject[name]
            except KeyError:
                continue
            else:
                try:
                    interpolation[name] = field.interpolate(value, parameters, interpolator)
                except UndefinedValueError:
                    continue
        return interpolation

    def merge(self, structure, prefer=False):
        for name, field in structure.iteritems():
            if not isinstance(field, Field):
                raise Exception()
            if name in self.structure and not prefer:
                return
            if field.name != name:
                field = field.clone(name=name)
            self.structure[name] = field

    def process(self, value, phase=INCOMING, serialized=False, ancestry=None, partial=False):
        if not ancestry:
            ancestry = [self.guaranteed_name]

        if self._is_null(value, ancestry):
            return None
        if not isinstance(value, dict):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        if self.preprocessor:
            value = self.preprocessor(value)

        valid = True
        names = set(value.keys())

        identity = None
        polymorphic_on = self.polymorphic_on

        if polymorphic_on:
            identity = value.get(polymorphic_on.name)
            if identity is not None:
                identity = polymorphic_on.process(identity, phase, serialized,
                    ancestry + ['.' + polymorphic_on.name])
            else:
                raise ValidationError(identity=ancestry, field=self).construct('required',
                    name=polymorphic_on.name)

            definition = self.structure.get(identity)
            if not definition:
                raise ValidationError(identity=ancestry, field=self, value=identity).construct('unrecognized')
        else:
            definition = self.structure

        structure = None
        if self.key_order:
            structure = OrderedDict()
            if identity:
                key_order = self.key_order[identity]
            else:
                key_order = self.key_order

        if structure is None:
            structure = {}
            key_order = definition.iterkeys()

        for name in key_order:
            field = definition[name]
            if name in names:
                names.remove(name)
                field_value = value[name]
            elif partial:
                continue
            elif phase == INCOMING and field.default is not None:
                field_value = field.get_default()
            elif field.required:
                valid = False
                structure[name] = ValidationError(identity=ancestry, field=self).construct(
                    'required', name=name)
                continue
            else:
                continue

            if field.ignore_null and field_value is None:
                continue

            try:
                structure[name] = field.process(field_value, phase, serialized,
                    ancestry + ['.' + name])
            except StructuralError, exception:
                valid = False
                structure[name] = exception

        if self.strict:
            for name in names:
                valid = False
                structure[name] = ValidationError(identity=ancestry, field=self).construct(
                    'unknown', name=name)

        if valid:
            return structure
        else:
            raise ValidationError(identity=ancestry, field=self, value=value, structure=structure)

    def _define_undefined_field(self, field, name):
        identity, name = name
        if self.polymorphic_on:
            self.structure[identity][name] = field.clone(name=name)
        else:
            self.structure[name] = field.clone(name=name)

    def _describe_default(self, structure, default):
        description = {}
        for name, value in default.iteritems():
            description[name] = structure[name]._serialize_value(value)
        return description

    def _describe_structure(self, structure, parameters):
        description = {}
        for name, field in structure.iteritems():
            if isinstance(field, Field):
                description[name] = field.describe(parameters)
            else:
                raise SchemeError()
        return description

    def _filter_structure(self, structure, exclusive, params):
        filtered = {}
        for name, field in structure.iteritems():
            field = field.filter(exclusive, **params)
            if field:
                filtered[name] = field
        return filtered

    def _generate_default_values(self, structure, sparse=False):
        default = {}
        for name, field in structure.iteritems():
            if not sparse or field.default is not None:
                default[name] = field.default
        return default

    def _get_definition(self, value):
        identity = self._get_polymorphic_identity(value)
        if identity:
            return self.structure[identity]
        else:
            return self.structure

    def _get_key_order(self, value):
        key_order = self.key_order
        if not key_order:
            return None

        identity = self._get_polymorphic_identity(value)
        if identity:
            return key_order[identity]
        else:
            return key_order

    def _get_polymorphic_identity(self, value):
        polymorphic_on = self.polymorphic_on
        if polymorphic_on:
            identity = value.get(polymorphic_on.name)
            if identity is not None:
                return identity
            else:
                raise ValueError(value)

    def _prevalidate_structure(self, structure, identity=None):
        if not isinstance(structure, dict):
            raise SchemeError('structure must be a dict')

        for name, field in structure.items():
            if isinstance(field, Undefined):
                if field.field:
                    field = field.field
                    structure[name] = field
                else:
                    field.register(self._define_undefined_field, (identity, name))
                    continue

            if not isinstance(field, Field):
                raise SchemeError('structure values must be Field instances')
            if not field.name:
                field.name = name

    @classmethod
    def _visit_field(cls, specification, callback):
        def visit(structure):
            return dict((name, callback(field)) for name, field in structure.iteritems())

        if specification.get('polymorphic_on'):
            return {'structure': dict((identity, visit(candidate))
                for identity, candidate in specification['structure'].iteritems())}
        else:
            return {'structure': visit(specification['structure'])}

class Text(Field):
    """A resource field for text values.

    :param pattern: Optional, default is ``None``; a regular expression which values of this
        field must match, specified as either a compiled regular expression or a string.

    :param integer min_length: Optional, default is ``None``; the minimum length of valid
        values for this field.

    :param integer max_length: Optional, default is ``None``; the maximum length of valid
        values for this field.

    :param boolean strip: Optional, default is ``True``; if ``True``, values submitted to this
        field will have whitespace stripped before validation.

    :param boolean nonempty: Optional, default is ``False``; if ``True``, this field will
        be instantiated with ``required=True, nonnull=True, min_length=1``. This is merely
        a shortcut argument.
    """

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a textual value'),
        Error('pattern', 'invalid value', '%(field)s has an invalid value'),
        Error('min_length', 'minimum length', 
            '%(field)s must contain at least %(min_length)d non-whitespace %(noun)s'),
        Error('max_length', 'maximum length',
            '%(field)s may contain at most %(max_length)d %(noun)s'),
    ]
    parameters = ('max_length', 'min_length', 'strip')
    pattern = None

    def __init__(self, pattern=None, min_length=None, max_length=None, strip=True,
            nonempty=False, **params):

        self.strip = strip
        if nonempty:
            params.update(required=True, nonnull=True)
            if min_length is None:
                min_length = 1

        super(Text, self).__init__(**params)
        if pattern is not None:
            if isinstance(pattern, basestring):
                pattern = re.compile(pattern)
            self.pattern = pattern

        if min_length is None or (isinstance(min_length, int) and min_length >= 0):
            self.min_length = min_length
        else:
            raise SchemeError('TextField.min_length must be an integer >= 0, if specified')

        if max_length is None or (isinstance(max_length, int) and max_length >= 0):
            self.max_length = max_length
        else:
            raise SchemeError('TextField.max_length must be an integer >= 0, if specified')

    def __repr__(self):
        aspects = []
        if self.min_length is not None:
            aspects.append('min_length=%r' % self.min_length)
        if self.max_length is not None:
            aspects.append('max_length=%r' % self.max_length)
        if self.pattern is not None:
            aspects.append('pattern=%r' % self.pattern.pattern)
        return super(Text, self).__repr__(aspects)

    def describe(self, parameters=None):
        if self.pattern:
            pattern = self.pattern.pattern
        else:
            pattern = None
        return super(Text, self).describe(parameters, pattern=pattern)

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return subject
        else:
            return interpolate_parameters(subject, parameters, interpolator)

    def _validate_value(self, value, ancestry):
        if not isinstance(value, basestring):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        if self.strip:
            value = value.strip()

        min_length = self.min_length
        if min_length is not None and len(value) < min_length:
            noun = 'character'
            if min_length > 1:
                noun = 'characters'
            raise ValidationError(identity=ancestry, field=self, value=value).construct('min_length',
                min_length=min_length, noun=noun)

        max_length = self.max_length
        if max_length is not None and len(value) > max_length:
            noun = 'character'
            if max_length > 1:
                noun = 'characters'
            raise ValidationError(identity=ancestry, field=self, value=value).construct('max_length',
                max_length=max_length, noun=noun)

        if self.pattern and not self.pattern.match(value):
            raise ValidationError(identity=ancestry, field=self, value=value).construct('pattern')

        return value

class Time(Field):
    """A resource field for ``time`` values.

    :param minimum: Optional, default is ``None``; the earliest valid value for this field, as
        either a ``time`` or a callable which returns a ``time``.

    :param maximum: Optional, default is ``None``; the earliest valid value for this field, as
        either a ``time`` or a callable which returns a ``time``.
    """

    equivalent = time
    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a time value'),
        Error('minimum', 'minimum value', '%(field)s must not occur before %(minimum)s'),
        Error('maximum', 'maximum value', '%(field)s must not occur after %(maximum)s'),
    ]
    parameters = ('maximum', 'minimum')
    pattern = '%H:%M:%S'

    def __init__(self, minimum=None, maximum=None, **params):
        super(Time, self).__init__(**params)
        self.maximum = maximum
        self.minimum = minimum

    def __repr__(self):
        aspects = []
        if self.minimum is not None:
            aspects.append('minimum=%r' % self.minimum)
        if self.maximum is not None:
            aspects.append('maximum=%r' % self.maximum)
        return super(Time, self).__repr__(aspects)

    def _serialize_value(self, value):
        return value.strftime(self.pattern)

    def _unserialize_value(self, value, ancestry):
        if isinstance(value, time):
            return value

        try:
            return time(*strptime(value, self.pattern)[3:6])
        except Exception:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

    def _validate_value(self, value, ancestry):
        if not isinstance(value, time):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

        minimum = self.minimum
        if minimum is not None:
            if callable(minimum):
                minimum = minimum()
            if value < minimum:
                raise ValidationError(identity=ancestry, field=self, value=value).construct('minimum',
                    minimum=minimum.strftime(self.pattern))

        maximum = self.maximum
        if maximum is not None:
            if callable(maximum):
                maximum = maximum()
            if value > maximum:
                raise ValidationError(identity=ancestry, field=self, value=value).construct('maximum',
                    maximum=maximum.strftime(self.pattern))

class Token(Field):
    """A resource field for identifier tokens.

    A token is a string containing one or more colon-delimited segments, with each segment
    starting and ending with any of [a-zA-Z0-9_] and containing any of [a-zA-Z0-9_-+.].

    :param int segments: Optional, default is ``None``; if specified, indicates the exact
        number of segments that valid values for this field must have.
    """

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a valid token')
    ]
    pattern = re.compile(r'^\w[-+.\w]*(?<=\w)(?::\w[-+.\w]*(?<=\w))*$')

    def __init__(self, segments=None, **params):
        super(Token, self).__init__(**params)
        self.segments = segments

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return subject
        else:
            return interpolate_parameters(subject, parameters, interpolator)

    def _validate_value(self, value, ancestry):
        if not (isinstance(value, basestring) and self.pattern.match(value)):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        if self.segments is not None and value.count(':') + 1 != self.segments:
            raise ValidationError(identity=ancestry, field=self, value=value).construct('invalid')

class Tuple(Field):
    """A resource field for tuples of values.

    :param tuple values: A ``tuple`` of :class:`Field`s which specifies the values this
        tuple contains; can only be ``None`` when instantiating a subclass which specifies
        ``values`` at the class level.
    """

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a tuple'),
        Error('length', 'invalid length', '%(field)s must contain exactly %(length)d values'),
    ]
    structural = True
    values = None

    def __init__(self, values=None, **params):
        super(Tuple, self).__init__(**params)
        if values is not None:
            self.values = values
        if not isinstance(self.values, (list, tuple)):
            raise SchemeError('Tuple.values must be a list or tuple')
        
        stack = []
        for i, field in enumerate(self.values):
            if isinstance(field, Undefined):
                if field.field:
                    stack.append(field.field)
                else:
                    field.register(self._define_undefined_field, i)
                    stack.append(field)
            elif isinstance(field, Field):
                stack.append(field)
            else:
                raise SchemeError('tuple values must be Field instances')

        self.values = tuple(stack)

    def describe(self, parameters=None):
        values = []
        for value in self.values:
            if isinstance(value, Field):
                values.append(value.describe(parameters))
            else:
                raise SchemeError()

        default = None
        if self.default:
            default = []
            for field, value in zip(self.values, self.default):
                default.append(field.process(value, OUTGOING, True))
            default = tuple(default)

        return super(Tuple, self).describe(parameters, values=values, default=default)

    def extract(self, subject, **params):
        if params and not self.screen(**params):
            raise FieldExcludedError(self)

        if subject is None:
            return subject
        if self.extractor:
            subject = self.extractor(self, subject)
        if not isinstance(subject, (list, tuple)):
            raise ValueError(subject)

        extraction = []
        for i, definition in enumerate(self.values):
            try:
                extraction.append(definition.extract(subject[i], **params))
            except FieldExcludedError:
                pass
        return tuple(extraction)

    def instantiate(self, value, key=None):
        if value is None:
            return None

        sequence = []
        for i, field in enumerate(self.values):
            sequence.append(field.instantiate(value[i]))

        return super(Tuple, self).instantiate(tuple(sequence), key)

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return subject
        if isinstance(subject, basestring):
            subject = interpolate_parameters(subject, parameters, interpolator, True)
        if not isinstance(subject, (list, tuple)):
            raise ValueError(subject)

        interpolation = []
        for i, definition in enumerate(self.values):
            interpolation.append(definition.interpolate(subject[i], parameters, interpolator))
        return tuple(interpolation)

    def process(self, value, phase=INCOMING, serialized=False, ancestry=None):
        if not ancestry:
            ancestry = [self.guaranteed_name]

        if self._is_null(value, ancestry):
            return None
        if not isinstance(value, (list, tuple)):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')
        if self.preprocessor:
            value = self.preprocessor(value)

        values = self.values
        if len(value) != len(values):
            raise ValidationError(identity=ancestry, field=self, value=value).construct(
                'length', length=len(values))

        valid = True
        sequence = []

        for i, field in enumerate(values):
            try:
                sequence.append(field.process(value[i], phase, serialized, ancestry + ['[%s]' % i]))
            except StructuralError, exception:
                valid = False
                sequence.append(exception)

        if valid:
            return tuple(sequence)
        else:
            raise ValidationError(identity=ancestry, field=self, value=value, structure=sequence)

    def _define_undefined_field(self, field, idx):
        self.values = tuple(list(self.values[:idx]) + [field] + list(self.values[idx + 1:]))

    @classmethod
    def _visit_field(cls, specification, callback):
        return {'values': tuple([callback(field) for field in specification['values']])}

class Union(Field):
    """A resource field that supports multiple field values.

    :param tuple fields: A ``tuple`` of :class:`Field`s which specify, in order of preference,
        potential values for this field; can only be ``None`` when instantiating a subclass
        which specifies ``fields`` at the class level.
    """

    fields = None
    structural = True

    def __init__(self, *fields, **params):
        super(Union, self).__init__(**params)
        if fields:
            self.fields = tuple(fields)
        if not isinstance(self.fields, tuple) or not self.fields:
            raise SchemeError('Union.fields must be a tuple with at least one item')

        stack = []
        for i, field in enumerate(self.fields):
            if isinstance(field, Undefined):
                if field.field:
                    stack.append(field.field)
                else:
                    field.register(self._define_undefined_field, i)
                    stack.append(field)
            elif isinstance(field, Field):
                stack.append(field)
            else:
                raise SchemeError('Union.fields items must be Field instances')

        self.fields = tuple(stack)

    def describe(self, parameters=None):
        fields = []
        for field in self.fields:
            if isinstance(field, Field):
                fields.append(field.describe(parameters))
            else:
                raise SchemeError()
        return super(Union, self).describe(parameters, fields=fields)

    def instantiate(self, value):
        raise NotImplementedError()

    def interpolate(self, subject, parameters, interpolator=None):
        raise NotImplementedError()

    def process(self, value, phase=INCOMING, serialized=False, ancestry=None):
        if not ancestry:
            ancestry = [self.guaranteed_name]
        if self._is_null(value, ancestry):
            return None

        for field in self.fields:
            try:
                return field.process(value, phase, serialized, ancestry)
            except InvalidTypeError:
                pass
        else:
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

    def _define_undefined_field(self, field, idx):
        self.fields = tuple(list(self.fields[:idx]) + [field] + list(self.fields[idx + 1:]))

    @classmethod
    def _visit_field(cls, specification, callback):
        return {'fields': tuple([callback(field) for field in specification['fields']])}

class UUID(Field):
    """A resource field for UUIDs."""

    errors = [
        Error('invalid', 'invalid value', '%(field)s must be a UUID')
    ]
    pattern = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')

    def __init__(self, **params):
        super(UUID, self).__init__(**params)

    def interpolate(self, subject, parameters, interpolator=None):
        if subject is None:
            return subject
        else:
            return interpolate_parameters(subject, parameters, interpolator, True)

    def _validate_value(self, value, ancestry):
        if not (isinstance(value, basestring) and self.pattern.match(value)):
            raise InvalidTypeError(identity=ancestry, field=self, value=value).construct('invalid')

class Undefined(object):
    """A field which can be defined at a later time."""

    def __init__(self, field=None):
        self.callbacks = []
        self.field = field

    def define(self, field):
        self.field = field
        for callback, args in self.callbacks:
            callback(field, *args)

    def register(self, callback, *args):
        self.callbacks.append((callback, args))

Errors = Tuple((
    Sequence(
        Map(Text(nonnull=True), description='A mapping describing an error with this request.'),
        description='A sequence of global errors for this request.'),
    Field(description='A structure containing structural errors for this request.')),
    description='A two-tuple containing the errors for this request.'
)

__all__ = ['INCOMING', 'OUTGOING', 'Field', 'Errors', 'Error',
    'Undefined'] + construct_all_list(locals(), Field)
