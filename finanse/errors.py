class ValidationError(Exception):
    """Dane nie przeszły walidacji; `errors` to komunikaty dla użytkownika."""

    def __init__(self, errors):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))
