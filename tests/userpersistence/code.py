import warnings
import os
import asyncio

warnings.filterwarnings('ignore')

os.environ["MY_ENV_VAR"] = "1234"

def square(x):
    return x ** 2

var_a = var_b = var_c = 42
if var_a + var_b > 80:
    var_d = var_a + var_b
    print("var_d value = ", var_d)
var_e, var_f = 43, 44

list_g = [1, 2, 3]
str_h: str = "Hello, world"
dict_j = {'key': 'val'}

class CustomClass:
    desc = "Custom class"
    def __init__(self, value):
        self.value = value

    def foo(self):
        print("Foo")

    def bar(x, y, z):
        print("Bar")

    class CustomInnerClass():
        inner_desc = "Inner custom class"

        def baz(self=None):
            print("Baz")

def foo():
    print("Foo Function")

obj = CustomClass(3.14)
obj.desc = "Very custom class"

def simple_decorator(func):
    def inner(*args, **kwargs):
        func(*args, **kwargs)
        print("inner")
    return inner

@simple_decorator
def simple_decorated():
    print("Decorated")

simple_decorated()

async def sample_task():
    await asyncio.sleep(10)
    return 'task complete'