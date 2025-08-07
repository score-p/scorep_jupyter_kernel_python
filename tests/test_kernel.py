import logging
import unittest
import nbformat
from unittest.mock import MagicMock
import jupyter_kernel_test as jkt
import yaml, re, os

from scorep_jupyter import logging_config
from scorep_jupyter.kernel_messages import (
    KernelErrorCode,
    KERNEL_ERROR_MESSAGES,
)
from scorep_jupyter.kernel import scorep_jupyterKernel

tmp_dir = "test_kernel_tmp/"


class KernelTests(jkt.KernelTests):
    kernel_name = "scorep_jupyter"
    language_name = "python"

    @classmethod
    def setUpClass(cls) -> None:
        os.environ["SCOREP_JUPYTER_DISABLE_PROCESSING_ANIMATIONS"] = "1"
        os.environ["SCOREP_ENABLE_TRACING"] = "1"
        os.environ["SCOREP_ENABLE_PROFILING"] = "0"
        os.environ["SCOREP_TOTAL_MEMORY"] = "3g"
        os.environ["SCOREP_EXPERIMENT_DIRECTORY"] = (
            "test_kernel_tmp/scorep-traces"
        )
        logging_config.LOGGING["loggers"]["kernel"]["level"] = "WARNING"
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
            kernel_outputs = self.extract_kernel_executed_outputs(
                output_messages
            )

            with self.subTest(
                cell=idx + 1,
                code_starts=(
                    cell_code.splitlines()[0] if cell_code else "<empty>"
                ),
            ):
                self.assertListEqual(kernel_outputs, expected_outputs)

    def extract_notebook_cell_outputs(self, cell_outputs: list) -> list:
        expected_outputs = []
        for output in cell_outputs:
            if output.output_type == "stream":
                message_text = output.get("text", "")
            elif output.output_type == "execute_result":
                message_text = output["data"].get("text/plain", "")
            elif output.output_type == "error":
                message_text = "\n".join(output["traceback"])
            else:
                message_text = ""

            split_message_text = self.prepare_notebook_message_list(
                message_text
            )
            expected_outputs.extend(split_message_text)

        return expected_outputs

    @staticmethod
    def prepare_notebook_message_list(message_text: str) -> list:
        split_message_text = []
        for line in message_text.splitlines():
            clean_line = line.strip()
            # Expand environment variables (e.g. "${PWD}")
            # to ensure consistent test results across different machines
            expanded_line = os.path.expandvars(clean_line)
            split_message_text.append(expanded_line)
        return split_message_text

    @staticmethod
    def extract_kernel_executed_outputs(output_messages: list) -> list:
        kernel_outputs = []
        for msg in output_messages:
            if msg["header"]["msg_type"] == "stream":
                message_text = msg["content"]["text"]
            elif msg["header"]["msg_type"] == "execute_result":
                message_text = msg["content"]["data"]["text/plain"]
            else:
                message_text = ""

            if "\x00" not in message_text and "\r" not in message_text:
                split_message_text = [
                    line.strip() for line in message_text.splitlines()
                ]
                kernel_outputs.extend(split_message_text)

        return kernel_outputs

    # Enumerate tests to ensure proper execution order
    def test_00_scorep_pythonargs(self):
        self.check_from_notebook("tests/kernel/scorep_pythonargs.ipynb")

    def test_01_ipykernel_exec(self):
        self.check_from_notebook("tests/kernel/ipykernel_exec.ipynb")

    def test_02_scorep_exec(self):
        self.check_from_notebook("tests/kernel/scorep_exec.ipynb")

    def test_03_persistence(self):
        self.check_from_notebook("tests/kernel/persistence.ipynb")

    def test_04_multicell(self):
        pass
        # TODO: should be moved to the extension or tested only if extension is loaded
        # self.check_from_notebook("tests/kernel/multicell.ipynb")

    def test_05_writemode(self):
        self.check_from_notebook("tests/kernel/writemode.ipynb")


class DummyPersHelper:
    def __init__(self, mode="test_mode", marshaller="test_marshal"):
        self.mode = mode
        self.marshaller = marshaller


class KernelTestLogError(unittest.TestCase):
    def setUp(self):
        self.kernel = scorep_jupyterKernel()
        setattr(self.kernel.log, "error", MagicMock())
        self.kernel.cell_output = MagicMock()
        self.kernel.pershelper = DummyPersHelper()

        self.direction = "Far away"

    def test_error_with_all_fields(self):

        self.kernel.log_error(
            KernelErrorCode.PERSISTENCE_DUMP_FAIL, direction=self.direction
        )
        expected = KERNEL_ERROR_MESSAGES[
            KernelErrorCode.PERSISTENCE_DUMP_FAIL
        ].format(
            mode="test_mode",
            marshaller="test_marshal",
            direction=self.direction,
        )
        self.kernel.log.error.assert_called_with(expected)
        self.kernel.cell_output.assert_called_with(
            f"KernelError: {expected}", "stderr"
        )

    def test_unknown_error_code(self):
        dummy_code = -1

        self.kernel.log_error(dummy_code, dumb_hint="bar")
        msg = "Unknown error. Mode: test_mode, Marshaller: test_marshal"
        self.assertTrue(self.kernel.log.error.call_args[0][0].startswith(msg))

    def test_error_templates_are_formatable(self):
        fake_context = {
            "mode": "test_mode",
            "marshaller": "test_marshal",
            "direction": "dummy_direction",
            "detail": "dummy_detail",
            "step": "dummy_step",
            "optional_hint": "dummy_optional_hint",
            "scorep_folder": "/fake/path/to/scorep-dir",
            "exception": "dummy_exception",
        }

        for code, template in KERNEL_ERROR_MESSAGES.items():
            try:
                formatted = template.format(**fake_context)
                self.assertIsInstance(formatted, str)
            except KeyError as e:
                self.fail(f"Missing key in template for {code.name}: {e}")
            except ValueError as e:
                self.fail(f"Format error in template for {code.name}: {e}")


if __name__ == "__main__":
    unittest.main()
