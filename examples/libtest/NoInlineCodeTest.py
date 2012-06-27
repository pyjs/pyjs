# Tests for the implementatuion of --no-inline-code
# Note that the use of int/float/lon as variable 
# is not allowed with google closure compile

import sys
import UnitTest
import urllib

def test(a):
   return None

class NoInlineCodeTest(UnitTest.UnitTest):

    def test_bool(self):
        i1 = bool(1)
        def fn():
            i2 = True
            bool = test
            i3 = bool(1)
            i4 = True
            self.assertEqual(i1, True)
            self.assertEqual(i1, i2)
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_int(self):
        i1 = int(1)
        def fn():
            i2 = 1
            int = test
            i3 = int(1)
            i4 = 1
            self.assertEqual(i1, 1)
            self.assertEqual(i1, i2)
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_hexint(self):
        i1 = int(1)
        def fn():
            i2 = 0x1
            int = hex = test
            i3 = int(0x1)
            i4 = 0x1
            self.assertEqual(i1, 1)
            self.assertEqual(i1, i2)
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_long(self):
        i1 = long(1)
        def fn():
            i2 = 1L
            long = test
            i3 = long(1)
            i4 = 1L
            self.assertEqual(i1, 1L)
            self.assertEqual(i1, i2)
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_float(self):
        i1 = float(1.0)
        def fn():
            i2 = 1.0
            float = test
            i3 = float(1.0)
            i4 = 1.0
            self.assertEqual(i1, 1.0)
            self.assertEqual(i1, i2)
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_tuple(self):
        i1 = tuple((1,))
        def fn():
            i2 = (1,)
            tuple = test
            i3 = tuple((1,))
            i4 = (1,)
            self.assertEqual(i1, (1,))
            self.assertEqual(i1, i2)
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_list(self):
        i1 = list([1])
        def fn():
            i2 = [1]
            list = test
            i3 = list([1])
            i4 = [1]
            self.assertEqual(i1, [1])
            self.assertEqual(i1, i2)
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_dict(self):
        i1 = dict(a=1)
        def fn():
            i2 = {'a':1}
            dict = test
            i3 = dict(a=1)
            i4 = {'a':1}
            self.assertEqual(i1, {'a':1})
            self.assertEqual(i1, i2)
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_set(self):
        i1 = set([1])
        _set = set
        def fn():
            set = test
            i3 = set([1])
            i4 = _set([1])
            self.assertNotEqual(i1, i3)
            self.assertEqual(i1, i4)
        fn()

    def test_ArithmeticError(self):
        e1 = ArithmeticError
        def fn():
            ArithmeticError = bool
            try:
                a = 1/0
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, ArithmeticError))
            else:
                self.fail("Failed to raise ArithmeticError")
        fn()

    def test_AttributeError(self):
        e1 = AttributeError
        def fn():
            AttributeError = bool
            try:
                a = e1.noooo
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, AttributeError))
            else:
                self.fail("Failed to raise AttributeError")
        fn()

    def test_BaseException(self):
        e1 = BaseException
        def fn():
            BaseException = bool
            try:
                a = 1/0
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, BaseException))
            else:
                self.fail("Failed to raise BaseException")
        fn()

    def test_Exception(self):
        e1 = Exception
        def fn():
            Exception = bool
            try:
                a = 1/0
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, Exception))
            else:
                self.fail("Failed to raise Exception")
        fn()

    def _test_GeneratorExit(self):
        e1 = GeneratorExit
        def fn():
            GeneratorExit = bool
            try:
                a = 1/0
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, GeneratorExit))
            else:
                self.fail("Failed to raise GeneratorExit")
        fn()

    def test_ImportError(self):
        e1 = ImportError
        def fn():
            ImportError = bool
            try:
                import nosuchmodule
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, ImportError))
            else:
                self.fail("Failed to raise ImportError")
        fn()

    def test_IndexError(self):
        e1 = IndexError
        def fn():
            IndexError = bool
            try:
                a = [0][1]
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, IndexError))
            else:
                self.fail("Failed to raise IndexError")
        fn()

    def test_KeyError(self):
        e1 = KeyError
        def fn():
            KeyError = bool
            try:
                a = dict(a=1)['b']
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, KeyError))
            else:
                self.fail("Failed to raise KeyError")
        fn()

    def test_LookupError(self):
        e1 = LookupError
        def fn():
            LookupError = bool
            try:
                a = set([1]).remove(2)
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, LookupError))
            else:
                self.fail("Failed to raise LookupError")
        fn()

    def _test_NameError(self):
        # This fails anyway
        e1 = NameError
        def fn():
            NameError = bool
            try:
                a = nosuchname
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, NameError))
            else:
                self.fail("Failed to raise NameError")
        fn()

    def _test_RuntimeError(self):
        # This fails anyway...
        e1 = RuntimeError
        def fn():
            RuntimeError = bool
            try:
                a = dict(a=1,b=2,c=3)
                for k, v in a.iteritems():
                    a['_%s' % k] = v
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, RuntimeError))
            else:
                self.fail("Failed to raise RuntimeError")
        fn()

    def test_StandardError(self):
        e1 = StandardError
        def fn():
            StandardError = bool
            try:
                a = 1/0
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, StandardError))
            else:
                self.fail("Failed to raise StandardError")
        fn()

    def _test_StopIteration(self):
        #This fails anyway...
        e1 = StopIteration
        def fn():
            def g():
                yield None
            StopIteration = bool
            try:
                a = g()
                a.next()
                a.next()
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, StopIteration))
            else:
                self.fail("Failed to raise StopIteration")
        fn()

    def test_TypeError(self):
        e1 = TypeError
        def fn():
            TypeError = bool
            try:
                a = 1 + 'a'
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, TypeError))
            else:
                self.fail("Failed to raise TypeError")
        fn()

    def test_ValueError(self):
        e1 = ValueError
        def fn():
            ValueError = bool
            try:
                a = list([1]).index(2)
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, ValueError))
            else:
                self.fail("Failed to raise ValueError")
        fn()

    def test_ZeroDivisionError(self):
        e1 = ZeroDivisionError
        def fn():
            ZeroDivisionError = bool
            try:
                a = 1/0
            except e1, e:
                self.assertTrue(isinstance(e, e1))
                self.assertFalse(isinstance(e, ZeroDivisionError))
            else:
                self.fail("Failed to raise ZeroDivisionError")
        fn()

    def test_ArgsScoping(self):
        collection = []
        def fn(i, *args, **kwargs):
            if i < 2:
                fn(i+1)
            collection.append((i, args, kwargs))
        args = (2,3)
        kwargs = dict(a='a', b='b')
        collection.append((0, args, kwargs))
        fn(1, *args, **kwargs)
        self.assertEqual(
            collection,
            [
                (0, (2, 3), {'a': 'a', 'b': 'b'}),
                (2, (), {}),
                (1, (2, 3), {'a': 'a', 'b': 'b'}),
            ],
        )
