"""communicator birim testleri: çok abone, sıra numarası, veri kopyalama."""

from __future__ import annotations

import threading

import numpy as np

from libs.communicator import orb_advertise, orb_copy, orb_publish, orb_subscribe
from libs.communicator.topics import Frame


def test_advertise_same_name_returns_same_topic() -> None:
    assert orb_advertise("t_same") is orb_advertise("t_same")


def test_copy_before_any_publish_returns_none() -> None:
    sub = orb_subscribe(orb_advertise("t_empty"))
    assert orb_copy(sub) == (False, None)


def test_publish_increments_seq_and_updates_flag() -> None:
    topic = orb_advertise("t_seq")
    sub = orb_subscribe(topic)

    assert orb_publish(topic, 1)
    assert topic.seq == 1
    assert orb_copy(sub) == (True, 1)
    assert orb_copy(sub) == (False, 1)

    orb_publish(topic, 2)
    orb_publish(topic, 3)
    assert topic.seq == 3
    assert orb_copy(sub) == (True, 3)


def test_multiple_subscribers_do_not_reset_each_other() -> None:
    topic = orb_advertise("t_multi")
    sub_a = orb_subscribe(topic)
    sub_b = orb_subscribe(topic)

    orb_publish(topic, "x")
    assert orb_copy(sub_a) == (True, "x")
    assert orb_copy(sub_b) == (True, "x")
    assert orb_copy(sub_a) == (False, "x")
    assert orb_copy(sub_b) == (False, "x")


def test_late_subscriber_sees_existing_data_as_new() -> None:
    topic = orb_advertise("t_late")
    orb_publish(topic, 42)
    assert orb_copy(orb_subscribe(topic)) == (True, 42)


def test_publish_none_topic_returns_false() -> None:
    assert orb_publish(None, 1) is False


def test_publisher_cannot_modify_published_ndarray() -> None:
    topic = orb_advertise("t_array")
    sub = orb_subscribe(topic)
    image = np.zeros((2, 2), dtype=np.uint8)

    orb_publish(topic, Frame(image=image, timestamp_ms=0))
    image[0, 0] = 255

    _, frame = orb_copy(sub)
    assert frame.image[0, 0] == 0


def test_subscriber_cannot_modify_other_subscribers_data() -> None:
    topic = orb_advertise("t_isolation")
    sub_a = orb_subscribe(topic)
    sub_b = orb_subscribe(topic)
    orb_publish(topic, Frame(image=np.zeros((2, 2), dtype=np.uint8), timestamp_ms=0))

    _, frame_a = orb_copy(sub_a)
    frame_a.image[0, 0] = 255
    _, frame_b = orb_copy(sub_b)
    assert frame_b.image[0, 0] == 0


def test_concurrent_publish_counts_every_publish() -> None:
    topic = orb_advertise("t_concurrent")
    publishes_per_thread = 1000
    thread_count = 4

    def publisher() -> None:
        for i in range(publishes_per_thread):
            orb_publish(topic, i)

    threads = [threading.Thread(target=publisher) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert topic.seq == publishes_per_thread * thread_count
