from dataclasses import dataclass
from typing import Any, Dict, Generator

from pydynaa import EventExpression
from squidasm.sim.stack.program import ProgramContext, ProgramMeta
from squidasm.util import create_two_node_network

from qkd_program import QkdProgram

class BobProgram(QkdProgram):
    PEER = "Alice"

    @property
    def meta(self) -> ProgramMeta:
        return ProgramMeta(
            name="bob_program",
            csockets=[self.PEER],
            epr_sockets=[self.PEER],
            max_qubits=1,
        )

    def run(self, context: ProgramContext) -> Generator[EventExpression, None, Dict[str, Any]]:
        csocket = context.csockets[self.PEER]
        pairs_info = yield from self._distribute_states(context, False)
        self.logger.info("Finished distributing states")

        csocket.send(self.ALL_MEASURED)
        pairs_info = yield from self._filter_bases(csocket, pairs_info, False)
        pairs_info, error_rate = yield from self._estimate_error_rate(
            csocket, pairs_info, self._num_test_bits, False
        )
        self.logger.info(f"Estimates error rate: {error_rate}")

        raw_key = pairs_info
        self.logger.info(f"Prepared Raw key: {raw_key}")

        return raw_key
