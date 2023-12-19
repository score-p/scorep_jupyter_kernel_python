import unittest
import jupyter_kernel_test as jkt
import os
import yaml

class KernelTests(jkt.KernelTests):
    kernel_name = "scorep-python"
    language_name = "python"
    
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        os.system("mkdir tests_tmp")
        return
    
    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        os.system("rm -rf tests_tmp")
        return

    def check_stream_output(self, code, expected_output, stream="stdout"):
        self.flush_channels()
        reply, output_msgs = self.execute_helper(code=code)
        for msg, expected_msg in zip(output_msgs, expected_output):
            self.assertEqual(msg["header"]["msg_type"], "stream")
            self.assertEqual(msg["content"]["name"], stream)
            self.assertEqual(msg["content"]["text"], expected_msg)

    def check_from_file(self, filename):
        with open(filename, 'r') as file:
            cells = yaml.safe_load(file)
        for code, expected_output in cells:
            self.check_stream_output(code, expected_output)

    # Enumerate tests to ensure proper execution order
    def test_00_scorep_env(self):
        self.check_from_file("tests/kernel/scorep_env.yaml")
    
    def test_01_scorep_pythonargs(self):
        self.check_from_file("tests/kernel/scorep_pythonargs.yaml")
    
    def test_02_ipykernel_exec(self):
        self.check_from_file("tests/kernel/ipykernel_exec.yaml")
    
    def test_03_scorep_exec(self):
        self.check_from_file("tests/kernel/scorep_exec.yaml")
    
    def test_04_persistence(self):
        self.check_from_file("tests/kernel/persistence.yaml")

    def test_05_multicell(self):
        self.check_from_file("tests/kernel/multicell.yaml")
    
    def test_06_writemode(self):
        self.check_from_file("tests/kernel/writemode.yaml")

if __name__ == "__main__":
    unittest.main()