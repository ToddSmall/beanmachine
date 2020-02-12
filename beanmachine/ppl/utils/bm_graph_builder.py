# Copyright (c) Facebook, Inc. and its affiliates.
# from beanmachine.graph import Graph
"""A builder for the BeanMachine Graph language"""

from abc import ABC, ABCMeta, abstractmethod
from typing import Any, Dict, List

# TODO: For reasons unknown, Pyre is unable to find type information about
# TODO: beanmachine.graph from beanmachine.ppl.  I'll figure out why later;
# TODO: for now, we'll just turn off error checking in this mModuleNotFoundError
# pyre-ignore-all-errors
from beanmachine.graph import AtomicType, DistributionType, Graph, OperatorType
from beanmachine.ppl.utils.dotbuilder import DotBuilder
from torch import Tensor


class BMGNode(ABC):
    children: List["BMGNode"]
    edges: List[str]

    def __init__(self, children: List["BMGNode"]):
        self.children = children

    @abstractmethod
    def label(self) -> str:
        pass

    @abstractmethod
    def _add_to_graph(self, g: Graph, d: Dict["BMGNode", int]) -> int:
        pass


class ConstantNode(BMGNode, metaclass=ABCMeta):
    edges = []
    value: Any

    def __init__(self):
        BMGNode.__init__(self, [])


class BooleanNode(ConstantNode):
    value: bool

    def __init__(self, value: bool):
        ConstantNode.__init__(self)
        self.value = value

    def __str__(self) -> str:
        return str(self.value)

    def label(self) -> str:
        return str(self.value)

    def _add_to_graph(self, g: Graph, d: Dict[BMGNode, int]) -> int:
        return g.add_constant(bool(self.value))


class RealNode(ConstantNode):
    value: float

    def __init__(self, value: float):
        ConstantNode.__init__(self)
        self.value = value

    def __str__(self) -> str:
        return str(self.value)

    def label(self) -> str:
        return str(self.value)

    def _add_to_graph(self, g: Graph, d: Dict[BMGNode, int]) -> int:
        return g.add_constant(float(self.value))


class TensorNode(ConstantNode):
    value: Tensor

    def __init__(self, value: Tensor):
        ConstantNode.__init__(self)
        self.value = value

    def __str__(self) -> str:
        return str(self.value)

    def label(self) -> str:
        return str(self.value)

    def _add_to_graph(self, g: Graph, d: Dict[BMGNode, int]) -> int:
        return g.add_constant(self.value)


class DistributionNode(BMGNode, metaclass=ABCMeta):
    def __init__(self, children: List[BMGNode]):
        BMGNode.__init__(self, children)


class BernoulliNode(DistributionNode):
    edges = ["probability"]

    def __init__(self, probability: BMGNode):
        DistributionNode.__init__(self, [probability])

    def probability(self) -> BMGNode:
        return self.children[0]

    def label(self) -> str:
        return "Bernoulli"

    def __str__(self) -> str:
        return "Bernoulli(" + str(self.probability()) + ")"

    def _add_to_graph(self, g: Graph, d: Dict[BMGNode, int]) -> int:
        return g.add_distribution(
            DistributionType.BERNOULLI, AtomicType.BOOLEAN, [d[self.probability()]]
        )


class OperatorNode(BMGNode, metaclass=ABCMeta):
    def __init__(self, children: List[BMGNode]):
        BMGNode.__init__(self, children)


class BinaryOperatorNode(OperatorNode, metaclass=ABCMeta):
    edges = ["left", "right"]
    operator_type: OperatorType

    def __init__(self, left: BMGNode, right: BMGNode):
        OperatorNode.__init__(self, [left, right])

    def left(self) -> BMGNode:
        return self.children[0]

    def right(self) -> BMGNode:
        return self.children[1]

    def _add_to_graph(self, g: Graph, d: Dict[BMGNode, int]) -> int:
        return g.add_operator(self.operator_type, [d[self.left()], d[self.right()]])


class AdditionNode(BinaryOperatorNode):
    operator_type = OperatorType.ADD

    def __init__(self, left: BMGNode, right: BMGNode):
        BinaryOperatorNode.__init__(self, left, right)

    def label(self) -> str:
        return "+"

    def __str__(self) -> str:
        return "(" + str(self.left()) + "+" + str(self.right()) + ")"


class MultiplicationNode(BinaryOperatorNode):
    operator_type = OperatorType.MULTIPLY

    def __init__(self, left: BMGNode, right: BMGNode):
        BinaryOperatorNode.__init__(self, left, right)

    def label(self) -> str:
        return "*"

    def __str__(self) -> str:
        return "(" + str(self.left()) + "*" + str(self.right()) + ")"


class UnaryOperatorNode(OperatorNode, metaclass=ABCMeta):
    edges = ["operand"]
    operator_type: OperatorType

    def __init__(self, operand: BMGNode):
        OperatorNode.__init__(self, [operand])

    def operand(self) -> BMGNode:
        return self.children[0]

    def _add_to_graph(self, g: Graph, d: Dict[BMGNode, int]) -> int:
        return g.add_operator(self.operator_type, [d[self.operand()]])


class NegateNode(UnaryOperatorNode):
    operator_type = OperatorType.NEGATE

    def __init__(self, operand: BMGNode):
        UnaryOperatorNode.__init__(self, operand)

    def label(self) -> str:
        return "-"

    def __str__(self) -> str:
        return "-" + str(self.operand())


