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


def LatLng(lat, lng, nowrap=True):
    if nowrap:
        JS("return new $wnd['google']['maps']['LatLng'](@{{lat}}, @{{lng}}, @{{nowrap}})")
    else:
        JS("return new $wnd['google']['maps']['LatLng'](@{{lat}}, @{{lng}})")


def LatLngBounds(sw, ne):
    if sw and ne:
        JS("return new $wnd['google']['maps']['LatLngBounds'](@{{sw}}, @{{ne}})")
    else:
        JS("return new $wnd['google']['maps']['LatLngBounds']()")


def MVCArray(array):
    JS("return new $wnd['google']['maps']['MVCArray'](@{{array}})")


def Point(x, y):
    JS("return new $wnd['google']['maps']['Point'](@{{x}}, @{{y}})")


def Size(width, height, widthUnit, heightUnit):
    if widthUnit and heightUnit:
        JS("""
        return new $wnd['google']['maps']['Size']
           (@{{width}}, @{{height}}, @{{widthUnit}}, @{{heightUnit}})
        """)
    else:
        JS("return new $wnd['google']['maps']['Size'](@{{width}}, @{{height}})")


def Array():
    JS("return new Array()")
