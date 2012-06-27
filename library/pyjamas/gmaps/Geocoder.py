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

from pyjamas.gmaps.Utils import translateGmapsObject, dictToJs #, gmapsPyObjectToJs


GeocoderStatus = JS("$wnd['google']['maps']['GeocoderStatus']")
GeocoderLocationType = JS("$wnd['google']['maps']['GeocoderLocationType']")


geocoderResultsFields = dictToJs(
    {"results": 'l', "types": 'l', "address_components": 'l',
     "results[]": 'd', "address_components[]": 'd', "geometry": 'd',
     "result": 'd'})


# translates a geocoderResults structure from js to python
# and vice-versa

def translateGeocoderResults(jsResults, pyToJs=False):
    return translateGmapsObject(jsResults, "results", \
                                    geocoderResultsFields, pyToJs)


# translates just one element of the geocoderResults
# (because it is used inside directionsResults...)
def translateGeocoderResult(jsResult, pyToJs=False):
    return translateGmapsObject(jsResult, "result", \
                                    geocoderResultsFields, pyToJs)


class Geocoder:

    def __init__(self):
        self.geocoder = JS("new $wnd['google']['maps']['Geocoder']()")

    def geocode(self, request, callback):

        self.geocoder.geocode(request,
            lambda jsResults, status:
            callback(translateGeocoderResults(jsResults), status))


def GeocoderRequest(**params):
    return dictToJs(params)
