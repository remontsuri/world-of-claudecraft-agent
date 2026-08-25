# Browser navigation timing contract

Navigation helpers must not issue multiple movement commands against an unchanged browser simulation state. Each movement command must be followed by a browser-side simulation tick before the next position sample.

The navigation loop should therefore be:

1. send one movement/facing command;
2. await one or more browser-side animation frames/game ticks;
3. read the resulting position;
4. calculate progress/stuck state;
5. repeat within the bounded navigation budget.

Do not replace the tick wait with a tight Python/CDP loop. That reduces wall-clock sleep but can repeatedly observe the same simulation state and exhaust the navigation budget without moving the character.
