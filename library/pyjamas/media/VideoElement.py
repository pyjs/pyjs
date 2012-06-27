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

@TagName(VideoElement.TAG)
class VideoElement(MediaElement):
    TAG = "video"

    def create(self):
        return Document.get().createElement(TAG).cast()


    def __init__(self):
        pass


    def getWidth(self):
        JS("""
        return this['width'];
        """)


    def setWidth(self, width):
        JS("""
        this['width'] = width;
        """)


    def getHeight(self):
        JS("""
        return this['height'];
        """)


    def setHeight(self, height):
        JS("""
        this['height'] = height;
        """)


    def getVideoWidth(self):
        JS("""
        return this['videoWidth'];
        """)


    def getVideoHeight(self):
        JS("""
        return this['videoHeight'];
        """)


    def getPoster(self):
        JS("""
        return this['poster'];
        """)


    def setPoster(self, url):
        JS("""
        this['poster'] = url;
        """)
