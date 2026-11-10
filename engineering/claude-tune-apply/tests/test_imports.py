import importlib


def test_modules_import():
    tune_ops = importlib.import_module("tune_ops")
    importlib.import_module("apply")
    plan_render = importlib.import_module("plan_render")
    assert tune_ops.OP_KINDS == plan_render.OP_KINDS
