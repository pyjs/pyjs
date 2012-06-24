# -*- coding: utf-8 -*-


import sys
import os
import subprocess
import urllib
#import zlib
#import bz2
import zipfile
#import tarfile
import shutil
from optparse import OptionParser


ENV = None
OPTS = None
PATH = None
TARGETS = None
optparser = None


if not hasattr(str, 'format'):
    # Dirty implementation of str.format()
    # Ignores format_spec
    import __builtin__
    import re
    re_format = re.compile('((^{)|([^{]{))(((([a-zA-Z_]\w*)|(\d*))(([.][^.[]+?)|([[][^.[]+?[]]))*?))([!].)?(:[^}]*)?}')
    re_format_field = re.compile('([.][^.[]+)|([[][^.[]+[]]).*')
    class str(__builtin__.str):
        def format(self, *args, **kwargs):
            idx = [0]
            def sub(m):
                start_char = m.group(0)[0]
                if start_char == '{':
                    start_char = ''
                field = m.group(8)
                conversion = m.group(12)
                format_spec = m.group(13)
                if field is None:
                    field = m.group(7)
                    v = kwargs[field]
                else:
                    if field != '':
                        i = int(field)
                    else:
                        i = idx[0]
                        idx[0] += 1
                    v = args[i]
                s = m.group(4)
                s = s[len(field):]
                while s:
                    m = re_format_field.match(s)
                    name = m.group(1)
                    if name is not None:
                        v = getattr(v, name[1:])
                        s = s[len(name):]
                    else:
                        i = m.group(2)[1:-1]
                        s = s[len(i) + 2:]
                        try:
                            i = int(i)
                        except:
                            pass
                        v = v[i]
                if conversion is None or conversion == 's':
                    v = str(v)
                elif conversion == 'r':
                    v = repr(v)
                else:
                    raise ValueError("Unknown conversion character '%s'" % conversion)
                return start_char + v
            s = re_format.sub(sub, self)
            return s.replace('{{', '{').replace('}}', '}')
    __builtin__.str = str


PACKAGE = {
    'title': 'example',
    'desc': 'default description',
}

INDEX = {
    'example': r'''
        <!-- start {name} {{example.{name}._comment_end}}
        <tr>{{example.{name}.demo1}}

            <td rowspan="{{example.{name}.numdemos}}">
                {{example.{name}.desc}}
            </td>

            <td rowspan="{{example.{name}.numdemos}}">
               <a id="pyicon" href="https://github.com/pyjs/pyjs/tree/master/examples/{name}/"></a>
            </td>
        </tr>
        {{example.{name}.demos}}
        {{example.{name}._comment_start}} -->
    ''',
    'demo': r'''
        <td><a href="{target}.html">{title}</a></td>
    ''',
}


class _e(object):

    _ident = 'example'

    _special = {
        '_comment_start': '<!--',
        '_comment_end': '-->',
    }

    def __init__(self, examples=None, **kwds):
        if examples is None:
            self._examples = kwds
        else:
            self._examples = examples
            self._examples.update(kwds)
        self._path = [self._ident]

    def __repr__(self):
        return '_e(%s)' % repr(self.__str__())

    def __str__(self):
        try:
            curr = self._examples
            for frag in self._path[1:]:
                curr = curr[frag]
        except KeyError:
            if frag in self._special:
                curr = self._special[frag]
            else:
                curr = '{%s}' % '.'.join(self._path)
        self._path[1:] = []
        return curr

    def __getattr__(self, name):
        self._path.append(name)
        return self


def _find_python():
    if sys.version_info[0] == 2 and sys.executable and os.path.isfile(sys.executable):
        return sys.executable
    for python in ('python2', 'python2.7', 'python2.6'):
        try:
            subprocess.call([python, '-c', '"raise SystemExit"'])
            return python
        except OSError:
            pass
    return 'python'


def _list_examples():
    examples = [
        example
        for example in os.listdir(ENV['DIR_EXAMPLES'])
        if os.path.isfile(os.path.join(ENV['DIR_EXAMPLES'], example, '__main__.py'))
            and not example.startswith('_')
    ]
    examples.sort()
    return examples


def _process_pyjamas(root):
    lim = 3
    while lim > 0:
        root = os.path.join(root, '..')
        boot = os.path.join(root, 'bootstrap.py')
        if os.path.isfile(boot):
            root = os.path.abspath(root)
            boot = os.path.abspath(boot)
            if sys.platform == 'win32':
                pyjsbuild = os.path.join(root, 'bin', 'pyjsbuild.py')
            else:
                pyjsbuild = os.path.join(root, 'bin', 'pyjsbuild')
            break
        lim = lim - 1
    if lim == 0:
        raise RuntimeError('Unable to locate pyjamas root.')
    # Bootstrap on test failure; attempts to fix a couple issues at once
    null = open(os.devnull, 'wb')
    try:
        if subprocess.call(['python', pyjsbuild], cwd=root, stdout=null, stderr=subprocess.STDOUT) > 0:
            raise OSError
    except OSError:
        subprocess.call(['python', boot], cwd=root, stdout=null, stderr=subprocess.STDOUT)
    return {
        'DIR_PYJAMAS': root,
        'BASE_EXAMPLES': os.path.join(root, 'examples'),
        'BIN_PYJSBUILD': pyjsbuild,
    }


def _process_environ():
    return dict([
        (k[5:], v[:])
        for k, v in os.environ.items()
        if k.startswith('PYJS')
    ])



def _process_args(args):
    return {'ARG_PYJSBUILD': args or ['-O']}


def _process_path(targets, target):
    path = PATH
    if isinstance(targets, dict):
      	if 'path' in targets[target]:
            path = targets[target]['path']
            if not path.startswith(os.sep):
                path = os.path.join(PATH, path)
    return path

