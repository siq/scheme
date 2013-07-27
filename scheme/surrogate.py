import scheme
from scheme.interpolation import interpolate_parameters
from scheme.util import identify_object, import_object

class SurrogateMeta(type):
    def __new__(metatype, name, bases, namespace):
        cls = type.__new__(metatype, name, bases, namespace)
        cls.surrogate = identify_object(cls)
        return cls

class surrogate(dict):
    """A schema-based object surrogate."""

    __metaclass__ = SurrogateMeta
    cache = {}
    schema = None

    def __init__(self, value, schema=None):
        super(surrogate, self).__init__(value)
        self._dynamic_schema = schema

    def __repr__(self):
        return '%s(%s)' % (self.surrogate, super(surrogate, self).__repr__())

    @property
    def effective_schema(self):
        return self._dynamic_schema or self.schema

    @classmethod
    def construct(cls, implementation=None, value=None, schema=None, strict=False, **params):
        """Constructs a surrogate instance from ``value``, using the surrogate type
        indicated by ``implementation``.

        :param string implementation: The full module and class path to a surrogate
            subclass, indicating the type of surrogate to construct.

        :param value: Optional, default is ``None``; if specified, can either be a
            ``dict`` or object instance from which to 
        """

        if implementation is None:
            implementation = cls
        if isinstance(implementation, basestring):
            implementation = cls._get_implementation(implementation)

        surrogate_schema = schema
        if surrogate_schema:
            if implementation.schema:
                raise Exception('cannot specify dynamic schema for surrogate with inherent schema')
        else:
            surrogate_schema = implementation.schema

        if value is not None:
            if isinstance(value, dict):
                value = dict(value)
                if surrogate_schema:
                    value = surrogate_schema.extract(value)
            elif not strict and surrogate_schema:
                value = surrogate_schema.extract(value, strict=False)
            else:
                raise ValueError(value)
            if params:
                value.update(params)
        elif params:
            value = params
        else:
            raise ValueError(value)

        implementation.contribute(value)
        return implementation(value, schema)

    @classmethod
    def contribute(cls, value):
        pass

    @classmethod
    def interpolate(cls, value, parameters, interpolator=None):
        implementation = cls._get_implementation(value.pop('_', None))
        if '__schema__' in value:
            schema = scheme.Field.reconstruct(value.pop('__schema__'))
            if schema:
                value = schema.interpolate(value, parameters, interpolator)
                return implementation(value, schema)
            else:
                raise ValueError(value)
        elif implementation.schema:
            value = implementation.schema.interpolate(value, parameters, interpolator)
            return implementation(value)
        else:
            return implementation(value)

    def serialize(self):
        """Serializes this surrogate."""

        value = dict(self)
        if self._dynamic_schema:
            value = self._dynamic_schema.serialize(value)
        elif self.schema:
            value = self.schema.serialize(value)

        value['_'] = self.surrogate
        if self._dynamic_schema:
            value['__schema__'] = self._dynamic_schema.describe()
        return value

    @classmethod
    def unserialize(cls, value, ancestry=None):
        value = dict(value)
        implementation = cls._get_implementation(value.pop('_', None))
        if '__schema__' in value:
            return implementation._unserialize_dynamic_surrogate(value, ancestry)
        elif implementation.schema:
            value = implementation.schema.unserialize(value, ancestry=ancestry)
        return implementation(value)

    @classmethod
    def _get_implementation(cls, token):
        if token is None:
            return surrogate
        elif token in cls.cache:
            return cls.cache[token]

        try:
            implementation = import_object(token)
        except ImportError:
            implementation = surrogate

        cls.cache[token] = implementation
        return implementation

    @classmethod
    def _unserialize_dynamic_surrogate(cls, value, ancestry=None):
        schema = value.pop('__schema__', None)
        if not schema:
            raise ValueError(value)

        schema = scheme.Field.reconstruct(schema)
        if not schema:
            raise ValueError(value)

        value = schema.unserialize(value, ancestry=ancestry)
        return cls(value, schema)
