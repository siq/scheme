from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import date, datetime, time, timedelta
from unittest2 import TestCase
from uuid import uuid4

from scheme.exceptions import *
from scheme.fields import *
from scheme.surrogate import surrogate
from scheme.timezone import LOCAL, UTC

def construct_now(delta=None):
    now = datetime.now().replace(microsecond=0, tzinfo=LOCAL)
    if delta is not None:
        now += timedelta(seconds=delta)
    now_text = now.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    return now, now_text

def construct_today(delta=None):
    today = date.today()
    if delta is not None:
        today += timedelta(days=delta)
    return today, today.strftime('%Y-%m-%d')

def should_fail(callable, *args, **params):
    try:
        callable(*args, **params)
    except Exception, exception:
        return exception
    else:
        assert False, 'exception should be raised'

class attrmap(object):
    def __init__(self, field, value, key=None):
        self.__dict__.update(value)

    @classmethod
    def extract(self, field, value):
        return value.__dict__

class listwrapper(object):
    def __init__(self, field, value, key=None):
        self.list = value

    @classmethod
    def extract(self, field, value):
        return value.list

class valuewrapper(object):
    def __init__(self, field, value, key=None):
        self.value = value

    @classmethod
    def extract(self, field, value):
        return value.value

INVALID_ERROR = ValidationError({'token': 'invalid'})
NULL_ERROR = ValidationError({'token': 'nonnull'})
REQUIRED_ERROR = ValidationError({'token': 'required'})
UNKNOWN_ERROR = ValidationError({'token': 'unknown'})

class FieldTestCase(TestCase):
    def assert_processed(self, field, *tests):
        for test in tests:
            if isinstance(test, tuple):
                unserialized, serialized = test
            else:
                unserialized, serialized = (test, test)
            self.assertEqual(field.process(unserialized, INCOMING), unserialized)
            self.assertEqual(field.process(unserialized, OUTGOING), unserialized)
            self.assertEqual(field.process(serialized, INCOMING, True), unserialized)
            self.assertEqual(field.process(unserialized, OUTGOING, True), serialized)

    def assert_not_processed(self, field, expected, *tests):
        if isinstance(expected, basestring):
            expected = ValidationError().append({'token': expected})
        for test in tests:
            if not isinstance(test, tuple):
                test = (test, test)

            error = should_fail(field.process, test[0], INCOMING)
            failed, reason = self.compare_structural_errors(expected, error)
            assert failed, reason

            for value, phase in zip(test, (OUTGOING, INCOMING)):
                error = should_fail(field.process, value, phase, True)
                failed, reason = self.compare_structural_errors(expected, error)
                assert failed, reason

    def assert_interpolated(self, field, *tests, **params):
        for test in tests:
            if isinstance(test, tuple):
                left, right = test
            else:
                left, right = test, test
            self.assertEqual(field.interpolate(left, params), right)

    def compare_structural_errors(self, expected, received):
        if not isinstance(received, type(expected)):
            return False, 'received error not same type as expected error'
        if not self.compare_errors(expected, received):
            return False, 'nonstructural errors do not match'
        if not self.compare_structure(expected, received):
            return False, 'structural errors do not match'
        return True, ''

    def compare_errors(self, expected, received):
        if expected.errors:
            if len(received.errors) != len(expected.errors):
                return False
            for expected_error, received_error in zip(expected.errors, received.errors):
                if received_error.get('token') != expected_error['token']:
                    return False
        elif received.errors:
            return False
        return True

    def compare_structure(self, expected, received):
        expected, received = expected.structure, received.structure
        if isinstance(expected, list):
            if not isinstance(received, list):
                return False
            elif len(received) != len(expected):
                return False
            for expected_item, received_item in zip(expected, received):
                if isinstance(expected_item, StructuralError):
                    if not isinstance(received_item, StructuralError):
                        return False
                    elif expected_item.structure is not None:
                        if not self.compare_structure(expected_item, received_item):
                            return False
                    elif expected_item.errors is not None:
                        if not self.compare_errors(expected_item, received_item):
                            return False
                elif received_item != expected_item:
                    return False
        elif isinstance(expected, dict):
            if not isinstance(received, dict):
                return False
            elif len(received) != len(expected):
                return False
            for expected_pair, received_pair in zip(sorted(expected.items()), sorted(received.items())):
                if expected_pair[0] != received_pair[0]:
                    return False
                expected_value, received_value = expected_pair[1], received_pair[1]
                if isinstance(expected_value, StructuralError):
                    if not isinstance(received_value, StructuralError):
                        return False
                    elif expected_value.structure is not None:
                        if not self.compare_structure(expected_value, received_value):
                            return False
                    elif expected_value.errors is not None:
                        if not self.compare_errors(expected_value, received_value):
                            return False
                elif received_value != expected_value:
                    return False
        elif received:
            return False
        return True

class TestField(FieldTestCase):
    def test_nulls(self):
        field = Field()
        for phase in (INCOMING, OUTGOING):
            self.assert_processed(field, phase)

        field = Field(nonnull=True)
        self.assert_not_processed(field, 'nonnull', None)

    def test_filtering(self):
        field = Field()
        self.assertIs(field.filter(), field)
        self.assertIs(field.filter(exclusive=True), None)
        self.assertIs(field.filter(readonly=True), field)
        self.assertIs(field.filter(readonly=False), field)
        self.assertIs(field.filter(exclusive=True, readonly=True), None)
        self.assertIs(field.filter(exclusive=True, readonly=False), field)

        field = Field(readonly=True)
        self.assertIs(field.filter(), field)
        self.assertIs(field.filter(exclusive=True), None)
        self.assertIs(field.filter(readonly=True), field)
        self.assertIs(field.filter(readonly=False), None)
        self.assertIs(field.filter(exclusive=True, readonly=True), field)
        self.assertIs(field.filter(exclusive=True, readonly=False), None)

    def test_defaults(self):
        field = Field(default=True)
        assert field.get_default() is True

        field = Field(default=datetime.now)
        assert isinstance(field.get_default(), datetime)

    def test_extraction(self):
        field = Field()
        self.assertEqual(field.extract(1), 1)

    def test_instantiate(self):
        field = Field()
        self.assertEqual(field.instantiate(1), 1)

    def test_interpolation(self):
        field = Field()
        self.assertEqual(field.interpolate(None, {}), None)

