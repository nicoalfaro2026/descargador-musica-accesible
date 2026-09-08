# -*- coding: utf-8 -*-
"""Ecualizador basado en la curva ya configurada por Nicolás en Stereo Tool
(sección [Equalizer] de su archivo de configuración de Stereo Tool).

Estos 240 puntos (frecuencia en Hz, ganancia en dB) fueron extraídos
directamente de esa configuración real. No se inventó ni aproximó ninguna
curva: son los mismos valores que Stereo Tool ya aplica en su transmisión.

Este módulo solo prepara el filtro de audio para MPV (a través del filtro
firequalizer de FFmpeg, que MPV expone mediante la sintaxis "lavfi=[...]").
No decide por sí mismo si el ecualizador está activado o no: eso lo maneja
quien use este módulo (por ejemplo, ReproductorMPV en reproductor.py),
guardando la preferencia de la persona usuaria como con el volumen o la
velocidad.
"""

PUNTOS_ECUALIZADOR_STEREO_TOOL = [
    (10, -8.88), (11, -9.0), (12, -9.0), (13, -9.0), (14, -9.0), (15, -9.0),
    (16, -9.0), (17, -9.0), (18, -9.0), (19, -9.0), (20, -8.94), (21, -8.94),
    (22, -8.94), (23, -8.88), (24, -8.88), (25, -8.88), (26, -8.88), (27, -8.88),
    (28, -8.88), (29, -8.88), (30, -8.88), (31, -8.88), (32, -8.88), (33, -8.82),
    (34, 7.71), (35, 7.47), (36, 7.59), (37, 8.57), (38, 8.57), (39, 8.57),
    (40, 8.63), (42, 8.63), (43, 8.69), (44, 8.69), (46, 8.51), (47, 8.51),
    (49, 8.69), (50, 8.69), (52, 8.69), (53, 8.69), (55, 8.69), (57, 8.69),
    (58, 8.69), (60, 8.69), (62, 8.69), (64, 8.69), (66, 8.69), (68, 8.69),
    (70, 8.69), (72, 8.69), (74, 8.69), (77, 8.69), (79, 8.69), (81, 8.76),
    (84, 8.27), (87, 8.33), (89, 8.33), (92, 8.33), (95, 8.57), (98, 8.27),
    (101, 8.57), (104, 8.14), (107, 7.96), (110, 7.96), (114, 7.71), (117, 7.59),
    (121, 6.98), (125, 6.92), (129, 6.98), (133, 6.67), (137, 6.31), (141, 6.49),
    (145, 6.37), (150, 6.06), (154, 5.76), (159, 5.57), (164, 5.39), (169, 5.14),
    (174, 5.08), (180, 4.96), (185, 4.71), (191, 4.47), (197, 4.22), (203, 4.04),
    (209, 3.73), (216, 3.67), (222, 3.67), (229, 3.18), (236, 2.82), (243, 2.76),
    (251, 2.51), (259, 2.2), (267, 2.02), (275, 1.9), (283, 1.78), (292, 1.47),
    (301, 1.35), (310, 1.35), (320, 1.16), (330, 1.16), (340, 1.04), (351, 1.04),
    (361, 0.98), (373, 0.92), (384, 0.86), (396, 0.8), (408, 0.8), (421, 0.67),
    (434, 0.67), (447, 0.67), (461, 0.61), (475, 0.55), (490, 0.49), (505, 0.49),
    (521, 0.37), (537, 0.37), (553, 0.31), (570, 0.24), (588, 0.12), (606, 0.12),
    (625, 0.12), (644, 0.12), (664, 0.0), (684, 0.0), (706, 0.0), (727, 0.0),
    (750, 0.0), (773, 0.0), (797, 0.0), (821, 0.0), (847, 0.0), (873, 0.0),
    (900, 0.0), (928, 0.0), (956, 0.0), (986, 0.0), (1016, 0.0), (1048, 0.0),
    (1080, 0.0), (1113, 0.0), (1148, 0.0), (1183, 0.0), (1220, 0.0), (1257, 0.0),
    (1296, 0.0), (1336, 0.0), (1377, 0.0), (1420, 0.0), (1464, 0.0), (1509, 0.0),
    (1555, 0.0), (1603, 0.0), (1653, 0.0), (1704, 0.0), (1757, 0.0), (1811, 0.0),
    (1867, 0.0), (1924, 0.0), (1984, 0.0), (2045, 0.0), (2108, 0.0), (2173, 0.0),
    (2240, 0.0), (2309, 0.0), (2381, 0.0), (2454, 0.0), (2530, 0.0), (2608, 0.0),
    (2689, 0.0), (2772, 0.0), (2857, 0.0), (2945, 0.0), (3036, 0.0), (3130, 0.0),
    (3227, 0.0), (3326, 0.0), (3429, 0.0), (3535, 0.0), (3644, 0.0), (3756, 0.0),
    (3872, 0.0), (3992, 0.0), (4115, 0.06), (4242, 0.12), (4373, 0.12), (4508, 0.12),
    (4647, 0.18), (4791, 0.24), (4939, 0.31), (5091, 0.43), (5248, 0.49), (5410, 0.55),
    (5577, 0.67), (5749, 0.73), (5927, 0.86), (6110, 0.92), (6298, 1.04), (6493, 1.04),
    (6693, 1.22), (6900, 1.22), (7113, 1.29), (7333, 1.35), (7559, 1.35), (7792, 1.35),
    (8033, 1.35), (8281, 1.35), (8536, 1.35), (8800, 1.35), (9072, 1.35), (9352, 1.35),
    (9640, 1.35), (9938, 1.35), (10245, 1.35), (10561, 1.35), (10887, 1.35), (11223, 1.35),
    (11570, 1.35), (11927, 1.35), (12295, 1.35), (12674, 1.35), (13066, 1.35), (13469, 1.35),
    (13885, 1.29), (14313, 1.22), (14755, 1.04), (15211, 0.98), (15680, 0.67), (16164, 0.55),
    (16663, 0.37), (17178, -0.43), (17708, -1.29), (18255, -8.94), (18818, -8.94), (19399, -8.94),
    (19998, -8.94), (20615, -8.94), (21252, -8.94), (21908, -8.94), (22584, -8.94), (23281, -8.94),
]


def _gain_entry():
    return ";".join(f"entry({f},{g})" for f, g in PUNTOS_ECUALIZADOR_STEREO_TOOL)


def filtro_af_ecualizador(con_limitador=True):
    """Devuelve el valor listo para asignar a ReproductorMPV.player.af

    Usa el filtro firequalizer de FFmpeg (disponible dentro de MPV mediante
    la sintaxis lavfi=[...]) para reproducir la curva de Stereo Tool punto
    por punto, sin aproximarla con pocas bandas.

    Esta curva tiene bandas con bastante ganancia (graves y agudos medios
    boosteados varios dB). En la transmisión real, Stereo Tool aplica esta
    curva y después una etapa limitadora propia que evita que eso sature.
    Como acá solo se replica el ecualizador (sin el compresor/AGC de
    Stereo Tool, que se descartó a propósito), hace falta agregar un
    limitador de picos (alimiter) a continuación: no cambia el carácter
    del sonido ni la curva configurada, solo evita que los picos se
    recorten digitalmente y distorsionen. Se puede desactivar con
    con_limitador=False si en algún momento se quiere comparar sin él.
    """
    filtro = "firequalizer=gain_entry='%s'" % _gain_entry()
    if con_limitador:
        filtro += ",alimiter=limit=0.95:level=disabled"
    return "lavfi=[%s]" % filtro
