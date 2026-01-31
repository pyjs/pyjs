import inspect


DECORATIONS = {
    # safe to analyze and transpile
    "__js__",  # bool

    # do not analyze or transpile
    # eg. class is marked safe but you want to exclude a specific method
    "__nojs__",  # bool

    # include in output even if not visited
    "__js_include__",  # bool

    # use different implementation of a Python method on client by
    # replacing it with the function in the decoration, which is then
    # transpiled
    "__js_replace__",  # function

    # similar to __js_replace__ but no transpiling occurs; instead,
    # the function is expected to return the JavaScript source as string
    "__js_rewrite_func__",  # function

    # returns JavaScript source as string, replaces the code at
    # every call site where this function is called
    "__js_rewrite_call_site__",  # function

    # returns JavaScript source as string, appending the code
    # after the definition of the wrapped code object
    "__js_append__",  # function

    # safe to analyze but don't include in output
    "__builtin__",  # bool

    # do not analyze function
    "__no_analyze__",  # bool
}


def is_cls_or_func(obj):
    return inspect.isfunction(obj) or inspect.isclass(obj)


def has_inline_decorator(obj):
    return obj.__dict__.get("__js_rewrite_call_site__", False)


def has_source_decorator(obj):
    return obj.__dict__.get("__js_rewrite_func__", False)


def has_no_analyze(obj):
    return obj.__dict__.get("__no_analyze__", False)


def should_analyze_func_body(obj):
    return not (
        has_inline_decorator(obj) or
        has_source_decorator(obj) or
        has_no_analyze(obj)
    )


def has_include_decorator(obj):
    return obj.__dict__.get("__js_include__", False)


def should_include(obj):
    return (
        has_include_decorator(obj.py_obj) or
        bool(obj.visited)
    ) and not obj.py_obj.__dict__.get("__builtin__", False)


def js(*cls_func_args, inline=None, builtin=None, include=None, analyze=None):

    class Wrapper:

        def __init__(self, inline, builtin, include, analyze):
            self.inline = inline
            self.builtin = builtin
            self.include = include
            self.analyze = analyze

        def __call__(self, cls_func):
            cls_func.__js__ = True

            if self.builtin is True:
                cls_func.__builtin__ = True

            if self.inline is not None:
                if isinstance(self.inline, str):
                    cls_func.__js_rewrite_call_site__ = lambda **kwargs: self.inline.format(**kwargs)
                else:
                    cls_func.__js_rewrite_call_site__ = self.inline

            if inspect.isclass(cls_func):
                assert self.include is None, "@js(include=True) is only supported for class methods."
                return cls_func

            if self.include is True:
                assert "." in cls_func.__qualname__, "@js(include=True) is only supported for class methods."
                cls_func.__js_include__ = True

            if self.analyze is False:
                cls_func.__no_analyze__ = True

            def client(new_func: type):
                cls_func.__js_replace__ = new_func
                return cls_func
            cls_func.client = client

            def source(new_func: type):
                cls_func.__js_rewrite_func__ = new_func
                return cls_func
            cls_func.source = source

            def inline(new_func: type):
                cls_func.__js_rewrite_call_site__ = new_func
                return cls_func
            cls_func.inline = inline

            return cls_func

    if cls_func_args and is_cls_or_func(cls_func_args[0]):
        return Wrapper(inline, builtin, include, analyze)(cls_func_args[0])

    return Wrapper(inline, builtin, include, analyze)


def nojs(cls_func):
    cls_func.__js__ = False
    return cls_func


class js_str(str):
    def __new__(cls, value, builtin=None):
        obj = super().__new__(cls, value)
        obj.__js__ = True
        obj.__static__ = True
        if builtin is True:
            obj.__builtin__ = builtin
        return obj


def js_object(obj, builtin=None, include=None):
    obj.__js__ = True
    obj.__static__ = True
    if builtin is True:
        obj.__builtin__ = builtin
    if include is True:
        obj.__js_include__ = True
    return obj