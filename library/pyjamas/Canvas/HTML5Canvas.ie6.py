class HTML5Canvas(GWTCanvas):

    def getCanvasImpl(self):
        return HTML5CanvasImplIE6()