class TestBinary(FieldTestCase):
    def test_processing(self):
        field = Binary()
        self.assert_processed(field, None, '',
            ('testing', 'dGVzdGluZw=='),
            ('\x00\x00', 'AAA='))
        self.assert_not_processed(field, 'invalid', True, 1.0)

    def test_min_length(self):
        field = Binary(min_length=2)
        self.assert_processed(field, ('\x00\x00', 'AAA='), ('\x00\x00\x00', 'AAAA'))
        self.assert_not_processed(field, 'min_length', ('', ''), ('\x00', 'AA=='))

    def test_max_length(self):
        field = Binary(max_length=1)
        self.assert_processed(field, ('', ''), ('\x00', 'AA=='))
        self.assert_not_processed(field, 'max_length', ('\x00\x00', 'AAA='),
            ('\x00\x00\x00', 'AAAA'))

    def test_interpolation(self):
        field = Binary()
        self.assertEqual(field.interpolate(None, {}), None)
        self.assertEqual(field.interpolate('\x00\x01', {}), '\x00\x01')
        self.assertEqual(field.interpolate('${value}', {'value': '\x00\x01'}), '\x00\x01')

class TestBoolean(FieldTestCase):
    def test_processing(self):
        field = Boolean()
        self.assert_processed(field, None, True, False)
        self.assert_not_processed(field, 'invalid', '')

    def test_constants(self):
        field = Boolean(constant=True)
        self.assert_processed(field, True)
        self.assert_not_processed(field, 'invalid', False, '')

    def test_interpolation(self):
        field = Boolean()
        self.assert_interpolated(field, None, True, False)
        self.assert_interpolated(field, ('${value}', True), value=True)

class TestDate(FieldTestCase):
    def test_processing(self):
        field = Date()
        self.assert_processed(field, None, construct_today())
        self.assert_not_processed(field, 'invalid', ('', ''))

    def test_minimum(self):
        today, today_text = construct_today()
        for field in (Date(minimum=today), Date(minimum=date.today)):
            self.assert_processed(field, (today, today_text), construct_today(+1))
            self.assert_not_processed(field, 'minimum', construct_today(-1))

    def test_maximum(self):
        today, today_text = construct_today()
        for field in (Date(maximum=today), Date(maximum=date.today)):
            self.assert_processed(field, (today, today_text), construct_today(-1))
            self.assert_not_processed(field, 'maximum', construct_today(+1))

    def test_interpolation(self):
        field = Date()
        today = date.today()

        self.assert_interpolated(field, None, today)
        self.assert_interpolated(field, ('${value}', today), value=today)

class TestDateTime(FieldTestCase):
    def test_processing(self):
        field = DateTime()
        self.assert_not_processed(field, 'invalid', True)
        self.assert_processed(field, None)

        now = datetime.now().replace(microsecond=0)
        now_local = now.replace(tzinfo=LOCAL)
        now_utc = now_local.astimezone(UTC)
        now_text = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

        self.assertEqual(field.process(now_text, INCOMING, True), now_local)
        self.assertEqual(field.process(now, OUTGOING, True), now_text)
        self.assertEqual(field.process(now_local, OUTGOING, True), now_text)
        self.assertEqual(field.process(now_utc, OUTGOING, True), now_text)

    def test_minimum(self):
        now, now_text = construct_now()
        for field in (DateTime(minimum=now), DateTime(minimum=lambda: construct_now()[0])):
            self.assert_processed(field, (now, now_text), construct_now(+1))
            self.assert_not_processed(field, 'minimum', construct_now(-1))

    def test_maximum(self):
        now, now_text = construct_now()
        for field in (DateTime(maximum=now), DateTime(maximum=lambda: construct_now()[0])):
            self.assert_processed(field, (now, now_text), construct_now(-1))
            self.assert_not_processed(field, 'maximum', construct_now(+1))

    def test_interpolation(self):
        field = DateTime()
        now = datetime.now()

        self.assert_interpolated(field, None, now)
        self.assert_interpolated(field, ('${value}', now), value=now)

class TestDefinition(FieldTestCase):
    def test_processing(self):
        field = Definition()
        self.assert_not_processed(field, 'invalid', True)
        self.assert_processed(field, None)

    def test_interpolation(self):
        field = Definition()
        value = Field()

        self.assert_interpolated(field, None, value)
        self.assert_interpolated(field, ('${value}', value), value=value)

class TestEnumeration(FieldTestCase):
    def test_specification(self):
        self.assertRaises(SchemeError, lambda:Enumeration([datetime.now()]))
        self.assertRaises(SchemeError, lambda:Enumeration(True))

    def test_processing(self):
        values = ['alpha', 1, True]
        field = Enumeration(values)

        self.assert_processed(field, None, *values)
        self.assert_not_processed(field, 'invalid', 'beta', 2, False)

    def test_ignored_values(self):
        field = Enumeration('alpha beta', ignored_values='gamma delta')
        self.assert_processed(field, None, 'alpha', 'beta')
        self.assertEqual(field.process('gamma', INCOMING, True), None)
        self.assertEqual(field.process('gamma', INCOMING, False), None)
        self.assertEqual(field.process('delta', INCOMING, True), None)
        self.assertEqual(field.process('delta', INCOMING, False), None)
        self.assert_not_processed(field, 'invalid', 'epsilon', 'iota')

    def test_interpolation(self):
        field = Enumeration(['alpha', 'beta'])
        self.assert_interpolated(field, None, 'alpha', 'beta')
        self.assert_interpolated(field, ('${value}', 'alpha'), value='alpha')

