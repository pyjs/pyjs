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

from __pyjamas__ import JS

from pyjamas import DOM

"""*
* Static internal collection of ImageLoader instances.
* ImageLoader is not instantiable externally.
"""
imageLoaders = []


"""*
* Provides a mechanism for deferred execution of a callback
* method once all specified Images are loaded.
"""
class ImageLoader:


    def __init__(self):

        self.images = []
        self.callBack = None
        self.loadedImages = 0
        self.totalImages = 0


    """*
    * Stores the ImageElement reference so that when all the images report
    * an onload, we can return the array of all the ImageElements.
    * @param img
    """
    def addHandle(self, img):
        self.totalImages += 1
        self.images.append(img)


    """*
    * Invokes the onImagesLoaded method in the CallBack if all the
    * images are loaded AND we have a CallBack specified.
    *
    * Called from the JSNI onload event handler.
    """
    def dispatchIfComplete(self):
        if self.callBack is not None  and  self.isAllLoaded():
            self.callBack.onImagesLoaded(self.images)
            # remove the image loader
            imageLoaders.remove(self)



    """*
    * Sets the callback object for the ImageLoader.
    * Once this is set, we may invoke the callback once all images that
    * need to be loaded report in from their onload event handlers.
    *
    * @param cb
    """
    def finalize(self, cb):
        self.callBack = cb


    def incrementLoadedImages(self):
        self.loadedImages += 1


    def isAllLoaded(self):
        return (self.loadedImages == self.totalImages)


    def _onload(self, form, event, something):
        if not self.__formAction:
            return
        self._listener.onFrameLoad()

    def _onsubmit(self, form, event, something):
        print form, event, something
        try:
            event = get_main_frame().gobject_wrap(event) # webkit HACK!
            form = get_main_frame().gobject_wrap(form) # webkit HACK!
        except:
            pass

        if self.iframe:
            self.__formAction = form.action
        return self._listener.onFormSubmit()

    # FormPanelImpl.hookEvents
    def hookEvents(self, iframe, form, listener):
        # TODO: might have to fix this, use DOM.set_listener()
        self._listener = listener
        if iframe:
            wf = mf = get_main_frame()
            self._onload_listener = mf.addEventListener(iframe, "load",
                                                        self._onload)

        self._onsubmit_listener = mf.addEventListener(form, "onsubmit",
                                                    self._onsubmit)

    """*
    * Returns a handle to an img object. Ties back to the ImageLoader instance
    """
    def prepareImage(self, url):
        img = Image()
        JS("""
        // if( callback specified )
        // do nothing

        var __this = this;

        @{{img}}['onload'] = function() {
            if(!@{{img}}['__isLoaded']) {

                // __isLoaded should be set for the first time here.
                // if for some reason img fires a second onload event
                // we do not want to execute the following again (hence the guard)
                @{{img}}['__isLoaded'] = true;
                __this['incrementLoadedImages']();
                @{{img}}['onload'] = null;

                // we call this function each time onload fires
                // It will see if we are ready to invoke the callback
                __this['dispatchIfComplete']();
            } else {
                // we invoke the callback since we are already loaded
                __this['dispatchIfComplete']();
            }
        }

        return @{{img}};
        """)



def init():
    global imageLoadArray
    imageLoadArray = {}
