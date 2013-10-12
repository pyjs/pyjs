# Copyright (C) 2009, 2010, Luke Kenneth Casson Leighton <lkcl@lkcl.net>
# Copyright (C) 2010, Sujan Shakya <suzan.shakya@gmail.com>

import os
import sys
import time
import shutil
from pyjs import linker
from pyjs import translator
if translator.name == 'proto':
    required_modules =  [
        'pyjslib', 'sys', 'imp', 'dynamic', 'pyjamas', 'pyjamas.DOM',
    ]
    early_static_app_libs = ['_pyjs.js']
elif translator.name == 'dict':
    required_modules =  [
        '__builtin__', 'sys', 'imp', 'dynamic', 'pyjamas', 'pyjamas.DOM',
    ]
    early_static_app_libs = []
else:
    raise ValueError("unknown translator engine '%s'" % translator.name)

from pyjs import util
from pyjs import options
from cStringIO import StringIO
from optparse import OptionParser, OptionGroup
import pyjs
import re
import traceback
try:
    from hashlib import md5
except:
    from md5 import md5

from pprint import pprint, pformat

AVAILABLE_PLATFORMS = ('IE6', 'Opera', 'OldMoz', 'Safari', 'Mozilla')

BOILERPLATE_PATH = os.path.join(os.path.dirname(__file__), 'boilerplate')


APP_HTML_TEMPLATE = """\
<html>
<!-- auto-generated html - You should consider editing and adapting this
 to suit your requirements. No doctype used here to force quirks mode; see
 wiki for details: http://pyjs.org/wiki/csshellandhowtodealwithit/
-->
<head>
%(css)s
<title>%(title)s</title>
</head>
<body style="background-color:white">
</body>
</html>
"""

