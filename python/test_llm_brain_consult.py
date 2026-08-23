import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from llm_brain import LLMBrain

b = LLMBrain()

def test_first_decision_always():
    assert b.should_consult(None, "DO_OBJECTIVE", 7, 0, False) is True

def test_phase_change_consults():
    assert b.should_consult("DO_OBJECTIVE", "TURN_IN", 41, 0, False) is True

def test_same_goal_no_consult():
    assert b.should_consult("DO_OBJECTIVE", "DO_OBJECTIVE", 41, 0, False) is False

def test_three_failures_consult():
    assert b.should_consult("DO_OBJECTIVE", "DO_OBJECTIVE", 43, 3, False) is True

def test_new_quest_consults():
    assert b.should_consult("DO_OBJECTIVE", "DO_OBJECTIVE", 44, 0, True) is True

def test_periodic_consult_every_50():
    assert b.should_consult("DO_OBJECTIVE", "DO_OBJECTIVE", 50, 0, False) is True
    assert b.should_consult("DO_OBJECTIVE", "DO_OBJECTIVE", 51, 0, False) is False
