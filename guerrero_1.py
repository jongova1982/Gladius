#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador procedural de un guerrero humanoide realista para Blender 5.x y Unity.

El archivo es autocontenido: no descarga texturas ni usa complementos externos.
Se ejecuta desde Blender; los argumentos propios deben ir despues de ``--``::

    blender --background --python guerrero_1.py -- \
        --output-dir ./salida --name Guerrero_Realista --render-preview \
        --preview-resolution 1024x1024

Por defecto se guardan BLEND, FBX, GLB y un JSON de coordenadas. El FBX se
exporta con la convencion habitual de Unity (Y arriba, -Z hacia delante en el
archivo FBX). La escena de estudio (camara, luces y pedestal) nunca se incluye
en FBX/GLB.

Diseno: rig humanoide de referencia de 1.86 m, en pose A, con geometria visible
de piel, rasgos faciales, cabello/barba, armadura, capa, espada y escudo. La
altura total medida de la geometria se registra en el manifiesto. Las piezas se
deforman mediante grupos de vertices ligados a un armature humanoide. Esta
estrategia mantiene limpia la silueta de la armadura y produce pesos estables
para una base procedural sin dependencias.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import bpy  # type: ignore
    from mathutils import Vector  # type: ignore
except ImportError:  # Permite validar la sintaxis con Python fuera de Blender.
    bpy = None
    Vector = None


VERSION_GENERADOR = "1.0.2"
FPS = 24
PI = math.pi

# El personaje mira hacia -Y en Blender. Al exportar a Unity, ese eje se
# convierte en +Z. X conserva izquierda/derecha y Z se convierte en Y arriba.
BLENDER_A_UNITY = "Unity (x, y, z) = Blender (x, z, -y)"


class EstadoConstruccion:
    """Registro pequeno que evita depender de variables dispersas."""

    def __init__(self) -> None:
        self.coleccion_modelo = None
        self.coleccion_rig = None
        self.coleccion_preview = None
        self.rig = None
        self.objetos_exportables: List[Any] = []
        self.piezas: List[Dict[str, Any]] = []
        self.materiales: Dict[str, Any] = {}
        self.huesos: Dict[str, Dict[str, Any]] = {}
        self.acciones: List[Any] = []
        self.estilo = "roman"


ESTADO = EstadoConstruccion()


# ---------------------------------------------------------------------------
# CLI y utilidades generales
# ---------------------------------------------------------------------------


def _argumentos_despues_de_separador(argv: Sequence[str]) -> List[str]:
    """Devuelve solo los argumentos posteriores a ``--`` de Blender."""

    if "--" in argv:
        return list(argv[argv.index("--") + 1 :])
    # Resulta util al invocar desde el editor de texto de Blender.
    return []


def analizar_argumentos(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera un guerrero 3D riggeado y exportable a Unity."
    )
    parser.add_argument("--output-dir", default="salida_guerrero", help="Directorio de salida.")
    parser.add_argument("--name", default="Guerrero_Realista", help="Nombre base de los archivos.")
    parser.add_argument("--seed", type=int, default=2407, help="Semilla documentada en el manifiesto.")
    parser.add_argument(
        "--style", choices=("roman", "african_prince"), default="roman",
        help="Estilo visual conservando rig, escala y animaciones del guerrero.",
    )

    parser.set_defaults(guardar_blend=True, exportar_fbx=True, exportar_glb=True, exportar_json=True)
    parser.add_argument("--save-blend", dest="guardar_blend", action="store_true")
    parser.add_argument("--no-save-blend", dest="guardar_blend", action="store_false")
    parser.add_argument("--export-fbx", dest="exportar_fbx", action="store_true")
    parser.add_argument("--no-export-fbx", dest="exportar_fbx", action="store_false")
    parser.add_argument("--export-glb", dest="exportar_glb", action="store_true")
    parser.add_argument("--no-export-glb", dest="exportar_glb", action="store_false")
    parser.add_argument("--export-json", dest="exportar_json", action="store_true")
    parser.add_argument("--no-export-json", dest="exportar_json", action="store_false")

    parser.add_argument(
        "--render-preview",
        action="store_true",
        help="Renderiza una vista PNG con Eevee; se omite si no se indica.",
    )
    parser.add_argument(
        "--preview-resolution",
        default="1024x1024",
        help="Resolucion como 1024, 1024x1024 o 1920x1080.",
    )
    parser.add_argument("--preview-samples", type=int, default=64)
    parser.add_argument("--preview-frame", type=int, default=18)
    parser.add_argument(
        "--preview-action",
        default="Attack",
        choices=("Idle", "Walk", "Run", "Attack", "Block", "Hit", "Death"),
    )
    parser.add_argument(
        "--engine",
        default="BLENDER_EEVEE",
        help="Motor de preview. Blender 5.2 usa BLENDER_EEVEE.",
    )
    parser.add_argument("--verbose", action="store_true")

    entrada = list(sys.argv if argv is None else argv)
    return parser.parse_args(_argumentos_despues_de_separador(entrada))


def nombre_seguro(nombre: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9_.-]+", "_", nombre.strip())
    return limpio.strip("._") or "Guerrero_Realista"


def resolver_resolucion(valor: str) -> Tuple[int, int]:
    texto = str(valor).lower().replace(" ", "")
    if "x" in texto:
        ancho_txt, alto_txt = texto.split("x", 1)
        ancho, alto = int(ancho_txt), int(alto_txt)
    else:
        ancho = alto = int(texto)
    ancho = max(256, min(ancho, 4096))
    alto = max(256, min(alto, 4096))
    return ancho, alto


def log(mensaje: str) -> None:
    print(f"[GUERRERO] {mensaje}", flush=True)


def v3(valor: Sequence[float]) -> Any:
    return Vector((float(valor[0]), float(valor[1]), float(valor[2])))


def lista_vector(vector: Any, decimales: int = 6) -> List[float]:
    return [round(float(vector[0]), decimales), round(float(vector[1]), decimales), round(float(vector[2]), decimales)]


def coordenada_unity(vector: Any) -> List[float]:
    return [round(float(vector[0]), 6), round(float(vector[2]), 6), round(-float(vector[1]), 6)]


def ejecutar_operador_compatible(operador: Any, **opciones: Any) -> Any:
    """Filtra opciones que hayan cambiado de nombre entre versiones Blender."""

    try:
        validas = {prop.identifier for prop in operador.get_rna_type().properties}
        opciones = {k: v for k, v in opciones.items() if k in validas}
    except Exception:
        pass
    return operador(**opciones)


# ---------------------------------------------------------------------------
# Preparacion de escena y materiales
# ---------------------------------------------------------------------------


def limpiar_escena() -> None:
    """Parte de una escena vacia para que cada ejecucion sea idempotente."""

    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    # Se limpian bloques sin usuario; no se toca ninguna ruta externa.
    for contenedor in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.armatures,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.materials,
    ):
        for bloque in list(contenedor):
            if bloque.users == 0:
                contenedor.remove(bloque)

    # Las acciones usan fake-user para sobrevivir al guardado. Como esta escena
    # se regenera completa, deben retirarse incluso si ese indicador esta activo.
    for accion in list(bpy.data.actions):
        bpy.data.actions.remove(accion)

    # Las colecciones vinculadas a Scene conservan un usuario aun vacias.
    # Quitarlas garantiza nombres deterministas, sin sufijos .001 al reejecutar.
    for coleccion in list(bpy.data.collections):
        bpy.data.collections.remove(coleccion)


def crear_coleccion(nombre: str, padre: Any) -> Any:
    coleccion = bpy.data.collections.new(nombre)
    padre.children.link(coleccion)
    return coleccion


def preparar_escena(nombre: str) -> Any:
    limpiar_escena()
    escena = bpy.context.scene
    escena.name = f"ESCENA_{nombre}"
    escena.unit_settings.system = "METRIC"
    escena.unit_settings.length_unit = "METERS"
    escena.unit_settings.scale_length = 1.0
    escena.render.fps = FPS
    escena.render.fps_base = 1.0
    escena.frame_start = 1
    escena.frame_end = 72

    # AgX es la gestion de color recomendada para metal y piel en Blender 5.
    try:
        escena.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        try:
            escena.view_settings.look = "Medium High Contrast"
        except Exception:
            pass

    raiz = crear_coleccion("GUERRERO_GENERADO", escena.collection)
    ESTADO.coleccion_modelo = crear_coleccion("MODELO_EXPORTABLE", raiz)
    ESTADO.coleccion_rig = crear_coleccion("RIG_EXPORTABLE", raiz)
    ESTADO.coleccion_preview = crear_coleccion("ESTUDIO_NO_EXPORTAR", raiz)

    mundo = bpy.data.worlds.get("Mundo_Guerrero") or bpy.data.worlds.new("Mundo_Guerrero")
    escena.world = mundo
    mundo.use_nodes = True
    fondo = mundo.node_tree.nodes.get("Background")
    if fondo:
        fondo.inputs["Color"].default_value = (0.012, 0.016, 0.024, 1.0)
        fondo.inputs["Strength"].default_value = 0.22
    return escena


def mover_a_coleccion(objeto: Any, coleccion: Any) -> None:
    for coleccion_actual in list(objeto.users_collection):
        coleccion_actual.objects.unlink(objeto)
    coleccion.objects.link(objeto)


def _variar_color(color: Sequence[float], factor: float) -> Tuple[float, float, float, float]:
    return (
        max(0.0, min(1.0, color[0] * factor)),
        max(0.0, min(1.0, color[1] * factor)),
        max(0.0, min(1.0, color[2] * factor)),
        float(color[3]),
    )


def crear_material_pbr(
    nombre: str,
    color: Sequence[float],
    metalico: float,
    rugosidad: float,
    escala_ruido: float,
    relieve: float,
) -> Any:
    """Material PBR procedural basado en Principled BSDF y ruido 3D."""

    material = bpy.data.materials.new(nombre)
    material.use_nodes = True
    material.diffuse_color = tuple(color)
    material["pbr_procedural"] = True
    material["unity_shader_sugerido"] = "Universal Render Pipeline/Lit"

    nodos = material.node_tree.nodes
    enlaces = material.node_tree.links
    nodos.clear()
    salida = nodos.new("ShaderNodeOutputMaterial")
    salida.location = (560, 40)
    shader = nodos.new("ShaderNodeBsdfPrincipled")
    shader.location = (260, 40)
    shader.inputs["Metallic"].default_value = metalico
    shader.inputs["Roughness"].default_value = rugosidad
    # Deja el color base como un factor PBR real. Los nodos procedurales de
    # color de Blender no se exportan a glTF y dejaban el personaje blanco en
    # Panda3D/Unity; el ruido sigue aportando relieve al material de Blender.
    shader.inputs["Base Color"].default_value = tuple(color)
    if "IOR" in shader.inputs:
        shader.inputs["IOR"].default_value = 1.45
    enlaces.new(shader.outputs["BSDF"], salida.inputs["Surface"])

    coordenadas = nodos.new("ShaderNodeTexCoord")
    coordenadas.location = (-820, 20)
    ruido = nodos.new("ShaderNodeTexNoise")
    ruido.location = (-610, 50)
    ruido.noise_dimensions = "3D"
    ruido.inputs["Scale"].default_value = escala_ruido
    ruido.inputs["Detail"].default_value = 4.0
    ruido.inputs["Roughness"].default_value = 0.62
    rampa = nodos.new("ShaderNodeValToRGB")
    rampa.location = (-340, 130)
    rampa.color_ramp.elements[0].position = 0.24
    rampa.color_ramp.elements[0].color = _variar_color(color, 0.55 if metalico > 0.5 else 0.72)
    rampa.color_ramp.elements[1].position = 0.78
    rampa.color_ramp.elements[1].color = _variar_color(color, 1.22)
    golpe = nodos.new("ShaderNodeBump")
    golpe.location = (10, -135)
    golpe.inputs["Strength"].default_value = relieve
    golpe.inputs["Distance"].default_value = 0.018 if escala_ruido < 12 else 0.006

    enlaces.new(coordenadas.outputs["Generated"], ruido.inputs["Vector"])
    enlaces.new(ruido.outputs["Fac"], rampa.inputs["Fac"])
    enlaces.new(ruido.outputs["Fac"], golpe.inputs["Height"])
    enlaces.new(golpe.outputs["Normal"], shader.inputs["Normal"])
    ESTADO.materiales[nombre] = material
    return material


