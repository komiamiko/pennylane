# Copyright 2018-2021 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Tests for the controlled decompositions.
"""
import pytest

import numpy as np
import pennylane as qml
from pennylane.ops import ctrl_decomp_zyz
from pennylane.wires import Wires
from pennylane.ops.op_math.controlled_decompositions import ctrl_decomp_bisect_od, ctrl_decomp_bisect_md, ctrl_decomp_bisect_general, _convert_to_su2

cw5 = tuple(list(range(1, 1+n)) for n in range(2, 6))

class TestControlledDecompositionZYZ:
    """tests for qml.ops.ctrl_decomp_zyz"""

    def test_invalid_op_error(self):
        """Tests that an error is raised when an invalid operation is passed"""
        with pytest.raises(
            ValueError, match="The target operation must be a single-qubit operation"
        ):
            _ = ctrl_decomp_zyz(qml.CNOT([0, 1]), [2])

    su2_ops = [
        qml.RX(0.123, wires=0),
        qml.RY(0.123, wires=0),
        qml.RZ(0.123, wires=0),
        qml.Rot(0.123, 0.456, 0.789, wires=0),
    ]

    unitary_ops = [
        qml.Hadamard(0),
        qml.PauliZ(0),
        qml.S(0),
        qml.PhaseShift(1.5, wires=0),
        qml.QubitUnitary(
            np.array(
                [
                    [-0.28829348 - 0.78829734j, 0.30364367 + 0.45085995j],
                    [0.53396245 - 0.10177564j, 0.76279558 - 0.35024096j],
                ]
            ),
            wires=0,
        ),
        qml.DiagonalQubitUnitary(np.array([1, -1]), wires=0),
    ]

    @pytest.mark.parametrize("op", su2_ops + unitary_ops)
    @pytest.mark.parametrize("control_wires", ([1], [1, 2], [1, 2, 3]))
    def test_decomposition_circuit(self, op, control_wires, tol):
        """Tests that the controlled decomposition of a single-qubit operation
        behaves as expected in a quantum circuit"""
        dev = qml.device("default.qubit", wires=4)

        @qml.qnode(dev)
        def decomp_circuit():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            ctrl_decomp_zyz(op, Wires(control_wires))
            return qml.probs()

        @qml.qnode(dev)
        def expected_circuit():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            qml.ctrl(op, control_wires)
            return qml.probs()

        res = decomp_circuit()
        expected = expected_circuit()
        assert np.allclose(res, expected, atol=tol, rtol=0)

    @pytest.mark.parametrize("op", su2_ops)
    @pytest.mark.parametrize("control_wires", ([1], [1, 2], [1, 2, 3]))
    def test_decomposition_matrix(self, op, control_wires, tol):
        """Tests that the matrix representation of the controlled ZYZ decomposition
        of a single-qubit operation is correct"""
        expected_op = qml.ctrl(op, control_wires)
        res = qml.matrix(ctrl_decomp_zyz, wire_order=control_wires + [0])(op, control_wires)
        expected = expected_op.matrix()

        assert np.allclose(expected, res, atol=tol, rtol=0)

    def test_correct_decomp(self):
        """Test that the operations in the decomposition are correct."""
        phi, theta, omega = 0.123, 0.456, 0.789
        op = qml.Rot(phi, theta, omega, wires=0)
        control_wires = [1, 2, 3]
        decomps = ctrl_decomp_zyz(op, Wires(control_wires))

        expected_ops = [
            qml.RZ(0.123, wires=0),
            qml.RY(0.456 / 2, wires=0),
            qml.MultiControlledX(wires=control_wires + [0]),
            qml.RY(-0.456 / 2, wires=0),
            qml.RZ(-(0.123 + 0.789) / 2, wires=0),
            qml.MultiControlledX(wires=control_wires + [0]),
            qml.RZ((0.789 - 0.123) / 2, wires=0),
        ]
        assert all(
            qml.equal(decomp_op, expected_op)
            for decomp_op, expected_op in zip(decomps, expected_ops)
        )
        assert len(decomps) == 7

    @pytest.mark.parametrize("op", su2_ops + unitary_ops)
    @pytest.mark.parametrize("control_wires", ([1], [1, 2], [1, 2, 3]))
    def test_decomp_queues_correctly(self, op, control_wires, tol):
        """Test that any incorrect operations aren't queued when using
        ``ctrl_decomp_zyz``."""
        decomp = ctrl_decomp_zyz(op, control_wires=Wires(control_wires))
        dev = qml.device("default.qubit", wires=4)

        @qml.qnode(dev)
        def queue_from_list():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            for o in decomp:
                qml.apply(o)
            return qml.state()

        @qml.qnode(dev)
        def queue_from_qnode():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            ctrl_decomp_zyz(op, control_wires=Wires(control_wires))
            return qml.state()

        res1 = queue_from_list()
        res2 = queue_from_qnode()
        assert np.allclose(res1, res2, atol=tol, rtol=0)

    def test_trivial_ops_in_decomposition(self):
        """Test that an operator decomposition doesn't have trivial rotations."""
        op = qml.RZ(np.pi, wires=0)
        decomp = ctrl_decomp_zyz(op, [1])
        expected = [
            qml.RZ(np.pi, wires=0),
            qml.MultiControlledX(wires=[1, 0]),
            qml.RZ(-np.pi / 2, wires=0),
            qml.MultiControlledX(wires=[1, 0]),
            qml.RZ(-np.pi / 2, wires=0),
        ]

        assert len(decomp) == 5
        assert all(qml.equal(o, e) for o, e in zip(decomp, expected))

