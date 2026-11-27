"""Communicator modülü: task'lar arası thread-safe yayınla/abone ol (nORB) altyapısı."""

from __future__ import annotations

import copy
import dataclasses
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

TAG = "Communicator"
log = logging.getLogger(TAG)

_registry: dict[str, OrbTopic] = {}
_registry_lock = threading.Lock()


@dataclass
class OrbTopic:
    """Tek bir topic'in son verisini ve sıra numarasını tutar."""

    name: str
    data: Any = None
    seq: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass
class OrbSubscription:
    """Bir task'ın bir topic'e aboneliği. Abonenin gördüğü son sıra numarasını saklar."""

    topic: OrbTopic
    last_seq: int = 0


def orb_advertise(name: str) -> OrbTopic:
    """Topic'i oluşturur. Aynı isimle tekrar çağrılırsa mevcut topic'i döner.

    Args:
        name: Topic adı (topics.py içindeki sabitlerden biri).

    Returns:
        Topic handle'ı.
    """
    with _registry_lock:
        topic = _registry.get(name)
        if topic is None:
            topic = OrbTopic(name=name)
            _registry[name] = topic
            log.debug("Topic oluşturuldu: %s", name)
        return topic


def orb_publish(topic: OrbTopic | None, data: Any) -> bool:
    """Veriyi kopyalayarak topic'e yayınlar ve sıra numarasını bir artırır.

    Args:
        topic: Yayın yapılacak topic. Advertise edilmemişse (None) yayın yapılmaz.
        data: Yayınlanacak veri.

    Returns:
        Yayın başarılıysa True.
    """
    if topic is None:
        log.error("Advertise edilmemiş bir topic'e yayın denendi.")
        return False
    data_copy = _copy_data(data)
    with topic.lock:
        topic.data = data_copy
        topic.seq += 1
    return True


def orb_subscribe(topic: OrbTopic | None) -> OrbSubscription:
    """Topic'e yeni bir abonelik oluşturur. Her okuyan task kendi aboneliğini almalıdır.

    Args:
        topic: Abone olunacak topic.

    Returns:
        Abonelik handle'ı.

    Raises:
        ValueError: Topic advertise edilmemişse.
    """
    if topic is None:
        raise ValueError("Advertise edilmemiş bir topic'e abone olunamaz.")
    return OrbSubscription(topic=topic)


def orb_copy(sub: OrbSubscription) -> tuple[bool, Any]:
    """Topic'in son verisinin bir kopyasını döner.

    Args:
        sub: orb_subscribe ile alınmış abonelik.

    Returns:
        (abonenin son okumasından beri yeni veri geldi mi, son veri veya None)
    """
    topic = sub.topic
    with topic.lock:
        updated = topic.seq != sub.last_seq
        sub.last_seq = topic.seq
        data = topic.data
    # Birden çok abone aynı nesneyi okuyabildiği için okurken de kopyalanır.
    # Böylece bir abone (ör. overlay çizen UI) diğerinin verisini bozamaz.
    return updated, _copy_data(data)


def _copy_data(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, np.ndarray):
        return data.copy()
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        array_fields = {
            f.name: getattr(data, f.name).copy()
            for f in dataclasses.fields(data)
            if isinstance(getattr(data, f.name), np.ndarray)
        }
        return dataclasses.replace(data, **array_fields)
    return copy.copy(data)
