class Canvas(Widget):

    def isEmulation(self):
        JS("""
        return (typeof $wnd['G_vmlCanvasManager'] != "undefined");
        """)

    def init(self):
        JS("""
        var el = this['canvas'];
        if (typeof $wnd['G_vmlCanvasManager'] != "undefined") {
            var parent = el['parent'];

            el = $wnd['G_vmlCanvasManager']['fixElement_'](el);
            el['getContext'] = function () {
                if (this['context_']) {
                    return this['context_'];
                }
                return this['context_'] = new $wnd['CanvasRenderingContext2D'](el);
            };

            el['attachEvent']("onpropertychange", function (e) {
                // we need to watch changes to width and height
                switch (e['propertyName']) {
                    case "width":
                    case "height":
                    // coord size changed?
                    break;
                }
            });

            // if style['height'] is set

            var attrs = el['attributes'];
            if (attrs['width'] && attrs['width']['specified']) {
                // TODO: use runtimeStyle and coordsize
                // el['getContext']()['setWidth_'](attrs['width']['nodeValue']);
                el['style']['width'] = attrs['width']['nodeValue'] + "px";
            }
            if (attrs['height'] && attrs['height']['specified']) {
                // TODO: use runtimeStyle and coordsize
                // el['getContext']()['setHeight_'](attrs['height']['nodeValue']);
                el['style']['height'] = attrs['height']['nodeValue'] + "px";
            }
        }
        var ctx = el['getContext']("2d");

        ctx['_createPattern'] = ctx['createPattern'];
        ctx['createPattern'] = function(img, rep) {
            // Next line breaks things for Chrome
            //if (!(img instanceof Image)) img = img['getElement']();
            return this['_createPattern'](img, rep);
            }

        ctx['_drawImage'] = ctx['drawImage'];
        ctx['drawImage'] = function() {
            var a=arguments;
            // Next line breaks things for Chrome
            //if (!(a[0] instanceof Image)) a[0] = a[0]['getElement']();
            if (a['length']==9) return this['_drawImage'](a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8]);
            else if (a['length']==5) return this['_drawImage'](a[0], a[1], a[2], a[3], a[4]);
            return this['_drawImage'](a[0], a[1], a[2]);
            }

        this['context'] = ctx;
        """)