def crear_materiales() -> Dict[str, Any]:
    prince = ESTADO.estilo == "african_prince"
    materiales = {
        "Piel": crear_material_pbr("MAT_Piel", (0.095, 0.025, 0.009, 1) if prince else (0.46, 0.245, 0.145, 1), 0.0, 0.48, 42.0, 0.11),
        "Acero": crear_material_pbr("MAT_Acero_Patinado", (0.30, 0.19, 0.075, 1) if prince else (0.19, 0.22, 0.25, 1), 0.72 if prince else 0.91, 0.31 if prince else 0.24, 5.5, 0.22),
        "AceroOscuro": crear_material_pbr("MAT_Acero_Oscuro", (0.035, 0.09, 0.085, 1) if prince else (0.055, 0.065, 0.075, 1), 0.52 if prince else 0.86, 0.38 if prince else 0.31, 7.0, 0.18),
        "Filo": crear_material_pbr("MAT_Filo_Espada", (0.47, 0.53, 0.58, 1), 0.98, 0.12, 3.0, 0.06),
        "Laton": crear_material_pbr("MAT_Laton", (0.42, 0.245, 0.055, 1), 0.82, 0.25, 6.0, 0.14),
        "Cuero": crear_material_pbr("MAT_Cuero", (0.095, 0.033, 0.018, 1), 0.0, 0.64, 18.0, 0.28),
        "CueroClaro": crear_material_pbr("MAT_Cuero_Claro", (0.23, 0.09, 0.032, 1), 0.0, 0.58, 22.0, 0.25),
        "Tela": crear_material_pbr("MAT_Tela_Carmesi", (0.015, 0.25, 0.19, 1) if prince else (0.19, 0.012, 0.018, 1), 0.0, 0.78, 75.0, 0.2),
        "TelaOscura": crear_material_pbr("MAT_Tela_Oscura", (0.012, 0.065, 0.06, 1) if prince else (0.022, 0.028, 0.038, 1), 0.0, 0.86, 90.0, 0.16),
        "Cabello": crear_material_pbr("MAT_Cabello", (0.035, 0.012, 0.006, 1), 0.0, 0.66, 35.0, 0.22),
        "Ojo": crear_material_pbr("MAT_Iris", (0.03, 0.12, 0.16, 1), 0.0, 0.22, 16.0, 0.04),
        "OjoBlanco": crear_material_pbr("MAT_Esclerotica", (0.72, 0.69, 0.62, 1), 0.0, 0.34, 30.0, 0.03),
        "Negro": crear_material_pbr("MAT_Negro", (0.003, 0.004, 0.005, 1), 0.0, 0.3, 10.0, 0.02),
        "Piedra": crear_material_pbr("MAT_Piedra", (0.065, 0.075, 0.085, 1), 0.0, 0.78, 9.0, 0.42),
    }
    # El registro global usa las claves semanticas que consume el resto del
    # generador ("Piel", "Acero", "Piedra", etc.), no los nombres internos
    # MAT_* de Blender.
    ESTADO.materiales = materiales
    return materiales


# ---------------------------------------------------------------------------
# Geometria procedural
# ---------------------------------------------------------------------------


def aplicar_transformaciones(objeto: Any) -> None:
    bpy.context.view_layer.objects.active = objeto
    objeto.select_set(True)
    try:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    finally:
        objeto.select_set(False)


def suavizar(objeto: Any) -> None:
    if objeto.type == "MESH":
        for poligono in objeto.data.polygons:
            poligono.use_smooth = True


def biselar(objeto: Any, ancho: float, segmentos: int = 2) -> None:
    if ancho <= 0:
        return
    modificador = objeto.modifiers.new("Bisel_Micro", "BEVEL")
    modificador.width = ancho
    modificador.segments = segmentos
    modificador.limit_method = "ANGLE"
    try:
        bpy.context.view_layer.objects.active = objeto
        objeto.select_set(True)
        bpy.ops.object.modifier_apply(modifier=modificador.name)
    except Exception:
        pass
    finally:
        objeto.select_set(False)


def asignar_material(objeto: Any, material: Any) -> None:
    if objeto.data and hasattr(objeto.data, "materials"):
        objeto.data.materials.append(material)


def registrar_pieza(objeto: Any, hueso: Optional[str], categoria: str) -> Any:
    mover_a_coleccion(objeto, ESTADO.coleccion_modelo)
    objeto["categoria"] = categoria
    if hueso:
        objeto["hueso_unity"] = hueso
        vincular_a_hueso(objeto, ESTADO.rig, hueso)
    ESTADO.objetos_exportables.append(objeto)
    ESTADO.piezas.append(
        {
            "name": objeto.name,
            "category": categoria,
            "bone": hueso,
        }
    )
    return objeto


def crear_elipsoide(
    nombre: str,
    ubicacion: Sequence[float],
    escala: Sequence[float],
    material: Any,
    hueso: Optional[str],
    categoria: str,
    rotacion: Sequence[float] = (0.0, 0.0, 0.0),
    segmentos: int = 32,
    anillos: int = 20,
) -> Any:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segmentos,
        ring_count=anillos,
        location=ubicacion,
        rotation=rotacion,
    )
    objeto = bpy.context.object
    objeto.name = nombre
    objeto.scale = escala
    aplicar_transformaciones(objeto)
    suavizar(objeto)
    asignar_material(objeto, material)
    return registrar_pieza(objeto, hueso, categoria)


def crear_segmento(
    nombre: str,
    inicio: Sequence[float],
    fin: Sequence[float],
    radio_inicio: float,
    radio_fin: float,
    material: Any,
    hueso: Optional[str],
    categoria: str,
    vertices: int = 28,
    bisel: float = 0.012,
) -> Any:
    p0, p1 = v3(inicio), v3(fin)
    direccion = p1 - p0
    longitud = max(direccion.length, 0.0001)
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices,
        radius1=radio_inicio,
        radius2=radio_fin,
        depth=longitud,
        location=(p0 + p1) * 0.5,
    )
    objeto = bpy.context.object
    objeto.name = nombre
    objeto.rotation_mode = "QUATERNION"
    objeto.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(direccion.normalized())
    aplicar_transformaciones(objeto)
    biselar(objeto, min(bisel, radio_inicio * 0.3, radio_fin * 0.3), 3)
    suavizar(objeto)
    asignar_material(objeto, material)
    return registrar_pieza(objeto, hueso, categoria)


def crear_caja(
    nombre: str,
    ubicacion: Sequence[float],
    escala: Sequence[float],
    material: Any,
    hueso: Optional[str],
    categoria: str,
    rotacion: Sequence[float] = (0.0, 0.0, 0.0),
    ancho_bisel: float = 0.01,
) -> Any:
    bpy.ops.mesh.primitive_cube_add(location=ubicacion, rotation=rotacion)
    objeto = bpy.context.object
    objeto.name = nombre
    objeto.scale = escala
    aplicar_transformaciones(objeto)
    biselar(objeto, ancho_bisel, 3)
    asignar_material(objeto, material)
    return registrar_pieza(objeto, hueso, categoria)


def crear_viga(
    nombre: str,
    inicio: Sequence[float],
    fin: Sequence[float],
    ancho: float,
    grosor: float,
    material: Any,
    hueso: Optional[str],
    categoria: str,
    bisel: float = 0.008,
) -> Any:
    p0, p1 = v3(inicio), v3(fin)
    direccion = p1 - p0
    # Construir y orientar antes de aplicar la ubicacion. Si se reutiliza
    # crear_caja(), esa funcion hornea primero la traslacion en los vertices y
    # la rotacion posterior ocurre alrededor del origen mundial; las vigas
    # largas (por ejemplo la hoja de la espada) terminan dispersas.
    bpy.ops.mesh.primitive_cube_add(location=(p0 + p1) * 0.5)
    objeto = bpy.context.object
    objeto.name = nombre
    objeto.scale = (
        ancho * 0.5,
        grosor * 0.5,
        max(direccion.length, 0.001) * 0.5,
    )
    objeto.rotation_mode = "QUATERNION"
    objeto.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(direccion.normalized())
    aplicar_transformaciones(objeto)
    biselar(objeto, bisel, 3)
    asignar_material(objeto, material)
    return registrar_pieza(objeto, hueso, categoria)


def crear_toro(
    nombre: str,
    ubicacion: Sequence[float],
    radio_mayor: float,
    radio_menor: float,
    material: Any,
    hueso: Optional[str],
    categoria: str,
    rotacion: Sequence[float] = (0.0, 0.0, 0.0),
) -> Any:
    bpy.ops.mesh.primitive_torus_add(
        major_radius=radio_mayor,
        minor_radius=radio_menor,
        major_segments=48,
        minor_segments=10,
        location=ubicacion,
        rotation=rotacion,
    )
    objeto = bpy.context.object
    objeto.name = nombre
    aplicar_transformaciones(objeto)
    suavizar(objeto)
    asignar_material(objeto, material)
    return registrar_pieza(objeto, hueso, categoria)


def crear_loft(
    nombre: str,
    anillos: Sequence[Tuple[float, float, float, float]],
    material: Any,
    hueso: Optional[str],
    categoria: str,
    segmentos: int = 32,
) -> Any:
    """Crea una forma cerrada a partir de anillos (z, rx, ry, centro_y)."""

    vertices: List[Tuple[float, float, float]] = []
    caras: List[Tuple[int, ...]] = []
    for z, radio_x, radio_y, centro_y in anillos:
        for indice in range(segmentos):
            angulo = 2.0 * PI * indice / segmentos
            vertices.append((radio_x * math.cos(angulo), centro_y + radio_y * math.sin(angulo), z))
    for fila in range(len(anillos) - 1):
        base = fila * segmentos
        siguiente = (fila + 1) * segmentos
        for indice in range(segmentos):
            j = (indice + 1) % segmentos
            caras.append((base + indice, base + j, siguiente + j, siguiente + indice))
    inferior = len(vertices)
    z0, _, _, cy0 = anillos[0]
    vertices.append((0.0, cy0, z0))
    superior = len(vertices)
    z1, _, _, cy1 = anillos[-1]
    vertices.append((0.0, cy1, z1))
    for indice in range(segmentos):
        j = (indice + 1) % segmentos
        caras.append((inferior, j, indice))
        ultimo = (len(anillos) - 1) * segmentos
        caras.append((superior, ultimo + indice, ultimo + j))

    malla = bpy.data.meshes.new(f"MALLA_{nombre}")
    malla.from_pydata(vertices, [], caras)
    malla.update()
    objeto = bpy.data.objects.new(nombre, malla)
    ESTADO.coleccion_modelo.objects.link(objeto)
    suavizar(objeto)
    biselar(objeto, 0.006, 2)
    asignar_material(objeto, material)
    return registrar_pieza(objeto, hueso, categoria)


