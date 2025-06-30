import yaml, os
import logging
import unittest
from unittest.mock import MagicMock
import jupyter_kernel_test as jkt

from scorep_jupyter import logging_config
from scorep_jupyter.kernel_messages import KernelErrorCode, KERNEL_ERROR_MESSAGES
from scorep_jupyter.kernel import scorep_jupyterKernel

tmp_dir = "test_kernel_tmp/"


class KernelTests(jkt.KernelTests):
    kernel_name = "scorep_jupyter"
    language_name = "python"

    @classmethod
    def setUpClass(cls) -> None:
        os.environ["scorep_jupyter_DISABLE_PROCESSING_ANIMATIONS"] = "1"
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
        reply, output_msgs = self.execute_helper(code=code)
        for msg, expected_msg in zip(output_msgs, expected_output):
            # replace env vars
            expected_msg = os.path.expandvars(expected_msg)
            # self.assertEqual(msg["header"]["msg_type"], "stream")
            # some messages can be of type 'execute_result'
            # type instead of stdout
            # self.assertEqual(msg["content"]["name"], stream)

            if msg["header"]["msg_type"] == "stream":
                # self.assertEqual(msg["content"]["name"], stream)
                self.assertEqual(
                    clean_console_output(msg["content"]["text"]),
                    clean_console_output(expected_msg)
                )
            elif msg["header"]["msg_type"] == "execute_result":
                self.assertEqual(
                    clean_console_output(msg["content"]["data"]["text/plain"]),
                    clean_console_output(expected_msg)
                )


    def check_from_file(self, filename):

        with open(filename, "r") as file:
            cells = yaml.safe_load(file)

        for idx, (code, expected_output) in enumerate(cells):
            with self.subTest(block=idx, code_line=code.splitlines()[0]):
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


def clean_console_output(text):
    return text.replace('\r', '').strip()


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
            KernelErrorCode.PERSISTENCE_DUMP_FAIL,
            direction=self.direction
        )
        expected = KERNEL_ERROR_MESSAGES[KernelErrorCode.PERSISTENCE_DUMP_FAIL].format(
            mode="test_mode",
            marshaller="test_marshal",
            direction=self.direction
        )
        self.kernel.log.error.assert_called_with(expected)
        self.kernel.cell_output.assert_called_with(f"KernelError: {expected}", "stderr")

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
            "step": "dummy_step"
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
