from ipykernel.ipkernel import IPythonKernel
import sys
import os
import subprocess
import re
import json
from scorep_jupyter.userpersistence import extract_definitions, extract_variables_names

PYTHON_EXECUTABLE = sys.executable
READ_CHUNK_SIZE = 8
userpersistence_token = "scorep_jupyter.userpersistence"
scorep_script_name = "scorep_script.py"
jupyter_dump = "jupyter_dump.pkl"
subprocess_dump = "subprocess_dump.pkl"


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

        self.multicellmode = False
        self.multicellmode_cellcount = 0
        self.multicell_code = ""

        self.writemode = False
        self.writemode_filename = 'jupyter_to_script'
        self.writemode_multicell = False
        self.writemode_scorep_binding_args = []
        self.writemode_scorep_env = []
        # TODO: reset variables after each finalize writefile?
        self.bash_script_filename = ""
        self.python_script_filename = ""
        self.bash_script = None
        self.python_script = None

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

    def comm_files_cleanup(self):
        """
        Clean up files used for transmitting persistence and running subprocess.
        """
        for aux_file in [scorep_script_name, jupyter_dump, subprocess_dump]:
            if os.path.exists(aux_file):
                os.remove(aux_file)

    def set_scorep_env(self, code):
        """
        Read and record Score-P environment variables from the cell.
        """
        for scorep_param in code.split('\n')[1:]:
            key, val = scorep_param.split('=')
            self.scorep_env[key] = val
        self.cell_output(
            'Score-P environment set successfully: ' + str(self.scorep_env))
        return self.standard_reply()

    def set_scorep_pythonargs(self, code):
        """
        Read and record Score-P Python binding arguments from the cell.
        """
        self.scorep_binding_args += code.split('\n')[1:]
        self.cell_output(
            'Score-P Python binding arguments set successfully: ' + str(self.scorep_binding_args))
        return self.standard_reply()

    def enable_multicellmode(self):
        """
        Start multicell mode.
        """
        # TODO: scorep setup cells are not affected
        self.multicellmode = True
        self.cell_output(
            'Multicell mode enabled. The following cells will be marked for instrumented execution.')
        return self.standard_reply()

    def abort_multicellmode(self):
        """
        Cancel multicell mode.
        """
        self.multicellmode = False
        self.multicell_code = ""
        self.multicellmode_cellcount = 0
        self.cell_output('Multicell mode aborted.')
        return self.standard_reply()

    def append_multicellmode(self, code):
        """
        Append cell to multicell mode sequence.
        """
        self.multicell_code += ("\n" + code)
        self.multicellmode_cellcount += 1
        self.cell_output(
            f'Cell marked for multicell mode. It will be executed at position {self.multicellmode_cellcount}')
        return self.standard_reply()

    def start_writefile(self):
        """
        Start recording the notebook as a Python script. Custom file name
        can be defined as an argument of the magic command.
        """
        # TODO: Check for os path existence
        # TODO: Edge cases processing, similar to multicellmode
        self.writemode = True
        self.bash_script_filename = os.path.realpath(
            '') + '/' + self.writemode_filename + '_run.sh'
        self.python_script_filename = os.path.realpath(
            '') + '/' + self.writemode_filename + '.py'
        self.bash_script = open(self.bash_script_filename, 'w+')
        self.bash_script.write('# This bash script is generated automatically to run\n' +
                               '# Jupyter Notebook -> Python script convertation by Score-P kernel\n' +
                               '# ' + self.python_script_filename + '\n')
        self.bash_script.write('#!/bin/bash\n')
        self.python_script = open(self.python_script_filename, 'w+')
        self.python_script.write('# This is the automatic Jupyter Notebook -> Python script convertation by Score-P kernel.\n' +
                                 '# Code corresponding to the cells not marked for Score-P instrumentation\n' +
                                 '# is framed "with scorep.instrumenter.disable()".\n' +
                                 '# The script can be run with proper settings with bash script\n' +
                                 '# ' + self.bash_script_filename + '\n')
        # import scorep by default, convertation might add scorep commands
        # that are not present in original notebook (e.g. cells without instrumentation)
        self.python_script.write('import scorep\n')

        self.cell_output('Started converting to Python script. See files:\n' +
                         self.bash_script_filename + '\n' + self.python_script_filename + '\n')
        return self.standard_reply()

    def end_writefile(self):
        """
        Finish recording the notebook as a Python script.
        """
        # TODO: check for os path existence
        self.writemode = False
        self.bash_script.write(
            f"{' '.join(self.writemode_scorep_env)} {PYTHON_EXECUTABLE} -m scorep {' '.join(self.writemode_scorep_binding_args)} {self.python_script_filename}")

        self.bash_script.close()
        self.python_script.close()
        self.cell_output('Finished converting to Python script, files closed.')
        return self.standard_reply()

    def append_writefile(self, code):
        """
        Append cell to write mode sequence. Extract Score-P environment or Python bindings argument if necessary.
        """
        if code.startswith('%%scorep_env'):
            self.writemode_scorep_env += code.split('\n')[1:]
            self.cell_output('Environment variables recorded.')
        elif code.startswith('%%scorep_python_binding_arguments'):
            self.writemode_scorep_binding_args += code.split('\n')[1:]
            self.cell_output('Score-P bindings arguments recorded.')

        elif code.startswith('%%enable_multicellmode'):
            self.writemode_multicell = True
        elif code.startswith('%%finalize_multicellmode'):
            self.writemode_multicell = False
        elif code.startswith('%%abort_multicellmode'):
            self.cell_output(
                'Warning: Multicell abort command is ignored in write mode, check if the output file is recorded as expected.',
                'stderr')

        elif code.startswith('%%execute_with_scorep') or self.writemode_multicell:
            # Cut all magic commands
            code = code.split('\n')
            code = ''.join(
                [line + '\n' for line in code if not line.startswith('%%')])
            self.python_script.write(code + '\n')
            self.cell_output(
                'Python commands with instrumentation recorded.')

        elif not self.writemode_multicell:
            # Cut all magic commands
            code = code.split('\n')
            code = ''.join(
                ['    ' + line + '\n' for line in code if not line.startswith('%%')])
            self.python_script.write(
                'with scorep.instrumenter.disable():\n' + code + '\n')
            self.cell_output(
                'Python commands without instrumentation recorded.')
        return self.standard_reply()

    async def scorep_execute(self, code, silent, store_history=True, user_expressions=None,
                             allow_stdin=False, *, cell_id=None):
        """
        Execute given code with Score-P Python bindings instrumentation.
        """
        # Ghost cell - dump current Jupyter session for subprocess
        # Run in a "silent" way to not increase cells counter
        dump_jupyter = "import dill\n" + f"dill.dump_session('{jupyter_dump}')"
        reply_status_dump = await super().do_execute(dump_jupyter, silent, store_history=False,
                                                     user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)

        if reply_status_dump['status'] != 'ok':
            self.shell.execution_count += 1
            reply_status_dump['execution_count'] = self.shell.execution_count - 1
            self.comm_files_cleanup()
            self.cell_output("KernelError: Failed to pickle previous notebook's persistence and variables.",
                             'stderr')
            return reply_status_dump

        # Prepare code for the Score-P instrumented execution as subprocess
        # Transmit user persistence and updated sys.path from Jupyter notebook to subprocess
        # After running code, transmit subprocess persistence back to Jupyter notebook

        try:
            user_variables = extract_variables_names(code)
        except SyntaxError as e:
            self.cell_output(f"SyntaxError: {e}", 'stderr')
            return self.standard_reply()
        
        sys_path_updated = json.dumps(sys.path)
        scorep_code = "import scorep\n" + \
                      "with scorep.instrumenter.disable():\n" + \
                     f"    from {userpersistence_token} import save_variables_values \n" + \
                      "    import dill\n" + \
                     f"    globals().update(dill.load_module_asdict('{jupyter_dump}'))\n" + \
                      "    import sys\n" + \
                      "    sys.path.clear()\n" + \
                     f"    sys.path.extend({sys_path_updated})\n" + \
                      code + "\n" + \
                      "with scorep.instrumenter.disable():\n" + \
                     f"   save_variables_values(globals(), {str(user_variables)}, '{subprocess_dump}')"

        with open(scorep_script_name, 'w+') as file:
            file.write(scorep_code)

        # Launch subprocess with Jupyter notebook environment
        cmd = [PYTHON_EXECUTABLE, "-m", "scorep"] + \
            self.scorep_binding_args + [scorep_script_name]
        proc_env = os.environ.copy()
        proc_env.update(self.scorep_env)
        proc_env.update({'PYTHONUNBUFFERED': 'x'}) # subprocess observation

        incomplete_line = ''
        endline_pattern = re.compile(r'(.*?[\r\n]|.+$)')

        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=proc_env) as proc:
            # Redirect process stderr to stdout and observe the latter
            # Observing two stream with two threads causes interfence in cell_output in Jupyter notebook
            # stdout is read in chunks, which are split into lines using \r or \n as delimeter
            # Last element in the list might be "incomplete line", not ending with \n or \r, it is saved
            # and merged with the first line in the next chunk

            # Empty cell output, required for interactive output e.g. tqdm for-loop progress bar
            self.cell_output('\0')
            while True:
                chunk = b'' + proc.stdout.read(READ_CHUNK_SIZE)
                if not chunk:
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

            proc.wait()

        if proc.returncode:
            self.comm_files_cleanup()
            self.cell_output(
                'KernelError: Cell execution failed, cell persistence and variables are not recorded.',
                'stderr')
            return self.standard_reply()

        # Ghost cell - load subprocess definitions and persistence back to Jupyter notebook
        # Run in a "silent" way to not increase cells counter
        load_jupyter = extract_definitions(code) + "\n" + \
                        f"with open('{subprocess_dump}', 'rb') as file:\n" + \
                         "    globals().update(dill.load(file))\n"
        reply_status_load = await super().do_execute(load_jupyter, silent, store_history=False,
                                                     user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)

        if reply_status_load['status'] != 'ok':
            self.shell.execution_count += 1
            reply_status_load['execution_count'] = self.shell.execution_count - 1
            self.comm_files_cleanup()
            self.cell_output("KernelError: Failed to load cell's persistence and variables to the notebook.",
                             'stderr')
            return reply_status_load

        self.comm_files_cleanup()
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
        return self.standard_reply()

    async def do_execute(self, code, silent, store_history=False, user_expressions=None,
                         allow_stdin=False, *, cell_id=None):
        """
        Override of do_execute() method of IPythonKernel. If no custom magic commands specified,
        execute cell with super().do_execute(), else save Score-P environment/binding arguments/
        execute cell with Score-P Python binding.
        """
        if code.startswith('%%start_writefile'):
            # Get file name from arguments of magic command
            writefile_cmd = code.split('\n')[0].split(' ')
            if len(writefile_cmd) > 1:
                if writefile_cmd[1].endswith('.py'):
                    self.writemode_filename = writefile_cmd[1][:-3]
                else:
                    self.writemode_filename = writefile_cmd[1]
            return self.start_writefile()
        elif code.startswith('%%end_writefile'):
            return self.end_writefile()
        elif self.writemode:
            return self.append_writefile(code)

        elif code.startswith('%%finalize_multicellmode'):
            if not self.multicellmode:
                self.cell_output(
                    "KernelError: Multicell mode disabled. Run a cell with %%enable_multicellmode command first.",
                    'stderr')
                return self.standard_reply()

            try:
                reply_status = await self.scorep_execute(self.multicell_code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
            except:
                return self.standard_reply()
            self.multicell_code = ""
            self.multicellmode_cellcount = 0
            self.multicellmode = False
            return reply_status

        elif code.startswith('%%abort_multicellmode'):
            if not self.multicellmode:
                self.cell_output(
                    "KernelError: Multicell mode disabled. Run a cell with %%enable_multicellmode command first.",
                    'stderr')
                return self.standard_reply()
            return self.abort_multicellmode()
        elif code.startswith('%%enable_multicellmode'):
            return self.enable_multicellmode()

        elif code.startswith('%%scorep_env'):
            return self.set_scorep_env(code)
        elif code.startswith('%%scorep_python_binding_arguments'):
            return self.set_scorep_pythonargs(code)
        elif self.multicellmode:
            return self.append_multicellmode(code)
        elif code.startswith('%%execute_with_scorep'):
            return await self.scorep_execute(code.split("\n", 1)[1], silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
        else:
            return await super().do_execute(code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)


if __name__ == '__main__':
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=ScorepPythonKernel)