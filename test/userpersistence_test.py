import ast
import inspect
import os
import sys
import unittest

import astunparse
import numpy as np
import pandas as pd

import userpersistence

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir)

# global variable declaration for load and save variable test
x = 2
y = 3
test_string = "test_string"
window = []


class Testclass():
    z = 4


class_instance = Testclass()
test_list = [1, 2, 3, 4]
df = pd.DataFrame(np.random.randint(0, 100, size=(100, 4)), columns=list('ABCD'))
np_array = np.random.rand(2, 3)


class TestUserpersistence(unittest.TestCase):

    def test_get_user_variables_from_code(self):
        if os.path.isfile("cases/test_code_1.py") and os.path.isfile("cases/test_code_1_target_variables"):
            test_code_file = open("cases/test_code_1.py", "r")
            test_code = test_code_file.read()
            test_code_file.close()
            test_variables_file = open("cases/test_code_1_target_variables", "r")
            test_variables = ast.literal_eval(test_variables_file.read())
            test_variables_file.close()

            variables = userpersistence.get_user_variables_from_code(test_code)
            # the found variables should contain all the target variables.
            # found variables might contain more variables because they contain also local variables
            # note that local variables are filtered later by merging with globals()
            self.assertTrue(set(test_variables).issubset(variables))

    def test_save_and_load_user_variables(self):
        # declare variables, save them and load them
        # global x, y, test_string, class_instance, test_list, df, np_array, window
        # the functionality to obtain the defined variables by code parsing is tested in
        # test_get_user_variables_from_code()
        variables_from_code = ['x', 'y', 'test_string', 'class_instance', 'test_list', 'df', 'np_array', 'window']
        with open("tmpUserPers.py", "w") as f:
            # create empty file to make things work
            pass
        userpersistence.save_user_variables(globals(), variables_from_code, "tmpUserPers.py", ".tmpUserVars")
        loaded_variables = userpersistence.load_user_variables(".tmpUserVars")
        # now the loaded variables should also occur in globals()
        self.assertTrue(set(globals()).issuperset(loaded_variables))
        userpersistence.tidy_up("tmpUserPers.py", ".tmpUserVars")

    def test_save_and_load_user_definitions(self):
        if os.path.isfile("cases/test_code_1.py") and os.path.isfile("cases/test_code_1_target_userdefinitions"):
            test_code_file = open("cases/test_code_1.py", "r")
            test_code = test_code_file.read()
            test_code_file.close()

            userpersistence.save_user_definitions(test_code, "tmpUserPers.py")

            test_userdefinitions_file = open("cases/test_code_1_target_userdefinitions", "r")
            test_userdefinitions = test_userdefinitions_file.read()
            test_userdefinitions_file.close()

            self.assertTrue(os.path.isfile("tmpUserPers.py"))
            test_userpersistence_file = open("tmpUserPers.py", "r")
            test_userpersistence = test_userpersistence_file.read()
            test_userpersistence_file.close()
            self.assertTrue(astunparse.unparse(ast.parse(test_userpersistence)) ==
                            astunparse.unparse(ast.parse(test_userdefinitions)))
            userpersistence.tidy_up("tmpUserPers.py", ".tmpUserVars")

    def test_save_and_load_user_definitions_multiple(self):
        if os.path.isfile("cases/test_code_1.py") and os.path.isfile("cases/test_code_1.py") \
                and os.path.isfile("cases/test_code_2_target_userdefinitions"):
            test_code_file = open("cases/test_code_1.py", "r")
            test_code = test_code_file.read()
            test_code_file.close()
            test_code_file = open("cases/test_code_2.py", "r")
            test_code2 = test_code_file.read()
            test_code_file.close()
            test_userdefinitions_file = open("cases/test_code_2_target_userdefinitions", "r")
            test_userdefinitions = test_userdefinitions_file.read()
            test_userdefinitions_file.close()

            userpersistence.save_user_definitions(test_code, "tmpUserPers.py")
            userpersistence.save_user_definitions(test_code2, "tmpUserPers.py")
            self.assertTrue(os.path.isfile("tmpUserPers.py"))
            test_userpersistence_file = open("tmpUserPers.py", "r")
            test_userpersistence = test_userpersistence_file.read()
            test_userpersistence_file.close()
            self.assertTrue(astunparse.unparse(ast.parse(test_userpersistence)) ==
                            astunparse.unparse(ast.parse(test_userdefinitions)))
            userpersistence.tidy_up("tmpUserPers.py", ".tmpUserVars")

    def test_save_user_definitions_and_variables(self):
        if os.path.isfile("cases/test_code_1.py") and os.path.isfile("cases/test_code_1_target_userdefinitions"):
            test_code_file = open("cases/test_code_1.py", "r")
            test_code = test_code_file.read()
            test_code_file.close()

            userpersistence.save_user_definitions(test_code, "tmpUserPers.py")

            variables_from_code = ['x', 'y', 'test_string', 'class_instance', 'test_list', 'df', 'np_array', 'window']
            userpersistence.save_user_variables(globals(), variables_from_code, "tmpUserPers.py", ".tmpUserVars")
            loaded_variables = userpersistence.load_user_variables(".tmpUserVars")
            # now the loaded variables should also occur in globals()
            self.assertTrue(set(globals()).issuperset(loaded_variables))
            userpersistence.tidy_up("tmpUserPers.py", ".tmpUserVars")


if __name__ == '__main__':
    unittest.main()
