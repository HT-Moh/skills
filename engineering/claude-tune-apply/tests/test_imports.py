import importlib


def test_modules_import():
    tune_ops = importlib.import_module("tune_ops")
    plan_schema = importlib.import_module("plan_schema")
    importlib.import_module("apply")
    importlib.import_module("plan_render")
    assert tune_ops.OP_KINDS is plan_schema.OP_KINDS  # one source of truth, no second copy
