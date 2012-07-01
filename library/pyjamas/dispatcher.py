"""
    Dispatcher of py calls from html/javascript.
    
    Eg. Allows to bind some python code (eg. show window) into onclick of some button/href
    
    written by Łukasz Mach<maho@pagema.net>, idea from C.A.Risinger
"""

from pyjamas import Window

from __javascript__ import window
wnd=window.parent

####below doesn't work, but probably should 
#from __pyjamas__ import wnd


class PyjsDispatcher(object):

    def install(self):
        """ install self into document html tree, into $pyjs_dispatcher """
        wnd=window.parent

        wnd.pyjs_dispatcher=self


