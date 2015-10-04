# Check http://json-rpc.org/wiki for the sepcification of JSON-RPC
# Currently:
#     http://groups.google.com/group/json-rpc/web/json-rpc-1-1-wd
#     http://groups.google.com/group/json-rpc/web/json-rpc-1-2-proposal


""" JSONService is a module providing JSON RPC Client side proxying.
"""

import sys
from HTTPRequest import HTTPRequest

try:
    # included in python 2.6...
    from json import dumps, loads
except ImportError:
    # recommended library (python 2.5)
    from simplejson import dumps, loads

class JSONServiceError(Exception):
    pass

__requestID = 0
__requestIDPrefix = 'ID'
__lastRequestID = None
def nextRequestID():
    """
    Return Next Request identifier.
    MUST be a JSON scalar (String, Number, True, False), but SHOULD normally
    not be Null, and Numbers SHOULD NOT contain fractional parts.
    """
    global __requestID, __requestIDPrefix, __lastRequestID
    __requestID += 1
    id = "%s%s" % (__requestIDPrefix, __requestID)
    if __lastRequestID == id:
        # javascript integer resolution problem
        __requestIDPrefix += '_'
        __requestID = 0
        id = "%s%s" % (__requestIDPrefix, __requestID)
    __lastRequestID = id
    return id

# no stream support
class JSONService(object):
    content_type = 'application/json-rpc'
    accept = 'application/json-rpc'

    def __init__(self, url, handler=None, headers=None, return_object=False):
        """
        Create a JSON remote service object. The url is the URL that will
        receive POST data with the JSON request. See the JSON-RPC spec for
        more information.

        The handler object should implement::

            onRemoteResponse(value, requestInfo)

        to accept the return value of the remote method, and::

            onRemoteError(code, error_dict, requestInfo)
                 code = http-code or 0
                 error_dict is an jsonrpc 2.0 error dict:
                     {
                       'code': jsonrpc-error-code (integer) ,
                       'message': jsonrpc-error-message (string) ,
                       'data' : extra-error-data
                     }

        to handle errors.
        """
        self.url = url
        self.handler = handler
        self.headers = headers if headers is not None else {}
        if not self.headers.get("Accept"):
            self.headers["Accept"] = self.accept
        self.return_object = return_object

    def callMethod(self, method, params, handler = None):
        if handler is None:
            handler = self.handler

        if handler is None:
            return self.sendNotify(method, params)
        else:
            return self.sendRequest(method, params, handler)

    def onCompletion(self, response):
        pass

    def sendNotify(self, method, params):
        # jsonrpc: A String specifying the version of the JSON-RPC protocol.
        #          MUST be exactly "2.0"
        #          If jsonrpc is missing, the server MAY handle the Request as
        #          JSON-RPC V1.0-Request.
        # version: String specifying the version of the JSON-RPC protocol.
        #          MUST be exactly "1.1"
        # NOTE: We send both, to indicate that we can handle both.
        #
        # id:      If omitted, the Request is a Notification
        #          NOTE: JSON-RPC 1.0 uses an id of Null for Notifications.
        # method:  A String containing the name of the procedure to be invoked.
        # params:  An Array or Object, that holds the actual parameter values
        #          for the invocation of the procedure. Can be omitted if
        #          empty.
        #          NOTE: JSON-RPC 1.0 only a non-empty Array is used
        # From the spec of 1.1:
        #     The Content-Type MUST be specified and # SHOULD read
        #     application/json.
        #     The Accept MUST be specified and SHOULD read application/json.
        #
        # From http://groups.google.com/group/json-rpc/web/json-rpc-over-http
        #     Content-Type SHOULD be 'application/json-rpc' but MAY be
        #     'application/json' or 'application/jsonrequest'
        #     The Accept MUST be specified and SHOULD read 'application/json-rpc'
        #     but MAY be 'application/json' or 'application/jsonrequest'.
        #
        msg = {"jsonrpc": "2.0",
               "version": "1.1",
               "method": method,
               "params": params
              }
        msg_data = dumps(msg)
        request_object = HTTPRequest().asyncPost(self.url, msg_data, self,
                                       False, self.content_type,
                                       self.headers)
        if self.return_object:
            return id, request_object
        if not request_object:
            return -1
        return 1

    def sendRequest(self, method, params, handler):
        id = nextRequestID()
        msg = {"jsonrpc": "2.0",
               "id": id,
               "method": method,
               "params": params
              }
        msg_data = dumps(msg)

        request_info = JSONRequestInfo(id, method, handler)
        request_object = HTTPRequest().asyncPost(self.url, msg_data,
                                       JSONResponseTextHandler(request_info),
                                       False, self.content_type,
                                       self.headers)
        if self.return_object:
            return id, request_object
        if not request_object:
            return -1
        return id


