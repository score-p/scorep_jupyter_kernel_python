import logging
import unittest
import nbformat
import jupyter_kernel_test as jkt
import yaml, re, os

import logging_config

tmp_dir = "test_kernel_tmp/"


class KernelTests(jkt.KernelTests):
    kernel_name = "jumper"
    language_name = "python"

    @classmethod
    def setUpClass(cls) -> None:
        os.environ["DISABLE_PROCESSING_ANIMATIONS"] = "1"
        os.environ["SCOREP_ENABLE_TRACING"] = "1"
        os.environ["SCOREP_ENABLE_PROFILING"] = "0"
        os.environ["SCOREP_TOTAL_MEMORY"] = "3g"
        os.environ["SCOREP_EXPERIMENT_DIRECTORY"] = "test_kernel_tmp/scorep-traces"
        logging_config.LOGGING['loggers']['kernel']['level'] = 'WARNING'
        logging.config.dictConfig(logging_config.LOGGING)

        super().setUpClass()
        os.system(f"rm -rf {tmp_dir}")
        os.system(f"mkdir {tmp_dir}")
        os.system(f"mkdir {tmp_dir}/scorep-traces")
        return

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        os.system(f"rm -rf {tmp_dir}")
        return

    def check_from_notebook(self, notebook_path: str):
        with open(notebook_path, encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)

        for idx, cell in enumerate(nb.cells):
            if cell.cell_type != "code":
                continue

            cell_code = cell.source
            cell_outputs = cell.get("outputs", [])
            reply, output_messages = self.execute_helper(code=cell_code)

            expected_outputs = self.extract_notebook_cell_outputs(cell_outputs)
            kernel_outputs = self.extract_kernel_executed_outputs(output_messages)

            with self.subTest(cell=idx+1, code_starts=cell_code.splitlines()[0] if cell_code else '<empty>'):
                self.assertListEqual(kernel_outputs, expected_outputs)


    @staticmethod
    def extract_notebook_cell_outputs(cell_outputs: list) -> list:
        expected_outputs = []
        for output in cell_outputs:
            if output.output_type == "stream":
                message_text = output.get("text", "")
            elif output.output_type == "execute_result":
                message_text = output["data"].get("text/plain", "")
            elif output.output_type == "error":
                message_text = "\n".join(output["traceback"])
            else:
                message_text = ''

            split_message_text = [line.strip() for line in message_text.splitlines()]
            expected_outputs.extend(split_message_text)

        return expected_outputs

    @staticmethod
    def extract_kernel_executed_outputs(output_messages: list) -> list:
        kernel_outputs = []
        for msg in output_messages:
            if msg["header"]["msg_type"] == "stream":
                message_text = msg["content"]["text"]
            elif msg["header"]["msg_type"] == "execute_result":
                message_text = msg["content"]["data"]["text/plain"]
            else:
                message_text = ''

            if '\x00' not in message_text and '\r' not in message_text:
                kernel_outputs.extend(message_text.splitlines())

        return kernel_outputs

    # Enumerate tests to ensure proper execution order
    def test_00_scorep_env(self):
        self.check_from_notebook("tests/kernel/test_scorep_kernel_1.ipynb")

    def test_01_scorep_pythonargs(self):
        self.check_from_notebook("tests/kernel/scorep_pythonargs.ipynb")

    def test_02_ipykernel_exec(self):
        self.check_from_notebook("tests/kernel/ipykernel_exec.ipynb")

    def test_03_scorep_exec(self):
        self.check_from_notebook("tests/kernel/scorep_exec.ipynb")

    def test_04_persistence(self):
        self.check_from_file("tests/kernel/persistence.yaml")

    def test_05_multicell(self):
        self.check_from_file("tests/kernel/multicell.yaml")

    def test_06_writemode(self):
        self.check_from_file("tests/kernel/writemode.yaml")


if __name__ == "__main__":
    # KernelTests.check_from_notebook("tests/kernel/notebook.ipynb")
    unittest.main()