def crear_capa(material: Any) -> Any:
    """Capa ondulada de doble cara, fijada al pecho superior."""

    columnas, filas = 10, 13
    vertices: List[Tuple[float, float, float]] = []
    caras: List[Tuple[int, int, int, int]] = []
    for fila in range(filas):
        t = fila / (filas - 1)
        z = 1.53 - 1.02 * t
        semiancho = 0.33 + 0.11 * t
        for columna in range(columnas):
            u = columna / (columnas - 1)
            x = (u * 2.0 - 1.0) * semiancho
            onda = 0.018 * math.sin(u * 5.0 * PI + t * 2.0)
            y = 0.175 + 0.10 * t + onda
            vertices.append((x, y, z))
    for fila in range(filas - 1):
        for columna in range(columnas - 1):
            a = fila * columnas + columna
            caras.append((a, a + 1, a + 1 + columnas, a + columnas))
    malla = bpy.data.meshes.new("MALLA_Capa")
    malla.from_pydata(vertices, [], caras)
    malla.update()
    objeto = bpy.data.objects.new("Capa_Carmesi", malla)
    ESTADO.coleccion_modelo.objects.link(objeto)
    asignar_material(objeto, material)
    solido = objeto.modifiers.new("Grosor_Capa", "SOLIDIFY")
    solido.thickness = 0.012
    solido.offset = 0.0
    biselar(objeto, 0.004, 2)
    return registrar_pieza(objeto, "UpperChest", "tela")


# ---------------------------------------------------------------------------
# Armature humanoide y pesos
# ---------------------------------------------------------------------------


def especificaciones_huesos() -> Dict[str, Dict[str, Any]]:
    """Jerarquia en metros, pose A, preparada para mapeo Humanoid de Unity."""

    h: Dict[str, Dict[str, Any]] = {}

    def agregar(nombre: str, cabeza: Sequence[float], cola: Sequence[float], padre: Optional[str], deformar: bool = True) -> None:
        h[nombre] = {
            "head": tuple(cabeza),
            "tail": tuple(cola),
            "parent": padre,
            "deform": deformar,
        }

    agregar("Root", (0, 0, 0), (0, 0, 0.12), None, False)
    agregar("Hips", (0, 0, 1.00), (0, 0, 1.13), "Root")
    agregar("Spine", (0, 0, 1.10), (0, 0, 1.29), "Hips")
    agregar("Chest", (0, 0, 1.29), (0, 0, 1.47), "Spine")
    agregar("UpperChest", (0, 0, 1.47), (0, 0, 1.57), "Chest")
    agregar("Neck", (0, 0, 1.57), (0, 0, 1.66), "UpperChest")
    agregar("Head", (0, 0, 1.66), (0, -0.005, 1.86), "Neck")

    for lado, signo in (("Left", -1.0), ("Right", 1.0)):
        agregar(f"{lado}Shoulder", (0, 0, 1.53), (0.24 * signo, 0, 1.52), "UpperChest")
        agregar(f"{lado}UpperArm", (0.24 * signo, 0, 1.52), (0.53 * signo, 0, 1.31), f"{lado}Shoulder")
        agregar(f"{lado}LowerArm", (0.53 * signo, 0, 1.31), (0.72 * signo, -0.005, 1.11), f"{lado}UpperArm")
        agregar(f"{lado}Hand", (0.72 * signo, -0.005, 1.11), (0.82 * signo, -0.018, 1.045), f"{lado}LowerArm")
        agregar(f"{lado}UpperLeg", (0.13 * signo, 0, 1.01), (0.145 * signo, 0, 0.57), "Hips")
        agregar(f"{lado}LowerLeg", (0.145 * signo, 0, 0.57), (0.145 * signo, -0.005, 0.14), f"{lado}UpperLeg")
        agregar(f"{lado}Foot", (0.145 * signo, -0.005, 0.14), (0.145 * signo, -0.21, 0.075), f"{lado}LowerLeg")
        agregar(f"{lado}Toes", (0.145 * signo, -0.21, 0.075), (0.145 * signo, -0.34, 0.065), f"{lado}Foot")

        # Cinco dedos completos; son utiles para retargeting aunque los guantes
        # se mantengan visualmente compactos.
        nombres_dedos = ("Thumb", "Index", "Middle", "Ring", "Little")
        offsets_y = (-0.048, -0.026, -0.008, 0.012, 0.032)
        longitudes = (0.055, 0.072, 0.078, 0.070, 0.058)
        for dedo, offset_y, longitud in zip(nombres_dedos, offsets_y, longitudes):
            base_x = 0.79 * signo
            base_z = 1.06 - (0.012 if dedo == "Thumb" else 0.0)
            if dedo == "Thumb":
                base_y = -0.035
                delta_z = -0.025
            else:
                base_y = offset_y
                delta_z = -0.012
            p0 = (base_x, base_y, base_z)
            p1 = ((0.79 + longitud * 0.36) * signo, base_y - 0.005, base_z + delta_z * 0.36)
            p2 = ((0.79 + longitud * 0.70) * signo, base_y - 0.007, base_z + delta_z * 0.70)
            p3 = ((0.79 + longitud) * signo, base_y - 0.009, base_z + delta_z)
            agregar(f"{lado}{dedo}Proximal", p0, p1, f"{lado}Hand")
            agregar(f"{lado}{dedo}Intermediate", p1, p2, f"{lado}{dedo}Proximal")
            agregar(f"{lado}{dedo}Distal", p2, p3, f"{lado}{dedo}Intermediate")

    agregar("Weapon_R", (0.79, -0.018, 1.055), (0.84, -0.022, 0.91), "RightHand", True)
    agregar("Shield_L", (-0.77, -0.012, 1.075), (-0.77, -0.05, 0.92), "LeftHand", True)
    agregar("BackSocket", (0, 0.12, 1.47), (0, 0.24, 1.47), "UpperChest", False)
    agregar("HeadSocket", (0, 0, 1.84), (0, 0, 1.94), "Head", False)
    agregar("ChestSocket", (0, -0.15, 1.42), (0, -0.25, 1.42), "Chest", False)
    return h


def crear_armature(nombre: str) -> Any:
    datos = bpy.data.armatures.new(f"ARM_{nombre}")
    rig = bpy.data.objects.new(f"RIG_{nombre}", datos)
    ESTADO.coleccion_rig.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    ESTADO.huesos = especificaciones_huesos()
    creados: Dict[str, Any] = {}
    for nombre_hueso, spec in ESTADO.huesos.items():
        hueso = datos.edit_bones.new(nombre_hueso)
        hueso.head = spec["head"]
        hueso.tail = spec["tail"]
        hueso.roll = 0.0
        hueso.use_deform = bool(spec["deform"])
        creados[nombre_hueso] = hueso
    for nombre_hueso, spec in ESTADO.huesos.items():
        if spec["parent"]:
            creados[nombre_hueso].parent = creados[spec["parent"]]
            creados[nombre_hueso].use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    rig.select_set(False)
    rig.show_in_front = True
    rig.data.display_type = "BBONE"
    rig["unity_rig"] = "Humanoid"
    rig["altura_metros"] = 1.86
    ESTADO.rig = rig
    ESTADO.objetos_exportables.append(rig)
    return rig


def vincular_a_hueso(objeto: Any, rig: Any, nombre_hueso: str) -> None:
    if rig is None or nombre_hueso not in rig.data.bones:
        raise ValueError(f"Hueso inexistente para {objeto.name}: {nombre_hueso}")
    grupo = objeto.vertex_groups.get(nombre_hueso) or objeto.vertex_groups.new(name=nombre_hueso)
    if len(objeto.data.vertices):
        grupo.add(list(range(len(objeto.data.vertices))), 1.0, "REPLACE")
    modificador = objeto.modifiers.new("Deformacion_Armature", "ARMATURE")
    modificador.object = rig
    modificador.use_deform_preserve_volume = True
    objeto.parent = rig
    objeto.matrix_parent_inverse = rig.matrix_world.inverted()


# ---------------------------------------------------------------------------
# Construccion visual del guerrero
# ---------------------------------------------------------------------------