class BrowserLinker(linker.BaseLinker):

    # parents are specified in most-specific last
    platform_parents = {
        'mozilla':['browser'],
        'ie6':['browser'],
        'safari':['browser'],
        'oldmoz':['browser'],
        'opera':['browser'],
        }

    def __init__(self, *args, **kwargs):
        self.multi_file = kwargs.pop('multi_file', False)
        self.cache_buster = kwargs.pop('cache_buster', False)
        self.bootstrap_file = kwargs.pop('bootstrap_file', 'bootstrap.js')
        self.apploader_file = kwargs.pop('apploader_file', None)
        self.public_folder = kwargs.pop('public_folder', 'public')
        self.runtime_options = kwargs.pop('runtime_options', [])
        super(BrowserLinker, self).__init__(*args, **kwargs)

    def visit_start(self):
        super(BrowserLinker, self).visit_start()
        self.boilerplate_path = None
        self.early_static_app_libs += early_static_app_libs
        self.merged_public = set()
        self.app_files = {}
        self.renamed_libs = {}

    def visit_end_platform(self, platform):
        if not platform:
            return
        if self.cache_buster:
            # rename the files to their hashed equivalents
            renamed = []
            for p in self.done[platform]:
                if p in self.renamed_libs:
                    new_p = self.renamed_libs[p]
                else:
                    f = open(p)
                    md5sum = md5(f.read()).hexdigest()
                    f.close()
                    name, ext = os.path.splitext(p)
                    new_p = name + '.' + md5sum + ext
                    # if we are keeping all intermediate files
                    if self.keep_lib_files:
                        # copy the file to it's hashed equivalent
                        shutil.copyfile(p, new_p)
                    else:   # keep new file only
                        # clean out any previous version of the hashed file
                        if os.access(new_p, os.F_OK):
                            os.unlink(new_p)
                        os.rename(p, new_p)
                    self.renamed_libs[p] = new_p
                renamed.append(new_p)
            self.done[platform] = renamed
        self.app_files[platform] = self._generate_app_file(platform)

    def visit_end(self):
        self._create_app_html()
        self._create_nocache_html()
        if not self.keep_lib_files:
            for fname in self.remove_files:
                if fname.find(self.output) == 0:
                    os.unlink(fname)

    def merge_resources(self, dir_name):
        if not dir_name in self.merged_public:
            public_folder = os.path.join(dir_name, self.public_folder)
            if os.path.exists(public_folder) and os.path.isdir(public_folder):
                util.copytree_exists(public_folder,
                                     self.output)
                self.merged_public.add(dir_name)
        for libs in [self.js_libs, self.dynamic_js_libs,
                     self.static_js_libs, self.early_static_js_libs, self.late_static_js_libs]:
            for lib in libs:
                if not lib in self.merged_public:
                    for path in self.path:
                        if os.path.exists(lib) and os.path.isfile(lib):
                            util.copy_exists(lib, os.path.join(self.output, os.path.basename(lib)))
                            self.merged_public.add(lib)
                            break

        # merge all output/css.d/* files into one output/base.css file
        css_d_path = os.path.join(self.output, 'css.d')
        base_css_path = os.path.join(self.output, 'base.css')

        if os.path.exists(css_d_path):
            hdr = '/* name: %s\n * md5: %s\n */\n'
            with open(base_css_path, 'w') as base_css:
                for root, dirs, files in os.walk(css_d_path):
                    docroot = root.replace(root, '', 1).strip('/')
                    for frag in files:
                        frag_path = os.path.join(root, frag)
                        with open(frag_path) as fd:
                            csstxt = fd.read()
                            base_css.write(hdr % (
                                os.path.relpath(frag_path, self.output),
                                md5(csstxt).hexdigest(),
                                ))
                            base_css.write(csstxt)

    def find_boilerplate(self, name):
        if not self.top_module_path:
            raise RuntimeError('Top module not found %r' % self.top_module)
        if not self.boilerplate_path:
            self.boilerplate_path = [BOILERPLATE_PATH]
            module_bp_path = os.path.join(
                os.path.dirname(self.top_module_path), 'boilerplate')
            if os.path.isdir(module_bp_path):
                self.boilerplate_path.insert(0, module_bp_path)
        for p in self.boilerplate_path:
            bp =  os.path.join(p, name)
            if os.path.exists(bp):
                return bp
        raise RuntimeError("Boilerplate not found %r" % name)

    def read_boilerplate(self, name):
        f = file(self.find_boilerplate(name))
        res = f.read()
        f.close()
        return res

    def unique_list_values(self, lst):
        keys = {}
        for k in lst:
            keys[k] = 1
        return keys.keys()

    def _generate_app_file(self, platform):
        # TODO: cache busting
        template = self.read_boilerplate('all.cache.html')
        name_parts = [self.top_module, platform, 'cache.html']
        done = self.done[platform]
        len_ouput_dir = len(self.output)+1

        app_name = self.top_module
        platform_name = platform.lower()
        dynamic = 0,
        app_headers = ''
        available_modules = self.unique_list_values(self.visited_modules[platform])
        early_static_app_libs = [] + self.early_static_app_libs
        static_app_libs = []
        dynamic_app_libs = []
        dynamic_js_libs = [] + self.dynamic_js_libs
        static_js_libs = [] + self.static_js_libs
        early_static_js_libs = [] + self.early_static_js_libs
        late_static_js_libs = [] + self.late_static_js_libs
        dynamic_modules = []
        not_unlinked_modules = [re.compile(m[1:]) for m in self.unlinked_modules if m[0] == '!']
        for m in required_modules:
            not_unlinked_modules.append(re.compile('^%s$' % m))
        unlinked_modules = [re.compile(m) for m in self.unlinked_modules if m[0] != '!' and m not in not_unlinked_modules]

        def static_code(libs, msg = None):
            code = []
            for lib in libs:
                fname = lib
                if not os.path.isfile(fname):
                    fname = os.path.join(self.output, lib)
                if not os.path.isfile(fname):
                    raise RuntimeError('File not found %r' % lib)
                if fname[len_ouput_dir:] == self.output:
                    name = fname[len_ouput_dir:]
                else:
                    name = os.path.basename(lib)
                code.append('<script type="text/javascript"><!--')
                if not msg is None:
                    code.append("/* start %s: %s */" % (msg, name))
                f = file(fname)
                code.append(f.read())
                if not msg is None:
                    code.append("/* end %s */" % (name,))
                code.append("""--></script>""")
                self.remove_files[fname] = True
                fname = fname.split('.')
                if fname[-2] == '__%s__' % platform_name:
                    del fname[-2]
                    fname = '.'.join(fname)
                    if os.path.isfile(fname):
                        self.remove_files[fname] = True
            return "\n".join(code)

        def js_modname(path):
            return 'js@'+os.path.basename(path)+'.'+md5(path).hexdigest()

        def skip_unlinked(lst):
            new_lst = []
            pltfrm = '__%s__' % platform_name
            for path in lst:
                fname = os.path.basename(path).rpartition(pyjs.MOD_SUFFIX)[0]
                frags = fname.split('.')
                # TODO: do not combine module chunks until we write the file
                if self.cache_buster and len(frags[-1])==32 and len(frags[-1].strip('0123456789abcdef'))==0:
                    frags.pop()
                if frags[-1] == pltfrm:
                    frags.pop()
                fname = '.'.join(frags)
                in_not_unlinked_modules = False
                for m in not_unlinked_modules:
                    if m.match(fname):
                        in_not_unlinked_modules = True
                        new_lst.append(path)
                        break
                if not in_not_unlinked_modules:
                    in_unlinked_modules = False
                    for m in unlinked_modules:
                        if m.match(fname):
                            in_unlinked_modules = True
                            if fname in available_modules:
                                available_modules.remove(fname)
                    if not in_unlinked_modules:
                        new_lst.append(path)
            return new_lst

        if self.multi_file:
            dynamic_js_libs = self.unique_list_values(dynamic_js_libs + [m for m in list(self.js_libs) if not m in static_js_libs])
            dynamic_app_libs = self.unique_list_values([m for m in done if not m in early_static_app_libs])
        else:
            static_js_libs = self.unique_list_values(static_js_libs + [m for m in list(self.js_libs) if not m in dynamic_js_libs])
            static_app_libs = self.unique_list_values([m for m in done if not m in early_static_app_libs])

        dynamic_js_libs = skip_unlinked(dynamic_js_libs)
        dynamic_app_libs = skip_unlinked(dynamic_app_libs)
        static_js_libs = skip_unlinked(static_js_libs)
        static_app_libs = skip_unlinked(static_app_libs)

        dynamic_modules = self.unique_list_values(available_modules + [js_modname(lib) for lib in dynamic_js_libs])
        available_modules = self.unique_list_values(available_modules + early_static_app_libs + dynamic_modules)
        if len(dynamic_modules) > 0:
            dynamic_modules = "['" + "','".join(dynamic_modules) + "']"
        else:
            dynamic_modules = "[]"
        appscript = "<script><!--\n$wnd['__pygwt_modController']['init']($pyjs['appname'], window)\n$wnd['__pygwt_modController']['load']($pyjs['appname'], [\n'%s'\n])\n--></script>"
        jsscript = """<script type="text/javascript" src="%(path)s" onload="$pyjs['script_onload']('%(modname)s')" onreadystatechange="$pyjs['script_onreadystate']('%(modname)s')"></script>"""
        dynamic_app_libs = appscript % "',\n'".join([lib[len_ouput_dir:].replace('\\', '/') for lib in dynamic_app_libs])
        dynamic_js_libs = '\n'.join([jsscript % {'path': lib, 'modname': js_modname(lib)} for lib in dynamic_js_libs])
        early_static_app_libs = static_code(early_static_app_libs)
        static_app_libs = static_code(static_app_libs)
        early_static_js_libs = static_code(early_static_js_libs, "javascript lib")
        static_js_libs = static_code(static_js_libs, "javascript lib")
        late_static_js_libs = static_code(late_static_js_libs, "javascript lib")

        setoptions = "\n".join([("$pyjs['options']['%s'] = %s;" % (n, v)).lower() for n,v in self.runtime_options])

        file_contents = template % locals()
        if self.cache_buster:
            md5sum = md5(file_contents).hexdigest()
            name_parts.insert(2, md5sum)
        out_path = os.path.join(self.output, '.'.join((name_parts)))

        out_file = file(out_path, 'w')
        out_file.write(file_contents)
        out_file.close()
        return out_path

    def _create_nocache_html(self):
        # nocache
        template = self.read_boilerplate('home.nocache.html')
        out_path = os.path.join(self.output, self.top_module + ".nocache.html")
        select_tmpl = """O(["true","%s"],"%s");\n"""
        script_selectors = StringIO()
        for platform in self.platforms:
            cache_html = os.path.basename(self.app_files[platform])
            sel = select_tmpl % (platform, cache_html)
            script_selectors.write(sel)
        out_file = file(out_path, 'w')
        out_file.write(template % dict(
            app_name = self.top_module,
            script_selectors = script_selectors.getvalue()
            ))
        out_file.close()

    def _create_app_html(self):
        """ Checks if a base HTML-file is available in the Pyjamas
        output directory, and injects the bootstrap loader script tag.
        If the HTML-file isn't available, it will be created.

        If a CSS-file with the same name is available
        in the output directory, a reference to this CSS-file
        is included.

        If no CSS-file is found, this function will look for a special
        CSS-file in the output directory, with the name
        "pyjamas_default.css", and if found it will be referenced
        in the generated HTML-file.
        """

        html_output_filename = os.path.join(self.output,
                                            self.top_module + '.html')
        if self.apploader_file is None:
            file_name = html_output_filename
        else:
            file_name = self.apploader_file

        if os.path.exists(file_name):
            fh = open(file_name, 'r')
            base_html = fh.read()
            fh.close()
            created = 0
        else:
            title = self.top_module + ' (Pyjamas Auto-Generated HTML file)'
            link_tag = '<link rel="stylesheet" href="%s">'
            module_css = self.top_module + '.css'
            default_css = 'pyjamas_default.css'

            if os.path.exists(os.path.join(self.output, module_css)):
                css = link_tag % module_css
            elif os.path.exists(os.path.join(self.output, default_css)):
                css = link_tag % default_css
            else:
                css = ''

            base_html = APP_HTML_TEMPLATE % { 'title': title, 'css': css }
            created = 1

        # replace (or add) meta tag pygwt:module
        meta_tag_head = '<meta name="pygwt:module"'
        meta_tag_tail = ' content="%s">' % self.top_module

        meta_found = base_html.find(meta_tag_head)
        if meta_found > -1:
            meta_stop = base_html.find('>', meta_found + len(meta_tag_head))
        else:
            head_end = '</head>'
            meta_found = base_html.find(head_end)
            meta_stop = meta_found - 1
            meta_tag_tail += '\n'
            if meta_found == -1:
                raise RuntimeError("Can't inject module meta tag. " +\
                                   "No tag %(tag)s found in %(file)s" %\
                                   { 'tag': head_end, 'file': file_name })

        base_html = base_html[:meta_found] \
                  + meta_tag_head + meta_tag_tail \
                  + base_html[meta_stop + 1:]

        # inject bootstrap script tag and history iframe
        script_tag = '<script type="text/javascript" src="%s"></script>' % self.bootstrap_file
        iframe_tag = '<iframe id="__pygwt_historyFrame" style="display:none;"></iframe>'
        body_end = '</body>'

        if base_html.find(body_end) == -1:
            raise RuntimeError("Can't inject bootstrap loader. " + \
                               "No tag %(tag)s found in %(file)s" % \
                               { 'tag': body_end, 'file': file_name })
        base_html = base_html.replace(body_end,
                                      script_tag +'\n'+ iframe_tag +'\n'+ body_end)

        fh = open(html_output_filename, 'w')
        fh.write(base_html)
        fh.close()
        return created

