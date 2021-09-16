import unittest
import os
import ast
import pandas as pd
import numpy as np

import sys, os, inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir)
import scorep_jupyter_python_kernel
import userpersistency

#global variable declaration for load and save variable test
x = 2
y = 3
test_string = "test_string"
class Testclass():
    z=4
class_instance = Testclass()
test_list = [1,2,3,4]
df = pd.DataFrame(np.random.randint(0,100,size=(100, 4)), columns=list('ABCD'))
np_array = np.random.rand(2,3)

class Test_Userpersistency(unittest.TestCase):

    def test_get_user_variables_from_code(self):
        if os.path.isfile("cases/test_code_1.py") and os.path.isfile("cases/test_code_1_target_variables"):            
            test_code_file = open("cases/test_code_1.py", "r")
            test_code = test_code_file.read()
            test_code_file.close()
            test_variables_file = open("cases/test_code_1_target_variables", "r")
            test_variables = ast.literal_eval(test_variables_file.read())
            test_variables_file.close()
            
            variables = userpersistency.get_user_variables_from_code(test_code)
            #the found variables should contain all the target variables. 
            #found variables might contain more variables because they contain also local variables
            #note that local variables are filtered later by merging with globals()
            self.assertTrue(set(test_variables).issubset(variables))
            userpersistency.tidy_up()
            

    def test_save_and_load_user_variables(self):
        #declare variables, save them and load them
        global x, y, test_string, class_instance, test_list, df, np_array
        #the functionality to obtain the defined variables by code parsing is tested in test_get_user_variables_from_code()
        variables_from_code = ['x','y','test_string','class_instance','test_list','df','np_array']
        userpersistency.save_user_variables(globals(), variables_from_code)
        loaded_variables = userpersistency.load_user_variables()
        #now the loaded variables should also occur in globals()
        self.assertTrue(set(loaded_variables).issubset(globals()))
        userpersistency.tidy_up()


    def test_save_and_load_user_definitions(self):
        if os.path.isfile("cases/test_code_1.py") and os.path.isfile("cases/test_code_1_target_userdefinitions"):
            test_code_file = open("cases/test_code_1.py", "r")
            test_code = test_code_file.read()
            test_code_file.close()
            test_userdefinitions_file = open("cases/test_code_1_target_userdefinitions", "r")
            test_userdefinitions = test_userdefinitions_file.read().replace('\n', '')
            test_userdefinitions_file.close()
                        
            userpersistency.save_user_definitions(test_code)
            self.assertTrue(os.path.isfile("tmp_userpersistency.py"))
            test_userpersistency_file = open("tmp_userpersistency.py", "r")
            test_userpersistency = test_userpersistency_file.read().replace('\n', '')
            test_userpersistency_file.close()
            self.assertTrue(test_userpersistency == test_userdefinitions)
            userpersistency.tidy_up()

            
if __name__ == '__main__':
    unittest.main()
