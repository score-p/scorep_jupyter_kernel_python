# imports
import math
import asyncio
from scipy.stats import beta
import numpy as np
import warnings
import os

# Attributes:
# change by expr/call
warnings.filterwarnings('ignore')

# change by assign
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ = "PCI"


# classes
class A():
    my_desc = "desc"
    def foo(self):
        print("test")

    def bar(x, y, z):
        print("test2")

    class A_inner():
        definitions = "this is an inner class"

        def write_definition(definition_new, self=None):
            self.definition = definition_new


class B():
    def foo(self):
        print("do not overwrite foo of A")

    class A_inner():
        definitions = "do not overwrite inner class of A"

        def write_definition(definition_new, self=None):
            self.definition = definition_new


# expr/call with name (shouldn't be parsed)
print("hello, please do not take this statement into account")


# function def
def foo():
    print("this is an independent foo method")


def simple_decorator(func):
    def inner1(*args, **kwargs):
        func(*args, **kwargs)
        print("inner")
    return inner1


@simple_decorator
def simple_decorated():
    print("decorated")


# calling the function.
simple_decorated(10)


async def sample_task():
    await asyncio.sleep(10)
    return 'task complete'


# variables
aObj = A()
aObj.my_desc = "new_desc"
x = 2
testString = "this is a teststring"

bObj = B()
window = []
threshold = -math.log(0.05)
c, h = 3