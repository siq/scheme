from datetime import date
import re

try:
    import jinja2
except ImportError:
    jinja2 = None

from scheme.exceptions import UndefinedParameterError
from scheme.timezone import current_timestamp

PLURALIZATION_RULES = (
    (re.compile(r'ife$'), re.compile(r'ife$'), 'ives'),
    (re.compile(r'eau$'), re.compile(r'eau$'), 'eaux'),
    (re.compile(r'lf$'), re.compile(r'lf$'), 'lves'),
    (re.compile(r'[sxz]$'), re.compile(r'$'), 'es'),
    (re.compile(r'[^aeioudgkprt]h$'), re.compile(r'$'), 'es'),
    (re.compile(r'(qu|[^aeiou])y$'), re.compile(r'y$'), 'ies'),
)

SPACER_EXPR = re.compile(r'[-_\s]+')
VALID_CHARS_EXPR = re.compile(r'[^\w\s-]')
VARIABLE_EXPR = re.compile(r'^\s*[$][{]([^}]+)[}]\s*$')

def now(format='%Y-%m-%d %H:%M:%S %Z'):
    return current_timestamp().strftime(format)

def pluralize(value, quantity=None, rules=PLURALIZATION_RULES):
    if quantity == 1:
        return value

    for pattern, target, replacement in rules:
        if pattern.search(value):
            return target.sub(replacement, value)
    else:
        return value + 's'

def slugify(value, spacer='-', lowercase=True):
    if not isinstance(value, unicode):
        value = unicode(value)

    value = value.encode('ascii', 'ignore')
    value = VALID_CHARS_EXPR.sub('', value).strip()

    if lowercase:
        value = value.lower()
    return SPACER_EXPR.sub(spacer, value)

def timestamp():
    return current_timestamp().strftime('%Y%m%d%H%M%S')

class UndefinedValueError(Exception):
    pass

class Interpolator(object):
    """The standard jinja-based template renderer."""

    default_interpolator = None
    standard_filters = [pluralize, slugify]
    standard_globals = [now, timestamp]

    def __init__(self, filters=None, globals=None):
        self.environment = jinja2.Environment(
            variable_start_string='${',
            variable_end_string='}')

        for filter in self.standard_filters:
            self.environment.filters[filter.__name__] = filter
        for function in self.standard_globals:
            self.environment.globals[function.__name__] = function

        if filters:
            self.environment.filters.update(filters)
        if globals:
            self.environment.globals.update(globals)

    @classmethod
    def default(cls):
        if cls.default_interpolator is None:
            cls.default_interpolator = cls()
        return cls.default_interpolator

    def evaluate(self, subject, parameters):
        expression = self.environment.compile_expression(subject, False)
        value = expression(**parameters)
        if isinstance(value, self.environment.undefined):
            raise UndefinedValueError()
        return value

    def interpolate(self, subject, parameters):
        template = self.environment.from_string(subject)
        return template.render(parameters)

def interpolate_parameters(subject, parameters, interpolator=None, simple=False):
    """Interpolates ``subject``, a template, using ``parameters.``

    :param string subject: The template to interpolate.

    :param dict parameters: A ``dict`` of potential values for interpolating
        ``subject``.

    :param interpolator: Optional, defaults to ``None``; if specified, an
        :cls:`Interpolator` instance to use for the interpolation, rather then
        the default one.

    :param boolean simple: Optional, defaults to ``False``; if ``True``. 
    """

    if not isinstance(subject, basestring):
        raise ValueError(subject)
    if not subject:
        return ''

    interpolator = interpolator or Interpolator.default()
    if simple:
        match = VARIABLE_EXPR.match(subject)
        if match:
            expression = match.group(1).strip()
            return interpolator.evaluate(expression, parameters)
        else:
            return subject
    else:
        return interpolator.interpolate(subject, parameters)
