from ipykernel.ipkernel import IPythonKernel
import sys
import os
import subprocess
import re
from scorep_jupyter.userpersistence import PersHelper, scorep_script_name, magics_cleanup
from enum import Enum
from textwrap import dedent

PYTHON_EXECUTABLE = sys.executable
READ_CHUNK_SIZE = 8

# kernel modes
class KernelMode(Enum):
    DEFAULT   = (0, 'default')
    MULTICELL = (1, 'multicell')
    WRITEFILE = (2, 'writefile')
    
    def __str__(self):
        return self.value[1]

class ScorepPythonKernel(IPythonKernel):
    implementation = 'Python and Score-P'
    implementation_version = '1.0'
    language = 'python'
    language_version = '3.8'
    language_info = {
        'name': 'python',
        'mimetype': 'text/plain',
        'file_extension': '.py',
    }
    banner = "Jupyter kernel with Score-P Python binding."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.scorep_binding_args = []
        self.scorep_env = {}

        os.environ['SCOREP_KERNEL_PERSISTENCE_DIR'] = './'
        self.pershelper = PersHelper('dill', 'memory')

        self.mode = KernelMode.DEFAULT

        self.multicell_cellcount = 0
        self.multicell_code = ""

        self.writefile_base_name = "jupyter_to_script"
        self.writefile_bash_name = ""
        self.writefile_python_name = ""
        self.writefile_scorep_env = []
        self.writefile_scorep_binding_args = []
        self.writefile_multicell = False
        
    def cell_output(self, string, stream='stdout'):
        """
        Display string as cell output.
        """
        stream_content = {'name': stream, 'text': string}
        self.send_response(self.iopub_socket, 'stream', stream_content)

    def standard_reply(self):
        self.shell.execution_count += 1
        return {'status': 'ok',
                'execution_count': self.shell.execution_count - 1,
                'payload': [],
                'user_expressions': {},
                }

    def serializer_settings(self, code):
        """
        Switch serializer backend used for persistence in kernel.
        """
        if self.mode == KernelMode.DEFAULT:
            # Clean files/pipes before switching
            self.pershelper.postprocess()

            serializer_match = re.search(r'SERIALIZER=(\w+)', code.split('\n', 1)[1])
            mode_match = re.search(r'MODE=(\w+)', code.split('\n', 1)[1])
            serializer = serializer_match.group(1) if serializer_match else None
            mode = mode_match.group(1) if mode_match else None

            if serializer:
                if not self.pershelper.set_serializer(serializer):
                    self.cell_output(f"Serializer '{serializer}' is not recognized, kernel will use '{self.pershelper.serializer}'.", 'stderr')
                    return self.standard_reply()
            if mode:
                if not self.pershelper.set_mode(mode):
                    self.cell_output(f"Serialization mode '{mode}' is not recognized, kernel will use '{self.pershelper.mode}'.", 'stderr')

            self.cell_output(f"Kernel uses '{self.pershelper.serializer}' serializer in '{self.pershelper.mode}' mode.")
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def set_scorep_env(self, code):
        """
        Read and record Score-P environment variables from the cell.
        """
        if self.mode == KernelMode.DEFAULT:
            for scorep_param in code.split('\n')[1:]:
                key, val = scorep_param.split('=')
                self.scorep_env[key] = val
            self.cell_output(
                'Score-P environment set successfully: ' + str(self.scorep_env))
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_scorep_env += code.split('\n')[1:]
            self.cell_output('Environment variables recorded.')
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def set_scorep_pythonargs(self, code):
        """
        Read and record Score-P Python binding arguments from the cell.
        """
        if self.mode == KernelMode.DEFAULT:
            self.scorep_binding_args += code.split('\n')[1:]
            self.cell_output(
                'Score-P Python binding arguments set successfully: ' + str(self.scorep_binding_args))
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_scorep_binding_args += code.split('\n')[1:]
            self.cell_output('Score-P bindings arguments recorded.')
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def enable_multicellmode(self):
        """
        Start multicell mode.
        """
        if self.mode == KernelMode.DEFAULT:
            self.mode = KernelMode.MULTICELL
            self.cell_output('Multicell mode enabled. The following cells will be marked for instrumented execution.')
        elif self.mode == KernelMode.MULTICELL:
            self.cell_output(f'KernelWarning: {KernelMode.MULTICELL} mode has already been enabled', 'stderr')
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_multicell = True
        return self.standard_reply()

    def append_multicellmode(self, code):
        """
        Append cell to multicell mode sequence.
        """
        if self.mode == KernelMode.MULTICELL:
            self.multicell_cellcount += 1
            max_line_len = max(len(line) for line in code.split('\n'))
            self.multicell_code += f"print('Executing cell {self.multicell_cellcount}')\n" + \
                                f"print('''{code}''')\n" + \
                                f"print('-' * {max_line_len})\n" + \
                                f"{code}\n" + \
                                f"print('''\n''')\n"
            self.cell_output(
                f'Cell marked for multicell mode. It will be executed at position {self.multicell_cellcount}')
        return self.standard_reply()

    def abort_multicellmode(self):
        """
        Cancel multicell mode.
        """
        if self.mode == KernelMode.MULTICELL:
            self.mode = KernelMode.DEFAULT
            self.multicell_code = ""
            self.multicell_cellcount = 0
            self.cell_output('Multicell mode aborted.')
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def start_writefile(self, code):
        """
        Start recording the notebook as a Python script. Custom file name
        can be defined as an argument of the magic command.
        """
        # TODO: Check for os path existence
        # TODO: Edge cases processing, similar to multicellmode
        if self.mode == KernelMode.DEFAULT:
            self.mode = KernelMode.WRITEFILE
            writefile_cmd = code.split('\n')[0].split(' ')
            if len(writefile_cmd) > 1:
                if writefile_cmd[1].endswith('.py'):
                    self.writefile_base_name = writefile_cmd[1][:-3]
                else:
                    self.writefile_base_name = writefile_cmd[1]
            self.writefile_bash_name = os.path.realpath('') + '/' + self.writefile_base_name + '_run.sh'
            self.writefile_python_name = os.path.realpath('') + '/' + self.writefile_base_name + '.py'

            with open(self.writefile_bash_name, 'w+') as bash_script:
                bash_script.write(dedent(f"""\
                                          # This bash script is generated automatically to run
                                          # Jupyter Notebook -> Python script conversion by Score-P kernel
                                          # {self.writefile_python_name}
                                          # !/bin/bash
                                          """))
            with open(self.writefile_python_name, 'w+') as python_script:
                python_script.write(dedent(f"""
                                            # This is the automatic Jupyter Notebook -> Python script conversion by Score-P kernel.
                                            # Code corresponding to the cells not marked for Score-P instrumentation
                                            # is framed "with scorep.instrumenter.disable()
                                            # The script can be run with proper settings using bash script
                                            # {self.writefile_bash_name}
                                            import scorep
                                            """))
            self.cell_output('Started converting to Python script. See files:\n' +
                            self.writefile_bash_name + '\n' + self.writefile_python_name + '\n')
        elif self.mode == KernelMode.WRITEFILE:
            self.cell_output(f'KernelWarning: {KernelMode.WRITEFILE} mode has already been enabled', 'stderr')
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def append_writefile(self, code, explicit_scorep):
        """
        Append cell to writefile.
        """
        if self.mode == KernelMode.WRITEFILE:
            if explicit_scorep or self.writefile_multicell:
                with open(self.writefile_python_name, 'a') as python_script:
                    python_script.write(code + '\n')
                self.cell_output('Python commands with instrumentation recorded.')
            else:
                with open(self.writefile_python_name, 'a') as python_script:
                    code = ''.join(['    ' + line + '\n' for line in code.split('\n')])
                    python_script.write('with scorep.instrumenter.disable():\n' + code + '\n')
                self.cell_output('Python commands without instrumentation recorded.')
        return self.standard_reply()

    def end_writefile(self):
        """
        Finish recording the notebook as a Python script.
        """
        # TODO: check for os path existence
        if self.mode == KernelMode.WRITEFILE:
            self.mode = KernelMode.DEFAULT
            with open(self.writefile_bash_name, 'a') as bash_script:
                bash_script.write(
                    f"{' '.join(self.writefile_scorep_env)} {PYTHON_EXECUTABLE} -m scorep {' '.join(self.writefile_scorep_binding_args)} {self.writefile_python_name}")
            self.cell_output('Finished converting to Python script.')
        else:
            self.cell_output(
                f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def ghost_cell_error(self, reply_status, error_message):
        self.shell.execution_count += 1
        reply_status['execution_count'] = self.shell.execution_count - 1
        self.pershelper.postprocess()
        self.cell_output(error_message, 'stderr')

    async def scorep_execute(self, code, silent, store_history=True, user_expressions=None,
                             allow_stdin=False, *, cell_id=None):
        """
        Execute given code with Score-P Python bindings instrumentation.
        """
        # Set up files/pipes for persistence communication
        if not self.pershelper.preprocess():
            self.pershelper.postprocess()
            self.cell_output("KernelError: Failed to set up the persistence communication files/pipes.", "stderr")
            return self.standard_reply()

        # Prepare code for the Score-P instrumented execution as subprocess
        # Transmit user persistence and updated sys.path from Jupyter notebook to subprocess
        # After running the code, transmit subprocess persistence back to Jupyter notebook
        with open(scorep_script_name, 'w') as file:
            file.write(self.pershelper.subprocess_wrapper(code))

        # For disk mode use implicit synchronization between kernel and subprocess:
        # await jupyter_dump, subprocess.wait(), await jupyter_update
        # Ghost cell - dump current Jupyter session for subprocess
        # Run in a "silent" way to not increase cells counter
        if self.pershelper.mode == 'disk':
            reply_status_dump = await super().do_execute(self.pershelper.jupyter_dump(), silent, store_history=False,
                                                    user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)
            if reply_status_dump['status'] != 'ok':
                self.ghost_cell_error(reply_status_dump, "KernelError: Failed to pickle notebook's persistence.")
                return reply_status_dump
            
        # Launch subprocess with Jupyter notebook environment
        cmd = [PYTHON_EXECUTABLE, "-m", "scorep"] + \
            self.scorep_binding_args + [scorep_script_name]
        proc_env = self.scorep_env.copy()
        proc_env.update({'PATH': os.environ['PATH'], 'PYTHONUNBUFFERED': 'x'}) # scorep path, subprocess observation
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=proc_env)
        
        # For memory mode jupyter_dump and jupyter_update must be awaited
        # concurrently to the running subprocess
        if self.pershelper.mode == 'memory':
            reply_status_dump = await super().do_execute(self.pershelper.jupyter_dump(), silent, store_history=False,
                                                        user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)
            if reply_status_dump['status'] != 'ok':
                self.ghost_cell_error(reply_status_dump, "KernelError: Failed to pickle notebook's persistence.")
                return reply_status_dump

        # Redirect process stderr to stdout and observe the latter
        # Observing two stream with two threads causes interference in cell_output in Jupyter notebook
        # stdout is read in chunks, which are split into lines using \r or \n as delimiter
        # Last element in the list might be "incomplete line", not ending with \n or \r, it is saved
        # and merged with the first line in the next chunk
        incomplete_line = ''
        endline_pattern = re.compile(r'(.*?[\r\n]|.+$)')
        # Empty cell output, required for interactive output e.g. tqdm for-loop progress bar
        self.cell_output('\0')
        while True:
            chunk = b'' + proc.stdout.read(READ_CHUNK_SIZE)
            if chunk == b'':
                break
            chunk = chunk.decode(sys.getdefaultencoding(), errors='ignore')
            lines = endline_pattern.findall(chunk)
            if len(lines) > 0:
                lines[0] = incomplete_line + lines[0]
                if lines[-1][-1] not in ['\n', '\r']:
                    incomplete_line = lines.pop(-1)
                else:
                    incomplete_line = ""
                for line in lines:
                    self.cell_output(line)

        # In disk mode, subprocess already terminated after dumping persistence to file
        if self.pershelper.mode == 'disk':
            if proc.returncode:
                self.pershelper.postprocess()
                self.cell_output('KernelError: Cell execution failed, cell persistence was not recorded.', 'stderr')
                return self.standard_reply()
            
        # os_environ_.clear()
        # sys_path_.clear()

        # Ghost cell - load subprocess persistence back to Jupyter notebook
        # Run in a "silent" way to not increase cells counter
        reply_status_update = await super().do_execute(self.pershelper.jupyter_update(code), silent, store_history=False,
                                                    user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)
        if reply_status_update['status'] != 'ok':
            self.ghost_cell_error(reply_status_update, "KernelError: Failed to load cell's persistence to the notebook.")
            return reply_status_update
        
        # In memory mode, subprocess terminates once jupyter_update is executed and pipe is closed
        if self.pershelper.mode == 'memory':
            if proc.returncode:
                self.pershelper.postprocess()
                self.cell_output('KernelError: Cell execution failed, cell persistence was not recorded.', 'stderr')
                return self.standard_reply()

        # Determine directory to which trace files were saved by Score-P
        if 'SCOREP_EXPERIMENT_DIRECTORY' in self.scorep_env:
            scorep_folder = self.scorep_env['SCOREP_EXPERIMENT_DIRECTORY']
            self.cell_output(
                f"Instrumentation results can be found in {scorep_folder}")
        else:
            # Find last creasted directory with scorep* name
            # TODO: Directory isn't created locally when running scorep-collector
            scorep_dirs = [d for d in os.listdir('.') if os.path.isdir(d) and 'scorep' in d]
            if scorep_dirs:
                scorep_folder = max(scorep_dirs, key=os.path.getmtime)
                self.cell_output(
                    f"Instrumentation results can be found in {os.getcwd()}/{scorep_folder}")
            else:
                self.cell_output("KernelWarning: Instrumentation results were not saved locally.", 'stderr')

        self.pershelper.postprocess()
        return self.standard_reply()

    async def do_execute(self, code, silent, store_history=False, user_expressions=None,
                         allow_stdin=False, *, cell_id=None):
        """
        Override of do_execute() method of IPythonKernel. If no custom magic commands specified,
        execute cell with super().do_execute(), else save Score-P environment/binding arguments/
        execute cell with Score-P Python binding.
        """
        if code.startswith('%%scorep_env'):
            return self.set_scorep_env(code)
        elif code.startswith('%%scorep_python_binding_arguments'):
            return self.set_scorep_pythonargs(code)
        elif code.startswith('%%serializer_settings'):
            return self.serializer_settings(code)
        elif code.startswith('%%enable_multicellmode'):
            return self.enable_multicellmode()
        elif code.startswith('%%abort_multicellmode'):
            return self.abort_multicellmode()
        elif code.startswith('%%finalize_multicellmode'):
            # Cannot be put into a separate function due to tight coupling between do_execute and scorep_execute
            if self.mode == KernelMode.MULTICELL:
                self.mode = KernelMode.DEFAULT
                try:
                    reply_status = await self.scorep_execute(self.multicell_code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
                except:
                    self.cell_output("KernelError: Multicell execution failed.", 'stderr')
                    return self.standard_reply()
                self.multicell_code = ""
                self.multicell_cellcount = 0
                return reply_status
            elif self.mode == KernelMode.WRITEFILE:
                self.writefile_multicell = False
                return self.standard_reply()
            else:
                self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
                return self.standard_reply()
        elif code.startswith('%%start_writefile'):
            return self.start_writefile(code)
        elif code.startswith('%%end_writefile'):
            return self.end_writefile()
        elif code.startswith('%%execute_with_scorep'):
            if self.mode == KernelMode.DEFAULT:
                return await self.scorep_execute(code.split("\n", 1)[1], silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
            elif self.mode == KernelMode.MULTICELL:
                return self.append_multicellmode(magics_cleanup(code.split("\n", 1)[1]))
            elif self.mode == KernelMode.WRITEFILE:
                return self.append_writefile(magics_cleanup(code.split("\n", 1)[1]), explicit_scorep=True)
        else:
            if self.mode == KernelMode.DEFAULT:
                self.pershelper.parse(magics_cleanup(code), 'jupyter')
                return await super().do_execute(code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
            elif self.mode == KernelMode.MULTICELL:
                return self.append_multicellmode(magics_cleanup(code))
            elif self.mode == KernelMode.WRITEFILE:
                return self.append_writefile(magics_cleanup(code), explicit_scorep=False)

    def do_shutdown(self, restart):
        self.pershelper.postprocess()
        return super().do_shutdown(restart)


if __name__ == '__main__':
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=ScorepPythonKernel)