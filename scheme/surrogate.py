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
    def construct(cls, implementation, value=None, **params):
        if params:
            if value:
                value = dict(value, **params)
            else:
                value = params
        elif value:
            value = dict(value)
        else:
            raise ValueError(value)

        if isinstance(implementation, basestring):
            implementation = cls._get_implementation(implementation)
        if implementation.schema:
            value = implementation.schema.extract(value)
        return implementation(value)

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
