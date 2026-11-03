import pytest
from litellm import exceptions as litellm_errors

from app.providers.base import (
    ProviderRateLimitError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.providers.litellm_provider import map_provider_error

ARGS = {"message": "upstream said: <echoed request text>", "llm_provider": "gemini", "model": "m"}


@pytest.mark.parametrize(
    ("exc", "expected", "retryable"),
    [
        (litellm_errors.Timeout(**ARGS), ProviderTimeoutError, True),
        (litellm_errors.RateLimitError(**ARGS), ProviderRateLimitError, True),
        (litellm_errors.ServiceUnavailableError(**ARGS), ProviderUnavailableError, True),
        (litellm_errors.InternalServerError(**ARGS), ProviderUnavailableError, True),
        (litellm_errors.AuthenticationError(**ARGS), ProviderRejectedError, False),
        (litellm_errors.NotFoundError(**ARGS), ProviderRejectedError, False),
        (litellm_errors.BadRequestError(**ARGS), ProviderRejectedError, False),
        (RuntimeError("unexpected"), ProviderUnavailableError, True),
    ],
)
def test_litellm_errors_are_classified(
    exc: Exception, expected: type[Exception], retryable: bool
) -> None:
    mapped = map_provider_error(exc)

    assert type(mapped) is expected
    assert mapped.retryable is retryable


def test_mapped_message_never_echoes_the_provider_body() -> None:
    mapped = map_provider_error(litellm_errors.RateLimitError(**ARGS))

    assert "echoed request text" not in str(mapped)
    assert str(mapped) == "RateLimitError (status=429)"
