import logging
import unittest
import jupyter_kernel_test as jkt
import yaml, os

from jumper import logging_config

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


if __name__ == "__main__":
    unittest.main()
