
class Location:
    def getHash(self):
        return JS('unescape(@{{self}}["location"]["hash"])')

    def getSearch(self):
        JS("""if (@{{self}}['location']['search'] === null)
                return String("?");
            return String(@{{self}}['location']['search']);
           """)
