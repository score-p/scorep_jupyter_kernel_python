import pandas
import numpy as np

class A():
    def foo():
        print("test")

    def bar(x,y,z):
        print("test2")

    class A_inner():
        definitions = "this is an inner class"
        
        def write_definition(definition_new):
            self.definition = definition_new

class B():
    def foo():
        print("do not overwrite foo of A")

    class A_inner():
        definitions = "do not overwrite inner class of A"

        def write_definition(definition_new):
            self.definition = definition_new


print("hello, please do not take this statement into account")


def foo():
    print("this is an independent foo method")


aObj = A()
x = 2
testString = "this is a teststring"

bObj = B()
