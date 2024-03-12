import unittest
import os
import sys
import json
import subprocess
import dill
import cloudpickle
from textwrap import dedent

from src.scorep_jupyter.userpersistence import extract_variables_names, extract_definitions, load_variables, load_runtime

PYTHON_EXECUTABLE = sys.executable
dump_dir = 'tests_tmp/'

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
        # Those are filtered out later in pickle_values
        self.assertTrue(set(variables.keys()).issubset(extracted_names))

    def test_01_extract_definitions(self):
        with open("tests/userpersistence/code.py", "r") as file:
            code = file.read()
        with open("tests/userpersistence/definitions.py", "r") as file:
            expected_defs = file.read()
        extracted_defs = extract_definitions(code)
        self.assertEqual(extracted_defs, expected_defs)

    def test_02_pickle_load_runtime(self):
        # clean sys.path and os.environ inside subprocess and fill with values from file
        # load dump and compare with file
        # merge with load runtime
        for serializer, serializer_str in zip([dill, cloudpickle], ['dill', 'cloudpickle']):
            with open("tests/userpersistence/os_environ.json", "r") as file:
                expected_os_environ = json.load(file)
            with open("tests/userpersistence/sys_path.json", "r") as file:
                expected_sys_path = json.load(file)
            code = dedent(f"""\
                          from src.scorep_jupyter.userpersistence import pickle_runtime
                          import {serializer_str}
                          import os
                          import sys
                          os.environ.clear()
                          sys.path.clear()
                          os.environ.update({str(expected_os_environ)})
                          sys.path.extend({str(expected_sys_path)})
                          pickle_runtime(os.environ, sys.path, '{dump_dir}', {serializer_str})
                          """)
            cmd = [PYTHON_EXECUTABLE, "-c", code]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
                proc.wait()
            self.assertFalse(proc.returncode)

            pickled_os_environ = {}
            pickled_sys_path = []
            load_runtime(pickled_os_environ, pickled_sys_path, dump_dir, serializer)
            self.assertEqual(pickled_os_environ, expected_os_environ)
            self.assertEqual(pickled_sys_path, expected_sys_path)

    def test_03_pickle_load_variables(self):
        for serializer, serializer_str in zip([dill, cloudpickle], ['dill', 'cloudpickle']):
            with open("tests/userpersistence/code.py", "r") as file:
                code = file.read()
            with open("tests/userpersistence/variables.json", "r") as file:
                expected_variables = json.load(file)
                variables_names = list(expected_variables.keys())

            code = dedent(f"""\
                        from src.scorep_jupyter.userpersistence import pickle_variables
                        import {serializer_str}
                        """) + code + \
                        f"\npickle_variables({str(variables_names)}, globals(), '{dump_dir}', {serializer_str})"
            cmd = [PYTHON_EXECUTABLE, "-c", code]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
                proc.wait()
            self.assertFalse(proc.returncode)

            pickled_variables = {}
            load_variables(pickled_variables, dump_dir, serializer)
            # Easier to skip comparison of CustomClass object
            pickled_variables.pop('obj')
            expected_variables.pop('obj')
            self.assertEqual(pickled_variables, expected_variables)

if __name__ == '__main__':
    unittest.main()