MODIFIED_TIME = {}

def is_modified(path):
    current_mtime = os.path.getmtime(path)
    if current_mtime == MODIFIED_TIME.get(path):
        return False
    else:
        MODIFIED_TIME[path] = current_mtime
        print('mtime changed for %s.' % path)
        return True

def serve(path):
    print("\nMonitoring file modifications in %s ..." % \
           os.path.abspath(os.curdir))

def build(top_module, pyjs, options, app_platforms,
          runtime_options, args):
    print "Building: %s\nPYJSPATH: %s" % (top_module, pformat(pyjs.path))

    translator_arguments= translator.get_compile_options(options)

    l = BrowserLinker(args,
                      output=options.output,
                      platforms=app_platforms,
                      path=pyjs.path,
                      js_libs=options.js_includes,
                      unlinked_modules=options.unlinked_modules,
                      keep_lib_files=options.keep_lib_files,
                      compile_inplace=options.compile_inplace,
                      translator_arguments=translator_arguments,
                      multi_file=options.multi_file,
                      cache_buster=options.cache_buster,
                      bootstrap_file=options.bootstrap_file,
                      apploader_file=options.apploader_file,
                      public_folder=options.public_folder,
                      runtime_options=runtime_options,
                      list_imports=options.list_imports,
                     )
    l()

    if not options.list_imports:
        print "Built to :", os.path.abspath(options.output)
        return
    print "Dependencies"
    for f, deps in l.dependencies.items():
        print "%s\n%s" % (f, '\n'.join(map(lambda x: "\t%s" % x, deps)))
    print
    print "Visited Modules"
    for plat, deps in l.visited_modules.items():
        print "%s\n%s" % (plat, '\n'.join(map(lambda x: "\t%s" % x, deps)))
    print


