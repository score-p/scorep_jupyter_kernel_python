**Skripts used to run internal benchmark of parallel marshalling and in-memory communication versus file-based communication**.

- Use `bench.sh` to start the benchmark. It defines the marshalers (e.g. parallel_1, parallel_2,...parallel_16),
the modes (memory, disk) and the operations (dump, dumpload) for the benchmark. Modify them if necessary. Output one file for each experiment.
- On a slurm-based system, you can use `run_bench.sbatch` to submit the job.
- `common.py` creates the data for the benchmark and provides a method to compare dumped and loaded data
- `balancedDistributionIterator.py` and `parallel_marshall.py` are the original files used for parallel marshalling.
Note: There is a minor change to `parallel_marshall.py` (pipe creation in the main routine instead in the marshaller) to unify the dump and dumpload operations for the benchmark.
This does not affect the measurements.
- `main.py` runs one iteration of the benchmark, i.e. data creation, marshaller initialization, dumping, loading (for dumpload), with time measurements.
- `displaydata.ipynb` reads the output files and displays the data.