def get_optparser(**kwargs):
    global optparser
    if optparser is None:
        optparser = OptionParser(**kwargs)
        add_option = optparser.add_option
        add_option(
            '--download',
            dest='download',
            action='store_true',
            default=False,
            help='permit downloads of files or libraries',
        )
        add_option(
            '--misc',
            dest='misc',
            action='store_true',
            default=False,
            help='build miscellaneous examples',
        )
        add_option(
            '--deprecated',
            dest='deprecated',
            action='store_true',
            default=False,
            help='build deprecated examples',
        )
    return optparser


def init(path):
    global ENV, PATH, OPTS
    optparser = get_optparser()
    opts, args = optparser.parse_args()
    OPTS=opts
    PATH = path
    ENV = {}
    ENV.update(_process_environ())
    ENV.update(_process_args(args))
    if 'BIN_PYTHON' not in ENV:
        ENV['BIN_PYTHON'] = _find_python()
    if 'DIR_PYJAMAS' not in ENV:
        ENV.update(_process_pyjamas(path))
    if 'DIR_EXAMPLES' not in ENV:
        ENV['DIR_EXAMPLES'] = os.path.dirname(path)
    ENV['NAME_EXAMPLE'] = os.path.basename(path)
    ENV['DIR_EXAMPLE'] = path


def download(downloads):
    for download in downloads:
        url = download['url']
        dst = download['dst']
        if not os.path.exists(dst):
            if not OPTS.download:
                raise TypeError('Downloads not permitted. Use --download option to permit')
            urllib.urlretrieve(url, dst)
            if download.get('unzip'):
                path = download.get('path', os.path.dirname(dst))
                z = zipfile.ZipFile(dst)
                z.extractall(path)


def setup(targets):
    for target in targets:
        downloads = None
        path = _process_path(targets, target)
        if isinstance(targets, dict):
            downloads = targets[target].get('downloads')
        if not os.path.isfile(os.path.join(path, target)):
            raise TypeError('Target `%s` does not exist.' % target)
        if downloads:
            download(downloads)
    global TARGETS
    TARGETS = targets


def translate():
    for target in TARGETS:
        args = [target]
        if isinstance(TARGETS, dict):
            opts = TARGETS[target].get('options', [])
            args += TARGETS[target].get('additional_args', [])
        else:
            opts = []
        opts += ['--enable-strict',
                 '--enable-signatures',
                 '--enable-preserve-libs',
                 '--disable-debug',
                 '--dynamic-link',
                 '-o', '../__output__']
        cmd = [ENV['BIN_PYTHON'], ENV['BIN_PYJSBUILD']] + ENV['ARG_PYJSBUILD'] + opts + args

        if not [ENV['ARG_PYJSBUILD']] + opts + args:
            raise RuntimeError(cmd)
        path = _process_path(TARGETS, target)
        e = subprocess.Popen(cmd, cwd=path)
        ret = e.wait()


def install(package=None, **packages):
    if package is not None:
        PACKAGE.update(package)
        name = ENV['NAME_EXAMPLE']

        if len(TARGETS) == 1:
           demos = [
               str(INDEX['demo']).format(name=name, target=target[:-3], 
                                         title=PACKAGE['title'])
               for target in TARGETS
           ]
        else:
           demos = [
               str(INDEX['demo']).format(name=name, target=target[:-3], 
                                         title=target[:-3])
               for target in TARGETS
           ]

        example = {
            'name': name,
            'title': PACKAGE['title'],
            'desc': PACKAGE['desc'],
            'numdemos' : '%s' % len(demos),
            'demo1' : demos[0],
            'demos': ''.join(['<tr>%s</tr>' % _s for _s in demos[1:]]),
        }
        if 'OPT_PROXYINSTALL' in ENV:
            sys.stdout.write(repr(example))
            sys.stdout.flush()
            return
        packages[name] = example
    if not packages:
        raise TypeError('Nothing to install.')
    index = os.path.join(ENV['DIR_EXAMPLES'], '__output__', 'index.html')
    try:
        if os.path.isfile(index):
            idx_out_fd = open(index, 'r+')
            index_orig = tpl = idx_out_fd.read()
            idx_out_fd.seek(0)
            idx_out_fd.truncate()
        else:
            idx_out_fd = open(index, 'w')
            index_orig = tpl = None
        if tpl is None or '<style>' in tpl:
            examples = ''.join([
                str(INDEX['example']).format(name=example)
                for example in _list_examples()
            ])

            _src='''<div id="pyjsdemos">
                    <table>
                    <thead>
                    <tr><th>Demo</th><th>Description</th><th>Source Code</th></tr>
                    </thead>
                    <tbody>%s</tbody></table></div>'''

            examples = _src % examples

            index_tpl = os.path.join(ENV['BASE_EXAMPLES'], '_examples', 'template', 'index.html.tpl')
            idx_in_fd = open(index_tpl, 'r')
            tpl = str(idx_in_fd.read()).format(examples)
        index_new = str(tpl).format(example=_e(packages))
    except:
        if index_orig is None:
            idx_out_fd.close()
            os.unlink(index)
        else:
            idx_out_fd.write(index_orig)
        raise
    else:
        idx_out_fd.write(index_new)
    finally:
        idx_out_fd.close()


    _static_dir = os.path.join(ENV['BASE_EXAMPLES'], '_examples', 'static')
    _output_dir = os.path.join(ENV['BASE_EXAMPLES'], '__output__', 'static')

    if not os.path.exists(_output_dir):
        try:
           shutil.copytree(_static_dir, _output_dir)
        except Exception, e:
           sys.stdout.write("Error copying static directory to output directory\n")
           sys.stdout.write("%s\n" % e)
