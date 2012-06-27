"""
* Copyright 2009 Mark Renouf
*
* Licimport com.google.gwt.core.client.JavaScriptObject; cense"); you may not
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




class TimeRanges(object):

    def length(self):
        JS("""
        return this['length'];
        """)


    def start(self, index):
        JS("""
        return this['start'](index);
        """)


    def end(self, index):
        JS("""
        return this['end'](index);
        """)