class TestError(FieldTestCase):
    def test_processing(self):
        field = Error()
        error = {'token': 'invalid', 'message': 'testing'}

        serialized = field.process(ValidationError(error), OUTGOING, True)
        self.assertEqual(serialized, ([error], None))

        unserialized = field.process(serialized, INCOMING, True)
        self.assertIsInstance(unserialized, StructuralError)
        self.assertEqual(unserialized.errors[0], error)

class TestFloat(FieldTestCase):
    def test_specification(self):
        self.assertRaises(SchemeError, lambda:Float(minimum=True))
        self.assertRaises(SchemeError, lambda:Float(maximum=True))

    def test_processing(self):
        field = Float()
        self.assert_processed(field, None, -1.0, -0.1, 0.0, 0.1, 1.0)
        self.assert_not_processed(field, 'invalid', '')

    def test_minimum(self):
        field = Float(minimum=0.0)
        self.assert_processed(field, 0.0, 0.1, 1.0)
        self.assert_not_processed(field, 'minimum', -1.0, -0.1)

    def test_maximum(self):
        field = Float(maximum=0.0)
        self.assert_processed(field, -1.0, -0.1, 0.0)
        self.assert_not_processed(field, 'maximum', 0.1, 1.0)

    def test_minimum_maximum(self):
        field = Float(minimum=-1.0, maximum=1.0)
        self.assert_processed(field, -1.0, -0.5, 0.0, 0.5, 1.0)
        self.assert_not_processed(field, 'minimum', -2.0, -1.1)
        self.assert_not_processed(field, 'maximum', 1.1, 2.0)

    def test_constants(self):
        field = Float(constant=1.1)
        self.assert_processed(field, 1.1)
        self.assert_not_processed(field, 'invalid', 1.0, 1.2, '')

    def test_interpolation(self):
        field = Float()
        self.assert_interpolated(field, None, 1.0, (1, 1.0), (1L, 1.0))
        self.assert_interpolated(field, ('${value}', 1.0), ('${value + 1}', 2.0),
            value=1.0)

class TestInteger(FieldTestCase):
    def test_specification(self):
        self.assertRaises(SchemeError, lambda:Integer(minimum='bad'))
        self.assertRaises(SchemeError, lambda:Integer(maximum='bad'))

    def test_processing(self):
        field = Integer()
        self.assert_processed(field, None, -1, 0, 1)
        self.assert_not_processed(field, 'invalid', '')

    def test_minimum(self):
        field = Integer(minimum=0)
        self.assert_processed(field, 0, 1)
        self.assert_not_processed(field, 'minimum', -1)

    def test_maximum(self):
        field = Integer(maximum=0)
        self.assert_processed(field, -1, 0)
        self.assert_not_processed(field, 'maximum', 1)

    def test_minimum_maximum(self):
        field = Integer(minimum=-2, maximum=2)
        self.assert_processed(field, -2, -1, 0, 1, 2)
        self.assert_not_processed(field, 'minimum', -4, -3)
        self.assert_not_processed(field, 'maximum', 4, 5)

    def test_constants(self):
        field = Integer(constant=1)
        self.assert_processed(field, 1)
        self.assert_not_processed(field, 'invalid', 0, 2, '')

    def test_interpolation(self):
        field = Integer()
        self.assert_interpolated(field, None, 1, 1L, (1.0, 1))
        self.assert_interpolated(field, ('${value}', 1), ('${value + 1}', 2), value=1)

