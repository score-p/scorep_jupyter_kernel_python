from common import *
import time
import shutil
import sys
import subprocess
import numpy
import dill
# main.py parallel_4 dump memory 100 1000 (2000)

marshaller_name = sys.argv[1]
operation = sys.argv[2]
mode = sys.argv[3]
num_elements = int(sys.argv[4])

basepath_dump = "/tmp/"

if len(sys.argv) == 6:
    # balanced
    array_size = int(float(sys.argv[5]))
    dict_ = generate_random_dict(num_elements, array_size)

if marshaller_name == 'dill':
    # always uses disk, in-memory not supported
    start_time = time.time()
    with open(f'{basepath_dump}dill_dump.pkl', 'wb+') as fd:
        dill.dump(dict_, fd)
    dump_time = time.time() - start_time
    if operation == 'dumpload':
        with open('{basepath_dump}dill_dump.pkl', 'rb') as fd:
            loaded_dict = dill.load(fd)
        execution_time = time.time() - start_time
        assert(compare_dicts(dict_, loaded_dict))
        print(str(execution_time) + ";" + str(dump_time))
    if os.path.exists(f'{basepath_dump}dill_dump.pkl'):
        os.remove(f'{basepath_dump}dill_dump.pkl')


elif 'parallel' in marshaller_name:
    par = int(marshaller_name.split('_')[1])
    os.environ["PARALLEL_MARSHALL_NWORKERS"]=str(par)
    import parallel_marshall

    if mode == 'disk':
        start_time = time.time()
        with os.fdopen(os.open(f'{basepath_dump}parmar_dump', os.O_WRONLY | os.O_CREAT), 'wb+') as fd:
            parallel_marshall.dump(dict_, fd)
        dump_time = time.time() - start_time
        if operation == 'dumpload':
            with os.fdopen(os.open(f'{basepath_dump}parmar_dump', os.O_RDONLY), 'rb') as fd:
                loaded_dict = parallel_marshall.load(fd)
            execution_time = time.time() - start_time
            assert(compare_dicts(dict_, loaded_dict))
            print(str(execution_time) + ";" + str(dump_time))
        if operation == 'dump':
            print(dump_time)
        for i in range(0,par):
            os.unlink(f"{basepath_dump}parmar_dump_{i}")
        os.unlink(f'{basepath_dump}parmar_dump')


    elif mode=='memory':
        start_time = time.time()
        os.mkfifo(f'{basepath_dump}parmar_dump')
        # to keep dump and dumpload operations in the same procedure, we create the pipes here for both operations
        # the original parallel marshalling creates the subpipes in it's dump() operation buth without the
        # original loading operation (for the dump benchmark only), we would not be able to connect
        # to the several subpipes
        for i in range(0,par):
            os.mkfifo(f"{basepath_dump}parmar_dump_{i}")
            # depending on dump or dumpload, either read into a buffer or do the unmarshalling
            if operation == 'dump':
                cmd=f"import os\nwith os.fdopen(os.open('{basepath_dump}parmar_dump_{i}', os.O_RDONLY), 'rb') as fd:\n    fd.read()"
                subprocess.Popen(["python3", "-c", cmd])
        if operation == 'dump':
            cmd=f"import os\nwith os.fdopen(os.open('{basepath_dump}parmar_dump', os.O_RDONLY), 'rb') as fd:\n    fd.read()"
            subprocess.Popen(["python3", "-c", cmd])
        if 'dumpload' in operation:
            cmd=(
                "import os\n"
                "from numpy import array\n"
                "from common import *\n"
                "import dill\n"
                f"os.environ['PARALLEL_MARSHALL_NWORKERS']=str({par})\n"
                "import parallel_marshall\n"
                f"with os.fdopen(os.open('{basepath_dump}parmar_dump', os.O_RDONLY), 'rb') as file:\n"
                "    obj=parallel_marshall.load(file)\n"
            )
            # check the consistency for dumpload operation, write loaded data to file...
            if 'checkconsistency' in operation:
                cmd += "    with open('tmpconsistencytest', 'wb') as f:\n        dill.dump(obj, f)\n"
            with open(f"myscripttmp.py", 'w+') as file:
                file.write(cmd)
            sb = subprocess.Popen([sys.executable, f"myscripttmp.py"])
        with os.fdopen(os.open(f'{basepath_dump}parmar_dump', os.O_WRONLY | os.O_CREAT), 'wb') as file:
            parallel_marshall.dump(dict_, file)
        dump_time = time.time() - start_time
        if operation == 'dumploadcheckconsistency':
            sb.wait()
            # for checking consistency, wait till loaded data was written, read the data here again and compare
            with open('tmpconsistencytest', 'rb') as f:
                loaded_dict = dill.load(f)
                assert(compare_dicts(dict_, loaded_dict))
        if operation == 'dump':
            for i in range(0,par):
                os.unlink(f"{basepath_dump}parmar_dump_{i}")
        if 'dumpload' in operation:
            for i in range(0,par):
                os.unlink(f"{basepath_dump}parmar_dump_{i}")
            os.unlink("myscripttmp.py")
        if operation == 'dumploadcheckconsistency':
            os.unlink('tmpconsistencytest')
        os.unlink(f'{basepath_dump}parmar_dump')
        print(dump_time)


