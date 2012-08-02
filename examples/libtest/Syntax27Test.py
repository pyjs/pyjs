from UnitTest import UnitTest
import sys

class Syntax27Test(UnitTest):
    def testSetLiteral(self):
        s = {1,2,3,1,2,3,1,2,3}
        self.assertEqual(s, set([1,2,3]))

        s = {1, 2, None, True, False, 2, 2, ('a',)}
        self.assertEqual(s, set([False, True, 1, 2, ('a',), None]))

    def testSetComprehensions(self):
        s = sum({i*i for i in range(100) if i&1 == 1})
        self.assertEqual(s, 166650)

        s = {2*y + x + 1 for x in (0,) for y in (1,)}
        self.assertEqual(s, set([3]))

        l = list(sorted({(i,j) for i in range(3) for j in range(4)}))
        self.assertEqual(l, [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3), (2, 0), (2, 1), (2, 2), (2, 3)])

        l = list(sorted({(i,j) for i in range(4) for j in range(i)}))
        self.assertEqual(l, [(1, 0), (2, 0), (2, 1), (3, 0), (3, 1), (3, 2)])

        i = 20
        s = sum({i*i for i in range(100)})
        self.assertEqual(s, 328350)
        self.assertEqual(i, 20)

        def srange(n):
            return {i for i in range(n)}
        l = list(sorted(srange(10)))
        self.assertEqual(l, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])

        lrange = lambda n:  {i for i in range(n)}
        l = list(sorted(lrange(10)))
        self.assertEqual(l, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])

        def grange(n):
            for x in {i for i in range(n)}:
                yield x
        l = list(sorted(grange(5)))
        self.assertEqual(l, [0, 1, 2, 3, 4])

        s = {None for i in range(10)}
        self.assertEqual(s, set([None]))

        items = {(lambda i=i: i) for i in range(5)}
        s = {x() for x in items}
        self.assertEqual(s, set(range(5)))

        items = {(lambda: i) for i in range(5)}
        s = {x() for x in items}
        self.assertEqual(s, set([4]))

        items = {(lambda: y) for i in range(5)}
        y = 2
        s = {x() for x in items}
        self.assertEqual(s, set([2]))

        def test_func():
            items = {(lambda i=i: i) for i in range(5)}
            return {x() for x in items}
        self.assertEqual(test_func(), set(range(5)))

    def testDictComprehensions(self):
        k = "old value"
        d = { k: None for k in range(10) }
        self.assertEqual(d, {0: None, 1: None, 2: None, 3: None, 4: None, 5: None, 6: None, 7: None, 8: None, 9: None})
        self.assertEqual(k, 'old value')

        d = { k: k+10 for k in range(10) }
        self.assertEqual(d, {0: 10, 1: 11, 2: 12, 3: 13, 4: 14, 5: 15, 6: 16, 7: 17, 8: 18, 9: 19})

        d = { k: v for k in range(10) for v in range(10) if k == v }
        self.assertEqual(d, {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9})

        d = { k: v for v in range(10) for k in range(v*9, v*10) }
        self.assertEqual(d, {9: 1, 18: 2, 19: 2, 27: 3, 28: 3, 29: 3, 36: 4, 37: 4, 38: 4, 39: 4, 45: 5,
            46: 5, 47: 5, 48: 5, 49: 5, 54: 6, 55: 6, 56: 6, 57: 6, 58: 6, 59: 6, 63: 7, 64: 7,
            65: 7, 66: 7, 67: 7, 68: 7, 69: 7, 72: 8, 73: 8, 74: 8, 75: 8, 76: 8, 77: 8, 78: 8,
            79: 8, 81: 9, 82: 9, 83: 9, 84: 9, 85: 9, 86: 9, 87: 9, 88: 9, 89: 9})

        g = "outer"
        d = { k: g for k in range(3) }
        self.assertEqual(d, {0: 'outer', 1: 'outer', 2: 'outer'})
