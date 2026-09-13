package com.woof.agent.memory;

import com.fasterxml.jackson.databind.JsonNode;
import com.woof.agent.fsm.GoalFSM;
import java.util.List;
import java.util.Map;

/**
 * Skill — executable capability in Voyager architecture.
 * Retrieved from SkillLibrary, composed into execution plans.
 */
public class Skill {
    public String id;
    public String name;
    public String description;
    public List<String> preconditions;
    public List<String> postconditions;
    public Map<String, Object> params;

    public Skill(String id, String name) {
        this.id = id;
        this.name = name;
    }

    public Skill() {}
}
