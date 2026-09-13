package com.woof.agent.env;

/** Quest objective */
public class Objective {
    public String type;     // "kill", "gather", "interact", "escort"
    public String target;   // mob type, item id, npc id
    public int required;
    public int current;
    public boolean complete;

    public Objective() {}
}
