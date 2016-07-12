import contextlib
import collections
import gc
import pickle
import sys
import unittest

from asyncpg.protocol.protocol import _create_record as Record


R_A = collections.OrderedDict([('a', 0)])
R_AB = collections.OrderedDict([('a', 0), ('b', 1)])
R_AC = collections.OrderedDict([('a', 0), ('c', 1)])
R_ABC = collections.OrderedDict([('a', 0), ('b', 1), ('c', 2)])


class TestRecord(unittest.TestCase):

    @contextlib.contextmanager
    def checkref(self, *objs):
        cnt = [sys.getrefcount(objs[i]) for i in range(len(objs))]
        yield
        for _ in range(3):
            gc.collect()
        for i in range(len(objs)):
            before = cnt[i]
            after = sys.getrefcount(objs[i])
            if before != after:
                self.fail('refcounts differ for {!r}: {:+}'.format(
                    objs[i], after - before))

    def test_record_zero_length(self):
        with self.assertRaises(SystemError):
            Record({}, ())

    def test_record_gc(self):
        elem = object()
        mapping = {}
        with self.checkref(mapping, elem):
            r = Record(mapping, (elem,))
            del r

        key = 'spam'
        val = int('101010')
        mapping = {key: val}
        with self.checkref(key, val):
            r = Record(mapping, (0,))
            with self.assertRaises(KeyError):
                r[key]
            del r

        key = 'spam'
        val = 'ham'
        mapping = {key: val}
        with self.checkref(key, val):
            r = Record(mapping, (0,))
            with self.assertRaises(KeyError):
                r[key]
            del r

    def test_record_freelist_ok(self):
        for _ in range(10000):
            Record({'a': 0}, (42,))
            Record({'a': 0, 'b': 1}, (42, 42,))

    def test_record_len_getindex(self):
        r = Record({'a': 0}, (42,))
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0], 42)
        self.assertEqual(r['a'], 42)

        r = Record({'a': 0, 'b': 1}, (42, 43))
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0], 42)
        self.assertEqual(r[1], 43)
        self.assertEqual(r['a'], 42)
        self.assertEqual(r['b'], 43)

        with self.assertRaisesRegex(IndexError,
                                    'record index out of range'):
            r[1000]

        with self.assertRaisesRegex(KeyError, 'spam'):
            r['spam']

        with self.assertRaisesRegex(KeyError, 'spam'):
            Record(None, (1,))['spam']

        with self.assertRaisesRegex(KeyError, 'spam'):
            Record({'spam': 123}, (1,))['spam']

    def test_record_slice(self):
        r = Record(R_ABC, (1, 2, 3))
        self.assertEqual(r[:], (1, 2, 3))
        self.assertEqual(r[:1], (1,))
        self.assertEqual(r[::-1], (3, 2, 1))
        self.assertEqual(r[::-2], (3, 1))
        self.assertEqual(r[1:2], (2,))
        self.assertEqual(r[2:2], ())

    def test_record_immutable(self):
        r = Record(R_A, (42,))
        with self.assertRaisesRegex(TypeError, 'does not support item'):
            r[0] = 1

    def test_record_repr(self):
        self.assertEqual(
            repr(Record({'a': 0}, (42,))),
            '<Record a=42>')

        self.assertEqual(
            repr(Record(R_AB, (42, -1))),
            '<Record a=42 b=-1>')

        # test invalid records just in case
        with self.assertRaisesRegex(RuntimeError, 'invalid .* mapping'):
            repr(Record({'a': 0}, (42, 43)))
        self.assertEqual(repr(Record(R_AB, (42,))), '<Record a=42>')

        class Key:
            def __str__(self):
                1 / 0

            def __repr__(self):
                1 / 0

        with self.assertRaises(ZeroDivisionError):
            repr(Record({Key(): 0}, (42,)))
        with self.assertRaises(ZeroDivisionError):
            repr(Record({'a': 0}, (Key(),)))

    def test_record_iter(self):
        r = Record(R_AB, (42, 43))
        with self.checkref(r):
            self.assertEqual(iter(r).__length_hint__(), 2)
            self.assertEqual(tuple(r), (42, 43))

    def test_record_values(self):
        r = Record(R_AB, (42, 43))
        vv = r.values()
        self.assertEqual(tuple(vv), (42, 43))
        self.assertTrue(repr(vv).startswith('<RecordIterator '))

    def test_record_keys(self):
        r = Record(R_AB, (42, 43))
        vv = r.keys()
        self.assertEqual(tuple(vv), ('a', 'b'))

        # test invalid record
        with self.assertRaisesRegex(TypeError, 'not iterable'):
            Record(None, (42, 43)).keys()

    def test_record_items(self):
        r = Record(R_AB, (42, 43))

        self.assertEqual(dict(r), {'a': 42, 'b': 43})
        self.assertEqual(
            list(collections.OrderedDict(r).items()),
            [('a', 42), ('b', 43)])

        with self.checkref(r):
            rk = r.items()
            self.assertEqual(rk.__length_hint__(), 2)
            self.assertEqual(next(rk), ('a', 42))
            self.assertEqual(rk.__length_hint__(), 1)
            self.assertEqual(next(rk), ('b', 43))
            self.assertEqual(rk.__length_hint__(), 0)

            with self.assertRaises(StopIteration):
                next(rk)
            with self.assertRaises(StopIteration):
                next(rk)

            self.assertEqual(rk.__length_hint__(), 0)

        self.assertEqual(list(r.items()), [('a', 42), ('b', 43)])

        # Check invalid records just in case
        r = Record(R_A, (42, 43))
        self.assertEqual(list(r.items()), [('a', 42)])
        r = Record(R_AB, (42,))
        self.assertEqual(list(r.items()), [('a', 42)])
        r = Record(None, (42, 43))
        with self.assertRaises(TypeError):
            list(r.items())

    def test_record_hash(self):
        r1 = Record({'a': 0, 'b': 1}, (42, 43))
        r2 = Record({'a': 0, 'b': 1}, (42, 43))
        r3 = Record({'a': 0, 'b': 1}, (42, 45))
        r4 = (42, 43)

        self.assertEqual(hash(r1), hash(r2))
        self.assertNotEqual(hash(r1), hash(r3))
        self.assertNotEqual(hash(r1), hash(r4))

        d = {}
        d[r1] = 123
        self.assertEqual(d[r1], 123)
        self.assertIn(r2, d)
        self.assertEqual(d[r2], 123)
        self.assertNotIn(r3, d)
        self.assertNotIn(r4, d)

    def test_record_cmp(self):
        r1 = Record(R_AB, (42, 43))
        r2 = Record(R_AB, (42, 43))
        r3 = Record(R_AB.copy(), (42, 43))

        r4 = Record(R_AB.copy(), (42, 45))
        r5 = Record(R_ABC, (42, 46, 57))
        r6 = Record(R_AC, (42, 43))

        r7 = (42, 43)

        self.assertEqual(r1, r2)
        self.assertEqual(r1, r3)

        self.assertNotEqual(r1, r4)
        self.assertNotEqual(r1, r5)
        self.assertNotEqual(r1, r6)
        self.assertNotEqual(r1, r7)
        self.assertNotEqual(r4, r5)
        self.assertNotEqual(r4, r6)
        self.assertNotEqual(r6, r5)

        self.assertLess(r1, r4)
        self.assertGreater(r4, r1)

        self.assertLess(r1, r5)
        self.assertGreater(r5, r6)
        self.assertGreater(r5, r4)

        with self.assertRaisesRegex(TypeError, 'unorderable'):
            r7 < r1

        with self.assertRaisesRegex(TypeError, 'unorderable'):
            r1 < r7

    def test_record_not_pickleable(self):
        r = Record({'a': 0}, (42,))
        with self.assertRaisesRegex(TypeError,
                                    "can't pickle Record objects"):
            pickle.dumps(r)
