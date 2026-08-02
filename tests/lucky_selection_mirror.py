"""Python mirror of the frontend lucky-look diversity selection helpers.

Must stay aligned with ``src/cloth_store/web/static/app.js`` — update both together.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any


def lucky_look_signature(look: dict[str, Any]) -> str:
    return "|".join(sorted(piece["catalog_id"] for piece in look["pieces"]))


def lucky_look_key_piece_ids(look: dict[str, Any]) -> list[str]:
    pieces = look["pieces"]
    for kind in ("blazer", "top"):
        match = next((piece for piece in pieces if piece["kind"] == kind), None)
        if match is not None:
            return [match["catalog_id"]]
    return [piece["catalog_id"] for piece in pieces]


def lucky_recent_history_entry(look: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalogIds": [piece["catalog_id"] for piece in look["pieces"]],
        "lookType": look["look_type"],
        "signature": lucky_look_signature(look),
        "keyPieceIds": lucky_look_key_piece_ids(look),
    }


def group_lucky_looks_by_type(looks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_type: dict[str, list[dict[str, Any]]] = {
        "top_bottom": [],
        "blazer_top_bottom": [],
        "blazer_dress": [],
    }
    for look in looks:
        bucket = by_type.get(look["look_type"])
        if bucket is not None:
            bucket.append(look)
    return by_type


def shuffle_array(items: list[Any], rng: random.Random) -> list[Any]:
    copy = items[:]
    for index in range(len(copy) - 1, 0, -1):
        swap_index = rng.randrange(index + 1)
        copy[index], copy[swap_index] = copy[swap_index], copy[index]
    return copy


def filter_lucky_pool(
    pool: list[dict[str, Any]],
    *,
    recent_history: list[dict[str, Any]],
    avoid_look_type: str | None,
) -> list[dict[str, Any]]:
    last_signature = recent_history[0]["signature"] if recent_history else None
    recent_key_pieces = {piece_id for entry in recent_history for piece_id in entry["keyPieceIds"]}

    constraints: list[Callable[[list[dict[str, Any]]], list[dict[str, Any]]]] = [
        lambda looks: (
            [look for look in looks if lucky_look_signature(look) != last_signature]
            if last_signature
            else looks
        ),
        lambda looks: (
            [
                look
                for look in looks
                if not any(
                    catalog_id in recent_key_pieces for catalog_id in lucky_look_key_piece_ids(look)
                )
            ]
            if recent_key_pieces
            else looks
        ),
        lambda looks: (
            [look for look in looks if look["look_type"] != avoid_look_type]
            if avoid_look_type
            else looks
        ),
    ]

    filtered = pool
    for constraint in constraints:
        next_pool = constraint(filtered)
        if next_pool:
            filtered = next_pool
    return filtered


def pick_lucky_look_from_bag(
    type_pool: list[dict[str, Any]],
    *,
    recent_history: list[dict[str, Any]],
    shuffle_bags: dict[str, list[dict[str, Any]]],
    look_type: str,
    rng: random.Random,
) -> dict[str, Any] | None:
    if not type_pool:
        return None

    signatures = {lucky_look_signature(look) for look in type_pool}
    shuffle_bags[look_type] = [
        look for look in shuffle_bags.get(look_type, []) if lucky_look_signature(look) in signatures
    ]
    if not shuffle_bags[look_type]:
        shuffle_bags[look_type] = shuffle_array(type_pool, rng)

    bag = shuffle_bags[look_type]
    last_signature = recent_history[0]["signature"] if recent_history else None
    recent_key_pieces = {piece_id for entry in recent_history for piece_id in entry["keyPieceIds"]}
    bag_size = len(bag)

    for _ in range(bag_size):
        look = bag.pop(0)
        passes_exact = not last_signature or lucky_look_signature(look) != last_signature
        passes_key_pieces = not any(
            catalog_id in recent_key_pieces for catalog_id in lucky_look_key_piece_ids(look)
        )
        if passes_exact and passes_key_pieces:
            return look
        bag.append(look)

    fallback_pool = [
        look
        for look in type_pool
        if not last_signature or lucky_look_signature(look) != last_signature
    ]
    final_pool = fallback_pool or type_pool
    return final_pool[rng.randrange(len(final_pool))]


def pick_lucky_look(
    candidates: list[dict[str, Any]],
    *,
    recent_history: list[dict[str, Any]] | None = None,
    shuffle_bags: dict[str, list[dict[str, Any]]] | None = None,
    seed: int | None = None,
) -> dict[str, Any] | None:
    if not candidates:
        return None

    rng = random.Random(seed)
    history = recent_history or []
    bags: dict[str, list[dict[str, Any]]] = shuffle_bags or {
        "top_bottom": [],
        "blazer_top_bottom": [],
        "blazer_dress": [],
    }
    last_look_type = history[0]["lookType"] if history else None

    pool = filter_lucky_pool(candidates, recent_history=history, avoid_look_type=last_look_type)
    if not pool:
        pool = filter_lucky_pool(candidates, recent_history=history, avoid_look_type=None)
    if not pool:
        last_signature = history[0]["signature"] if history else None
        pool = [
            look
            for look in candidates
            if not last_signature or lucky_look_signature(look) != last_signature
        ]
    if not pool:
        pool = candidates

    by_type = group_lucky_looks_by_type(pool)
    available_types = [look_type for look_type, looks in by_type.items() if looks]
    if not available_types:
        return None

    if last_look_type and len(available_types) > 1:
        alternate_types = [
            look_type for look_type in available_types if look_type != last_look_type
        ]
        if alternate_types:
            available_types = alternate_types

    look_type = available_types[rng.randrange(len(available_types))]
    type_pool = by_type[look_type]
    return pick_lucky_look_from_bag(
        type_pool,
        recent_history=history,
        shuffle_bags=bags,
        look_type=look_type,
        rng=rng,
    )


def simulate_lucky_clicks(
    candidates: list[dict[str, Any]],
    *,
    clicks: int,
    seed: int,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    bags: dict[str, list[dict[str, Any]]] = {
        "top_bottom": [],
        "blazer_top_bottom": [],
        "blazer_dress": [],
    }
    results: list[dict[str, Any]] = []
    click_seed = seed
    for _ in range(clicks):
        look = pick_lucky_look(
            candidates,
            recent_history=history,
            shuffle_bags=bags,
            seed=click_seed,
        )
        assert look is not None
        results.append(look)
        history = [lucky_recent_history_entry(look), *history][:4]
        click_seed += 1
    return results
