from optparse import SUPPRESS_HELP, NO_DEFAULT
from logging import warn

#-----------------------------------------------------------( group namespace )

class Groups(object):

    ALL        = ('all',     True)
    DEFAULT    = ('default', True)
    NODEFAULT  = ('default', False)
    DEBUG      = ('debug',   True)
    NODEBUG    = ('debug',   False)
    SPEED      = ('speed',   True)
    NOSPEED    = ('speed',   False)
    STRICT     = ('strict',  True)
    NOSTRICT   = ('strict',  False)

#----------------------------------------------------------( option container )

class Mappings(object):

    class Defaults(object):

        def __init__(self, mappings, *grps):
            self._mappings = mappings
            self._groups = set(grps) & set(mappings._groups_cache.keys())

        def __iter__(self):
            for grp in self._groups:
                for dest in self._mappings._groups_cache[grp]:
                    yield dest

        def __getitem__(self, key, exc=KeyError):
            for grp in self._groups:
                if key in self._mappings._groups_cache[grp]:
                    return grp[1]
            raise exc(key)

        __getattr__ = lambda k: self.__getitem__(k, exc=AttributeError)

        def iteritems(self):
            for o in self:
                yield (o, self[o])

        def items(self):
            return list(self.iteritems())

        def keys(self):
            return list(self)

        def get(self, key, *args):
            try:
                return self[key]
            except KeyError:
                if args:
                    return args[0]
                raise

    _opt_sig = ('names', 'aliases', 'groups', 'spec')
    _grp_sig = ('names', 'aliases', 'spec')
    _opt_sig_hash = set(_opt_sig)
    _grp_sig_hash = set(_grp_sig)

    _opt_types = {str: 'string', int: 'int', long: 'long',
                  float: 'float', complex: 'complex',
                  NO_DEFAULT: 'string'}

    def __init__(self):
        groups = dict()
        for n, g in Groups.__dict__.iteritems():
            if not n.startswith('_'):
                groups[g] = set()
        super(self.__class__, self).__setattr__('_order', list())
        super(self.__class__, self).__setattr__('_cache', dict())
        super(self.__class__, self).__setattr__('_groups', dict())
        super(self.__class__, self).__setattr__('_groups_cache', groups)

    def __iter__(self):
        for k in self._order:
            yield k

    def __contains__(self, key):
        return key in self._cache

    def __getitem__(self, key, exc=KeyError):
        try:
            return self._cache[key]
        except KeyError:
            raise exc(key)

    def __setitem__(self, key, kwds):
        if not key:
            raise TypeError('Malformed name.')
        n = 'opt'
        if key.isupper():
            n = 'grp'
        new = '_%s' % n
        sig = '_%s_sig' % n
        sig_hash = '_%s_sig_hash' % n
        try:
            None in kwds
        except TypeError:
            raise TypeError('Must pass list or dict.')
        else:
            try:
                kwds[None]
            except TypeError:
                kwds= dict(zip(getattr(self, sig), kwds))
            except KeyError:
                pass
        if set(kwds.keys()) != getattr(self, sig_hash):
            raise TypeError('Malformed signature.')
        getattr(self, new)(key, **kwds)

    __getattr__ = lambda k: self.__getitem__(k, exc=AttributeError)
    __setattr__ = __setitem__

    def _opt(self, dest, **kwds):
        if not dest or set(kwds.keys()) != self._opt_sig_hash:
            raise TypeError('Malformed option signature.')
        for k in ('aliases', 'groups', 'names'):
            kwds[k] = list(kwds[k])
        spec = kwds['spec']
        spec['dest'] = dest
        tf = (True, False)
        tfs = ''
        pat = '%(help)s%(tfs)s'
        default = spec.setdefault('default', NO_DEFAULT)
        default_type = self._opt_types.get(type(default), None)
        self._groups_cache[Groups.ALL].add(dest)
        for g in kwds['groups']:
            self._groups_cache[g].add(dest)
        if default is True:
            self._groups_cache[Groups.DEFAULT].add(dest)
        elif default is False:
            self._groups_cache[Groups.NODEFAULT].add(dest)
        if default in tf:
            spec['action'] = 'store_true'
        if 'action' not in spec:
            spec['action'] = 'store'
        if 'choices' in spec:
            spec['type'] = 'choice'
        if 'type' not in spec:
            spec['type'] = default_type
        if default in tf or default_type is not None:
            tfs = ' [%default]'
        spec['help'] = pat % {'tfs': tfs,
                              'help': spec['help']}
        if spec['action'] != 'callback':
            spec['callback'] = self._opt_set
            spec['callback_kwargs'] = {'_action': spec['action'],
                                       '_cache': kwds}
            spec['action'] = 'callback'
        for k, nk in (('names', 'nonames'), ('aliases', 'noaliases')):
            no = kwds[nk] = list()
            for n in kwds[k]:
                for repl in [('--with', '--without', 1),
                             ('--enable', '--disable', 1),
                             ('--', '--no-', 1)]:
                    rev = n.replace(*repl)
                    if rev != n:
                        no.append(rev)
        self._order.append(dest)
        self._cache[dest] = kwds

    def _grp(self, dest, **kwds):
        if not dest or set(kwds.keys()) != self._grp_sig_hash:
            raise TypeError('Malformed group signature.')
        for k in ('aliases', 'names'):
            kwds[k] = list(kwds[k])
        dest = getattr(Groups, dest)
        spec = kwds['spec']
        spec['action'] = 'callback'
        spec['callback'] = self._grp_set
        spec['callback_kwargs'] = {'_group': dest}
        for k, nk in (('names', 'nonames'), ('aliases', 'noaliases')):
            no = kwds[nk] = list()
            for n in kwds[k]:
                for repl in [('--with', '--without', 1),
                             ('--enable', '--disable', 1),
                             ('--', '--no-', 1)]:
                    rev = n.replace(*repl)
                    if rev != n:
                        no.append(rev)
        self._groups[dest] = kwds

    def _opt_set(self, inst, opt, value, parser, *args, **kwds):
        cache = kwds['_cache']
        action = kwds['_action']
        positive = kwds['_positive']
        alternates = kwds['_alternates']
        tf = {'store_true': positive and 'store_true' or 'store_false',
              'store_false': positive and 'store_false' or 'store_true'}
        if alternates:
            warn('[%s] is deprecated, see [%s]' % (opt, ', '.join(alternates)))
        inst.take_action(tf.get(action, action), inst.dest,
                         opt, value, parser.values, parser)

    def _grp_set(self, inst, opt, value, parser, *args, **kwds):
        name, flag = kwds['_group']
        positive = kwds['_positive']
        alternates = kwds['_alternates']
        tf = {True: positive, False: not positive}
        if alternates:
            warn('[%s] is deprecated, see [%s]' % (opt, ', '.join(alternates)))
        for boolean in tf:
            for dest in self._groups_cache[name, boolean]:
                setattr(parser.values, dest, tf[boolean])

    def iteritems(self):
        for o in self:
            yield (o, self[o])

    def items(self):
        return list(self.iteritems())

    def keys(self):
        return list(self)

    def get(self, key, *args):
        try:
            return self[key]
        except KeyError:
            if args:
                return args[0]
            raise

    def defaults(self, *grps):
        return self.Defaults(self, *grps)

    def bind(self, parser):
        for x in (self._groups, self):
            for k, o in x.iteritems():
                for key, pub, pos, alt in [('names', True, True, None),
                                           ('nonames', False, False, None),
                                           ('aliases', False, True, o['names']),
                                           ('noaliases', False, False, o['nonames'])]:
                    signatures = o[key]
                    if signatures:
                        spec = o['spec'].copy()
                        kwds = spec['callback_kwargs'].copy()
                        kwds.update({'_positive': pos, '_alternates': alt})
                        if not pub:
                            spec.update({'help': SUPPRESS_HELP})
                        spec.update({'callback_kwargs': kwds})
                        parser.add_option(*signatures, **spec)

    def link(self, options):
        ret = {}
        for k in self:
            ret[k] = getattr(options, k)
        return ret

