class FormPanel:
    def getTextContents(self, iframe):
        JS("""
        try {
            if (!@{{iframe}}['contentWindow']['document'])
                return null;

            return @{{iframe}}['contentWindow']['document']['body']['innerText'];
        } catch (e) {
            return null;
        }
        """)

    def hookEvents(self, iframe, form, listener):
        JS("""
        if (@{{iframe}}) {
            @{{iframe}}['onreadystatechange'] = function() {
                if (!@{{iframe}}['__formAction'])
                    return;

                if (@{{iframe}}['readyState'] == 'complete') {
                    @{{listener}}['onFrameLoad']();
                }
            };
        }

        @{{form}}['onsubmit'] = function() {
            if (@{{iframe}})
                @{{iframe}}['__formAction'] = @{{form}}['action'];
            return @{{listener}}['onFormSubmit']();
        };
        """)

    def unhookEvents(self, iframe, form):
        JS("""
        if (@{{iframe}})
            @{{iframe}}['onreadystatechange'] = null;
        @{{form}}['onsubmit'] = null;
        """)

