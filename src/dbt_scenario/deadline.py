import math
import time

from dbt_scenario import errors


class Deadline:
    def __init__(
        self, seconds: float, reason: str, parent: "Deadline | None" = None
    ) -> None:
        self.expires = time.monotonic() + seconds
        self.reason = reason
        self.parent = parent

    def remaining(self) -> float:
        parent_remaining = (
            self.parent.remaining() if self.parent else float("inf")
        )
        remaining = self.expires - time.monotonic()
        if remaining <= 0:
            raise errors.ScenarioError(self.reason)
        return min(remaining, parent_remaining)

    def check(self) -> None:
        self.remaining()

    def milliseconds(self) -> int:
        return max(1, math.ceil(self.remaining() * 1000))

    def expired_reason(self) -> str:
        try:
            self.check()
        except errors.ScenarioError as error:
            return error.code
        return self.reason
