import type { GameId } from "./types";

/** Games offered in this event. The engine still supports all four; hidden
    games simply do not appear on the host selection or the audience menu. */
export const VISIBLE_GAMES: GameId[] = ["family_feud", "price_is_right"];