def build_script():
    usage = """usage: %prog [OPTIONS...] APPLICATION [MODULE...]

Command line interface to the pyjs.org suite: Python Application -> AJAX Application.
APPLICATION is the translation entry point; it MUST be importable by the toolchain.
MODULE(s) will also translate, if available; they MUST be importable by the toolchain."""
    global app_platforms

    parser = OptionParser(usage=usage, epilog='For more information, see http://pyjs.org/')
    parser_group_builder = OptionGroup(parser, 'Builder',
                                      'Configures the high-level properties of current '
                                      'command and final project assembly.')
    parser_group_trans = OptionGroup(parser, 'Translator',
                                    'Configures the semantics/expectations of '
                                    'application code. Each --enable-* implies '
                                    '--disable-*. Groups modify several options at once.')
    parser_group_linker = OptionGroup(parser, 'Linker',
                                      'Configures the includes/destination of application '
                                      'code, static resources, and project support files.')
    add_builder_options(parser_group_builder)
    translator.add_compile_options(parser_group_trans)
    linker.add_linker_options(parser_group_linker)
    parser.add_option_group(parser_group_builder)
    parser.add_option_group(parser_group_trans)
    parser.add_option_group(parser_group_linker)

    options, _args = parser.parse_args()
    args = []
    for a in _args:
        if a.lower().endswith('.py'):
            args.append(a[:-3])
        else:
            args.append(a)

    if options.log_level is not None:
        import logging
        logging.basicConfig(level=options.log_level)
    if len(args) < 1:
        parser.error("incorrect number of arguments in %s" % repr((sys.argv, options, _args)))

    top_module = args[0]
    for d in options.library_dirs:
        pyjs.path.append(os.path.abspath(d))

    if options.platforms:
       app_platforms = options.platforms.lower().split(',')

    if options.multi_file and options.compile_inplace:
        options.compile_inplace = False

    runtime_options = []
    runtime_options.append(("arg_ignore", options.function_argument_checking))
    runtime_options.append(("arg_count", options.function_argument_checking))
    runtime_options.append(("arg_is_instance", options.function_argument_checking))
    runtime_options.append(("arg_instance_type", options.function_argument_checking))
    runtime_options.append(("arg_kwarg_dup", options.function_argument_checking))
    runtime_options.append(("arg_kwarg_unexpected_keyword", options.function_argument_checking))
    runtime_options.append(("arg_kwarg_multiple_values", options.function_argument_checking))
    runtime_options.append(("dynamic_loading", (len(options.unlinked_modules)>0)))

    build(top_module, pyjs, options, app_platforms,
          runtime_options, args)

    if not options.auto_build:
        sys.exit(0)

    # autobuild starts here: loops round the current directory file structure
    # looking for file modifications.  extra files in the public folder are
    # copied to output, verbatim (without a recompile) but changes to python
    # files result in a recompile with the exact same compile options.

    first_loop = True

    public_dir = options.public_folder
    output_dir = options.output

    serve(top_module)

    while True:
        for root, dirs, files in os.walk('.'):
            if root[2:].startswith(output_dir):
                continue
            if root[2:].startswith(public_dir):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    if is_modified(file_path) and not first_loop:
                        dest_path = output_dir
                        dest_path += file_path.split(public_dir, 1)[1]
                        dest_dir = os.path.dirname(dest_path)
                        if not os.path.exists(dest_dir):
                            os.makedirs(dest_dir)
                        print('Copying %s to %s' % (file_path, dest_path))
                        shutil.copy(file_path, dest_path)
            else:
                for filename in files:
                    if os.path.splitext(filename)[1] in ('.py',):
                        file_path = os.path.join(root, filename)
                        if is_modified(file_path) and not first_loop:
                            try:
                              build(top_module, pyjs, options,
                                    app_platforms, runtime_options, args)
                            except Exception:
                              traceback.print_exception(*sys.exc_info())
                            break
        first_loop = False
        time.sleep(1)


