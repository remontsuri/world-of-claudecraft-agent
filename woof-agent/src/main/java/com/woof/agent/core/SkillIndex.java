package com.woof.agent.core;

import java.util.List;

/**
 * Единственный источник истины: индекс навыка для запроса {action:"step",idx:N}.
 *
 * Порядок обязан совпадать с python/hierarchical_env.py (SKILLS) и
 * src/bridge/actions.cjs (applyAction). Расхождение = агент вызывает не тот навык:
 * например "heal" при idx=8 превращается в equip, а "buy" при idx=5 — в gather.
 */
public final class SkillIndex {
    public static final List<String> SKILLS = List.of(
            "farm", "loot", "accept_quest", "turn_in_quest", "sell_junk",
            "gather", "craft", "heal", "equip", "buy",
            "cast_frostbolt", "cast_fireball", "craft_item");

    private SkillIndex() {}

    /** Индекс навыка для моста. Бросает, если навыка нет в таблице — молча звать
     *  «примерно тот» индекс нельзя, это и был баг. */
    public static int idx(String skill) {
        String s = canonical(skill);
        int i = SKILLS.indexOf(s);
        if (i < 0) {
            throw new IllegalArgumentException("навык отсутствует в таблице моста: " + skill);
        }
        return i;
    }

    public static boolean known(String skill) {
        return SKILLS.indexOf(canonical(skill)) >= 0;
    }

    public static String at(int idx) {
        return (idx >= 0 && idx < SKILLS.size()) ? SKILLS.get(idx) : null;
    }

    /** Алиасы: имена из архитектуры -> имена моста. */
    private static String canonical(String skill) {
        if (skill == null) return "";
        switch (skill) {
            case "turn_in":     return "turn_in_quest";
            case "sell":        return "sell_junk";
            default:            return skill;
        }
    }
}
