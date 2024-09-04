from typing import Any, List, Dict
import wandb

from opto.trace.nodes import ParameterNode, Node
from opto.trace.propagators import GraphPropagator
from opto.trace.propagators.propagators import Propagator
from opto.trace.utils import sum_feedback
from opto.optimizers.synthesizer import Synthesizer
from opto.optimizers.optosynth import OptoSynth


import autogen

class AbstractOptimizer:
    """An optimizer is responsible for updating the parameters based on the feedback."""

    def __init__(self, parameters: List[ParameterNode], *args, **kwargs):
        assert type(parameters) is list
        assert all([isinstance(p, ParameterNode) for p in parameters])
        self.parameters = parameters

    def step(self):
        """Update the parameters based on the feedback."""
        raise NotImplementedError

    def zero_feedback(self):
        """Reset the feedback."""
        raise NotImplementedError

    @property
    def propagator(self):
        """Return a Propagator object that can be used to propagate feedback in backward."""
        raise NotImplementedError


class Optimizer(AbstractOptimizer):
    def __init__(self, parameters: List[ParameterNode], *args, propagator: Propagator=None, synthesize=False, wandb_enabled=False, **kwargs):
        super().__init__(parameters)
        propagator = propagator if propagator is not None else self.default_propagator()
        assert isinstance(propagator, Propagator)
        self._propagator = propagator
        self.wandb_enabled = wandb_enabled
        self.inner_feedbacks = []
        if synthesize:
            self._synthesizer = self.default_synthesizer()
        else:
            self._synthesizer = None
            
    @property
    def propagator(self):
        return self._propagator
    
    @property
    def synthesizer(self):
        return self._synthesizer

    @property
    def trace_graph(self):
        """ Aggregate the graphs of all the parameters. """
        return sum_feedback(self.parameters)

    def step(self, *args, **kwargs):
        update_dict = self.propose(*args, **kwargs)
        self.update(update_dict)

    def propose(self, *args, **kwargs):
        """Propose the new data of the parameters based on the feedback."""
        return self._step(*args, **kwargs)

    def update(self, update_dict: Dict[ParameterNode, Any]):
        """Update the trainable parameters given a dictionary of new data."""
        for p, d in update_dict.items():
            if p.trainable:
                p._data = d

    def zero_feedback(self):
        for p in self.parameters:
            p.zero_feedback()

    # Subclass should implement the methods below.
    def _step(self, *args, **kwargs) -> Dict[ParameterNode, Any]:
        """Return the new data of parameter nodes based on the feedback."""
        raise NotImplementedError

    def default_propagator(self):
        """Return the default Propagator object of the optimizer."""
        return GraphPropagator()
    
    def default_synthesizer(self):
        """Return the default Synthesizer object of the optimizer."""
        return Synthesizer(self.parameters,
                            config_list=autogen.config_list_from_json("OAI_CONFIG_LIST"),
                            memory_size=0)

    def backward(self, node: Node, *args, **kwargs):
        """Propagate the feedback backward."""
        if self._synthesizer is not None:
            node._feedback = args[0]
            summary = self.summary_log[-1]['summary'] if len(self.summary_log) > 0 else self.summarize()
            summary.user_feedback = args[0]
            summary.output['feedback'] = args[0]
            problem = str(self.probelm_instance(summary))

            feedback = self._synthesizer.step(summary, problem, *args, verbose=True, mask=None)
            if self.wandb_enabled:
                self.inner_feedbacks.append([feedback])
                wandb.log({'inner feedback': wandb.Table(data=self.inner_feedbacks, columns=["inner feedback"])})
            return node.backward(feedback, propagator=self.propagator, **kwargs)
        return node.backward(*args, propagator=self.propagator, **kwargs)