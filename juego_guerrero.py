#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Duelo 3D de gladiadores en el Coliseo."""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path
from typing import Any, Optional

from PIL import Image as PILImage
from panda3d.core import MaterialAttrib, NodePath, Vec3, loadPrcFileData
from direct.actor.Actor import Actor
import gltf
from ursina import (
    AmbientLight,
    Button,
    DirectionalLight,
    Entity,
    Text,
    Texture,
    Ursina,
    camera,
    color,
    held_keys,
    scene,
    time,
    window,
)
from ursina.models.procedural.cylinder import Cylinder
from ursina.shaders.lit_with_shadows_shader import lit_with_shadows_shader


ANIMATIONS = (
    "Idle", "Walk", "Run", "Attack", "Attack_Overhead", "Attack_Thrust",
    "Jump_Crouch", "Jump_Air", "Jump_Land", "Block", "Hit", "Death",
)
ATTACK_STYLES = ("Attack", "Attack_Overhead", "Attack_Thrust")
ARENA_LIMIT = 18.0
MAX_HEALTH = 100

INK = color.rgb32(22, 29, 38)
PAPER = color.rgb32(242, 224, 190)
MARBLE = color.rgb32(201, 177, 137)
GOLD = color.rgb32(232, 174, 79)
OXBLOOD = color.rgb32(133, 44, 43)
TEAL = color.rgb32(50, 195, 183)
SAND = color.rgb32(187, 139, 89)
CYLINDER_MODEL = Cylinder(24, start=-0.5)
PLAYER_MODEL_YAW_OFFSET = 180.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Comprueba que el modelo y la escena carguen sin abrir una ventana.",
    )
    parser.add_argument(
        "--pbr-preview",
        action="store_true",
        help="Activa una vista previa PBR de los personajes con materiales glTF.",
    )
    return parser.parse_args()


def add_block(
    position: tuple[float, float, float],
    scale: tuple[float, float, float],
    tint: Any,
    rotation_y: float = 0,
) -> Entity:
    return Entity(
        parent=scene,
        model="cube",
        position=position,
        scale=scale,
        rotation_y=rotation_y,
        color=tint,
    )


def heading_for_move(direction: Vec3) -> float:
    """Alinea el frente del modelo importado con la dirección de movimiento."""
    yaw = math.degrees(math.atan2(direction.x, direction.z))
    return (yaw + PLAYER_MODEL_YAW_OFFSET) % 360.0


def turn_towards(current: float, target: float, response: float) -> float:
    difference = (target - current + 180.0) % 360.0 - 180.0
    return (current + difference * min(1.0, response)) % 360.0


