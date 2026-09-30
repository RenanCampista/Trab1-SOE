import httpx
import pytest
from pydantic import SecretStr

from aeromonitor.opensky import OpenSky, RateLimited


def mocked_api(settings, handler):
    """Cria um cliente cuja comunicação HTTP é respondida pelo handler de teste."""
    api = OpenSky(settings)
    api.client.close()
    api.client = httpx.Client(transport=httpx.MockTransport(handler))
    return api


def test_anonymous_empty_response(settings):
    """Verifica consulta geográfica anônima com resposta sem aeronaves."""

    def handler(request):
        """Valida a requisição anônima e devolve uma resposta sem estados."""
        assert "Authorization" not in request.headers
        assert "lamin" in request.url.params
        return httpx.Response(200, json={"time": 1000, "states": None})

    api = mocked_api(settings, handler)
    try:
        assert api.fetch()["states"] is None
    finally:
        api.close()


def test_rate_limit_honors_server_wait(settings):
    """Verifica que HTTP 429 preserva o prazo de espera enviado pelo servidor."""
    api = mocked_api(
        settings,
        lambda _: httpx.Response(429, headers={"X-Rate-Limit-Retry-After-Seconds": "7200"}),
    )
    try:
        with pytest.raises(RateLimited) as exc:
            api.fetch()
        assert exc.value.seconds == 7200
    finally:
        api.close()


def test_token_refresh_after_401(settings):
    """Verifica a renovação do token e a repetição da consulta após HTTP 401."""
    settings.opensky_client_id = "test-client"
    settings.opensky_client_secret = SecretStr("test-secret")
    count = {"tokens": 0, "queries": 0}

    def handler(request):
        """Simula emissão de tokens, rejeição inicial e sucesso com o novo Bearer."""
        if request.method == "POST":
            count["tokens"] += 1
            return httpx.Response(
                200, json={"access_token": str(count["tokens"]), "expires_in": 1800}
            )
        count["queries"] += 1
        if count["queries"] == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer 2"
        return httpx.Response(200, json={"states": []})

    api = mocked_api(settings, handler)
    try:
        assert api.fetch() == {"states": []}
        assert count == {"tokens": 2, "queries": 2}
    finally:
        api.close()
