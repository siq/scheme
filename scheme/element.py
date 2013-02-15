from scheme.fields import *

class ElementMeta(type):
    def __new__(metatype, name, bases, namespace):
        element = type.__new__(metatype, name, bases, namespace)
        if element.schema is None:
            return element

        element.__polymorphic_on__ = None
        schema = element.schema

        if isinstance(schema, Structure):
            element.__attrs__ = schema.generate_default(sparse=False)
            if schema.polymorphic:
                element.__polymorphic_on__ = schema.polymorphic_on.name
        elif schema.name:
            element.__attrs__ = {schema.name: schema.default}
        else:
            raise TypeError(schema)

        schema.instantiator = element.instantiate
        schema.extractor = element.extract
        return element

class Element(object):
    """A schema-based object."""

    __metaclass__ = ElementMeta
    schema = None

    def __init__(self, **params):
        polymorphic_on = self.__polymorphic_on__
        if polymorphic_on:
            defaults = self.__attrs__[params[polymorphic_on]]
        else:
            defaults = self.__attrs__

        for attr, default in defaults.iteritems():
            setattr(self, attr, params.get(attr, default))

    def __repr__(self):
        aspects = []
        for attr in ('id', 'name', 'title'):
            value = getattr(self, attr, None)
            if value is not None:
                aspects.append('%s=%r' % (attr, value))
        return '%s(%s)' % (type(self).__name__, ', '.join(aspects))

    @classmethod
    def extract(cls, field, subject):
        if isinstance(field, Structure):
            return subject.__dict__
        else:
            return getattr(subject, field.name)

    @classmethod
    def instantiate(cls, field, value, key=None):
        if isinstance(field, Structure):
            return cls(**value)
        else:
            return cls(**{field.name: value})

    def serialize(self, format='yaml'):
        return self.schema.serialize(self.schema.extract(self), format)

    @classmethod
    def unserialize(cls, value, format='yaml'):
        return cls.schema.instantiate(cls.schema.unserialize(value, format))
