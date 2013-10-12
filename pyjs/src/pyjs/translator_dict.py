#!/usr/bin/env python

import sys
import os
import re

from lib2to3.pgen2.driver import Driver
from lib2to3 import pygram, pytree
from lib2to3.pytree import Node, Leaf, type_repr
from lib2to3.pygram import python_symbols

def sym_type(name):
    return getattr(python_symbols, name)

def new_node(name):
    return Node(sym_type(name), [])

import __Pyjamas__
from __Future__ import __Future__


# This is taken from the django project.
# Escape every ASCII character with a value less than 32.
JS_ESCAPES = (
    ('\\', r'\x5C'),
    ('\'', r'\x27'),
    ('"', r'\x22'),
    ('>', r'\x3E'),
    ('<', r'\x3C'),
    ('&', r'\x26'),
    (';', r'\x3B')
    ) + tuple([('%c' % z, '\\x%02X' % z) for z in range(32)])

def escapejs(value):
    """Hex encodes characters for use in JavaScript strings."""
    for bad, good in JS_ESCAPES:
        value = value.replace(bad, good)
    return value

re_js_string_escape = ''.join([chr(i) for i in range(32)])
re_js_string_escape += '''\\\\"'<>&;'''
re_js_string_escape = re.compile("[%s]" % re_js_string_escape)
re_int = re.compile('^[-+]?[0-9]+$')
re_long = re.compile('^[-+]?[0-9]+[lL]$')
re_hex_int = re.compile('^[-+]?0x[0-9a-fA-F]+$')
re_hex_long = re.compile('^[-+]?0x[0-9a-fA-F]+[lL]$')
re_oct_int = re.compile('^[-+]?0[0-8]+$')
re_oct_long = re.compile('^[-+]?0[0-8]+[lL]$')


builtin_names = [
    'ArithmeticError',
    'AssertionError',
    'AttributeError',
    'BaseException',
    'BufferError',
    'BytesWarning',
    'DeprecationWarning',
    'EOFError',
    'Ellipsis',
    'EnvironmentError',
    'Exception',
    'False',
    'FloatingPointError',
    'FutureWarning',
    'GeneratorExit',
    'IOError',
    'ImportError',
    'ImportWarning',
    'IndentationError',
    'IndexError',
    'KeyError',
    'KeyboardInterrupt',
    'LookupError',
    'MemoryError',
    'NameError',
    'None',
    'NotImplemented',
    'NotImplementedError',
    'OSError',
    'OverflowError',
    'PendingDeprecationWarning',
    'ReferenceError',
    'RuntimeError',
    'RuntimeWarning',
    'StandardError',
    'StopIteration',
    'SyntaxError',
    'SyntaxWarning',
    'SystemError',
    'SystemExit',
    'TabError',
    'True',
    'TypeError',
    'UnboundLocalError',
    'UnicodeDecodeError',
    'UnicodeEncodeError',
    'UnicodeError',
    'UnicodeTranslateError',
    'UnicodeWarning',
    'UserWarning',
    'ValueError',
    'Warning',
    'ZeroDivisionError',
    '_',
    '__debug__',
    '__doc__',
    '__import__',
    '__name__',
    '__package__',
    'abs',
    'all',
    'any',
    'apply',
    'basestring',
    'bin',
    'bool',
    'buffer',
    'bytearray',
    'bytes',
    'callable',
    'chr',
    'classmethod',
    'cmp',
    'coerce',
    'compile',
    'complex',
    'copyright',
    'credits',
    'delattr',
    'dict',
    'dir',
    'divmod',
    'enumerate',
    'eval',
    'execfile',
    'exit',
    'file',
    'filter',
    'float',
    'format',
    'frozenset',
    'getattr',
    'globals',
    'hasattr',
    'hash',
    'help',
    'hex',
    'id',
    'input',
    'int',
    'intern',
    'isinstance',
    'issubclass',
    'iter',
    'len',
    'license',
    'list',
    'locals',
    'long',
    'map',
    'max',
    'min',
    'next',
    'object',
    'oct',
    'open',
    'ord',
    'pow',
    'print',
    'property',
    'quit',
    'range',
    'raw_input',
    'reduce',
    'reload',
    'repr',
    'reversed',
    'round',
    'set',
    'setattr',
    'slice',
    'sorted',
    'staticmethod',
    'str',
    'sum',
    'super',
    'tuple',
    'type',
    'unichr',
    'unicode',
    'vars',
    'xrange',
    'zip',
]

class TranslateOptions(object):

    def __init__(self, **kwargs):
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

    def __getattribute__(self, name):
        try:
            return object.__getattribute__(self, name)
        except:
            return None


class Name(object):

    def __init__(self, name, reflineno, glob=False, to_js=None):
        self.name = name
        self.reflineno = reflineno
        self.glob = glob
        self.to_js = to_js
        self.depth = None
        self.builtin = False

    def __str__(self):
        return "<Name %s %s %s>" % (self.name, self.reflineno, self.glob)

    def __repr__(self):
        return "<Name %s %s %s>" % (self.name, self.reflineno, self.glob)


class Names(dict):
    pass


class ClassNames(Names):
    pass


class AstNode(object):
    pass


class Argument(AstNode):

    def __init__(self, name, value=None):
        self.name = name
        self.value = value


class Attribute(AstNode):

    def __init__(self, name):
        self.name = name


class Code(AstNode):

    def __new__(cls, code, lineno):
        if code is None:
            return None
        return object.__new__(cls)

    def __init__(self, code, lineno):
        self.code = code
        self.lineno = lineno

    def __str__(self):
        if self.code is None:
            return None
        return str(self.code)

    def __repr__(self):
        if self.code is None:
            return None
        return repr(self.code)


class Decorator(AstNode):

    def __init__(self, name, lineno):
        self.name = name
        self.lineno = lineno


class Import(AstNode):

    def __init__(self, modname, assname=None, fromlist=None):
        self.modname = '.'.join(modname)
        if assname is None:
            self.assname = modname[0]
        else:
            self.assname = assname
        self.fromlist = fromlist


class Parameters(AstNode):

    def __init__(self, args, star_args, dstar_args, defaults):
        assert isinstance(args, list)
        self.args = []
        self.named_args = {}
        for arg in args:
            if not isinstance(arg, Argument):
                self.args.append(arg)
            else:
                if arg.name == '*':
                    assert star_args is None
                    star_args = arg.value
                    continue
                if arg.name == '**':
                    assert dstar_args is None
                    dstar_args = arg.value
                    continue
                self.named_args[arg.name] = arg.value
        if not self.named_args:
            self.named_args = None
        self.star_args = star_args
        self.dstar_args = dstar_args
        self.all_args = args[:]
        if star_args is not None:
            self.all_args.append(star_args)
        if dstar_args is not None:
            self.all_args.append(dstar_args)
        self.defaults = defaults


class Slice(AstNode):

    def __init__(self, items):
        assert isinstance(items, tuple)
        self.items = items

    def __str__(self):
        return 'Slice%s' % (self.items,)

    def __repr__(self):
        return 'Slice%s' % (self.items,)


leaf_type = {
    1: 'name',
    2: 'number',
    3: 'str',
}

# TODO: import this from mkbuiltin.py
func_type = {
    'function': 1,
    'staticmethod': 2,
    'classmethod': 3,
}

# TODO: import this from mkbuiltin.py
short_names = {
    'module': 'm$',
    'globals': 'g$',
    'locals': 'l$',
    'namestack': 'n$',
    'funcbase': 'f$',
    'builtin': 'B$',
    'constants': 'C$',
    'None': 'N$',
    'True': 'T$',
    'False': 'F$',
}

op_names1 = {
    'inv': 'op_inv',
    'neg': 'op_neg',
    'not': 'op_not',
}

op_names2 = {
    '+': 'op_add',
    '-': 'op_sub',
    '*': 'op_mul',
    '/': 'op_div', # set to op_truediv with 'from __future__ import division'
    '//': 'op_floordiv',
    '%': 'op_mod',
    '**': 'op_pow',
    '&': 'op_bitand',
    '|': 'op_bitor',
    '^': 'op_bitxor',
    '<<': 'op_bitlshift',
    '>>': 'op_bitrshift',
    '+=': 'op_add',
    '-=': 'op_sub',
    '*=': 'op_mul',
    '/=': 'op_div',
    '//=': 'op_floordiv',
    '%=': 'op_mod',
    '**=': 'op_pow',
    '&=': 'op_bitand',
    '|=': 'op_bitor',
    '^=': 'op_bitxor',
    '<<=': 'op_bitlshift',
    '>>=': 'op_bitrshift',
}

op_compare = {
    'is': 'op_is',
    'is not': 'op_is_not',
    '==': 'op_eq',
    '!=': 'op_ne',
    '<': 'op_lt',
    '<=': 'op_le',
    '>': 'op_gt',
    '>=': 'op_ge',
    'in': 'op_in',
    'not in': 'op_not_in',
}

