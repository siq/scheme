from scheme.interpolation import interpolate_parameters
from scheme.util import identify_object, import_object

class SurrogateMeta(type):
    def __new__(metatype, name, bases, namespace):
        cls = type.__new__(metatype, name, bases, namespace)
        if cls.schema:
            from scheme.fields import Structure, Token
            if isinstance(cls.schema, Structure):
                cls.schema.insert(Token(name='_', nonempty=True), True)
            else:
                raise TypeError(cls.schema)

        cls.surrogate = identify_object(cls)
        return cls

class surrogate(dict):
    """A schema-based object surrogate."""

    __metaclass__ = SurrogateMeta
    cache = {}
    schema = None

    def __repr__(self):
        return '%s(%s)' % (self.surrogate, super(surrogate, self).__repr__())

    @classmethod
    def construct(cls, implementation, value=None, strict=False, **params):
        """Constructs a surrogate instance from ``value``, using the surrogate type
        indicated by ``implementation``.

        :param string implementation: The full module and class path to a surrogate
            subclass, indicating the type of surrogate to construct.

        :param value: Optional, default is ``None``; if specified, can either be a
            ``dict`` or object instance from which to 
        """


        if isinstance(implementation, basestring):
            implementation = cls._get_implementation(implementation)

        if value is not None:
            if isinstance(value, dict):
                value = dict(value)
                if implementation.schema:
                    value = implementation.schema.extract(value)
            elif not strict and implementation.schema:
                value = implementation.schema.extract(value, strict=False)
            else:
                raise ValueError(value)
            if params:
                value.update(params)
        elif params:
            value = params
        else:
            raise ValueError(value)

        implementation.contribute(value)
        return implementation(value)

    @classmethod
    def contribute(cls, value):
        pass

    @classmethod
    def interpolate(cls, value, parameters, interpolator=None):
        implementation = cls._get_implementation(value.get('_'))
        if implementation.schema:
            return implementation.schema.interpolate(value, parameters, interpolator)
        else:
            return value # should probably best effort this

    def serialize(self):
        value = dict(self, _=self.surrogate)
        if self.schema:
            value = self.schema.serialize(value)
        return value

    @classmethod
    def unserialize(cls, value, ancestry=None):
        implementation = cls._get_implementation(value.get('_'))
        if implementation.schema:
            value = implementation.schema.unserialize(value, ancestry=ancestry)

        value.pop('_', None)
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
