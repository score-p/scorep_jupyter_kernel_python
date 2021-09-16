import re
import string
import os
import ast
import shelve
import pickle
import glob
from tmp_userpersistency import *

def save_user_definitions(code):

    lines_of_code = code.split('\n')
    
    #keep only user defined classes, methods and imports
    code_to_keep = list()
    keep_code = False
    indent_user_definition = -1
    remove_indent=False
    for line in lines_of_code:
        if re.match(r'.*(def|class|import)\s+.+',line):
            #it is important to know, that the indent was caused by def or class
            if indent_user_definition >= (len(line) - len(line.lstrip())) or indent_user_definition == -1:
                if indent_user_definition == -1:
                    remove_indent = True
                indent_user_definition = len(line) - len(line.lstrip())
                keep_code = True
        elif len(line.lstrip()) == 0:
            #skip empty lines
            continue
        elif indent_user_definition >= (len(line) - len(line.lstrip())) and keep_code:
            keep_code = False
            indent_user_definition = -1
        if keep_code:
            if remove_indent:
                line = line[indent_user_definition:] 
            code_to_keep.append(line)
    
    
    if os.path.isfile(".userpersistency"):
        #now merge with usercode from previous cells
        functions_content_str = ""
        with open(".userpersistency", "r") as f:
            functions_content_str = f.read()
        #open previous defined functions
        functions_content = ast.literal_eval(functions_content_str)
        
        #store index of lines to delete from previous definitions sinces it is overwritten by new code
        lines_to_delete_from_old = list()
        delete_lines = False
        indent_user_definition = -1
        for index in range(0,len(functions_content)):
            line = functions_content[index]
            if re.match(r'.*(def|class|import)\s+.+',line):
                if indent_user_definition >= (len(line) - len(line.lstrip())) or indent_user_definition == -1:
                    indent_user_definition = len(line) - len(line.lstrip())
                    if line in code_to_keep:
                        delete_lines = True
                    else:
                        delete_lines = False
            if delete_lines:
                lines_to_delete_from_old.append(index)

        #delete lines that are overwritten by new code
        lines_to_delete_from_old.reverse()
        for idx in lines_to_delete_from_old:
            functions_content.pop(idx)

        #combine old and new code
        functions_content.extend(code_to_keep)
        code_to_keep = functions_content
    
    #write out
    #TODO: someday make one file here
    with open(".userpersistency", "w") as f:
        f.write(str(code_to_keep))
    with open("tmp_userpersistency.py", "w") as f:
        f.write(('\n'.join(ast.literal_eval(str(code_to_keep))))+'\n')


def get_user_variables_from_code(code):
    lines_of_code = code.split('\n')
    lines_of_code = list(filter(lambda x: "=" in str(x), lines_of_code))
    lines_of_code = [''.join((str(x).split('=')[0]).split()) for x in lines_of_code]
    variables_tmp = []
    for line in lines_of_code:
        variables_tmp.extend(str(line).split(','))
    variables = [var.split(".")[0] for var in variables_tmp]
    return variables


def save_user_variables(globs, variables):
    prior_variables = load_user_variables()
    user_variables = {k: v for k, v in globs.items() if str(k) in variables}
    user_variables = {**prior_variables, **user_variables}
    if bool(user_variables):
        d = shelve.open(".variables")
        for el in user_variables.keys():
            #if possible, exchange class of the object here with the class that is stored for persistency. 
            #This is valid since the classes should be the same and this does not affect the objects attribute dictionary
            non_persistent_class = user_variables[el].__class__.__name__
            if non_persistent_class in globals().keys():
                user_variables[el].__class__ = globals()[non_persistent_class]
            d[el] = user_variables[el]
        d.close()


def load_user_variables():
    user_variables = {}
    d = shelve.open(".variables")
    klist = list(d.keys())
    for key in klist:
        user_variables[key] = d[key]   
    d.close()
    return user_variables
    

def tidy_up():
    with open("tmp_userpersistency.py", "w") as f:
        pass
    files_to_remove = [glob.glob(e) for e in ['.variables*', '.userpersistency']]
    files_to_remove = [item for sublist in files_to_remove for item in sublist]
    for file in files_to_remove:
        try:
            os.remove(file)
        except:
            print("Error while deleting file : ", file)
