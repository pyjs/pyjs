"""
* Copyright 2008 Google Inc.
*
* Licensed under the Apache License, Version 2.0 (the "License"); you may not
* use this file except in compliance with the License. You may obtain a copy of
* the License at
*
* http:#www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
* WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
* License for the specific language governing permissions and limitations under
* the License.
"""


from pyjamas.gears.database.Database import GearsDatabase
#from pyjamas.gears.localserver import LocalServer
#from pyjamas.gears.workerpool import WorkerPool
from __pyjamas__ import JS

JS("""
// Copyright 2007 Google Inc. All Rights Reserved.
//
// Sets up google['gears'].*, which is *the only* supported way to access Gears.
//
// Circumvent this file at your own risk!
//
// In the future, Gears may automatically define google['gears'].* without this
// file. Gears may use these objects to transparently fix bugs and compatibility
// issues. Applications that use the code below will continue to work seamlessly
// when that happens.

@{{!init_gears}} = function() {
  // We are already defined. Hooray!
  if ($wnd['google'] && $wnd['google']['gears']) {
    return;
  }

  var factory = null;

  // Firefox
  if (typeof @{{!GearsFactory}} != 'undefined') {
    factory = new @{{!GearsFactory}}();
  } else {
    // IE
    try {
      factory = new ActiveXObject('Gears['Factory']');
    } catch (e) {
      // Safari
      if (navigator['mimeTypes']["application/x-googlegears"]) {
        factory = $doc['createElement']("object");
        factory['style']['display'] = "none";
        factory['width'] = 0;
        factory['height'] = 0;
        factory['type'] = "application/x-googlegears";
        $doc['documentElement']['appendChild'](factory);
      }
    }
  }

  // *Do not* define any objects if Gears is not installed. This mimics the
  // behavior of Gears defining the objects in the future.
  if (!factory) {
    return;
  }

  // Now set up the objects, being careful not to overwrite anything.
  if (!$wnd['google']) {
    $wnd['google'] = {};
  }

  if (!$wnd['google']['gears']) {
    $wnd['google']['gears'] = {factory: factory};
  }
}

""")

"""*
* Returns the singleton instance of the Factory class or <code>None</code>
* if Gears is not installed or accessible.
*
* @return singleton instance of the Factory class or <code>None</code> if
*         Gears is not installed or accessible
"""
def getInstance():
    JS("""
    @{{!init_gears}}();
    return $wnd['google'] && $wnd['google']['gears'] && $wnd['google']['gears']['factory'];
    """)


"""*
* Creates a {@link Database} instance.
*
* @return a {@link Database} instance
"""
def createDatabase():
    return GearsDatabase(create("beta.database"))


"""*
* Creates a {@link LocalServer} instance.
*
* @return a {@link LocalServer} instance
"""
def createLocalServer():
    return LocalServer(create("beta.localserver"))


"""*
* Creates a {@link WorkerPool} instance.
*
* @return a {@link WorkerPool} instance
"""
def createWorkerPool():
    return WorkerPool(create("beta.workerpool"))


"""*
* Returns a description of the build of Gears installed. This string is
* purely informational. Application developers should not rely on the format
* of data returned. The contents and layout may change over time.
*
* @return build description string
"""
def getBuildInfo():
    return getInstance().getBuildInfo()


"""*
* Returns the version of Gears installed, as a string of the form
* Major.Minor.Build.Patch (e.g., '0.10.2.0').
*
* @return string of the form Major.Minor.Build.Patch
"""
def getVersion():
    return getInstance().version


"""*
* Creates an instance of the specified Gears object.
*
* @param <T> Gears object type to return
* @param className name of the object to create
* @return an instance of the specified Gears object
"""
def create(className):
    return getInstance().create(className)


