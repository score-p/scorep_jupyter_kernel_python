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

    def check_stream_output(self, code, expected_output, stream="stdout"):
        self.flush_channels()
        reply, output_messages = self.execute_helper(code=code)
        from pprint import pprint

        for expected_msg in expected_output:
            # replace env vars
            expected_msg = os.path.expandvars(expected_msg)
            for msg in output_messages:
                self.extract_message_output(msg)




    def check_from_file(self, filename):
        with open(filename, "r") as file:
            cells = yaml.safe_load(file)

        for idx, (code, expected_output) in enumerate(cells):
            with self.subTest(block=idx, code_line=code.splitlines()[0]):
                self.check_stream_output(code, expected_output)

    def check_from_notebook(self, notebook_path: str):
        nb = nbformat.read(open(notebook_path), as_version=4)
        from pprint import pprint
        # pprint(nb.cells)

        for idx, cell in enumerate(nb.cells):
            if cell.cell_type != "code":
                continue

            cell_code = cell.source
            cell_outputs = cell.get("outputs", [])
            reply, output_messages = self.execute_helper(code=cell_code)

            expected_outputs = self.extract_notebook_cell_outputs(cell_outputs)
            kernel_outputs = self.extract_kernel_executed_outputs(output_messages)

            # print(idx)
            # pprint(expected_outputs)
            # print('---------------------------------')
            # pprint(kernel_outputs)
            # print()

            # with self.subTest(cell=idx, code_line=cell_code.splitlines()[0] if cell_code.strip() else "<empty>"):
            #     self.assertListEqual()

            # with self.subTest(cell=idx, code_line=code.splitlines()[0] if code.strip() else "<empty>"):
            #     self.check_stream_output(code, expected_outputs)

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
            message_text = message_text.strip()
            print(f'{message_text=}')
            expected_outputs.append(message_text)
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
                kernel_outputs.append(message_text.strip())

        return kernel_outputs

    # Enumerate tests to ensure proper execution order
    def test_00_scorep_env(self):
        self.check_from_notebook("tests/kernel/test_scorep_kernel.ipynb")

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
    # KernelTests.check_from_notebook("tests/kernel/notebook.ipynb")
    unittest.main()
