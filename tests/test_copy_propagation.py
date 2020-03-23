from utils import run_pass_harness
from inliner.passes.copy_propagation import CopyPropagationPass


def test_copy_propagation_noop():
    def prog():
        x = 1
        y = x
        y = y + 1
        assert y == 2

    def outp():
        x = 1
        y = x
        y = y + 1
        assert y == 2

    run_pass_harness(prog, CopyPropagationPass, outp, locals())


def test_copy_propagation_basic():
    def prog():
        x = 1
        y = x
        z = y + x

    def outp():
        x = 1
        z = x + x

    run_pass_harness(prog, CopyPropagationPass, outp, locals())


def test_copy_propagation_two_step():
    def prog():
        x = 1
        y = x
        z = y
        assert z == 1

    def outp():
        x = 1
        assert x == 1

    run_pass_harness(prog, CopyPropagationPass, outp, locals())
