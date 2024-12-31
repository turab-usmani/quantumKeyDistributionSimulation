import abc
import random
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Tuple
from squidasm.sim.stack.program import Program
from squidasm.sim.stack.common import LogManager
from squidasm.sim.stack.csocket import ClassicalSocket
from squidasm.sim.stack.program import Program, ProgramContext
from netqasm.sdk.classical_communication.message import StructuredMessage
from pydynaa import EventExpression
from squidasm.util import create_two_node_network

@dataclass
class PairInfo:
    """Information about a generated pair in the QKD protocol."""
    index: int
    basis: int
    outcome: int
    same_basis: Optional[bool] = None
    test_outcome: Optional[bool] = None
    same_outcome: Optional[bool] = None

class QkdProgram(Program, abc.ABC):
    PEER: str
    ALL_MEASURED = "All qubits measured"

    def __init__(self, num_epr: int, num_test_bits: int = None):
        self._num_epr = num_epr
        self._num_test_bits = num_epr // 4 if num_test_bits is None else num_test_bits
        self._buf_msgs = []
        self.logger = LogManager.get_stack_logger(self.__class__.__name__)

    def _distribute_states(
        self, context: ProgramContext, is_init: bool
    ) -> Generator[EventExpression, None, List[PairInfo]]:
        conn = context.connection
        epr_socket = context.epr_sockets[self.PEER]
        results = []

        for i in range(self._num_epr):
            basis = random.randint(0, 1)
            q = epr_socket.create_keep(1)[0] if is_init else epr_socket.recv_keep(1)[0]
            if basis == 1:
                q.H()
            m = q.measure()
            yield from conn.flush()
            results.append(PairInfo(index=i, outcome=int(m), basis=basis))

        return results

    @staticmethod
    def _filter_bases(
        socket: ClassicalSocket, pairs_info: List[PairInfo], is_init: bool
    ) -> Generator[EventExpression, None, List[PairInfo]]:
        bases = [(i, pair.basis) for i, pair in enumerate(pairs_info)]
        if is_init:
            socket.send_structured(StructuredMessage("Bases", bases))
            remote_bases = (yield from socket.recv_structured()).payload
        else:
            remote_bases = (yield from socket.recv_structured()).payload
            socket.send_structured(StructuredMessage("Bases", bases))

        for (i, basis), (remote_i, remote_basis) in zip(bases, remote_bases):
            assert i == remote_i
            pairs_info[i].same_basis = basis == remote_basis

        return pairs_info

    @staticmethod
    def _estimate_error_rate(
        socket: ClassicalSocket,
        pairs_info: List[PairInfo],
        num_test_bits: int,
        is_init: bool,
    ) -> Generator[EventExpression, None, Tuple[List[PairInfo], float]]:
        if is_init:
            same_basis_indices = [pair.index for pair in pairs_info if pair.same_basis]
            test_indices = random.sample(
                same_basis_indices, min(num_test_bits, len(same_basis_indices))
            )
            for pair in pairs_info:
                pair.test_outcome = pair.index in test_indices

            test_outcomes = [(i, pairs_info[i].outcome) for i in test_indices]

            socket.send_structured(StructuredMessage("Test indices", test_indices))
            target_test_outcomes = (yield from socket.recv_structured()).payload
            socket.send_structured(StructuredMessage("Test outcomes", test_outcomes))
        else:
            test_indices = (yield from socket.recv_structured()).payload
            for pair in pairs_info:
                pair.test_outcome = pair.index in test_indices

            test_outcomes = [(i, pairs_info[i].outcome) for i in test_indices]

            socket.send_structured(StructuredMessage("Test outcomes", test_outcomes))
            target_test_outcomes = (yield from socket.recv_structured()).payload

        num_error = 0
        for (i1, t1), (i2, t2) in zip(test_outcomes, target_test_outcomes):
            assert i1 == i2
            if t1 != t2:
                num_error += 1
                pairs_info[i1].same_outcome = False
            else:
                pairs_info[i1].same_outcome = True

        return pairs_info, (num_error / num_test_bits)
