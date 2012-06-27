# Copyright (C) 2009 Daniel Carvalho <idnael@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __pyjamas__ import JS


# Converts javascript structures from googlemaps javascript library to
# python structures, and vice-versa.
#
# Example:
# jsobj=JS("""[{nome:"danire", year:1814}, {nome:"joano", year:"1901"}]""")
#
# #print jsobj[0].nome  # this is an error!
#
# fields = dictToJs({"lista": 'l', "lista[]": 'd'})
# pyobj=translateGmapsObject(jsobj,"lista",fields)
# for line in pyobj:
#   print line.nome, line.year
#
# jsobj2=translateGmapsObject(pyobj,"lista",fields,True)
# #jsobj2 is exactly the same as jsobj!


def translateGmapsObject(obj, fieldName, fields, pyToJs):
    JS("""
    //console['log']("translateGmapsObject " + fieldNameXXX+"("+pyToJs+")")

    if (! (@{{fieldName}} in @{{fields}}))
    {
      //console['log']("nothing")
      return @{{obj}};
    }
    else{
        @{{action}} = @{{fields}}[@{{fieldName}}]
        //console['log']("action=" + action)

        if (@{{action}} == 'd')
        {
          //console['log']("is dict")
          // this newobj can be used in js and also in python,
          // like this "newobj['field']"
          var newobj = {}
          for (var i in @{{obj}})
             // vai ficar disponivel como uma propriedade, no python!
             newobj[i] = $m['translateGmapsObject'](@{{obj}}[i], i, @{{fields}}, @{{pyToJs}});
          return newobj

        }
        else if (@{{action}} == 'l')
        {
          if (@{{pyToJs}}) {
              var newobj = $m['listToJs'](@{{obj}})
              //console['log']("is list py->js")
              for (var i in newobj){
                 newobj[i]=$m['translateGmapsObject'](
                    newobj[i], @{{fieldName}} + "[]", @{{fields}},@{{pyToJs}} ) ;
              }
              return newobj
          }else{
              //console['log']("is list js->py")
              var newobj = @{{list}}([])
              for (var i in @{{obj}})
                 newobj['append']($m['translateGmapsObject'](
                     @{{obj}}[i], @{{fieldName}} + "[]", @{{fields}},@{{pyToJs}} ));
              return newobj
          }
        }
        else
        {
          //console['log']("is special")
          return @{{action}}(@{{obj}})
        }
    }
    """)


# converts a python dict to js
# It can be used in python functions that have variable number of args
#
# like
# def MapOptions(**params):
#     return dictToJs(params)
#
# if MapOptions is called without arguments, the for loop will
# raise an exception.
# I could use the test "if params" BUT it always gives True...
# So I have to catch the exception.


def dictToJs(dict):
    obj = JS("{}")
    try:
        for key in dict:
            value = dict[key]
            JS("@{{obj}}[@{{key}}] = @{{value}}")
    except:
        pass

    return obj


# Converts a python list to a javascript list
def listToJs(list):
    obj = JS("[]")
    for i in list:
        obj.push(i)
    return obj


# LISTENERS

# This functions add python listener methods to any
# gmaps javascript object


def createListenerMethods(obj):
    obj.addListener = __addListener
    obj.removeListener = __removeListener
    obj.clearListeners = __clearListeners
    obj.clearInstanceListeners = __clearInstanceListeners

    #obj.dumpListeners = __dumpListeners # para debug

    obj.__listeners = {} #__ !


def __dumpListeners():
    self = JS("this")
    print "DUMP"
    for eventName in self.__listeners:
        print "  " + eventName
        for list in self.__listeners[eventName]:
            print "    " + str(list)


def __addListener(eventName, callback):
    self = JS("this")

    thelist = JS("""
       $wnd['google']['maps']['event']['addListener'](this, @{{eventName}}, function(event) {
         @{{callback}}(event);
       })
    """)

    # I have to keep information about the registered listeners for
    # this instance!

    if eventName in self.__listeners:
        self.__listeners[eventName].append(thelist)
    else:
        self.__listeners[eventName] = [thelist]

    return thelist


def __removeListener(list):
    self = JS("this")

    for eventName in self.__listeners:
        if list in self.__listeners[eventName]:
            JS("""$wnd['google']['maps']['event']['removeListener'](@{{list}});""")
            self.__listeners[eventName].remove(list)
            return
    # if we get here, there is nothing to remove,
    # the listener specified doesn't exist or does not belong to this object


def __clearListeners(eventName):
    self = JS("this")

    JS("""$wnd['google']['maps']['event']['clearListeners'](this, @{{eventName}})""")
    if eventName in self.__listeners:
        del self.__listeners[eventName]


def __clearInstanceListeners():
    self = JS("this")

    JS("""$wnd['google']['maps']['event']['clearInstanceListeners'](this)""")
    self.__listeners = {}
