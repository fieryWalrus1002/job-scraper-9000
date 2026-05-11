from abc import ABC, abstractmethod

from ..models import JobPosting


class BaseScraper(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str: ...

    @abstractmethod
    def scrape(self) -> list[JobPosting]: ...

    def describe(self) -> dict:
        return {"source": self.source_name}
