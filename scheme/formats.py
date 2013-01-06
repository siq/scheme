import os
import re
from csv import Dialect, DictWriter, QUOTE_ALL
from cStringIO import StringIO
from datetime import date, datetime, time
from textwrap import TextWrapper
from urllib import urlencode

try:
    from collections import OrderedDict
except ImportError:
    class OrderedDict(object):
        pass

try:
    import json
except ImportError:
    from scheme import json

try:
    from urlparse import parse_qsl
except ImportError:
    from cgi import parse_qsl

try:
    import yaml
except ImportError:
    yaml = None

from scheme.util import construct_all_list, traverse_to_key

class FormatMeta(type):
    def __new__(metatype, name, bases, namespace):
        format = type.__new__(metatype, name, bases, namespace)
        if not format.name:
            return format

        if format.extensions:
            for extension in format.extensions:
                if extension[0] == '.':
                    format.formats[extension] = format

        format.formats[format.name] = format
        if format.mimetype:
            format.formats[format.mimetype] = format

        format.formats[format] = format
        return format

class Format(object):
    """A data format."""

    __metaclass__ = FormatMeta
    formats = {}

    extensions = None
    mimetype = None
    name = None

    @classmethod
    def read(cls, path, quiet=False, **params):
        if not os.path.exists(path):
            if quiet:
                return False
            else:
                raise ValueError(path)

        format = cls
        if not cls.name:
            extension = os.path.splitext(path)[-1].lower()
            if extension in cls.formats:
                format = cls.formats[extension]
            else:
                raise Exception()

        openfile = open(path)
        try:
            return format.unserialize(openfile.read(), **params)
        finally:
            openfile.close()

    @classmethod
    def serialize(cls, value):
        raise NotImplementedError()

    @classmethod
    def unserialize(cls, value):
        raise NotImplementedError()

    @classmethod
    def write(cls, path, value, format=None, **params):
        if not format:
            format = os.path.splitext(path)[-1].lower()

        openfile = open(path, 'w+')
        try:
            openfile.write(cls.formats[format].serialize(value, **params))
        finally:
            openfile.close()

