class LedgerError(ValueError):
    def __init__(self, code: str, message: str, reason: str | None = None, **details):
        super().__init__(message)
        self.code, self.message, self.reason, self.details = (
            code,
            message,
            reason,
            details,
        )

    def as_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "reason": self.reason,
            "field_errors": {},
            "related_transaction_ids": [],
            **self.details,
        }
