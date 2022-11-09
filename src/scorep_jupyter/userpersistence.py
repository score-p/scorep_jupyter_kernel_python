import os
import ast
import astunparse
import dill
import sys
import time

'''
Note: general limitation
changes in modules can not be persisted since pickling/shelving modules is not allowed
'''
comm_pipe = "_comm"
val_pipe = "_val"


def save_user_definitions(code, code_prev):
    # keep imports, classes and definitions
    root = ast.parse(code)

    code_curr = []
    for top_node in ast.iter_child_nodes(root):
        if isinstance(top_node, ast.With):
            for node in ast.iter_child_nodes(top_node):
                if (isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef) or
                        isinstance(node, ast.ClassDef) or isinstance(node, ast.Import) or isinstance(node,
                                                                                                     ast.ImportFrom)):
                    code_curr.append(node)
        elif (isinstance(top_node, ast.FunctionDef) or isinstance(top_node, ast.AsyncFunctionDef) or
              isinstance(top_node, ast.ClassDef) or isinstance(top_node, ast.Import) or isinstance(top_node,
                                                                                                   ast.ImportFrom)):
            code_curr.append(top_node)

    code_curr_id = [node.name for node in code_curr if isinstance(node, ast.FunctionDef)
                    or isinstance(node, ast.ClassDef)]

    code_prev = [node for node in ast.iter_child_nodes(ast.parse(code_prev))]
    code_to_keep = []
    for node in code_prev:
        # TODO: maintain synch of imports
        # TODO: maintain synch of attributes (del keyword)
        if not (isinstance(node, ast.FunctionDef) or isinstance(node, ast.ClassDef) or
                isinstance(node, ast.AsyncFunctionDef)):
            code_to_keep.append(node)
        else:
            if node.name not in code_curr_id:
                code_to_keep.append(node)
    code_to_keep.append(code_curr)

    pers_string = ""
    for node in code_to_keep:
        pers_string += astunparse.unparse(node)

    return pers_string


def get_user_variables_from_code(code):
    # found variables might contain more variables because they contain also local variables
    # note that local variables are filtered later by merging with globals()
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


def check_rec_del(basepipeName, t):
    while True:
        with open(basepipeName + comm_pipe, "rb") as file:
            line = file.readline()

        if line == b"REC\n":
            with open(basepipeName + val_pipe, "wb") as file:
                file.write(t + b"0000000")
        elif line == b"DEL\n":
            os.unlink(basepipeName + comm_pipe)
            os.unlink(basepipeName + val_pipe)
            break
        time.sleep(1)


def save_user_variables(globs, variables, basepipeName, prior_variables):
    user_variables = {k: v for k, v in globs.items() if str(k) in variables}
    user_variables = {**prior_variables, **user_variables}

    for el in user_variables.keys():
        # if possible, exchange class of the object here with the class that is stored for persistence. This is
        # valid since the classes should be the same and this does not affect the objects attribute dictionary
        non_persistent_class = user_variables[el].__class__.__name__
        if non_persistent_class in globals().keys():
            user_variables[el].__class__ = globals()[non_persistent_class]

    if user_variables:

        if os.path.exists(basepipeName + comm_pipe) and os.path.exists(basepipeName + val_pipe):
            with open(basepipeName + comm_pipe, "wb") as file:
                file.write(b'DEL\n')

        t = dill.dumps(user_variables)

        # wait until both pipes are deleted from previous cell/process
        while True:
            if not (os.path.exists(basepipeName + comm_pipe) and os.path.exists(basepipeName + val_pipe)):
                break
            time.sleep(1)

        os.mkfifo(basepipeName + comm_pipe)
        os.mkfifo(basepipeName + val_pipe)
        sys.stdout.write("WAIT" + basepipeName)

        check_rec_del(basepipeName, t)


def load_user_variables(basepipeName):
    content = {}

    if os.path.exists(basepipeName + comm_pipe) and os.path.exists(basepipeName + val_pipe):
        # pipes exist, we should ask for the vars
        with open(basepipeName + comm_pipe, "wb") as file:
            file.write(b'REC\n')

        line = b""
        with open(basepipeName + val_pipe, "rb") as file:
            while True:
                tmp = file.read(1024 * 1024 * 1024)
                end = tmp[-7:]
                if end == b"0000000":
                    line += tmp[:-7]
                    break
                else:
                    line += tmp

        content = dill.loads(line)
    return content


def tidy_up(basepipeName):
    try:
        if os.path.exists(basepipeName + val_pipe):
            os.unlink(basepipeName + val_pipe)
        if os.path.exists(basepipeName + comm_pipe):
            os.unlink(basepipeName + comm_pipe)
    except:
        print("error tidy up")
