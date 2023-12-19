import ast
import astunparse

def save_variables_values(globs, variables, filename):
    """
    Dump values of given variables into the file.
    """
    import dill
    user_variables = {k: v for k, v in globs.items() if k in variables}
    for el in user_variables.keys():
        # if possible, exchange class of the object here with the class that is stored for persistence. This is
        # valid since the classes should be the same and this does not affect the objects attribute dictionary
        non_persistent_class = user_variables[el].__class__.__name__
        if non_persistent_class in globals().keys():
            user_variables[el].__class__ = globals()[non_persistent_class]
    with open(filename, 'wb+') as file:
        dill.dump(user_variables, file)

def extract_definitions(code):
    """
    Extract imported modules and definitions of classes and functions from the code block.
    """
    # can't use in kernel as import from userpersistence:
    # self-reference error during dill dump of notebook
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

def extract_variables_names(code):
    """
    Extract user-assigned variables from code.
    Unlike dir(), nothing coming from the imported modules is included.
    Might contain non-variables as well from assignments, which are later filtered out in save_variables_values.
    """
    root = ast.parse(code)

    variables = set()
    for node in ast.walk(root):
        # assignment nodes can include attributes, therefore go over all targets and check for attribute nodes
        if isinstance(node, ast.Assign):
            for el in node.targets:
                for target_node in ast.walk(el):
                    if isinstance(target_node, ast.Name):
                        variables.add(target_node.id)
        elif isinstance(node, ast.AnnAssign):
            for target_node in ast.walk(node.target):
                if isinstance(target_node, ast.Name):
                    variables.add(target_node.id)

    return variables