mappings = options.Mappings()
add_builder_options = mappings.bind
get_builder_options = mappings.link


mappings.log_level = (
    ['-v', '--verbosity'],
    ['-l', '--log-level'],
    [],
    dict(help='numeric Python logging level',
         type='int',
         metavar='LEVEL')
)
mappings.platforms = (
    ['-P', '--platforms'],
    [],
    [],
    dict(help='comma-separated list of target platforms',
         default=(','.join(AVAILABLE_PLATFORMS)))
)
mappings.list_imports = (
    ['--list-imports'],
    ['-i'],
    [],
    dict(help='list import dependencies (no translation)',
         default=False)
)
mappings.apploader_file = (
    ['--frame'],
    ['--apploader-file'],
    [],
    dict(help='application html loader file',
        type='string',
         metavar='FILE',
         default=None)
)
mappings.bootstrap_file = (
    ['--bootloader'],
    ['--bootstrap-file'],
    [],
    dict(help='application initial JS import/bootstrap code',
         metavar='FILE',
         default='bootstrap.js')
)
mappings.public_folder = (
    ['--resources'],
    ['--public-folder'],
    [],
    dict(help='application resource directory; contents copied to output dir',
         metavar='PATH',
         default='public')
)
mappings.auto_build = (
    ['--enable-rebuilds'],
    ['--auto-build', '-A'],
    [],
    dict(help='continuously rebuild on file changes',
         default=False)
)
mappings.cache_buster = (
    ['--enable-signatures'],
    ['--cache-buster', '-c'],
    [],
    dict(help='enable browser cache-busting; append md5 hashes to filenames',
         default=False)
)
mappings.compile_inplace = (
    ['--enable-compile-inplace'],
    ['--compile-inplace'],
    [],
    dict(help='store ouput JS in the same place as the Python source',
         default=False)
)
mappings.keep_lib_files = (
    ['--enable-preserve-libs'],
    ['--keep-lib-files'],
    [],
    dict(help='do not remove intermediate compiled JS libs',
        default=True)
)
