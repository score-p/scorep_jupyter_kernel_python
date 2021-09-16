from ipykernel.kernelbase import Kernel
from subprocess import Popen, PIPE 
import os
import re
import userpersistency

PYTHON_EXECUTABLE= "/home/h9/s4122485/virtualenv_jupyterkernel_scorep_python/bin/python"

class ScoreP_Python_Kernel(Kernel):
    implementation = 'Python and ScoreP'
    implementation_version = '1.0'
    language = 'python'
    language_version = '3.8'
    language_info = {
        'name': 'Any text',
        'mimetype': 'text/plain',
        'file_extension': '.py',
    }
    banner = "A python kernel with scorep binding"
    
    userEnv = {}
    scoreP_python_args = ""
    multicellmode = False
    init_multicell = False
    multicellmode_cellcount = 0
    
    def do_execute(self, code, silent, store_history=True, user_expressions=None,
                   allow_stdin=False):

        if code.startswith('%%scorep_env'):
            #set scorep environment variables
            scoreP_vars = code.split('\n')
            #iterate from first line since this is scoreP_env indicator
            for var in scoreP_vars[1:]:
                keyVal=var.split('=')
                self.userEnv[keyVal[0]]=keyVal[1]
            stream_content_stdout = {'name': 'stdout', 'text': 'set user environment sucessfully: ' + str(self.userEnv)}
            self.send_response(self.iopub_socket, 'stream', stream_content_stdout)
        elif code.startswith('%%scorep_python_binding_arguments'):
            #set scorep python bindings arguments
            self.scoreP_python_args = ' '.join(code.split('\n')[1:])
            stream_content_stdout = {'name': 'stdout', 'text': 'use the following scorep python binding arguments: ' + str(self.scoreP_python_args)}
            self.send_response(self.iopub_socket, 'stream', stream_content_stdout)
        #elif code.startswith('%%profile'):
            #start with internal profiling mode
            #self.manage_profiling_commands(code)
        elif code.startswith('%%enable_multicellmode'):
            #start to mark the cells for multi cell mode
            if os.path.exists(".tmpCodeFile.py"):
                #ensure to start with a clean file in multi cell mode
                os.remove(".tmpCodeFile.py")
            self.multicellmode = True
            self.multicellmode_cellcount = 0
            self.init_multicell = True
            stream_content_stdout = {'name': 'stdout', 'text': 'started multi-cell mode. The following cells will be marked.'}
            self.send_response(self.iopub_socket, 'stream', stream_content_stdout)
        elif code.startswith('%%abort_multicellmode'):
            #abort the multi cell mode
            self.multicellmode = False
            self.init_multicell = False
            self.multicellmode_cellcount = 0
            stream_content_stdout = {'name': 'stdout', 'text': 'aborted multi-cell mode.'}
            self.send_response(self.iopub_socket, 'stream', stream_content_stdout)
        elif code.startswith('%%finalize_multicellmode'):
            #finish multi cell mode and execute the code of the marked cells
            stream_content_stdout = {'name': 'stdout', 'text': 'finalizing multi-cell mode and execute cells.'}
            self.send_response(self.iopub_socket, 'stream', stream_content_stdout)
            self.multicellmode = False
            self.init_multicell = False
            self.multicellmode_cellcount = 0
            cell_code_file = open(".tmpCodeFile.py", "r")
            #read the defined code to save it
            code = cell_code_file.read()
            cell_code_file.close()
            userpersistency.save_user_definitions(code)
            user_variables = userpersistency.get_user_variables_from_code(code)
            #add ordinary userpersistency handling (as in normal mode)
            cell_code_file = open(".tmpCodeFile.py", "w")
            cell_code_file.write("import userpersistency\n")
            cell_code_file.write("from tmp_userpersistency import *\n")
            cell_code_file.write("globals().update(userpersistency.load_user_variables())\n")
            cell_code_file.write(code)

            cell_code_file.write("\nuserpersistency.save_user_variables(globals(), "+str(user_variables)+")")
            cell_code_file.close()
            ls_output = Popen([PYTHON_EXECUTABLE, "-m", "scorep", self.scoreP_python_args, ".tmpCodeFile.py"], stdout=PIPE, stderr=PIPE,
                              env=os.environ.update(self.userEnv))
            (output, err) = ls_output.communicate()
            if not silent:
                if output:
                    stream_content_stdout = {'name': 'stdout', 'text': output.decode('utf8')}
                    self.send_response(self.iopub_socket, 'stream', stream_content_stdout)
                if err:
                    stream_content_stderr = {'name': 'stderr', 'text': err.decode('utf8')}
                    self.send_response(self.iopub_socket, 'stream', stream_content_stderr)
            
        else:
            execute_with_scorep = code.startswith('%%execute_with_scorep')
            if execute_with_scorep:
                #just remove first line (execute_with_scorep indicator)
                code = code.split("\n",1)[1]
            if self.multicellmode:
                #in multi cell mode, just append the code because we execute multiple cells as one
                self.multicellmode_cellcount += 1
                cell_code = open(".tmpCodeFile.py", "a")
            else:
                #if we do not use scorep or multi cell mode, just remove the content and write to the file
                cell_code = open(".tmpCodeFile.py", "w")
            
            #import variables defined so far
            if not self.multicellmode:
                #all cells that are not executed in multi cell mode have to import them
                cell_code.write("import userpersistency\n")
                #prior imports can be loaded before runtime. we have to load them this way because they can not be pickled
                
                #user variables can be pickled and should be loaded at runtime
                cell_code.write("from tmp_userpersistency import *\n")
                cell_code.write("globals().update(userpersistency.load_user_variables())\n")
            
            #add original cell code
            cell_code.write("\n"+code)

            #for persistency reasons, we have to store user defined variables  after the execution of the cell. 
            #therefore we use shelve/pickle for object serialization and object persistency
            #imports, user defined classes and methods are handled by storing them in code files and prepending them to the execution cell code
            #However, if the user defines some network connections, filereaders etc. this might fail due to pickle limitations

            if not self.multicellmode:
                #in multi cell mode we call this mechanism in "finalize"
                user_variables = userpersistency.get_user_variables_from_code(code)
                cell_code.write("\nuserpersistency.save_user_variables(globals(), "+str(user_variables)+")")
                userpersistency.save_user_definitions(code)
            
            cell_code.close()
            
            if self.multicellmode:
                #if we are in multi cell mode, do not execute here (wait for "finalize")
                stream_content_stdout = {'name': 'stdout', 'text': 'marked the cell for multi-cell mode. This cell will be executed at position: ' + str(self.multicellmode_cellcount)}
                self.send_response(self.iopub_socket, 'stream', stream_content_stdout)
            else:       
                #execute cell with or without scorep
                if execute_with_scorep:
                    ls_output = Popen([PYTHON_EXECUTABLE, "-m", "scorep", self.scoreP_python_args, ".tmpCodeFile.py"], stdout=PIPE, stderr=PIPE,
                                      env=os.environ.update(self.userEnv))
                else:
                    ls_output = Popen([PYTHON_EXECUTABLE, ".tmpCodeFile.py"], stdout=PIPE, stderr=PIPE,
                                      env=os.environ.update(self.userEnv))

                (output, err) = ls_output.communicate()
                if not silent:
                    if output:
                        stream_content_stdout = {'name': 'stdout', 'text': output.decode('utf8')}
                        self.send_response(self.iopub_socket, 'stream', stream_content_stdout)
                    if err:
                        stream_content_stderr = {'name': 'stderr', 'text': err.decode('utf8')}
                        self.send_response(self.iopub_socket, 'stream', stream_content_stderr)

        return {'status': 'ok',
                # The base class increments the execution count
                'execution_count': self.execution_count,
                'payload': [],
                'user_expressions': {},
               }


    def do_shutdown(content, restart):
        if os.path.exists(".tmpCodeFile.py"):
            os.remove(".tmpCodeFile.py")
        userpersistency.tidy_up()

        return {'status': 'ok',
                'restart': restart
               }


    def manage_profiling_commands(self, code):
        if code.startswith('%%profile_runtime'):
            prof = cubex.open('profile.cubex')
            metrics = prof.show_metrics()                       
            stream_content_stdout = {'data': metrics, 'metadata': metrics}
        elif code.startswith('%%profile_memory'):
            stream_content_stdout = {'name': 'stdout', 'text': 'memory'}
        elif code.startswith('%%profile_functioncalls'):
            stream_content_stdout = {'name': 'stdout', 'text': 'calls'}
        
        self.send_response(self.iopub_socket, 'display_data', stream_content_stdout)


if __name__ == '__main__':
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=ScoreP_Python_Kernel)
