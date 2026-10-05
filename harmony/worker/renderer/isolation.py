'''Runs one render in a child process, so a browser that will not close cannot
hold a render slot.

The child gets the render's deadline plus `cleanup_grace_seconds` to answer.
After that it is killed together with every process it started: Playwright's
driver and Chromium, which Playwright starts in a session of its own, so killing
the child's process group would miss it.
'''

import multiprocessing
import os
import signal
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Callable, Union

from harmony.worker.renderer.errors import RenderError, RenderTimeout
from harmony.worker.renderer.server import RendererSettings, RenderOutput
from harmony.worker.renderer.spec import RenderSpec

Render = Callable[[RenderSpec, RendererSettings], RenderOutput]

# A fresh interpreter: forking the threaded HTTP server could copy a held lock.
SPAWN = multiprocessing.get_context('spawn')


class RenderCrashed(RenderError):
    '''The render failed unexpectedly; the message is only the exception type,
    because a browser error's text can quote the request.'''


def _child(
    render: Render, spec: RenderSpec, settings: RendererSettings, answer: Connection
) -> None:
    outcome: Union[RenderOutput, RenderError]
    try:
        outcome = render(spec, settings)
    except RenderError as error:
        outcome = error
    except Exception as error:  # pylint: disable=broad-except
        outcome = RenderCrashed(type(error).__name__)
    answer.send(outcome)
    answer.close()


def _children_by_parent() -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            # The command name is in parentheses and may contain spaces.
            fields = stat.read_text().rsplit(')', 1)[1].split()
        except (OSError, IndexError):
            continue
        children.setdefault(int(fields[1]), []).append(int(stat.parent.name))
    return children


def _descendants(root: int) -> set[int]:
    children = _children_by_parent()
    found: set[int] = set()
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _signal(pid: int, signum: signal.Signals) -> None:
    try:
        os.kill(pid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def kill_tree(root: int) -> None:
    '''Kills `root` and every process descended from it.

    Each process is stopped before any is killed: a killed parent's children
    move to init and could no longer be found, and a stopped one cannot fork.
    '''
    stopped: set[int] = set()
    while True:
        found = ({root} | _descendants(root)) - stopped
        if not found:
            break
        for pid in found:
            _signal(pid, signal.SIGSTOP)
        stopped |= found
    for pid in stopped:
        _signal(pid, signal.SIGKILL)


def run_isolated(
    render: Render, spec: RenderSpec, settings: RendererSettings
) -> RenderOutput:
    '''`render(spec, settings)` in a child process, killed with everything it
    started once it overruns the deadline plus the clean-up grace.'''
    receiver, sender = SPAWN.Pipe(duplex=False)
    child = SPAWN.Process(target=_child, args=(render, spec, settings, sender))
    child.start()
    sender.close()
    limit = spec.timeout_seconds + settings.cleanup_grace_seconds
    outcome: Union[RenderOutput, RenderError]
    try:
        if receiver.poll(limit):
            outcome = receiver.recv()
            # The browser is closed; this only waits for the interpreter to exit.
            child.join(settings.cleanup_grace_seconds)
        else:
            outcome = RenderTimeout(f'no render within {spec.timeout_seconds:.0f}s')
    except EOFError:
        outcome = RenderCrashed('the render process exited without an answer')
    finally:
        receiver.close()
        if child.pid is not None and child.is_alive():
            kill_tree(child.pid)
        child.join()
    if isinstance(outcome, RenderError):
        raise outcome
    return outcome
