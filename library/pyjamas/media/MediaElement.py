"""
* Copyright 2009 Mark Renouf
*
* Licensed under the Apache License, Version 2.0 (the "License"); you may not
* use this file except in compliance with the License. You may obtain a copy of
* the License at
*
* http:#www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS, WITHDIR
* WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
* License for the specific language governing permissions and limitations under
* the License.
"""




class MediaElement(Element):

    def __init__(self):
        pass


    def getNetworkState(self):
        JS("""
        return this['networkState'];
        """)


    def getBuffered(self):
        JS("""
        return this['buffered'];
        """)


    def isSeeking(self):
        JS("""
        return media['seeking'];
        """)


    def setBooleanAttr(self, name, value):
        if value:
            setAttribute(name, "")

        else:
            removeAttribute(name)