class Translator(object):

    jsvars = {
        'module_store': '$pyjs.loaded_modules',
        # Internals
        'catch': 'e$',
        'catchclass': 'e$cls',
        'module': 'm$',
        'globals': 'g$',
        'locals': 'l$',
        'funcbase': 'f$',
        'builtin': 'B$',
        'constants': 'C$',
        #'__builtin__': '__builtin__',
        '__builtin__': '__builtin__',
        'track': '$pyjs.track',

        # Short names
        'fcall': '_f',
        'fcallext': '_fe',
        'mcall': '_m',
        'mcallext': '_me',
        'getattr': '_ga',
        'setattr': '_sa',
        'getitem': '_i',
        'booljs': '_b',
        'str': 's$',
        'int': 'i$',
        'bool': 'b$',
        'None': 'N$',
        'True': 'T$',
        'False': 'F$',

        # References to builtins
        'try_else': "B$['TryElse']",
        'dict': "B$['dict']",
        'list': "B$['list']",
        'tuple': "B$['tuple']",
    }
    jsvars.update(short_names)
    indent_str = '\t'
    __future__ = __Future__()

    class TranslationError(RuntimeError):
        filename = None

        def __init__(self, msg, lineno=None, filename=None):
            self.msg = msg
            self.lineno = lineno
            if filename is not None:
                self.filename = filename

        def __str__(self):
            return "TranslationError in %s at line %s: %s" % (
                self.filename, self.lineno, self.msg,
            )

        def __repr__(self):
            return "<TranslationError %s,%s: %s" % (
                self.filename, self.lineno, self.msg,
            )


    def __init__(self, srcfile, module_name, options):
        #sys.stderr.write('module_name: %s\n' % module_name)
        self.op_names2 = op_names2.copy()
        self.lines = []
        self.imported_modules = {}
        self.imported_js = {}
        self.indent_level = 0
        self.depth = 0
        self.names = [Names()]
        self.const_int = {}
        self.const_long = {}
        self.const_float = {}
        self.const_str = {}
        self.tmp_jsname = {}
        self.assign_state = False
        self.inloop = 0
        self.next_func_type = [func_type['function']]
        self.last_lineno = 0
        self.jsvars = self.jsvars.copy()
        self.srcfile = srcfile
        self.tree = None
        self.driver = None
        self.TranslationError.filename = srcfile
        if not module_name:
            module_name, extension = os.path.splitext(os.path.basename(srcfile))
        self.jsvars['module_name'] = module_name
        self.options = TranslateOptions(**options)

    def ast_tree_creator(self, srcfile=None):
        if srcfile is None:
            srcfile = self.srcfile
        if self.driver is None:
            self.driver = Driver(pygram.python_grammar, pytree.convert)
        return self.driver.parse_file(srcfile)

    def tree_merge(self, dst, src, flags=None):
        if flags and 'FULL_OVERRIDE' in flags:
            return src
        for child in src.children:
            if isinstance(child, Node):
                if type_repr(child.type) == 'funcdef':
                    self.tree_replace_function(dst, child)
                elif type_repr(child.type) == 'classdef':
                    self.tree_merge_class(dst, child)
        return dst

    def tree_merge_class(self, dst, src):
        if isinstance(src.children[0], Leaf) and \
           src.children[0].value == 'class' and \
           isinstance(src.children[1], Leaf) and \
           isinstance(src.children[-1], Node):
            class_name = src.children[1].value
            if type_repr(src.children[-1].type) == 'suite':
                src_children = src.children[-1].children
            else:
                src_children = [src.children[-1]]
        else:
            raise self.TranslationError(
                "Cannot merge class %r" % src
            )
        for dst_child in dst.children:
            if type_repr(dst_child.type) == 'classdef' and \
               dst_child.children[0].value == 'class' and \
               isinstance(dst_child.children[1], Leaf) and \
               dst_child.children[1].value == class_name and \
               isinstance(dst_child.children[-1], Node) and \
               type_repr(dst_child.children[-1].type) == 'suite':
                dst_node = dst_child.children[-1]
                for src_child in src_children:
                    if type_repr(src_child.type) == 'funcdef':
                        self.tree_replace_function(dst_node, src_child)
                    elif type_repr(src_child.type) == 'simple_stmt':
                        self.tree_replace_stmt(dst_node, src_child)
                return
        raise self.TranslationError(
            "Cannot find class %r for merge" % class_name
        )

    def tree_replace_function(self, dst, func_node):
        if isinstance(func_node.children[0], Leaf) and \
           func_node.children[0].value == 'def' and \
           isinstance(func_node.children[1], Leaf):
            func_name = func_node.children[1].value
        else:
            raise self.TranslationError(
                "Cannot replace function %r" % func_node
            )
        for child in dst.children:
            if isinstance(child, Node) and \
               type_repr(child.type) == 'funcdef':
                if isinstance(child.children[0], Leaf) and \
                   child.children[0].value == 'def' and \
                   isinstance(func_node.children[1], Leaf) and \
                   child.children[1].value == func_name:
                    child.children = func_node.children
                    child.changed()
                    return
        # Next two lines will append a function if it's not found,
        # but that's different behavior then in the other translator
        #dst.append_child(func_node)
        #return
        raise self.TranslationError(
            "Cannot find function %r for replace" % func_name
        )

    def tree_replace_stmt(self, dst, stmt_node):
        if isinstance(stmt_node.children[0], Leaf):
            if stmt_node.children[0].value == 'pass':
                return
        else:
            node = stmt_node.children[0]
            if type_repr(node.type) == 'expr_stmt':
                if isinstance(node.children[0], Leaf) and \
                   isinstance(node.children[1], Leaf) and \
                   node.children[1].value == '=':
                    for child in dst.children:
                        if isinstance(child, Node) and \
                           type_repr(child.type) == 'simple_stmt' and \
                           isinstance(child.children[0], Node) and \
                           type_repr(child.children[0].type) == 'expr_stmt':
                            dst_node = child.children[0]
                            if isinstance(dst_node.children[0], Leaf) and \
                               isinstance(dst_node.children[1], Leaf) and \
                               dst_node.children[1].value == '=' and \
                               dst_node.children[0].value == node.children[0].value:
                                dst_node.children = node.children
                                dst_node.changed()
                                return
                    dst.append_child(stmt_node)
                    return
        raise self.TranslationError(
            "Cannot replace or merge statement %r" % stmt_node
        )

    def dispatch_file(self, tree):
        if isinstance(tree, Leaf):
            assert tree.value == '', self.TranslationError(repr(tree.value), self.get_lineno(tree))
            tree = new_node('file_input')
        return self.dispatch(tree)

    def get_javascript(self):
        code = []
        for indent_level, line in self.lines:
            code.append(
                '%s%s' % (
                    self.indent_str * indent_level,
                    line,
                )
            )
        return '\n'.join(code)

    def add_import(self, modname, fromlist=None):
        # Refuse to report pyjslib as imported module
        if modname == 'pyjslib':
            return
        if fromlist is None:
            fromlist = [None]
        fl = self.imported_modules.get(modname, None)
        if fl is None:
            self.imported_modules[modname] = fromlist
            for f in fromlist:
                if f is not None:
                    self.add_import("%s.%s" % (modname, f))
        else:
            for f in fromlist:
                if not f in fl:
                    fl.append(f)
                    if f is not None:
                        self.add_import("%s.%s" % (modname, f))

    def indent(self, n=1):
        self.indent_level += n
        return self.indent_level

    def dedent(self, n=1):
        indent_level = self.indent_level
        self.indent_level -= n
        assert self.indent_level >= 0, self.TranslationError("indent_level: %d" % self.indent_level, self.get_lineno(self.last_lineno))
        return indent_level

    def get_lineno(self, node):
        if getattr(node, 'lineno', None) is not None:
            return node.lineno
        #if isinstance(node, Leaf) or isinstance(node, Code):
        #    return node.lineno
        for child in node.children:
            if getattr(child, 'lineno', None) is not None:
                return child.lineno
            #if isinstance(child, Leaf) or isinstance(child, Code):
            #    return child.lineno
            lineno = self.get_lineno(child)
            if lineno is not None:
                return lineno

    def track_lineno(self, node):
        return self.get_lineno(node)

    def add_lines(self, lines, lineno=None, split=True):
        if lineno != None:
            track = "%(track)s['lineno'] = " % self.jsvars
            while len(self.lines) > 0 and \
                  self.lines[-1][1].strip().startswith(track):
                self.lines.pop()
            line = lines[0]
            level = self.indent_level
            if line and line[0] == '+':
                while line[0] == '+':
                    level += 1
                    line = line[1:]
            self.lines.append([level, '%s%s;' % (track, lineno)])
        if split:
            lines = lines.split("\n")
        for line in lines:
            level = self.indent_level
            if line and line[0] == '+':
                while line[0] == '+':
                    level += 1
                    line = line[1:]
                line = line.lstrip()
            self.lines.append([level, line])

    def add_name(self, name, reflineno=None, glob=False, to_js=None, force=False):
        #if not force and self.assign_state is False:
        #    return
        if not force and \
           (self.assign_state is False and \
            isinstance(self.names[-1], ClassNames)):
            return
        depth = 0
        for names in self.names:
            if not isinstance(names, ClassNames):
                depth += 1
        if name in self.names[-1]:
            _name = self.names[-1][name]
            if reflineno is None and len(self.names) > 1 and \
               not _name.glob and _name.reflineno is not None and \
               _name.depth == depth and force is False:
                print _name.name, _name.reflineno, _name.glob, _name.depth, len(self.names) - 1
                reflineno = _name.reflineno
                _name.reflineno = None
                raise self.TranslationError(
                    "Local variable '%s' referenced before assignment at line %s" % (name, reflineno)
                )
        else:
            done = []
            if len(self.names) == 1:
                _name = Name(name, reflineno, glob, to_js)
                _name.depth = 1
            elif reflineno is not None:
                _name = None
                names = self.names[:-1]
                while len(names):
                    if name in names[-1]:
                        _name = names[-1][name]
                        break
                    done.append(names.pop())
                if _name is None:
                    _name = Name(name, reflineno, to_js=to_js)
                    _name.depth = 1
            else:
                _name = Name(name, reflineno, glob, to_js)
                _name.depth = depth
                #_name.depth = 0
                #for names in self.names:
                #    if not isinstance(names, ClassNames):
                #        _name.depth += 1
            if reflineno is not None and _name.depth == 0:
                if not _name.builtin and name in builtin_names:
                    _name.builtin = True
            if not force and self.assign_state is False and \
               _name.depth == 1 and \
               len(self.names) > 1:
                return
            while len(done):
                done[-1][name] = _name
                done.pop()
            self.names[-1][name] = _name

    def get_names_depth(self, skip_class_names=True):
        depth = 0
        for names in self.names:
            if skip_class_names and isinstance(names, ClassNames):
                continue
            depth += 1
        return depth

    def get_jsname(self, name):
        if isinstance(name, Code):
            return str(name)
        jsvars = self.jsvars.copy()
        jsvars.update(name=name)
        jsname = None
        if name in self.names[-1]:
            if self.names[-1][name].to_js is not None:
                return self.names[-1][name].to_js
            if not self.names[-1][name].glob:
                if isinstance(self.names[-1], ClassNames):
                    jsname = """\
%(funcbase)s['$dict'][%(name)r]""" % jsvars
                else:
                    jsname = "%(locals)s[%(name)r]" % jsvars
                jsvars.update(jsname=jsname)
        else:
            for names in self.names[1:-1]:
                if isinstance(names, ClassNames):
                    continue
                if name in names:
                    if isinstance(self.names[-1], ClassNames):
                        cn = self.names.pop()
                    else:
                        cn = None
                    self.add_name(name)
                    jsname = self.get_jsname(name)
                    if cn is not None:
                        self.names.append(cn)
                    return jsname
        if jsname is None:
            if name in ['globals', 'locals']:
                src = "%%(%s)s" % name
                return ("%(builtin)s['%(name)s'](" + src + ")") % jsvars
            if name in self.names[0] and self.names[0][name].to_js is not None:
                return self.names[0][name].to_js
            jsname = '%(globals)s[%(name)r]' % (jsvars)
        if self.options.check_defined:
            return "(typeof %(jsname)s != 'undefined' ? %(jsname)s : %(builtin)s['UnboundLocalError'](%(name)r)" % jsvars
        return jsname

    def get_tmp_jsname(self, prefix):
        if not prefix in self.tmp_jsname:
            self.tmp_jsname[prefix] = 1
        else:
            self.tmp_jsname[prefix] += 1
        return '%s%d' % (prefix, self.tmp_jsname[prefix])

    def add_const_int(self, value):
        value = str(value)
        if not value in self.const_int:
            name = '%s.i%d' % (
                self.jsvars['constants'],
                len(self.const_int),
            )
            self.const_int[value] = name
        return self.const_int[value]

    def add_const_long(self, value):
        value = str(long(value))
        if not value in self.const_long:
            name = '%s.l%d' % (
                self.jsvars['constants'],
                len(self.const_long),
            )
            self.const_long[value] = name
        return self.const_long[value]

    def add_const_float(self, value):
        if not value in self.const_float:
            name = '%s.f%d' % (
                self.jsvars['constants'],
                len(self.const_float),
            )
            self.const_float[value] = name
        return self.const_float[value]

    def add_const_str(self, value):
        if not value in self.const_str:
            name = '%s.s%d' % (
                self.jsvars['constants'],
                len(self.const_str),
            )
            self.const_str[value] = name
        return self.const_str[value]

    def assert_value(self, node, value, expected_value):
        if isinstance(expected_value, list) or \
           isinstance(expected_value, tuple):
            assert value in expected_value, self.TranslationError(
                "one of %r expected, got '%s'" % (expected_value, value),
                self.get_lineno(node),
            )
        else:
            assert value == expected_value, self.TranslationError(
                "%r expected, got '%s'" % (expected_value, value),
                self.get_lineno(node),
            )

    def assert_type(self, node, type_, expected_type):
        type_ = type_repr(type_)
        assert type_ == expected_type, self.TranslationError(
            "'%s' expected, got '%s'" % (expected_type, type_),
            self.get_lineno(node),
        )

    def assert_instance(self, node, inst, expected_class):
        assert isinstance(inst, expected_class), self.TranslationError(
            "instance of '%s' expected, got '%r'" % (expected_class.__name__, inst),
            self.get_lineno(node),
        )

    def assert_dedent(self, level, expected_level):
        assert level == expected_level, self.TranslationError(
            "expected dedent %s, got %s" % (expected_level, level),
            self.last_lineno,
        )


    def dispatch(self, x, assign=False):
        if isinstance(x, Code):
            return x
        assign_state = self.assign_state
        if assign:
            self.assign_state = assign
        lineno = self.get_lineno(x)
        if lineno is not None:
            self.last_lineno = lineno
        else:
            lineno = self.last_lineno
        try:
            if isinstance(x, Node):
                visit = getattr(self, 'node_%s' % type_repr(x.type), None)
                if visit is None:
                    raise self.TranslationError("No name for node type %s at %r" % (x.type, x))
            else:
                visit = getattr(self, 'leaf_%s' % type_repr(x.value), None)
                if visit is None:
                    if x.type in leaf_type:
                        visit = getattr(self, 'leaftype_%s' % leaf_type.get(x.type), None)
                    if visit is None:
                        if x.value in ['', '\n', '\r\n', ';']:
                            self.assign_state = assign_state
                            return
                        raise self.TranslationError("No name for leaf type %s at %r" % (x.type, x))
            code = visit(x)
            self.assign_state = assign_state
            return code
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            if isinstance(exc_value, self.TranslationError):
                if exc_value.lineno is None:
                    exc_value.lineno = lineno
                raise
            else:
                print "Error in %s at %s:" % (self.srcfile, lineno)
                raise

    def not_implemented(self, node):
        print repr(node)
        print dir(node)
        raise NotImplementedError(repr(node))

    def get_test(self, node, name=None):
        #print 'get_test:', repr(node)
        if isinstance(node, Node):
            t = type_repr(node.type)
            if t in ['and_test', 'or_test', 'not_test']:
                if name is None:
                    return getattr(self, 'node_%s' % t)(node, True)
                return getattr(self, 'node_%s' % t)(node, name=name)
            elif t in ['comparison']:
                test = self.dispatch(node)
                if name is None:
                    return "%s.valueOf()" % test
                else:
                    return "(%s=%s).valueOf()" % (name, test)
        test = self.dispatch(node)
        if name is None:
            return "%s(%s)" % (self.jsvars['booljs'], test)
        return "%s(%s=%s)" % (self.jsvars['booljs'], name, test)

    def get_bit_expr(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        args = [self.dispatch(childs.next())]
        op = child = childs.next()
        while child is not None:
            op = child
            op_name = self.op_names2.get(op.value, None)
            if op is None:
                self.not_implemented(node)
            try:
                while True:
                    args.append(self.dispatch(childs.next()))
                    child = childs.next()
                    if child.value != op.value:
                        break
            except StopIteration:
                child = None
            if len(args) == 2:
                left, right = args
                jsvars.update(locals())
                code = "%(builtin)s['%(op_name)s2'](%(left)s, %(right)s)" % jsvars
            else:
                args = ', '.join(str(i) for i in args)
                jsvars.update(locals())
                code = "%(builtin)s['%(op_name)s']([%(args)s])" % jsvars
            args = [code]
        return code

    def get_op_item(self, node, op_item, op_slice):
        op = op_item
        if isinstance(node, Leaf) and \
           node.value == ':':
            what = Slice((
                self.add_const_int(0),
                self.add_const_int(2147483647),
            ))
        else:
            what = self.dispatch(node)
        if isinstance(what, Slice):
            slice = []
            for i in what.items:
                if i is None:
                    slice.append(self.jsvars['None'])
                else:
                    slice.append(i)
            what = "[%s]" % ', '.join(slice)
            op = op_slice
        return op, what

    def collect_locals(self, node):
        for child in node.children:
            if isinstance(child, Node):
                if type_repr(child.type) == 'funcdef':
                    self.add_name(child.children[1].value, force=True)
                elif type_repr(child.type) == 'classdef':
                    self.add_name(child.children[1].value, force=True)
                elif type_repr(child.type) == 'suite':
                    self.collect_locals(child)
                elif type_repr(child.type) == 'simple_stmt':
                    child0 = child.children[0]
                    if isinstance(child0, Node):
                        children = child0.children
                        if type_repr(child0.type) == 'expr_stmt':
                            if isinstance(children[1], Leaf) and \
                               children[1].value == '=':
                                if isinstance(children[0], Leaf):
                                    self.add_name(children[0].value, force=True)
                        elif type_repr(child0.type) == 'global_stmt':
                            for c in children:
                                if c.value == ',':
                                    continue
                                self.add_name(c.value, glob=True, force=True)
        return

    def create_assign_stmt(self, lhs='lhs', rhs='rhs', subst_lhs=None, subst_rhs=None):
        stmt = self.driver.parse_string(
            "%(lhs)s = %(rhs)s\n" % locals(),
            True,
        ).children[0]
        # Node(simple_stmt, [Node(expr_stmt, [Leaf(1, 'lhs'), Leaf(22, '='), Leaf(1, 'rhs')]), Leaf(4, '\n')])
        if subst_lhs is not None:
            children = stmt.children[0].children
            if isinstance(subst_lhs, basestring):
                children[0].value = subst_lhs
            else:
                children[0] = subst_lhs
        if subst_rhs is not None:
            children = stmt.children[0].children
            if isinstance(subst_rhs, basestring):
                children[2].value = subst_rhs
            else:
                children[2] = subst_rhs
        return stmt

    def create_call_stmt(self, fname='fn', args=None, subst_base=None, subst_args=None):
        if args is None or len(args) == 0:
            a = ''
        else:
            a = []
            for arg in args:
                if isinstance(arg, Node) or isinstance(arg, Leaf):
                    a.append('1')
                else:
                    a.append(arg)
            a = ', '.join(a)
        stmt = self.driver.parse_string(
            "%(fname)s(%(a)s)\n" % locals(),
            True,
        ).children[0]
        # driver.parse_string("fn()\n", True).children[0]
        # Node(simple_stmt, [Node(power, [Leaf(1, 'fn'), Node(trailer, [Leaf(7, '('), Leaf(8, ')')])]), Leaf(4, '\n')]), Leaf(0, '')
        # driver.parse_string("fn(1)\n", True).children[0]
        # Node(simple_stmt, [Node(power, [Leaf(1, 'fn'), Node(trailer, [Leaf(7, '('), Leaf(2, '1'), Leaf(8, ')')])]), Leaf(4, '\n')]), Leaf(0, '')
        # driver.parse_string("fn(1,2)\n", True).children[0]
        # Node(simple_stmt, [Node(power, [Leaf(1, 'fn'), Node(trailer, [Leaf(7, '('), Node(arglist, [Leaf(2, '1'), Leaf(12, ','), Leaf(2, '2')]), Leaf(8, ')')])]), Leaf(4, '\n')]), Leaf(0, '')
        trailer_childs = stmt.children[0].children[-1].children
        if args is None or len(args) == 0:
            pass
        elif len(args) == 1:
            arg = args[0]
            if isinstance(arg, Node) or isinstance(arg, Leaf):
                trailer_childs[1] = arg
        else:
            self.assert_type(stmt, trailer_childs[1].type, 'arglist')
            arglist_childs = trailer_childs[1].children
            for idx, arg in enumerate(args):
                idx *= 2
                if isinstance(arg, Node) or isinstance(arg, Leaf):
                    arglist_childs[idx] = arg
        if subst_base is not None:
            if isinstance(subst_base, basestring):
                stmt.children[0].children[0].value = subst_base
            else:
                stmt.children[0].children[0] = subst_base
        if subst_args is not None:
            self.assert_type(stmt, trailer_childs[1].type, 'arglist')
            arglist_childs = trailer_childs[1].children
            if len(args) == 1:
                arg = args[0]
                if arg is None:
                    pass
                elif isinstance(arg, basestring):
                    trailer_childs[1].value = arg
                else:
                    trailer_childs[1] = arg
            elif len(args) > 1:
                for idx, arg in enumerate(subst_args):
                    idx *= 2
                    if arg is None:
                        pass
                    elif isinstance(arg, basestring):
                        arglist_childs[idx].value = arg
                    else:
                        arglist_childs[idx] = arg
        return stmt

    def create_getindex_stmt(self, base='base', idx='idx', subst_base=None, subst_idx=None):
        stmt = self.driver.parse_string(
            "%(base)s[%(idx)s]\n" % locals(),
            True,
        ).children[0]
        # driver.parse_string("base[idx]\n", True).children[0]
        # Node(simple_stmt, [Node(power, [Leaf(1, 'base'), Node(trailer, [Leaf(9, '['), Leaf(1, 'idx'), Leaf(10, ']')])]), Leaf(4, '\n')]), Leaf(0, '')
        if subst_base is not None:
            children = stmt.children[0].children
            if isinstance(subst_base, basestring):
                children[0].value = subst_base
            else:
                children[0] = subst_base
        if subst_idx is not None:
            children = stmt.children[0].children[1].children
            if isinstance(subst_idx, basestring):
                children[1].value = subst_idx
            else:
                children[1] = subst_idx
        return stmt




    def node_and_expr(self, node):
        return self.get_bit_expr(node)

    def node_and_test(self, node, jsbool=False, name=None):
        jsvars = self.jsvars.copy()
        args = []
        childs = node.children.__iter__()
        if jsbool:
            name = None
        elif name is None:
            name = self.get_tmp_jsname('and$')
            self.add_lines("var %s" % name)
        args.append(self.get_test(childs.next(), name))
        try:
            while True:
                self.assert_value(node, childs.next().value, 'and')
                args.append(self.get_test(childs.next(), name))
        except StopIteration:
            pass
        test = ' && '.join(args)
        if jsbool:
            return test
        return '(%s ? %s : %s)' % (test, name, name)

    def node_arglist(self, node):
        childs = node.children.__iter__()
        arglist = []
        try:
            while True:
                child = childs.next()
                if isinstance(child, Leaf):
                    if child.value == ',':
                        continue
                    if child.value in ['*', '**']:
                        value = self.dispatch(childs.next())
                        arglist.append(Argument(child.value, value))
                        continue
                    arglist.append(self.dispatch(child))
                else:
                    arglist.append(self.dispatch(child))
        except StopIteration:
            pass
        return arglist

    def node_argument(self, node):
        if isinstance(node.children[1], Leaf):
            if node.children[1].value == '=':
                if len(node.children) == 3:
                    name = node.children[0].value
                    value = self.dispatch(node.children[2])
                    return Argument(name, value)
        else:
            if type_repr(node.children[1].type) == 'comp_for':
                return self.node_listmaker(node)
        self.not_implemented(node)

    def node_arith_expr(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        left = self.dispatch(childs.next())
        try:
            while True:
                op = childs.next()
                op = self.op_names2.get(op.value, None)
                if op is None:
                    self.not_implemented(node)
                right = self.dispatch(childs.next())
                jsvars.update(locals())
                left = "%(builtin)s['%(op)s'](%(left)s, %(right)s)" % jsvars
        except StopIteration:
            pass
        return left

    def node_assert_stmt(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        self.assert_value(node, childs.next().value, 'assert')
        test = self.dispatch(childs.next())
        arg = ''
        if len(node.children) > 2:
            child = childs.next()
            self.assert_value(node, child.value, ',')
            arg = ', %s' % self.dispatch(childs.next())
        jsvars.update(locals())
        # TODO: return %(builtin)s['raise'](%(builtin)s['AssertionError']%(arg)s, %(None)s)
        return """if (!%(booljs)s(%(test)s)) {
+   return %(builtin)s['raise'](%(module)s['$new'](%(builtin)s['AssertionError']%(arg)s));
}""" % jsvars

    def node_atom(self, node):
        jsvars = self.jsvars.copy()
        items = []
        cls = None
        if node.children[0].value == '(':
            cls = jsvars['tuple']
            if len(node.children) == 3:
                items = self.dispatch(node.children[1])
                if not isinstance(items, list):
                    return items
            elif len(node.children) != 2:
                self.not_implemented(node)
        elif node.children[0].value == '[':
            cls = jsvars['list']
            if len(node.children) == 3:
                items = self.dispatch(node.children[1])
                if not isinstance(items, list):
                    if isinstance(node.children[1], Leaf):
                        items = [items]
                    elif type_repr(node.children[1].type) == 'listmaker':
                        pass
                    else:
                        items = [items]
            elif len(node.children) != 2:
                self.not_implemented(node)
        elif node.children[0].value == '{':
            cls = jsvars['dict']
            if len(node.children) == 3:
                items = self.dispatch(node.children[1])
                if not isinstance(items, dict):
                    self.not_implemented(node)
            elif len(node.children) != 2:
                self.not_implemented(node)
            if items:
                items = ["[%s, %s]" % (k, v) for k, v in items.iteritems()]
            else:
                items = []
        elif node.children[0].value == '`':
            assert len(node.children) == 3
            what = self.dispatch(node.children[1])
            jsvars.update(locals())
            return "%(builtin)s['repr'](%(what)s)" % jsvars
        elif leaf_type.get(node.children[0].type) == 'str':
            s = ''
            for child in node.children:
                assert leaf_type.get(child.type) == 'str'
                s += child.value
            return self.add_const_str(eval(s))
        else:
            self.not_implemented(node)
        if isinstance(items, list):
            items = '[%s]' % ', '.join([str(i) for i in items])
        jsvars.update(locals())
        return "%(module)s['$new'](%(cls)s, %(items)s)" % jsvars

    def node_augassign(self, node):
        self.not_implemented(node)

    def node_break_stmt(self, node):
        return 'break'

    def node_classdef(self, node):
        jsvars = self.jsvars.copy()
        #print node.depth()
        childs = node.children.__iter__()
        self.assert_value(node, childs.next().value, 'class')
        name = childs.next().value
        self.add_name(name)
        tok = childs.next()
        if tok.value == ':':
            bases = self.get_jsname('object')
        else:
            self.assert_value(node, tok.value, '(')
            bases = childs.next()
            if isinstance(bases, Leaf):
                if bases.value == ')':
                    bases = None
                else:
                    bases = [self.get_jsname(bases.value)]
            else:
                bases = self.dispatch(bases)
            if bases is None:
                bases = self.get_jsname('object')
            elif isinstance(bases, list):
                bases = ', '.join([str(i) for i in bases])
                self.assert_value(node, childs.next().value, ')')
            else:
                self.assert_value(node, childs.next().value, ')')
            self.assert_value(node, childs.next().value, ':')
        lineno = self.track_lineno(node)
        jsvars.update(locals())
        if isinstance(self.names[-1], ClassNames):
            namespace = "%(funcbase)s['$dict']" % jsvars
        else:
            namespace = "%(locals)s" % jsvars
        jsvars.update(namespace=namespace)
        self.add_lines("""\
%(namespace)s[%(name)r] = %(builtin)s['B$type'](%(module)s, %(name)r, [%(bases)s], {});
(function(%(funcbase)s){
+   //var %(locals)s = %(funcbase)s['$dict'];""" % jsvars)
        names = ClassNames()
        self.names.append(names)
        indent_level = self.indent()
        self.next_func_type.append(func_type['function'])
        try:
            while True:
                child = childs.next()
                self.dispatch(child)
        except StopIteration:
            pass
        self.next_func_type.pop()
        self.assert_dedent(self.dedent(), indent_level)
        assert names is self.names.pop(), self.TranslationError("names pop error", self.get_lineno(node))
        if '__slots__' in names:
            self.add_lines("""\
+   %(funcbase)s['__slots__'] =  %(module)s['$new'](%(tuple)s, %(locals)s['__slots__']).__array;\
""" % jsvars)
        self.add_lines("})(%(namespace)s[%(name)r]);" % jsvars)
        return name

    def node_comp_for(self, node):
        assert False, "Shouldn't get here..."

    def node_comp_if(self, node):
        assert False, "Shouldn't get here..."

    def node_comp_iter(self, node):
        self.not_implemented(node)

    def node_comp_op(self, node):
        if node.children[0].value == 'is':
            if node.children[1].value == 'not':
                return op_compare['is not']
        elif node.children[0].value == 'not':
            if node.children[1].value == 'in':
                return op_compare['not in']
        self.not_implemented(node)

    def node_comparison(self, node):
        jsvars = self.jsvars.copy()
        left = op = right = None
        childs = node.children.__iter__()
        first_left = left = self.dispatch(childs.next())
        prev_right = None
        cmp_expr = []
        tmp = None
        try:
            while True:
                op_node = childs.next()
                right = self.dispatch(childs.next())
                if isinstance(op_node, Leaf):
                    op = op_compare[op_node.value]
                elif type_repr(op_node.type) == 'comp_op':
                    op = self.dispatch(op_node)
                jsvars.update(locals())
                if prev_right is None:
                    cmp_expr.append("""\
%(builtin)s['%(op)s'](%(left)s, %(right)s)""" % jsvars)
                else:
                    if tmp is None:
                        tmp = self.get_tmp_jsname('comp$')
                        jsvars['tmp'] = tmp
                        self.add_lines("var %s;" % tmp)
                        cmp_expr = ["""\
%(builtin)s['%(op)s'](%(first_left)s, %(tmp)s=%(prev_right)s)""" % jsvars]
                    cmp_expr.append("""\
%(builtin)s['%(op)s'](%(tmp)s, %(tmp)s=%(right)s)""" % jsvars)
                left = right
                prev_right = right
        except StopIteration:
            pass
        if cmp_expr:
            if len(cmp_expr) == 1:
                return cmp_expr[0]
            s = ' && '.join([
                "(%s).valueOf()" % i
                for i in cmp_expr
            ])
            jsvars.update(locals())
            return "(%(s)s ? %(True)s : %(False)s)" % jsvars
        self.not_implemented(node)

    def node_compound_stmt(self, node):
        self.not_implemented(node)

    def node_continue_stmt(self, node):
        self.not_implemented(node)

    def node_decorated(self, node):
        self.assert_instance(node, node.children[0], Node)
        self.assert_instance(node, node.children[1], Node)
        assert len(node.children) == 2
        decorators = self.dispatch(node.children[0])
        func = node.children[1]
        if not isinstance(decorators, list):
            decorators = [decorators]
        lineno = self.track_lineno(decorators[0])
        next_func_type = None
        if isinstance(self.names[-1], ClassNames):
            next_func_type = func_type['function']
            if decorators[-1].name == 'staticmethod':
                next_func_type = func_type['staticmethod']
            elif decorators[-1].name == 'classmethod':
                next_func_type = func_type['classmethod']
            self.next_func_type.append(next_func_type)
        self.assert_value(func, func.children[0].value, 'def')
        name = func.children[1].value
        self.add_name(name, self.track_lineno(func), force=True)
        src = self.get_jsname(name)
        dst = "%s = " % src
        jsvars = self.jsvars.copy()
        for decorator in decorators:
            if decorator is decorators[-1] and \
               next_func_type is not None and \
               decorator.name in ['staticmethod', 'classmethod']:
                pass
            else:
                deco = decorator.name.split('.')
                if len(deco) == 1:
                    deco = self.get_jsname(decorator.name)
                else:
                    dst = ''
                    deco = "%s(%s, ['%s'])" %(
                        jsvars['getattr'],
                        self.get_jsname(deco[0]),
                        "', '".join(deco[1:]),
                    )
                jsvars.update(locals())
                self.add_lines("""\
%(src)s = %(fcall)s(%(module)s, %(lineno)s, %(deco)s, null,""" % jsvars)
                dst = ''
                self.indent()

        name = self.dispatch(func)

        for decorator in decorators:
            if decorator is decorators[-1] and \
               next_func_type is not None and \
               decorator.name in ['staticmethod', 'classmethod']:
                pass
            else:
                self.dedent()
                # remove trailing ';' from last line
                assert self.lines[-1][1][-1] == ';'
                self.lines[-1][1] = self.lines[-1][1][:-1]
                self.add_lines(");")

        if next_func_type is not None:
            self.next_func_type.pop()
        return

    def node_decorator(self, node):
        self.assert_value(node, node.children[0].value, '@')
        self.assert_value(node, node.children[-1].value, ['\n', '\r\n'])
        childs = node.children.__iter__()
        self.assert_value(node, childs.next().value, '@')
        child = childs.next()
        if isinstance(child, Leaf):
            name = child.value
        else:
            name = self.dispatch(child)
            # TODO / FIXME : handle x.setter etc
            name = '.'.join(name)
        self.assert_value(node, childs.next().value, ['\n', '\r\n'])
        return Decorator(name, node.children[0].lineno)

    def node_decorators(self, node):
        decorators = []
        for child in node.children:
            decorators.append(self.dispatch(child))
        return decorators

    def node_del_stmt(self, node):
        # del a
        # del a.b
        # del a.b[1]
        # del a, b
        # del a[:]
        # a = [0,1,2,3,4,5,6,7,8,9] ; del a[1:8:2]
        # Node(del_stmt, [Leaf(1, 'del'), Leaf(1, 'a')])
        # Node(del_stmt, [Leaf(1, 'del'), Node(power, [Leaf(1, 'a'), Node(trailer, [Leaf(23, '.'), Leaf(1, 'b')])])])
        # Node(del_stmt, [Leaf(1, 'del'), Node(power, [Leaf(1, 'a'), Node(trailer, [Leaf(23, '.'), Leaf(1, 'b')]), Node(trailer, [Leaf(9, '['), Leaf(2, '1'), Leaf(10, ']')])])])
        jsvars = self.jsvars.copy()
        lineno = self.track_lineno(node)
        childs = node.children.__iter__()
        self.assert_value(node, childs.next().value, 'del')
        child = childs.next()
        if isinstance(child, Node) and \
           type_repr(child.type) == 'exprlist':
            childs = child.children.__iter__()
            child = childs.next()
        try:
            while True:
                if isinstance(child, Leaf):
                    name = self.get_jsname(child.value)
                    self.add_lines("delete %s;" % name, lineno)
                elif type_repr(child.type) == 'power':
                    jsvars = self.jsvars.copy()
                    tail = child.children.pop()
                    if len(child.children) > 1:
                        base = self.dispatch(child)
                    else:
                        base = self.dispatch(child.children[0])
                    if type_repr(tail.type) == 'trailer':
                        what = tail.children[1]
                        if tail.children[0].value == '.':
                            # delattr
                            op = 'delattr'
                            if isinstance(what, Leaf):
                                what = repr(what.value)
                            else:
                                what = self.dispatch(what)
                        elif tail.children[0].value == '[':
                            op, what = self.get_op_item(
                                what, 'delitem', 'delslice',
                            )
                        else:
                            self.not_implemented(node)
                        jsvars.update(locals())
                        self.add_lines("""\
%(builtin)s['%(op)s'](%(base)s, %(what)s)\
""" % jsvars)
                        return
                else:
                    self.not_implemented(node)
                self.assert_value(node, childs.next().value, ',')
                child = childs.next()
        except StopIteration:
            pass

    def node_dictsetmaker(self, node):
        values = {}
        childs = node.children.__iter__()
        try:
            while True:
                k = self.dispatch(childs.next())
                self.assert_value(node, childs.next().value, ':')
                v = self.dispatch(childs.next())
                values[k] = v
                self.assert_value(node, childs.next().value, ',')
        except StopIteration:
            pass
        return values

    def node_dotted_as_name(self, node):
        assert len(node.children) == 3
        if isinstance(node.children[0], Leaf):
            mod = [node.children[0].value]
        else:
            mod = self.dispatch(node.children[0])
        name = node.children[2].value
        return Import(mod, name)

    def node_dotted_as_names(self, node):
        imports = []
        childs = node.children.__iter__()
        try:
            while True:
                child = childs.next()
                if isinstance(child, Leaf):
                    if child.value == ',':
                        continue
                    imports.append(Import([child.value]))
                else:
                    imp = self.dispatch(child)
                    if isinstance(imp, list):
                        imp = Import(imp)
                    else:
                        imp = Import([imp])
                    imports.append(imp)
        except StopIteration:
            pass
        return imports

    def node_dotted_name(self, node):
        names = []
        for child in node.children:
            if child.value == '.':
                continue
            names.append(child.value)
        return names

    def node_encoding_decl(self, node):
        self.not_implemented(node)

    def node_eval_input(self, node):
        self.not_implemented(node)

    def node_except_clause(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        self.assert_value(node, childs.next().value, 'except')
        classes = None
        varname = None
        try:
            child = childs.next()
            if isinstance(child, Node) and type_repr(child.type) == 'atom':
                self.assert_value(node, child.children[0].value, '(')
                self.assert_value(node, child.children[-1].value, ')')
                classes = self.dispatch(child.children[1])
            else:
                classes = self.dispatch(child)
            self.assert_value(node, childs.next().value, ',')
            varname = self.dispatch(childs.next(), assign=True)
        except StopIteration:
            pass
        if classes is not None:
            if not isinstance(classes, list):
                classes = [classes]
            tests = []
            return classes, varname
        return None, None

    def node_exec_stmt(self, node):
        self.not_implemented(node)

    def node_expr(self, node):
        if len(node.children) > 2:
            if isinstance(node.children[1], Leaf):
                if node.children[1].value == '|':
                    return self.get_bit_expr(node)
        self.not_implemented(node)

    def _assign(self, node, left, rest):
        jsvars = self.jsvars.copy()
        lineno = self.track_lineno(node)
        if len(rest) == 1:
            right = self.dispatch(rest[0])
        else:
            self.assert_value(node, rest[1].value, '=')
            right = self._assign(node, rest[0], rest[2:])
        if not isinstance(left, Node):
            if isinstance(self.names[-1], ClassNames):
                self.dispatch(left, assign=right)
                left = left.value
                jsvars.update(locals())
                return "%(setattr)s(%(funcbase)s, ['%(left)s'], %(right)s)" % jsvars
            left = self.dispatch(left, assign=right)
        elif type_repr(left.type) in ['testlist_star_expr', 'atom', 'exprlist']:
            # Assignment to tuple or list (aka tuple assignment)
            # children for:
            # a, b = foo
            # [Node(testlist_star_expr, [Leaf(1, 'a'), Leaf(12, ','), Leaf(1, 'b')]), Leaf(22, '='), Leaf(1, 'foo')]
            # (a, b) = foo
            # [Node(atom, [Leaf(7, '('), Node(testlist_gexp, [Leaf(1, 'a'), Leaf(12, ','), Leaf(1, 'b')]), Leaf(8, ')')]), Leaf(22, '='), Leaf(1, 'foo')]
            # for k, v in foo:
            #    pass
            # [Node(exprlist, [Leaf(1, 'k'), Leaf(12, ','), Leaf(1, 'v')]), Leaf(22, '='), Leaf(1, 'for$1')]
            head_lines = []
            lines = []
            def tuple_assign(left, right):
                if type_repr(left.type) == 'atom':
                    children = left.children[1:-1]
                    if isinstance(children[0], Node) and \
                       type_repr(children[0].type) in ['testlist_gexp', 'listmaker']:
                        children = children[0].children[:]
                else:
                    children = left.children[:]
                n = len(children) / 2 + 1
                rhs = self.get_tmp_jsname('tplass$')
                jsvars.update(locals())
                self.add_lines("var %(rhs)s;" % jsvars)
                head_lines.append(
                    "%(rhs)s = %(builtin)s['tplass'](%(right)s, %(n)s);" % jsvars
                )
                idx = -1
                for child in children:
                    if isinstance(child, Leaf) and child.value == ',':
                        continue
                    idx += 1
                    right = self.create_getindex_stmt(
                        idx=1,
                        subst_base=rhs,
                        subst_idx=str(idx),
                    ).children[0]
                    if isinstance(child, Node) and type_repr(child.type) == 'atom':
                        self.assert_value(node, child.children[0].value, ['(', '['])
                        right = self.dispatch(right)
                        tuple_assign(child, right)
                    else:
                        self.dispatch(child, assign=right)
                        n = self.create_assign_stmt(
                            subst_lhs=child,
                            subst_rhs=right,
                        ).children[0]
                        line = self.node_expr_stmt(n)
                        if line[-1] != ';':
                            line += ';'
                        lines.append(line)
            tuple_assign(left, right)
            lines = head_lines + lines
            return '\n'.join(lines)
        elif type_repr(left.type) == 'power':
            tail = left.children.pop()
            if len(left.children) > 1:
                base = self.dispatch(left)
            else:
                base = self.dispatch(left.children[0])
            if isinstance(base, Code):
                base = str(base)
            self.assert_instance(node, base, basestring)
            args = []
            if type_repr(tail.type) == 'trailer':
                what = tail.children[1]
                if tail.children[0].value == '.':
                    # setattr
                    op = 'setattr'
                    if isinstance(what, Leaf):
                        what = repr(what.value)
                    else:
                        what = self.dispatch(what)
                    what = "[%s]" % what
                elif tail.children[0].value == '[':
                    op, what = self.get_op_item(
                        what, 'setitem', 'setslice',
                    )
                else:
                    self.not_implemented(node)
                jsvars.update(locals())
                return """\
%(builtin)s['%(op)s'](%(base)s, %(what)s, %(right)s)\
""" % jsvars
            else:
                self.not_implemented(node)
        else:
            left = self.dispatch(left)
        return '%s = %s' % (left, right)

    def node_expr_stmt(self, node):
        jsvars = self.jsvars.copy()
        lineno = self.track_lineno(node)
        if node.children[1].value == '=':
            return self._assign(node, node.children[0], node.children[2:])
        elif node.children[1].value[-1] == '=' and \
             node.children[1].value in self.op_names2:
            jsvars = self.jsvars.copy()
            op_node = node.children[1]
            op = self.op_names2.get(op_node.value, None)
            if op is None:
                self.not_implemented(node)
            right = self.dispatch(node.children[2])
            left = node.children[0]
            get_left = self.dispatch(left)
            jsvars.update(locals())
            # lhs = op_X(lhs, rhs)
            # Node(simple_stmt, [Node(expr_stmt, [Leaf(1, 'b'), Leaf(22, '='), Leaf(2, '1')]), Leaf(4, '\n')])
            if op_node.value[:-1] in ['&', '|', '^', '>>', '<<']:
                stmt = "%(builtin)s['%(op)s2'](%(get_left)s, %(right)s)" % jsvars
            else:
                stmt = "%(builtin)s['%(op)s'](%(get_left)s, %(right)s, true)" % jsvars
            if isinstance(left, Leaf):
                set_left = left.value
            else:
                set_left = self.dispatch(left, stmt)
                return set_left
            stmt = self.create_assign_stmt(
                subst_lhs=set_left,
                subst_rhs=Code(stmt, lineno),
            ).children[0]
            stmt = self.dispatch(stmt)
            return stmt
        self.not_implemented(node)

    def node_exprlist(self, node):
        self.not_implemented(node)

    def node_factor(self, node):
        if len(node.children) == 2:
            if node.children[0].value == '-':
                right = node.children[1]
                if isinstance(right, Leaf) and \
                   leaf_type.get(right.type) == 'number':
                    v = right.value
                    right.value = '-' + right.value
                    r = self.dispatch(right)
                    right.value = v
                    return r
                value = self.dispatch(right)
                return "%s['%s'](%s)" % (
                    self.jsvars['builtin'], op_names1['neg'], value,
                )
            if node.children[0].value == '~':
                right = node.children[1]
                value = self.dispatch(right)
                return "%s['%s'](%s)" % (
                    self.jsvars['builtin'], op_names1['inv'], value,
                )
        self.not_implemented(node)

    def node_file_input(self, node):
        jsvars = self.jsvars.copy()

        # Initialize module creation
        self.add_lines("""\
/* <start module: %(module_name)s */ (function(){
var %(module)s = %(module_store)s[%(module_name)r] = {
+   '$inst': true,
+   '$dict': {
++      '__name__': null
+   },
+   'toString': function() { return "<module " + this['$dict']['__name__'] + ">";},
+   '$module_init': function($name$) {
++      if (%(globals)s['__name__'] !== null) {
+++         return %(module)s;
++      }
++      var $name = $name$;
++      if ($name === null || typeof $name == 'undefined') $name = %(module_name)r;
++      %(builtin)s = %(module_store)s[%(__builtin__)r]['$dict'];
++      %(namestack)s = [%(builtin)s['_builtin_object_'], %(globals)s];""" % jsvars)

        if jsvars['module_name'] != jsvars['__builtin__']:
            self.add_lines("""\
++      %(module)s['__class__'] = %(builtin)s['module'];
++      %(module)s['$new'] = %(builtin)s['$new'];
++      $name = %(module)s['$new'](%(builtin)s['str'], $name);
++      %(globals)s['__doc__'] = %(None)s = %(builtin)s['None'];
++      %(globals)s['__name__'] = $name;""" % jsvars)
            if os.path.basename(self.srcfile) == '__init__.py':
                self.add_lines("""\
++      %(globals)s['__package__'] = $name;""" % jsvars)
        jsvars.update(locals())

        if len(node.children) > 0:
            # Initialize the short names and the constants etc.
            #
            self.add_lines("""\
++      %(locals)s = %(globals)s,
++      %(funcbase)s = %(globals)s,
++      %(globals)s['__builtins__'] = %(module_store)s[%(__builtin__)r]
++      %(track)s['module'] = $name;""" % jsvars)
            if jsvars['module_name'] != jsvars['__builtin__']:
                # Add builtins to the module object _and_ the globals. On
                # deletion of a global, the builtin (if any) has to be
                # copied back from module to global.
                # TODO: restrict the number of 'copied' builtins
                self.add_lines("""\
++      init_short_names$();
++      init_constants$();
++      for (var name in %(namestack)s[0]) {
+++         %(globals)s[name] = %(module_store)s[%(module_name)r][name] = %(namestack)s[0][name];
++      }
++      %(globals)s['__name__'] = %(fcall)s(%(module)s, null, %(builtin)s['str'], null, $name);\
""" % jsvars)

        self.indent(2)

        # Now the module content
        for child in node.children:
            self.dispatch(child)

        # Close the module creation
        self.dedent(2)
        self.assert_dedent(self.indent_level, 0)
        self.add_lines("""\
++      return %(module)s;
+   }
};
var %(globals)s = %(module_store)s[%(module_name)r]['$dict'];""" % jsvars)
        if len(node.children) > 0:
            # Declare short names for builtins
            self.add_lines("""\
var %(namestack)s, %(locals)s, %(funcbase)s, %(builtin)s, %(fcall)s, %(fcallext)s, %(mcall)s, %(mcallext)s, %(booljs)s,
    %(getattr)s, %(setattr)s, %(getitem)s, %(None)s, %(int)s, %(bool)s, %(True)s, %(False)s, %(str)s,
    %(constants)s = {};

function init_short_names$(silent) {
+   var builtin = %(builtin)s;
+   try {
++      %(fcall)s = builtin['fcall'];
++      %(fcallext)s = builtin['fcallext'];
++      %(mcall)s = builtin['mcall'];
++      %(mcallext)s = builtin['mcallext'];
++      %(booljs)s = builtin['B$booljs'];
++      %(getattr)s = builtin['getattr'];
++      %(setattr)s = builtin['setattr'];
++      %(getitem)s = 'getitem';
++      %(None)s = builtin['None'];
++      %(int)s = builtin['int'];
++      %(bool)s = builtin['B$bool'];
++      %(True)s = builtin['True'];
++      %(False)s = builtin['False'];
++      %(str)s = builtin['B$str'];
+   } catch (e) {
++      if (silent !== true) {
+++         throw e;
++      }
+   }
};

function init_constants$(silent) {
+   var builtin = %(builtin)s;
+   try {
""" % jsvars)
            # Add constants: int
            for name, value in sorted([(v, k) for k,v in self.const_int.iteritems()]):
                if name is not None:
                    v = abs(int(value))
                    if v > (1 << 30):
                        value = "%s(%r)" % (jsvars['str'], value)
                    jsvars['value'] = value
                    jsvars['name'] = name
                    self.add_lines("""\
++%(name)s = %(fcall)s(%(module)s, null, builtin['int'], null, %(value)s);\
""" % jsvars)
            # Add constants: long
            for name, value in sorted([(v, k) for k,v in self.const_long.iteritems()]):
                if name is not None:
                    v = abs(int(value))
                    if v > (1 << 30):
                        value = "%s(%r)" % (jsvars['str'], value)
                    jsvars['value'] = value
                    jsvars['name'] = name
                    self.add_lines("""\
++%(name)s = %(fcall)s(%(module)s, null, builtin['long'], null, %(value)s);\
""" % jsvars)
            # Add constants: float
            for name, value in sorted([(v, k) for k,v in self.const_float.iteritems()]):
                if name is not None:
                    jsvars['value'] = value
                    jsvars['name'] = name
                    self.add_lines("""\
++%(name)s = %(fcall)s(%(module)s, null, builtin['float'], null, %(value)s);\
""" % jsvars)
            # Add constants: str
            for name, value in sorted([(v,k) for k,v in self.const_str.iteritems()]):
                value = "'%s'" % re_js_string_escape.sub(self.substitute_js_chars, value)
                if isinstance(value, unicode):
                    value = value.encode('ascii', 'xmlcharrefreplace')
                if name is not None:
                    jsvars['value'] = value
                    jsvars['name'] = name
                    self.add_lines("""\
++%(name)s = %(str)s(%(value)s);\
""" % jsvars)
            self.add_lines("""\
+   } catch (e) {
++      if (silent !== true) {
+++         throw e;
++      }
+   }
};""" % jsvars)
        self.add_lines("""\
})();
/* end module: %(module_name)s */
""" % jsvars)
        pyjs_deps = self.imported_modules.keys()
        if pyjs_deps:
            pyjs_deps.sort()
            jsvars.update(pyjs_deps=pyjs_deps)
            self.add_lines("""\
/*
PYJS_DEPS: %(pyjs_deps)r
*/
""" % jsvars)
        pyjs_js = self.imported_js.keys()
        if pyjs_js:
            pyjs_js.sort()
            jsvars.update(pyjs_js=pyjs_js)
            self.add_lines("""\
/*
PYJS_JS: %(pyjs_js)r
*/
""" % jsvars)

    def node_flow_stmt(self, node):
        self.not_implemented(node)

    def node_for_stmt(self, node):
        jsvars = self.jsvars.copy()
        lineno = self.track_lineno(node)
        inloop = self.inloop
        self.inloop += 1
        childs = node.children.__iter__()
        self.assert_value(node, childs.next().value, 'for')
        assign = childs.next()
        self.assert_value(node, childs.next().value, 'in')
        iterable = self.dispatch(childs.next())
        if isinstance(iterable, list):
            iterable = '[%s]' % ', '.join([str(i) for i in iterable])
        self.assert_value(node, childs.next().value, ':')
        if True:# len(node.children) > 6 and node.children[6].value == 'else':
            floop = self.get_tmp_jsname('for$')
            floopdecl = 'var %s = [];\n' % floop
            floopass = '\n++%s = true;' % floop
            floopass = ''
        else:
            floop = None
            floopdecl = floopass = ''
        iter = self.get_tmp_jsname('iter$')
        loop = self.get_tmp_jsname('for$')
        jsvars.update(locals())
        # There's a special 'next$' method that doesn't throw
        # StopIteration, but returns void instead.
        self.add_lines("""\
var %(iter)s = %(builtin)s['iter'](%(iterable)s, %(None)s);
%(floopdecl)svar %(loop)s;
try {
+   for (;;) {
++      %(loop)s = %(floop)s;
++      %(loop)s = %(mcall)s(%(module)s, %(lineno)s, %(iter)s, 'next');\
%(floopass)s""" % jsvars, lineno)
        indent_level = self.indent(2)
        n = self.create_assign_stmt(
            subst_lhs=assign,
            subst_rhs=loop,
        ).children[0]
        line = self.node_expr_stmt(n)
        if line.rstrip()[-1] != ';':
            line += ';'
        self.add_lines(line)
        n = len(self.lines)
        self.dispatch(childs.next())
        self.assert_dedent(self.dedent(2), indent_level)
        self.add_lines("""\
+   }
} catch (%(catch)s) {
+    if (%(loop)s !== %(floop)s || %(catch)s['__class__'] !== %(builtin)s['StopIteration']) throw %(catch)s;\
""" % jsvars)
        if len(node.children) > 6 and node.children[6].value == 'else':
            if len(self.lines) > n:
                self.add_lines("""\
}
if (%(loop)s === %(floop)s) {""" % jsvars)
            else:
                self.add_lines("""\
}
if (true) {""" % jsvars)
            indent_level = self.indent(1)
            self.assert_value(node, childs.next().value, 'else')
            self.assert_value(node, childs.next().value, ':')
            self.dispatch(childs.next())
            self.assert_dedent(self.dedent(1), indent_level)
        self.add_lines("""\
}""" % jsvars)
        self.inloop -= 1

    def node_funcdef(self, node, is_lambda=False):
        jsvars = self.jsvars.copy()
        #print 'node.depth():', node.depth()
        depth = self.get_names_depth()
        childs = node.children.__iter__()
        if is_lambda:
            self.assert_value(node, childs.next().value, 'lambda')
            name = "<lambda>"
            assign_name = self.get_tmp_jsname('lamb$')
            assign = "var %s = " % assign_name
            if isinstance(node.children[1], Leaf) and \
               node.children[1].value == ':':
                params = Parameters([], None, None, None)
            else:
                child = childs.next()
                if isinstance(child, Leaf):
                    params = Parameters([child.value], None, None, None)
                    #args, star_args, dstar_args, defaults
                else:
                    params = self.dispatch(child)
        else:
            self.assert_value(node, childs.next().value, 'def')
            name = childs.next().value
            self.add_name(name, force=True)
            assign = ''
            params = self.dispatch(childs.next())
        self.assert_instance(node, params, Parameters)
        if params.star_args is None:
            star_args = 'null'
        else:
            star_args = repr(params.star_args)
        if params.dstar_args is None:
            dstar_args = 'null'
        else:
            dstar_args = repr(params.dstar_args)
        if params.defaults is None:
            defaults = 'null'
        else:
            defaults = ', '.join([str(self.dispatch(i)) for i in params.defaults])
            defaults = '[%s]' % defaults
        tfpdef = {}
        jsargs = []
        locals_init = []
        for arg in params.all_args:
            if isinstance(arg, tuple):
                tfpdef_name = self.get_tmp_jsname('tfpdef$')
                jsargs.append(tfpdef_name)
                def flatten_arg(names):
                    args = []
                    for name in names:
                        if isinstance(name, tuple):
                            name = flatten_arg(name)
                        else:
                            self.add_name(name)
                        args.append(name)
                    args = ', '.join(args)
                    return "(%s)" % args
                tfpdef[tfpdef_name] = flatten_arg(arg)
            else:
                jsargs.append('$%s' % arg)
                if is_lambda:
                    locals_init.append(
                        "%s['%s'] = $%s;" % (
                            jsvars['locals'],
                            arg,
                            arg,
                        )
                    )
                else:
                    locals_init.append("'%s': $%s" % (arg, arg))
        args = params.args
        if not jsargs:
            jsargs = ''
        else:
            jsargs = ', '.join(jsargs)
        self.assert_value(node, childs.next().value, ':')
        type = self.next_func_type[-1]
        lineno = self.track_lineno(node)
        jsvars.update(locals())
        self.add_lines("""\
%(assign)s(function(%(funcbase)s, $%(locals)s){
+   return %(builtin)s['func'](%(module)s, %(lineno)s, %(funcbase)s, '%(name)s', %(type)s, %(args)r, %(star_args)s, %(dstar_args)s, %(defaults)s, function(%(jsargs)s) {\
""" % jsvars)
        if not is_lambda:
            self.add_lines("""\
++      var %(namestack)s = $%(locals)s.slice(0);
++      var %(locals)s = {""" % jsvars)
        else:
            for line in locals_init:
                self.add_lines("++%s" % line)
        lines = self.lines
        self.lines = func_lines = []
        names = Names()
        self.names.append(names)
        for a in params.all_args:
            self.add_name(a)
        if not is_lambda:
            self.collect_locals(node)
        indent_level = self.indent(2)

        try:
            lambda_code = None
            while True:
                child = childs.next()
                code = self.dispatch(child)
                if is_lambda:
                    if lambda_code is None:
                        self.add_lines(
                            "return %s" % code, self.track_lineno(child),
                        )
                        lambda_code = code
                    else:
                        self.TranslationError(
                            "Multiple lines found in lambda definition",
                            self.get_lineno(node)
                        )
        except StopIteration:
            pass
        self.assert_dedent(self.dedent(2), indent_level)
        self.lines = lines
        assert names is self.names.pop()
        for n in names.itervalues():
            if n.name not in params.all_args and \
               n.builtin is False and \
               n.to_js is None and \
               n.depth <= depth and \
               n.glob is False:
                scope = 'locals'
                src = self.jsvars['funcbase']
                src = '$%(locals)s' % self.jsvars
                src = '%s[%s]' % (self.jsvars['namestack'], n.depth)
                locals_init.append(
                    "'%s': %s['%s']" % (
                        n.name, src, n.name,
                    ),
                )
        locals_init = ',\n+++'.join(locals_init)
        locals_init = locals_init.strip()
        jsvars.update(locals())
        if not is_lambda:
            self.add_lines("""\
+++         %(locals_init)s
++      };
++      %(namestack)s[%(depth)s + 1] = %(locals)s;""" % jsvars)
        if tfpdef:
            self.indent(2)
            for k, v in tfpdef.iteritems():
                n = self.create_assign_stmt(
                    lhs=str(v),
                    subst_rhs=Code(k, self.track_lineno(node)),
                ).children[0]
                line = self.node_expr_stmt(n)
                self.add_lines(line)
            self.dedent(2)
        self.lines += func_lines
        if is_lambda:
            self.add_lines("""\
+   });
})({}, %(namestack)s);""" % jsvars)
            return assign_name
        if isinstance(self.names[-1], ClassNames):
            self.add_lines("""\
++      return %(None)s;
+   });
})(%(funcbase)s, %(namestack)s);""" % jsvars)
        else:
            self.add_lines("""\
++      return %(None)s;
+   });
})(%(locals)s, %(namestack)s);""" % jsvars)
        return name

    def node_global_stmt(self, node):
        for child in node.children[1:]:
            if child.value == ',':
                continue
            self.add_name(child.value, glob=True)

    def node_if_stmt(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        try:
            while True:
                stmt = childs.next()
                if stmt.value == 'if':
                    test = self.get_test(childs.next())
                    test = "if (%s) {" % test
                    self.add_lines(test, self.track_lineno(stmt))
                elif stmt.value == 'elif':
                    test = self.get_test(childs.next())
                    test = "} else if (%s) {" % test
                    self.add_lines(test)
                elif stmt.value == 'else':
                    self.add_lines('} else {')
                self.assert_value(node, childs.next().value, ':')
                self.indent()
                self.dispatch(childs.next())
                self.dedent()
        except StopIteration:
            pass
        self.add_lines("}")

    def node_import_as_name(self, node):
        assert len(node.children) == 3
        return node.children[0].value, node.children[2].value

    def node_import_as_names(self, node):
        names = []
        for child in node.children:
            if isinstance(child, Leaf):
                if child.value == ',':
                    continue
                names.append([child.value, None])
            else:
                names.append(self.dispatch(child))
        return names

    def node_import_from(self, node):
        jsvars = self.jsvars.copy()
        imports = []
        if isinstance(node.children[1], Leaf):
            modname = node.children[1].value
        else:
            modname = '.'.join(self.dispatch(node.children[1]))
        for child in node.children[3:]:
            if isinstance(child, Leaf):
                if child.value in ['(', ')']:
                    continue
                names = [[child.value, None]]
            else:
                names = self.dispatch(child)
            if not isinstance(names, list):
                names = [names]
            if modname == '__pyjamas__':
                for name, assname in names:
                    if not hasattr(__Pyjamas__, name):
                        raise self.TranslationError(
                            "ImportError: cannot import name %s from %s" % (
                                name, modname,
                            ),
                        )
                    to_js = getattr(__Pyjamas__, name)(self)
                    self.add_name(name, to_js=to_js, force=True)
                return
            if modname == '__javascript__':
                for name, assname in names:
                    if assname is None:
                        assname = name
                    self.add_name(assname, to_js=name, force=True)
                return
            if modname == '__future__':
                for name, assname in names:
                    imp = 'import_%s' % name
                    imp = getattr(self.__future__, imp, None)
                    if imp is None:
                        raise self.TranslationError(
                            "SyntaxError: future feature %s is not defined" % (
                                name,
                            ),
                        )
                    imp(self)
            level = modname
            modname = modname.lstrip('.')
            level = len(level) - len(modname)
            if level == 0:
                level = 'null'
            else:
                modname = ''
            c_modname = self.add_const_str(modname)
            assnames = []
            fromlist = []
            for name, assname in names:
                c_name = self.add_const_str(name)
                fromlist.append(c_name)
                if assname is None:
                    assnames.append([c_name, 'null'])
                    assname = name
                else:
                    c_assname = self.add_const_str(assname)
                    assnames.append([c_name, c_assname])
                self.add_name(assname)
                self.add_import(modname, [name])
            if assnames:
                assnames = "[%s]" % '], ['.join(["%s, %s" % (i, j) for (i, j) in assnames])
            else:
                assnames = ''
            fromlist = ', '.join(fromlist)
            jsvars.update(
                modname=c_modname,
                fromlist=fromlist,
                assnames=assnames,
                level=level,
            )
            imports.append("""\
%(builtin)s['_import']([%(assnames)s], %(modname)s, %(globals)s, %(locals)s, [%(fromlist)s], %(level)s);""" % jsvars)
        return "\n".join(imports)

    def node_import_name(self, node):
        jsvars = self.jsvars.copy()
        imports = []
        for child in node.children[1:]:
            if isinstance(child, Leaf):
                imp = child.value
            else:
                imp = self.dispatch(child)
            if not isinstance(imp, list):
                imp = [imp]
            if not isinstance(imp[0], Import):
                imp = [Import(imp)]
            for i in imp:
                self.add_name(i.assname)
                self.add_import(i.modname, None)
                c_modname = self.add_const_str(i.modname)
                c_assname = self.add_const_str(i.assname)
                assnames = "%s, %s" % (c_modname, c_assname)
                dst = self.get_jsname(i.assname)
                jsvars.update(
                    dst=dst,
                    modname=c_modname,
                    assname=i.assname,
                    assnames=assnames,
                )
                imports.append("""\
%(dst)s = %(builtin)s['_import']([], %(modname)s, %(globals)s, %(locals)s, null, null);""" % jsvars)
        return "\n".join(imports)

    def node_import_stmt(self, node):
        self.not_implemented(node)

    def node_lambdef(self, node):
        return self.node_funcdef(node, is_lambda=True)

    def node_listmaker(self, node, cls='list'):
        items = []
        for child in node.children:
            if isinstance(child, Leaf):
                if child.value != ',':
                    items.append(self.dispatch(child))
            elif type_repr(child.type) == 'comp_for':
                # list comprehension
                # create a for_stmt lookalike
                simple_stmt = self.create_call_stmt(
                    'a.append',
                    [node.children[0]],
                    subst_base='comp$',
                )
                childs = child.children.__iter__()
                base_node = comp_node = child
                comp_node.type = sym_type('for_stmt')
                comp_node.children = []
                child = childs.next()

                try:
                    while True:
                        while isinstance(child, Leaf) or \
                              not type_repr(child.type) in ['comp_if', 'comp_for']:
                            comp_node.append_child(child)
                            child = childs.next()
                        childs = child.children.__iter__()
                        comp_node.append_child(Leaf(11, ':'))
                        comp_node.append_child(child)
                        comp_node = child
                        comp_node.children = []
                        if type_repr(comp_node.type) == 'comp_for':
                            comp_node.type = sym_type('for_stmt')
                        else:
                            comp_node.type = sym_type('if_stmt')
                        child = childs.next()
                except StopIteration:
                    pass
                comp_node.append_child(Leaf(11, ':'))
                comp_node.append_child(simple_stmt)
                lines = self.lines
                self.lines = []
                self.node_for_stmt(base_node)
                i = self.indent_level - 1
                comp = '\n'.join(["%s%s" % ('+' * (j-i), s) for j, s in self.lines])
                self.lines = lines
                jsvars = self.jsvars.copy()
                jsvars.update(locals())
                retval = 'comp$'
                if cls != 'list':
                    retval = "%(module)s['$new'](%(builtin)s['%(cls)s'], comp$)" % jsvars
                jsvars.update(locals())
                return """\
(function() {
+   var comp$ = %(module)s['$new'](%(builtin)s['list'], []);
%(comp)s
+   return %(retval)s;
})()""" % jsvars

            else:
                items.append(self.dispatch(child))
        return items

    def node_not_test(self, node, jsbool=False, name=None):
        jsvars = self.jsvars.copy()
        if len(node.children) == 2:
            self.assert_value(node, node.children[0].value, 'not')
            value = self.dispatch(node.children[1])
            jsvars.update(locals())
            if jsbool:
                return "%(builtin)s['test_not'](%(value)s)" % jsvars

            return "%(builtin)s['op_not'](%(value)s)" % jsvars
        self.not_implemented(node)

    def node_old_lambdef(self, node):
        self.not_implemented(node)

    def node_old_test(self, node):
        self.not_implemented(node)

    def node_or_test(self, node, jsbool=False, name=None):
        jsvars = self.jsvars.copy()
        args = []
        childs = node.children.__iter__()
        if jsbool:
            name = None
        elif name is None:
            name = self.get_tmp_jsname('or$')
            self.add_lines("var %s" % name)
        args.append(self.get_test(childs.next(), name))
        try:
            while True:
                self.assert_value(node, childs.next().value, 'or')
                args.append(self.get_test(childs.next(), name))
        except StopIteration:
            pass
        test = ' || '.join(args)
        if jsbool:
            return test
        return '(%s ? %s : %s)' % (test, name, name)

    def node_parameters(self, node):
        self.assert_value(node, node.children[0].value, '(')
        self.assert_value(node, node.children[-1].value, ')')
        assert len(node.children) <= 3
        if len(node.children) == 2:
            return Parameters([], None, None, None)
        if isinstance(node.children[1], Leaf):
            args = node.children[1].value
        else:
            args = self.dispatch(node.children[1])
        if isinstance(args, basestring):
            return Parameters([args], None, None, None)
        return self.dispatch(node.children[1])

    def node_pass_stmt(self, node):
        self.not_implemented(node)

    def node_power(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        left = self.dispatch(childs.next())
        if isinstance(node.children[1], Leaf):
            if node.children[1].value == '**':
                assert len(node.children) == 3
                jsvars.update(
                    left=self.dispatch(node.children[0]),
                    right=self.dispatch(node.children[2]),
                )
                return "%(builtin)s['op_pow'](%(left)s, %(right)s)" % jsvars
        elif isinstance(node.children[1], Node):
            attrs = []
            lineno = self.track_lineno(node)
            for child in node.children[1:]:
                if isinstance(child, Leaf) and \
                   child.value == '**':
                    assert child is node.children[-2]
                    jsvars.update(
                        left=left,
                        right=self.dispatch(node.children[-1]),
                    )
                    return "%(builtin)s['op_pow'](%(left)s, %(right)s)" % jsvars
                trailer = self.dispatch(child)
                if isinstance(trailer, Attribute):
                    assert not isinstance(left, __Pyjamas__.__Pyjamas__), node
                    attrs.append(trailer.name)
                elif isinstance(trailer, Slice):
                    assert not isinstance(left, __Pyjamas__.__Pyjamas__), node
                    assign = self.assign_state is not False and \
                             child is node.children[-1]
                    if assign is False:
                        method = "'getslice'"
                    else:
                        method = "'setslice'"
                    if len(trailer.items) == 1:
                        if assign is False:
                            method = '%(getitem)s' % jsvars
                        else:
                            method = "'setitem'" % jsvars
                        args = trailer.items[0]
                    elif len(trailer.items) == 2:
                        args = list(trailer.items)
                        if args[0] == None:
                            args[0] = self.add_const_int(0)
                        if args[1] == None:
                            args[1] = self.add_const_int(2147483647)
                        args = "[%s]" % ', '.join(str(i) for i in args)
                    else:
                        args = []
                        for a in trailer.items:
                            if a is None:
                                args.append(jsvars['None'])
                            else:
                                args.append(a)
                        args = ', '.join(args)
                        jsvars.update(args=args)
                        args = "%(fcall)s(%(module)s, null, %(builtin)s['slice'], null, %(args)s)" % jsvars
                    if attrs:
                        attrs = ', '.join(attrs)
                        jsvars.update(attrs=attrs, left=left)
                        left = """\
%(getattr)s(%(left)s, [%(attrs)s])""" % jsvars
                        attrs = []
                    jsvars.update(locals())
                    if self.assign_state is False:
                        left = """\
%(builtin)s[%(method)s](%(left)s, %(args)s)""" % jsvars
                    else:
                        jsvars['what'] = self.assign_state
                        left = """\
%(builtin)s[%(method)s](%(left)s, %(args)s, %(what)s)""" % jsvars
                elif isinstance(trailer, Parameters):

                    params = trailer
                    args = ''
                    if params.args:
                        args += ', ' + ', '.join([str(a) for a in params.args])
                    star_args = params.star_args
                    dstar_args = params.dstar_args
                    named_args = params.named_args
                    extended = False
                    if star_args or dstar_args or named_args:
                        extended = True
                        if star_args is None:
                            star_args = 'null'
                        if dstar_args is None:
                            dstar_args = 'null'
                        if named_args is None:
                            named_args = 'null'
                        else:
                            named_args = ', '.join([
                                '%r: %s' % (k, v) for k,v in named_args.iteritems()
                            ])
                            named_args = "{%s}" % named_args
                    if isinstance(left, __Pyjamas__.__Pyjamas__):
                        if params.named_args is None:
                            left = Code(left.js(self, *params.args), self.get_lineno(node))
                        else:
                            left = Code(left.js(self, *params.args, **params.named_args), self.get_lineno(node))
                    elif not attrs:
                        jsvars.update(locals())
                        if star_args is None:
                            left = """\
%(fcall)s(%(module)s, %(lineno)s, %(left)s, null%(args)s)""" % jsvars
                        else:
                            left = """\
%(fcallext)s(%(module)s, %(lineno)s, %(left)s, null%(args)s, %(star_args)s, %(dstar_args)s, %(named_args)s)""" % jsvars
                    else:
                        attrs = ', '.join(attrs)
                        jsvars.update(locals())
                        if star_args is None:
                            left = """\
%(mcall)s(%(module)s, %(lineno)s, %(left)s, [%(attrs)s]%(args)s)""" % jsvars
                        else:
                            left = """\
%(mcallext)s(%(module)s, %(lineno)s, %(left)s, [%(attrs)s]%(args)s, %(star_args)s, %(dstar_args)s, %(named_args)s)""" % jsvars
                    attrs = []
            if attrs:
                attrs = ', '.join(attrs)
                if self.assign_state is False:
                    jsvars.update(locals())
                    return Code("""\
%(getattr)s(%(left)s, [%(attrs)s])""" % jsvars, self.get_lineno(node))
                else:
                    value = self.assign_state
                    jsvars.update(locals())
                    return Code("""\
%(setattr)s(%(left)s, [%(attrs)s], %(value)s)""" % jsvars, self.get_lineno(node))
            return Code(left, self.get_lineno(node))

        self.not_implemented(node)

    def node_print_stmt(self, node):
        if self.options.print_statements is False:
            return
        jsvars = self.jsvars.copy()
        self.assert_value(node, node.children[0].value, 'print')
        args = []
        for child in node.children[1:]:
            if isinstance(child, Leaf) and \
               child.value == ',':
                continue
            arg = self.dispatch(child)
            if child is not None:
                args.append(arg)
        newline = 'true'
        if isinstance(node.children[-1], Leaf) and \
           node.children[-1].value == ',':
            newline = 'false'
        args = ', '.join([str(i) for i in args])
        jsvars.update(locals())
        return """\
%(builtin)s['printFunc']([%(args)s], %(newline)s)""" % jsvars

    def node_raise_stmt(self, node):
        jsvars = self.jsvars.copy()
        args = []
        for child in node.children[1:]:
            if isinstance(child, Leaf) and child.value == ',':
                continue
            args.append(self.dispatch(child))
        args = ', '.join([str(a) for a in args])
        jsvars.update(locals())
        return "return %(builtin)s['raise'](%(args)s)" % jsvars

    def node_return_stmt(self, node):
        assert len(node.children) == 2
        value = self.dispatch(node.children[1])
        if isinstance(value, list):
            jsvars = self.jsvars.copy()
            items = ', '.join([str(i) for i in value])
            jsvars.update(locals())
            return "return %(tuple)s([%(items)s])" % jsvars
        return "return %s" % value

    def node_shift_expr(self, node):
        return self.get_bit_expr(node)

    def node_simple_stmt(self, node):
        for child in node.children:
            if isinstance(child, Leaf):
                if child.value in ['break', 'continue']:
                    self.add_lines('%s;' % child.value, self.get_lineno(child))
                    continue
            code = self.dispatch(child)
            if isinstance(code, Code):
                code = code.code
                code = str(code)
            if code is not None:
                if code[-1] not in [';', '}']:
                    code += ';'
                self.add_lines(code, self.get_lineno(child))
                #self.add_lines(code)

    def node_single_input(self, node):
        self.not_implemented(node)

    def node_sliceop(self, node):
        assert len(node.children) == 2
        self.assert_value(node, node.children[0].value, ':')
        return self.dispatch(node.children[1])

    def node_small_stmt(self, node):
        self.not_implemented(node)

    def node_star_expr(self, node):
        self.not_implemented(node)

    def node_stmt(self, node):
        self.not_implemented(node)

    def node_subscript(self, node):
        slice = [None]
        for child in node.children:
            if isinstance(child, Leaf) and child.value == ':':
                slice.append(None)
                continue
            slice[-1] = self.dispatch(child)
        return Slice(tuple(slice))

    def node_subscriptlist(self, node):
        # d = {}; d[1,2] = 1
        jsvars = self.jsvars.copy()
        args = []
        childs = node.children.__iter__()
        args.append(self.dispatch(childs.next()))
        try:
            while True:
                self.assert_value(node, childs.next().value, ',')
                args.append(self.dispatch(childs.next()))
        except StopIteration:
            pass
        args = ', '.join([str(i) for i in args])
        jsvars.update(locals())
        return "%(tuple)s([%(args)s])" % jsvars

    def node_suite(self, node):
        for child in node.children:
            if isinstance(child, Node):
                self.dispatch(child)

    def node_term(self, node):
        # x * y / x
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        left = self.dispatch(childs.next())
        try:
            while True:
                op = childs.next().value
                right = self.dispatch(childs.next())
                op = self.op_names2.get(op, None)
                if op is None:
                    self.not_implemented(node)
                jsvars.update(left=left, op=op, right=right)
                left = "%(builtin)s[%(op)r](%(left)s, %(right)s)" % jsvars
        except StopIteration:
            pass
        return left

    def node_test(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        left = self.dispatch(childs.next())
        self.assert_value(node, childs.next().value, 'if')
        test = self.get_test(childs.next())
        self.assert_value(node, childs.next().value, 'else')
        right = self.dispatch(childs.next())
        return '%s ? %s : %s' % (test, left, right)

    def node_testlist(self, node):
        items = []
        childs = node.children.__iter__()
        try:
            while True:
                items.append(self.dispatch(childs.next()))
                self.assert_value(node, childs.next().value, ',')
        except StopIteration:
            pass
        return items

    def node_testlist1(self, node):
        self.not_implemented(node)

    def node_testlist_gexp(self, node):
        items = []
        for child in node.children:
            if isinstance(child, Leaf):
                if child.value == ',':
                    continue
            else:
                if type_repr(child.type) == 'comp_for':
                    return self.node_listmaker(node, cls='tuple')
            items.append(self.dispatch(child))
        return items

    def node_testlist_safe(self, node):
        self.not_implemented(node)

    def node_testlist_star_expr(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        items = []
        try:
            while True:
                items.append(self.dispatch(childs.next()))
                self.assert_value(node, childs.next().value, ',')
        except StopIteration:
            pass
        cls = 'tuple'
        items = ', '.join([str(i) for i in items])
        jsvars.update(locals())
        return "%(module)s['$new'](%(builtin)s['%(cls)s'], [%(items)s])" % jsvars

    def node_tfpdef(self, node):
        childs = node.children.__iter__()
        self.assert_value(node, childs.next().value, '(')
        tpl = self.dispatch(childs.next())
        self.assert_value(node, childs.next().value, ')')
        return tuple(tpl)

    def node_tfplist(self, node):
        childs = node.children.__iter__()
        tpl = []
        try:
            while True:
                child = childs.next()
                if isinstance(child, Leaf):
                    tpl.append(child.value)
                else:
                    tpl.append(self.dispatch(child))
                self.assert_value(node, childs.next().value, ',')
        except StopIteration:
            pass
        return tpl

    def node_tname(self, node):
        self.not_implemented(node)

    def node_trailer(self, node):
        if node.children[0].value == '(':
            args = []
            star_args = None
            dstar_args = None
            defaults = None
            childs = node.children.__iter__()
            self.assert_value(node, childs.next().value, '(')
            while True:
                child = childs.next()
                if isinstance(child, Leaf):
                    if child.value == ')':
                        break
                    args.append(self.dispatch(child))
                else:
                    arg = self.dispatch(child)
                    if isinstance(arg, list):
                        args += arg
                    else:
                        args.append(arg)
            return Parameters(args, star_args, dstar_args, defaults)
        elif node.children[0].value == '.':
            assert len(node.children) == 2
            if isinstance(node.children[1], Leaf):
                return Attribute(repr(node.children[1].value))
            return Attribute(self.dispatch(node.children[1]))
        elif node.children[0].value == '[':
            slice = []
            assert len(node.children) == 3
            if isinstance(node.children[1], Leaf) and \
               node.children[1].value == ':':
                return Slice((None, None))
            slice = self.dispatch(node.children[1])
            if isinstance(slice, Slice):
                return slice
            return Slice((slice, ))

        self.not_implemented(node)

    def node_try_stmt(self, node):
        jsvars = self.jsvars.copy()
        childs = node.children.__iter__()
        # syntax ensures fixed order
        # try:
        # except-clauses:
        # except:
        # else:
        # finally
        self.assert_value(node, childs.next().value, 'try')
        self.assert_value(node, childs.next().value, ':')
        _try = childs.next()
        _except_clauses = []
        _except = None
        _else = None
        _finally = None
        try:
            while True:
                child = childs.next()
                if isinstance(child, Leaf):
                    if child.value == 'except':
                        self.assert_value(node, childs.next().value, ':')
                        _except = childs.next()
                    elif child.value == 'else':
                        self.assert_value(node, childs.next().value, ':')
                        _else = childs.next()
                    elif child.value == 'finally':
                        self.assert_value(node, childs.next().value, ':')
                        _finally = childs.next()
                    else:
                        raise NotImplementedError(repr(node))
                elif type_repr(child.type) == 'except_clause':
                    self.assert_value(node, childs.next().value, ':')
                    _except_clauses.append((child, childs.next()))
                else:
                    raise NotImplementedError(repr(node))
        except StopIteration:
            pass
        track_len = self.get_tmp_jsname('track$len')
        self.add_lines("var %s = $pyjs.trackstack.length;" % track_len)
        self.add_lines("try {", node.children[0].lineno)
        self.indent()
        self.dispatch(_try)
        if _else is not None:
            self.add_lines("throw %(try_else)s" % jsvars)
        self.dedent()
        self.add_lines("} catch (%(catch)s) {" % jsvars)
        self.indent()
        self.add_lines("var %(catchclass)s = %(catch)s['__class__'];" % jsvars)
        self.add_lines(
            "$pyjs.trackstack.splice(%s, $pyjs.trackstack.length);" % (
                track_len,
            ),
        )
        elseif = "if"
        jsvars.update(locals())
        if _else is not None:
            self.add_lines("if (%(catchclass)s === %(try_else)s['__class__']) {" % jsvars)
            self.indent()
            self.dispatch(_else)
            self.dedent()
            elseif = "} else if"
        for clause, suite in _except_clauses:
            # See node_except_clause
            classes, varname = self.dispatch(clause)
            jsvars['classes'] = ', '.join([str(i) for i in classes])
            jsvars['elseif'] = elseif
            self.add_lines("""%(elseif)s(%(builtin)s['_issubclass'](%(catchclass)s, [%(classes)s])) {""" % jsvars)
            self.indent()
            if varname:
                self.add_lines("%s = %s;" % (varname, jsvars['catch']))
            self.dispatch(suite)
            self.dedent()
            elseif = "} else if"
        if elseif != "if":
            self.add_lines("} else {")
            self.indent()
        if _except is None:
            self.add_lines("throw %(catch)s;" % jsvars)
        else:
            self.dispatch(_except)
        if elseif != "if":
            self.dedent()
            self.add_lines("}")
        if _finally is not None:
            self.dedent()
            self.add_lines("} finally {")
            self.indent()
            self.dispatch(_finally)
        self.dedent()
        self.add_lines("}")

    def node_typedargslist(self, node):
        childs = node.children.__iter__()
        args = []
        star_args = None
        dstar_args = None
        defaults = []
        try:
            while True:
                child = childs.next()
                if isinstance(child, Leaf):
                    if child.value == '*':
                        star_args = childs.next().value
                    elif child.value == '**':
                        dstar_args = childs.next().value
                    elif child.value == '=':
                        defaults.append(childs.next())
                    elif child.value != ',':
                        args.append(child.value)
                elif type_repr(child.type) == 'tfpdef':
                    args.append(self.dispatch(child))
                else:
                    self.not_implemented(node)
        except StopIteration:
            pass
        return Parameters(args, star_args, dstar_args, defaults)

    def node_varargslist(self, node):
        # Used from node_lambdef:
        # f = lambda a, *args, **kwargs: tuple([a, args, kwargs])
        return self.node_typedargslist(node)

    def node_vfpdef(self, node):
        self.not_implemented(node)

    def node_vfplist(self, node):
        self.not_implemented(node)

    def node_vname(self, node):
        self.not_implemented(node)

    def node_while_stmt(self, node):
        jsvars = self.jsvars.copy()
        inloop = self.inloop
        self.inloop += 1
        childs = node.children.__iter__()
        self.assert_value(node, childs.next().value, 'while')
        test = self.get_test(childs.next())
        self.assert_value(node, childs.next().value, ':')
        if len(node.children) > 4 and node.children[4].value == 'else':
            loop = self.get_tmp_jsname('while$')
            loopdecl = 'var %s = false;\n' % loop
            loopass = '\n+%s = true;' % loop
        else:
            loop = None
            loopdecl = loopass = ''
        jsvars.update(locals())
        self.add_lines("""\
%(loopdecl)swhile (%(test)s) {%(loopass)s""" % jsvars, node.children[0].lineno)
        self.indent()
        self.dispatch(childs.next())
        self.dedent()
        self.add_lines("};")
        if loop is not None:
            self.assert_value(node, childs.next().value, 'else')
            self.assert_value(node, childs.next().value, ':')
            self.add_lines("""\
if (!(%(loop)s).valueOf()) {""" % jsvars, )
            self.indent()
            self.dispatch(childs.next())
            self.dedent()
            self.add_lines("};")
        self.inloop -= 1

    def node_with_item(self, node):
        self.not_implemented(node)

    def node_with_stmt(self, node):
        self.not_implemented(node)

    def node_with_var(self, node):
        self.not_implemented(node)

    def node_xor_expr(self, node):
        return self.get_bit_expr(node)

    def node_yield_expr(self, node):
        return
        self.not_implemented(node)

    def node_yield_stmt(self, node):
        return
        self.not_implemented(node)


    def leaftype_name(self, leaf):
        # type 1
        if leaf.value.find('$') >= 0:
            # this is an internal javascript variable
            return leaf.value
        self.add_name(leaf.value, leaf.lineno, force=False)
        return self.get_jsname(leaf.value)

    def leaftype_number(self, leaf):
        # type 2
        if re_oct_int.match(leaf.value):
            i = str(int(leaf.value, 8))
            return self.add_const_int(i)
        if re_hex_int.match(leaf.value):
            i = str(int(leaf.value, 16))
            return self.add_const_int(i)
        if re_int.match(leaf.value):
            return self.add_const_int(leaf.value)
        if re_oct_long.match(leaf.value):
            i = str(long(leaf.value, 16))
            return self.add_const_long(i)
        if re_hex_long.match(leaf.value):
            i = str(long(leaf.value, 16))
            return self.add_const_long(i)
        if re_long.match(leaf.value):
            return self.add_const_long(leaf.value)
        return self.add_const_float(leaf.value)

    def substitute_js_chars(self, m):
        c = m.group(0)
        i = ord(c)
        if i < 32:
            return '\\x%02X' % i
        if c in ["'", '"', '<', '>', '\\']:
            return '\\x%02X' % i
        return c

    def leaftype_str(self, leaf):
        # type 3
        s = leaf.value
        return self.add_const_str(eval(s))

    def leaf_False(self, leaf):
        return self.jsvars['False']

    def leaf_None(self, leaf):
        return self.jsvars['None']

    def leaf_True(self, leaf):
        return self.jsvars['True']

    def leaf_pass(self, leaf):
        return None

    def leaf_return(self, leaf):
        return 'return null'


###
# External hooks as in translator_proto
###

from options import (all_compile_options, add_compile_options,
                     get_compile_options, debug_options, speed_options,
                     pythonic_options)

if os.environ.has_key('PYJS_SYSPATH'):
    sys.path[0:0] = [os.environ['PYJS_SYSPATH']]

import pyjs

LIBRARY_PATH = os.path.abspath(os.path.dirname(__file__))


TranslationError = Translator.TranslationError

def translate(sources, output_file, module_name=None, **kw):
    global TranslationError
    kw = dict(all_compile_options, **kw)
    list_imports = kw.get('list_imports', False)
    sources = map(os.path.abspath, sources)
    output_file = os.path.abspath(output_file)
    if not module_name:
        module_name, extension = os.path.splitext(os.path.basename(sources[0]))

    translator = Translator(sources[0], module_name, kw)
    TranslationError = translator.TranslationError
    trees = []
    tree = None
    for src in sources:
        current_tree = translator.ast_tree_creator(src)
        flags = set()
        f = file(src)
        for l in f:
            if l.startswith('#@PYJS_'):
                flags.add(l.strip()[7:])
        f.close()
        if tree:
            tree = translator.tree_merge(tree, current_tree, flags)
        else:
            tree = current_tree
    #XXX: if we have an override the sourcefile and the tree is not the same!
    f = file(sources[0], "r")
    src = f.read()
    f.close()
    if list_imports:
        # TODO: use ImportVisitor instead of Translator
        translator.dispatch_file(tree)
        return translator.imported_modules.keys(), translator.imported_js.keys()
        v = ImportVisitor(module_name)
        compiler.walk(tree, v)
        return v.imported_modules, v.imported_js

    translator.dispatch_file(tree)

    if output_file == '-':
        output = sys.stdout
    else:
        output = file(output_file, 'w')
    output.write(translator.get_javascript())
    output.close()
    return sorted(translator.imported_modules.keys()), sorted(translator.imported_js.keys())


class ImportVisitor(object):

    def __init__(self, module_name):
        self.module_name = module_name
        self.imported_modules = []
        self.imported_js = []

    def add_imported_module(self, importName):
        if not importName in self.imported_modules:
            self.imported_modules.append(importName)

    def visitModule(self, node):
        self.visit(node.node)

    def visitImport(self, node):
        self._doImport(node.names)

    def _doImport(self, names):
        for importName, importAs in names:
            if importName == '__pyjamas__':
                continue
            if importName.endswith(".js"):
                continue
                imp.add_imported_js(importName)
                continue

            self.add_imported_module(importName)

    def visitFrom(self, node):
        if node.modname == '__pyjamas__':
            return
        if node.modname == '__javascript__':
            return
        # XXX: hack for in-function checking, we should have another
        # object to check our scope
        absPath = False
        modname = node.modname
        if hasattr(node, 'level') and node.level > 0:
            absPath = True
            modname = self.module_name.split('.')
            level = node.level
            if len(modname) < level:
                raise TranslationError(
                    "Attempted relative import beyond toplevel package",
                    node, self.module_name)
            if node.modname != '':
                level += 1
            if level > 1:
                modname = '.'.join(modname[:-(node.level-1)])
            else:
                modname = self.module_name
            if node.modname != '':
                modname += '.' + node.modname
                if modname[0] == '.':
                    modname = modname[1:]
        for name in node.names:
            sub = modname + '.' + name[0]
            ass_name = name[1] or name[0]
            self._doImport(((sub, ass_name),))


if __name__ == "__main__":
    translator = Translator(sys.argv[1], None, {})
    translator.tree = translator.ast_tree_creator()
    translator.dispatch_file(translator.tree)
    print translator.get_javascript()
