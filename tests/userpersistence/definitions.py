
import warnings

import os

import asyncio


def square(x):
    return (x ** 2)


class CustomClass():
    desc = 'Custom class'

    def __init__(self, value):
        self.value = value

    def foo(self):
        print('Foo')

    def bar(x, y, z):
        print('Bar')

    class CustomInnerClass():
        inner_desc = 'Inner custom class'

        def baz(self=None):
            print('Baz')


def foo():
    print('Foo Function')


def simple_decorator(func):

    def inner(*args, **kwargs):
        func(*args, **kwargs)
        print('inner')
    return inner


@simple_decorator
def simple_decorated():
    print('Decorated')


async def sample_task():
    (await asyncio.sleep(10))
    return 'task complete'
