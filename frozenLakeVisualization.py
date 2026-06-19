import re
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import helpers

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.LANCZOS

# Extracts at tile from state.
def _extract_at_tile_from_state(state, search_task):
    true_props, _ = state

    for var_index in true_props:
        name = helpers.get_variable_display_name(search_task, var_index)

        match = re.fullmatch(r"at\(tile_(\d+)_(\d+)\)", name)
        if match:
            return int(match.group(1)), int(match.group(2))

    return None


# Extracts at tile from sas state.
def _extract_at_tile_from_sas_state(state_key, sas_task):
    sas_state, _ = state_key

    for var_index, value_index in enumerate(sas_state):
        if var_index >= len(sas_task.variables):
            continue

        values = sas_task.variables[var_index].values
        if value_index < 0 or value_index >= len(values):
            continue

        match = re.fullmatch(r"at\(tile_(\d+)_(\d+)\)", values[value_index])
        if match:
            return int(match.group(1)), int(match.group(2))

    return None


# Draws a legacy policy over a Frozen Lake map.
def draw_policy_on_map(img, policy, search_task, grid_size, tile_size):
    draw = ImageDraw.Draw(img)
    circle_radius = tile_size // 8

    visited_tiles = {}
    tile_state_counts = {}
    transitions = set()

    for state, decision in policy.strategy.items():
        nondet_name, det_actions = decision

        coords = _extract_at_tile_from_state(state, search_task)
        if coords is None:
            continue

        is_collect = nondet_name.startswith("collect")

        previous = visited_tiles.get(coords, False)
        visited_tiles[coords] = previous or is_collect
        tile_state_counts[coords] = tile_state_counts.get(coords, 0) + 1

        for det_action in det_actions:
            successor = helpers.apply_action(state, det_action, search_task)
            successor_coords = _extract_at_tile_from_state(successor, search_task)

            if successor_coords is None or successor_coords == coords:
                continue

            transitions.add((coords, successor_coords))

    print(f"[Info] Generando visualización para {len(visited_tiles)} casillas visitadas...")

    print(f"[Info] Desplazamientos visualizados: {len(transitions)}")

    for origin, destination in sorted(transitions):
        _draw_transition_arrow(
            draw=draw,
            origin=origin,
            destination=destination,
            grid_size=grid_size,
            tile_size=tile_size,
        )

    for (tx, ty), is_collect in visited_tiles.items():
        px, py = _image_position(tx, ty, grid_size, tile_size)

        cx = px + tile_size // 2
        cy = py + tile_size // 2

        bbox = [
            cx - circle_radius,
            cy - circle_radius,
            cx + circle_radius,
            cy + circle_radius,
        ]

        fill_color = (0, 200, 0, 180) if is_collect else (220, 0, 0, 180)
        outline_color = (255, 255, 255, 220)

        draw.ellipse(bbox, fill=fill_color, outline=outline_color, width=3)

        state_count = tile_state_counts.get((tx, ty), 0)
        if state_count > 1:
            _draw_count_badge(
                draw=draw,
                count=state_count,
                center=(cx, cy),
                tile_size=tile_size,
            )


# Draws a SAS policy over a Frozen Lake map.
def draw_sas_policy_on_map(img, policy, sas_task, grid_size, tile_size):
    draw = ImageDraw.Draw(img)
    circle_radius = tile_size // 8

    visited_tiles = {}
    tile_state_counts = {}
    transitions = set()

    for state_key, decision in policy.strategy.items():
        group_key, outcomes = decision

        coords = _extract_at_tile_from_sas_state(state_key, sas_task)
        if coords is None:
            continue

        group_name = group_key[0] if isinstance(group_key, tuple) else str(group_key)
        is_collect = group_name.startswith("collect") or any(
            action.name.startswith("collect") for action, _successor in outcomes
        )

        previous = visited_tiles.get(coords, False)
        visited_tiles[coords] = previous or is_collect
        tile_state_counts[coords] = tile_state_counts.get(coords, 0) + 1

        for action, successor in outcomes:
            if getattr(action, "is_fictitious", False):
                continue

            successor_coords = _extract_at_tile_from_sas_state(successor, sas_task)
            if successor_coords is None or successor_coords == coords:
                continue

            transitions.add((coords, successor_coords))

    print(f"[Info] Generando visualizacion SAS para {len(visited_tiles)} casillas visitadas...")
    print(f"[Info] Desplazamientos visualizados: {len(transitions)}")

    for origin, destination in sorted(transitions):
        _draw_transition_arrow(
            draw=draw,
            origin=origin,
            destination=destination,
            grid_size=grid_size,
            tile_size=tile_size,
        )

    for (tx, ty), is_collect in visited_tiles.items():
        px, py = _image_position(tx, ty, grid_size, tile_size)

        cx = px + tile_size // 2
        cy = py + tile_size // 2

        bbox = [
            cx - circle_radius,
            cy - circle_radius,
            cx + circle_radius,
            cy + circle_radius,
        ]

        fill_color = (0, 200, 0, 180) if is_collect else (220, 0, 0, 180)
        outline_color = (255, 255, 255, 220)

        draw.ellipse(bbox, fill=fill_color, outline=outline_color, width=3)

        state_count = tile_state_counts.get((tx, ty), 0)
        if state_count > 1:
            _draw_count_badge(
                draw=draw,
                count=state_count,
                center=(cx, cy),
                tile_size=tile_size,
            )


