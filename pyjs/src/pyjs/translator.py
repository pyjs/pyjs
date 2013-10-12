import sys
import os
if os.environ.has_key('PYJS_SYSPATH'):
    sys.path[0:0] = [os.environ['PYJS_SYSPATH']]
import pyjs
LIBRARY_PATH = os.path.abspath(os.path.dirname(__file__))

if (
    "--translator=dict" in sys.argv or
    "--use-translator=dict" in sys.argv
):
    from translator_dict import *
    name = 'dict'
else:
    from translator_proto import *
    name = 'proto'

usage = """
  usage: %prog [options] file...
"""

def main():
    import sys
    from optparse import OptionParser

    parser = OptionParser(usage = usage)
    parser.add_option("-o", "--output", dest="output",
                      default="-",
                      help="Place the output into <output>")
    parser.add_option("-m", "--module-name", dest="module_name",
                      help="Module name of output")
    parser.add_option("-i", "--list-imports", dest="list_imports",
                      default=False,
                      action="store_true",
                      help="List import dependencies (without compiling)")
    add_compile_options(parser)
    (options, args) = parser.parse_args()

    if len(args)<1:
        parser.error("incorrect number of arguments in %s" % repr(sys.argv))


    if not options.output:
        parser.error("No output file specified")
    if options.output != '-':
        options.output = os.path.abspath(options.output)

    file_names = map(os.path.abspath, args)
    for fn in file_names:
        if not os.path.isfile(fn):
            print >> sys.stderr, "Input file not found %s" % fn
            sys.exit(1)

    imports, js = translate(file_names, options.output,
              options.module_name,
              **get_compile_options(options))
    if options.list_imports:
        if imports:
            print '/*'
            print 'PYJS_DEPS: %s' % imports
            print '*/'

        if js:
            print '/*'
            print 'PYJS_JS: %s' % repr(js)
            print '*/'

if __name__ == "__main__":
    main()
