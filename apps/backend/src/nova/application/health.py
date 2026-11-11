from dataclasses import dataclass


@dataclass
class HealthService:
    ready: bool = False
