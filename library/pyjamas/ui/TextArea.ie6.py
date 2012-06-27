class TextArea:
    def getCursorPos(self):
        JS("""
        try {
            var elem = this['getElement']();
            var tr = elem['document']['selection']['createRange']();
            var tr2 = tr['duplicate']();
            tr2['moveToElementText'](elem);
            tr['setEndPoint']('EndToStart', tr2);
            return tr['text']['length'];
        }
        catch (e) {
            return 0;
        }
        """)


