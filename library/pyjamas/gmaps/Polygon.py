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
from pyjamas.gmaps.Utils import dictToJs, createListenerMethods, listToJs


def Polygon(options):
    JS("return new $wnd['google']['maps']['Polygon'](@{{options}})")

def PolygonOptions(adict):
    """Accepts a dictionary of options. If necessary, transforms "paths" from
    python list or encoded string to javascript array."""
    if adict.has_key("paths"):
        try:
            if isinstance(adict["paths"], (list,tuple)):
                adict["paths"] = listToJs(adict["paths"])
            elif isinstance(adict["paths"], basestring): #Gmaps
                adict["paths"] = decodePoly(adict["paths"])
        except: #isinstance throws exception for raw javascript objects.
            pass #That means it's already good.
    return dictToJs(adict)

def decodePoly(poly):
    """Quickly decodes a gmaps api v2 encoded polyline... deprecated by google but still
    a good over-the-wire compression format"""
    JS("""
    var i=-1,j=-1,k,l,q=@{{poly}}['match'](/[\_-\~]*[\?-\^]/g),w=0,x=0,y=0,z=1e-5;

    @{{poly}}=[];

    if (q) for (;;)
    {
        if (!q[++i]) break;
        for (k=q[i]['length'],l=63,w=0;k--;l=95) w=(w<<5)+q[i]['charCodeAt'](k)-l;
        y+=(w<<31>>31)^(w>>1);
        if (!q[++i]) break;
        for (k=q[i]['length'],l=63,w=0;k--;l=95) w=(w<<5)+q[i]['charCodeAt'](k)-l;
        x+=(w<<31>>31)^(w>>1);
        @{{poly}}[++j]=new $wnd['google']['maps']['LatLng'](y*z,x*z);
    }
    return @{{poly}}
""")
