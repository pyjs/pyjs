# Copyright (C) 2010, Daniel Popowich <danielpopowich@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pyjamas import Window
from __pyjamas__ import JS, get_main_frame
import pyjd
from traceback import print_exc # used in Timer.pywebkitgtknew.py for debugging

class Timer(object):

    '''
    Timer() a re-implementation of GWT's Timer class.  This class has
    the same interface as GWT's with two minor enhancements in the
    constructor which changes what gets fired when the timer goes off.
    '''

    __timers = set()

    class __WindowCloseListener:
        ## window closing events
        # cancel all the timers when window is closed
        def onWindowClosed(self):
            for timer in list(Timer.__timers):
                timer.cancel()

        def onWindowClosing(self):
            pass

    def __init__(self, delayMillis=0, notify=None):

        '''Called with no arguments, create a timer that will call its
        run() method when it is scheduled and fired.  This usage
        requires subclassing to implement the run() method.  This is
        GWT's interface and behaviour.

        There are two enhancements to pyjamas' implementation when
        specified with special keyword arguments, one of which
        obviates the need for subclassing::

            timer = Timer(delayMillis=ms)

        is identical to::

            timer = Timer()
            timer.schedule(ms)

        and::

            timer = Timer(notify=object_or_func)

        is the same as::

            timer = Timer()
            run = getattr(object_or_func, 'onTimer', object_or_func)
            if not callable(run): raise ValueError, msg

        i.e., the value passed to notify is checked to see if it has
        an onTimer attribute; if so, it is used as the callable, if
        not, the object itself is used as the callable.

        NOTE: when notify is specified, the function or method will be
        called with one argument: the instance of the timer.  So, this
        would be proper usage::

            def timer_cb(timer):
               ...

            timer = Timer(notify=timer_cb)

        or::

            class myclass:

                def __init__(self):
                    ...
                    self.timer = Timer(notify=self)

                def onTimer(self, timer):
                    ...
        '''

        # initialize a few house keeping vars
        self.__tid = None
        self.__onTimer = lambda: self.run()
        Window.addWindowCloseListener(Timer.__WindowCloseListener())

        # check notify
        if notify is not None:
            run = getattr(notify, 'onTimer', notify)
            if not callable(run):
                raise ValueError, 'Programming error: notify must be callable'
            self.__onTimer = lambda: run(self)

        # ugly, ugly, ugly, but there's no other way to get
        # implementation-specific initialization (without subclassing,
        # which the override system doesn't do).  The default is a
        # no-op.  We do it here, so the instance can be init'd before
        # the possible scheduling of the timer.
        self.__impl_init_hook()

        # schedule?
        if delayMillis != 0:
            self.schedule(delayMillis)

    def __impl_init_hook(self):
        pass

    def cancel(self):
        'Cancel the timer.'

        if self.__tid is None:
            return

        if self.__is_repeating:
            self.__clearInterval(self.__tid)
        else:
            self.__clearTimeout(self.__tid)

        self.__tid = None
        Timer.__timers.discard(self)

    def run(self):
        """
        The method that gets fired when the timer goes off.
        The base class raises a NotImplementedError if it is not
        overridden by a subclass or if Timer isn't instantiated with
        the notify keyword argument.
        """
        raise NotImplementedError, ('''Timer.run() must be overridden or Timer
                                       must be instantiated with notify keyword
                                       argument''')

    def schedule(self, delayMillis):
        '''Schedule this timer to fire in delayMillis milliseconds.
        Calling this method cancels (for this instance only) any
        previously scheduled timer.'''

        if delayMillis <= 0:
            raise ValueError, 'delay must be positive'

        self.cancel()
        self.__is_repeating = False
        self.__tid = self.__setTimeout(delayMillis)
        Timer.__timers.add(self)


    def scheduleRepeating(self, periodMillis):
        '''Schedule this timer to fire forever (or until cancelled)
        every periodMillis milliseconds.  Calling this method cancels
        (for this instance only) any previously scheduled timer.'''

        if periodMillis <= 0:
            raise ValueError, 'period must be positive'

        self.cancel()
        self.__is_repeating = True
        self.__tid = self.__setInterval(periodMillis)
        Timer.__timers.add(self)

    # fire the timer
    def __fire(self, *args, **kwds):
        # if not repeating, remove it from the list of active timers
        if not self.__is_repeating:
            Timer.__timers.discard(self)
        self.__onTimer()

    ######################################################################
    # Platforms may need to implement the following four methods
    ######################################################################

    def __setTimeout(self, delayMillis):
        return get_main_frame().window.setTimeout(self.__fire, delayMillis)

    def __clearTimeout(self,tid):
        return get_main_frame().window.clearTimeout(tid)

    def __setInterval(self, periodMillis):
        return get_main_frame().window.setInterval(self.__fire, periodMillis)

    def __clearInterval(self, tid):
        return get_main_frame().window.clearInterval(tid)
