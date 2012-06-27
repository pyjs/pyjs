class TextBoxBase:
    def getCursorPos(self):
        JS("""
        try {
            var elem = this['getElement']();
            var tr = elem['document']['selection']['createRange']();
            if (tr['parentElement']()['uniqueID'] != elem['uniqueID'])
                return -1;
            return -tr['move']("character", -65535);
        }
        catch (e) {
            return 0;
        }
        """)

    def getSelectionLength(self):
        JS("""
        try {
            var elem = this['getElement']();
            var tr = elem['document']['selection']['createRange']();
            if (tr['parentElement']()['uniqueID'] != elem['uniqueID'])
                return 0;
            return tr['text']['length'];
        }
        catch (e) {
            return 0;
        }
        """)

    def setSelectionRange(self, pos, length):
        JS("""
        try {
            var elem = this['getElement']();
            var tr = elem['createTextRange']();
            tr['collapse'](true);
            tr['moveStart']('character', @{{pos}});
            tr['moveEnd']('character', @{{length}});
            tr['select']();
        }
        catch (e) {
        }
        """)

