package com.woof.agent;

/**
 * Bootstrap — полный старт агента.
 *
 * Раньше здесь создавался BridgeServer с зашитым GUID вкладки CDP и
 * GameEnvironment-заглушка, поэтому «Bootstrap» не мог работать в принципе.
 * Теперь: мост поднимается отдельно (Node или Java), а Bootstrap запускает
 * агента против него — тем же кодом, что и VoyagerAgent.
 */
public class Bootstrap {
    public static void main(String[] args) throws Exception {
        System.out.println("[WoOF] Bootstrap v1.0.0");
        VoyagerAgent.main(args);
    }
}
