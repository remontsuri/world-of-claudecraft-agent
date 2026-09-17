import com.woof.agent.core.SkillIndex;

/** Таблица навыков обязана совпадать с src/bridge/actions.cjs (applyAction). */
public class TestSkillIndex {
    public static void main(String[] args) {
        int bad = 0;
        // Порядок из actions.cjs: farm,loot,accept,turn_in,sell,gather,craft,heal,equip,buy,frostbolt,fireball,craft_item
        String[] expected = {"farm","loot","accept_quest","turn_in_quest","sell_junk","gather","craft",
                             "heal","equip","buy","cast_frostbolt","cast_fireball","craft_item"};
        for (int i = 0; i < expected.length; i++) {
            int got = SkillIndex.idx(expected[i]);
            if (got != i) { System.out.printf("FAIL  %s: expected idx %d, got %d%n", expected[i], i, got); bad++; }
        }
        // Алиасы архитектуры
        if (SkillIndex.idx("turn_in") != 3) { System.out.println("FAIL  alias turn_in != 3"); bad++; }
        if (SkillIndex.idx("sell") != 4) { System.out.println("FAIL  alias sell != 4"); bad++; }
        // Неизвестный навык обязан падать, а не маппиться куда попало
        try {
            SkillIndex.idx("teleport");
            System.out.println("FAIL  unknown skill did not throw"); bad++;
        } catch (IllegalArgumentException e) { /* ожидаемо */ }
        System.out.println(bad == 0 ? "PASS  TestSkillIndex (13 навыков + алиасы + исключение)"
                                    : "FAIL  TestSkillIndex: " + bad + " проблем");
        System.exit(bad == 0 ? 0 : 1);
    }
}
