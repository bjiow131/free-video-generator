"""A venv launcher and its Python child are not two supervisors."""
from local_agent.poller import _supervisor_instance_count


def p(pid, parent_pid, role):
    return {"pid": pid, "parent_pid": parent_pid, "role": role}


def test_venv_wrapper_chain_is_one_instance():
    samples = [
        p(16272, 10268, "supervisor"),
        p(7676, 16272, "supervisor"),
        p(7348, 7676, "studio"),
        p(2692, 7676, "mailbox"),
        p(8448, 5944, "watchdog"),
    ]
    assert _supervisor_instance_count(samples) == 1


def test_two_independent_supervisor_trees_detected():
    samples = [
        p(10, 1, "supervisor"), p(11, 10, "supervisor"),
        p(20, 2, "supervisor"), p(21, 20, "supervisor"),
    ]
    assert _supervisor_instance_count(samples) == 2


def test_zero_or_unrelated_processes():
    assert _supervisor_instance_count([]) == 0
    assert _supervisor_instance_count([p(23, 1, "mailbox"), p(24, 1, "studio")]) == 0