#----------------------------------------------------------( mapping instance )

mappings = Mappings()

#---------------------------------------------------------( group definitions )

mappings.DEFAULT = (
    ['--enable-default', '-D'],
    [],
    dict(help='(group) enable DEFAULT options')
)
mappings.DEBUG = (
    ['--enable-debug', '-d'],
    ['--debug'],
    dict(help='(group) enable DEBUG options')
)
mappings.SPEED = (
    ['--enable-speed', '-O'],
    [],
    dict(help='(group) enable SPEED options, degrade STRICT')
)
mappings.STRICT = (
    ['--enable-strict', '-S'],
    ['--strict'],
    dict(help='(group) enable STRICT options, degrade SPEED')
)

#--------------------------------------------------------( option definitions )

mappings.debug = (
    ['--enable-wrap-calls'],
    ['--debug-wrap'],
    [Groups.DEBUG, Groups.NOSPEED],
    dict(help='enable call site debugging',
         default=False)
)
mappings.print_statements = (
    ['--enable-print-statements'],
    ['--print-statements'],
    [Groups.NOSPEED],
    dict(help='enable printing to console',
         default=True)
)
mappings.function_argument_checking = (
    ['--enable-check-args'],
    ['--function-argument-checking'],
    [Groups.STRICT, Groups.NOSPEED],
    dict(help='enable function argument validation',
         default=False)
)
mappings.attribute_checking = (
    ['--enable-check-attrs'],
    ['--attribute-checking'],
    [Groups.STRICT, Groups.NOSPEED],
    dict(help='enable attribute validation',
         default=False)
)
mappings.getattr_support = (
    ['--enable-accessor-proto'],
    ['--getattr-support'],
    [Groups.STRICT, Groups.NOSPEED],
    dict(help='enable __get/set/delattr__() accessor protocol',
         default=True)
)
mappings.bound_methods = (
    ['--enable-bound-methods'],
    ['--bound-methods'],
    [Groups.STRICT, Groups.NOSPEED],
    dict(help='enable proper method binding',
         default=True)
)
mappings.descriptors = (
    ['--enable-descriptor-proto'],
    ['--descriptors'],
    [Groups.STRICT, Groups.NOSPEED],
    dict(help='enable __get/set/del__ descriptor protocol',
         default=False)
)
mappings.source_tracking = (
    ['--enable-track-sources'],
    ['--source-tracking'],
    [Groups.DEBUG, Groups.STRICT, Groups.NOSPEED],
    dict(help='enable tracking original sources',
         default=False)
)
mappings.line_tracking = (
    ['--enable-track-lines'],
    ['--line-tracking'],
    [Groups.DEBUG, Groups.STRICT],
    dict(help='enable tracking original sources: every line',
         default=False)
)
mappings.store_source = (
    ['--enable-store-sources'],
    ['--store-source'],
    [Groups.DEBUG, Groups.STRICT],
    dict(help='enable storing original sources in javascript',
         default=False)
)
mappings.inline_code = (
    ['--enable-inline-code'],
    ['--inline-code'],
    [Groups.SPEED],
    dict(help='enable bool/eq/len inlining',
         default=False)
)
mappings.operator_funcs = (
    ['--enable-operator-funcs'],
    ['--operator-funcs'],
    [Groups.STRICT, Groups.NOSPEED],
    dict(help='enable operators-as-functions',
         default=True)
)
mappings.number_classes = (
    ['--enable-number-classes'],
    ['--number-classes'],
    [Groups.STRICT, Groups.NOSPEED],
    dict(help='enable float/int/long as classes',
         default=False)
)
mappings.create_locals = (
    ['--enable-locals'],
    ['--create-locals'],
    [],
    dict(help='enable locals()',
         default=False)
)
mappings.stupid_mode = (
    ['--enable-stupid-mode'],
    ['--stupid-mode'],
    [],
    dict(help='enable minimalism by relying on javascript-isms',
         default=False)
)
mappings.translator = (
    ['--use-translator'],
    ['--translator'],
    [],
    dict(help='override translator',
         choices=['proto', 'dict'],
         default='proto')
)
#mappings.internal_ast = (
#    ['--enable-internal-ast'],
#    ['--internal-ast'],
#    [],
#    dict(help='enable internal AST parsing',
#         default=True)
#)

#----------------------------------------------------------( public interface )

get_compile_options = mappings.link
add_compile_options = mappings.bind

debug_options = mappings.defaults(Groups.DEBUG, Groups.NODEBUG)
speed_options = mappings.defaults(Groups.SPEED, Groups.NOSPEED)
pythonic_options = mappings.defaults(Groups.STRICT, Groups.NOSTRICT)
all_compile_options = mappings.defaults(Groups.ALL)
