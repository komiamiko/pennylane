# Copyright 2018-2023 Xanadu Quantum Technologies Inc.

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
This submodule defines functions to decompose controlled operations
"""

import numpy as np
import numpy.linalg as npl
import scipy.optimize as spo
import pennylane as qml
from pennylane.operation import Operator
from pennylane.wires import Wires

def _matrix_adjoint(matrix: np.ndarray):
    return np.transpose(np.conj(matrix))

def _param_su2(ar: float, ai: float, br: float, bi: float):
    """
    Create a matrix in the SU(2) form from complex parameters a, b.
    The resulting matrix is not guaranteed to be in SU(2), unless |a|^2 + |b|^2 = 1.
    """
    return np.array([[complex(ar, ai), complex(-br, bi)],
                     [complex(br, bi), complex(ar, -ai)]])

def _flatreals(x: np.ndarray):
    x = x.flatten()
    return np.concatenate((np.real(x), np.imag(x)))

def _bisect_compute_a(u: np.ndarray):
    """
    Given the U matrix, compute the A matrix such that
    At x A x At x A x = U
    where At is the adjoint of A
    and x is the Pauli X matrix.
    """
    sx = np.array([[0, 1], [1, 0]]) # Pauli X matrix

    def optfunc(x):
        a = _param_su2(*x)
        at = _matrix_adjoint(a)
        expect_u = at @ sx @ a @ sx @ at @ sx @ a @ sx
        return _flatreals((expect_u - u)[0])
    
    sol = spo.root(optfunc, [1, 0, 0, 0])

    if not sol.success:
        raise ValueError(f'Unable to compute A matrix for U matrix {u}')
    
    a = _param_su2(*sol.x)
    
    if not np.isclose(npl.det(a), 1):
        raise AssertionError(f'A matrix is not SU(2): {a}')
    
    return a

def ctrl_decomp_zyz(target_operation: Operator, control_wires: Wires):
    """Decompose the controlled version of a target single-qubit operation

    This function decomposes a controlled single-qubit target operation using the
    decomposition defined in section 5 of
    `Barenco et al. (1995) <https://arxiv.org/abs/quant-ph/9503016>`_.

    .. warning:: This method will add a global phase for target operations that do not
        belong to the SU(2) group.

    Args:
        target_operation (~.operation.Operator): the target operation to decompose
        control_wires (~.wires.Wires): the control wires of the operation

    Returns:
        list[Operation]: the decomposed operations

    Raises:
        ValueError: if ``target_operation`` is not a single-qubit operation

    **Example**

    We can create a controlled operation using `qml.ctrl`, or by creating the
    decomposed controlled version of using `qml.ctrl_decomp_zyz`.

    .. code-block:: python

        dev = qml.device("default.qubit", wires=3)

        @qml.qnode(dev)
        def expected_circuit(op):
            qml.Hadamard(wires=0)
            qml.Hadamard(wires=1)
            qml.ctrl(op, [0,1])
            return qml.probs()

        @qml.qnode(dev)
        def decomp_circuit(op):
            qml.Hadamard(wires=0)
            qml.Hadamard(wires=1)
            qml.ops.ctrl_decomp_zyz(op, [0,1])
            return qml.probs()

    Measurements on both circuits will give us the same results:

    >>> op = qml.RX(0.123, wires=2)
    >>> expected_circuit(op)
    tensor([0.25      , 0.        , 0.25      , 0.        , 0.25      ,
        0.        , 0.24905563, 0.00094437], requires_grad=True)
    >>> decomp_circuit(op)
    tensor([0.25      , 0.        , 0.25      , 0.        , 0.25      ,
        0.        , 0.24905563, 0.00094437], requires_grad=True)

    """
    if len(target_operation.wires) != 1:
        raise ValueError(
            "The target operation must be a single-qubit operation, instead "
            f"got {target_operation.__class__.__name__}."
        )

    target_wire = target_operation.wires

    try:
        phi, theta, omega = target_operation.single_qubit_rot_angles()
    except NotImplementedError:
        with qml.QueuingManager.stop_recording():
            zyz_decomp = qml.transforms.zyz_decomposition(
                qml.matrix(target_operation), target_wire
            )[0]
        phi, theta, omega = zyz_decomp.single_qubit_rot_angles()

    decomp = []

    if not qml.math.isclose(phi, 0.0, atol=1e-8, rtol=0):
        decomp.append(qml.RZ(phi, wires=target_wire))
    if not qml.math.isclose(theta / 2, 0.0, atol=1e-8, rtol=0):
        decomp.extend(
            [
                qml.RY(theta / 2, wires=target_wire),
                qml.MultiControlledX(wires=control_wires + target_wire),
                qml.RY(-theta / 2, wires=target_wire),
            ]
        )
    else:
        decomp.append(qml.MultiControlledX(wires=control_wires + target_wire))
    if not qml.math.isclose(-(phi + omega) / 2, 0.0, atol=1e-6, rtol=0):
        decomp.append(qml.RZ(-(phi + omega) / 2, wires=target_wire))
    decomp.append(qml.MultiControlledX(wires=control_wires + target_wire))
    if not qml.math.isclose((omega - phi) / 2, 0.0, atol=1e-8, rtol=0):
        decomp.append(qml.RZ((omega - phi) / 2, wires=target_wire))

    return decomp

def ctrl_decomp_bisect_od(target_operation: Operator, control_wires: Wires):
    """Decompose the controlled version of a target single-qubit operation

    This function decomposes a controlled single-qubit target operation using the
    decomposition defined in section 3.1 of
    `Vale et al. (2023) <https://arxiv.org/abs/2302.06377>`_.

    The target operation's matrix must have a real off-diagonal for this specialized method to work.

    .. warning:: This method will add a global phase for target operations that do not
        belong to the SU(2) group.

    Args:
        target_operation (~.operation.Operator): the target operation to decompose
        control_wires (~.wires.Wires): the control wires of the operation

    Returns:
        list[Operation]: the decomposed operations

    Raises:
        ValueError: if ``target_operation`` is not a single-qubit operation
            or its matrix does not have a real off-diagonal

    """
    from pennylane.transforms.decompositions.single_qubit_unitary import _convert_to_su2

    if len(target_operation.wires) != 1:
        raise ValueError(
            "The target operation must be a single-qubit operation, instead "
            f"got {target_operation.__class__.__name__}."
        )

    target_wire = target_operation.wires

    u = target_operation.matrix()
    u = _convert_to_su2(u)
    u = np.array(u)

    ui = np.imag(u)
    if not np.isclose(ui[1,0], 0) or not np.isclose(ui[0,1], 0):
        raise ValueError(f"Target operation's matrix must have real off-diagonal, but it is {u}")
    
    a = _bisect_compute_a(u)

    mid = len(control_wires) // 2
    lk = control_wires[:mid]
    rk = control_wires[mid:]

    def mcx(_lk, _rk):
        return qml.MultiControlledX(control_wires = _lk, wires = target_wire, work_wires = _rk)
    op_mcx1 = lambda:mcx(lk,rk)
    op_mcx2 = lambda:mcx(rk,lk)
    op_a = lambda:qml.QubitUnitary(a, target_wire)
    op_at = lambda:qml.adjoint(op_a())

    return [op_mcx1(), op_a(), op_mcx2(), op_at(), op_mcx1(), op_a(), op_mcx2(), op_at()]

    