def construir_cuerpo_y_rostro(mat: Mapping[str, Any]) -> None:
    # Volumen corporal bajo la armadura. Permanece visible en cuello, rostro,
    # articulaciones y pequenas separaciones entre placas.
    crear_elipsoide("Cuerpo_Pelvis", (0, 0.005, 1.035), (0.205, 0.145, 0.175), mat["Piel"], "Hips", "piel")
    crear_loft(
        "Cuerpo_Torso",
        ((1.10, 0.19, 0.12, 0.0), (1.29, 0.27, 0.15, 0.0), (1.46, 0.34, 0.18, 0.0), (1.56, 0.29, 0.15, 0.0)),
        mat["Piel"],
        "Chest",
        "piel",
    )
    crear_segmento("Cuello", (0, 0, 1.54), (0, 0, 1.67), 0.078, 0.072, mat["Piel"], "Neck", "piel", bisel=0.018)

    puntos_brazo = {
        "Left": ((-0.245, 0, 1.51), (-0.53, 0, 1.31), (-0.72, -0.005, 1.11), (-0.82, -0.018, 1.045)),
        "Right": ((0.245, 0, 1.51), (0.53, 0, 1.31), (0.72, -0.005, 1.11), (0.82, -0.018, 1.045)),
    }
    for lado, (hombro, codo, muneca, mano) in puntos_brazo.items():
        crear_segmento(f"Piel_{lado}_Brazo", hombro, codo, 0.086, 0.068, mat["Piel"], f"{lado}UpperArm", "piel")
        crear_elipsoide(f"Piel_{lado}_Codo", codo, (0.073, 0.071, 0.073), mat["Piel"], f"{lado}LowerArm", "piel")
        crear_segmento(f"Piel_{lado}_Antebrazo", codo, muneca, 0.072, 0.050, mat["Piel"], f"{lado}LowerArm", "piel")
        crear_segmento(f"Piel_{lado}_Mano", muneca, mano, 0.052, 0.043, mat["Piel"], f"{lado}Hand", "piel", bisel=0.014)

    for lado, signo in (("Left", -1.0), ("Right", 1.0)):
        cadera, rodilla, tobillo = (0.13 * signo, 0, 1.0), (0.145 * signo, 0, 0.57), (0.145 * signo, -0.005, 0.14)
        crear_segmento(f"Piel_{lado}_Muslo", cadera, rodilla, 0.13, 0.095, mat["Piel"], f"{lado}UpperLeg", "piel", bisel=0.02)
        crear_elipsoide(f"Piel_{lado}_Rodilla", rodilla, (0.098, 0.092, 0.092), mat["Piel"], f"{lado}LowerLeg", "piel")
        crear_segmento(f"Piel_{lado}_Pantorrilla", rodilla, tobillo, 0.10, 0.065, mat["Piel"], f"{lado}LowerLeg", "piel", bisel=0.018)

    # Cabeza y rasgos, con suficiente relieve para leer bien en un primer plano.
    crear_elipsoide("Cabeza", (0, 0.0, 1.735), (0.108, 0.101, 0.137), mat["Piel"], "Head", "piel", segmentos=40, anillos=28)
    crear_elipsoide("Mandibula", (0, -0.018, 1.665), (0.091, 0.086, 0.075), mat["Piel"], "Head", "piel")
    nariz = (0.035, 0.038, 0.045) if ESTADO.estilo == "african_prince" else (0.025, 0.035, 0.048)
    crear_elipsoide("Nariz", (0, -0.102, 1.733), nariz, mat["Piel"], "Head", "piel", segmentos=24, anillos=14)
    crear_elipsoide("Oreja_L", (-0.108, 0.0, 1.735), (0.018, 0.014, 0.038), mat["Piel"], "Head", "piel", segmentos=20, anillos=12)
    crear_elipsoide("Oreja_R", (0.108, 0.0, 1.735), (0.018, 0.014, 0.038), mat["Piel"], "Head", "piel", segmentos=20, anillos=12)

    for lado, signo in (("L", -1.0), ("R", 1.0)):
        crear_elipsoide(f"Ojo_{lado}", (0.039 * signo, -0.092, 1.758), (0.027, 0.013, 0.015), mat["OjoBlanco"], "Head", "ojo", segmentos=24, anillos=14)
        crear_elipsoide(f"Iris_{lado}", (0.039 * signo, -0.104, 1.758), (0.010, 0.005, 0.010), mat["Ojo"], "Head", "ojo", segmentos=20, anillos=12)
        crear_elipsoide(f"Pupila_{lado}", (0.039 * signo, -0.108, 1.758), (0.0045, 0.003, 0.0045), mat["Negro"], "Head", "ojo", segmentos=16, anillos=10)
        crear_segmento(
            f"Ceja_{lado}",
            (0.014 * signo, -0.103, 1.791),
            (0.074 * signo, -0.096, 1.786),
            0.006,
            0.005,
            mat["Cabello"],
            "Head",
            "cabello",
            vertices=16,
            bisel=0.002,
        )
    crear_segmento("Boca", (-0.034, -0.096, 1.676), (0.034, -0.096, 1.676), 0.004, 0.004, mat["Tela"], "Head", "rostro", vertices=16, bisel=0.001)

    # Cabello corto con mechones y barba modular.
    crear_elipsoide("Cabello_Base", (0, 0.024, 1.825), (0.111, 0.101, 0.071), mat["Cabello"], "Head", "cabello")
    if ESTADO.estilo == "african_prince":
        # Rizos cortos con volumen y un aro real de metal en la frente.
        for fila, z in enumerate((1.82, 1.855, 1.884)):
            for indice in range(12 if fila < 2 else 8):
                angulo = 2 * PI * indice / (12 if fila < 2 else 8) + fila * 0.18
                x, y = 0.094 * math.cos(angulo), 0.075 * math.sin(angulo) + 0.024
                crear_elipsoide(f"Rizo_{fila}_{indice}", (x, y, z), (0.027, 0.025, 0.028), mat["Cabello"], "Head", "cabello", segmentos=12, anillos=8)
        crear_toro("Diadema_Principesca", (0, -0.015, 1.842), 0.112, 0.012, mat["Laton"], "Head", "corona", rotacion=(PI / 2, 0, 0))
        crear_elipsoide("Gema_Diadema", (0, -0.103, 1.848), (0.027, 0.012, 0.036), mat["Ojo"], "Head", "corona", segmentos=20, anillos=12)
    else:
        for indice, x in enumerate((-0.075, -0.04, 0.0, 0.04, 0.075)):
            crear_segmento(
                f"Cabello_Mechon_{indice:02d}",
                (x, -0.07 + abs(x) * 0.12, 1.85 - abs(x) * 0.12),
                (x * 1.05, -0.091, 1.812 - abs(x) * 0.08),
                0.018,
                0.008,
                mat["Cabello"],
                "Head",
                "cabello",
                vertices=16,
                bisel=0.003,
            )
    for indice, x in enumerate((-0.067, -0.042, -0.018, 0.0, 0.018, 0.042, 0.067)):
        inicio = (x, -0.091 + abs(x) * 0.06, 1.69 - abs(x) * 0.16)
        fin = (x * 0.82, -0.095, 1.615 + abs(x) * 0.18)
        crear_segmento(f"Barba_{indice:02d}", inicio, fin, 0.014, 0.006, mat["Cabello"], "Head", "barba", vertices=16, bisel=0.003)
    for lado, signo in (("L", -1.0), ("R", 1.0)):
        crear_segmento(f"Patilla_{lado}", (0.087 * signo, -0.055, 1.76), (0.079 * signo, -0.077, 1.68), 0.013, 0.010, mat["Cabello"], "Head", "barba", vertices=16, bisel=0.003)


def construir_armadura(mat: Mapping[str, Any]) -> None:
    if ESTADO.estilo == "african_prince":
        # Diadema y plumas ceremoniales visibles por encima del cabello.
        crear_viga("Pluma_Principal", (0, 0.015, 1.86), (0, 0.065, 2.13), 0.055, 0.009, mat["Tela"], "Head", "corona", bisel=0.008)
        for lado, signo in (("L", -1.0), ("R", 1.0)):
            crear_viga(f"Pluma_{lado}", (0.025 * signo, 0.025, 1.86), (0.09 * signo, 0.055, 2.04), 0.036, 0.008, mat["Laton"], "Head", "corona", bisel=0.006)
        crear_elipsoide("Broche_Corona", (0, -0.104, 1.89), (0.04, 0.016, 0.05), mat["Laton"], "Head", "corona")
    if ESTADO.estilo != "african_prince":
        # Casco de oficial con cresta de crin y carrilleras articuladas.
        # El rostro y los ojos permanecen despejados para conservar la expresión.
        crear_elipsoide(
            "Casco_Calota",
            (0, 0.018, 1.824),
            (0.137, 0.119, 0.076),
            mat["Acero"],
            "Head",
            "armadura",
            segmentos=36,
            anillos=24,
        )
        crear_viga("Casco_Borde_Frontal", (-0.119, -0.083, 1.784), (0.119, -0.083, 1.784), 0.018, 0.014, mat["Laton"], "Head", "armadura", bisel=0.004)
        for lado, signo in (("L", -1.0), ("R", 1.0)):
            crear_viga(
                f"Casco_Carrillera_{lado}",
                (0.102 * signo, -0.025, 1.775),
                (0.082 * signo, -0.058, 1.676),
                0.032,
                0.022,
                mat["Acero"],
                "Head",
                "armadura",
                bisel=0.008,
            )
            crear_elipsoide(
                f"Casco_Remache_{lado}",
                (0.101 * signo, -0.07, 1.767),
                (0.012, 0.008, 0.012),
                mat["Laton"],
                "Head",
                "detalle",
                segmentos=16,
                anillos=10,
            )
        crear_elipsoide(
            "Casco_Cresta_Crin",
            (0, 0.015, 1.9),
            (0.115, 0.04, 0.072),
            mat["Tela"],
            "Head",
            "armadura",
            segmentos=28,
            anillos=18,
        )

    # Cota oscura visible bajo el peto.
    crear_loft(
        "Cota_Malla",
        ((1.09, 0.21, 0.135, 0.006), (1.29, 0.29, 0.17, 0.006), (1.48, 0.35, 0.19, 0.008), (1.55, 0.29, 0.16, 0.008)),
        mat["AceroOscuro"],
        "Chest",
        "armadura",
    )
    # Peto completo: silueta anatomica, borde inferior estrecho y pecho amplio.
    crear_loft(
        "Peto_Placas",
        ((1.15, 0.225, 0.145, -0.006), (1.25, 0.275, 0.165, -0.009), (1.39, 0.348, 0.192, -0.012), (1.50, 0.335, 0.182, -0.007), (1.555, 0.285, 0.15, 0.0)),
        mat["Acero"],
        "Chest",
        "armadura",
    )
    # Nervio central, lineas pectorales y ribete dorado.
    crear_viga("Nervio_Peto", (0, -0.196, 1.18), (0, -0.205, 1.50), 0.026, 0.018, mat["AceroOscuro"], "Chest", "armadura", bisel=0.005)
    crear_viga("Pectoral_L", (-0.025, -0.198, 1.40), (-0.276, -0.157, 1.43), 0.025, 0.018, mat["AceroOscuro"], "Chest", "armadura", bisel=0.005)
    crear_viga("Pectoral_R", (0.025, -0.198, 1.40), (0.276, -0.157, 1.43), 0.025, 0.018, mat["AceroOscuro"], "Chest", "armadura", bisel=0.005)
    # Fajas de acero superpuestas: dan lectura de placas y volumen al torso.
    for nivel, z in enumerate((1.245, 1.305, 1.365, 1.465)):
        ancho = (0.255, 0.295, 0.32, 0.29)[nivel]
        y_lateral = (-0.162, -0.176, -0.19, -0.18)[nivel]
        crear_viga(
            f"Peto_Faja_{nivel:02d}_L",
            (-ancho, y_lateral, z),
            (0, -0.204, z + 0.012),
            0.012,
            0.009,
            mat["Acero"],
            "Chest",
            "armadura",
            bisel=0.003,
        )
        crear_viga(
            f"Peto_Faja_{nivel:02d}_R",
            (0, -0.204, z + 0.012),
            (ancho, y_lateral, z),
            0.012,
            0.009,
            mat["Acero"],
            "Chest",
            "armadura",
            bisel=0.003,
        )
    crear_toro("Ribete_Cuello", (0, 0, 1.552), 0.095, 0.014, mat["Laton"], "UpperChest", "armadura")

    # Correas diagonales de cuero que rompen la simetria militar.
    crear_viga("Correa_Pecho_1", (-0.255, -0.19, 1.50), (0.225, -0.192, 1.20), 0.055, 0.018, mat["Cuero"], "Chest", "cuero", bisel=0.006)
    crear_viga("Correa_Pecho_2", (0.30, 0.155, 1.48), (-0.23, 0.145, 1.18), 0.044, 0.015, mat["Cuero"], "Chest", "cuero", bisel=0.005)

    # Hombreras, brazales y guantes.
    for lado, signo in (("Left", -1.0), ("Right", 1.0)):
        crear_elipsoide(
            f"Hombrera_{lado}",
            (0.29 * signo, 0.0, 1.495),
            (0.17, 0.145, 0.105),
            mat["Acero"],
            f"{lado}UpperArm",
            "armadura",
            rotacion=(0.0, 0.24 * signo, 0.0),
            segmentos=28,
            anillos=18,
        )
        crear_viga(
            f"Borde_Hombrera_{lado}",
            (0.19 * signo, -0.11, 1.525),
            (0.41 * signo, -0.10, 1.43),
            0.022,
            0.018,
            mat["Laton"],
            f"{lado}UpperArm",
            "armadura",
            bisel=0.004,
        )
        crear_segmento(
            f"Brazal_{lado}",
            (0.555 * signo, -0.001, 1.285),
            (0.705 * signo, -0.005, 1.125),
            0.084,
            0.063,
            mat["Cuero"],
            f"{lado}LowerArm",
            "armadura",
            bisel=0.012,
        )
        crear_segmento(
            f"Placa_Brazal_{lado}",
            (0.57 * signo, -0.047, 1.28),
            (0.69 * signo, -0.045, 1.15),
            0.052,
            0.041,
            mat["Acero"],
            f"{lado}LowerArm",
            "armadura",
            vertices=20,
            bisel=0.008,
        )
        crear_segmento(
            f"Guante_{lado}",
            (0.712 * signo, -0.006, 1.115),
            (0.817 * signo, -0.018, 1.047),
            0.061,
            0.047,
            mat["Cuero"],
            f"{lado}Hand",
            "guante",
            bisel=0.012,
        )
        # Dedos del guante siguen los huesos de falanges individuales.
        for dedo in ("Thumb", "Index", "Middle", "Ring", "Little"):
            for tramo, radio in (("Proximal", 0.012), ("Intermediate", 0.010), ("Distal", 0.008)):
                nombre_hueso = f"{lado}{dedo}{tramo}"
                spec = ESTADO.huesos[nombre_hueso]
                crear_segmento(
                    f"Guante_{nombre_hueso}",
                    spec["head"],
                    spec["tail"],
                    radio,
                    radio * 0.82,
                    mat["Cuero"],
                    nombre_hueso,
                    "guante",
                    vertices=12,
                    bisel=0.002,
                )

    # Cinturon y faldones de tela/cuero.
    crear_toro("Cinturon", (0, 0, 1.115), 0.222, 0.035, mat["Cuero"], "Hips", "cuero")
    crear_caja("Hebilla", (0, -0.225, 1.113), (0.055, 0.018, 0.043), mat["Laton"], "Hips", "cuero", ancho_bisel=0.008)
    crear_elipsoide("Emblema_Hebilla", (0, -0.246, 1.113), (0.024, 0.009, 0.024), mat["AceroOscuro"], "Hips", "detalle", segmentos=20, anillos=12)

    paneles = (
        (-0.17, -0.105, -0.04),
        (-0.058, -0.14, -0.015),
        (0.058, -0.14, 0.015),
        (0.17, -0.105, 0.04),
        (-0.16, 0.095, 0.02),
        (0.0, 0.13, 0.0),
        (0.16, 0.095, -0.02),
    )
    for indice, (x, y, giro) in enumerate(paneles):
        material_panel = mat["Tela"] if indice < 4 else mat["TelaOscura"]
        crear_caja(
            f"Faldon_{indice:02d}",
            (x, y, 0.94),
            (0.065, 0.018, 0.18),
            material_panel,
            "Hips",
            "tela",
            rotacion=(0.03, giro, 0),
            ancho_bisel=0.012,
        )
    for lado, signo in (("Left", -1.0), ("Right", 1.0)):
        crear_caja(
            f"Tasset_{lado}",
            (0.185 * signo, -0.13, 0.93),
            (0.09, 0.026, 0.20),
            mat["Acero"],
            f"{lado}UpperLeg",
            "armadura",
            rotacion=(0.05, 0.07 * signo, 0.04 * signo),
            ancho_bisel=0.018,
        )

        # Grebas, rodilleras y botas de marcha.
        crear_segmento(
            f"Greba_{lado}",
            (0.145 * signo, -0.035, 0.55),
            (0.145 * signo, -0.02, 0.17),
            0.112,
            0.078,
            mat["Acero"],
            f"{lado}LowerLeg",
            "armadura",
            bisel=0.016,
        )
        crear_elipsoide(f"Rodillera_{lado}", (0.145 * signo, -0.075, 0.575), (0.105, 0.07, 0.09), mat["AceroOscuro"], f"{lado}LowerLeg", "armadura")
        crear_segmento(f"Bota_Cana_{lado}", (0.145 * signo, 0, 0.27), (0.145 * signo, -0.005, 0.11), 0.09, 0.08, mat["Cuero"], f"{lado}Foot", "bota", bisel=0.014)
        crear_elipsoide(
            f"Bota_Pie_{lado}",
            (0.145 * signo, -0.175, 0.085),
            (0.105, 0.205, 0.082),
            mat["Cuero"],
            f"{lado}Foot",
            "bota",
            segmentos=28,
            anillos=18,
        )
        crear_caja(f"Bota_Puntera_{lado}", (0.145 * signo, -0.325, 0.074), (0.10, 0.055, 0.05), mat["AceroOscuro"], f"{lado}Toes", "bota", ancho_bisel=0.025)

    # Remaches visibles sobre el peto y tassets.
    posiciones_remache = []
    for z, ancho in ((1.20, 0.19), (1.31, 0.27), (1.45, 0.29), (1.52, 0.23)):
        posiciones_remache.extend(((-ancho, -0.19 + (1.45 - z) * 0.1, z), (ancho, -0.19 + (1.45 - z) * 0.1, z)))
    for indice, posicion in enumerate(posiciones_remache):
        crear_elipsoide(f"Remache_{indice:02d}", posicion, (0.012, 0.008, 0.012), mat["Laton"], "Chest", "detalle", segmentos=16, anillos=10)

    crear_capa(mat["Tela"])
    crear_toro("Broche_Capa_L", (-0.23, -0.04, 1.51), 0.035, 0.010, mat["Laton"], "UpperChest", "detalle", rotacion=(PI / 2, 0, 0))
    crear_toro("Broche_Capa_R", (0.23, -0.04, 1.51), 0.035, 0.010, mat["Laton"], "UpperChest", "detalle", rotacion=(PI / 2, 0, 0))


