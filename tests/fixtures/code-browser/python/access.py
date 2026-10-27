def permit(name):
    return len(name) > 0

class Store:
    def __init__(self, prefix):
        self.prefix = prefix
    def put(self, key):
        return self.prefix + key
