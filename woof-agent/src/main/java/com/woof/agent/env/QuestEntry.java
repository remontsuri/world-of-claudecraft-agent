package com.woof.agent.env;

import java.util.List;

/** Quest entry from game */
public class QuestEntry {
    public String id;
    public String name;
    public String giverId;
    public String giverName;
    public String state;
    public int progress;
    public int required;
    public java.util.List<Objective> objectives;
    public Integer killCount;
    public String targetType;
    public String targetMobId;

    public QuestEntry() {}
}
