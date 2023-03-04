from ipykernel.ipkernel import IPythonKernel
import sys
import os
import ast
import astunparse

PYTHON_EXECUTABLE = sys.executable
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
        'name': 'Any text',
        'mimetype': 'text/plain',
        'file_extension': '.py',
    }
    banner = "Jupyter kernel with Score-P Python binding."

    user_persistence = ""
    scorep_binding_args = []
    scorep_env = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # TODO: find out how output is printed in IPythonKernel
    def cell_output(self, string, stream='stdout'):
        """
        Display string as cell output.
        """
        stream_content = {'name': stream, 'text': string}
        self.send_response(self.iopub_socket, 'stream', stream_content)

    def set_scorep_env(self, code):
        """
        Read and record Score-P environment variables from the cell.
        """
        self.scorep_env += code.split('\n')[1:]
        self.cell_output(
            'Score-P environment set successfully: ' + str(self.scorep_env))

    def set_scorep_pythonargs(self, code):
        """
        Read and record Score-P Python binding arguments from the cell.
        """
        self.scorep_binding_args += code.split('\n')[1:]
        self.cell_output(
            'Score-P Python binding arguments set successfully: ' + str(self.scorep_binding_args))

    def save_definitions(self, code):
        """
        Extract imported modules and definitions of classes and functions from the code block.
        """
        # can't use in kernel as import from userpersistence - self-reference error during dill dump of notebook
        root = ast.parse(code)
        definitions = []
        for top_node in ast.iter_child_nodes(root):
            if isinstance(top_node, ast.With):
                for node in ast.iter_child_nodes(top_node):
                    if (isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef) or
                            isinstance(node, ast.ClassDef) or isinstance(node, ast.Import) or isinstance(node,
                                                                                                         ast.ImportFrom)):
                        definitions.append(node)
            elif (isinstance(top_node, ast.FunctionDef) or isinstance(top_node, ast.AsyncFunctionDef) or
                  isinstance(top_node, ast.ClassDef) or isinstance(top_node, ast.Import) or isinstance(top_node,
                                                                                                       ast.ImportFrom)):
                definitions.append(top_node)

        pers_string = ""
        for node in definitions:
            pers_string += astunparse.unparse(node)

        return pers_string

    def get_user_variables(self, code):
        """
        Extract user-assigned variables from code. Unlike dir(), nothing coming from the imported modules is included.
        """
        root = ast.parse(code)

        variables = set()
        for node in ast.walk(root):
            # assignment nodes can include attributes, therefore go over all targets and check for attribute nodes
            if isinstance(node, ast.Assign) or isinstance(node, ast.AnnAssign):
                for el in node.targets:
                    for target_node in ast.walk(el):
                        if isinstance(target_node, ast.Name):
                            variables.add(target_node.id)

        return variables

    async def do_execute(self, code, silent, store_history=True, user_expressions=None,
                         allow_stdin=False, *, cell_id=None):
        """
        Override of do_execute() method of IPythonKernel. If no custom magic commands specified,
        execute cell with super().do_execute(), else save Score-P environment/binding arguments/
        execute cell with Score-P Python binding.
        """
        # TODO: fix cell id counter
        if code.startswith('%%scorep_env'):
            self.set_scorep_env(code)
            reply_status = {'status': 'ok',
                            # The base class increments the execution count
                            'execution_count': self.execution_count,
                            'payload': [],
                            'user_expressions': {},
                            }
        elif code.startswith('%%scorep_python_binding_arguments'):
            self.set_scorep_pythonargs(code)
            reply_status = {'status': 'ok',
                            # The base class increments the execution count
                            'execution_count': self.execution_count,
                            'payload': [],
                            'user_expressions': {},
                            }
        elif code.startswith('%%execute_with_scorep'):
            code = code.split("\n", 1)[1]

            # ghost cell - dump current jupyter session
            dump_jupyter = "import dill\n" + \
                          f"dill.dump_session('{jupyter_dump}')"
            await super().do_execute(dump_jupyter, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)

            # prepare code for scorep instrumented execution
            user_variables = self.get_user_variables(code)
            
            scorep_code = "import scorep\n" + \
                          "with scorep.instrumenter.disable():\n" + \
                         f"    from {userpersistence_token} import * \n" + \
                          "    import dill\n" + \
                         f"    globals().update(dill.load_module_asdict('{jupyter_dump}'))\n" + \
                          code + "\n" + \
                          "with scorep.instrumenter.disable():\n" + \
                         f"   save_user_variables(globals(), {str(user_variables)}, '{subprocess_dump}')"

            scorep_script_file = open(scorep_script_name, 'w+')
            scorep_script_file.write(scorep_code)
            scorep_script_file.close()

            script_run = "%%bash\n" + \
                        f"{' '.join(self.scorep_env)} {PYTHON_EXECUTABLE} -m scorep {' '.join(self.scorep_binding_args)} {scorep_script_name}"
            await super().do_execute(script_run, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)

            # ghost cell - load subprocess persistence back to jupyter session
            load_jupyter = self.save_definitions(code) + "\n" + \
                          f"vars_load = open('{subprocess_dump}', 'rb')\n" + \
                           "globals().update(dill.load(vars_load))\n" + \
                           "vars_load.close()"
            await super().do_execute(load_jupyter, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)

            reply_status = {'status': 'ok',
                            # The base class increments the execution count
                            'execution_count': self.execution_count,
                            'payload': [],
                            'user_expressions': {},
                            }
        else:
            reply_status = await super().do_execute(code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)

        return reply_status

    def do_shutdown(self, restart):
        """
        Override of do_shutdown() method of IPythonKernel. Clean up
        persistence and variables dumps before the exit.
        """
        for aux_file in [scorep_script_name, jupyter_dump, subprocess_dump]:
            if os.path.exists(aux_file):
                os.remove(aux_file)
        super().do_shutdown(restart)


if __name__ == '__main__':
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=ScorepPythonKernel)