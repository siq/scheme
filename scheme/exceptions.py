from traceback import format_exc

from scheme.util import format_structure, indent

__all__ = ('InvalidTypeError', 'SchemeError', 'StructuralError', 'ValidationError')

class SchemeError(Exception):
    """A scheme error."""

class StructuralError(SchemeError):
    """A structural error."""

    def __init__(self, *errors, **params):
        self.errors = list(errors)
        self.field = params.pop('field', None)
        self.identity = params.pop('identity', '(unknown)')
        self.structure = params.pop('structure', None)
        self.tracebacks = None
        self.value = params.pop('value', None)

        if params and 'token' in params:
            self.errors.append(params)

    def __str__(self):
        return '\n'.join(['validation failed'] + self.format_errors())

    @property
    def substantive(self):
        return (self.errors or self.structure)

    def append(self, error):
        self.errors.append(error)
        return self

    def attach(self, structure):
        self.structure = structure
        return self

    def capture(self):
        if self.tracebacks is None:
            self.tracebacks = []

        self.tracebacks.append(format_exc())
        return self

    def format_errors(self):
        errors = []
        if self.errors:
            self._format_errors(errors)
        if self.structure:
            self._format_structure(errors)

        enumerated_errors = []
        for i, error in enumerate(errors):
            enumerated_errors.append('[%02d] %s' % (i + 1, indent(error, 5, False)))

        return enumerated_errors

    def merge(self, exception):
        self.errors.extend(exception.errors)
        return self

    def serialize(self, force=False):
        if not force:
            try:
                return self._serialized_errors
            except AttributeError:
                pass

        if self.errors:
            errors = self._serialize_errors(self.errors)
        else:
            errors = None

        if self.structure:
            structure = self._serialize_structure()
        else:
            structure = None

        self._serialized_errors = [errors, structure]
        return self._serialized_errors

    def _format_errors(self, errors):
        field = self.field
        if not field:
            return

        identity = ''.join(self.identity)
        for error in self.errors:
            definition = field.errors[error['token']]
            lines = ['%s error at %s: %s' % (error['title'].capitalize(), identity,
                error['message'])]

            if definition.show_field:
                lines.append('Field: %r' % field)

            if definition.show_value and self.value is not None:
                lines.append('Value: %r' % self.value)

            if self.tracebacks:
                lines.append('Captured tracebacks:')
                for traceback in self.tracebacks:
                    lines.append(indent(traceback, 2))

            errors.append('\n'.join(lines))

    def _format_structure(self, errors):
        if isinstance(self.structure, list):
            for item in self.structure:
                if isinstance(item, StructuralError):
                    if item.structure is not None:
                        item._format_structure(errors)
                    else:
                        item._format_errors(errors)
        elif isinstance(self.structure, dict):
            for value in self.structure.itervalues():
                if isinstance(value, StructuralError):
                    if value.structure is not None:
                        value._format_structure(errors)
                    else:
                        value._format_errors(errors)

    def _serialize_errors(self, errors):
        serialized = []
        for error in errors:
            if isinstance(error, dict):
                serialized.append(error)
            else:
                serialized.append({'message': error})
        return serialized

    def _serialize_structure(self):
        if isinstance(self.structure, list):
            errors = []
            for item in self.structure:
                if isinstance(item, StructuralError):
                    if item.structure is not None:
                        errors.append(item._serialize_structure())
                    else:
                        errors.append(self._serialize_errors(item.errors))
                else:
                    errors.append(None)
            return errors
        elif isinstance(self.structure, dict):
            errors = {}
            for attr, value in self.structure.iteritems():
                if isinstance(value, StructuralError):
                    if value.structure is not None:
                        errors[attr] = value._serialize_structure()
                    else:
                        errors[attr] = self._serialize_errors(value.errors)
            return errors
        else:
            raise ValueError()

class ValidationError(StructuralError):
    """Raised when validation fails."""

    def construct(self, error, **params):
        error = self.field.errors[error]
        return self.append({'token': error.token, 'title': error.title,
            'message': error.format(self.field, params)})

class InvalidTypeError(ValidationError):
    """A validation error indicating the value being processed is invalid due
    to its type."""

class UndefinedParameterError(SchemeError):
    """Raised when interpolation encounters an undefined parameter."""
