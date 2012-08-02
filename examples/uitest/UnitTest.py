from write import write, writebr
import sys

IN_BROWSER = sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz', 'safari']
IN_JS = sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz',
                         'safari', 'spidermonkey', 'pyv8']

from pyjamas import DOM
from pyjamas.Timer import Timer

from pyjamas.HTTPRequest import HTTPRequest
from pyjamas.ui.RootPanel import RootPanel

class GetTestOutput:

    def __init__(self, unittest, test_name, output):
        self.test_name = test_name
        self.unittest = unittest
        self.output = output

    def onCompletion(self, responseText):
        # TODO - cope with unicode / utf-8 test results
        print "onCompletion", self.unittest.tests_outstanding, self.test_name
        self.unittest.async_test_name = self.test_name
        e1 = DOM.getElementById('testcompare1')
        e2 = DOM.getElementById('testcompare2')
        e1.innerHTML = responseText
        e2.innerHTML = responseText
        i1 = DOM.walkChildren(e1)
        i2 = DOM.walkChildren(e2)
        ok = True
        while ok:
            try:
                ec1 = i1.next()
                ec2 = i2.next()
            except StopIteration:
                break
            ok = ok and (ec1.nodeType == ec2.nodeType)
            if not ok:
                break
            print ec1.nodeName, ec1.nodeValue
            ok = ok and (ec1.nodeName == ec2.nodeName)
            ok = ok and (ec1.nodeValue == ec2.nodeValue)
            if not ok:
                break
            if hasattr(ec1, 'getInnerText') and hasattr(ec2, 'getInnerText'):
                print ec1.getInnerText()
                ok = ok and (ec1.getInnerText() == ec2.getInnerText())
            if not ok:
                break
            if hasattr(ec1, 'attributes') and hasattr(ec2, 'attributes'):
                a1 = ec1.attributes
                a2 = ec2.attributes
                ok = hasattr(a1, 'length') and hasattr(a2, 'length')
                if not ok:
                    break
                ok = ok and (a1.length == a2.length)
                if not ok:
                    break
                for i in range(a1.length):
                    ai1 = a1.item(i)
                    ai2 = a2.item(i)
                    ok = ok and (ai1.nodeValue == ai2.nodeValue)
                    ok = ok and (ai1.nodeName == ai2.nodeName)
        self.unittest.assertTrue(ok)
        self.unittest.tests_outstanding -= 1

        # clear the test HTML
        e1.innerHTML = ''
        e2.innerHTML = ''


    def onError(self, responseText, status):
        self.unittest.async_test_name = self.test_name
        self.unittest.fail("""downloading test output %s failed,
status %s, response %s""" % (self.test_name, str(status), repr(responseText)))
        self.unittest.tests_outstanding -= 1

#renamed class UnitTest to UnitTest1.  see Issue #768 for more details 
class UnitTest1:

    def __init__(self, test_gen_folder):
        self.test_gen_folder = test_gen_folder
        self.tests_completed=0
        self.tests_failed=0
        self.tests_passed=0
        self.test_methods=[]
        self.test_idx = None
        self.tests_outstanding = None

        # Synonyms for assertion methods
        self.assertEqual = self.assertEquals = self.failUnlessEqual
        self.assertNotEqual = self.assertNotEquals = self.failIfEqual
        self.assertAlmostEqual = self.assertAlmostEquals = self.failUnlessAlmostEqual
        self.assertNotAlmostEqual = self.assertNotAlmostEquals = self.failIfAlmostEqual
        self.assertRaises = self.failUnlessRaises
        self.assert_ = self.assertTrue = self.failUnless
        self.assertFalse = self.failIf

    def do_test(self, output, name):
        handler = GetTestOutput(self, self.current_test_name, output)
        if name:
            fname = "%s.%s.txt" % (self.current_test_name, name)
        else:
            fname = "%s.txt" % self.current_test_name
        HTTPRequest().asyncGet(fname, handler)

    def write_test_output(self, name=None, div_id=None):
        if div_id is None:
            div_id = 'tests'
        element = DOM.getElementById(div_id)
        output = element.innerHTML

        if self.test_gen_folder is None:
            if self.tests_outstanding is None:
                self.tests_outstanding = 0
            self.tests_outstanding += 1
            self.do_test(output, name)
            return

        # otherwise assume we're running pyjd, and have file-system
        # access
        import os
        if name:
            fname = "%s.%s.txt" % (self.current_test_name, name)
        else:
            fname = "%s.txt" % self.current_test_name
        f = open(os.path.join(self.test_gen_folder, fname), "w")
        f.write(output)
        f.close()

        if self.tests_outstanding is None:
            self.tests_outstanding = 0

        return False

    def _run_test(self, test_method_name):
        self.getTestMethods()

        test_method=getattr(self, test_method_name)
        self.current_test_name = test_method_name
        self.setUp()
        test_method()
        self.tearDown()
        self.current_test_name = None
        self.async_test_name = None

    def run(self):
        self.getTestMethods()
        self.test_idx = 0
        Timer(1, self)

    def onTimer(self, timer):
        print self.test_idx
        if self.test_idx is 'DONE':
            self.check_start_next_test()
            return

        for i in range(1):
            if self.test_idx >= len(self.test_methods):
                self.test_idx = 'DONE'
                self.check_start_next_test()
                return

            self._run_test(self.test_methods[self.test_idx])
            self.test_idx += 1
        timer.schedule(1)

    def check_start_next_test(self):
        if self.tests_outstanding is None:
            return
        if self.tests_outstanding == 0:
            if hasattr(self, 'lastTestsCheck'):
                self.lastTestsCheck()
            self.displayStats()
            self.start_next_test()
            return
        # do it again.
        Timer(100, self)

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def getName(self):
        return self.__class__.__name__

    def getNameFmt(self, msg=""):
        test_name = self.async_test_name or self.current_test_name
        if self.getName():
            if msg:
                msg=" " + str(msg)
            if test_name:
                msg += " (%s) " % test_name
            return self.getName() + msg + ": "
        return ""

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

        title="<b>" + self.getNameFmt("Test failed") + "</b>"
        writebr(title + msg)
        if sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz', 'safari']:
            from __pyjamas__ import JS
            JS("""if (typeof @{{!console}} != 'undefined') {
                if (typeof @{{!console}}.error == 'function') @{{!console}}.error(@{{msg}});
                if (typeof @{{!console}}.trace == 'function') @{{!console}}.trace();
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

        write(output, do_escape=False)