class GladiatorGame(Entity):
    def __init__(self, pbr_preview: bool = False) -> None:
        super().__init__()
        self.pbr_preview = pbr_preview
        self.is_paused = False
        self.is_finished = False
        self.match_started = False
        self.selected_character = "Spartaco"
        self.elapsed = 0.0
        self.player_health = MAX_HEALTH
        self.cpu_health = MAX_HEALTH
        self.player_points = 0
        self.cpu_points = 0
        self.attack_cooldown = 0.0
        self.cpu_attack_cooldown = 0.0
        self.player_windup = 0.0
        self.cpu_windup = 0.0
        self.player_jump_velocity = 0.0
        self.cpu_jump_velocity = 0.0
        self.player_jump_windup = 0.0
        self.player_landing_time = 0.0
        self.cpu_velocity = Vec3(0, 0, 0)
        self.player_blocking = False
        self.cpu_block_timer = 0.0
        self.player_animation_time = 0.0
        self.cpu_animation_time = 0.0
        self.player_velocity = Vec3(0, 0, 0)
        self.player_attack_side = 1
        self.cpu_attack_side = 1
        self.blood_effects: list[dict[str, Any]] = []
        self.active_animation = ""
        self.cpu_active_animation = ""
        self.player_attack_style = 0
        self.cpu_attack_style = 0
        # El menú no necesita la arena 3D. Construirla al abrir el juego
        # retrasaba la selección mientras se creaban cientos de entidades.
        self.arena_built = False
        self._build_hud()
        self._build_selection_screen()
        self._selection_camera()

    def _build_arena(self) -> None:
        window.color = color.rgb32(126, 164, 188)
        window.title = "GLADIUS · duelo en el Coliseo"
        scene.fog_color = color.rgb32(159, 178, 184)
        scene.fog_density = 0.006

        AmbientLight(color=color.rgba32(126, 113, 102, 255))
        key_light = DirectionalLight()
        key_light.color = color.rgba32(255, 231, 190, 255)
        key_light.look_at(Vec3(1, -2, 1))

        Entity(
            model="plane",
            position=(0, -0.42, 0),
            scale=(120, 1, 120),
            color=color.rgb32(137, 116, 92),
        )
        Entity(
            model=CYLINDER_MODEL,
            position=(0, -0.18, 0),
            scale=(44, 0.48, 44),
            color=MARBLE,
        )
        Entity(
            model=CYLINDER_MODEL,
            position=(0, 0.04, 0),
            scale=(38, 0.06, 38),
            color=SAND,
        )
        Entity(
            model=CYLINDER_MODEL,
            position=(0, 0.075, 0),
            scale=(35, 0.025, 35),
            color=color.rgb32(194, 146, 94),
        )

        # La arena gana variación de tono con pequeños granos y huellas de uso.
        # Semilla fija para que la distribución sea idéntica en cada partida.
        rng = random.Random(120)
        sand_tones = (
            color.rgb32(181, 132, 81),
            color.rgb32(211, 163, 105),
            color.rgb32(164, 117, 73),
            color.rgb32(196, 148, 96),
        )
        for _ in range(90):
            radius = rng.uniform(3.2, 17.2)
            angle = rng.uniform(0, math.tau)
            size = rng.uniform(0.045, 0.16)
            Entity(
                model="sphere",
                position=(radius * math.cos(angle), 0.095, radius * math.sin(angle)),
                scale=(size * 1.5, 0.012, size),
                color=sand_tones[rng.randrange(len(sand_tones))],
            )

        # Adoquines de travertino delimitan el pasillo junto a las gradas.
        for index in range(64):
            angle = math.tau * index / 64
            radius = 18.7
            add_block(
                (radius * math.cos(angle), 0.12, radius * math.sin(angle)),
                (0.46, 0.11, 0.88),
                color.rgb32(167, 143, 112) if index % 3 else color.rgb32(139, 119, 95),
                rotation_y=-math.degrees(angle),
            )

        # Anillos dorados y oscuros marcan la pista de entrenamiento.
        for radius, tint in ((5.0, GOLD), (5.18, OXBLOOD), (12.0, MARBLE)):
            self._make_ring(radius, 48, tint)

        self._build_colosseum()
        self._build_banners()
        self._build_audience()
        self._build_torches()

    def _make_ring(self, radius: float, segments: int, tint: Any) -> None:
        for index in range(segments):
            angle = math.tau * index / segments
            add_block(
                (radius * math.cos(angle), 0.115, radius * math.sin(angle)),
                (0.18, 0.035, radius * math.tau / segments * 1.15),
                tint,
                rotation_y=-math.degrees(angle),
            )

    def _build_colosseum(self) -> None:
        # Tres arcadas elípticas superpuestas alrededor de la arena.
        for tier, radius in enumerate((22.6, 24.4, 26.1)):
            base_y = (0.1, 4.1, 8.0)[tier]
            column_h = (4.0, 3.9, 3.6)[tier]
            count = 18
            for index in range(count):
                angle = math.tau * index / count
                x, z = radius * math.cos(angle), radius * math.sin(angle)
                add_block(
                    (x, base_y + column_h / 2, z),
                    (0.6, column_h, 0.68),
                    (MARBLE, color.rgb32(181, 153, 118), PAPER)[(index + tier) % 3],
                    rotation_y=-math.degrees(angle),
                )
                add_block(
                    (x, base_y + column_h, z),
                    (0.92, 0.3, 0.92),
                    GOLD if index % 4 == 0 else MARBLE,
                    rotation_y=-math.degrees(angle),
                )

            # Dovelas poligonales que sugieren los arcos romanos.
            for index in range(count):
                angle = math.tau * (index + 0.5) / count
                x, z = radius * math.cos(angle), radius * math.sin(angle)
                add_block(
                    (x, base_y + column_h - 0.03, z),
                    (1.35, 0.42, 0.48),
                    color.rgb32(164, 132, 99),
                    rotation_y=-math.degrees(angle),
                )

        # Build the ledges as separate radial stones. A solid cylinder here
        # would become an opaque roof over the arena and block the game camera.
        for tier, radius in enumerate((23.5, 25.2, 26.2)):
            tier_y = (4.16, 8.12, 11.7)[tier]
            for index in range(18):
                angle = math.tau * (index + 0.5) / 18
                x, z = radius * math.cos(angle), radius * math.sin(angle)
                add_block(
                    (x, tier_y, z),
                    (0.34, 0.24, radius * math.tau / 18 * 1.04),
                    color.rgb32(165, 136, 103),
                    rotation_y=-math.degrees(angle),
                )

        # Plinto, espina central y mosaico del emblema.
        Entity(
            model=CYLINDER_MODEL,
            position=(0, 0.13, 0),
            scale=(5.4, 0.12, 5.4),
            color=INK,
        )
        Entity(
            model=CYLINDER_MODEL,
            position=(0, 0.205, 0),
            scale=(4.95, 0.06, 4.95),
            color=GOLD,
        )
        for index in range(12):
            angle = math.tau * index / 12
            add_block(
                (2.1 * math.cos(angle), 0.25, 2.1 * math.sin(angle)),
                (0.2, 0.025, 1.1),
                OXBLOOD if index % 2 else PAPER,
                rotation_y=-math.degrees(angle),
            )

    def _build_banners(self) -> None:
        for angle in range(0, 360, 60):
            radians = math.radians(angle)
            x, z = 20.8 * math.cos(radians), 20.8 * math.sin(radians)
            add_block((x, 3.45, z), (0.12, 4.8, 0.12), INK, rotation_y=-angle)
            add_block((x, 2.45, z - 0.12), (0.8, 1.9, 0.12), OXBLOOD, rotation_y=-angle)
            Entity(
                model="sphere",
                position=(x, 1.6, z - 0.2),
                scale=(0.12, 0.12, 0.1),
                color=GOLD,
            )

    def _build_audience(self) -> None:
        crowd_colors = (OXBLOOD, TEAL, GOLD, INK, PAPER)
        for row, radius in enumerate((20.1, 22.8, 25.3)):
            for index in range(20):
                angle = math.tau * (index + 0.35 * (row % 2)) / 20
                x, z = radius * math.cos(angle), radius * math.sin(angle)
                y = 1.15 + row * 3.9
                Entity(
                    model="sphere",
                    position=(x, y, z),
                    scale=(0.32, 0.38, 0.3),
                    color=color.rgb32(181, 137, 101),
                )
                Entity(
                    model="sphere",
                    position=(x, y - 0.38, z),
                    scale=(0.46, 0.52, 0.34),
                    color=crowd_colors[(index + row * 2) % len(crowd_colors)],
                )

    def _build_torches(self) -> None:
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            x, z = 18.2 * math.cos(radians), 18.2 * math.sin(radians)
            Entity(
                model=CYLINDER_MODEL,
                position=(x, 1.05, z),
                scale=(0.22, 1.8, 0.22),
                color=INK,
            )
            Entity(
                model="sphere",
                position=(x, 2.1, z),
                scale=(0.28, 0.5, 0.28),
                color=color.rgb32(255, 153, 53),
            )
            Entity(
                model="sphere",
                position=(x, 2.18, z),
                scale=(0.15, 0.32, 0.15),
                color=color.rgb32(255, 226, 144),
            )

    @staticmethod
    def _load_actor(model_path: Path, pbr_preview: bool = False) -> Actor:
        if not model_path.is_file():
            raise FileNotFoundError(f"No encuentro el modelo 3D: {model_path}")
        model_root = NodePath(
            gltf.load_model(
                str(model_path),
                gltf.GltfSettings(legacy_materials=not pbr_preview),
            )
        )
        # El shader de escena de Ursina usa el atributo de color por vértice y
        # omite MaterialAttrib. Copiamos el diffuse de cada pieza a ColorAttrib
        # para que el modelo conserve su paleta también con ese shader.
        if not pbr_preview:
            for geom_path in model_root.findAllMatches("**/+GeomNode"):
                geom_node = geom_path.node()
                if geom_node.getNumGeoms() == 0:
                    continue
                geom_state = geom_node.getGeomState(0)
                if geom_state.hasAttrib(MaterialAttrib):
                    diffuse = geom_state.getAttrib(MaterialAttrib).getMaterial().getDiffuse()
                    geom_path.setColor(diffuse)
        actor = Actor(model_root, copy=False)
        missing = set(ANIMATIONS).difference(actor.getAnimNames())
        if missing:
            actor.cleanup()
            raise RuntimeError(f"El modelo no contiene estas animaciones: {', '.join(sorted(missing))}")
        return actor

    def _fighter_info(self, fighter: str) -> tuple[str, str, str]:
        project = Path(__file__).resolve().parent
        root = project / "build" / "animation_preview"
        portrait_root = project / "build" / "revised"
        if fighter == "Spartaco":
            return "Spartaco", str(root / "Guerrero_Player.glb"), str(portrait_root / "Spartaco_menu.png")
        return "Chaca_Zulo", str(root / "Principe_Guerrero_Africano.glb"), str(portrait_root / "Chaca_Zulo_menu.png")

    def _build_selection_screen(self) -> None:
        self.selection_screen = Entity(parent=camera.ui, enabled=True)
        Entity(
            parent=self.selection_screen,
            model="quad",
            scale=(2, 2),
            color=color.rgba32(9, 13, 22, 242),
        )
        Entity(
            parent=self.selection_screen,
            model="quad",
            scale=(1.42, 0.88),
            color=color.rgba32(20, 28, 42, 248),
        )
        Text(
            parent=self.selection_screen,
            text="GLADIUS",
            y=0.36,
            origin=(0, 0),
            scale=2.2,
            color=GOLD,
        )
        Text(
            parent=self.selection_screen,
            text="ELIGE A TU LUCHADOR",
            y=0.27,
            origin=(0, 0),
            scale=0.95,
            color=PAPER,
        )
        self.selection_cards: dict[str, Entity] = {}
        self.selection_frames: dict[str, Entity] = {}
        self.selection_names: dict[str, Text] = {}
        for fighter, x in (("Spartaco", -0.34), ("Chaca_Zulo", 0.34)):
            _, _, preview_path = self._fighter_info(fighter)
            image_path = Path(preview_path)
            if not image_path.is_file():
                raise FileNotFoundError(f"No encuentro el retrato del luchador: {image_path}")
            try:
                with PILImage.open(image_path) as source_image:
                    portrait_texture = Texture(source_image.convert("RGBA"))
            except Exception as error:
                raise RuntimeError(f"No se pudo cargar el retrato: {image_path}") from error

            # El marco y el fondo quedan debajo del botón que muestra el retrato.
            frame = Entity(
                parent=self.selection_screen,
                model="quad",
                position=(x, 0.02, 0.04),
                scale=(0.515, 0.535),
                color=color.rgb32(76, 89, 106, 255),
            )
            Entity(
                parent=self.selection_screen,
                model="quad",
                position=(x, 0.02, 0.02),
                scale=(0.5, 0.52),
                color=color.rgba32(38, 50, 67, 255),
            )
            card = Button(
                parent=self.selection_screen,
                model="quad",
                text="",
                position=(x, 0.065, 0),
                scale=(0.335, 0.388),
                texture=portrait_texture,
                color=color.white,
                highlight_color=color.white,
                pressed_color=color.white,
            )
            card.on_click = lambda selected=fighter: self.select_character(selected)
            card.on_mouse_enter = lambda selected=fighter: self._highlight_character(selected, True)
            card.on_mouse_exit = lambda selected=fighter: self._highlight_character(selected, False)
            self.selection_cards[fighter] = card
            self.selection_frames[fighter] = frame
            self.selection_names[fighter] = Text(
                parent=self.selection_screen,
                text=fighter.upper(),
                position=(x, -0.175),
                origin=(0, 0),
                scale=0.95,
                color=PAPER,
            )
            self._button(
                "ELEGIR",
                (x, -0.23),
                lambda selected=fighter: self.select_character(selected),
                parent=self.selection_screen,
                scale=(0.22, 0.065),
            )
        Text(
            parent=self.selection_screen,
            text="JUGADOR VS COMPUTADORA  ·  DUELO A PRIMER KO",
            y=-0.34,
            origin=(0, 0),
            scale=0.66,
            color=TEAL,
        )
        self.fight_button = self._button(
            "INICIAR PELEA",
            (0, -0.41),
            self.start_match,
            parent=self.selection_screen,
            scale=(0.32, 0.075),
        )
        self.select_character("Spartaco")

    def select_character(self, fighter: str) -> None:
        if fighter not in self.selection_cards:
            return
        self.selected_character = fighter
        for name, card in self.selection_cards.items():
            # Keep the image untinted; selection is shown in the player label.
            card.color = color.white
            self.selection_frames[name].color = (
                GOLD if name == fighter else color.rgb32(76, 89, 106, 255)
            )
            self.selection_names[name].text = f"{name.upper()}  ·  JUGADOR" if name == fighter else name.upper()

    def _highlight_character(self, fighter: str, hovering: bool) -> None:
        if fighter not in self.selection_frames:
            return
        if fighter == self.selected_character:
            self.selection_frames[fighter].color = GOLD
        else:
            self.selection_frames[fighter].color = (
                TEAL if hovering else color.rgb32(76, 89, 106, 255)
            )

    def _selection_camera(self) -> None:
        camera.position = (0, 12, -31)
        camera.fov = 68
        camera.look_at((0, 1, 0))

    def _spawn_fighters(self) -> None:
        if hasattr(self, "player"):
            self.actor.cleanup()
            self.cpu_actor.cleanup()
            self.player.disable()
            self.cpu.disable()
        player_name, player_path, _ = self._fighter_info(self.selected_character)
        cpu_name = "Chaca_Zulo" if player_name == "Spartaco" else "Spartaco"
        _, cpu_path, _ = self._fighter_info(cpu_name)
        self.player_name = player_name
        self.cpu_name = cpu_name
        self.actor = self._load_actor(Path(player_path), self.pbr_preview)
        self.cpu_actor = self._load_actor(Path(cpu_path), self.pbr_preview)
        fighter_shader = None if self.pbr_preview else lit_with_shadows_shader
        self.player = Entity(model=self.actor, position=(-3.2, 0.1, 0), scale=1, shader=fighter_shader)
        self.cpu = Entity(model=self.cpu_actor, position=(3.2, 0.1, 0), scale=1, shader=fighter_shader)
        self.actor.loop("Idle", restart=True)
        self.cpu_actor.loop("Idle", restart=True)
        self.active_animation = ""
        self.player.rotation_y = heading_for_move(self.cpu.position - self.player.position)
        self.cpu.rotation_y = heading_for_move(self.player.position - self.cpu.position)

    def start_match(self) -> None:
        if not self.arena_built:
            self._build_arena()
            self.arena_built = True
        self._spawn_fighters()
        self.selection_screen.enabled = False
        self.fight_hud.enabled = True
        self.match_started = True
        self.is_paused = False
        self.is_finished = False
        self.player_health = MAX_HEALTH
        self.cpu_health = MAX_HEALTH
        self.player_points = 0
        self.cpu_points = 0
        self.elapsed = 0.0
        self.attack_cooldown = 0.0
        self.cpu_attack_cooldown = 0.8
        self.player_attack_side = 1
        self.cpu_attack_side = 1
        self.player_windup = 0.0
        self.cpu_windup = 0.0
        self.player_jump_velocity = 0.0
        self.cpu_jump_velocity = 0.0
        self.player_blocking = False
        self.cpu_block_timer = 0.0
        self.player_velocity = Vec3(0, 0, 0)
        self._refresh_hud()
        self._reset_camera()

    def _build_hud(self) -> None:
        self.fight_hud = Entity(parent=camera.ui, enabled=False)
        # Los fondos y el contenido son hermanos: el tama?o del panel no encoge
        # los textos, las barras ni los botones.
        left_panel = Entity(parent=self.fight_hud, model="quad", position=(-0.45, 0.43), scale=(0.4, 0.11), color=color.rgba32(13, 20, 33, 238))
        right_panel = Entity(parent=self.fight_hud, model="quad", position=(0.45, 0.43), scale=(0.4, 0.11), color=color.rgba32(13, 20, 33, 238))
        Text(parent=self.fight_hud, text="JUGADOR  /  P1", position=(-0.45, 0.465), origin=(0, 0), scale=0.5, color=TEAL)
        Text(parent=self.fight_hud, text="RIVAL  /  CPU", position=(0.45, 0.465), origin=(0, 0), scale=0.5, color=GOLD)
        self.player_name_text = Text(parent=self.fight_hud, text="SPARTACO", position=(-0.51, 0.425), origin=(0, 0), scale=0.6, color=PAPER)
        self.cpu_name_text = Text(parent=self.fight_hud, text="CHACA ZULO", position=(0.36, 0.425), origin=(0, 0), scale=0.6, color=PAPER)
        self.player_health_text = Text(parent=self.fight_hud, text="100%", position=(-0.27, 0.425), origin=(0.5, 0), scale=0.6, color=TEAL)
        self.cpu_health_text = Text(parent=self.fight_hud, text="100%", position=(0.63, 0.425), origin=(0.5, 0), scale=0.6, color=GOLD)
        Entity(parent=self.fight_hud, model="quad", position=(-0.45, 0.385), scale=(0.34, 0.016), color=color.rgb32(49, 58, 69))
        Entity(parent=self.fight_hud, model="quad", position=(0.45, 0.385), scale=(0.34, 0.016), color=color.rgb32(49, 58, 69))
        self.player_health_bar = Entity(parent=self.fight_hud, model="quad", origin=(-0.5, 0), position=(-0.62, 0.385), scale=(0.34, 0.016), color=TEAL)
        self.cpu_health_bar = Entity(parent=self.fight_hud, model="quad", origin=(0.5, 0), position=(0.62, 0.385), scale=(0.34, 0.016), color=OXBLOOD)
        self.timer_text = Text(parent=self.fight_hud, text="00:00", origin=(0, 0), position=(0, 0.465), scale=0.6, color=PAPER)
        self.score_text = Text(parent=self.fight_hud, text="0000  VS  0000", origin=(0, 0), y=0.28, scale=0.72, color=PAPER)
        self.round_text = Text(parent=self.fight_hud, text="ARENA  /  COMBATE", origin=(0, 0), y=0.22, scale=0.52, color=GOLD)
        self.status_text = Text(parent=self.fight_hud, text="PREPARADOS", origin=(0, 0), y=-0.29, scale=0.72, color=TEAL)
        self.help_text = Text(parent=self.fight_hud, text="W/S AVANZAR-RETROCEDER  A/D DESPLAZARSE  MAYUS CORRER  ESPACIO SALTAR\nE/F CICLO DE 3 ATAQUES     Q CUBRIRSE     ESC PAUSA     R REINICIAR", origin=(0, 0), y=-0.445, scale=0.47, color=PAPER)
        self.pause_button = self._button("PAUSA", (0.73, 0.465), self.toggle_pause, parent=self.fight_hud, scale=(0.11, 0.045))
        self.reset_button = self._button("REINICIAR", (0.73, 0.395), self.reset_game, parent=self.fight_hud, scale=(0.11, 0.045))

        self.overlay = Entity(parent=camera.ui, enabled=False)
        Entity(parent=self.overlay, model="quad", scale=(0.62, 0.38), color=color.rgba32(12, 17, 28, 248))
        self.overlay_title = Text(
            text="",
            parent=self.overlay,
            origin=(0, 0),
            y=0.09,
            scale=1.2,
            color=GOLD,
        )
        self.overlay_body = Text(
            text="",
            parent=self.overlay,
            origin=(0, 0),
            y=-0.005,
            scale=0.75,
            color=PAPER,
        )
        self.overlay_button = self._button("CONTINUAR", (-0.17, -0.12), self.toggle_pause, parent=self.overlay, scale=(0.22, 0.06))
        self.menu_button = self._button("CAMBIAR LUCHADOR", (0.17, -0.12), self.return_to_selection, parent=self.overlay, scale=(0.28, 0.06))

    def _button(
        self,
        label: str,
        position: tuple[float, float],
        callback: Any,
        parent: Entity = camera.ui,
        scale: tuple[float, float] = (0.16, 0.06),
    ) -> Button:
        button = Button(
            parent=parent,
            text=label,
            position=position,
            scale=scale,
            color=INK,
            highlight_color=OXBLOOD,
            pressed_color=GOLD,
            text_color=PAPER,
            text_scale=0.72,
        )
        button.on_click = callback
        return button

    def _reset_camera(self) -> None:
        center = (self.player.position + self.cpu.position) * 0.5
        camera.position = (center.x, 4.5, center.z - 8.8)
        camera.fov = 59
        camera.look_at(center + Vec3(0, 1.1, 0))

    def _play_animation(self, name: str, loop: bool = True) -> None:
        if name == self.active_animation:
            return
        if name not in self.actor.getAnimNames():
            raise RuntimeError(f"Animación desconocida en el modelo: {name}")
        if self.active_animation in ATTACK_STYLES:
            self.actor.setPlayRate(1, self.active_animation)
        self.active_animation = name
        preview_rates = {"Jump_Crouch": 1.45, "Jump_Air": 1.12, "Jump_Land": 1.85}
        if name in preview_rates:
            self.actor.setPlayRate(preview_rates[name], name)
        if loop:
            self.actor.loop(name, restart=True)
        else:
            self.actor.play(name)

    def _play_cpu_animation(self, name: str, loop: bool = True) -> None:
        if name not in self.cpu_actor.getAnimNames():
            return
        if name == self.cpu_active_animation:
            return
        self.cpu_active_animation = name
        if loop:
            self.cpu_actor.loop(name, restart=True)
        else:
            self.cpu_actor.play(name)

    def _play_sword_swing(self, side: int, animation: str = "Attack") -> None:
        frames = max(1, self.actor.getNumFrames(animation))
        durations = {"Attack": 0.94, "Attack_Overhead": 1.10, "Attack_Thrust": 0.92}
        play_rate = max(0.8, (frames - 1) / 30.0 / durations[animation])
        self.active_animation = animation
        if animation == "Attack" and side < 0:
            self.actor.setPlayRate(-play_rate, animation)
            self.actor.play(animation, fromFrame=frames - 1, toFrame=0)
        else:
            self.actor.setPlayRate(play_rate, animation)
            self.actor.play(animation, fromFrame=0, toFrame=frames - 1)

    def _play_cpu_sword_swing(self, side: int, animation: str = "Attack") -> None:
        frames = max(1, self.cpu_actor.getNumFrames(animation))
        durations = {"Attack": 0.98, "Attack_Overhead": 1.12, "Attack_Thrust": 0.94}
        play_rate = max(0.8, (frames - 1) / 30.0 / durations[animation])
        self.cpu_active_animation = animation
        if animation == "Attack" and side < 0:
            self.cpu_actor.setPlayRate(-play_rate, animation)
            self.cpu_actor.play(animation, fromFrame=frames - 1, toFrame=0)
        else:
            self.cpu_actor.setPlayRate(play_rate, animation)
            self.cpu_actor.play(animation, fromFrame=0, toFrame=frames - 1)

    def attack(self, side: int = 1) -> None:
        if not self.match_started or self.is_paused or self.is_finished or self.attack_cooldown > 0 or self.player_blocking:
            return
        style_index = self.player_attack_style
        animation = ATTACK_STYLES[style_index]
        self.player_attack_style = (style_index + 1) % len(ATTACK_STYLES)
        windups = (0.38, 0.42, 0.36)
        durations = (0.94, 1.10, 0.92)
        cooldowns = (0.82, 0.98, 0.86)
        self.attack_cooldown = cooldowns[style_index]
        self.player_windup = windups[style_index]
        self.player_animation_time = durations[style_index]
        self._play_sword_swing(side, animation)
        labels = ("TAJO LATERAL", "GOLPE DESCENDENTE", "ESTOCADA")
        self.status_text.text = f"{labels[style_index]}  >" if side > 0 else f"<  {labels[style_index]}"
        self.status_text.color = GOLD

    def _spawn_blood_burst(self, defender: Entity) -> None:
        origin = defender.position + Vec3(0, 1.15, 0)
        for _ in range(8):
            particle = Entity(
                parent=scene,
                model="sphere",
                position=origin + Vec3(random.uniform(-0.18, 0.18), random.uniform(-0.12, 0.2), random.uniform(-0.16, 0.16)),
                scale=random.uniform(0.035, 0.075),
                color=color.rgba32(157, 24, 31, 245),
            )
            particle_velocity = Vec3(random.uniform(-1.8, 1.8), random.uniform(0.8, 3.4), random.uniform(-1.8, 1.8))
            self.blood_effects.append({"entity": particle, "velocity": particle_velocity, "life": random.uniform(0.38, 0.62), "duration": 0.62})

    def _update_blood_effects(self, dt: float) -> None:
        alive: list[dict[str, Any]] = []
        for effect in self.blood_effects:
            effect["life"] -= dt
            particle = effect["entity"]
            if effect["life"] <= 0:
                particle.disable()
                continue
            velocity = effect["velocity"]
            velocity.y -= 7.5 * dt
            particle.position += velocity * dt
            alpha = int(245 * effect["life"] / effect["duration"])
            particle.color = color.rgba32(157, 24, 31, alpha)
            particle.scale *= max(0.0, 1.0 - dt * 1.7)
            alive.append(effect)
        self.blood_effects = alive

    def jump(self) -> None:
        if (
            self.match_started
            and not self.is_paused
            and not self.is_finished
            and self.player.y <= 0.101
            and self.player_jump_windup <= 0
            and self.player_landing_time <= 0
            and self.player_jump_velocity == 0
        ):
            self.player_jump_windup = 0.20
            self.player_animation_time = 0.20
            self._play_animation("Jump_Crouch", loop=False)

    def _resolve_attack(self, from_player: bool) -> None:
        attacker = self.player if from_player else self.cpu
        defender = self.cpu if from_player else self.player
        distance = (defender.position - attacker.position).length()
        if distance > 2.55:
            if from_player:
                self.status_text.text = "FUERA DE ALCANCE"
                self.status_text.color = PAPER
            return

        attacker_yaw = self.player.rotation_y if from_player else self.cpu.rotation_y
        target_direction = defender.position - attacker.position
        target_yaw = heading_for_move(Vec3(target_direction.x, 0, target_direction.z))
        yaw_error = abs((target_yaw - attacker_yaw + 180.0) % 360.0 - 180.0)
        if yaw_error > 105.0:
            if from_player:
                self.status_text.text = "EL TAJO NO ALCANZA"
                self.status_text.color = PAPER
            return

        blocked = self.cpu_block_timer > 0 if from_player else self.player_blocking
        if blocked:
            defender_yaw = self.cpu.rotation_y if from_player else self.player.rotation_y
            defender_direction = attacker.position - defender.position
            block_yaw = heading_for_move(Vec3(defender_direction.x, 0, defender_direction.z))
            block_error = abs((block_yaw - defender_yaw + 180.0) % 360.0 - 180.0)
            blocked = block_error <= 105.0
        damage = 7 if blocked else 18
        if from_player:
            self.cpu_health = max(0, self.cpu_health - damage)
            self.player_points += 25 if blocked else 100
            self._play_cpu_animation("Block" if blocked else "Hit", loop=False)
            self.cpu_animation_time = 0.45
            self.status_text.text = "GOLPE BLOQUEADO" if blocked else "¡IMPACTO!"
        else:
            self.player_health = max(0, self.player_health - damage)
            self.cpu_points += 25 if blocked else 100
            if not blocked:
                self._play_animation("Block" if blocked else "Hit", loop=False)
                self.player_animation_time = 0.45
            self.status_text.text = "CUBRISTE EL GOLPE" if blocked else "¡TE ALCANZÓ!"
        if not blocked:
            self._spawn_blood_burst(defender)
        self.status_text.color = TEAL if blocked else GOLD
        self._refresh_hud()
        self._check_victory()

    def _check_victory(self) -> None:
        if self.player_health <= 0 or self.cpu_health <= 0:
            winner = self.cpu_name if self.player_health <= 0 else self.player_name
            self.finish_game(winner)

    def toggle_pause(self) -> None:
        if not self.match_started or self.is_finished:
            return
        self.is_paused = not self.is_paused
        self.overlay.enabled = self.is_paused
        self.overlay_title.text = "PAUSA" if self.is_paused else ""
        self.overlay_body.text = (
            "El entrenamiento esta detenido.\nPulsa ESC o CONTINUAR para volver."
            if self.is_paused
            else ""
        )
        self.pause_button.text = "SEGUIR" if self.is_paused else "PAUSA"
        self.overlay_button.text = "CONTINUAR" if self.is_paused else "CONTINUAR"
        self.overlay_button.on_click = self.toggle_pause
        if self.is_paused:
            self.actor.stop()
            self.cpu_actor.stop()
        else:
            self.active_animation = ""
            self.cpu_active_animation = ""
            self._play_animation("Idle")
            self._play_cpu_animation("Idle")

    def reset_game(self) -> None:
        if not self.match_started:
            return
        self.player.position = (-3.2, 0.1, 0)
        self.cpu.position = (3.2, 0.1, 0)
        self.player.rotation = (0, 0, 0)
        self.cpu.rotation = (0, 0, 0)
        self.elapsed = 0
        self.player_health = MAX_HEALTH
        self.cpu_health = MAX_HEALTH
        self.player_points = 0
        self.cpu_points = 0
        self.attack_cooldown = 0
        self.cpu_attack_cooldown = 0.8
        self.player_windup = self.cpu_windup = 0
        self.player_jump_velocity = self.cpu_jump_velocity = 0
        self.player_jump_windup = 0
        self.player_landing_time = 0
        self.player_animation_time = self.cpu_animation_time = 0
        self.player_velocity = Vec3(0, 0, 0)
        self.cpu_velocity = Vec3(0, 0, 0)
        self.player_attack_side = 1
        self.cpu_attack_side = 1
        self.player_attack_style = 0
        self.cpu_attack_style = 0
        self.cpu_block_timer = 0
        self.is_paused = False
        self.is_finished = False
        self.overlay.enabled = False
        self.status_text.text = "¡FIGHT!"
        self.status_text.color = TEAL
        self.pause_button.text = "PAUSA"
        self.overlay_button.text = "CONTINUAR"
        self.overlay_button.on_click = self.toggle_pause
        self.player_blocking = False
        self.active_animation = ""
        self.cpu_active_animation = ""
        self._play_animation("Idle")
        self._play_cpu_animation("Idle")
        self._refresh_hud()
        self._reset_camera()

    def finish_game(self, winner: Optional[str] = None) -> None:
        if self.is_finished:
            return
        self.is_paused = False
        self.is_finished = True
        self.overlay.enabled = True
        self.overlay_title.text = f"¡VICTORIA DE {winner.upper()}!" if winner else "COMBATE FINALIZADO"
        self.overlay_button.text = "REVANCHA"
        self.overlay_button.on_click = self.reset_game
        self.overlay_body.text = (
            f"PUNTOS  {self.player_name}: {self.player_points}  ·  {self.cpu_name}: {self.cpu_points}\n"
            f"DURACIÓN  {int(self.elapsed // 60):02d}:{int(self.elapsed % 60):02d}\n"
            "Pulsa REVANCHA para volver al duelo."
        )
        self.status_text.text = "KO  /  FIN DEL DUELO"
        self.status_text.color = GOLD
        self.actor.stop()
        self.cpu_actor.stop()

    def return_to_selection(self) -> None:
        self.is_paused = False
        self.is_finished = False
        self.overlay.enabled = False
        self.fight_hud.enabled = False
        self.selection_screen.enabled = True
        self.match_started = False
        self._selection_camera()

    def input(self, key: str) -> None:
        if not self.match_started:
            return
        if key == "escape":
            self.toggle_pause()
        elif key == "r":
            self.reset_game()
        elif key == "e":
            self.attack(1)
        elif key == "f":
            self.attack(-1)
        elif key == "space":
            self.jump()
        elif key == "q":
            self.player_blocking = True
        elif key == "q up":
            self.player_blocking = False

    def update(self) -> None:
        dt = time.dt
        self._update_blood_effects(dt)
        if not self.match_started or self.is_paused or self.is_finished:
            return
        self.elapsed += dt
        self.attack_cooldown = max(0, self.attack_cooldown - dt)
        self.cpu_attack_cooldown = max(0, self.cpu_attack_cooldown - dt)
        self.player_animation_time = max(0, self.player_animation_time - dt)
        self.cpu_animation_time = max(0, self.cpu_animation_time - dt)

        wasd_input = Vec3(
            held_keys["d"] - held_keys["a"],
            0,
            held_keys["w"] - held_keys["s"],
        )
        arrow_input = Vec3(
            held_keys["right arrow"] - held_keys["left arrow"],
            0,
            held_keys["up arrow"] - held_keys["down arrow"],
        )
        self.player_blocking = held_keys["q"] > 0
        self.cpu_block_timer = max(0, self.cpu_block_timer - dt)

        to_enemy = Vec3(self.cpu.x - self.player.x, 0, self.cpu.z - self.player.z)
        distance = to_enemy.length()
        if distance > 0.01:
            cpu_facing = heading_for_move(-to_enemy)
            self.player.rotation_y = turn_towards(self.player.rotation_y, heading_for_move(to_enemy), dt * 9.0)
            self.cpu.rotation_y = turn_towards(self.cpu.rotation_y, cpu_facing, dt * 10.0)

        forward = to_enemy.normalized() if distance > 0.01 else Vec3(0, 0, 1)
        strafe = Vec3(forward.z, 0, -forward.x)
        # WASD se orienta respecto al rival; las flechas siguen la pantalla,
        # donde abajo debe desplazar hacia la parte inferior (Z negativo).
        player_move = strafe * wasd_input.x + forward * wasd_input.z + arrow_input
        if player_move.length_squared() > 1:
            player_move.normalize()
        speed = 1.25 if self.player_blocking else (5.2 if held_keys["shift"] else 2.35)
        target_velocity = player_move * speed
        accelerating = target_velocity.length_squared() > self.player_velocity.length_squared()
        response = 1.0 - math.exp(-(8.0 if accelerating else 11.0) * dt)
        self.player_velocity += (target_velocity - self.player_velocity) * response
        self.player.position += self.player_velocity * dt
        self.player.x, self.player.z = self._clamp_arena(self.player.x, self.player.z)

        self._update_jump(dt, True)
        self._update_cpu(dt, distance, to_enemy)

        self.player_windup = self._advance_windup(self.player_windup, dt, True)
        self.cpu_windup = self._advance_windup(self.cpu_windup, dt, False)

        jump_locked = (
            self.player_jump_windup > 0
            or self.player_jump_velocity != 0
            or self.player.y > 0.101
            or self.player_landing_time > 0
        )
        if self.player_blocking and not jump_locked:
            self._play_animation("Block")
        elif not jump_locked and self.player_animation_time <= 0 and self.player_windup <= 0:
            speed_now = self.player_velocity.length()
            locomotion = "Run" if held_keys["shift"] and speed_now > 3.0 else "Walk" if speed_now > 0.12 else "Idle"
            self._play_animation(locomotion)
            if locomotion in ("Walk", "Run"):
                self._sync_locomotion_rate(self.actor, locomotion, speed_now)

        if self.cpu_block_timer > 0:
            self._play_cpu_animation("Block")
        elif self.cpu_animation_time <= 0 and self.cpu_windup <= 0:
            cpu_speed = self.cpu_velocity.length()
            locomotion = "Run" if cpu_speed > 3.1 else "Walk" if cpu_speed > 0.12 else "Idle"
            self._play_cpu_animation(locomotion)
            if locomotion in ("Walk", "Run"):
                self._sync_locomotion_rate(self.cpu_actor, locomotion, cpu_speed)

        center = (self.player.position + self.cpu.position) * 0.5
        target_camera = Vec3(center.x, 4.5, center.z - 8.8)
        camera.position += (target_camera - camera.position) * min(1, dt * 4.0)
        camera.look_at(center + Vec3(0, 1.1, 0))

        self._refresh_hud()

    def _refresh_hud(self) -> None:
        if not hasattr(self, "player_health_text") or not hasattr(self, "player"):
            return
        self.player_name_text.text = self.player_name.replace("_", " ").upper()
        self.cpu_name_text.text = self.cpu_name.replace("_", " ").upper()
        self.player_health_text.text = f"{self.player_health}%"
        self.cpu_health_text.text = f"{self.cpu_health}%"
        self.player_health_bar.scale_x = 0.34 * self.player_health / MAX_HEALTH
        self.cpu_health_bar.scale_x = 0.34 * self.cpu_health / MAX_HEALTH
        self.score_text.text = f"{self.player_points:04d}   VS   {self.cpu_points:04d}"
        self.timer_text.text = f"{int(self.elapsed // 60):02d}:{int(self.elapsed % 60):02d}"

    @staticmethod
    def _sync_locomotion_rate(actor: Actor, animation: str, speed: float) -> None:
        frame_count = max(2, actor.getNumFrames(animation))
        clip_duration = (frame_count - 1) / 30.0
        stride_length = 1.45 if animation == "Walk" else 2.25
        play_rate = max(0.65, min(2.8, speed * clip_duration / stride_length))
        actor.setPlayRate(play_rate, animation)

    @staticmethod
    def _clamp_arena(x: float, z: float) -> tuple[float, float]:
        radius = 12.5
        length = math.hypot(x, z)
        if length > radius:
            return x * radius / length, z * radius / length
        return x, z

    def _update_jump(self, dt: float, player: bool) -> None:
        if not player:
            return

        if self.player_landing_time > 0:
            self.player_landing_time = max(0.0, self.player_landing_time - dt)
            if self.player_landing_time == 0 and self.active_animation == "Jump_Land":
                self.active_animation = ""

        if self.player_jump_windup > 0:
            self.player_jump_windup = max(0.0, self.player_jump_windup - dt)
            if self.player_jump_windup == 0:
                self.player_jump_velocity = 7.8
                self._play_animation("Jump_Air")

        velocity = self.player_jump_velocity
        if velocity == 0:
            return

        velocity -= 19.0 * dt
        self.player.y += velocity * dt
        if self.player.y <= 0.1 and velocity < 0:
            self.player.y = 0.1
            velocity = 0.0
            self.player_landing_time = 0.28
            self.player_animation_time = self.player_landing_time
            self._play_animation("Jump_Land", loop=False)
        self.player_jump_velocity = velocity

    def _advance_windup(self, value: float, dt: float, from_player: bool) -> float:
        if value <= 0:
            return 0.0
        value = max(0.0, value - dt)
        if value == 0:
            self._resolve_attack(from_player)
        return value

    def _update_cpu(self, dt: float, distance: float, to_enemy: Vec3) -> None:
        target_velocity = Vec3(0, 0, 0)
        can_approach = self.cpu_animation_time <= 0 and self.cpu_windup <= 0 and self.cpu_block_timer <= 0
        if distance > 1.85 and distance > 0 and can_approach:
            approach_speed = min(4.2, max(2.4, (distance - 1.55) * 1.25))
            target_velocity = -to_enemy.normalized() * approach_speed
        response = 1.0 - math.exp(-(7.0 if target_velocity.length_squared() else 10.0) * dt)
        self.cpu_velocity += (target_velocity - self.cpu_velocity) * response
        self.cpu.position += self.cpu_velocity * dt
        self.cpu.x, self.cpu.z = self._clamp_arena(self.cpu.x, self.cpu.z)

        if distance <= 2.0 and self.cpu_attack_cooldown <= 0 and self.cpu_windup <= 0 and self.cpu_block_timer <= 0:
            if random.random() < 0.30:
                self.cpu_block_timer = 0.65
                self._play_cpu_animation("Block")
            else:
                style_index = self.cpu_attack_style
                animation = ATTACK_STYLES[style_index]
                self.cpu_attack_style = (style_index + 1) % len(ATTACK_STYLES)
                self.cpu_attack_cooldown = (1.08, 1.26, 1.14)[style_index]
                self.cpu_windup = (0.38, 0.42, 0.36)[style_index]
                self.cpu_animation_time = (0.98, 1.12, 0.94)[style_index]
                self._play_cpu_sword_swing(self.cpu_attack_side, animation)
                self.cpu_attack_side *= -1

    def run_self_test(self) -> None:
        assert self.selection_screen.enabled
        assert set(self.selection_cards) == {"Spartaco", "Chaca_Zulo"}
        assert all(callable(card.on_click) for card in self.selection_cards.values())
        assert callable(self.fight_button.on_click)
        assert all(Path(self._fighter_info(name)[2]).is_file() for name in self.selection_cards)
        assert all(callable(card.on_mouse_enter) for card in self.selection_cards.values())
        self.selection_cards["Spartaco"].on_click()
        assert self.selected_character == "Spartaco"
        self.selection_cards["Chaca_Zulo"].on_click()
        assert self.selected_character == "Chaca_Zulo"
        self._highlight_character("Spartaco", True)
        self.select_character("Chaca_Zulo")
        self.start_match()
        assert self.match_started and not self.selection_screen.enabled and self.fight_hud.enabled
        assert self.player_name == "Chaca_Zulo" and self.cpu_name == "Spartaco"
        assert sorted(self.actor.getAnimNames()) == sorted(ANIMATIONS)
        assert sorted(self.cpu_actor.getAnimNames()) == sorted(ANIMATIONS)
        self._play_sword_swing(1)
        self._play_sword_swing(-1)
        self._play_cpu_sword_swing(1)
        self._play_cpu_sword_swing(-1)
        self.actor.setPlayRate(1, "Attack")
        self.cpu_actor.setPlayRate(1, "Attack")
        self.active_animation = ""
        self._play_animation("Idle")
        assert heading_for_move(Vec3(0, 0, -1)) == 0.0  # Abajo: frente a cámara.
        assert heading_for_move(Vec3(0, 0, 1)) == 180.0  # Arriba: espalda a cámara.
        self.player.position = (-1.0, 0.1, 0)
        self.cpu.position = (1.0, 0.1, 0)
        self._resolve_attack(True)
        assert self.cpu_health == 82 and self.player_points == 100
        assert len(self.blood_effects) == 8
        self._update_blood_effects(1.0)
        assert not self.blood_effects
        self.cpu_block_timer = 0.5
        self._resolve_attack(True)
        assert self.cpu_health == 75 and self.player_points == 125
        self.player_blocking = True
        self._resolve_attack(False)
        assert self.player_health == 93 and self.cpu_points == 25
        self.player_blocking = False
        self.jump()
        assert self.player_jump_windup > 0 and self.player_jump_velocity == 0
        assert all(
            0 <= channel <= 1
            for entity in scene.entities
            for channel in entity.color
        ), "La escena contiene colores fuera del rango normalizado 0-1."

        self.cpu_health = 18
        self.cpu_block_timer = 0
        self._resolve_attack(True)
        assert self.is_finished and self.overlay.enabled
        self.return_to_selection()
        self.select_character("Spartaco")
        self.start_match()
        assert self.player_name == "Spartaco" and self.cpu_name == "Chaca_Zulo"
        self.reset_game()
        self.toggle_pause()
        assert self.is_paused and self.overlay.enabled
        self.toggle_pause()
        assert self.player_health == MAX_HEALTH and self.cpu_health == MAX_HEALTH and not self.is_paused
        self.finish_game(self.player_name)
        assert self.is_finished and self.overlay.enabled
        print(
            "SELF-TEST OK: selección, Spartaco/Chaca_Zulo, duelo, bloqueo, salto, vida, puntos y pausa.",
            flush=True,
        )


def main() -> int:
    args = parse_args()
    if args.self_test:
        loadPrcFileData("", "window-type none")
    app = Ursina(
        title="GLADIUS · duelo en el Coliseo",
        size=(1440, 900),
        fullscreen=False,
        borderless=False,
        development_mode=False,
        window_type="none" if args.self_test else "onscreen",
    )
    if args.pbr_preview:
        import simplepbr

        env_pattern = Path(__file__).resolve().parent / "build" / "pbr_preview" / "studio_#.png"
        pipeline = simplepbr.init(
            env_map=str(env_pattern),
            enable_shadows=True,
            enable_fog=True,
            msaa_samples=4,
            exposure=0.15,
        )
    else:
        pipeline = None
    game = GladiatorGame(pbr_preview=args.pbr_preview)
    game.pbr_pipeline = pipeline
    if args.self_test:
        game.run_self_test()
        game.actor.cleanup()
        app.destroy()
        return 0
    app.run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
