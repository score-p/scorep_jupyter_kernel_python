import ast
import os
import sys
import unittest

import astunparse
import subprocess
from subprocess import PIPE
import src.scorep_jupyter.userpersistence as userpersistence

userpersistence_token = "scorep_jupyter.userpersistence"


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
        # declare variable, save them and load them
        # the functionality to obtain the defined variables by code parsing is tested in
        # test_get_user_variables_from_code()
        variables_from_code = ['x']
        target_val = 1
        code_save = "from " + userpersistence_token + " import * \n"
        # save a variable for x in one cell
        code_save += "x=" + str(target_val) + "\n"
        code_save += "save_user_variables(globals(), " + str(variables_from_code) + ", 'testpipe', {})\n"

        code_load = "from " + userpersistence_token + " import * \n"
        code_load += "prior = load_user_variables('testpipe')\n"
        code_load += "globals().update(prior)\n"
        # give the value of x back in another cell
        code_load += "print(globals()['x'])\n"

        subprocess.Popen([sys.executable, "-c", code_save])
        process_load = subprocess.Popen([sys.executable, "-c", code_load], stdout=PIPE)
        output = process_load.stdout.read()
        x = eval(output.decode())
        # now the loaded variables should be here
        self.assertTrue(x == target_val)
        userpersistence.tidy_up("testpipe")

    def test_save_and_load_user_definitions(self):
        if os.path.isfile("cases/test_code_1.py") and os.path.isfile("cases/test_code_1_target_userdefinitions"):
            test_code_file = open("cases/test_code_1.py", "r")
            test_code = test_code_file.read()
            test_code_file.close()

            user_defs = userpersistence.save_user_definitions(test_code, "")

            test_userdefinitions_file = open("cases/test_code_1_target_userdefinitions", "r")
            test_userdefinitions = test_userdefinitions_file.read()
            test_userdefinitions_file.close()

            self.assertTrue(astunparse.unparse(ast.parse(user_defs)) ==
                            astunparse.unparse(ast.parse(test_userdefinitions)))

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

            user_defs1 = userpersistence.save_user_definitions(test_code, "")
            user_defs2 = userpersistence.save_user_definitions(test_code2, user_defs1)

            self.assertTrue(astunparse.unparse(ast.parse(user_defs2)) ==
                            astunparse.unparse(ast.parse(test_userdefinitions)))


if __name__ == '__main__':
    unittest.main()
