import os
import re
from copy import deepcopy
from datetime import datetime, date, time
from time import mktime, strptime

from scheme.exceptions import *
from scheme.formats import Format
from scheme.timezone import LOCAL, UTC
from scheme.util import construct_all_list, format_structure, minimize_string, pluralize

NATIVELY_SERIALIZABLE = (basestring, bool, float, int, long, type(None), dict, list, tuple)
PATTERN_TYPE = type(re.compile(''))

INCOMING = 'incoming'
OUTGOING = 'outgoing'

class FieldMeta(type):
    def __new__(metatype, name, bases, namespace):
        declared_errors = namespace.pop('errors', {})
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

        errors.update(declared_errors)
        field.errors = errors

        parameters.update(declared_parameters)
        field.parameters = parameters

        field.types[field.type] = field
        return field

    def reconstruct(field, specification):
        """Reconstructs the field described by ``specification``."""

        if isinstance(specification, Field):
            return specification
        if specification is not None:
            return field.types[specification['__type__']].construct(specification)

class Field(object):
    """A resource field.

    :param string name: The name of this field.

    :param string description: Optional, a concise description of this field,
        used prominently in documentation.

    :param default: Optional, default is ``None``; if specified, indicates
        the default value for this field when no value is present in a
        request to the associated resource. Only applicable when this field
        is part of a ``Structure``.

    :param boolean nonnull: Optional, default is ``False``; if ``True``, indicates
        this field must have a value other than ``None`` when present in a
        request to the associated resource.

    :param boolean required: Optional, default is ``False``; if ``True``, indicates
        this field is required to be present in a request to the associated
        resource. Only applicable when this field is part of a ``Structure``.

    :param dict errors: Optional, default is ``None``; specifies custom error
        strings for this field.

    :param string notes: Optional, notes of any length concerning the use of
        this field, used primarily for documentation.
    """

    __metaclass__ = FieldMeta
    types = {}

    errors = {
        'invalid': '%(field)s has an invalid value',
        'nonnull': '%(field)s must be a non-null value',
    }
    parameters = ('name', 'constant', 'description', 'default', 'nonnull',
        'required', 'notes', 'structural')
    structural = False

    def __init__(self, name=None, description=None, default=None, nonnull=False, required=False,
        constant=None, errors=None, notes=None, **params):

        self.constant = constant
        self.default = default
        self.description = description
        self.name = name
        self.notes = notes
        self.nonnull = nonnull
        self.required = required

        if errors:
            self.errors = self.errors.copy()
            self.errors.update(errors)
        for attr, value in params.iteritems():
            if attr[0] != '_':
                setattr(self, attr, value)

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
        if structure:
            aspects.append(structure)
        return '%s(%s)' % (type(self).__name__, ', '.join(aspects))

    def __deepcopy__(self, memo):
        return self.clone()

    def __getattr__(self, name):
        try:
            return super(Field, self).__getattr__(name)
        except AttributeError:
            return None

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

        return cls(**specification)

    def describe(self, parameters=None, **params):
        """Constructs a serializable description of this field as a dictionary, which will
        contain enough information to reconstruct this field in another context. Any keyword
        parameters are mixed into the description."""

        description = {'__type__': self.type}
        for source in (self.parameters, parameters):
            if source:
                for parameter in source:
                    if parameter not in params:
                        value = getattr(self, parameter, None)
                        if value is not None and isinstance(value, NATIVELY_SERIALIZABLE):
                            description[parameter] = value
        
        for name, value in params.iteritems():
            if value is not None:
                description[name] = value

        return description

    def extract(self, subject):
        raise NotImplementedError()

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

    def get_error(self, error):
        return self.errors.get(error)

    def process(self, value, phase=INCOMING, serialized=False):
        """Processes ``value`` for this field.

        :param value: The value to process.

        :param string phase: The phase for this particular processing; either ``incoming``,
            to indicate the value is coming into the framework, or ``outgoing``, to indicate
            the value is leaving the framework.

        :param boolean serialized: Optional, defaults to ``False``; if ``True``, indicates
            ``value`` should either be unserialized before validation, if ``phase`` is
            ``incoming``, or serialized after validation, if ``phase`` is ``outgoing``.
        """
    
        if self._is_null(value):
            return None
        if serialized and phase == INCOMING:
            value = self._unserialize_value(value)
        if self.constant is not None and value != self.constant:
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        candidate = self._validate_value(value)
        if candidate is not None:
            value = candidate

        if serialized and phase == OUTGOING:
            value = self._serialize_value(value)
        return value

    def read(self, path, **params):
        data = Format.read(path, **params)
        return self.process(data, INCOMING, True)

    def serialize(self, value, format=None, **params):
        value = self.process(value, OUTGOING, True)
        if format:
            value = Format.formats[format].serialize(value, **params)
        return value

    def unserialize(self, value, format=None, **params):
        if format:
            value = Format.formats[format].unserialize(value, **params)
        return self.process(value, INCOMING, True)

    @classmethod
    def visit(cls, specification, callback):
        return cls.types[specification['__type__']]._visit_field(specification, callback)

    def write(self, path, value, format=None, **params):
        value = self.process(value, OUTGOING, True)
        Format.write(path, value, format, **params)

    def _is_null(self, value):
        if value is None:
            if self.nonnull:
                raise ValidationError().construct(self, 'nonnull')
            else:
                return True

    def _serialize_value(self, value):
        """Serializes and returns ``value``, if necessary."""

        return value

    def _unserialize_value(self, value):
        return value

    def _validate_value(self, value):
        """Validates ``value`` according to the parameters of this field."""

        return value

    @classmethod
    def _visit_field(cls, specification, callback):
        return {}

