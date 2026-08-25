"""CoatiPay SDK errors."""


class CoatiPaySDKError(Exception):
    """Raised when the CoatiPay API returns an error."""

    def __init__(self, code: str, message: str, param: str | None, doc_url: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.param = param
        self.doc_url = doc_url


# Backwards-compatible alias.
CoatiPayError = CoatiPaySDKError
