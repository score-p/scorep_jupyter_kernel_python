import sys
from collections.abc import Iterable


class BalancedDistributionIterator(Iterable):
    def __init__(self, obj, n_bins):
        self.obj = obj
        self.n_bins = n_bins
        self.bins, self.keys_or_indices = self._balanced_distribution(obj)
        self.current_bin = 0

    def _balanced_distribution(self, obj):
        if isinstance(obj, dict):
            size_items = sorted(
                (sys.getsizeof(value), key) for key, value in obj.items()
            )
            bins = [set() for _ in range(self.n_bins)]
        elif isinstance(obj, list):
            size_items = sorted(
                (sys.getsizeof(value), index)
                for index, value in enumerate(obj)
            )
            bins = [[] for _ in range(self.n_bins)]
        else:
            raise TypeError("Object must be a dictionary or a list")

        sizes = [0] * self.n_bins
        for size, key_or_index in reversed(size_items):
            min_index = sizes.index(min(sizes))
            (
                bins[min_index].add(key_or_index)
                if isinstance(obj, dict)
                else bins[min_index].append(key_or_index)
            )
            sizes[min_index] += size

        return bins, [item for _, item in size_items]

    def __iter__(self):
        return self

    def __next__(self):
        if self.current_bin >= self.n_bins:
            raise StopIteration

        if isinstance(self.obj, dict):
            subdict = {k: self.obj[k] for k in self.bins[self.current_bin]}
            self.current_bin += 1
            return subdict
        elif isinstance(self.obj, list):
            sublist = [self.obj[i] for i in self.bins[self.current_bin]]
            self.current_bin += 1
            return sublist