class TestMap(FieldTestCase):
    def test_specification(self):
        self.assertRaises(SchemeError, lambda:Map(True))

    def test_processing(self):
        field = Map(Integer())

        self.assert_processed(field, None)
        for valid in [{}, {'a': 1}, {'a': 1, 'b': 2}, {'a': None}]:
            self.assert_processed(field, (valid, valid))

        expected_error = ValidationError(structure={'a': INVALID_ERROR, 'b': 2})
        self.assert_not_processed(field, expected_error, {'a': '', 'b': 2})

    def test_null_values(self):
        field = Map(Integer(nonnull=True))
        self.assert_processed(field, {}, {'a': 1})

        expected_error = ValidationError(structure={'a': NULL_ERROR, 'b': 2})
        self.assert_not_processed(field, expected_error, {'a': None, 'b': 2})

    def test_required_keys(self):
        field = Map(Integer(), required_keys=('a',))
        self.assert_processed(field, {'a': 1})

        expected_error = ValidationError(structure={'a': REQUIRED_ERROR})
        self.assert_not_processed(field, expected_error, {})

    def test_explicit_key(self):
        field = Map(Integer(), key=Integer())
        self.assert_processed(field, {1: 1})

    def test_undefined_fields(self):
        f = Undefined(Integer())
        field = Map(f)
        self.assert_processed(field, None, {}, {'a': 1}, {'a': 1, 'b': 2})

        f = Undefined()
        field = Map(f)
        f.define(Integer())
        self.assert_processed(field, None, {}, {'a': 1}, {'a': 1, 'b': 2})

    def test_naive_extraction(self):
        field = Map(Integer())
        value = {'a': 1, 'b': 2}

        extracted = field.extract(value)
        self.assertIsInstance(extracted, dict)
        self.assertIsNot(value, extracted)
        self.assertEqual(value, extracted)

        field = Map(Map(Integer()))
        value = {'a': {'a': 1}, 'b': {'b': 2}}

        extracted = field.extract(value)
        self.assertIsNot(value, extracted)
        self.assertIsNot(value['a'], extracted['a'])
        self.assertEqual(value, extracted)

    def test_mediated_extraction(self):
        field = Map(Integer(), extractor=attrmap.extract)
        value = {'a': 1, 'b': 2}
        extracted = field.extract(attrmap(None, value))

        self.assertIsInstance(extracted, dict)
        self.assertIsNot(extracted, value)
        self.assertEqual(extracted, value)

        field = Map(Integer(extractor=valuewrapper.extract), extractor=attrmap.extract)
        value = attrmap(None, {'a': valuewrapper(None, 1), 'b': valuewrapper(None, 2)})
        extracted = field.extract(value)

        self.assertIsInstance(extracted, dict)
        self.assertEqual(extracted, {'a': 1, 'b': 2})

        field = Map(Integer(extractor=valuewrapper.extract))
        value = {'a': valuewrapper(None, 1), 'b': valuewrapper(None, 2)}
        extracted = field.extract(value)

        self.assertIsInstance(extracted, dict)
        self.assertEqual(extracted, {'a': 1, 'b': 2})

    def test_instantiation(self):
        field = Map(Integer(), instantiator=attrmap)
        instance = field.instantiate({'a': 1, 'b': 2})

        self.assertIsInstance(instance, attrmap)
        self.assertEqual(instance.a, 1)
        self.assertEqual(instance.b, 2)

        instance = field.instantiate({})
        self.assertIsInstance(instance, attrmap)

        field = Map(Integer(instantiator=valuewrapper), instantiator=attrmap)
        instance = field.instantiate({'a': 1, 'b': 2})

        self.assertIsInstance(instance, attrmap)
        self.assertIsInstance(instance.a, valuewrapper)
        self.assertEqual(instance.a.value, 1)

    def test_interpolation(self):
        field = Map(Integer())
        self.assert_interpolated(field, None, {}, ({'alpha': 1, 'beta': 2},
            {'alpha': 1, 'beta': 2}))
        self.assert_interpolated(field, ({'alpha': '${alpha}', 'beta': '${beta}'},
            {'alpha': 1, 'beta': 2}), alpha=1, beta=2)
        self.assert_interpolated(field, ('${value}', {'alpha': 1, 'beta': 2}),
            value={'alpha': '${alpha}', 'beta': '${beta}'}, alpha=1, beta=2)

class TestSequence(FieldTestCase):
    def generate_sequences(self):
        today, today_text = construct_today()
        yesterday, yesterday_text = construct_today(-1)
        tomorrow, tomorrow_text = construct_today(+1)
        return ([yesterday, today, tomorrow],
            [yesterday_text, today_text, tomorrow_text])

    def test_specification(self):
        self.assertRaises(SchemeError, lambda:Sequence(True))
        self.assertRaises(SchemeError, lambda:Sequence(Integer(), min_length='bad'))
        self.assertRaises(SchemeError, lambda:Sequence(Integer(), max_length='bad'))

    def test_processing(self):
        field = Sequence(Date())
        self.assert_processed(field, None, self.generate_sequences())
        self.assert_not_processed(field, 'invalid', True)

        field = Sequence(Integer())
        self.assert_processed(field, [1, 2, 3], [1, None, 3])
        
        expected_error = ValidationError(structure=[1, INVALID_ERROR, 3])
        self.assert_not_processed(field, expected_error, [1, '', 3])

    def test_null_values(self):
        field = Sequence(Integer(nonnull=True))
        self.assert_processed(field, [], [1, 2, 3])
        
        expected_error = ValidationError(structure=[1, NULL_ERROR, 3])
        self.assert_not_processed(field, expected_error, [1, None, 3])

    def test_min_length(self):
        field = Sequence(Date(), min_length=2)
        a, b = self.generate_sequences()

        self.assert_processed(field, (a, b), (a[:2], b[:2]))
        self.assert_not_processed(field, 'min_length', (a[:1], b[:1]))

    def test_max_length(self):
        field = Sequence(Date(), max_length=2)
        a, b = self.generate_sequences()

        self.assert_processed(field, (a[:1], b[:1]), (a[:2], b[:2]))
        self.assert_not_processed(field, 'max_length', (a, b))

    def test_unique(self):
        field = Sequence(Integer(), unique=True)
        self.assert_processed(field, [], [1], [1, 2])
        self.assert_not_processed(field, 'duplicate', [1, 1])

    def test_undefined_fields(self):
        f = Undefined(Integer())
        field = Sequence(f)
        self.assert_processed(field, None, [], [1], [1, 2])

        f = Undefined()
        field = Sequence(f)
        f.define(Integer())
        self.assert_processed(field, None, [], [1], [1, 2])
    
    def test_naive_extraction(self):
        field = Sequence(Integer())
        value = [1, 2, 3]

        extracted = field.extract(value)
        self.assertIsNot(value, extracted)
        self.assertEqual(value, extracted)

        field = Sequence(Sequence(Integer()))
        value = [[1], [2], [3]]

        extracted = field.extract(value)
        self.assertIsNot(value, extracted)
        self.assertEqual(value, extracted)
        for i in (0, 1, 2):
            self.assertIsNot(value[i], extracted[i])

    def test_mediated_extraction(self):
        field = Sequence(Integer(), extractor=listwrapper.extract)
        value = listwrapper(None, [1, 2])
        extracted = field.extract(value)

        self.assertIsInstance(extracted, list)
        self.assertEqual(extracted, [1, 2])

        field = Sequence(Integer(extractor=valuewrapper.extract), extractor=listwrapper.extract)
        value = listwrapper(None, [valuewrapper(None, 1), valuewrapper(None, 2)])
        extracted = field.extract(value)

        self.assertIsInstance(extracted, list)
        self.assertEqual(extracted, [1, 2])

        field = Sequence(Integer(extractor=valuewrapper.extract))
        value = [valuewrapper(None, 1), valuewrapper(None, 2)]
        extracted = field.extract(value)

        self.assertIsInstance(extracted, list)
        self.assertEqual(extracted, [1, 2])

    def test_instantiation(self):
        field = Sequence(Integer(), instantiator=listwrapper)
        instance = field.instantiate([1, 2])

        self.assertIsInstance(instance, listwrapper)
        self.assertEqual(instance.list, [1, 2])

        instance = field.instantiate([])
        self.assertIsInstance(instance, listwrapper)
        self.assertEqual(instance.list, [])

        field = Sequence(Integer(instantiator=valuewrapper), instantiator=listwrapper)
        instance = field.instantiate([1, 2])

        self.assertIsInstance(instance, listwrapper)
        self.assertIsInstance(instance.list[0], valuewrapper)
        self.assertEqual(instance.list[0].value, 1)
        self.assertIsInstance(instance.list[1], valuewrapper)
        self.assertEqual(instance.list[1].value, 2)

        field = Sequence(Integer(instantiator=valuewrapper))
        instance = field.instantiate([1, 2])

        self.assertIsInstance(instance, list)
        self.assertIsInstance(instance[0], valuewrapper)
        self.assertEqual(instance[0].value, 1)
        self.assertIsInstance(instance[1], valuewrapper)
        self.assertEqual(instance[1].value, 2)

    def test_interpolation(self):
        field = Sequence(Integer())
        self.assert_interpolated(field, None, [])
        self.assert_interpolated(field, (['${alpha}', '${beta}'], [1, 2]), alpha=1, beta=2)
        self.assert_interpolated(field, ([1, 2], [1, 2]))
        self.assert_interpolated(field, ('${value}', [1, 2]), value=['${alpha}', '${beta}'],
            alpha=1, beta=2)

