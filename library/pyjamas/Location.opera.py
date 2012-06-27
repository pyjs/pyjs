
class Location:
    def getHash(self):
        return JS('unescape(@{{self}}["location"]["hash"])')

    def getSearch(self):
        return JS('unescape(@{{self}}["location"]["search"])')