class ToRealNode(UnaryOperatorNode):
    operator_type = OperatorType.TO_REAL

    def __init__(self, operand: BMGNode):
        UnaryOperatorNode.__init__(self, operand)

    def label(self) -> str:
        return "ToReal"

    def __str__(self) -> str:
        return "ToReal(" + str(self.operand()) + ")"


class ExpNode(UnaryOperatorNode):
    operator_type = OperatorType.EXP

    def __init__(self, operand: BMGNode):
        UnaryOperatorNode.__init__(self, operand)

    def label(self) -> str:
        return "Exp"

    def __str__(self) -> str:
        return "Exp(" + str(self.operand()) + ")"


class SampleNode(UnaryOperatorNode):
    operator_type = OperatorType.SAMPLE

    def __init__(self, operand: DistributionNode):
        UnaryOperatorNode.__init__(self, operand)

    def operand(self) -> DistributionNode:
        c = self.children[0]
        assert isinstance(c, DistributionNode)
        return c

    def label(self) -> str:
        return "Sample"

    def __str__(self) -> str:
        return "Sample(" + str(self.operand()) + ")"


class Observation(BMGNode):
    edges = ["operand", "value"]

    def __init__(self, observed: SampleNode, value: ConstantNode):
        BMGNode.__init__(self, [observed, value])

    def observed(self) -> SampleNode:
        c = self.children[0]
        assert isinstance(c, SampleNode)
        return c

    def value(self) -> ConstantNode:
        c = self.children[1]
        assert isinstance(c, ConstantNode)
        return c

    def label(self) -> str:
        return "Observation"

    def __str__(self) -> str:
        return str(self.observed()) + "=" + str(self.value())

    def _add_to_graph(self, g: Graph, d: Dict[BMGNode, int]) -> int:
        v = self.value().value
        g.observe(d[self.observed()], v)
        return -1


class Query(BMGNode):
    edges = ["operator"]

    def __init__(self, operator: OperatorNode):
        BMGNode.__init__(self, [operator])

    def operator(self) -> OperatorNode:
        c = self.children[0]
        assert isinstance(c, OperatorNode)
        return c

    def label(self) -> str:
        return "Query"

    def __str__(self) -> str:
        return "Query(" + str(self.operator()) + ")"

    def _add_to_graph(self, g: Graph, d: Dict[BMGNode, int]) -> int:
        g.query(d[self.operator()])
        return -1


class BMGraphBuilder:

    # Note that Python 3.7 guarantees that dictionaries maintain insertion order.
    nodes: Dict[BMGNode, int]

    def __init__(self):
        self.nodes = {}

    def add_node(self, node: BMGNode) -> None:
        # Maintain the invariant that children are always before parents
        # in the list.
        # TODO: If we are ever in a situation where we need to make nodes
        # TODO: and then add the edges later, we'll have to instead do
        # TODO: a deterministic topo sort.
        if node not in self.nodes:
            for child in node.children:
                self.add_node(child)
            self.nodes[node] = len(self.nodes)

    def add_real(self, value: float) -> RealNode:
        node = RealNode(value)
        self.add_node(node)
        return node

    def add_boolean(self, value: bool) -> BooleanNode:
        node = BooleanNode(value)
        self.add_node(node)
        return node

    def add_tensor(self, value: Tensor) -> TensorNode:
        node = TensorNode(value)
        self.add_node(node)
        return node

    def add_bernoulli(self, probability: BMGNode) -> BernoulliNode:
        node = BernoulliNode(probability)
        self.add_node(node)
        return node

    def add_addition(self, left: BMGNode, right: BMGNode) -> AdditionNode:
        node = AdditionNode(left, right)
        self.add_node(node)
        return node

    def add_multiplication(self, left: BMGNode, right: BMGNode) -> MultiplicationNode:
        node = MultiplicationNode(left, right)
        self.add_node(node)
        return node

    def add_negate(self, operand: BMGNode) -> NegateNode:
        node = NegateNode(operand)
        self.add_node(node)
        return node

    def add_to_real(self, operand: BMGNode) -> ToRealNode:
        node = ToRealNode(operand)
        self.add_node(node)
        return node

    def add_exp(self, operand: BMGNode) -> ExpNode:
        node = ExpNode(operand)
        self.add_node(node)
        return node

    def add_sample(self, operand: DistributionNode) -> SampleNode:
        node = SampleNode(operand)
        self.add_node(node)
        return node

    def add_observation(self, observed: SampleNode, value: ConstantNode) -> Observation:
        node = Observation(observed, value)
        self.add_node(node)
        return node

    def add_query(self, operator: OperatorNode) -> Query:
        node = Query(operator)
        self.add_node(node)
        return node

    def to_dot(self) -> str:
        db = DotBuilder()
        for node, index in self.nodes.items():
            n = "N" + str(index)
            db.with_node(n, node.label())
            for (child, label) in zip(node.children, node.edges):
                db.with_edge(n, "N" + str(self.nodes[child]), label)
        return str(db)

    def to_bmg(self) -> Graph:
        g = Graph()
        d: Dict[BMGNode, int] = {}
        for node in self.nodes:
            d[node] = node._add_to_graph(g, d)
        return g
