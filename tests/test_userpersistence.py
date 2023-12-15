import unittest
import os
import sys
import json
import subprocess
import dill

from src.scorep_jupyter.userpersistence import extract_variables_names, extract_definitions

PYTHON_EXECUTABLE = sys.executable
subprocess_dump = "tests_tmp/subprocess_dump.pkl"
userpersistence_token = "src.scorep_jupyter.userpersistence"

class UserPersistenceTests(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        os.system("mkdir tests_tmp")
        return

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        os.system(f'rm -rf tests_tmp')
        return
    
    def test_00_extract_variables_names(self):
        with open("tests/userpersistence/code.py", "r") as file:
            code = file.read()
        with open("tests/userpersistence/variables.json", "r") as file:
            variables = json.load(file)
        extracted_names = extract_variables_names(code)
        # Extracted names might contain extra non-variables from assignments
        # Those are filtered out later in save_variables_values
        self.assertTrue(set(variables.keys()).issubset(extracted_names))

    def test_01_extract_definitions(self):
        with open("tests/userpersistence/code.py", "r") as file:
            code = file.read()
        with open("tests/userpersistence/definitions.py", "r") as file:
            expected_defs = file.read()
        extracted_defs = extract_definitions(code)
        self.assertEqual(extracted_defs, expected_defs)

    def test_02_save_variables_values(self):
        with open("tests/userpersistence/code.py", "r") as file:
            code = file.read()
        with open("tests/userpersistence/variables.json", "r") as file:
            variables = json.load(file)
        code = f"from {userpersistence_token} import save_variables_values\n" + \
                code + "\n" + \
               f"save_variables_values(globals(), {str(list(variables.keys()))}, '{subprocess_dump}')"
        cmd = [PYTHON_EXECUTABLE, "-c", code]
        with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
            proc.wait()
        with open(subprocess_dump, 'rb') as file:
            saved_values = dill.load(file)
        # Easier to skip comparison of CustomClass object
        saved_values.pop('obj')
        variables.pop('obj')
        self.assertEqual(saved_values, variables)

if __name__ == '__main__':
    unittest.main()