class TestStructure(FieldTestCase):
    class ExtractionTarget(object):
        def __init__(self, **params):
            self.__dict__.update(**params)

    def test_specification(self):
        self.assertRaises(SchemeError, lambda: Structure(True))
        self.assertRaises(SchemeError, lambda: Structure({'a': True}))

    def test_processing(self):
        field = Structure({})
        self.assert_processed(field, None, {})
        self.assert_not_processed(field, 'invalid', True)

        field = Structure({'a': Integer(), 'b': Text(), 'c': Boolean()})
        self.assert_processed(field, None, {}, {'a': None}, {'a': 1}, {'a': 1, 'b': None}, 
            {'a': 1, 'b': 'b', 'c': True})

        expected_error = ValidationError(structure={'a': INVALID_ERROR, 'b': 'b', 'c': True})
        self.assert_not_processed(field, expected_error, {'a': '', 'b': 'b', 'c': True})

    def test_required_values(self):
        field = Structure({'a': Integer(required=True), 'b': Text()})
        self.assert_processed(field, {'a': 1}, {'a': 1, 'b': 'b'}, {'a': None})

        expected_error = ValidationError(structure={'a': REQUIRED_ERROR, 'b': 'b'})
        self.assert_not_processed(field, expected_error, {'b': 'b'})

    def test_ignore_null_values(self):
        field = Structure({'a': Integer()})
        self.assertEqual(field.process({'a': None}, INCOMING), {'a': None})

        field = Structure({'a': Integer(ignore_null=True)})
        self.assertEqual(field.process({'a': None}, INCOMING), {})

    def test_unknown_values(self):
        field = Structure({'a': Integer()})
        self.assert_processed(field, {}, {'a': 1})

        expected_error = ValidationError(structure={'a': 1, 'z': ValidationError({'token': 'unknown'})})
        self.assert_not_processed(field, expected_error, {'a': 1, 'z': True})

    def test_default_values(self):
        field = Structure({'a': Integer(default=2)})
        self.assertEqual(field.process({'a': 1}, INCOMING), {'a': 1})
        self.assertEqual(field.process({}, INCOMING), {'a': 2})
        self.assertEqual(field.process({'a': 1}, OUTGOING), {'a': 1})
        self.assertEqual(field.process({}, OUTGOING), {})

    def test_undefined_fields(self):
        f = Undefined(Integer())
        field = Structure({'a': f})
        self.assert_processed(field, None, {}, {'a': 1})

        f = Undefined()
        field = Structure({'a': f})
        f.define(Integer())
        self.assert_processed(field, None, {}, {'a': 1})

    def test_polymorphism(self):
        field = Structure({
            'alpha': {'a': Integer()},
            'beta': {'b': Integer()},
        }, polymorphic_on=Text(name='identity'))

        self.assert_processed(field, None)
        self.assert_not_processed(field, 'required', {})

        self.assert_processed(field, {'identity': 'alpha', 'a': 1},
            {'identity': 'beta', 'b': 2})
        self.assert_not_processed(field, 'unrecognized', {'identity': 'gamma'})

        expected_error = ValidationError(structure={'identity': 'alpha', 'b': UNKNOWN_ERROR})
        self.assert_not_processed(field, expected_error, {'identity': 'alpha', 'b': 2})

    def test_polymorphic_on_autogeneration(self):
        field = Structure({
            'alpha': {'a': Integer()},
            'beta': {'b': Integer()},
        }, polymorphic_on='identity')

        self.assert_processed(field, None)
        self.assert_not_processed(field, 'required', {})

        self.assert_processed(field, {'identity': 'alpha', 'a': 1},
            {'identity': 'beta', 'b': 2})
        #self.assert_not_processed(field, 'unrecognized', {'identity': 'gamma'})

        expected_error = ValidationError(structure={'identity': 'alpha', 'b': UNKNOWN_ERROR})
        self.assert_not_processed(field, expected_error, {'identity': 'alpha', 'b': 2})

    def test_polymorphism_with_common_fields(self):
        field = Structure({
            '*': {'n': Integer()},
            'alpha': {'a': Integer()},
            'beta': {'b': Integer()},
        }, polymorphic_on='identity')

        self.assert_processed(field, None)
        self.assert_processed(field, {'identity': 'alpha', 'a': 1, 'n': 3},
            {'identity': 'beta', 'b': 2, 'n': 3})

    def test_naive_extraction(self):
        field = Structure({'a': Integer()})
        value = {'a': 1}

        extracted = field.extract(value)
        self.assertIsNot(value, extracted)
        self.assertEqual(value, extracted)

        extracted = field.extract({'a': 1, 'b': 2})
        self.assertEqual(value, extracted)

        extracted = field.extract({})
        self.assertEqual(extracted, {})

        field = Structure({'a': Structure({'a': Integer()})})
        value = {'a': {'a': 1}}

        extracted = field.extract(value)
        self.assertIsNot(value, extracted)
        self.assertIsNot(value['a'], extracted['a'])
        self.assertEqual(value, extracted)

        field = Structure({
            'alpha': {'a': Integer()},
            'beta': {'b': Integer()},
        }, polymorphic_on=Text(name='identity'))

        for value in ({'identity': 'alpha', 'a': 1}, {'identity': 'beta', 'b': 2}):
            extracted = field.extract(value)
            self.assertIsNot(extracted, value)
            self.assertEqual(extracted, value)

    def test_mediated_extraction(self):
        field = Structure({'a': Integer(), 'b': Text()}, extractor=attrmap.extract)
        value = attrmap(None, {'a': 1, 'b': 'test'})
        extracted = field.extract(value)

        self.assertIsInstance(extracted, dict)
        self.assertEqual(extracted, {'a': 1, 'b': 'test'})

        field = Structure({'a': Integer(extractor=valuewrapper.extract), 'b': Text()}, extractor=attrmap.extract)
        value = attrmap(None, {'a': valuewrapper(None, 1), 'b': 'test'})
        extracted = field.extract(value)

        self.assertIsInstance(extracted, dict)
        self.assertEqual(extracted, {'a': 1, 'b': 'test'})

        field = Structure({'a': Integer(), 'b': Text(extractor=valuewrapper.extract)})
        value = {'a': 1, 'b': valuewrapper(None, 'test')}
        extracted = field.extract(value)

        self.assertIsInstance(extracted, dict)
        self.assertEqual(extracted, {'a': 1, 'b': 'test'})

    def test_object_extraction(self):
        field = Structure({'a': Integer(), 'b': Text()})
        target = self.ExtractionTarget(a=1, b='b', c='c', d=4)
        extracted = field.extract(target, strict=False)

        self.assertIsInstance(extracted, dict)
        self.assertEqual(extracted, {'a': 1, 'b': 'b'})

        target = self.ExtractionTarget(a=1, c='c')
        extracted = field.extract(target, strict=False)

        self.assertIsInstance(extracted, dict)
        self.assertEqual(extracted, {'a': 1})

    def test_instantiation(self):
        field = Structure({'a': Integer(), 'b': Text()}, instantiator=attrmap)
        instance = field.instantiate({'a': 1, 'b': 'test'})

        self.assertIsInstance(instance, attrmap)
        self.assertEqual(instance.a, 1)
        self.assertEqual(instance.b, 'test')

        instance = field.instantiate({})
        self.assertIsInstance(instance, attrmap)

        field = Structure({'a': Integer(instantiator=valuewrapper), 'b': Text()}, instantiator=attrmap)
        instance = field.instantiate({'a': 1, 'b': 'test'})

        self.assertIsInstance(instance, attrmap)
        self.assertIsInstance(instance.a, valuewrapper)
        self.assertEqual(instance.a.value, 1)
        self.assertEqual(instance.b, 'test')

        field = Structure({'a': Integer(), 'b': Text(instantiator=valuewrapper)})
        instance = field.instantiate({'a': 1, 'b': 'test'})

        self.assertIsInstance(instance, dict)
        self.assertIsInstance(instance['b'], valuewrapper)
        self.assertEqual(instance['a'], 1)
        self.assertEqual(instance['b'].value, 'test')

        field = Structure({
            'alpha': {'a': Integer()},
            'beta': {'b': Integer()},
        }, polymorphic_on=Text(name='identity'), instantiator=attrmap)

        for value in ({'identity': 'alpha', 'a': 1}, {'identity': 'beta', 'b': 2}):
            instance = field.instantiate(value)
            self.assertIsInstance(instance, attrmap)
            self.assertEqual(instance.identity, value['identity'])

    def test_interpolation(self):
        field = Structure({'alpha': Integer(), 'beta': Text()})
        self.assert_interpolated(field, None, {}, ({'alpha': 1, 'beta': 'two'},
            {'alpha': 1, 'beta': 'two'}))
        self.assert_interpolated(field, ({'alpha': '${alpha}', 'beta': '${beta}'},
            {'alpha': 1, 'beta': 'two'}), alpha=1, beta='two')
        self.assert_interpolated(field, ('${value}', {'alpha': 1, 'beta': 'two'}),
            value={'alpha': '${alpha}', 'beta': '${beta}'}, alpha=1, beta='two')

