import dill


def save_user_variables(globs, variables, filename):
    user_variables = {k: v for k, v in globs.items() if k in variables}
    for el in user_variables.keys():
        # if possible, exchange class of the object here with the class that is stored for persistence. This is
        # valid since the classes should be the same and this does not affect the objects attribute dictionary
        non_persistent_class = user_variables[el].__class__.__name__
        if non_persistent_class in globals().keys():
            user_variables[el].__class__ = globals()[non_persistent_class]

    if user_variables:
        vars_dump = open(filename, 'wb+')
        dill.dump(user_variables, vars_dump)
        vars_dump.close()
