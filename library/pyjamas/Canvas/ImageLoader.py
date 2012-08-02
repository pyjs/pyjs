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

from pyjamas import DOM
from pyjamas.ui.Image import Image
from pyjamas.ui import Event

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

        #some listeners want to call onImageLoad, instead of onLoad
        #fixes issue 746
        self.onImageLoad = self.onLoad


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


    """*
    * Returns a handle to an img object. Ties back to the ImageLoader instance
    """
    def prepareImage(self, url):
        img = Image()
        img.__isLoaded = False
        img.addLoadListener(self)
        # normally, event listeners are only set up when the widget
        # is attached to part of the DOM (see Widget.onAttach).  but,
        # in this case, we want a load even _even though_ the Image
        # widget is not yet attached (and quite likely won't be).
        DOM.setEventListener(img.getElement(), img)
        DOM.sinkEvents(img.getElement(), Event.ONLOAD)
        return img

    def onLoad(self, img):

        if not img.__isLoaded:

            # __isLoaded should be set for the first time here.
            # if for some reason img fires a second onload event
            # we do not want to execute the following again (hence the guard)
            img.__isLoaded = True;
            self.incrementLoadedImages();
            img.removeLoadListener(self)

        # we call this function each time onload fires
        # It will see if we are ready to invoke the callback
        self.dispatchIfComplete();

        return img;



"""*
* Takes in an array of url Strings corresponding to the images needed to
* be loaded. The onImagesLoaded() method in the specified CallBack
* object is invoked with an array of ImageElements corresponding to
* the original input array of url Strings once all the images report
* an onload event.
*
* @param urls Array of urls for the images that need to be loaded
* @param cb CallBack object
"""
def loadImages(urls, cb):
    il = ImageLoader()
    for i in range(len(urls)):
        il.addHandle(il.prepareImage(urls[i]))

    il.finalize(cb)
    imageLoaders.append(il)
    # Go ahead and fetch the images now
    for i in range(len(urls)):
        il.images[i].setUrl(urls[i])