class surrogate_subclass(surrogate):
    schema = Structure({
        'id': Text(nonempty=True),
        'value': Integer(),
    })

    def describe(self):
        return '%(id)s:%(value)s' % self

class TestSurrogate(FieldTestCase):
    def test_naive_processing(self):
        field = Surrogate()
        self.assert_processed(field, None)
        
        instance = field.process({'a': 1}, INCOMING, True)
        self.assertIsInstance(instance, surrogate)
        self.assertEqual(instance, {'a': 1})

        value = field.process(instance, OUTGOING, True)
        self.assertNotIsInstance(value, surrogate)
        self.assertIsInstance(value, dict)
        self.assertEqual(value, {'_': 'scheme.surrogate.surrogate', 'a': 1})

    def test_schema_processing(self):
        field = Surrogate()
        value = {'_': surrogate_subclass.surrogate, 'id': 'alpha', 'value': 1}

        instance = field.process(value, INCOMING, True)
        self.assertIsInstance(instance, surrogate_subclass)
        self.assertEqual(instance, {'id': 'alpha', 'value': 1})
        self.assertEqual(instance.describe(), 'alpha:1')

        serialized_value = field.process(instance, OUTGOING, True)
        self.assertNotIsInstance(serialized_value, surrogate_subclass)
        self.assertIsInstance(serialized_value, dict)
        self.assertEqual(serialized_value, value)

        value = {'_': surrogate_subclass.surrogate, 'value': 1}
        self.assertRaises(ValidationError, lambda:field.process(value, INCOMING, True))

    def test_surrogates_validation(self):
        field = Surrogate(surrogates=surrogate_subclass.surrogate)

    def test_interpolation(self):
        field = Surrogate()
        value = surrogate({'a': 1})

        self.assert_interpolated(field, None, value)
        self.assert_interpolated(field, ('${value}', value), value=value)