class TestControlledBisectOD:
    """tests for qml.ops.ctrl_decomp_bisect_od"""

    def test_invalid_op_error(self):
        """Tests that an error is raised when an invalid operation is passed"""
        with pytest.raises(
            ValueError, match="The target operation must be a single-qubit operation"
        ):
            _ = ctrl_decomp_bisect_od(qml.CNOT([0, 1]), [2])

    su2_od_ops = [
        qml.QubitUnitary(
            np.array(
                [
                    [0, 1],
                    [-1, 0],
                ]
            ),
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [1, 1],
                    [-1, 1],
                ]
            ) * 2 **-0.5,
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [1j, 0],
                    [0, -1j],
                ]
            ),
            wires=0,
        ),
    ]

    od_ops = [
        qml.PauliZ(0),
    ]

    @pytest.mark.parametrize("op", su2_od_ops + od_ops)
    @pytest.mark.parametrize("control_wires", cw5)
    def test_decomposition_circuit(self, op, control_wires, tol):
        """Tests that the controlled decomposition of a single-qubit operation
        behaves as expected in a quantum circuit"""
        dev = qml.device("default.qubit", wires=max(control_wires)+1)

        @qml.qnode(dev)
        def decomp_circuit():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            ctrl_decomp_bisect_od(op, Wires(control_wires))
            return qml.probs()

        @qml.qnode(dev)
        def expected_circuit():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            qml.ctrl(op, control_wires)
            return qml.probs()

        res = decomp_circuit()
        expected = expected_circuit()
        assert np.allclose(res, expected, atol=tol, rtol=tol)

    @pytest.mark.parametrize("op", su2_od_ops)
    @pytest.mark.parametrize("control_wires", cw5)
    def test_decomposition_matrix(self, op, control_wires, tol):
        """Tests that the matrix representation of the controlled decomposition
        of a single-qubit operation is correct"""
        assert np.allclose(op.matrix(), _convert_to_su2(op.matrix()), atol=tol, rtol=tol)

        expected_op = qml.ctrl(op, control_wires)
        res = qml.matrix(ctrl_decomp_bisect_od, wire_order=control_wires + [0])(op, control_wires)
        expected = expected_op.matrix()

        assert np.allclose(res, expected, atol=tol, rtol=tol)