class Json(Format):
    extensions = ['.json']
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
    def unserialize(cls, value, parse_numbers=False):
        if not isinstance(value, basestring):
            raise ValueError(value)
        if value[0] in ('{', '['):
            return cls._unserialize_structured_value(value, parse_numbers)
        else:
            return cls._unserialize_simple_value(value, parse_numbers)

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
    def _unserialize_structure(cls, text, structures, parse_numbers=False):
        head, tail = text[0], text[-1]
        if head == '{' and tail == '}':
            tokens = text[1:-1]
            if tokens:
                pairs = []
                for pair in tokens.split(','):
                    key, value = pair.split(':', 1)
                    try:
                        if value in structures:
                            value = structures[value]
                        else:
                            value = cls._unserialize_simple_value(value, parse_numbers)
                        pairs.append((key, value))
                    except Exception:
                        raise ValueError(value)

                return dict(pairs)
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
                        value = cls._unserialize_simple_value(value, parse_numbers)
                    values.append(value)
                return values
            else:
                return []
        else:
            raise ValueError(value)

    @classmethod
    def _unserialize_structured_value(cls, text, parse_numbers=False):
        expr = cls.STRUCTURE_EXPR
        structures = {}

        def replace(match):
            token = '||%d||' % len(structures)
            structures[token] = cls._unserialize_structure(match.group(0), structures, parse_numbers)
            return token
            
        while True:
            text, count = expr.subn(replace, text)
            if count == 0:
                return structures[text]

    @classmethod
    def _unserialize_simple_value(cls, value, parse_numbers=False):
        candidate = value.lower()
        if candidate == 'true':
            return True
        elif candidate == 'false':
            return False
        elif not parse_numbers:
            return value

        if '.' in value:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass

        try:
            return int(value)
        except (TypeError, ValueError):
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
    extensions = ['.yaml', '.yml']
    indent = '  '
    line_width = 100
    mimetype = 'application/x-yaml'
    name = 'yaml'
    requires_quotes = ('null', '~', 'true', 'false')
    whitespace = re.compile(r'^\s*$')

    @classmethod
    def serialize(cls, value):
        content = cls._serialize_value(value, 0)
        if isinstance(content, list):
            content = '\n'.join(content)
        return content

    @classmethod
    def unserialize(cls, value):
        return yaml.load(value)

    @classmethod
    def _is_literal_text(cls, value):
        if '\n' not in value:
            return False

        whitespace = cls.whitespace
        for line in value.split('\n'):
            if not line or whitespace.match(line):
                continue
            if line[0] in ' \t\v\f':
                return True
        else:
            return False

    @classmethod
    def _is_simple_sequence(cls, value):
        for item in value:
            if not (item is None or isinstance(item, (bool, float, int))):
                return False
        else:
            return True

    @classmethod
    def _serialize_sequence(cls, value, level):
        if not value:
            return '[]'

        if cls._is_simple_sequence(value):
            return '[%s]' % ', '.join(cls._serialize_value(v, None) for v in value)

        prefix = (cls.indent * level) + '-'
        lines = []
        for v in value:
            content = cls._serialize_value(v, level + 1)
            if isinstance(content, list):
                lines.append('%s %s' % (prefix, content[0].lstrip()))
                lines.extend(content[1:])
            else:
                lines.append('%s %s' % (prefix, content))
        return lines

    @classmethod
    def _serialize_structure(cls, value, level):
        if not value:
            return '{}'

        if isinstance(value, OrderedDict):
            items = value.iteritems()
        else:
            items = sorted(value.iteritems())

        lines = []
        for k, v in items:
            key = '%s%s:' % (cls.indent * level, k)
            if isinstance(v, basestring):
                content = cls._serialize_string(v, level + 1)
                if isinstance(content, list):
                    lines.append('%s %s' % (key, content[0]))
                    lines.extend(content[1:])
                else:
                    lines.append('%s %s' % (key, content))
            else:
                content = cls._serialize_value(v, level + 1)
                if isinstance(content, list):
                    lines.append(key)
                    lines.extend(content)
                else:
                    lines.append('%s %s' % (key, content))
        return lines

    @classmethod
    def _serialize_string(cls, value, level):
        length = len(value)
        if length == 0:
            return "''"
        elif length <= 5 and value.lower() in cls.requires_quotes:
            return "'%s'" % value

        indent = cls.indent * level
        if cls._is_literal_text(value):
            lines = ['|']
            for line in value.split('\n'):
                if line:
                    lines.append(indent + line)
                else:
                    lines.append('')
            return lines
        elif length + len(indent) <= cls.line_width:
            return value
        else:
            wrapper = TextWrapper(width=cls.line_width, initial_indent=indent,
                subsequent_indent=indent, break_long_words=False,
                replace_whitespace=False, drop_whitespace=False)

            lines = []
            for line in value.splitlines():
                lines.extend(wrapper.wrap(line))
            return lines

    @classmethod
    def _serialize_value(cls, value, level):
        if value is None:
            return 'null'
        elif isinstance(value, (OrderedDict, dict)):
            return cls._serialize_structure(value, level)
        elif isinstance(value, (list, set, tuple)):
            return cls._serialize_sequence(value, level)
        elif isinstance(value, basestring):
            return cls._serialize_string(value, level)
        elif isinstance(value, bool):
            if value:
                return 'true'
            else:
                return 'false'
        elif isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(value, date):
            return value.strftime('%Y-%m-%d')
        elif isinstance(value, time):
            return "'%s'" % value.strftime('%H:%M:%S')
        elif isinstance(value, (float, int)):
            return str(value)
        else:
            raise ValueError(value)

class Csv(Format):
    extensions = ['.csv']
    mimetype = 'application/csv'
    name = 'csv'

    class Dialect(Dialect):
        quoting = QUOTE_ALL
        quotechar = '"'
        doublequote = True
        delimiter = ','
        escapechar = None
        lineterminator = '\r\n'
        skipinitialspace = False

    @classmethod
    def serialize(cls, value, columns=None, path=None):
        if path:
            value = traverse_to_key(value, path)
        if not isinstance(value, (list, tuple)):
            raise ValueError(value)
        if not value:
            return ''

        if isinstance(columns, basestring):
            columns = columns.split(',')
        if not columns:
            columns = sorted(value[0].keys())

        content = StringIO()
        writer = DictWriter(content, columns, extrasaction='ignore', dialect=cls.Dialect)

        writer.writerow(dict((name, name) for name in columns))
        writer.writerows(value)
        return content.getvalue()

__all__ = ['Format'] + construct_all_list(locals(), Format)