def construir_espada(mat: Mapping[str, Any]) -> None:
    """Espada larga modular ligada al socket Weapon_R."""

    pomo = (0.755, -0.024, 1.095)
    guarda = (0.84, -0.026, 0.93)
    punta = (1.075, -0.03, 0.13)
    crear_segmento("Espada_Empunadura", pomo, guarda, 0.025, 0.025, mat["CueroClaro"], "Weapon_R", "arma", vertices=20, bisel=0.006)
    crear_elipsoide("Espada_Pomo", (0.74, -0.023, 1.125), (0.035, 0.028, 0.035), mat["Laton"], "Weapon_R", "arma", segmentos=20, anillos=12)
    # Guarda perpendicular a la direccion principal y legible desde camara.
    crear_viga("Espada_Guarda", (0.73, -0.028, 0.895), (0.94, -0.028, 0.962), 0.033, 0.025, mat["Laton"], "Weapon_R", "arma", bisel=0.008)
    crear_viga("Espada_Hoja", (0.847, -0.027, 0.91), punta, 0.082, 0.018, mat["Filo"], "Weapon_R", "arma", bisel=0.006)
    # Nervio central y punta acentuada.
    crear_viga("Espada_Canal", (0.86, -0.038, 0.87), (1.05, -0.039, 0.21), 0.018, 0.006, mat["AceroOscuro"], "Weapon_R", "arma", bisel=0.002)
    crear_segmento("Espada_Punta", (1.05, -0.03, 0.21), punta, 0.041, 0.002, mat["Filo"], "Weapon_R", "arma", vertices=4, bisel=0.002)


def construir_escudo(mat: Mapping[str, Any]) -> None:
    centro = (-0.79, -0.095, 1.06)
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.34, depth=0.052, location=centro, rotation=(PI / 2, 0, 0))
    base = bpy.context.object
    base.name = "Escudo_Base"
    aplicar_transformaciones(base)
    biselar(base, 0.015, 3)
    suavizar(base)
    asignar_material(base, mat["AceroOscuro"])
    registrar_pieza(base, "Shield_L", "escudo")
    crear_toro("Escudo_Borde", centro, 0.315, 0.032, mat["Laton"], "Shield_L", "escudo", rotacion=(PI / 2, 0, 0))
    crear_elipsoide("Escudo_Umbo", (-0.79, -0.145, 1.06), (0.105, 0.052, 0.105), mat["Acero"], "Shield_L", "escudo", segmentos=28, anillos=18)
    # Emblema simple de lobo/chevron en relieve.
    crear_viga("Escudo_Emblema_L", (-0.95, -0.153, 1.16), (-0.79, -0.156, 0.94), 0.035, 0.018, mat["Tela"], "Shield_L", "escudo", bisel=0.006)
    crear_viga("Escudo_Emblema_R", (-0.63, -0.153, 1.16), (-0.79, -0.156, 0.94), 0.035, 0.018, mat["Tela"], "Shield_L", "escudo", bisel=0.006)
    for indice, angulo in enumerate(range(0, 360, 45)):
        rad = math.radians(angulo)
        x = centro[0] + 0.28 * math.cos(rad)
        z = centro[2] + 0.28 * math.sin(rad)
        crear_elipsoide(f"Escudo_Remache_{indice:02d}", (x, -0.151, z), (0.014, 0.009, 0.014), mat["Laton"], "Shield_L", "detalle", segmentos=14, anillos=8)


def construir_guerrero(nombre: str) -> Any:
    mat = crear_materiales()
    rig = crear_armature(nombre)
    construir_cuerpo_y_rostro(mat)
    construir_armadura(mat)
    construir_espada(mat)
    construir_escudo(mat)
    return rig


# ---------------------------------------------------------------------------
# Animaciones basicas
# ---------------------------------------------------------------------------


HUESOS_ANIMADOS = (
    "Root", "Hips", "Spine", "Chest", "UpperChest", "Neck", "Head",
    "LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "LeftToes",
    "RightUpperLeg", "RightLowerLeg", "RightFoot", "RightToes",
)


def _pose(rotaciones: Optional[Mapping[str, Sequence[float]]] = None, ubicaciones: Optional[Mapping[str, Sequence[float]]] = None) -> Dict[str, Any]:
    return {"rot": dict(rotaciones or {}), "loc": dict(ubicaciones or {})}


def crear_accion(
    rig: Any,
    nombre: str,
    fin: int,
    claves: Sequence[Tuple[int, Dict[str, Any]]],
    bucle: bool,
) -> Any:
    accion = bpy.data.actions.new(name=nombre)
    accion.use_fake_user = True
    accion["fps"] = FPS
    accion["loop"] = bucle
    accion["unity_clip_name"] = nombre
    rig.animation_data_create()
    rig.animation_data.action = accion

    for fotograma, estado in claves:
        for nombre_hueso in HUESOS_ANIMADOS:
            pb = rig.pose.bones.get(nombre_hueso)
            if not pb:
                continue
            pb.rotation_mode = "XYZ"
            pb.location = estado["loc"].get(nombre_hueso, (0.0, 0.0, 0.0))
            pb.rotation_euler = estado["rot"].get(nombre_hueso, (0.0, 0.0, 0.0))
            pb.scale = (1.0, 1.0, 1.0)
            pb.keyframe_insert(data_path="location", frame=fotograma, group=nombre_hueso)
            pb.keyframe_insert(data_path="rotation_euler", frame=fotograma, group=nombre_hueso)
            pb.keyframe_insert(data_path="scale", frame=fotograma, group=nombre_hueso)

    accion["frame_start"] = 1
    accion["frame_end"] = fin
    ESTADO.acciones.append(accion)
    rig.animation_data.action = None
    return accion


