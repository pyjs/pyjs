"""
* Copyright 2009 Mark Renouf
*
* Licensed under the Apache License, Version 2.0 (the "License") you may not
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


from pyjamas.ui import Event
from pyjamas import DOM
from pyjamas.ui.Widget import Widget

def mediaEventGetTypeInt(eventType):
    JS("""
    window['console']['log']('mediaEventGetTypeInt: ' + eventType)
    switch (eventType) {
        case "abort":             return 0x00001;
        case "canplay":           return 0x00002;
        case "canplaythrough":    return 0x00004;
        case "durationchange":    return 0x00008;
        case "emptied":           return 0x00010;
        case "ended":             return 0x00020;
        case "error":             return 0x00040;
        case "loadstart":         return 0x00080;
        case "loadeddata":        return 0x00100;
        case "loadedmetadata":    return 0x00200;
        case "pause":             return 0x00400;
        case "play":              return 0x00800;
        case "playing":           return 0x01000;
        case "progress":          return 0x02000;
        case "ratechange":        return 0x04000;
        case "seeked":            return 0x08000;
        case "seeking":           return 0x10000;
        case "stalled":           return 0x20000;
        case "suspend":           return 0x40000;
        case "timeupdate":        return 0x80000;
        case "volumechange":      return 0x100000;
        case "waiting":           return 0x200000;
        default:
        window['console']['debug']("Unknown media eventType: " + eventType)
        return 0;
    }
    """)

class Media(Widget):
    """
    HasAbortHandlers,
    HasCanPlayHandlers, HasCanPlayThroughHandlers, HasDurationChangeHandlers,
    HasEmptiedHandlers,
    HasEndedHandlers, HasErrorHandlers, HasLoadStartHandlers,
    HasLoadedDataHandlers, HasLoadedMetadataHandlers, HasPauseHandlers,
    HasPlayHandlers, HasPlayingHandlers, HasProgressHandlers,
    HasRateChangeHandlers, HasSeekedHandlers, HasSeekingHandlers,
    HasStalledHandlers, HasSuspendHandlers, HasTimeUpdateHandlers,
    HasVolumeChangeHandlers, HasWaitingHandlers, HasAllMouseHandlers,
    HasClickHandlers"""

    def __init__(self, **kwargs):
        self.mediaEventsToSink = 0
        self.mediaEventsInitialized = False

        Widget.__init__(self, **kwargs)

    def setSrc(self, src):
        DOM.setAttribute(self.getElement(), 'src', src)

    def addSrc(self, src):
        s = DOM.createElement("source")
        DOM.setAttribute(s, 'src', src)
        DOM.appendChild(self.getElement(), s)

    def getSrc(self):
        return DOM.getAttribute(self.getElement(), 'src')

    def getError(self):
        " return (this.error == null) ? 0 : this.error; "
        return self.getElement().error or 0

    def getCurrentSrc(self):
        return self.getElement().currentSrc

    def getCurrentTime(self):
        return self.getElement().currentTime

    def setCurrentTime(self, time):
        self.getElement().currentTime = time

    def getStartTime(self):
        return self.getElement().startTime

    def getDuration(self):
        return self.getElement().duration

    def isPaused(self):
        return self.getElement().paused

    def getDefaultPlaybackRate(self):
        return self.getElement().defaultPlaybackRate

    def setDefaultPlaybackRate(self, rate):
        self.getElement().defaultPlaybackRate = rate

    def getPlaybackRate(self):
        return self.getElement().playbackRate

    def setPlaybackRate(self, rate):
        self.getElement().playbackRate = rate

    def getPlayed(self):
        return self.getElement().played

    def getSeekable(self):
        return self.getElement().seekable

    def hasEnded(self):
        return self.getElement().ended

    def isLoop(self):
        return bool(self.getElement().loop)

    def getVolume(self):
        return self.getElement().volume

    def setVolume(self, volume):
        self.getElement().volume = volume

    def getReadyState(self):
        return self.getElement().readyState


    """*
    * If set, this informs the browser that the media element is likely to be
    * played and that it should begin buffering the content immediately.
    * <p>
    * This setting has no effect if {@linkplain #setAutoplay(boolean) autoplay}
    * is set. Per the current HTML5 spec, the browser is not required to support
    * this feature.
    *
    * @param autobuffer Whether to begin buffering content immediately
    """
    def setAutobuffer(self, autobuffer):
        self.getElement().autobuffer = autobuffer


    """*
    * Whether to automatically begin playback of the media resource as soon as
    * it's possible to do so without stopping.
    *
    * @param autoplay Whether the content should begin playing immediately
    """
    def setAutoplay(self, autoplay):
        self.getElement().autoplay = autoplay


    """*
    * Whether the media element is to seek back to the start of the media
    * resource upon reaching the end.
    *
    * @param loop whether the media element should loop
    """
    def setLoop(self, loop):
        self.getElement().loop = loop


    """*
    * Whether the browser should expose a user interface to the user. This user
    * interface should include features to begin playback, pause playback, seek
    * to an arbitrary position in the content (if the content supports arbitrary
    * seeking), change the volume, and show the media content in manners more
    * suitable to the user (e.g. full-screen video or in an independent resizable
    * window). Other controls may also be made available.
    *
    * @param controls Whether the browser should show playback controls
    """
    def setControls(self, controls):
        DOM.setBooleanAttribute(self.getElement(), "controls", controls)

    def hasControls(self):
        DOM.getBooleanAttribute(self.getElement(), "controls")

    def isMuted(self):
        return self.getElement().muted

    def play(self):
        self.getElement().play()

    def load(self):
        self.getElement().load()

    def pause(self):
        self.getElement().pause()

    def canPlayType(self, etype):
        self.getElement().canPlayType(etype)

    def setMute(self, muted):
        self.getElement().setMute(muted)


    """*
    * Adds a handler to be called when the user agent stops fetching the media data before it is
    * completely downloaded, but not due to an error.
    """

    def addAbortHandler(self, handler):
        return self.addMediaEventHandler(handler, AbortEvent.getType())


    """*
    * Adds a handler to be called when the user agent can resume playback of the media data, but
    * estimates that if playback were to be started now, the media resource could
    * not be rendered at the current playback rate up to its end without having
    * to stop for further buffering of content.
    *
    * @param handler the {@link CanPlayHandler} to be called
    """

    def addCanPlayHandler(self, handler):
        return self.addMediaEventHandler(handler, CanPlayEvent.getType())


    """*
    * Adds a handler to be called when the user agent estimates that if playback were to be started
    * now, the media resource could be rendered at the current playback rate all
    * the way to its end without having to stop for further buffering.
    *
    * @param handler the {@link CanPlayThroughHandler} to be called
    """

    def addCanPlayThroughHandler(self, handler):
        return self.addMediaEventHandler(handler, CanPlayThroughEvent.getType())



    def addDurationChangeHandle(self, handler):
        return self.addMediaEventHandler(handler, DurationChangeEvent.getType())


    """*
    * Adds a handler to be called when the duration attribute has just been updated.
    *
    * @param handler the {@link DurationChangeHandler} to be called
    """

    def addEmptiedHandler(self, handler):
        return self.addMediaEventHandler(handler, EmptiedEvent.getType())


    """*
    * Adds a handler to be called when a media element whose networkState was previously not in the
    * NETWORK_EMPTY state has just switched to that state (either because of a
    * fatal error during load that's about to be reported, or because the load()
    * method was invoked while the resource selection algorithm was already
    * running, in which case it is fired synchronously during the load() method
    * call).
    *
    * @param handler the {@link EmptiedHandler} to be called
    """

    def addEndedHandler(self, handler):
        return self.addMediaEventHandler(handler, EndedEvent.getType())


    """*
    * Adds a handler to be called when playback has stopped because the end of the media resource was
    * reached.
    *
    * @param handler the {@link EndedHandler} to be called
    """

    def addErrorHandler(self, handler):
        return self.addMediaEventHandler(handler, ErrorEvent.getType())


    """*
    * Adds a handler to be called when the user agent begins looking for media data, as part of the
    * resource selection algorithm.
    *
    * @param handler the {@link LoadStartHandler} to be called
    """

    def addLoadStartHandler(self, handler):
        return self.addMediaEventHandler(handler, LoadStartEvent.getType())


    """*
    * Adds a handler to be called when the user agent can render the media data at the current
    * playback position for the first time.
    *
    * @param handler the {@link LoadedDataHandler} to be called
    """

    def addLoadedDataHandler(self, handler):
        return self.addMediaEventHandler(handler, LoadedDataEvent.getType())


    """*
    * Adds a handler to be called when the user agent has just determined the duration and dimensions
    * of the media resource.
    *
    * @param handler the {@link LoadedMetadataHandler} to be called
    """

    def addLoadedMetadataHandler(self, handler):
        return self.addMediaEventHandler(handler, LoadedMetadataEvent.getType())


    """*
    * Adds a handler to be called when playback has been paused. Fired after the pause method has
    * returned.
    *
    * @param handler the {@link PauseHandler} to be called
    """

    def addPauseHandler(self, handler):
        return self.addMediaEventHandler(handler, PauseEvent.getType())


    """*
    * Adds a handler to be called when playback has begun. Fired after the play() method has returned.
    *
    * @param handler the {@link PlayHandler} to be called
    """

    def addPlayHandler(self, handler):
        return self.addMediaEventHandler(handler, PlayEvent.getType())


    """*
    * Adds a handler to be called when playback has started.
    *
    * @param handler the {@link PlayingHandler} to be called
    """

    def addPlayingHandler(self, handler):
        return self.addMediaEventHandler(handler, PlayingEvent.getType())


    """*
    * Adds a handler to be called when the user agent is fetching media data.
    *
    * @param handler the {@link ProgressHandler} to be called
    """

    def addProgressHandler(self, handler):
        return self.addMediaEventHandler(handler, ProgressEvent.getType())


    """*
    * Adds a handler to be called when either the defaultPlaybackRate or the playbackRate attribute
    * has just been updated.
    *
    * @param handler the {@link RateChangeHandler} to be called
    """

    def addRateChangeHandler(self, handler):
        return self.addMediaEventHandler(handler, RateChangeEvent.getType())


    """*
    * Adds a handler to be called when a seek operation has completed.
    *
    * @param handler the {@link SeekedHandler} to be called
    """

    def addSeekedHandler(self, handler):
        return self.addMediaEventHandler(handler, SeekedEvent.getType())


    """*
    * Adds a handler to be called when the user agent is seeking to a time position in the stream.
    *
    * @param handler the {@link SeekingHandler} to be called
    """

    def addSeekingHandler(self, handler):
        return self.addMediaEventHandler(handler, SeekingEvent.getType())


    """*
    * Adds a handler to be called when the user agent is trying to fetch media data, but data is
    * unexpectedly not forthcoming.
    *
    * @param handler the {@link StalledHandler} to be called
    """

    def addStalledHandler(self, handler):
        return self.addMediaEventHandler(handler, StalledEvent.getType())


    """*
    * Adds a handler to be called when the user agent is intentionally not currently fetching media
    * data, but does not have the entire media resource downloaded.
    *
    * @param handler the {@link SuspendHandler} to be called
    """

    def addSuspendHandler(self, handler):
        return self.addMediaEventHandler(handler, SuspendEvent.getType())


    """*
    * Adds a handler to be called when the current playback position changed as part of normal
    * playback or in an especially interesting way, for example discontinuously.
    *
    * @param handler the {@link TimeUpdateHandler} to be called
    """

    def addTimeUpdateHandler(self, handler):
        return self.addMediaEventHandler(handler, TimeUpdateEvent.getType())


    """*
    * Adds a handler to be called when either the volume attribute or the muted attribute has changed.
    * Fired after the relevant attribute's setter has returned.
    *
    * @param handler the {@link VolumeChangeHandler} to be called
    """

    def addVolumeChangeHandler(self, handler):
        return self.addMediaEventHandler(handler, VolumeChangeEvent.getType())


    """*
    * Adds a handler to be called when playback has stopped because the next frame is not available,
    * but the user agent expects that frame to become available in due course.
    *
    * @param handler the {@link WaitingHandler} to be called
    """

    def addWaitingHandler(self, handler):
        return self.addMediaEventHandler(handler, WaitingEvent.getType())


    def addMediaEventHandler(self, handler, etype):
        assert handler is not None, "handler must not be None"
        assert etype is not None, "type must not be None"
        self.maybeInitMediaEvents()
        self.sinkMediaEvents(mediaEventGetTypeInt(etype.getName()))
        return addHandler(handler, etype)



    def sinkMediaEvents(self, eventBitsToAdd):
        if self.isOrWasAttached():
            self.nativeSinkMediaEvents(self.getElement(), eventBitsToAdd)
        else:
            self.mediaEventsToSink |= eventBitsToAdd



    """*
    * doAttachChildren is called immediately after sinkEvents is called in
    * Widget. This opportunity is taken to lazily attach event handlers to the
    * element.
    """
    def doAttachChildren(self):
        bitsToAdd = self.mediaEventsToSink
        self.mediaEventsToSink = -1
        if bitsToAdd > 0:
            self.nativeSinkMediaEvents(self.getElement(), bitsToAdd)


    def nativeSinkMediaEvents(self, elem, bits):
#        chMask = (elem.__mediaEventBits or 0) ^ bits
#        elem.__mediaEventBits = bits;
#        if not chMask:
#             return
#
#        if (chMask & 0x00001) and (bits & 0x00001):
#            elem.addEventListener('abort', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('abort', mediaDispatchEvent, false)
#        if (chMask & 0x00002) and (bits & 0x00002):
#            elem.addEventListener('canplay', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('canplay', mediaDispatchEvent, false)
#        if (chMask & 0x00004) and (bits & 0x00004):
#            elem.addEventListener('canplaythrough', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('canplaythrough', mediaDispatchEvent, false)
#        if (chMask & 0x00008) and (bits & 0x00008):
#            elem.addEventListener('durationchange', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('durationchange', mediaDispatchEvent, false)
#        if (chMask & 0x00010) and (bits & 0x00010):
#            elem.addEventListener('emptied', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('emptied', mediaDispatchEvent, false)
#        if (chMask & 0x00020) and (bits & 0x00020):
#            elem.addEventListener('ended', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('ended', mediaDispatchEvent, false)
#        if (chMask & 0x00040) and (bits & 0x00040):
#            elem.addEventListener('error', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('error', mediaDispatchEvent, false)
#        if (chMask & 0x00080) and (bits & 0x00080):
#            elem.addEventListener('loadstart', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('loadstart', mediaDispatchEvent, false)
#        if (chMask & 0x00100) and (bits & 0x00100):
#            elem.addEventListener('loadeddata', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('loadeddata', mediaDispatchEvent, false)
#        if (chMask & 0x00200) and (bits & 0x00200):
#            elem.addEventListener('loadedmetadata', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('loadedmetadata', mediaDispatchEvent, false)
#        if (chMask & 0x00400) and (bits & 0x00400):
#            elem.addEventListener('pause', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('pause', mediaDispatchEvent, false)
#        if (chMask & 0x00800) and (bits & 0x00800):
#            elem.addEventListener('play', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('play', mediaDispatchEvent, false)
#        if (chMask & 0x01000) and (bits & 0x01000):
#            elem.addEventListener('playing', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('playing', mediaDispatchEvent, false)
#        if (chMask & 0x02000) and (bits & 0x02000):
#            elem.addEventListener('progress', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('progress', mediaDispatchEvent, false)
#        if (chMask & 0x04000) and (bits & 0x04000):
#            elem.addEventListener('ratechange', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('ratechange', mediaDispatchEvent, false)
#        if (chMask & 0x08000) and (bits & 0x08000):
#            elem.addEventListener('seeked', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('seeked', mediaDispatchEvent, false)
#        if (chMask & 0x10000) and (bits & 0x10000):
#            elem.addEventListener('seeking', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('seeking', mediaDispatchEvent, false)
#        if (chMask & 0x20000) and (bits & 0x20000):
#            elem.addEventListener('stalled', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('stalled', mediaDispatchEvent, false)
#        if (chMask & 0x40000) and (bits & 0x40000):
#            elem.addEventListener('suspend', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('suspend', mediaDispatchEvent, false)
#        if (chMask & 0x80000) and (bits & 0x80000):
#            elem.addEventListener('timeupdate', mediaDispatchEvent, false)
#        else:
#            elem.removeEventListener('timeupdate', mediaDispatchEvent, false)
#        if (chMask & 0x100000) and (bits & 0x100000):
#            elem.addEventListener('volumechange', mediaDispatchEvent, false)
#        else:
#             elem.removeEventListener('volumechange', mediaDispatchEvent, false)
#        if (chMask & 0x200000) and (bits & 0x200000):
#            elem.addEventListener('waiting', mediaDispatchEvent, false)
#        else:
#             elem.removeEventListener('waiting', mediaDispatchEvent, false)
        return

    def addMouseDownHandler(self, handler):
        return addDomHandler(handler, MouseDownEvent.getType())



    def addMouseUpHandler(self, handler):
        return addDomHandler(handler, MouseUpEvent.getType())



    def addMouseOutHandler(self, handler):
        return addDomHandler(handler, MouseOutEvent.getType())



    def addMouseOverHandler(self, handler):
        return addDomHandler(handler, MouseOverEvent.getType())



    def addMouseMoveHandler(self, handler):
        return addDomHandler(handler, MouseMoveEvent.getType())



    def addMouseWheelHandler(self, handler):
        return addDomHandler(handler, MouseWheelEvent.getType())



    def addClickHandler(self, handler):
        return addDomHandler(handler, ClickEvent.getType())


    def maybeInitMediaEvents(self):
        if not mediaEventsInitialized:
            initMediaEvents()
            mediaEventsInitialized = True



    """*
    * Warning: W3C/Standards version
    """
    def initMediaEvents(self):
        JS("""
        mediaDispatchEvent = function(evt) {
            var curElem = evt['target'];
            var listener = curElem['__listener'];
            if (listener) {
                @{{self['dispatchMediaEvent']}}(evt, listener)
            }
        }
        """)


    """*
    * Dispatches an event to the listener. This bypasses the main GWT event
    * handling system because it's not possible to access from external packages.
    * <p>
    * Due to this event catpure and event preview will not work properly for
    * media-specific events (existing GWT handled events are not affected). Also,
    * since the sinkEvents system is not extensible media events can only be
    * listened for directly on the Media object generating them ie. they will not
    * be received or handled by any containing elements because these objects
    * won't know how to set the correct event listeners.
    *
    * @param evt
    * @param listener
    """
    def dispatchMediaEvent(self, evt, listener):
        # Pass the event to the listener.
        listener.onBrowserEvent(evt)