class JSONRequestInfo(object):
    def __init__(self, id, method, handler):
        self.id = id
        self.method = method
        self.handler = handler

def create_object(items):
    """ creates an object by looking for __jsonclass__ hint,
        loading the class from that and then constructing an
        object from the rest of the dictionary as kwargs
    """
    clsname = items.pop('__jsonclass__', None)
    if not clsname:
        return items
    clsname = clsname[0]
    dot = clsname.rfind('.')
    modulename = clsname[:dot]
    clsname = clsname[dot+1:]
    vars = {}
    exec "from %s import %s as kls" % (modulename, clsname) in vars
    kls = vars['kls']
    vars = {}
    for (k, v) in items.items():
        vars[str(k)] = v
    return kls(**vars)

def _decode_response(json_str):
    return loads(json_str, object_hook=create_object)

class JSONResponseTextHandler(object):
    def __init__(self, request):
        self.request = request

    def onCompletion(self, json_str):
        try:
            response = _decode_response(json_str)
        except: # just catch... everything.
            # err.... help?!!
            error = dict(
                         code=-32700,
                         message="Parse error while decoding response",
                         data=None,
                        )
            self.request.handler.onRemoteError(0, error, self.request)
            return

        if not response:
            error = dict(
                         code=-32603,
                         message="Empty Response",
                         data=None,
                        )
            self.request.handler.onRemoteError(0, error, self.request)
        elif response.get("error"):
            error = response["error"]
            jsonrpc = response.get("jsonrpc")
            code = error.get("code", 0)
            message = error.get("message", error)
            data = error.get("data")
            if not jsonrpc:
                jsonrpc = response.get("version", "1.0")
                if jsonrpc == "1.0":
                    message = error
                else:
                    data = error.get("error")
            error = dict(
                         code=code,
                         message=message,
                         data=data,
                        )
            self.request.handler.onRemoteError(0, error, self.request)
        elif "result" in response:
            self.request.handler.onRemoteResponse(response["result"],
                                                  self.request)
        else:
            error = dict(
                         code=-32603,
                         message="No result or error in response",
                         data=response,
                        )
            self.request.handler.onRemoteError(0, error, self.request)

    def onError(self, error_str, error_code):
        error = dict(
                     code=error_code,
                     message=error_str,
                     data=None,
                    )
        self.request.handler.onRemoteError(error_code, error, self.request)

class ServiceProxy(JSONService):
    def __init__(self, serviceURL, serviceName=None, headers=None, return_object=False):
        JSONService.__init__(self, serviceURL, headers=headers, return_object=return_object)
        self.__serviceName = serviceName

    def __call__(self, *params, **kwargs):
        if isinstance(params, tuple):
            params = list(params)
        if params and hasattr(params[0], "onRemoteResponse"):
            handler = params.pop(0)
        elif params and hasattr(params[-1], "onRemoteResponse"):
            handler = params.pop()
        else:
            handler = None
        if kwargs:
            if params:
                if not isinstance(params, dict):
                    raise JSONServiceError("Cannot mix positional and keyword arguments")
                params.update(kwargs)
            else:
                params = kwargs
        if handler is not None:
            return JSONService.sendRequest(self, self.__serviceName,
                                           params, handler)
        else:
            return JSONService.sendNotify(self, self.__serviceName, params)

# reserved names: callMethod, onCompletion
class JSONProxy(JSONService):
    def __init__(self, url, methods=None, headers=None, return_object=False):
        self._serviceURL = url
        self.methods = methods
        self.headers = {} if headers is None else headers
        self.return_object = return_object
        # Init with JSONService, for the use of callMethod
        JSONService.__init__(self, url, headers=self.headers, return_object=self.return_object)
        self._registerMethods(methods)

    def _registerMethods(self, methods):
        if methods:
            for method in methods:
                setattr(self,
                        method,
                        getattr(ServiceProxy(self._serviceURL, method,
                                             headers=self.headers,
                                             return_object=self.return_object),
                                '__call__')
                       )

    # It would be nice to use __getattr__ (instead of _registerMethods)
    # However, that doesn't work with pyjs and the use of _registerMethods
    # saves some repeated instance creations (now only once per method and
    # not once per call)
    #def __getattr__(self, name):
    #    if not name in self.methods:
    #        raise AttributeError("no such method %s" % name)
    #    return ServiceProxy(self._serviceURL, name, headers=self.headers)