class TestText(FieldTestCase):
    def test_specification(self):
        self.assertRaises(SchemeError, lambda:Text(min_length='bad'))
        self.assertRaises(SchemeError, lambda:Text(max_length='bad'))

    def test_processing(self):
        field = Text()
        self.assert_processed(field, None, '', 'testing')
        self.assert_not_processed(field, 4)

    def test_strip(self):
        field = Text()
        self.assertEqual(field.process('  '), '')

        field = Text(strip=False)
        self.assertEqual(field.process('  '), '  ')

    def test_pattern(self):
        field = Text(pattern=r'^[abc]*$')
        self.assert_processed(field, '', 'a', 'ab', 'bc', 'abc', 'aabbcc')
        self.assert_not_processed(field, 'pattern', 'q', 'aq')

    def test_min_length(self):
        field = Text(min_length=2)
        self.assert_processed(field, 'aa', 'aaa')
        self.assert_not_processed(field, 'min_length', '', 'a', '    ')

        field = Text(min_length=2, strip=False)
        self.assert_processed(field, 'aa', 'aaa', '   ')
        self.assert_not_processed(field, 'min_length', '', 'a')

    def test_max_length(self):
        field = Text(max_length=2)
        self.assert_processed(field, '', 'a', 'aa')
        self.assert_not_processed(field, 'max_length', 'aaa')

    def test_constants(self):
        field = Text(constant='a')
        self.assert_processed(field, 'a')
        self.assert_not_processed(field, 'invalid', '', 'b', 1)

    def test_interpolation(self):
        field = Text()
        self.assert_interpolated(field, None, '', 'testing')
        self.assert_interpolated(field, ('${alpha}', 'one'), ('${beta}', 'two'),
            ('${alpha}, ${beta}', 'one, two'), alpha='one', beta='two')

class TestTime(FieldTestCase):
    def construct(self, delta=None):
        now = datetime.now().time().replace(second=30, microsecond=0)
        if delta is not None:
            now = now.replace(second=(30 + delta))
        return now, now.strftime('%H:%M:%S')

    def test_processing(self):
        field = Time()
        self.assert_processed(field, None, self.construct())
        self.assert_not_processed(field, 'invalid', '')

    def test_minimum(self):
        now, now_text = self.construct()
        for field in (Time(minimum=now), Time(minimum=lambda: self.construct()[0])):
            self.assert_processed(field, (now, now_text), self.construct(+1))
            self.assert_not_processed(field, 'minimum', self.construct(-1))

    def test_maximum(self):
        now, now_text = self.construct()
        for field in (Time(maximum=now), Time(maximum=lambda: self.construct()[0])):
            self.assert_processed(field, (now, now_text), self.construct(-1))
            self.assert_not_processed(field, 'maximum', self.construct(+1))

    def test_interpolation(self):
        field = Time()
        now, now_text = self.construct()

        self.assert_interpolated(field, None, now)
        self.assert_interpolated(field, ('${value}', now), value=now)

class TestToken(FieldTestCase):
    def test_processing(self):
        field = Token()
        self.assert_processed(field, None, 'good', 'good.good', 'good-good',
            'good.good-good', 'good:good', 'good:good:good', 'good.good:good.good',
            'good-good:good-good', 'good.good-good:good.good-good', str(uuid4()))
        self.assert_not_processed(field, 'invalid', True, 2, '', 'bad.', '.bad',
            '-bad', 'bad-', ':bad', 'bad:')

    def test_segments(self):
        field = Token(segments=1)
        self.assert_processed(field, 'good', 'good.good', 'good-good', 'good.good-good')
        self.assert_not_processed(field, 'invalid', 'bad:bad', 'bad:bad:bad')

        field = Token(segments=2)
        self.assert_processed(field, 'good:good', 'good.good:good', 'good:good-good')
        self.assert_not_processed(field, 'invalid', 'bad', 'bad.bad', 'bad-bad',
            'bad:bad:bad')

