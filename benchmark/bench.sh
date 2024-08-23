#!/bin/bash

# 1500 elements, each containing 2^k 8 byte entries, i.e. 1500 * 2*23 * 8 = 96GB
num_elements=1500
# marshallers for the benchmark, number of CPUs is automatically extracted
marshallers=("parallel_1" "parallel_2" "parallel_4" "parallel_8" "parallel_16")
# operations are:
# dump (measuring dump only)
# dumpload (measuring dump and load and checking if dumped and loaded data are identically for disk mode,
# for in-memory, use dumploadcheckconsistency operation)
operations=("dumpload" "dump")
# modes are memory and/or disk
modes=("memory" "disk")

# the dumploadcheckconsistency operation checks whether dumped and loaded data are identically for the in-memory
# dumpload operation. It's not valid and required for disk mode and will fail. time measurements for this
# operation are not useful, since they contain the consistency check, use usual dumpload operation for time
# measurements
#operations=("dumploadcheckconsistency")
#modes=("memory")

for marshaller in "${marshallers[@]}"; do
    for mode in "${modes[@]}"; do
        for operation in "${operations[@]}"; do
            # Balanced setup
            balanced_file="${marshaller}_${operation}_balanced_${mode}.txt"
            echo "Array Size, Average Time" > "${balanced_file}"
            for k in {21..23}; do
                array_size=$((2**k))
                total_time=0
                arr=()
                for (( i=0; i<10; i++ )); do
                    run_time=$(python main.py "$marshaller" "$operation" "$mode" "$num_elements" "$array_size")
                    total_time=$(echo "$total_time + $run_time" | bc)
                    arr+=($run_time)
                done
                # return size of data and time measurements per iteration
                # for dump: dump time (disk and in memory)
                # for dumpload: overall time;dump time (disk)
                # for dumpload: overall time (in memory) because in-memory needs reader and writer connected to pipe, so it is indistinguishable
                echo "${array_size}, ${arr[@]}" >> "${balanced_file}"
            done
        done
    done
done
