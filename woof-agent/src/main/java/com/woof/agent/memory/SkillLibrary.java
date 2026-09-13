package com.woof.agent.memory;

import java.util.*;

/**
 * SkillLibrary — registry of all available skills.
 * Voyager pattern: retrieve → compose → execute → verify → save back.
 */
public class SkillLibrary {
    private final Map<String, Skill> skills = new HashMap<>();

    public void register(Skill skill) {
        skills.put(skill.id, skill);
    }

    public Skill get(String id) {
        return skills.get(id);
    }

    public List<Skill> all() {
        return new ArrayList<>(skills.values());
    }

    public List<Skill> findByPrecondition(String precondition) {
        List<Skill> result = new ArrayList<>();
        for (Skill s : skills.values()) {
            if (s.preconditions != null && s.preconditions.contains(precondition)) {
                result.add(s);
            }
        }
        return result;
    }

    public int size() { return skills.size(); }
}