class TestTuple(FieldTestCase):
    def test_specification(self):
        self.assertRaises(SchemeError, lambda:Tuple(True))

    def test_processing(self):
        field = Tuple((Text(), Boolean(), Integer()))
        self.assert_not_processed(field, 'invalid', True)

        self.assert_processed(field, None)
        for valid in [('test', True, 1), ('test', None, 1)]:
            self.assert_processed(field, (valid, valid))

        self.assert_not_processed(field, 'length', ((), ()))

        expected_error = ValidationError(structure=['test', INVALID_ERROR, 1])
        self.assert_not_processed(field, expected_error, (('test', 'a', 1), ('test', 'a', 1)))

    def test_null_values(self):
        field = Tuple((Text(nonnull=True), Integer()))
        for valid in [('test', 1), ('test', None)]:
            self.assert_processed(field, (valid, valid))

        expected_error = ValidationError(structure=[NULL_ERROR, None])
        self.assert_not_processed(field, expected_error, ((None, None), (None, None)))

    def test_undefined_fields(self):
        f = Undefined(Integer())
        field = Tuple((Text(), f, Text()))
        self.assert_processed(field, None, (('', 1, ''), ('', 1, '')))

        f = Undefined()
        field = Tuple((Text(), f, Text()))
        f.define(Integer())
        self.assert_processed(field, None, (('', 1, ''), ('', 1, '')))
    
    def test_naive_extraction(self):
        field = Tuple((Integer(), Text()))
        value = (1, 'test')

        extracted = field.extract(value)
        self.assertIsNot(value, extracted)
        self.assertEqual(value, extracted)

        field = Tuple((Tuple((Integer(),)), Text()))
        value = ((1,), 'test')

        extracted = field.extract(value)
        self.assertIsNot(value, extracted)
        self.assertIsNot(value[0], extracted[0])
        self.assertEqual(value, extracted)

    def test_mediated_extraction(self):
        field = Tuple((Integer(), Text()), extractor=listwrapper.extract)
        value = listwrapper(None, (1, 'test'))
        extracted = field.extract(value)

        self.assertIsInstance(extracted, tuple)
        self.assertEqual(extracted, (1, 'test'))

        field = Tuple((Integer(extractor=valuewrapper.extract), Text()), extractor=listwrapper.extract)
        value = listwrapper(None, (valuewrapper(None, 1), 'test'))
        extracted = field.extract(value)

        self.assertIsInstance(extracted, tuple)
        self.assertEqual(extracted, (1, 'test'))

        field = Tuple((Integer(), Text(extractor=valuewrapper.extract)))
        value = (1, valuewrapper(None, 'test'))
        extracted = field.extract(value)

        self.assertIsInstance(extracted, tuple)
        self.assertEqual(extracted, (1, 'test'))

    def test_instantiation(self):
        field = Tuple((Integer(), Text()), instantiator=listwrapper)
        instance = field.instantiate((1, 'test'))

        self.assertIsInstance(instance, listwrapper)
        self.assertEqual(instance.list, (1, 'test'))

        field = Tuple((Integer(instantiator=valuewrapper), Text()), instantiator=listwrapper)
        instance = field.instantiate((1, 'test'))

        self.assertIsInstance(instance, listwrapper)
        self.assertIsInstance(instance.list[0], valuewrapper)
        self.assertEqual(instance.list[0].value, 1)
        self.assertEqual(instance.list[1], 'test')

        field = Tuple((Integer(), Text(instantiator=valuewrapper)))
        instance = field.instantiate((1, 'test'))

        self.assertIsInstance(instance, tuple)
        self.assertEqual(instance[0], 1)
        self.assertIsInstance(instance[1], valuewrapper)
        self.assertEqual(instance[1].value, 'test')

    def test_interpolation(self):
        field = Tuple((Integer(), Text()))
        self.assert_interpolated(field, None, ((1, 'two'), (1, 'two')))
        self.assert_interpolated(field, (('${alpha}', '${beta}'), (1, 'two')),
            alpha=1, beta='two')
        self.assert_interpolated(field, ('${value}', (1, 'two')),
            value=('${alpha}', '${beta}'), alpha=1, beta='two')

class TestUnion(FieldTestCase):
    def test_specification(self):
        self.assertRaises(SchemeError, lambda:Union(True))
        self.assertRaises(SchemeError, lambda:Union((Date(), True)))

    def test_processing(self):
        field = Union(Text(), Integer())
        self.assert_processed(field, None, 'testing', 1)
        self.assert_not_processed(field, 'invalid', True, {}, [])

        field = Union(Map(Integer()), Text())
        self.assert_processed(field, None, {'a': 1}, 'testing')
        self.assert_not_processed(field, 'invalid', 1, True, [])

    def test_undefined_fields(self):
        f = Undefined(Integer())
        field = Union(Text(), f, Boolean())
        self.assert_processed(field, None, 'testing', 1, True)
        self.assert_not_processed(field, 'invalid', {}, [])

        f = Undefined()
        field = Union(Text(), f, Boolean())
        f.define(Integer())
        self.assert_processed(field, None, 'testing', 1, True)
        self.assert_not_processed(field, 'invalid', {}, [])

class TestUUID(FieldTestCase):
    def uuid(self):
        return str(uuid4())

    def test_processing(self):
        field = UUID()
        self.assert_processed(field, None, self.uuid())
        self.assert_not_processed(field, 'invalid', True, '', self.uuid()[:-1])

    def test_interpolation(self):
        field = UUID()
        uuid = self.uuid()

        self.assert_interpolated(field, None, '', uuid)
        self.assert_interpolated(field, ('${value}', uuid), value=uuid)
