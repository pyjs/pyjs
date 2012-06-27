class FormPanel(SimplePanel):

    # FormPanelImpl.getTextContents
    def getTextContents(self, iframe):
        JS("""
        try {
            if (!@{{iframe}}['contentWindow']['document'])
                return null;

            return @{{iframe}}['contentWindow']['document']['body']['innerHTML'];
        } catch (e) {
            return null;
        }
        """)

    # FormPanelImpl.hookEvents
    def hookEvents(self, iframe, form, listener):
        JS("""
        if (@{{iframe}}) {
            @{{iframe}}['onload'] = function() {
                if (!@{{iframe}}['__formAction'])
                    return;

                @{{listener}}['onFrameLoad']();
            };
        }

        @{{form}}['onsubmit'] = function() {
            if (@{{iframe}})
                @{{iframe}}['__formAction'] = @{{form}}['action'];
            return @{{listener}}['onFormSubmit']();
        };
        """)

    # FormPanelImpl.submit
    def submitImpl(self, form, iframe):
        JS("""
        if (@{{iframe}})
            @{{iframe}}['__formAction'] = @{{form}}['action'];
        @{{form}}['submit']();
        """)

    # FormPanelImpl.unhookEvents
    def unhookEvents(self, iframe, form):
        JS("""
        if (@{{iframe}})
            @{{iframe}}['onload'] = null;
        @{{form}}['onsubmit'] = null;
        """)

