def can_upload(user):
    return user.enabled


def create_key(name):
    return 'asset/' + name


class Store:
    def __init__(self):
        self.ready = True

    def put(self, key, value):
        return key
