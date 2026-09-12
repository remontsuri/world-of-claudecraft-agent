package com.woof.agent.env;

import java.util.List;
import java.util.Map;

/** Quest state container */
public class QuestInfo {
    public List<QuestEntry> active;
    public List<QuestEntry> ready;
    public List<QuestEntry> done;
    public Map<String, QuestEntry> all;

    public QuestInfo() {}
}
