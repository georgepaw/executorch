# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Example script for exporting simple models to flatbuffer

import argparse

import executorch.exir as exir
import torch
from executorch.backends.test.backend_with_compiler_demo import BackendWithCompilerDemo
from executorch.backends.test.op_partitioner_demo import AddMulPartitionerDemo
from executorch.exir.backend.backend_api import to_backend

from ..models import MODEL_NAME_TO_MODEL

from .utils import _CAPTURE_CONFIG, _EDGE_COMPILE_CONFIG

"""
BackendWithCompilerDemo is a test demo backend, only supports torch.mm and torch.add, here are some examples
to show how to lower torch.mm and torch.add into this backend via to_backend API.

We support three ways:
1. Lower the whole graph
2. Lower part of the graph via graph partitioner
3. Composite a model with lowered module
"""


def export_compsite_module_with_lower_graph():
    """

    AddMulModule:

        input -> torch.mm -> torch.add -> output

    this module can be lowered to the demo backend as a delegate

        input -> [lowered module (delegate)] -> output

    the lowered module can be used to composite with other modules

        input -> [lowered module (delegate)] -> sub  -> output
               |--------  composite module    -------|

    """
    print("Running the example to export a composite module with lowered graph...")
    m, m_inputs = MODEL_NAME_TO_MODEL.get("add_mul")()
    m = m.eval()
    m_inputs = m.get_example_inputs()
    edge = exir.capture(m, m_inputs, _CAPTURE_CONFIG).to_edge(_EDGE_COMPILE_CONFIG)
    print("Exported graph:\n", edge.exported_program.graph)

    # Lower AddMulModule to the demo backend
    print("Lowering to the demo backend...")
    lowered_graph = to_backend(
        BackendWithCompilerDemo.__name__, edge.exported_program, m.get_compile_spec()
    )

    # Composite the lower graph with other module
    class CompositeModule(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.lowered_graph = lowered_graph

        def forward(self, *args):
            return torch.sub(self.lowered_graph(*args), torch.ones(1))

    # Get the graph for the composite module, which includes lowered graph
    composited_edge = exir.capture(
        CompositeModule(),
        m_inputs,
        _CAPTURE_CONFIG,
    ).to_edge(_EDGE_COMPILE_CONFIG)

    # The graph module is still runnerable
    composited_edge.exported_program.graph_module(*m_inputs)

    print("Lowered graph:\n", composited_edge.exported_program.graph)

    exec_prog = composited_edge.to_executorch()
    buffer = exec_prog.buffer

    model_name = "composite_model"
    filename = f"{model_name}.pte"
    print(f"Saving exported program to {filename}")
    with open(filename, "wb") as file:
        file.write(buffer)


def export_and_lower_partitioned_graph():
    """

    Model:
        input -> torch.mm -> torch.add -> torch.sub -> torch.mm -> torch.add -> output

    AddMulPartitionerDemo is a graph partitioner that tag the lowered nodes, in this case, it will tag
    torch.mm and torch.add nodes. After to_backend, the graph will becomes:

        input -> [lowered module (delegate)] -> torch.sub -> [lowered module (delegate)] -> output
    """

    print("Running the example to export and lower the whole graph...")

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()

        def forward(self, a, x, b):
            y = torch.mm(a, x)
            z = y + b
            a = z - a
            y = torch.mm(a, x)
            z = y + b
            return z

        def get_example_inputs(self):
            return (torch.randn(2, 2), torch.randn(2, 2), torch.randn(2, 2))

    m = Model()
    edge = exir.capture(m, m.get_example_inputs(), _CAPTURE_CONFIG).to_edge(
        _EDGE_COMPILE_CONFIG
    )
    print("Exported graph:\n", edge.exported_program.graph)

    # Lower to backend_with_compiler_demo
    print("Lowering to the demo backend...")
    edge.exported_program = to_backend(edge.exported_program, AddMulPartitionerDemo)
    print("Lowered graph:\n", edge.exported_program.graph)

    exec_prog = edge.to_executorch()
    buffer = exec_prog.buffer

    model_name = "partition_lowered_model"
    filename = f"{model_name}.pte"
    print(f"Saving exported program to {filename}")
    with open(filename, "wb") as file:
        file.write(buffer)


def export_and_lower_the_whole_graph():
    """

    AddMulModule:

        input -> torch.mm -> torch.add -> output

    this module can be lowered to the demo backend as a delegate

        input -> [lowered module (delegate)] -> output
    """
    print("Running the example to export and lower the whole graph...")

    m, m_inputs = MODEL_NAME_TO_MODEL.get("add_mul")()
    m = m.eval()
    m_inputs = m.get_example_inputs()
    edge = exir.capture(m, m_inputs, _CAPTURE_CONFIG).to_edge(_EDGE_COMPILE_CONFIG)
    print("Exported graph:\n", edge.exported_program.graph)

    # Lower AddMulModule to the demo backend
    print("Lowering to the demo backend...")
    _ = to_backend(
        BackendWithCompilerDemo.__name__, edge.exported_program, m.get_compile_spec()
    )

    # TODO(chenlai): emit the lowered graph


OPTIONS_TO_LOWER = {
    "composite": export_compsite_module_with_lower_graph,
    "partition": export_and_lower_partitioned_graph,
    "whole": export_and_lower_the_whole_graph,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--option",
        required=True,
        choices=list(OPTIONS_TO_LOWER.keys()),
        help=f"Provide the flow name. Valid ones: {list(OPTIONS_TO_LOWER.keys())}",
    )

    args = parser.parse_args()

    # Choose one option
    option = OPTIONS_TO_LOWER[args.option]

    # Run the example flow
    option()
