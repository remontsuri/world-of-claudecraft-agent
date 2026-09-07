"""test_verdict_lifecycle.py — regression test for P0 verdict UnboundLocalError."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))


def test_verdict_initialized_before_bounds_check():
    """Verify verdict is assigned before _is_progress uses it in the bounds block."""
    play_path = os.path.join(os.path.dirname(__file__), "play_autonomous.py")
    with open(play_path, "r", encoding="utf-8") as f:
        src = f.read()

    lines = src.split('\n')
    in_bounds_block = False
    assignment_line = None
    use_line = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if 'if bounds is not None:' in stripped:
            in_bounds_block = True
            continue
        if in_bounds_block:
            if assignment_line is None and re.match(r'verdict\s*=', stripped):
                assignment_line = i + 1
            if '_is_progress' in stripped and 'verdict' in stripped:
                use_line = i + 1

    assert assignment_line is not None, "verdict must be assigned inside bounds block"
    assert use_line is not None, "verdict must be used in _is_progress"
    assert assignment_line < use_line, (
        f"verdict assigned at line {assignment_line} but used at line {use_line}. "
        f"Assignment must come BEFORE use."
    )
    print(f"PASS: verdict assigned at line {assignment_line}, used at line {use_line}")


def test_summary_receives_bounds_parameter():
    """Verify _summary() accepts bounds parameter and callers pass it."""
    play_path = os.path.join(os.path.dirname(__file__), "play_autonomous.py")
    with open(play_path, "r", encoding="utf-8") as f:
        src = f.read()

    # Check _summary signature
    m = re.search(r'def _summary\(.*?\):', src, re.DOTALL)
    assert m, "_summary function not found"
    sig = m.group(0)
    assert 'bounds=' in sig, f"_summary must accept bounds parameter. Signature: {sig}"
    print(f"PASS: _summary accepts bounds parameter")

    # Check callers pass bounds
    calls = re.findall(r'_summary\([^)]+\)', src)
    for call in calls:
        if 'final=True' in call or 'SAVE_EVERY' in call:
            assert 'bounds=' in call, f"Caller must pass bounds: {call}"
    print(f"PASS: all _summary callers pass bounds")


if __name__ == "__main__":
    test_verdict_initialized_before_bounds_check()
    test_summary_receives_bounds_parameter()
    print("\nAll regression tests PASSED")
