import os
import stat
import multiprocessing
from balancedDistributionIterator import BalancedDistributionIterator
import importlib
import logging
import sys
import numpy as np
import dill
import ast

def generate_random_dict(num_elements, element_size):
    result_dict = {}
    if isinstance(element_size, int):
        array_sizes = [element_size] * num_elements

    for i in range(num_elements):
        result_dict[i] = np.random.rand(array_sizes[i])

    return result_dict

def compare_dicts(dict1, dict2):
    if len(set(dict1.keys()).difference(dict2.keys())) != 0:
        return False

    for key in dict1:
        if not np.array_equal(dict1[key], dict2[key]):
            return False

    return True
