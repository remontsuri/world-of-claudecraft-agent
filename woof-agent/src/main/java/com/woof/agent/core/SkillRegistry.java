package com.woof.agent.core;

import com.woof.agent.memory.SkillLibrary;
import com.woof.agent.memory.Skill;

/**
 * SkillRegistry — loads and registers all game skills.
 */
public class SkillRegistry {
    private final SkillLibrary library;

    public SkillRegistry(SkillLibrary library) {
        this.library = library;
        registerDefaults();
    }

    public SkillLibrary getLibrary() {
        return library;
    }

    private void registerDefaults() {
        library.register(new Skill("farm", "Farm mobs for quest objectives"));
        library.register(new Skill("navigate", "Navigate to target location"));
        library.register(new Skill("return_to_giver", "Return to quest giver"));
        library.register(new Skill("flee", "Flee from combat"));
        library.register(new Skill("accept_quest", "Accept quest from NPC"));
        library.register(new Skill("turn_in", "Turn in completed quest"));
        library.register(new Skill("heal", "Heal via potion or spell"));
        library.register(new Skill("gather", "Gather resource node"));
        library.register(new Skill("loot", "Loot from mob corpse"));
        library.register(new Skill("explore", "Explore to find objectives"));
        library.register(new Skill("sell", "Sell items to vendor"));
        library.register(new Skill("buy", "Buy from vendor"));
        library.register(new Skill("craft", "Craft item at station"));
        library.register(new Skill("cast_frostbolt", "Cast Frostbolt spell"));
        library.register(new Skill("cast_fireball", "Cast Fireball spell"));
    }
}
