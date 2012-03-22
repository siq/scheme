import re
from urllib import urlencode

try:
    import json
except ImportError:
    from scheme import json

try:
    from urlparse import parse_qsl
except ImportError:
    from cgi import parse_qsl

from scheme.util import construct_all_list

class FormatMeta(type):
    def __new__(metatype, name, bases, namespace):
        format = type.__new__(metatype, name, bases, namespace)
        if not format.name:
            return format

        format.formats[format.name] = format
        if format.mimetype:
            format.formats[format.mimetype] = format

        format.formats[format] = format
        return format

class Format(object):
    """A data format."""

    __metaclass__ = FormatMeta
    formats = {}

    mimetype = None
    name = None

    @classmethod
    def serialize(cls, value):
        raise NotImplementedError()

    @classmethod
    def unserialize(cls, value):
        raise NotImplementedError()

class Json(Format):
    mimetype = 'application/json'
    name = 'json'

    @classmethod
    def serialize(cls, value):
        return json.dumps(value)

    @classmethod
    def unserialize(cls, value):
        return json.loads(value)

class StructuredText(Format):
    mimetype = 'text/plain'
    name = 'structuredtext'

    STRUCTURE_EXPR = re.compile(r'(?:\{[^{\[\]]*?\})|(?:\[[^{}\[]*?\])')

    @classmethod
    def serialize(cls, value):
        return cls._serialize_content(value)

    @classmethod
    def unserialize(cls, value):
        if not isinstance(value, basestring):
            raise ValueError(value)
        if value[0] in ('{', '['):
            return cls._unserialize_structured_value(value)
        else:
            return cls._unserialize_simple_value(value)

    @classmethod
    def _serialize_content(cls, content):
        if isinstance(content, dict):
            tokens = []
            for key, value in sorted(content.iteritems()):
                tokens.append('%s:%s' % (key, cls._serialize_content(value)))
            return '{%s}' % ','.join(tokens)
        elif isinstance(content, (list, tuple)):
            tokens = []
            for value in content:
                tokens.append(cls._serialize_content(value))
            return '[%s]' % ','.join(tokens)
        elif isinstance(content, bool):
            return content and 'true' or 'false'
        else:
            return str(content)

    @classmethod
    def _unserialize_structure(cls, text, structures):
        head, tail = text[0], text[-1]
        if head == '{' and tail == '}':
            tokens = text[1:-1]
            if tokens:
                try:
                    pairs = []
                    for pair in tokens.split(','):
                        key, value = pair.split(':')
                        if value in structures:
                            value = structures[value]
                        else:
                            value = cls._unserialize_simple_value(value)
                        pairs.append((key, value))
                    return dict(pairs)
                except Exception:
                    raise ValueError(value)
            else:
                return {}
        elif head == '[' and tail == ']':
            tokens = text[1:-1]
            if tokens:
                values = []
                for value in tokens.split(','):
                    if value in structures:
                        value = structures[value]
                    else:
                        value = cls._unserialize_simple_value(value)
                    values.append(value)
                return values
            else:
                return []
        else:
            raise ValueError(value)

    @classmethod
    def _unserialize_structured_value(cls, text):
        expr = cls.STRUCTURE_EXPR
        structures = {}

        def replace(match):
            token = '||%d||' % len(structures)
            structures[token] = cls._unserialize_structure(match.group(0), structures)
            return token
            
        while True:
            text, count = expr.subn(replace, text)
            if count == 0:
                return structures[text]

    @classmethod
    def _unserialize_simple_value(cls, value):
        candidate = value.lower()
        if candidate == 'true':
            return True
        elif candidate == 'false':
            return False
        else:
            return value

class UrlEncoded(StructuredText):
    mimetype = 'application/x-www-form-urlencoded'
    name = 'urlencoded'

    @classmethod
    def serialize(cls, content):
        if not isinstance(content, dict):
            raise ValueError(content)

        data = []
        for name, value in content.iteritems():
            data.append((name, cls._serialize_content(value)))
        return urlencode(data)

    @classmethod
    def unserialize(cls, content):
        if not isinstance(content, basestring):
            raise ValueError(content)

        data = {}
        for name, value in parse_qsl(content):
            if value[0] in ('{', '['):
                value = cls._unserialize_structured_value(value)
            else:
                value = cls._unserialize_simple_value(value)
            data[name] = value
        return data

class Yaml(Format):
    mimetype = 'application/x-yaml'
    name = 'yaml'

    @classmethod
    def serialize(cls, value):
        import yaml
        return yaml.dump(value)

    @classmethod
    def unserialize(cls, value):
        import yaml
        return yaml.load(value)

__all__ = ['Format'] + construct_all_list(locals(), Format)
