"""HTTP com OAuth2 opcional, timeout e indicação de espera após rate limit."""

import time

import httpx

from aeromonitor.config import Settings

API_URL = "https://opensky-network.org/api/states/all"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)


class RateLimited(Exception):
    def __init__(self, seconds: float):
        """Registre o tempo de espera, em segundos, antes de consultar novamente."""
        self.seconds = seconds
        super().__init__(f"Limite da OpenSky; aguardar {seconds:.0f} segundos")


class OpenSky:
    def __init__(self, settings: Settings):
        """Prepare o cliente HTTP e o cache OAuth2 sem realizar consultas."""
        self.settings = settings
        self.client = httpx.Client(timeout=20, headers={"User-Agent": "aeromonitor-academic/0.1"})
        self.token: str | None = None
        self.expires_at = 0.0

    def close(self):
        """Feche o cliente HTTP e libere suas conexões."""
        self.client.close()

    def headers(self) -> dict[str, str]:
        """Retorne cabeçalhos anônimos ou Bearer, renovando o token se necessário.

        A renovação realiza uma requisição HTTP e propaga falhas de acesso.
        """
        if not self.settings.opensky_client_id:
            return {}
        if time.monotonic() >= self.expires_at:
            response = self.client.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.opensky_client_id,
                    "client_secret": self.settings.opensky_client_secret.get_secret_value(),
                },
            )
            response.raise_for_status()
            data = response.json()
            self.token = data["access_token"]
            self.expires_at = time.monotonic() + max(1, data.get("expires_in", 1800) - 60)
        return {"Authorization": f"Bearer {self.token}"}

    def fetch(self) -> dict:
        """Consulte os estados da região e retorne o JSON fornecido pela OpenSky.

        Renova o token e repete uma vez após HTTP 401 autenticado. Levanta
        RateLimited após HTTP 429; outras falhas HTTP ou de conexão são propagadas.
        """
        response = self.client.get(
            API_URL, params=self.settings.monitored_region().bounds(), headers=self.headers()
        )
        if response.status_code == 401 and self.settings.opensky_client_id:
            self.expires_at = 0
            response = self.client.get(
                API_URL, params=self.settings.monitored_region().bounds(), headers=self.headers()
            )
        if response.status_code == 429:
            raw = response.headers.get("X-Rate-Limit-Retry-After-Seconds", "3600")
            try:
                seconds = max(60, float(raw))
            except ValueError:
                seconds = 3600
            raise RateLimited(seconds)
        response.raise_for_status()
        return response.json()
