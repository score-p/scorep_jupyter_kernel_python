import pandas



class B():
    def foo_new(self):
        print("do not overwrite foo of A")

    class A_inner_new():
        definitions = "do not overwrite inner class of A"

        def write_definition_new(definition_new, self=None):
            self.definition = definition_new


print("hello, please do not take this statement into account")


def foo():
    print("this was added later")

def bar():
    print("a new function")