def crear_animaciones(rig: Any) -> None:
    # Idle: respiracion, balance de hombros y transferencia sutil de peso.
    crear_accion(
        rig,
        "Idle",
        72,
        (
            (1, _pose({"Chest": (0, 0, -0.018), "Head": (0.01, 0, 0.012)}, {"Hips": (0, 0, 0)})),
            (18, _pose({"Chest": (-0.012, 0, 0.012), "UpperChest": (0.008, 0, 0), "LeftUpperArm": (0.01, 0, 0.014), "RightUpperArm": (-0.01, 0, -0.014)}, {"Hips": (0, 0, 0.008)})),
            (36, _pose({"Chest": (0, 0, 0.018), "Head": (-0.008, 0, -0.012)}, {"Hips": (0, 0, 0.002)})),
            (54, _pose({"Chest": (0.012, 0, -0.01), "UpperChest": (-0.008, 0, 0), "LeftUpperArm": (-0.01, 0, -0.012), "RightUpperArm": (0.01, 0, 0.012)}, {"Hips": (0, 0, 0.007)})),
            (72, _pose({"Chest": (0, 0, -0.018), "Head": (0.01, 0, 0.012)}, {"Hips": (0, 0, 0)})),
        ),
        True,
    )

    # Walk: contactos alternos; X local inclina las piernas hacia delante/atras.
    crear_accion(
        rig,
        "Walk",
        32,
        (
            (1, _pose({"LeftUpperLeg": (0.48, 0, 0), "RightUpperLeg": (-0.48, 0, 0), "LeftLowerLeg": (-0.18, 0, 0), "RightLowerLeg": (0.62, 0, 0), "LeftUpperArm": (-0.34, 0, 0.06), "RightUpperArm": (0.34, 0, -0.06), "Chest": (0, 0.06, 0)}, {"Hips": (0, 0, 0)})),
            (9, _pose({"LeftUpperLeg": (0.05, 0, 0), "RightUpperLeg": (-0.05, 0, 0), "LeftLowerLeg": (0.18, 0, 0), "RightLowerLeg": (0.30, 0, 0), "LeftUpperArm": (-0.05, 0, 0), "RightUpperArm": (0.05, 0, 0)}, {"Hips": (0, 0, 0.035)})),
            (17, _pose({"LeftUpperLeg": (-0.48, 0, 0), "RightUpperLeg": (0.48, 0, 0), "LeftLowerLeg": (0.62, 0, 0), "RightLowerLeg": (-0.18, 0, 0), "LeftUpperArm": (0.34, 0, 0.06), "RightUpperArm": (-0.34, 0, -0.06), "Chest": (0, -0.06, 0)}, {"Hips": (0, 0, 0)})),
            (25, _pose({"LeftUpperLeg": (-0.05, 0, 0), "RightUpperLeg": (0.05, 0, 0), "LeftLowerLeg": (0.30, 0, 0), "RightLowerLeg": (0.18, 0, 0), "LeftUpperArm": (0.05, 0, 0), "RightUpperArm": (-0.05, 0, 0)}, {"Hips": (0, 0, 0.035)})),
            (32, _pose({"LeftUpperLeg": (0.48, 0, 0), "RightUpperLeg": (-0.48, 0, 0), "LeftLowerLeg": (-0.18, 0, 0), "RightLowerLeg": (0.62, 0, 0), "LeftUpperArm": (-0.34, 0, 0.06), "RightUpperArm": (0.34, 0, -0.06), "Chest": (0, 0.06, 0)}, {"Hips": (0, 0, 0)})),
        ),
        True,
    )

    crear_accion(
        rig,
        "Run",
        24,
        (
            (1, _pose({"Spine": (0.18, 0, 0), "LeftUpperLeg": (0.78, 0, 0), "RightUpperLeg": (-0.72, 0, 0), "LeftLowerLeg": (-0.22, 0, 0), "RightLowerLeg": (1.05, 0, 0), "LeftUpperArm": (-0.65, 0, 0.08), "RightUpperArm": (0.65, 0, -0.08), "LeftLowerArm": (-0.55, 0, 0), "RightLowerArm": (-0.55, 0, 0)}, {"Hips": (0, 0, 0.02)})),
            (7, _pose({"Spine": (0.22, 0, 0), "LeftUpperLeg": (0.05, 0, 0), "RightUpperLeg": (-0.05, 0, 0), "LeftLowerLeg": (0.55, 0, 0), "RightLowerLeg": (0.75, 0, 0)}, {"Hips": (0, 0, 0.09)})),
            (13, _pose({"Spine": (0.18, 0, 0), "LeftUpperLeg": (-0.72, 0, 0), "RightUpperLeg": (0.78, 0, 0), "LeftLowerLeg": (1.05, 0, 0), "RightLowerLeg": (-0.22, 0, 0), "LeftUpperArm": (0.65, 0, 0.08), "RightUpperArm": (-0.65, 0, -0.08), "LeftLowerArm": (-0.55, 0, 0), "RightLowerArm": (-0.55, 0, 0)}, {"Hips": (0, 0, 0.02)})),
            (19, _pose({"Spine": (0.22, 0, 0), "LeftUpperLeg": (-0.05, 0, 0), "RightUpperLeg": (0.05, 0, 0), "LeftLowerLeg": (0.75, 0, 0), "RightLowerLeg": (0.55, 0, 0)}, {"Hips": (0, 0, 0.09)})),
            (24, _pose({"Spine": (0.18, 0, 0), "LeftUpperLeg": (0.78, 0, 0), "RightUpperLeg": (-0.72, 0, 0), "LeftLowerLeg": (-0.22, 0, 0), "RightLowerLeg": (1.05, 0, 0), "LeftUpperArm": (-0.65, 0, 0.08), "RightUpperArm": (0.65, 0, -0.08)}, {"Hips": (0, 0, 0.02)})),
        ),
        True,
    )

    crear_accion(
        rig,
        "Attack",
        36,
        (
            (1, _pose({"RightUpperArm": (-0.20, 0.15, -0.12), "RightLowerArm": (-0.25, 0, 0), "LeftUpperArm": (-0.12, 0, 0.18)})),
            (9, _pose({"Spine": (-0.08, -0.30, 0), "Chest": (-0.15, -0.38, 0), "RightUpperArm": (-1.10, 0.20, -0.65), "RightLowerArm": (-1.25, 0.12, 0.1), "RightHand": (0, 0.25, 0), "LeftUpperArm": (-0.35, 0.1, 0.35), "LeftLowerArm": (-0.65, 0, 0)}, {"Hips": (0, 0, 0.015)})),
            (18, _pose({"Spine": (0.14, 0.38, 0), "Chest": (0.28, 0.55, -0.08), "RightUpperArm": (0.55, -0.22, 0.72), "RightLowerArm": (-0.20, -0.12, -0.2), "RightHand": (0, -0.3, 0), "LeftUpperArm": (-0.20, -0.1, 0.45), "LeftLowerArm": (-0.75, 0.05, 0), "LeftUpperLeg": (0.18, 0, 0), "RightUpperLeg": (-0.15, 0, 0)}, {"Hips": (0, -0.035, -0.025)})),
            (25, _pose({"Chest": (0.12, 0.18, 0), "RightUpperArm": (0.25, -0.1, 0.30), "RightLowerArm": (-0.35, 0, 0), "LeftUpperArm": (-0.15, 0, 0.25)})),
            (36, _pose({"RightUpperArm": (-0.20, 0.15, -0.12), "RightLowerArm": (-0.25, 0, 0), "LeftUpperArm": (-0.12, 0, 0.18)})),
        ),
        False,
    )

    # Segundo estilo: carga alta y golpe vertical con transferencia del peso.
    crear_accion(
        rig,
        "Attack_Overhead",
        36,
        (
            (1, _pose({"RightUpperArm": (-0.18, 0.08, -0.08), "RightLowerArm": (-0.28, 0, 0), "LeftUpperArm": (-0.12, 0, 0.18)})),
            (9, _pose({"Spine": (-0.18, 0, 0), "Chest": (-0.12, 0, 0), "RightUpperArm": (-2.25, 0.12, -0.18), "RightLowerArm": (-0.45, 0, 0), "LeftUpperArm": (-0.38, 0.08, 0.30), "LeftLowerArm": (-0.45, 0, 0)}, {"Hips": (0, -0.025, -0.045)})),
            (17, _pose({"Spine": (0.12, 0, 0), "Chest": (0.42, 0.04, 0), "RightUpperArm": (0.38, 0.08, -0.08), "RightLowerArm": (-0.18, 0, 0), "LeftUpperArm": (-0.30, 0.08, 0.28), "LeftLowerArm": (-0.65, 0, 0), "LeftUpperLeg": (0.16, 0, 0), "RightUpperLeg": (-0.12, 0, 0)}, {"Hips": (0, 0.015, -0.11)})),
            (25, _pose({"Spine": (0.20, 0, 0), "Chest": (0.18, 0.02, 0), "RightUpperArm": (0.52, 0.02, 0.02), "RightLowerArm": (-0.22, 0, 0), "LeftUpperArm": (-0.22, 0.05, 0.22)}, {"Hips": (0, 0.01, -0.055)})),
            (36, _pose({"RightUpperArm": (-0.20, 0.15, -0.12), "RightLowerArm": (-0.25, 0, 0), "LeftUpperArm": (-0.12, 0, 0.18)})),
        ),
        False,
    )

    # Tercer estilo: estocada frontal, con cadera adelantada y mano extendida.
    crear_accion(
        rig,
        "Attack_Thrust",
        32,
        (
            (1, _pose({"RightUpperArm": (-0.16, 0.10, -0.08), "RightLowerArm": (-0.28, 0, 0), "LeftUpperArm": (-0.14, 0, 0.18)})),
            (8, _pose({"Spine": (-0.14, 0, 0), "Chest": (-0.08, 0, 0), "RightUpperArm": (-0.82, 0.08, -0.30), "RightLowerArm": (-1.22, 0, 0), "LeftUpperArm": (-0.40, 0.12, 0.28), "LeftLowerArm": (-0.52, 0, 0), "LeftUpperLeg": (0.25, 0, 0), "RightUpperLeg": (-0.32, 0, 0)}, {"Hips": (0, 0.01, -0.055)})),
            (16, _pose({"Spine": (0.10, 0, 0), "Chest": (0.20, 0, 0), "RightUpperArm": (-0.35, 0.02, -0.08), "RightLowerArm": (-0.12, 0, 0), "LeftUpperArm": (-0.32, 0.1, 0.30), "LeftLowerArm": (-0.62, 0, 0), "LeftUpperLeg": (0.62, 0, 0), "RightUpperLeg": (-0.42, 0, 0)}, {"Hips": (0, 0.015, -0.13)})),
            (23, _pose({"Spine": (0.06, 0, 0), "Chest": (0.14, 0, 0), "RightUpperArm": (-0.28, 0.04, -0.06), "RightLowerArm": (-0.12, 0, 0), "LeftUpperArm": (-0.28, 0.1, 0.25), "LeftUpperLeg": (0.35, 0, 0), "RightUpperLeg": (-0.24, 0, 0)}, {"Hips": (0, 0.005, -0.06)})),
            (32, _pose({"RightUpperArm": (-0.16, 0.10, -0.08), "RightLowerArm": (-0.28, 0, 0), "LeftUpperArm": (-0.14, 0, 0.18)})),
        ),
        False,
    )

    # El salto separa anticipacion, fase aerea y recuperacion al aterrizar.
    crear_accion(
        rig,
        "Jump_Crouch",
        8,
        (
            (1, _pose()),
            (3, _pose({"Spine": (0.08, 0, 0), "Chest": (0.04, 0, 0), "LeftUpperArm": (-0.18, 0, -0.12), "RightUpperArm": (-0.18, 0, 0.12), "LeftLowerLeg": (0.18, 0, 0), "RightLowerLeg": (0.18, 0, 0)}, {"Hips": (0, 0, -0.025)})),
            (8, _pose({"Spine": (0.16, 0, 0), "Chest": (0.08, 0, 0), "LeftUpperLeg": (0.22, 0, 0), "RightUpperLeg": (0.22, 0, 0), "LeftLowerLeg": (0.82, 0, 0), "RightLowerLeg": (0.82, 0, 0), "LeftUpperArm": (-0.30, 0, -0.16), "RightUpperArm": (-0.30, 0, 0.16)}, {"Hips": (0, -0.025, -0.075)})),
        ),
        False,
    )
    crear_accion(
        rig,
        "Jump_Air",
        24,
        (
            (1, _pose({"Spine": (0.10, 0, 0), "Chest": (0.05, 0, 0), "LeftUpperLeg": (0.30, 0, 0), "RightUpperLeg": (0.30, 0, 0), "LeftLowerLeg": (0.55, 0, 0), "RightLowerLeg": (0.55, 0, 0), "LeftUpperArm": (-0.22, 0, -0.20), "RightUpperArm": (-0.22, 0, 0.20)})),
            (7, _pose({"Spine": (0.12, 0, 0), "Chest": (0.06, 0, 0), "LeftUpperLeg": (0.34, 0, 0), "RightUpperLeg": (0.26, 0, 0), "LeftLowerLeg": (0.52, 0, 0), "RightLowerLeg": (0.62, 0, 0), "LeftUpperArm": (-0.18, 0, -0.18), "RightUpperArm": (-0.18, 0, 0.18)})),
            (13, _pose({"Spine": (0.08, 0, 0), "Chest": (0.04, 0, 0), "LeftUpperLeg": (0.28, 0, 0), "RightUpperLeg": (0.32, 0, 0), "LeftLowerLeg": (0.60, 0, 0), "RightLowerLeg": (0.50, 0, 0), "LeftUpperArm": (-0.24, 0, -0.18), "RightUpperArm": (-0.24, 0, 0.18)})),
            (19, _pose({"Spine": (0.12, 0, 0), "Chest": (0.06, 0, 0), "LeftUpperLeg": (0.34, 0, 0), "RightUpperLeg": (0.26, 0, 0), "LeftLowerLeg": (0.52, 0, 0), "RightLowerLeg": (0.62, 0, 0), "LeftUpperArm": (-0.18, 0, -0.18), "RightUpperArm": (-0.18, 0, 0.18)})),
            (24, _pose({"Spine": (0.10, 0, 0), "Chest": (0.05, 0, 0), "LeftUpperLeg": (0.30, 0, 0), "RightUpperLeg": (0.30, 0, 0), "LeftLowerLeg": (0.55, 0, 0), "RightLowerLeg": (0.55, 0, 0), "LeftUpperArm": (-0.22, 0, -0.20), "RightUpperArm": (-0.22, 0, 0.20)})),
        ),
        True,
    )
    crear_accion(
        rig,
        "Jump_Land",
        14,
        (
            (1, _pose({"Spine": (0.18, 0, 0), "Chest": (0.08, 0, 0), "LeftUpperLeg": (0.18, 0, 0), "RightUpperLeg": (0.18, 0, 0), "LeftLowerLeg": (0.90, 0, 0), "RightLowerLeg": (0.90, 0, 0), "LeftUpperArm": (-0.28, 0, -0.18), "RightUpperArm": (-0.28, 0, 0.18)}, {"Hips": (0, 0, -0.07)})),
            (5, _pose({"Spine": (0.18, 0, 0), "Chest": (0.10, 0, 0), "LeftUpperLeg": (0.20, 0, 0), "RightUpperLeg": (0.20, 0, 0), "LeftLowerLeg": (0.92, 0, 0), "RightLowerLeg": (0.92, 0, 0), "LeftUpperArm": (-0.26, 0, -0.18), "RightUpperArm": (-0.26, 0, 0.18)}, {"Hips": (0, 0, -0.09)})),
            (10, _pose({"Spine": (0.06, 0, 0), "Chest": (0.02, 0, 0), "LeftUpperLeg": (0.05, 0, 0), "RightUpperLeg": (0.05, 0, 0), "LeftLowerLeg": (0.18, 0, 0), "RightLowerLeg": (0.18, 0, 0), "LeftUpperArm": (-0.08, 0, -0.08), "RightUpperArm": (-0.08, 0, 0.08)}, {"Hips": (0, 0, -0.025)})),
            (14, _pose()),
        ),
        False,
    )

    crear_accion(
        rig,
        "Block",
        32,
        (
            (1, _pose()),
            (8, _pose({"LeftUpperArm": (-0.55, -0.15, -0.72), "LeftLowerArm": (-1.0, 0.1, 0.15), "LeftHand": (0.1, 0.25, 0), "RightUpperArm": (-0.25, 0.1, 0.2), "Chest": (-0.08, -0.15, 0)})),
            (20, _pose({"LeftUpperArm": (-0.62, -0.12, -0.78), "LeftLowerArm": (-1.10, 0.12, 0.18), "LeftHand": (0.12, 0.3, 0), "RightUpperArm": (-0.35, 0.1, 0.25), "RightLowerArm": (-0.45, 0, 0), "Chest": (-0.12, -0.18, 0), "LeftUpperLeg": (0.10, 0, 0), "RightUpperLeg": (-0.08, 0, 0)}, {"Hips": (0, 0.015, -0.03)})),
            (32, _pose({"LeftUpperArm": (-0.55, -0.15, -0.72), "LeftLowerArm": (-1.0, 0.1, 0.15), "LeftHand": (0.1, 0.25, 0), "RightUpperArm": (-0.25, 0.1, 0.2), "Chest": (-0.08, -0.15, 0)})),
        ),
        True,
    )

    crear_accion(
        rig,
        "Hit",
        24,
        (
            (1, _pose()),
            (6, _pose({"Spine": (-0.22, 0.20, 0.10), "Chest": (-0.35, 0.35, 0.15), "Head": (0.28, -0.18, 0), "LeftUpperArm": (0.28, 0, -0.22), "RightUpperArm": (0.28, 0, 0.22)}, {"Hips": (0, 0.025, -0.035)})),
            (12, _pose({"Spine": (0.12, -0.12, -0.06), "Chest": (0.18, -0.2, -0.08), "Head": (-0.12, 0.08, 0)}, {"Hips": (0, -0.015, -0.01)})),
            (24, _pose()),
        ),
        False,
    )

    crear_accion(
        rig,
        "Death",
        56,
        (
            (1, _pose()),
            (12, _pose({"Spine": (-0.15, 0.18, 0.08), "Chest": (-0.28, 0.28, 0.12), "Head": (0.22, -0.1, 0), "LeftUpperArm": (0.25, 0, -0.28), "RightUpperArm": (-0.15, 0, 0.35)}, {"Hips": (0, 0.02, -0.06)})),
            (28, _pose({"Hips": (0.65, 0.12, 0.45), "Spine": (0.72, 0.15, 0.10), "Chest": (0.62, 0.1, 0.18), "Head": (-0.28, 0, -0.15), "LeftUpperArm": (0.55, 0.15, -0.30), "RightUpperArm": (-0.4, -0.1, 0.45), "LeftUpperLeg": (-0.32, 0, 0.12), "RightUpperLeg": (0.42, 0, -0.1)}, {"Hips": (0, 0.12, -0.48)})),
            (44, _pose({"Hips": (1.18, 0.12, 0.55), "Spine": (0.82, 0.08, 0.12), "Chest": (0.45, 0, 0.12), "Head": (-0.35, 0, -0.12), "LeftUpperArm": (0.75, 0.1, -0.4), "RightUpperArm": (-0.55, -0.08, 0.55), "LeftUpperLeg": (-0.5, 0, 0.18), "RightUpperLeg": (0.6, 0, -0.16)}, {"Hips": (0, 0.2, -0.87)})),
            (56, _pose({"Hips": (1.28, 0.12, 0.57), "Spine": (0.85, 0.08, 0.12), "Chest": (0.48, 0, 0.12), "Head": (-0.38, 0, -0.12), "LeftUpperArm": (0.78, 0.1, -0.42), "RightUpperArm": (-0.58, -0.08, 0.58), "LeftUpperLeg": (-0.52, 0, 0.2), "RightUpperLeg": (0.62, 0, -0.18)}, {"Hips": (0, 0.21, -0.91)})),
        ),
        False,
    )

    restablecer_pose(rig)


