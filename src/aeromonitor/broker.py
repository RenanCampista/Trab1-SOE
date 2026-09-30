"""Publicação confirmada e consumo com commit explícito."""

from confluent_kafka import Consumer, KafkaException, Producer
from pydantic import BaseModel

from aeromonitor.config import Settings

POSITIONS = "aircraft.positions"
ALERTS = "aircraft.alerts"
DERIVED = "aircraft.derived"
COLLECTIONS = "aircraft.collections"


class Publisher:
    def __init__(self, settings: Settings):
        """Configura um produtor Kafka idempotente com prazo de entrega de 30 s."""
        self.producer = Producer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "enable.idempotence": True,
                "acks": "all",
                "delivery.timeout.ms": 30000,
            }
        )

    def send(self, topic: str, key: str, event: BaseModel):
        """Publica o evento em JSON com a chave fornecida e aguarda confirmação.

        Levanta RuntimeError se houver mensagens pendentes após a espera ou
        KafkaException se o callback informar falha na entrega.
        """
        errors = []

        def delivered(error, _message):
            """Guarde uma falha de entrega para propagá-la após o flush."""
            if error:
                errors.append(error)

        self.producer.produce(topic, key=key, value=event.model_dump_json(), on_delivery=delivered)
        if self.producer.flush(35): # Levanta RuntimeError se houver mensagens pendentes após 35 s
            raise RuntimeError("Publicação Kafka não confirmada no prazo")
        if errors:
            raise KafkaException(errors[0])


def consumer(settings: Settings, group: str, topics: list[str]) -> Consumer:
    """Cria um consumidor inscrito nos tópicos, com confirmação manual de offsets.

    Sem offset salvo para o grupo, começa no primeiro registro ainda retido.
    O chamador deve confirmar o processamento e fechar o consumidor.
    """
    client = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
        }
    )
    client.subscribe(topics)
    return client
