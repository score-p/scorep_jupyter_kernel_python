from abc import ABC, abstractmethod


class AbstractMonitor(ABC):

    @abstractmethod
    def parse_nodelist(self):
        pass

    @abstractmethod
    def start_monitor(self):
        pass

    @abstractmethod
    def end_monitor(self):
        pass
