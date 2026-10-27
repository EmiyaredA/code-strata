from .barrel import allowed as can_upload, Store
shared = 0
async def upload_asset(name, handler):
    中文 = "😀"; key = name + 中文
    if not can_upload(name):
        raise ValueError('denied')
    store = Store('root/')
    def nested():
        key = 'inner'
        return key
    def capture():
        nonlocal key
        key = name
        return key
    try:
        for i in range(2):
            handler(key)
        store.put(key)
        nested()
        capture()
        return key
    finally:
        can_upload('cleanup')
def recursive(n):
    return recursive(n - 1) if n else 0
def generate():
    yield 1
def update():
    global shared
    shared = 2
    return shared
values = [key for key in range(3)]
def scopes(input):
    key = 1
    key = 2
    left, right = input
    def closure():
        nonlocal key
        key += 1
        return key
    return key, left, right, closure()

def patterns(value):
    match value:
        case {'x': captured}:
            return captured
    return None
