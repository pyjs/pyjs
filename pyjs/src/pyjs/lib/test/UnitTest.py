from write import write, writebr
import sys

IN_BROWSER = sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz', 'safari']
IN_JS = sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz',
                         'safari', 'spidermonkey', 'pyv8']

if IN_BROWSER:
    from pyjamas.Timer import Timer

class UnitTest:

    def __init__(self):
        self.tests_completed=0
        self.tests_failed=0
        self.tests_passed=0
        self.test_methods=[]
        self.test_idx = None

        # Synonyms for assertion methods
        self.assertEqual = self.assertEquals = self.failUnlessEqual
        self.assertNotEqual = self.assertNotEquals = self.failIfEqual
        self.assertAlmostEqual = self.assertAlmostEquals = self.failUnlessAlmostEqual
        self.assertNotAlmostEqual = self.assertNotAlmostEquals = self.failIfAlmostEqual
        self.assertRaises = self.failUnlessRaises
        self.assert_ = self.assertTrue = self.failUnless
        self.assertFalse = self.failIf

    def _run_test(self, test_method_name):
        self.getTestMethods()

        test_method=getattr(self, test_method_name)
        self.current_test_name = test_method_name
        self.setUp()
        try:
            try:
                test_method()
            except Exception,e:
                self.fail("uncaught exception:" + str(e))
        except:
            self.fail("uncaught javascript exception")
        self.tearDown()
        self.current_test_name = None

    def run(self):
        self.getTestMethods()
        if not IN_BROWSER:
            for test_method_name in self.test_methods:
                self._run_test(test_method_name)
            self.displayStats()
            if hasattr(self, "start_next_test"):
                self.start_next_test()
            return
        self.test_idx = 0
        Timer(10, self)

    def onTimer(self, timer):
        for i in range(1):
            if self.test_idx >= len(self.test_methods):
                self.displayStats()
                self.test_idx = 'DONE'
                self.start_next_test()
                return

            self._run_test(self.test_methods[self.test_idx])
            self.test_idx += 1
        timer.schedule(10)

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def getName(self):
        return self.__class__.__name__

    def getNameFmt(self, msg=""):
        if self.getName():
            if msg:
                msg=" " + str(msg)
            if self.current_test_name:
                msg += " (%s) " % self.getCurrentTestID()
            return self.getName() + msg + ": "
        return ""

    def getCurrentTestID(self):
        return "%s/%i" % (self.current_test_name,self.tests_completed)


    def getTestMethods(self):
        self.test_methods=[]
        for m in dir(self):
            if self.isTestMethod(m):
                self.test_methods.append(m)

    def isTestMethod(self, method):
        if callable(getattr(self, method)):
            if method.find("test") == 0:
                return True
        return False

    def fail(self, msg=None):
        self.startTest()
        self.tests_failed+=1

        if not msg:
            msg="assertion failed"
        else:
            msg = str(msg)

        octothorp = msg.find("#")
        has_bugreport = octothorp >= 0 and msg[octothorp+1].isdigit()
        if has_bugreport:
            name_fmt = "Known issue"
            bg_colour="#ffc000"
            fg_colour="#000000"
        else:
            bg_colour="#ff8080"
            fg_colour="#000000"
            name_fmt = "Test failed"
        output="<table style='padding-left:20px;padding-right:20px;' cellpadding=2 width=100%><tr><td bgcolor='" + bg_colour + "'><font color='" + fg_colour + "'>"
        write(output)
        title="<b>" + self.getNameFmt(name_fmt) + "</b>"
        write(title + msg)
        output="</font></td></tr></table>"
        output+= "\n"
        write(output)
        if sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz', 'safari']:
            from __pyjamas__ import JS
            JS("""if (typeof @{{!console}} != 'undefined') {
                if (typeof @{{!console}}['error'] == 'function') @{{!console}}['error'](@{{msg}});
                if (typeof @{{!console}}['trace'] == 'function') @{{!console}}['trace']();
            }""")
        return False

    def startTest(self):
        self.tests_completed+=1

    def failIf(self, expr, msg=None):
        self.startTest()
        if expr:
            return self.fail(msg)

    def failUnless(self, expr, msg=None):
        self.startTest()
        if not expr:
            return self.fail(msg)

    def failUnlessRaises(self, excClass, callableObj, *args, **kwargs):
        try:
            callableObj(*args, **kwargs)
        except excClass:
            return
        else:
            if hasattr(excClass,'__name__'): excName = excClass.__name__
            else: excName = str(excClass)
            #raise self.failureException, "%s not raised" % excName
            self.fail("%s not raised" % excName)

    def failUnlessEqual(self, first, second, msg=None):
        self.startTest()
        if not first == second:
            if not msg:
                msg=repr(first) + " != " + repr(second)
            return self.fail(msg)

    def failIfEqual(self, first, second, msg=None):
        self.startTest()
        if first == second:
            if not msg:
                msg=repr(first) + " == " + repr(second)
            return self.fail(msg)

    def failUnlessAlmostEqual(self, first, second, places=7, msg=None):
        self.startTest()
        if round(second-first, places) != 0:
            if not msg:
                msg=repr(first) + " != " + repr(second) + " within " + repr(places) + " places"
            return self.fail(msg)

    def failIfAlmostEqual(self, first, second, places=7, msg=None):
        self.startTest()
        if round(second-first, places)  is  0:
            if not msg:
                msg=repr(first) + " == " + repr(second) + " within " + repr(places) + " places"
            return self.fail(msg)

    # based on the Python standard library
    def assertRaises(self, excClass, callableObj, *args, **kwargs):
        """
        Fail unless an exception of class excClass is thrown
        by callableObj when invoked with arguments args and keyword
        arguments kwargs. If a different type of exception is
        thrown, it will not be caught, and the test case will be
        deemed to have suffered an error, exactly as for an
        unexpected exception.
        """
        self.startTest()
        try:
            callableObj(*args, **kwargs)
        except excClass, exc:
            return
        else:
            if hasattr(excClass, '__name__'):
                excName = excClass.__name__
            else:
                excName = str(excClass)
            self.fail("%s not raised" % excName)

    def displayStats(self):
        if self.tests_failed:
            bg_colour="#ff0000"
            fg_colour="#ffffff"
        else:
            bg_colour="#00ff00"
            fg_colour="#000000"

        tests_passed=self.tests_completed - self.tests_failed
        if sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz', 'safari']:
            output="<table cellpadding=4 width=100%><tr><td bgcolor='" + bg_colour + "'><font face='arial' size=4 color='" + fg_colour + "'><b>"
        else:
            output = ""
        output+=self.getNameFmt() + "Passed %d " % tests_passed + "/ %d" % self.tests_completed + " tests"

        if self.tests_failed:
            output+=" (%d failed)" % self.tests_failed

        if sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz', 'safari']:
            output+="</b></font></td></tr></table>"
        else:
            output+= "\n"

        write(output)
