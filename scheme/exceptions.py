__all__ = ('InvalidTypeError', 'SchemeError', 'StructuralError', 'ValidationError')

class SchemeError(Exception):
    """A scheme error."""

class StructuralError(SchemeError):
    """A structural error."""

    def __init__(self, *errors, **params):
        self.errors = list(errors)
        self.structure = params.get('structure', None)
        self.value = params.get('value', None)

    @property
    def substantive(self):
        return (self.errors or self.structure)

    def append(self, error):
        self.errors.append(error)
        return self

    def attach(self, structure):
        self.structure = structure
        return self

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

    def construct(self, field, error, **params):
        message = field.get_error(error)
        if message:
            params['field'] = field.name or 'unknown-field'
            return self.append({'token': error, 'message': message % params})
        else:
            raise KeyError(error)

class InvalidTypeError(ValidationError):
    """A validation error indicating the value being processed is invalid due
    to its type."""
