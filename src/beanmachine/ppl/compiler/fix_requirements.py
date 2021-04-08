# Copyright (c) Facebook, Inc. and its affiliates.

"""This module takes a Bean Machine Graph builder and makes a best
effort attempt to transform the accumulated graph to meet the
requirements of the BMG type system. All possible transformations
are made; if there are nodes that cannot be represented in BMG
or cannot be made to meet type requirements, an error report is
returned."""


import beanmachine.ppl.compiler.bmg_nodes as bn
import beanmachine.ppl.compiler.bmg_types as bt
from beanmachine.ppl.compiler.bm_graph_builder import BMGraphBuilder
from beanmachine.ppl.compiler.error_report import ErrorReport, Violation
from beanmachine.ppl.compiler.graph_labels import get_edge_labels
from torch import Tensor


class RequirementsFixer:
    """This class takes a Bean Machine Graph builder and attempts to
    fix violations of BMG type system requirements.

    The basic idea is that every *edge* in the graph has a *requirement*, such as
    "the type of the input must be Probability".  We do a traversal of the input
    edges of every node in the graph; if the input node meets the requirement,
    it is unchanged. If it does not, then a new node that has the same semantics
    that meets the requirement is returned. If there is no such node then an
    error is added to the error report."""

    errors: ErrorReport
    bmg: BMGraphBuilder

    def __init__(self, bmg: BMGraphBuilder) -> None:
        self.errors = ErrorReport()
        self.bmg = bmg

    def _meet_constant_requirement(
        self,
        node: bn.ConstantNode,
        requirement: bt.Requirement,
        consumer: bn.BMGNode,
        edge: str,
    ) -> bn.BMGNode:
        # If the constant node already meets the requirement, we're done.
        if bt.node_meets_requirement(node, requirement):
            return node

        # It does not meet the requirement. Is there a semantically equivalent node
        # that does meet the requirement?

        # The inf type is defined as the smallest type to which the node can be converted.
        # If the infimum type is smaller than or equal to the required type, then the
        # node can definitely be converted to a type which meets the requirement.

        if bt.type_meets_requirement(node.inf_type, bt.upper_bound(requirement)):

            # To what type should we convert the node to meet the requirement?
            # If the requirement is an exact bound, then that's the type we need to
            # convert to. If the requirement is an upper bound, there's no reason
            # why we can't just convert to that type.

            required_type = bt.requirement_to_type(requirement)
            if bt.must_be_matrix(requirement):
                assert isinstance(required_type, bt.BMGMatrixType)
                result = self.bmg.add_constant_of_matrix_type(node.value, required_type)
            else:
                result = self.bmg.add_constant_of_type(node.value, required_type)
            assert bt.node_meets_requirement(result, requirement)
            return result

        # We cannot convert this node to any type that meets the requirement.
        # Add an error.
        self.errors.add_error(Violation(node, requirement, consumer, edge))
        return node

    def _meet_distribution_requirement(
        self,
        node: bn.DistributionNode,
        requirement: bt.Requirement,
        consumer: bn.BMGNode,
        edge: str,
    ) -> bn.BMGNode:
        # The only edges which point to distributions are samples, and the requirement
        # on that edge is always met automatically.
        assert isinstance(consumer, bn.SampleNode)
        assert requirement == node.inf_type
        return node

    def _meet_map_requirement(
        self,
        node: bn.MapNode,
        requirement: bt.Requirement,
        consumer: bn.BMGNode,
        edge: str,
    ) -> bn.BMGNode:
        # The only edges which point to maps are indexes, and the requirement
        # on that edge is always met automatically.
        # TODO: We do not support map nodes in BMG yet, so:
        # TODO: (1) this code path is not exercised by any test case; when
        # TODO: we support map nodes, add a test case.
        # TODO: (2) until we do support map nodes in BMG, we should add an
        # TODO: error reporting pass to this code that detects map nodes
        # TODO: and gives an unsupported node type error.
        assert isinstance(consumer, bn.IndexNodeDeprecated)
        assert requirement == node.inf_type
        return node

    def _convert_malformed_multiplication(
        self,
        node: bn.MultiplicationNode,
        requirement: bt.BMGLatticeType,
        consumer: bn.BMGNode,
        edge: str,
    ) -> bn.BMGNode:
        # We are given a malformed multiplication node which can be converted
        # to a semantically equivalent node that meets the given requirement.
        # Verify these preconditions.

        assert node.graph_type == bt.Malformed
        assert bt.supremum(node.inf_type, requirement) == requirement

        # Under what conditions can a multiplication be malformed?
        #
        # * Its operand types are not equal
        # * Its operand types are not probability or larger

        lgt = node.left.graph_type
        rgt = node.right.graph_type

        # Which of those conditions are possible at this point? Remember,
        # we visit nodes in topological order, so the requirements of the
        # left and right operands have already been met and they are converted
        # to their correct types.
        #
        # * If its operands were malformed, those malformations would have already
        #   been fixed. We never leave a reachable malformed node in the graph.

        assert lgt != bt.Malformed and rgt != bt.Malformed

        # * If its operands were any combination of natural, probability,
        #   positive real, real or tensor, then we would already have converted
        #   them both to the smallest possible common type larger than probability.
        #   They would therefore be equal.
        #
        # * Therefore, for this node to be malformed, at least one of its operands
        #   must be bool.

        assert lgt == bt.Boolean or rgt == bt.Boolean

        # * In that case, we can convert it to an if-then-else.

        if lgt == bt.Boolean:
            zero = self.bmg.add_constant_of_type(0.0, rgt)
            if_then_else = self.bmg.add_if_then_else(node.left, node.right, zero)
            assert if_then_else.graph_type == rgt
        else:
            zero = self.bmg.add_constant_of_type(0.0, lgt)
            if_then_else = self.bmg.add_if_then_else(node.right, node.left, zero)
            assert if_then_else.graph_type == lgt

        # We have met the requirements of the if-then-else; the condition
        # is bool and the consequence and alternative are of the same type.
        # However, we might not yet have met the original requirement, which
        # we have not yet used in this method. We might need to put a to_real
        # on top of it, for instance.
        #
        # Recurse to ensure that is met.

        return self.meet_requirement(if_then_else, requirement, consumer, edge)

    def _convert_malformed_power(
        self,
        node: bn.PowerNode,
        requirement: bt.BMGLatticeType,
        consumer: bn.BMGNode,
        edge: str,
    ) -> bn.BMGNode:
        # We are given a malformed power node which can be converted
        # to a semantically equivalent node that meets the given requirement.
        # Verify these preconditions.

        assert node.graph_type == bt.Malformed
        assert bt.supremum(node.inf_type, requirement) == requirement

        # The only condition in which a power node can be malformed is
        # if the exponent is bool; since we visit the nodes in topological
        # order, we have already converted the operands to well-formed
        # nodes.

        lgt = node.left.graph_type
        rgt = node.right.graph_type

        assert lgt != bt.Malformed
        assert rgt == bt.Boolean

        # Therefore this can be made an if-then-else.
        # x ** b --> if b then x else 1

        one = self.bmg.add_constant_of_type(1.0, lgt)
        if_then_else = self.bmg.add_if_then_else(node.right, node.left, one)

        assert if_then_else.graph_type == lgt

        # We have met the requirements of the if-then-else; the condition
        # is bool and the consequence and alternative are of the same type.
        # However, we might not yet have met the original requirement, which
        # we have not yet used in this method. We might need to put a to_real
        # on top of it, for instance.
        #
        # Recurse to ensure that is met.

        return self.meet_requirement(if_then_else, requirement, consumer, edge)

    def _convert_node(
        self,
        node: bn.OperatorNode,
        requirement: bt.BMGLatticeType,
        consumer: bn.BMGNode,
        edge: str,
    ) -> bn.BMGNode:
        # We have been given a node which does not meet a requirement,
        # but it can be converted to a node which does meet the requirement
        # that has the same semantics. Start by confirming those preconditions.
        assert node.graph_type != requirement
        assert bt.supremum(node.inf_type, requirement) == requirement

        if isinstance(node, bn.MultiplicationNode) and node.graph_type == bt.Malformed:
            return self._convert_malformed_multiplication(
                node, requirement, consumer, edge
            )

        if isinstance(node, bn.PowerNode) and node.graph_type == bt.Malformed:
            return self._convert_malformed_power(node, requirement, consumer, edge)

        # TODO: We no longer support Tensor as a type in BMG.  We must
        # detect, and produce a good error message, for situations
        # where we have deduced that the only possible type of a node is
        # a >2-dimension tensor; we must correctly support cases where
        # the type of the node is a 1- or 2-dimensional tensor.

        if requirement == Tensor:
            raise ValueError("Unsupported type requirement: Tensor")

        # Converting anything to real or positive real is easy;
        # there's already a node for that so just insert it on the edge
        # whose requirement is not met, and the requirement will be met.

        if requirement == bt.Real:
            return self.bmg.add_to_real(node)
        if requirement == bt.PositiveReal:
            return self.bmg.add_to_positive_real(node)

        # We are not converting to real or positive real.
        # Our precondition is that the requirement is larger than
        # *something*, which means that it cannot be bool.
        # That means the requirement must be either natural or
        # probability. Verify this.

        assert requirement == bt.Natural or requirement == bt.Probability

        # Our precondition is that the requirement is larger than the
        # inf type of the node.

        assert bt.supremum(node.inf_type, bt.Boolean) == bt.Boolean

        # There is no "to natural" or "to probability" but since we have
        # a bool in hand, we can use an if-then-else as a conversion.

        zero = self.bmg.add_constant_of_type(0.0, requirement)
        one = self.bmg.add_constant_of_type(1.0, requirement)
        return self.bmg.add_if_then_else(node, one, zero)

    def _can_force_to_prob(
        self, inf_type: bt.BMGLatticeType, requirement: bt.Requirement
    ) -> bool:
        # Consider the graph created by a call like:
        #
        # Bernoulli(0.5 + some_beta() / 2)
        #
        # The inf types of the addends are both probability, but there is
        # no addition operator on probabilities; we will add these as
        # positive reals, and then get an error when we use it as the parameter
        # to a Bernoulli.  But you and I both know that this is a legal
        # probability.
        #
        # To work around this problem, if we have a *real* or *positive real* used
        # in a situation where a *probability* is required, we insert an explicit
        # "clamp this real to a probability" operation.
        #
        # TODO: We might want to restrict this. For example, if we have
        #
        # Bernoulli(some_normal())
        #
        # then it seems plausible that we ought to produce an error here rather than
        # clamping the result to a probability. We could allow this feature only
        # in situations where there was some operator other than a sample, for instance.
        #
        # TODO: We might want to build a warning mechanism that informs the developer
        # of the possibility that they've gotten something wrong here.
        return (
            requirement == bt.Probability
            or requirement == bt.upper_bound(bt.Probability)
        ) and (inf_type == bt.Real or inf_type == bt.PositiveReal)

    def _meet_operator_requirement(
        self,
        node: bn.OperatorNode,
        requirement: bt.Requirement,
        consumer: bn.BMGNode,
        edge: str,
    ) -> bn.BMGNode:
        # If the operator node already meets the requirement, we're done.
        if bt.node_meets_requirement(node, requirement):
            return node

        # It does not meet the requirement. Can we convert this thing to a node
        # whose type does meet the requirement? Remember, the inf type is the
        # smallest type that this node is convertible to, so if the inf type
        # meets an upper bound requirement, then the conversion we want exists.

        it = node.inf_type

        if not bt.type_meets_requirement(it, bt.upper_bound(requirement)):
            # We cannot make the node meet the requirement "implicitly". However
            # there is one situation where we can "explicitly" meet a requirement:
            # an operator of type real or positive real used as a probability.
            if self._can_force_to_prob(it, requirement):
                # Ensure that the operand is converted to real or positive real:
                operand = self.meet_requirement(node, it, consumer, edge)
                # Force the real / positive real to probability:
                result = self.bmg.add_to_probability(operand)
                assert bt.node_meets_requirement(result, requirement)
                return result

            # We have no way to make the conversion we need, so add an error.
            self.errors.add_error(Violation(node, requirement, consumer, edge))
            return node

        # We definitely can meet the requirement; it just remains to figure
        # out exactly how.
        #
        # There are now two possibilities:
        #
        # * The requirement is an exact requirement. We know that the node
        #   can be converted to that type, because its inf type meets an
        #   upper bound requirement. Convert it to that exact type.
        #
        # * The requirement is an upper-bound requirement, and the inf type
        #   meets it. Convert the node to the inf type.

        if isinstance(requirement, bt.BMGLatticeType):
            result = self._convert_node(node, requirement, consumer, edge)
        else:
            result = self._convert_node(node, it, consumer, edge)

        # TODO: This assertion could fire if we require a positive real matrix
        # but the result of the conversion is a positive real value.  We need
        # to handle that case.

        assert bt.node_meets_requirement(result, requirement)
        return result

    def meet_requirement(
        self,
        node: bn.BMGNode,
        requirement: bt.Requirement,
        consumer: bn.BMGNode,
        edge: str,
    ) -> bn.BMGNode:
        """The consumer node consumes the value of the input node. The consumer's
        requirement is given; the name of this edge is provided for error reporting."""

        if isinstance(node, bn.Observation):
            raise AssertionError(
                "Unexpected graph topology; an observation is never an input"
            )
        if isinstance(node, bn.Query):
            raise AssertionError("Unexpected graph topology; a query is never an input")
        if isinstance(node, bn.ConstantNode):
            return self._meet_constant_requirement(node, requirement, consumer, edge)
        if isinstance(node, bn.DistributionNode):
            return self._meet_distribution_requirement(
                node, requirement, consumer, edge
            )
        if isinstance(node, bn.MapNode):
            return self._meet_map_requirement(node, requirement, consumer, edge)
        if isinstance(node, bn.OperatorNode):
            return self._meet_operator_requirement(node, requirement, consumer, edge)
        raise AssertionError("Unexpected node type")

    def fix_problems(self) -> None:
        nodes = self.bmg._traverse_from_roots()
        for node in nodes:
            requirements = node.requirements
            # TODO: The edge labels used to visualize the graph in DOT
            # are not necessarily the best ones for displaying errors.
            # Consider fixing this.
            edges = get_edge_labels(node)
            for i in range(len(requirements)):
                node.inputs[i] = self.meet_requirement(
                    node.inputs[i], requirements[i], node, edges[i]
                )