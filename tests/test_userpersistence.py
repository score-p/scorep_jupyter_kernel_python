import unittest
import os
import sys
import json
import subprocess
import dill
import cloudpickle
from textwrap import dedent

from src.jumper.userpersistence import extract_variables_names, extract_definitions, load_variables, load_runtime

PYTHON_EXECUTABLE = sys.executable
tmp_dir = 'test_userpersistence_tmp/'

class UserPersistenceTests(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        os.system(f'rm -rf {tmp_dir}')
        os.system(f"mkdir {tmp_dir}")
        return

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        os.system(f'rm -rf {tmp_dir}')
        return
    
    def test_00_extract_variables_names(self):
        with open("tests/userpersistence/code.py", "r") as file:
            code = file.read()
        with open("tests/userpersistence/variables.json", "r") as file:
            variables = json.load(file)
        extracted_names = extract_variables_names(code)
        # Extracted names might contain extra non-variables from assignments
        # Those are filtered out later in dump_values
        self.assertTrue(set(variables.keys()).issubset(extracted_names))

    def test_01_extract_definitions(self):
        with open("tests/userpersistence/code.py", "r") as file:
            code = file.read()
        with open("tests/userpersistence/definitions.py", "r") as file:
            expected_defs = file.read()
        extracted_defs = extract_definitions(code)
        self.assertEqual(extracted_defs, expected_defs)

    def handle_communication(self, object, mode, action):
        if object == 'runtime':
            filenames = [tmp_dir + 'os_environ_' + mode, tmp_dir + 'sys_path_' + mode]
        elif object == 'var':
            filenames = [tmp_dir + 'var_' + mode]
        
        if action == 'open':
            if mode == 'memory':
                for path in filenames: os.mkfifo(path)
            elif mode == 'disk':
                for path in filenames: open(path, 'a').close()
            return filenames
        elif action == 'close':
            if mode == 'memory':
                for path in filenames: os.unlink(path)
            elif mode == 'disk':
                for path in filenames: os.remove(path)

    def test_02_dump_load_runtime(self):
        #for mode in ['memory', 'disk']:
        for mode in ['disk']:
            os_environ_file, sys_path_file = self.handle_communication('runtime', mode, 'open')
            for serializer in [dill, cloudpickle]:
                with open("tests/userpersistence/os_environ.json", "r") as file:
                    expected_os_environ = json.load(file)
                with open("tests/userpersistence/sys_path.json", "r") as file:
                    expected_sys_path = json.load(file)
                code = dedent(f"""\
                            from src.jumper.userpersistence import dump_runtime
                            import {serializer.__name__}
                            import os
                            import sys
                            os.environ.clear()
                            sys.path.clear()
                            os.environ.update({str(expected_os_environ)})
                            sys.path.extend({str(expected_sys_path)})
                            dump_runtime(os.environ, sys.path, '{os_environ_file}', '{sys_path_file}', {serializer.__name__})
                            """)
                dumped_os_environ = {}
                dumped_sys_path = []

                cmd = [PYTHON_EXECUTABLE, "-c", code]
                proc = subprocess.Popen(cmd)
                
                if mode == 'memory':
                    load_runtime(dumped_os_environ, dumped_sys_path, os_environ_file, sys_path_file, serializer)
                proc.wait()
                self.assertFalse(proc.returncode)
                if mode == 'disk':
                    load_runtime(dumped_os_environ, dumped_sys_path, os_environ_file, sys_path_file, serializer)

                self.assertFalse(proc.returncode)
                self.assertEqual(dumped_os_environ, expected_os_environ)
                self.assertEqual(dumped_sys_path, expected_sys_path)
                self.handle_communication('runtime', mode, 'close')

    def test_03_dump_load_variables(self):
        #for mode in ['memory', 'disk']:
        for mode in ['disk']:
            var_file = self.handle_communication('var', mode, 'open')[0]
            for serializer in [dill, cloudpickle]:
                with open("tests/userpersistence/code.py", "r") as file:
                    code = file.read()
                with open("tests/userpersistence/variables.json", "r") as file:
                    expected_variables = json.load(file)
                    variables_names = list(expected_variables.keys())
                code = dedent(f"""\
                            from src.jumper.userpersistence import dump_variables
                            import {serializer.__name__}
                            """) + code + \
                            f"\ndump_variables({str(variables_names)}, globals(), '{var_file}', {serializer.__name__})"
                dumped_variables = {}

                cmd = [PYTHON_EXECUTABLE, "-c", code]
                proc = subprocess.Popen(cmd)

                if mode == 'memory':
                    load_variables(dumped_variables, var_file, serializer)
                proc.wait()
                self.assertFalse(proc.returncode)
                if mode == 'disk':
                    load_variables(dumped_variables, var_file, serializer)

                # Easier to skip comparison of CustomClass object
                dumped_variables.pop('obj')
                expected_variables.pop('obj')
                self.assertEqual(dumped_variables, expected_variables)
                self.handle_communication('var', mode, 'close')

if __name__ == '__main__':
    unittest.main()
