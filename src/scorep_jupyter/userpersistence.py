import os
import ast
import astunparse
import inspect
import shutil
import dill
import sys

'''
Note: general limitation
changes in modules can not be persisted since pickling/shelving modules is not allowed
this might be fixed by using shared memory
'''


def save_user_definitions(code):
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

    code_prev = []

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
    # variables = sorted({node.id for node in ast.walk(root) if isinstance(node, ast.Name)})
    variables = set()
    for node in ast.walk(root):
        # assignment nodes can include attributes, therefore go over all targets and check for attribute nodes
        if isinstance(node, ast.Assign) or isinstance(node, ast.AnnAssign):
            for el in node.targets:
                for target_node in ast.walk(el):
                    if isinstance(target_node, ast.Name):
                        variables.add(target_node.id)

    return variables


def save_user_variables(globs, variables, tmp_user_vars_file):

    prior_variables = load_user_variables(tmp_user_vars_file)
    user_variables = {k: v for k, v in globs.items() if str(k) in variables}
    user_variables = {**prior_variables, **user_variables}
    # TODO: use shared memory
    if bool(user_variables):
        with open(tmp_user_vars_file, "wb") as dill_file:
            # d = shelve.open(tmp_user_vars_file)
            for el in user_variables.keys():
                # if possible, exchange class of the object here with the class that is stored for persistence. This is
                # valid since the classes should be the same and this does not affect the objects attribute dictionary
                non_persistent_class = user_variables[el].__class__.__name__
                if non_persistent_class in globals().keys():
                    user_variables[el].__class__ = globals()[non_persistent_class]
                # d[el] = user_variables[el]
            dill.dump(user_variables, dill_file)
            # d.close()


def load_user_variables(tmp_user_vars_file):
    user_variables = {}
    # TODO: use shared memory

    if os.path.isfile(tmp_user_vars_file):
        with open(tmp_user_vars_file, "rb") as dill_file:
            user_variables = dill.load(dill_file)

    return user_variables


def tidy_up(tmp_user_vars_file):
    try:
        if os.path.isfile(tmp_user_vars_file):
            os.remove(tmp_user_vars_file)
    except:
        print("error tidy up")
