#!/usr/bin/env python2

import sys
from epydoc import cli
from os import path

out = path.dirname(path.abspath(__file__))

def gen_api_docs():
    sys.argv += [
        '--parse-only',
        '--name', 'Pyjs',
        '--url', 'http://pyjs.org',
        '-o', path.join(out, 'api'),
        '--exclude', 'pyjamas.raphael',
        '--exclude', 'pyjamas.selection',
        '--exclude', 'pyjamas.chart',
        '--exclude', 'pyjamas.Canvas',
        path.abspath(path.join(out, '..', 'library', 'pyjamas'))
    ]
    cli.cli()

if __name__ == '__main__':
    gen_api_docs()
