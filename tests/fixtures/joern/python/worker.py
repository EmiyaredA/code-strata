from barrel import allowed as permit, create_key, Store

state = 0


async def upload_asset(file, user):
    allowed = permit(user)  # CASE alias-reexport
    if not allowed:
        raise ValueError('Forbidden')
    name, suffix = file.name, 'asset'  # CASE destructuring
    key = create_key(name)  # CASE direct-call
    store = Store()  # CASE constructor

    def nested():
        key = 'inner'  # CASE shadow-inner
        return key

    def captured():
        return key  # CASE closure-capture

    def mutate():
        nonlocal key
        key = 'changed'  # CASE nonlocal

    if len(name) > 5:
        key = key + '-long'  # CASE reassignment
    url = store.put(key, file)  # CASE method-call
    nested()  # CASE nested-call
    中文 = '😀'; unicode_key = create_key(  # CASE unicode-multiline
        中文
    )
    return {'key': key, 'url': url, 'captured': captured()}


def recurse(n):
    if n <= 0:
        return 0
    return recurse(n - 1)  # CASE recursion


def dispatch(handler):
    return handler()  # CASE unresolved-callback


def dynamic_call(obj, name):
    return getattr(obj, name)()  # CASE dynamic-target


def cleanup():
    return 'done'


def control(items):
    global state
    state = 1  # CASE global
    total = 0
    try:
        for item in items:  # CASE loop
            if item < 0:
                continue
            if item > 10:
                break
            total += item
        else:
            total += 1  # CASE loop-else
        if total:
            return total  # CASE early-return
        raise ValueError('empty')
    except ValueError:
        return -1
    finally:
        cleanup()  # CASE finally


def generate():
    yield create_key('one')  # CASE generator


async def async_call(task):
    return await task()  # CASE async


def overwritten():
    value = 1  # CASE flow-first-write
    value = 2  # CASE flow-last-write
    return value  # CASE flow-read
