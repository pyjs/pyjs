# emulate behaviour of other browsers
def focus(elem):
    JS("""
        try {
            @{{elem}}['focus']();
        } catch (e) {
            // Only trap the exception if the attempt was mostly legit
            if (!@{{elem}} || !@{{elem}}['focus']) {
                // Rethrow the probable NPE or invalid type
                throw e;
            }
        }
    """)