def restablecer_pose(rig: Any) -> None:
    if rig.animation_data:
        rig.animation_data.action = None
    for pb in rig.pose.bones:
        pb.location = (0, 0, 0)
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.scene.frame_set(1)


# ---------------------------------------------------------------------------
# Estudio de preview
# ---------------------------------------------------------------------------


def orientar_hacia(objeto: Any, objetivo: Sequence[float]) -> None:
    direccion = v3(objetivo) - objeto.location
    objeto.rotation_euler = direccion.to_track_quat("-Z", "Y").to_euler()


def crear_luz(nombre: str, tipo: str, ubicacion: Sequence[float], energia: float, color: Sequence[float], tamano: float, objetivo: Sequence[float]) -> Any:
    datos = bpy.data.lights.new(name=f"DATOS_{nombre}", type=tipo)
    datos.energy = energia
    datos.color = color
    if hasattr(datos, "shape"):
        datos.shape = "DISK"
    if hasattr(datos, "size"):
        datos.size = tamano
    objeto = bpy.data.objects.new(nombre, datos)
    ESTADO.coleccion_preview.objects.link(objeto)
    objeto.location = ubicacion
    orientar_hacia(objeto, objetivo)
    return objeto


def preparar_estudio(mat: Mapping[str, Any]) -> Any:
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=1.55, depth=0.10, location=(0, 0, -0.06))
    pedestal = bpy.context.object
    pedestal.name = "PREVIEW_Pedestal"
    mover_a_coleccion(pedestal, ESTADO.coleccion_preview)
    biselar(pedestal, 0.035, 3)
    asignar_material(pedestal, mat["Piedra"])

    crear_luz("PREVIEW_Key", "AREA", (3.2, -3.8, 4.4), 1050, (1.0, 0.72, 0.52), 2.2, (0, 0, 1.05))
    crear_luz("PREVIEW_Fill", "AREA", (-3.0, -2.2, 2.7), 720, (0.42, 0.62, 1.0), 2.6, (0, 0, 1.1))
    crear_luz("PREVIEW_Rim", "AREA", (0.8, 3.2, 3.6), 1250, (0.72, 0.82, 1.0), 1.7, (0, 0, 1.3))
    crear_luz("PREVIEW_Face", "AREA", (0.0, -2.0, 2.3), 280, (1.0, 0.86, 0.72), 0.8, (0, -0.03, 1.7))

    datos_camara = bpy.data.cameras.new("DATOS_PREVIEW_Camera")
    camara = bpy.data.objects.new("PREVIEW_Camera", datos_camara)
    ESTADO.coleccion_preview.objects.link(camara)
    camara.location = (3.15, -5.5, 2.55)
    datos_camara.lens = 58
    datos_camara.sensor_width = 36
    orientar_hacia(camara, (0, 0, 1.02))
    bpy.context.scene.camera = camara
    return camara


def configurar_motor_preview(escena: Any, motor_solicitado: str, muestras: int) -> str:
    # Blender 5.2 identifica Eevee como BLENDER_EEVEE. Se mantienen alternativas
    # para ejecutar el mismo script en ramas 4.x sin editarlo.
    candidatos = []
    for candidato in (motor_solicitado, "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"):
        if candidato not in candidatos:
            candidatos.append(candidato)
    motor_activo = ""
    for candidato in candidatos:
        try:
            escena.render.engine = candidato
            motor_activo = candidato
            break
        except Exception:
            continue
    if not motor_activo:
        raise RuntimeError("No se encontro un motor de render compatible.")

    # Las propiedades de muestreo han cambiado entre Eevee Next y Eevee 5.x.
    if hasattr(escena, "eevee"):
        for atributo in ("taa_render_samples", "taa_samples"):
            if hasattr(escena.eevee, atributo):
                setattr(escena.eevee, atributo, muestras)
    if hasattr(escena.render, "film_transparent"):
        escena.render.film_transparent = False
    return motor_activo


