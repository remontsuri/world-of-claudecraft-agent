package com.woof.agent.core;

import com.woof.agent.memory.Skill;
import com.woof.agent.memory.SkillLibrary;

/**
 * SkillRegistry — регистрирует навыки ИМЕННО теми именами, которые понимает
 * мост. Прежний список содержал "turn_in" и "sell", тогда как мост ждёт
 * "turn_in_quest" и "sell_junk", и не содержал equip/frostbolt/fireball/craft_item.
 */
public class SkillRegistry {
    private static final String[][] DEFAULTS = {
            {"farm",            "цель + атака (подход — отдельный навык navigate)"},
            {"loot",            "обыскать труп рядом"},
            {"accept_quest",    "взять квест у NPC в радиусе"},
            {"turn_in_quest",   "сдать готовый квест"},
            {"sell_junk",       "продать лишнее торговцу"},
            {"gather",          "добыть ресурсный узел (с подходом)"},
            {"craft",           "ремесло (в live-клиенте не открыто)"},
            {"heal",            "выпить зелье лечения"},
            {"equip",           "надеть снаряжение"},
            {"buy",             "купить у торговца"},
            {"cast_frostbolt",  "дальний урон + замедление"},
            {"cast_fireball",   "дальний урон + DoT"},
            {"craft_item",      "изготовить предмет по рецепту"},
    };

    private final SkillLibrary library;

    public SkillRegistry(SkillLibrary library) {
        this.library = library;
        registerDefaults();
    }

    public SkillLibrary getLibrary() { return library; }

    private void registerDefaults() {
        for (String[] d : DEFAULTS) {
            Skill skill = new Skill(d[0], d[0]);
            skill.description = d[1];
            skill.bridgeIndex = SkillIndex.idx(d[0]);
            library.register(skill);
        }
    }
}