class Boolean(Field):
    """A resource field for ``boolean`` values."""

    errors = {'invalid': '%(field)s must be a boolean value'}

    def _validate_value(self, value):
        if not isinstance(value, bool):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

class Date(Field):
    """A resource field for ``date`` values.

    :param minimum: Optional, default is ``None``; the earliest valid value for this field, as
        either a ``date`` or a callable which returns a ``date``.
    :param maximum: Optional, default is ``None``; the latest valid value for this field, as
        either a ``date`` or a callable which returns a ``date``.
    """

    parameters = ('maximum', 'minimum')
    pattern = '%Y-%m-%d'

    errors = {
        'invalid': '%(field)s must be a date value',
        'minimum': '%(field)s must not occur before %(minimum)s',
        'maximum': '%(field)s must not occur after %(maximum)s',
    }

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

    def _unserialize_value(self, value):
        if isinstance(value, date):
            return value

        try:
            return date(*strptime(value, self.pattern)[:3])
        except Exception:
            raise InvalidTypeError(value=value).construct(self, 'invalid')

    def _validate_value(self, value):
        if not isinstance(value, date):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        minimum = self.minimum
        if minimum is not None:
            if callable(minimum):
                minimum = minimum()
            if value < minimum:
                raise ValidationError(value=value).construct(self, 'minimum',
                    minimum=minimum.strftime(self.pattern))

        maximum = self.maximum
        if maximum is not None:
            if callable(maximum):
                maximum = maximum()
            if value > maximum:
                raise ValidationError(value=value).construct(self, 'maximum',
                    maximum=maximum.strftime(self.pattern))

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

    :param tzinfo timezone: Optional, default is the local timezone; the timezone to apply
        to naive values processed by this field.

    Values are serialized according to ISO-8601, in UTC time. A naive ``datetime`` (one with
    no ``tzinfo``) will be assumed to be in the default timezone for the field, and will be
    converted to UTC after having that timezone applied to it. On unserialization, values will
    be converted back to the default timezone (typically local).
    """

    parameters = ('maximum', 'minimum')
    pattern = '%Y-%m-%dT%H:%M:%SZ'

    errors = {
        'invalid': '%(field)s must be a datetime value',
        'minimum': '%(field)s must not occur before %(minimum)s',
        'maximum': '%(field)s must not occur after %(maximum)s',
    }

    def __init__(self, minimum=None, maximum=None, timezone=LOCAL, **params):
        super(DateTime, self).__init__(**params)
        self.timezone = timezone

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

    def _unserialize_value(self, value):
        if isinstance(value, datetime):
            return value

        try:
            unserialized = datetime(*strptime(value, self.pattern)[:6])
            return unserialized.replace(tzinfo=UTC)
        except Exception:
            raise InvalidTypeError(value=value).construct(self, 'invalid')

    def _validate_value(self, value):
        if not isinstance(value, datetime):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        value = self._normalize_value(value)

        minimum = self.minimum
        if minimum is not None:
            if callable(minimum):
                minimum = self._normalize_value(minimum())
            if value < minimum:
                raise ValidationError(value=value).construct(self, 'minimum',
                    minimum=minimum.strftime(self.pattern))

        maximum = self.maximum
        if maximum is not None:
            if callable(maximum):
                maximum = self._normalize_value(maximum())
            if value > maximum:
                raise ValidationError(value=value).construct(self, 'maximum',
                    maximum=maximum.strftime(self.pattern))

        return value

class Enumeration(Field):
    """A resource field for enumerated values.

    :param list enumeration: The list of valid values for this field, all of which must be
        natively serializable (i.e., a ``bool``, ``float``, ``integer`` or ``string``). Can
        also be specified as a single space-delimited string.
    """

    errors = {'invalid': '%(field)s must be one of %(values)s'}
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

    def __repr__(self):
        return super(Enumeration, self).__repr__(['enumeration=[%s]' % self.representation])

    def _validate_value(self, value):
        if value not in self.enumeration:
            raise InvalidTypeError(value=value).construct(self, 'invalid', values=self.representation)

class Float(Field):
    """A resource field for ``float`` values.

    :param float minimum: Optional, default is ``None``; the minimum valid value
        for this field.

    :param float maximum: Optional, default is ``None``; the maximum valid value
        for this field.
    """

    errors = {
        'invalid': '%(field)s must be a floating-point number',
        'minimum': '%(field)s must be greater then or equal to %(minimum)f',
        'maximum': '%(field)s must be less then or equal to %(maximum)f',
    }
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

    def _unserialize_value(self, value):
        if isinstance(value, float):
            return value

        try:
            return float(value)
        except Exception:
            raise InvalidTypeError(value=value).construct(self, 'invalid')

    def _validate_value(self, value):
        if not isinstance(value, float):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        minimum = self.minimum
        if minimum is not None and value < minimum:
            raise ValidationError(value=value).construct(self, 'minimum', minimum=minimum)

        maximum = self.maximum
        if maximum is not None and value > maximum:
            raise ValidationError(value=value).construct(self, 'maximum', maximum=maximum)

class Integer(Field):
    """A resource field for ``integer`` values.

    :param integer minimum: Optional, default is ``None``; the minimum valid value
        for this field.

    :param integer maximum: Optional, default is ``None``; the maximum valid value
        for this field.
    """

    errors = {
        'invalid': '%(field)s must be an integer',
        'minimum': '%(field)s must be greater then or equal to %(minimum)d',
        'maximum': '%(field)s must be less then or equal to %(maximum)d',
    }
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

    def _unserialize_value(self, value):
        if value is True or value is False:
            raise InvalidTypeError(value=value).construct(self, 'invalid')
        elif isinstance(value, int):
            return value

        try:
            return int(value)
        except Exception:
            raise InvalidTypeError(value=value).construct(self, 'invalid')

    def _validate_value(self, value):
        if value is True or value is False or not isinstance(value, (int, long)):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        minimum = self.minimum
        if minimum is not None and value < minimum:
            raise ValidationError(value=value).construct(self, 'minimum', minimum=minimum)

        maximum = self.maximum
        if maximum is not None and value > maximum:
            raise ValidationError(value=value).construct(self, 'maximum', maximum=maximum)

class Map(Field):
    """A resource field for mappings of key/value pairs.

    :param Field value: A :class:`Field` which specifies the values this map can contain;
        can only be ``None`` when instantiating a subclass which specifies ``value`` at
        the class level.

    :param list required_keys: Optional, default is ``None``; a list of keys which are
        required to be present in this map. Can also be specified as a single space-delimited
        string.
    """

    value = None
    errors = {
        'invalid': '%(field)s must be a map',
        'required': "%(field)s is missing required key '%(name)s'",
    }
    parameters = ('required_keys',)
    structural = True

    def __init__(self, value=None, required_keys=None, **params):
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

        self.required_keys = required_keys
        if isinstance(self.required_keys, basestring):
            self.required_keys = self.required_keys.split(' ')
        if self.required_keys is not None and not isinstance(self.required_keys, (list, tuple)):
            raise SchemeError('Map(required_keys) must be a list of strings')

    @classmethod
    def construct(cls, specification):
        specification['value'] = Field.reconstruct(specification['value'])
        return super(Map, cls).construct(specification)

    def describe(self, parameters=None):
        if not isinstance(self.value, Field):
            return SchemeError()

        default = None
        if self.default:
            default = {}
            for key, value in self.default.iteritems():
                default[key] = self.value.process(value, OUTGOING, True)

        return super(Map, self).describe(parameters, value=self.value.describe(parameters),
            default=default)

    def extract(self, subject):
        definition = self.value
        if definition.structural:
            extraction = {}
            for key, value in subject.iteritems():
                if value is not None:
                    value = definition.extract(value)
                extraction[key] = value
            return extraction
        else:
            return subject.copy()
        
    def process(self, value, phase=INCOMING, serialized=False):
        if self._is_null(value):
            return None
        if not isinstance(value, dict):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        valid = True
        value_field = self.value

        map = {}
        for name, subvalue in value.iteritems():
            try:
                map[name] = value_field.process(subvalue, phase, serialized)
            except StructuralError, exception:
                valid = False
                map[name] = exception

        if self.required_keys:
            for name in self.required_keys:
                if name not in map:
                    valid = False
                    map[name] = ValidationError().construct(self, 'required', name=name)

        if valid:
            return map
        else:
            raise ValidationError(value=value, structure=map)

    def _define_undefined_field(self, field):
        self.value = field

    @classmethod
    def _visit_field(cls, specification, callback):
        return {'value': callback(specification['value'])}

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

    errors = {
        'invalid': '%(field)s must be a sequence',
        'min_length': '%(field)s must have at least %(min_length)d %(noun)s',
        'max_length': '%(field)s must have at most %(max_length)d %(noun)s',
        'unique': '%(field)s must not have duplicate values',
    }
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

    @classmethod
    def construct(cls, specification):
        specification['item'] = Field.reconstruct(specification['item'])
        return super(Sequence, cls).construct(specification)

    def describe(self, parameters=None):
        if not isinstance(self.item, Field):
            raise SchemeError()

        default = None
        if self.default:
            default = [self.item.process(value, OUTGOING, True) for value in self.default]

        return super(Sequence, self).describe(parameters, item=self.item.describe(parameters),
            default=default)

    def extract(self, subject):
        definition = self.item
        if definition.structural:
            extraction = []
            for item in subject:
                if item is not None:
                    item = definition.extract(item)
                extraction.append(item)
            return extraction
        else:
            return list(subject)

    def filter(self, exclusive=False, **params):
        if not super(Sequence, self).filter(exclusive, **params):
            return None
        if self.item and self.item.structural:
            return self.clone(item=self.item.filter(exclusive, **params))
        else:
            return self

    def process(self, value, phase=INCOMING, serialized=False):
        if self._is_null(value):
            return None
        if not isinstance(value, list):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        min_length = self.min_length
        if min_length is not None and len(value) < min_length:
            raise ValidationError(value=value).construct(self, 'min_length',
                min_length=min_length, noun=pluralize('item', min_length))

        max_length = self.max_length
        if max_length is not None and len(value) > max_length:
            raise ValidationError(value=value).construct(self, 'max_length',
                max_length=max_length, noun=pluralize('item', max_length))

        valid = True
        item = self.item

        sequence = []
        for subvalue in value:
            try:
                sequence.append(item.process(subvalue, phase, serialized))
            except StructuralError, exception:
                valid = False
                sequence.append(exception)

        if not valid:
            raise ValidationError(value=value, structure=sequence)
        elif self.unique and len(set(sequence)) != len(sequence):
            raise ValidationError(value=value).construct(self, 'unique')
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
        can only be ``None`` when instantiating a subclass which specifies ``structure``
        at the class level.

    :param boolean strict: Optional, defaults to ``True``; if ``False``, unknown key/value
        pairs will be silently ignored instead of causing a :exc:`ValidationError` to be
        raised.
    """

    errors = {
        'invalid': '%(field)s must be a structure',
        'required': "%(field)s is missing required field '%(name)s'",
        'unknown': "%(field)s includes an unknown field '%(name)s'",
        'unrecognized': "%(field)s must specify a recognized polymorphic identity",
    }
    parameters = ('strict',)
    structure = None
    structural = True

    def __init__(self, structure=None, strict=True, polymorphic_on=None, generate_default=False, **params):
        if polymorphic_on:
            if not isinstance(polymorphic_on, Field):
                raise SchemeError()
            if not polymorphic_on.required:
                polymorphic_on = polymorphic_on.clone(required=True)

        super(Structure, self).__init__(**params)
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

    @classmethod
    def construct(cls, specification):
        structure = specification['structure']
        if specification.get('polymorphic_on', False):
            specification['polymorphic_on'] = Field.reconstruct(specification['polymorphic_on'])
            for candidate in structure.itervalues():
                for name, field in candidate.items():
                    candidate[name] = Field.reconstruct(field)
        else:
            for name, field in structure.items():
                structure[name] = Field.reconstruct(field)
        return super(Structure, cls).construct(specification)

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

    def extract(self, subject):
        extraction = {}
        for name, field in self.structure.iteritems():
            try:
                value = subject[name]
            except KeyError:
                continue
            if value is not None and field.structural:
                value = field.extract(value)
            extraction[name] = value
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

    def generate_default(self):
        # todo: support for polymorphic_on
        default = {}
        for name, field in self.structure.iteritems():
            if field.default:
                default[name] = field.default
        return default

    def merge(self, structure, prefer=False):
        for name, field in structure.iteritems():
            if not isinstance(field, Field):
                raise Exception()
            if name in self.structure and not prefer:
                return
            if field.name != name:
                field = field.clone(name=name)
            self.structure[name] = field

    def process(self, value, phase=INCOMING, serialized=False, partial=False):
        if self._is_null(value):
            return None
        if not isinstance(value, dict):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        valid = True
        names = set(value.keys())

        polymorphic_on = self.polymorphic_on
        if polymorphic_on:
            identity = value.get(polymorphic_on.name)
            if identity is not None:
                identity = polymorphic_on.process(identity, phase, serialized)
            else:
                raise ValidationError().construct(self, 'required', name=polymorphic_on.name)

            definition = self.structure.get(identity)
            if not definition:
                raise ValidationError().construct(self, 'unrecognized')
        else:
            definition = self.structure

        structure = {}
        for name, field in definition.iteritems():
            if name in names:
                names.remove(name)
                field_value = value[name]
            elif partial:
                continue
            elif phase == 'incoming' and field.default:
                field_value = field.get_default()
            elif field.required:
                valid = False
                structure[name] = ValidationError().construct(self, 'required', name=name)
                continue
            else:
                continue

            try:
                structure[name] = field.process(field_value, phase, serialized)
            except StructuralError, exception:
                valid = False
                structure[name] = exception

        if self.strict:
            for name in names:
                valid = False
                structure[name] = ValidationError().construct(self, 'unknown', name=name)

        if valid:
            return structure
        else:
            raise ValidationError(value=value, structure=structure)

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

    :param boolean nonempty: Optional, default is ``False``; if ``True``, this field will
        be instantiated with ``required=True, nonnull=True, min_length=1``. This is merely
        a shortcut argument.
    """

    errors = {
        'invalid': '%(field)s must be a textual value',
        'pattern': '%(field)s has an invalid value',
        'min_length': '%(field)s must contain at least %(min_length)d %(noun)s',
        'max_length': '%(field)s may contain at most %(max_length)d %(noun)s',
    }
    parameters = ('max_length', 'min_length')
    pattern = None

    def __init__(self, pattern=None, min_length=None, max_length=None, nonempty=False, **params):
        if nonempty:
            params.update(required=True, nonnull=True)
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

    def _validate_value(self, value):
        if not isinstance(value, basestring):
            raise InvalidTypeError(value=value).construct(self, 'invalid')
        if self.pattern and not self.pattern.match(value):
            raise ValidationError(value=value).construct(self, 'pattern')

        min_length = self.min_length
        if min_length is not None and len(value) < min_length:
            noun = 'character'
            if min_length > 1:
                noun = 'characters'
            raise ValidationError(value=value).construct(self, 'min_length',
                min_length=min_length, noun=noun)

        max_length = self.max_length
        if max_length is not None and len(value) > max_length:
            noun = 'character'
            if max_length > 1:
                noun = 'characters'
            raise ValidationError(value=value).construct(self, 'max_length',
                max_length=max_length, noun=noun)

class Time(Field):
    """A resource field for ``time`` values.

    :param minimum: Optional, default is ``None``; the earliest valid value for this field, as
        either a ``time`` or a callable which returns a ``time``.

    :param maximum: Optional, default is ``None``; the earliest valid value for this field, as
        either a ``time`` or a callable which returns a ``time``.
    """

    errors = {
        'invalid': '%(field)s must be a time value',
        'minimum': '%(field)s must not occur before %(minimum)s',
        'maximum': '%(field)s must not occur after %(maximum)s',
    }
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

    def _unserialize_value(self, value):
        if isinstance(value, time):
            return value

        try:
            return time(*strptime(value, self.pattern)[3:6])
        except Exception:
            raise InvalidTypeError(value=value).construct(self, 'invalid')

    def _validate_value(self, value):
        if not isinstance(value, time):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        minimum = self.minimum
        if minimum is not None:
            if callable(minimum):
                minimum = minimum()
            if value < minimum:
                raise ValidationError(value=value).construct(self, 'minimum',
                    minimum=minimum.strftime(self.pattern))

        maximum = self.maximum
        if maximum is not None:
            if callable(maximum):
                maximum = maximum()
            if value > maximum:
                raise ValidationError(value=value).construct(self, 'maximum',
                    maximum=maximum.strftime(self.pattern))

class Tuple(Field):
    """A resource field for tuples of values.

    :param tuple values: A ``tuple`` of :class:`Field`s which specifies the values this
        tuple contains; can only be ``None`` when instantiating a subclass which specifies
        ``values`` at the class level.
    """

    errors = {
        'invalid': '%(field)s must be a tuple',
        'length': '%(field)s must contain exactly %(length)d values',
    }
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

    @classmethod
    def construct(cls, specification):
        specification['values'] = tuple(Field.reconstruct(field) for field in specification['values'])
        return super(Tuple, cls).construct(specification)

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

    def extract(self, subject):
        extraction = []
        for i, definition in enumerate(self.values):
            value = subject[i]
            if value is not None and definition.structural:
                value = definition.extract(value)
            extraction.append(value)
        return tuple(extraction)

    def process(self, value, phase=INCOMING, serialized=False):
        if self._is_null(value):
            return None
        if not isinstance(value, (list, tuple)):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

        values = self.values
        if len(value) != len(values):
            raise ValidationError(value=value).construct(self, 'length', length=len(values))

        valid = True
        sequence = []

        for i, field in enumerate(values):
            try:
                sequence.append(field.process(value[i], phase, serialized))
            except StructuralError, exception:
                valid = False
                sequence.append(exception)

        if valid:
            return tuple(sequence)
        else:
            raise ValidationError(value=value, structure=sequence)

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

    def __init__(self, fields=None, **params):
        super(Union, self).__init__(**params)
        if fields is not None:
            self.fields = fields
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

    @classmethod
    def construct(cls, specification):
        specification['fields'] = tuple(Field.reconstruct(field) for field in specification['fields'])
        return super(Union, cls).construct(specification)

    def describe(self, parameters=None):
        fields = []
        for field in self.fields:
            if isinstance(field, Field):
                fields.append(field.describe(parameters))
            else:
                raise SchemeError()
        return super(Union, self).describe(parameters, fields=fields)

    def process(self, value, phase=INCOMING, serialized=False):
        if self._is_null(value):
            return None

        for field in self.fields:
            try:
                return field.process(value, phase, serialized)
            except InvalidTypeError:
                pass
        else:
            raise InvalidTypeError(value=value).construct(self, 'invalid')

    def _define_undefined_field(self, field, idx):
        self.fields = tuple(list(self.fields[:idx]) + [field] + list(self.fields[idx + 1:]))

    @classmethod
    def _visit_field(cls, specification, callback):
        return {'fields': tuple([callback(field) for field in specification['fields']])}

class UUID(Field):
    """A resource field for UUIDs."""

    errors = {
        'invalid': '%(field)s must be a UUID'
    }
    pattern = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')

    def __init__(self, nonempty=False, **params):
        if nonempty:
            params.update(required=True, nonnull=True)
        super(UUID, self).__init__(**params)

    def _validate_value(self, value):
        if not (isinstance(value, basestring) and self.pattern.match(value)):
            raise InvalidTypeError(value=value).construct(self, 'invalid')

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

__all__ = ['INCOMING', 'OUTGOING', 'Field', 'Errors', 'Undefined'] + construct_all_list(locals(), Field)
