#!/bin/bash

#SBATCH --ntasks=1
#SBATCH --time=12:00:00
#SBATCH --job-name=parMar_bench
#SBATCH --cpus-per-task=16
#SBATCH --mem=480G
#SBATCH --cpu-freq=2000000
#SBATCH --exclusive

ml GCCcore/10.3.0 Python
./bench.sh