class TestControlledBisectMD:
    """tests for qml.ops.ctrl_decomp_bisect_md"""

    def test_invalid_op_error(self):
        """Tests that an error is raised when an invalid operation is passed"""
        with pytest.raises(
            ValueError, match="The target operation must be a single-qubit operation"
        ):
            _ = ctrl_decomp_bisect_md(qml.CNOT([0, 1]), [2])

    su2_md_ops = [
        qml.QubitUnitary(
            np.array(
                [
                    [0, 1j],
                    [1j, 0],
                ]
            ),
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [0, 1],
                    [-1, 0],
                ]
            ),
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [1, 1],
                    [-1, 1],
                ]
            ) * 2 **-0.5,
            wires=0,
        ),
    ]

    md_ops = [
        qml.QubitUnitary(
            np.array(
                [
                    [0, 1],
                    [1, 0],
                ]
            ),
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [1j, 1j],
                    [-1j, 1j],
                ]
            ) * 2 **-0.5,
            wires=0,
        ),
    ]

    @pytest.mark.parametrize("op", su2_md_ops + md_ops)
    @pytest.mark.parametrize("control_wires", cw5)
    def test_decomposition_circuit(self, op, control_wires, tol):
        """Tests that the controlled decomposition of a single-qubit operation
        behaves as expected in a quantum circuit"""
        dev = qml.device("default.qubit", wires=max(control_wires)+1)

        @qml.qnode(dev)
        def decomp_circuit():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            ctrl_decomp_bisect_md(op, Wires(control_wires))
            return qml.probs()

        @qml.qnode(dev)
        def expected_circuit():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            qml.ctrl(op, control_wires)
            return qml.probs()

        res = decomp_circuit()
        expected = expected_circuit()
        assert np.allclose(res, expected, atol=tol, rtol=tol)

    @pytest.mark.parametrize("op", su2_md_ops)
    @pytest.mark.parametrize("control_wires", cw5)
    def test_decomposition_matrix(self, op, control_wires, tol):
        """Tests that the matrix representation of the controlled decomposition
        of a single-qubit operation is correct"""
        assert np.allclose(op.matrix(), _convert_to_su2(op.matrix()), atol=tol, rtol=tol)
        
        expected_op = qml.ctrl(op, control_wires)
        res = qml.matrix(ctrl_decomp_bisect_md, wire_order=control_wires + [0])(op, control_wires)
        expected = expected_op.matrix()

        assert np.allclose(res, expected, atol=tol, rtol=tol)


class TestControlledBisectGeneral:
    """tests for qml.ops.ctrl_decomp_bisect_general"""

    def test_invalid_op_error(self):
        """Tests that an error is raised when an invalid operation is passed"""
        with pytest.raises(
            ValueError, match="The target operation must be a single-qubit operation"
        ):
            _ = ctrl_decomp_bisect_general(qml.CNOT([0, 1]), [2])

    su2_gen_ops = [
        qml.QubitUnitary(
            np.array(
                [
                    [0, 1],
                    [-1, 0],
                ]
            ),
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [0, 1j],
                    [1j, 0],
                ]
            ),
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [1j, 1j],
                    [1j, -1j],
                ]
            ) * 2 **-0.5,
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [1, 1],
                    [-1, 1],
                ]
            ) * 2 **-0.5,
            wires=0,
        ),
        qml.QubitUnitary(
            np.array(
                [
                    [1+2j, -3+4j],
                    [3+4j, 1-2j],
                ]
            ) * 30 **-0.5,
            wires=0,
        ),
    ]

    gen_ops = [
        qml.PauliX(0),
        qml.PauliY(0),
        qml.PauliZ(0),
        qml.Hadamard(0),
        qml.Rot(0.123, 0.456, 0.789, wires=0),
    ]

    @pytest.mark.parametrize("op", su2_gen_ops + gen_ops)
    @pytest.mark.parametrize("control_wires", cw5)
    def test_decomposition_circuit(self, op, control_wires, tol):
        """Tests that the controlled decomposition of a single-qubit operation
        behaves as expected in a quantum circuit"""
        dev = qml.device("default.qubit", wires=max(control_wires)+1)

        @qml.qnode(dev)
        def decomp_circuit():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            ctrl_decomp_bisect_general(op, Wires(control_wires))
            return qml.probs()

        @qml.qnode(dev)
        def expected_circuit():
            qml.broadcast(unitary=qml.Hadamard, pattern="single", wires=control_wires)
            qml.ctrl(op, control_wires)
            return qml.probs()

        res = decomp_circuit()
        expected = expected_circuit()
        assert np.allclose(res, expected, atol=tol, rtol=tol)

    @pytest.mark.parametrize("op", su2_gen_ops)
    @pytest.mark.parametrize("control_wires", cw5)
    def test_decomposition_matrix(self, op, control_wires, tol):
        """Tests that the matrix representation of the controlled decomposition
        of a single-qubit operation is correct"""
        assert np.allclose(op.matrix(), _convert_to_su2(op.matrix()), atol=tol, rtol=tol)
        
        expected_op = qml.ctrl(op, control_wires)
        res = qml.matrix(ctrl_decomp_bisect_general, wire_order=control_wires + [0])(op, control_wires)
        expected = expected_op.matrix()

        print('Expected:')
        print(np.round(expected,2))
        print('Result:')
        print(np.round(res,2))
        assert np.allclose(res, expected, atol=tol, rtol=tol)