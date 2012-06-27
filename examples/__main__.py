#!/usr/bin/env python
# -*- coding: utf-8 -*-


import os
import sys
import subprocess

from _examples import util

try:
    from __builtin__ import str # In case str is redefined in util
except ImportError:
    pass

usage = '''usage: %prog [options] -- [translator options]'''
argv = sys.argv
optparser = util.get_optparser(usage=usage)
opts, args = optparser.parse_args()

head = os.path.dirname(__file__)
if not head:
    head = '.'
paths = [head]
if opts.misc:
    paths.append(os.path.join(head, 'misc'))
if opts.deprecated:
    paths.append(os.path.join(head, 'deprecated'))

for path in paths:
    examples = [
        example
        for example in os.listdir(path)
            if os.path.isfile(os.path.join(path, example, '__main__.py'))
                and not example.startswith('_')
    ]
    examples.sort()

    env = os.environ.copy()
    # Not ready yet
    #env['PYJS_OPT_PROXYINSTALL'] = '1'
    if 'PYJS_BIN_PYTHON' not in env:
        env['PYJS_BIN_PYTHON'] = util._find_python()
    if 'PYJS_DIR_PYJAMAS' not in env:
        env.update(dict([
            ('PYJS_' + k, v)
            for k, v in util._process_pyjamas(head).items()
        ]))

    for example in examples:
        header = '\n' + str('( Building {0} )').format(example.upper()).center(69, '-') + '\n\n'
        sys.stdout.write(header)
        sys.stdout.flush()
        if sys.version_info[0] <= 2 and sys.version_info[1] <= 5:
            cmd = os.path.join(path, example, '__main__.py')
        else:
            cmd = os.path.join(path, example)
        e = subprocess.Popen([env['PYJS_BIN_PYTHON'], cmd] + sys.argv[1:], env=env)
        e.wait()

complete = [
    '\n' + '( Pyjs )'.center(69, '-') + '\n',
    '  Complete! View examples via:',
    str('  # cd {0}/__output__').format(path),
    str('  # {0} -m SimpleHTTPServer').format(env['PYJS_BIN_PYTHON']),
    '  http://localhost:8000',
    '\n' + '( Pyjs )'.center(69, '-') + '\n\n',
]

sys.stdout.write('\n'.join(complete))
