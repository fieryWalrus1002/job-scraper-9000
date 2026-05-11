from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from ..models import JobPosting

Q = TypeVar("Q")


class BaseScraper(ABC, Generic[Q]):
    query: Q

    @property
    @abstractmethod
    def source_name(self) -> str: ...

    @abstractmethod
    def scrape(self) -> list[JobPosting]: ...

    def describe(self) -> dict:
        return {"source": self.source_name}