# Handles the internal tile center step.
def _tile_center(x, y, grid_size, tile_size):
    px, py = _image_position(x, y, grid_size, tile_size)
    return px + tile_size / 2, py + tile_size / 2


# Handles the internal shorten segment step.
def _shorten_segment(start, end, padding):
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)

    if length <= padding * 2:
        return start, end

    ux = dx / length
    uy = dy / length

    return (
        (sx + ux * padding, sy + uy * padding),
        (ex - ux * padding, ey - uy * padding),
    )


# Draws arrow.
def _draw_arrow(draw, start, end, color, outline_color, width, head_length, head_width):
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)

    if length <= 1:
        return

    ux = dx / length
    uy = dy / length
    bx = ex - ux * head_length
    by = ey - uy * head_length
    px = -uy
    py = ux

    head = [
        (ex, ey),
        (bx + px * head_width / 2, by + py * head_width / 2),
        (bx - px * head_width / 2, by - py * head_width / 2),
    ]

    draw.line([start, end], fill=outline_color, width=width + 5)
    draw.polygon(head, fill=outline_color)
    draw.line([start, end], fill=color, width=width)
    draw.polygon(head, fill=color)


# Draws transition arrow.
def _draw_transition_arrow(draw, origin, destination, grid_size, tile_size):
    start = _tile_center(origin[0], origin[1], grid_size, tile_size)
    end = _tile_center(destination[0], destination[1], grid_size, tile_size)
    start, end = _shorten_segment(start, end, tile_size * 0.22)

    _draw_arrow(
        draw=draw,
        start=start,
        end=end,
        color=(40, 90, 230, 210),
        outline_color=(255, 255, 255, 230),
        width=max(5, tile_size // 16),
        head_length=max(18, tile_size // 5),
        head_width=max(18, tile_size // 4),
    )


# Draws count badge.
def _draw_count_badge(draw, count, center, tile_size):
    cx, cy = center
    radius = max(10, tile_size // 9)
    x = cx + tile_size * 0.15
    y = cy - tile_size * 0.15
    bbox = [
        x - radius,
        y - radius,
        x + radius,
        y + radius,
    ]

    draw.ellipse(bbox, fill=(255, 255, 255, 235), outline=(30, 30, 30, 230), width=2)

    text = str(count)
    font = ImageFont.load_default()
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    draw.text(
        (x - text_width / 2, y - text_height / 2),
        text,
        fill=(30, 30, 30, 255),
        font=font,
    )


# Loads asset.
def _load_asset(assets_dir, filename, max_size=None):
    path = Path(assets_dir) / filename

    if not path.exists():
        print(f"[Warn] No se encontró la imagen {path}.")
        return None

    img = Image.open(path).convert("RGBA")

    if max_size is not None:
        img.thumbnail((max_size, max_size), RESAMPLE)

    return img


# Handles the internal image position step.
def _image_position(x, y, grid_size, tile_size):
    px = x * tile_size
    py = (grid_size - 1 - y) * tile_size
    return px, py


# Pastes centered.
def _paste_centered(base_img, overlay_img, x, y, grid_size, tile_size):
    px, py = _image_position(x, y, grid_size, tile_size)

    ox = px + (tile_size - overlay_img.width) // 2
    oy = py + (tile_size - overlay_img.height) // 2

    base_img.alpha_composite(overlay_img, (ox, oy))


# Builds the Frozen Lake base map image from parsed problem data.
def build_base_map_from_problem(problem_map, assets_dir, tile_size):
    grid_size = problem_map["grid_size"]

    tile_img = _load_asset(assets_dir, "tile.png")
    pit_img = _load_asset(assets_dir, "pit.png", max_size=tile_size)
    wall_img = _load_asset(assets_dir, "wall.png", max_size=tile_size)
    character_img = _load_asset(assets_dir, "character.png", max_size=tile_size)
    goal_img = _load_asset(assets_dir, "goal.png", max_size=tile_size)

    if tile_img is None:
        raise FileNotFoundError("No se encontró frozenLake/tile.png")

    if tile_img.size != (tile_size, tile_size):
        tile_img = tile_img.resize((tile_size, tile_size), RESAMPLE)

    img = Image.new(
        "RGBA",
        (grid_size * tile_size, grid_size * tile_size),
        (255, 255, 255, 0),
    )

    # Fondo común
    for y in range(grid_size):
        for x in range(grid_size):
            px, py = _image_position(x, y, grid_size, tile_size)
            img.alpha_composite(tile_img, (px, py))

    # Casillas especiales
    for (x, y), tile_type in problem_map["tiles"].items():
        if tile_type == "pit" and pit_img is not None:
            _paste_centered(img, pit_img, x, y, grid_size, tile_size)

        elif tile_type == "wall" and wall_img is not None:
            _paste_centered(img, wall_img, x, y, grid_size, tile_size)

    # Goal
    goal_tile = problem_map.get("goal_tile")
    
    if goal_tile is not None and goal_img is not None:
        x, y = goal_tile
        _paste_centered(img, goal_img, x, y, grid_size, tile_size)

    # Rewards
    for reward_name, (x, y) in problem_map["rewards"]:
        reward_img = _load_asset(assets_dir, f"{reward_name}.png", max_size=tile_size)

        if reward_img is not None:
            _paste_centered(img, reward_img, x, y, grid_size, tile_size)

    # Personaje inicial
    if problem_map["character_tile"] is not None and character_img is not None:
        x, y = problem_map["character_tile"]
        _paste_centered(img, character_img, x, y, grid_size, tile_size)

    return img

# Handles the internal tile coords step.
def _tile_coords(name):
    match = re.fullmatch(r"tile_(\d+)_(\d+)", name)
    if not match:
        return None

    return int(match.group(1)), int(match.group(2))

# Extracts goal tile from condition.
def _extract_goal_tile_from_condition(cond):
    if cond is None:
        return None

    cond_name = getattr(cond, "name", None)

    if cond_name == "at":
        terms = list(getattr(cond, "terms", []))
        if len(terms) == 1:
            tile_name = getattr(terms[0], "name", str(terms[0]))
            return _tile_coords(tile_name)

    # Caso típico: goal compuesto con And(...)
    operands = getattr(cond, "operands", None)
    if operands:
        for sub in operands:
            coords = _extract_goal_tile_from_condition(sub)
            if coords is not None:
                return coords

    return None

# Extracts tiles, walls, pits, rewards, and start/goal data from a problem.
def extract_map_from_parsed_problem(problem):
    tiles = {}
    rewards = []
    character_tile = None
    goal_tile = _extract_goal_tile_from_condition(getattr(problem, "goal", None))
    
    max_x = 0
    max_y = 0

    # 1) Objetos y tipos: tile_0_5 - ice / pit / wall
    for obj in problem.objects:
        name = getattr(obj, "name", str(obj))
        coords = _tile_coords(name)

        if coords is None:
            continue

        obj_type = getattr(obj, "type_tag", None)

        x, y = coords
        tiles[(x, y)] = str(obj_type)

        max_x = max(max_x, x)
        max_y = max(max_y, y)

    # 2) Hechos iniciales: at(...) y reward-position(...)
    for fact in problem.init:
        fact_name = getattr(fact, "name", None)

        if fact_name == "at":
            terms = list(getattr(fact, "terms", []))
            if len(terms) == 1:
                tile_name = getattr(terms[0], "name", str(terms[0]))
                character_tile = _tile_coords(tile_name)

        elif fact_name == "reward-position":
            terms = list(getattr(fact, "terms", []))
            if len(terms) == 2:
                reward_name = getattr(terms[0], "name", str(terms[0]))
                tile_name = getattr(terms[1], "name", str(terms[1]))

                coords = _tile_coords(tile_name)
                if coords is not None:
                    rewards.append((reward_name, coords))

    grid_size = max(max_x, max_y) + 1

    return {
        "tiles": tiles,
        "rewards": rewards,
        "character_tile": character_tile,
        "goal_tile": goal_tile,
        "grid_size": grid_size,
    }


# Generates a PNG visualization for a SAS policy.
def generate_sas_policy_visualization(
    problem,
    policy,
    sas_task,
    output_image_path,
    assets_dir="frozenLake",
    tile_size=125,
):
    try:
        problem_map = extract_map_from_parsed_problem(problem)

        img = build_base_map_from_problem(
            problem_map=problem_map,
            assets_dir=assets_dir,
            tile_size=tile_size,
        )

        draw_sas_policy_on_map(
            img=img,
            policy=policy,
            sas_task=sas_task,
            grid_size=problem_map["grid_size"],
            tile_size=tile_size,
        )

        img.save(output_image_path, "PNG")

    except Exception as e:
        print(f"[Error] No se pudo generar la visualizacion SAS FrozenLake: {e}")


# Generates a PNG visualization for a legacy policy.
def generate_policy_visualization(
    problem,
    policy,
    search_task,
    output_image_path,
    assets_dir="frozenLake",
    tile_size=125,
):
    try:
        problem_map = extract_map_from_parsed_problem(problem)

        img = build_base_map_from_problem(
            problem_map=problem_map,
            assets_dir=assets_dir,
            tile_size=tile_size,
        )

        draw_policy_on_map(
            img=img,
            policy=policy,
            search_task=search_task,
            grid_size=problem_map["grid_size"],
            tile_size=tile_size,
        )

        img.save(output_image_path, "PNG")

    except Exception as e:
        print(f"[Error] No se pudo generar la visualización FrozenLake: {e}")