def renderizar_preview(args: argparse.Namespace, ruta: Path) -> None:
    escena = bpy.context.scene
    ancho, alto = resolver_resolucion(args.preview_resolution)
    escena.render.resolution_x = ancho
    escena.render.resolution_y = alto
    escena.render.resolution_percentage = 100
    escena.render.image_settings.file_format = "PNG"
    escena.render.image_settings.color_mode = "RGBA"
    escena.render.filepath = str(ruta)
    motor = configurar_motor_preview(escena, args.engine, max(1, args.preview_samples))

    accion = bpy.data.actions.get(args.preview_action)
    if accion:
        ESTADO.rig.animation_data_create()
        ESTADO.rig.animation_data.action = accion
        fin = int(accion.get("frame_end", args.preview_frame))
        escena.frame_set(max(1, min(args.preview_frame, fin)))
    log(f"Renderizando preview {ancho}x{alto} con {motor}...")
    bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------------------
# Coordenadas y exportacion
# ---------------------------------------------------------------------------


LANDMARKS = {
    "ground": (0.0, 0.0, 0.0),
    "pelvis_center": (0.0, 0.0, 1.02),
    "chest_center": (0.0, -0.01, 1.40),
    "neck_base": (0.0, 0.0, 1.57),
    "head_center": (0.0, 0.0, 1.735),
    "head_top": (0.0, 0.0, 1.87),
    "left_eye": (-0.039, -0.104, 1.758),
    "right_eye": (0.039, -0.104, 1.758),
    "left_shoulder": (-0.24, 0.0, 1.52),
    "right_shoulder": (0.24, 0.0, 1.52),
    "left_elbow": (-0.53, 0.0, 1.31),
    "right_elbow": (0.53, 0.0, 1.31),
    "left_wrist": (-0.72, -0.005, 1.11),
    "right_wrist": (0.72, -0.005, 1.11),
    "left_knee": (-0.145, 0.0, 0.57),
    "right_knee": (0.145, 0.0, 0.57),
    "left_ankle": (-0.145, -0.005, 0.14),
    "right_ankle": (0.145, -0.005, 0.14),
    "sword_tip": (1.075, -0.03, 0.13),
    "shield_center": (-0.79, -0.095, 1.06),
}


def aabb_exportable() -> Tuple[Any, Any]:
    minimo = Vector((float("inf"), float("inf"), float("inf")))
    maximo = Vector((float("-inf"), float("-inf"), float("-inf")))
    encontrados = False
    # La caja se calcula en pose de reposo sobre las mallas exportables.
    for objeto in ESTADO.objetos_exportables:
        if objeto.type != "MESH":
            continue
        encontrados = True
        for esquina in objeto.bound_box:
            punto = objeto.matrix_world @ Vector(esquina)
            minimo.x = min(minimo.x, punto.x)
            minimo.y = min(minimo.y, punto.y)
            minimo.z = min(minimo.z, punto.z)
            maximo.x = max(maximo.x, punto.x)
            maximo.y = max(maximo.y, punto.y)
            maximo.z = max(maximo.z, punto.z)
    if not encontrados:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    return minimo, maximo


def crear_manifiesto(nombre: str, args: argparse.Namespace, archivos: Mapping[str, str]) -> Dict[str, Any]:
    restablecer_pose(ESTADO.rig)
    minimo, maximo = aabb_exportable()

    huesos: Dict[str, Any] = {}
    for nombre_hueso, spec in ESTADO.huesos.items():
        cabeza = v3(spec["head"])
        cola = v3(spec["tail"])
        huesos[nombre_hueso] = {
            "parent": spec["parent"],
            "deform": bool(spec["deform"]),
            "head_blender_xyz": lista_vector(cabeza),
            "tail_blender_xyz": lista_vector(cola),
            "head_unity_xyz": coordenada_unity(cabeza),
            "tail_unity_xyz": coordenada_unity(cola),
        }

    landmarks = {}
    for clave, valor in LANDMARKS.items():
        vector = v3(valor)
        landmarks[clave] = {
            "blender_xyz": lista_vector(vector),
            "unity_xyz": coordenada_unity(vector),
        }

    sockets = {}
    for clave in ("Weapon_R", "Shield_L", "BackSocket", "HeadSocket", "ChestSocket"):
        punto = v3(ESTADO.huesos[clave]["head"])
        sockets[clave] = {
            "parent_bone": ESTADO.huesos[clave]["parent"],
            "blender_xyz": lista_vector(punto),
            "unity_xyz": coordenada_unity(punto),
        }

    estadisticas_malla = []
    total_vertices = 0
    total_poligonos = 0
    for objeto in ESTADO.objetos_exportables:
        if objeto.type != "MESH":
            continue
        vertices = len(objeto.data.vertices)
        poligonos = len(objeto.data.polygons)
        total_vertices += vertices
        total_poligonos += poligonos
        estadisticas_malla.append(
            {
                "name": objeto.name,
                "category": objeto.get("categoria", ""),
                "bone": objeto.get("hueso_unity", ""),
                "vertices": vertices,
                "polygons": poligonos,
            }
        )

    return {
        "generator": "guerrero_1.py",
        "generator_version": VERSION_GENERADOR,
        "character": nombre,
        "archetype": "Príncipe guerrero africano" if args.style == "african_prince" else "Guerrero humano realista",
        "style": args.style,
        "target_engine": "Unity Humanoid",
        "seed": args.seed,
        "units": "meters",
        "height_m": round(float(maximo.z - minimo.z), 6),
        "blender_axes": {"right": "+X", "forward": "-Y", "up": "+Z"},
        "unity_axes": {"right": "+X", "forward": "+Z", "up": "+Y"},
        "conversion": BLENDER_A_UNITY,
        "aabb": {
            "blender": {"min_xyz": lista_vector(minimo), "max_xyz": lista_vector(maximo)},
            # Al invertir Y, el minimo Unity-Z procede del maximo Blender-Y.
            "unity": {
                "min_xyz": [round(minimo.x, 6), round(minimo.z, 6), round(-maximo.y, 6)],
                "max_xyz": [round(maximo.x, 6), round(maximo.z, 6), round(-minimo.y, 6)],
            },
        },
        "landmarks": landmarks,
        "bones": huesos,
        "sockets": sockets,
        "animations": [
            {
                "name": accion.name,
                "frame_start": int(accion.get("frame_start", 1)),
                "frame_end": int(accion.get("frame_end", 1)),
                "fps": FPS,
                "loop": bool(accion.get("loop", False)),
            }
            for accion in ESTADO.acciones
        ],
        "mesh_summary": {
            "objects": len(estadisticas_malla),
            "vertices": total_vertices,
            "polygons": total_poligonos,
            "parts": estadisticas_malla,
        },
        "materials": list(ESTADO.materiales.keys()),
        "files": dict(archivos),
        "unity_import": {
            "rig_type": "Humanoid",
            "avatar_definition": "Create From This Model",
            "scale_factor": 1.0,
            "read_write": False,
            "recommended_material_workflow": "URP Lit; extraer materiales si se desea editarlos",
            "notes": [
                "El FBX usa -Z Forward / Y Up.",
                "Los clips se exportan desde las acciones Idle, Walk, Run, Attack, Block, Hit y Death.",
                "Weapon_R y Shield_L son sockets deformantes para que los accesorios sigan las manos.",
            ],
        },
    }


def seleccionar_exportables() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for objeto in ESTADO.objetos_exportables:
        if objeto and objeto.name in bpy.data.objects:
            objeto.hide_set(False)
            objeto.hide_render = False
            objeto.select_set(True)
    bpy.context.view_layer.objects.active = ESTADO.rig


def exportar_fbx(ruta: Path) -> None:
    restablecer_pose(ESTADO.rig)
    seleccionar_exportables()
    log(f"Exportando FBX: {ruta}")
    ejecutar_operador_compatible(
        bpy.ops.export_scene.fbx,
        filepath=str(ruta),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z",
        axis_up="Y",
        use_mesh_modifiers=True,
        mesh_smooth_type="FACE",
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        use_armature_deform_only=False,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=True,
        bake_anim_force_startend_keying=True,
        bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,
        path_mode="AUTO",
        embed_textures=False,
    )


def exportar_glb(ruta: Path) -> None:
    restablecer_pose(ESTADO.rig)
    seleccionar_exportables()
    log(f"Exportando GLB: {ruta}")
    ejecutar_operador_compatible(
        bpy.ops.export_scene.gltf,
        filepath=str(ruta),
        export_format="GLB",
        use_selection=True,
        export_apply=False,
        export_yup=True,
        export_skins=True,
        export_all_influences=False,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_merge_animation="ACTION",
        export_frame_range=False,
        export_force_sampling=True,
        export_nla_strips=False,
        export_materials="EXPORT",
        export_cameras=False,
        export_lights=False,
    )


def guardar_blend(ruta: Path) -> None:
    log(f"Guardando BLEND: {ruta}")
    ejecutar_operador_compatible(bpy.ops.wm.save_as_mainfile, filepath=str(ruta), check_existing=False)


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    global ESTADO
    if bpy is None:
        print(
            "Este archivo debe ejecutarse con Blender 5.x: "
            "blender --background --python guerrero_1.py -- --output-dir ./salida",
            file=sys.stderr,
        )
        return 2

    # Permite ejecutar el texto varias veces desde la misma sesion de Blender.
    ESTADO = EstadoConstruccion()
    args = analizar_argumentos(argv)
    ESTADO.estilo = args.style
    nombre = nombre_seguro(args.name)
    salida = Path(args.output_dir).expanduser().resolve()
    salida.mkdir(parents=True, exist_ok=True)

    log(f"Iniciando {nombre}; salida: {salida}")
    escena = preparar_escena(nombre)
    rig = construir_guerrero(nombre)
    crear_animaciones(rig)
    preparar_estudio(ESTADO.materiales)
    escena["generator"] = "guerrero_1.py"
    escena["generator_version"] = VERSION_GENERADOR
    escena["target_engine"] = "Unity"
    escena["character_style"] = args.style
    minimo, maximo = aabb_exportable()
    escena["character_height_m"] = round(float(maximo.z - minimo.z), 6)

    rutas = {
        "blend": str(salida / f"{nombre}.blend"),
        "fbx": str(salida / f"{nombre}.fbx"),
        "glb": str(salida / f"{nombre}.glb"),
        "json": str(salida / f"{nombre}_coordenadas.json"),
        "preview": str(salida / f"{nombre}_preview.png"),
    }
    archivos_generados: Dict[str, str] = {}

    if args.exportar_fbx:
        exportar_fbx(Path(rutas["fbx"]))
        archivos_generados["fbx"] = rutas["fbx"]
    if args.exportar_glb:
        exportar_glb(Path(rutas["glb"]))
        archivos_generados["glb"] = rutas["glb"]

    if args.render_preview:
        renderizar_preview(args, Path(rutas["preview"]))
        archivos_generados["preview"] = rutas["preview"]

    # Se guarda al final para que el BLEND abra en la misma pose atractiva del
    # preview cuando este fue solicitado; sin preview abre en reposo.
    if args.guardar_blend:
        archivos_generados["blend"] = rutas["blend"]
        guardar_blend(Path(rutas["blend"]))

    # Se escribe despues de generar todas las salidas para reflejar exactamente
    # los archivos creados en esta ejecucion.
    if args.exportar_json:
        archivos_generados["json"] = rutas["json"]
        manifiesto = crear_manifiesto(nombre, args, archivos_generados)
        with open(rutas["json"], "w", encoding="utf-8") as archivo:
            json.dump(manifiesto, archivo, ensure_ascii=False, indent=2)
        log(f"Coordenadas JSON: {rutas['json']}")

    bpy.ops.object.select_all(action="DESELECT")
    ESTADO.rig.select_set(True)
    bpy.context.view_layer.objects.active = ESTADO.rig
    log("Generacion finalizada correctamente.")
    print(json.dumps({"ok": True, "name": nombre, "files": archivos_generados}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[GUERRERO][ERROR] {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        raise
