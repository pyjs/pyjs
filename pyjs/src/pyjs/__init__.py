import sys
import os
try:
    import lib2to3
except ImportError:
    import pgen
    import lib2to3

path = [os.path.abspath('')]


# default to None indicates 'relative paths' so that as a self-contained
# archive, pyjs can run its tests.
try:
    import pyjamaslibrary
    import pyjamasaddons
    pyjspth = os.path.abspath(os.path.join(__file__,'../'))
    path += [os.path.dirname(pyjamaslibrary.__file__),
             os.path.dirname(pyjamasaddons.__file__), ]
except ImportError:
    pyjspth = None

if os.environ.has_key('PYJSPATH'):
    for p in os.environ['PYJSPATH'].split(os.pathsep):
        p = os.path.abspath(p)
        if os.path.isdir(p):
            path.append(p)

MOD_SUFFIX = '.js'

PYTHON = os.path.realpath(sys.executable) if sys.executable else None
if PYTHON is None or not os.access(PYTHON, os.X_OK):
    PYTHON = 'python'


