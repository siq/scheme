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

try:
    import xml.etree.cElementTree as etree
except ImportError:
    etree = None

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
        if not path:
            raise ValueError(path)
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

    STRUCTURE_EXPR = re.compile(
        r'(?:\{((\\[\\\[\]\{\}])|[^\\{\[\]])*?\})|(?:\[((\\[\\\[\]\{\}])|[^\\{}\[])*?\])'
    )
    STRUCTURE_TOKENS_EXPR = re.compile(r'([{}\[\]])')
    ESCAPED_TOKENS_EXPR = re.compile(r'\\([{}\[\]])')

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
        elif content is None:
            return 'null'
        elif isinstance(content, basestring):
            return cls.STRUCTURE_TOKENS_EXPR.sub(r'\\\1', content)
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
            raise ValueError(text)

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
        elif candidate == 'null':
            return None
        elif not parse_numbers:
            return cls.ESCAPED_TOKENS_EXPR.sub(r'\1', value)

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
    indicators = '-?:,[]{}#&*!|>\'"%@`'
    line_width = 100
    mimetype = 'application/x-yaml'
    name = 'yaml'
    requires_escape = (': ', ' #')
    requires_quotes = ('null', '~', 'true', 'false')
    whitespace = re.compile(r'^\s*$')

    @classmethod
    def serialize(cls, value):
        content = cls._serialize_value(value, 0)
        if isinstance(content, list):
            content = '\n'.join(content)
        return content + '\n'

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
    def _requires_escaping(cls, value):
        if value[0] in cls.indicators:
            return True

        for token in cls.requires_escape:
            if token in value:
                return True
        else:
            return False

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
                    lines.append('%s %s' % (key, content[0].lstrip()))
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
        if '\n' in value:
            lines = ['|']
            for line in value.split('\n'):
                if line:
                    lines.append(indent + line)
                else:
                    lines.append('')
            return lines
        elif length + len(indent) <= cls.line_width:
            if cls._requires_escaping(value):
                return "'%s'" % value.replace("'", "''")
            else:
                return value
        else:
            if cls._requires_escaping(value):
                value = "'%s'" % value.replace("'", "''")

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

class Xml(Format):
    default_root = 'root'
    extensions = ['.xml']
    mimetype = 'application/xml'
    name = 'xml'
    preamble = '<?xml version="1.0"?>\n'

    @classmethod
    def serialize(cls, value, root=None, preamble=True):
        element = etree.Element(root or cls.default_root)
        cls._serialize_content(value, element)

        serialized = etree.tostring(element)
        if preamble:
            serialized = cls.preamble + serialized

        return serialized

    @classmethod
    def unserialize(cls, value, ignore_root=True):
        root = etree.fromstring(value)
        attr, value = cls._unserialize_element(root)

        if not ignore_root:
            value = {attr: value}

        return value

    @classmethod
    def _is_list(cls, candidates):
        for attr, child in candidates:
            if attr != '_':
                return False
        else:
            return True

    @classmethod
    def _serialize_content(cls, content, element):
        if isinstance(content, dict):
            if content:
                for key, value in sorted(content.iteritems()):
                    subelement = etree.SubElement(element, key)
                    cls._serialize_content(value, subelement)
            else:
                element.set('type', 'struct')
        elif isinstance(content, (list, set, tuple)):
            if content:
                for value in content:
                    subelement = etree.SubElement(element, '_')
                    cls._serialize_content(value, subelement)
            else:
                element.set('type', 'list')
        elif isinstance(content, bool):
            if content:
                element.text = 'true'
            else:
                element.text = 'false'
        elif content is None:
            element.text = 'null'
        else:
            element.text = str(content)

    @classmethod
    def _unserialize_element(cls, element):
        attr = element.tag
        type = element.get('type', None)

        children = list(element)
        if children:
            children = [cls._unserialize_element(child) for child in children]
            if type == 'list' or cls._is_list(children):
                return attr, [child[1] for child in children]
            else:
                return attr, dict(children)

        if not element.text:
            if type == 'list':
                return attr, []
            elif type == 'struct':
                return attr, {}
            elif type in ('bool', 'int', 'float', 'null'):
                return attr, None
            else:
                return attr, ''

        if type == 'str':
            return attr, element.text

        candidate = element.text.lower()
        if candidate == 'true':
            return attr, True
        elif candidate == 'false':
            return attr, False
        elif candidate == 'null':
            return attr, None

        value = element.text
        if '.' in value:
            try:
                return attr, float(value)
            except (TypeError, ValueError):
                pass

        try:
            return attr, int(value)
        except (TypeError, ValueError):
            return attr, value

def serialize(mimetype, value, **params):
    return Format.formats[mimetype].serialize(value, **params)

def unserialize(mimetype, value, **params):
    return Format.formats[mimetype].unserialize(value, **params)

__all__ = ['Format'] + construct_all_list(locals(), Format)
