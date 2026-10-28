# GLADIUS V1: duelo en el Coliseo

Juego de combate 3D para Windows, hecho con Python, Ursina, Panda3D y Blender.
Esta copia contiene el código y los recursos necesarios para ejecutar GLADIUS V1 desde GitHub.

## Iniciar

Haz doble clic en `run_game.bat`. Aparece la pantalla de selección con los
retratos de **Spartaco** y **Chaca_Zulo**. Haz clic en cualquiera de los dos
retratos o en su botón **ELEGIR**. El borde dorado indica quién jugará; al
pasar el cursor por la otra tarjeta, su borde se resalta en turquesa. Después
pulsa **INICIAR PELEA**; la computadora controla automáticamente al otro
gladiador.

Para comparar una vista previa PBR de los personajes, ejecuta
`run_game_pbr.bat`. Esta opción usa los materiales metálicos glTF y un entorno
de iluminación de estudio, sin reemplazar los modelos originales. Esta primera
fase mejora la respuesta de los materiales a la luz; no añade todavía mapas de
detalle ni cambia la geometría.

## Controles

- En la pantalla inicial, haz clic en el retrato o en `ELEGIR`; un marco dorado marca al luchador seleccionado y el cursor resalta la otra tarjeta al pasar por encima.
- `W`: acercarse al rival; `S`: retroceder; `A` y `D`: desplazarse a los lados respecto al rival.
- Flechas: desplazarse según la pantalla; `↓` baja y `↑` sube.
- `Mayús`: correr; sin Mayús, el personaje camina.
- `E` o `F`: recorrer el ciclo de tres ataques con espada: tajo lateral, golpe elevado y estocada. Se usa la misma tecla para todos.
- Mantén `Q`: cubrirse con el escudo y reducir el daño.
- `Espacio`: agacharse para tomar impulso y saltar, con animación de caída y aterrizaje.
- `Esc`: pausar o continuar.
- `R`: reiniciar el duelo.

La pelea termina por KO. La interfaz muestra la vida en porcentaje y los puntos
de cada luchador.

## Modelos

- Spartaco: `build/animation_preview/Guerrero_Player.glb`.
- Chaca_Zulo: `build/animation_preview/Principe_Guerrero_Africano.glb`.

Ambos usan el mismo rig, caminata, carrera, tres ataques y clips de salto. Los
retratos del selector se cargan desde `build/revised/Spartaco_menu.png` y
`build/revised/Chaca_Zulo_menu.png`. Los renders originales siguen disponibles
con sufijo `_preview.png`.

Para verificar que carguen los dos personajes y las mecánicas:

```powershell
.\.venv\Scripts\python.exe .\juego_guerrero.py --self-test
```

