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
    schemas = None

    def __init__(self, value, schema=None, version=None):
        super(surrogate, self).__init__(value)
        self.schema = schema
        self.version = version

    def __repr__(self):
        return '%s(%s)' % (self.surrogate, super(surrogate, self).__repr__())

    @classmethod
    def construct(cls, implementation=None, value=None, schema=None, version=None, **params):
        """Constructs a surrogate instance from ``value``, using the surrogate type
        indicated by ``implementation``.

        :param string implementation: The full module and class path to a surrogate
            subclass, indicating the type of surrogate to construct.
        """

        if implementation is None:
            implementation = cls
        if isinstance(implementation, basestring):
            implementation = cls._get_implementation(implementation)

        effective_schema = schema
        if effective_schema:
            if implementation.schemas:
                raise Exception('cannot specify dynamic schema for surrogate with inherent schema')
        elif implementation.schemas:
            if version is None:
                version = len(implementation.schemas)
            try:
                effective_schema = implementation.schemas[version - 1]
            except IndexError:
                raise Exception('invalid surrogate version')

        if value is not None:
            if isinstance(value, dict):
                value = dict(value)
                if effective_schema:
                    value = effective_schema.extract(value)
            elif effective_schema:
                value = effective_schema.extract(value, strict=False)
            else:
                raise ValueError(value)
            if params:
                value.update(params)
        elif params:
            value = params
        else:
            raise ValueError(value)

        implementation.contribute(value, version)
        return implementation(value, schema, version)

    @classmethod
    def contribute(cls, value, version):
        pass

    @classmethod
    def interpolate(cls, value, parameters, interpolator=None):
        implementation = cls._get_implementation(value.pop('_', None))
        if '__schema__' in value:
            return implementation._interpolate_dynamic_surrogate(value, parameters, interpolator)
        elif implementation.schemas:
            return implementation._interpolate_versioned_surrogate(value, parameters, interpolator)
        else:
            raise ValueError(value)

    def serialize(self):
        """Serializes this surrogate."""

        value = dict(self)
        if self.schema:
            value = self.schema.serialize(value)
            value['__schema__'] = self.schema.describe()
        elif self.schemas:
            value = self.schemas[self.version - 1].serialize(value)
            if self.version > 1:
                value['__version__'] = self.version

        value['_'] = self.surrogate
        return value

    @classmethod
    def unserialize(cls, value, ancestry=None):
        value = dict(value)
        implementation = cls._get_implementation(value.pop('_', None))

        if '__schema__' in value:
            return implementation._unserialize_dynamic_surrogate(value, ancestry)
        elif implementation.schemas:
            return implementation._unserialize_versioned_surrogate(value, ancestry)
        else:
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
    def _interpolate_dynamic_surrogate(cls, value, parameters, interpolator):
        schema = scheme.Field.reconstruct(value.pop('__schema__'))
        if not schema:
            raise ValueError(value)

        value = schema.interpolate(value, parameters, interpolator)
        cls.contribute(value, None)
        return implementation(value, schema)

    @classmethod
    def _interpolate_versioned_surrogate(cls, value, parameters, interpolator):
        version = value.pop('__version__', None)
        if version is None:
            version = len(cls.schemas)

        try:
            schema = cls.schemas[version - 1]
        except IndexError:
            raise ValueError(value)

        value = schema.interpolate(value, parameters, interpolator)
        cls.contribute(value, version)
        return cls(value, version=version)

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

    @classmethod
    def _unserialize_versioned_surrogate(cls, value, ancestry=None):
        version = value.pop('__version__', 1)
        try:
            schema = cls.schemas[version - 1]
        except IndexError:
            raise ValueError(value)

        value = schema.unserialize(value, ancestry=ancestry)
        return cls(value, version=version)
