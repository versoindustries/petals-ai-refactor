import threading
import time

import pytest
import torch
from hivemind import DHT, get_logger
from test_utils import *

from petals.client import RemoteSequenceManager, RemoteSequential
from petals.client.remote_model import DistributedBloomConfig
from petals.data_structures import UID_DELIMITER

logger = get_logger(__file__)


@pytest.mark.forked
@pytest.mark.parametrize("mode", ["fastest", "random"])
def test_sequence_manager_basics(mode: str):
    config = DistributedBloomConfig.from_pretrained(MODEL_NAME, initial_peers=INITIAL_PEERS)
    dht = DHT(initial_peers=config.initial_peers, client_mode=True, start=True)
    sequential = RemoteSequential(config, dht)
    shutdown_evt = threading.Event()

    # test RemoteSequential with lossy compression
    block_uids = [f"{config.dht_prefix}{UID_DELIMITER}{i}" for i in range(config.n_layer)]
    sequential = RemoteSequential(
        config,
        dht,
        sequence_manager=TestSequenceManager(dht, block_uids, sequential.p2p, _was_shut_down=shutdown_evt, start=True),
    )

    sequence = sequential.sequence_manager.make_sequence(mode=mode)
    assert all(sequence[i].peer_id != sequence[i + 1].peer_id for i in range(len(sequence) - 1))

    assert sequential.sequence_manager.is_alive()
    assert sequential.sequence_manager._thread.ready.is_set()
    assert not shutdown_evt.is_set()
    sequential(torch.randn(1, 2, config.hidden_size), torch.ones((1, 2)))

    sequential.sequence_manager.shutdown()
    del sequential
    time.sleep(1)

    assert shutdown_evt.is_set()


class TestSequenceManager(RemoteSequenceManager):
    """A sequence manager that signals if it was shut down"""

    def __init__(self, *args, _was_shut_down: threading.Event, **kwargs):
        super().__init__(*args, **kwargs)
        self._was_shut_down = _was_shut_down

    def shutdown(self):
        super().shutdown()
        assert not self.is_alive()
        self._was_shut_down.set()
