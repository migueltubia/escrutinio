"""Guarda en la base de trabajo lo que devuelven los conectores territoriales.

Las votaciones de todas las instituciones van a las mismas tablas que las del Congreso (votacion,
voto_grupo, voto, iniciativa, grupo), con el id de legislatura global (num del cuerpo * 100 +
número). Así el procesado común, las afinidades, las fichas IA y la web valen para todas.
"""

import hashlib
import json
import re
from collections import Counter

from ..texto import normalizar
from .modelo import TIPOS_INICIATIVA, Iniciativa, Votacion
from .partidos import codigo_grupo


def _sentido_grupo(si, no, abst):
    votos = sorted({"si": si, "no": no, "abstencion": abst}.items(), key=lambda kv: kv[1], reverse=True)
    if votos[0][1] == 0:
        return None
    return "dividido" if votos[0][1] == votos[1][1] else votos[0][0]


def _texto(t):
    return re.sub(r"[ \t\xa0]+", " ", (t or "").strip())


def expediente_de(v):
    exp = _texto(v.expediente).replace(":", "-")
    if exp:
        return exp, False
    base = normalizar(v.titulo)[:300] or f"{v.fecha} {v.sesion} {v.numero}"
    return "SIN/" + hashlib.sha1(base.encode()).hexdigest()[:10], True


class Cargador:
    # titulo_norm (el título normalizado) solo lo necesitaba el cruce por título del Congreso: aquí se deja vacío.

    def __init__(self, con, cuerpos, modulo=""):
        self.con = con
        self.cuerpos = cuerpos          # codigo -> territorio.Cuerpo
        self.modulo = modulo            # nombre del conector (queda en iniciativa.fuente)
        self.dip = {(r[2], r[1]): r[0] for r in con.execute("SELECT id, nombre, cuerpo FROM diputado WHERE cuerpo<>'congreso'")}
        self.n = Counter()
        self.sesiones = {}              # (legislatura, fecha, sesion) -> ids guardados en esta pasada

    def leg(self, cuerpo, numero, fecha):
        c = self.cuerpos[cuerpo]
        numero = numero or c.legislatura_de(fecha)
        if numero not in c.legislaturas:
            raise ValueError(f"{cuerpo}: legislatura {numero!r} ({fecha}) no declarada")
        return c.id_leg(numero)

    def diputado_id(self, cuerpo, nombre):
        clave = (cuerpo, nombre)
        if clave not in self.dip:
            cur = self.con.execute("INSERT INTO diputado(nombre, cuerpo) VALUES (?,?)", (nombre, cuerpo))
            self.dip[clave] = cur.lastrowid
        return self.dip[clave]

    def grupo(self, leg, nombre):
        codigo, siglas, color = codigo_grupo(nombre)
        self.con.execute(
            """INSERT INTO grupo(legislatura, codigo, nombre, siglas, color) VALUES (?,?,?,?,?)
               ON CONFLICT(legislatura, codigo) DO UPDATE SET
                 nombre=CASE WHEN length(excluded.nombre) > length(grupo.nombre) THEN excluded.nombre ELSE grupo.nombre END""",
            (leg, codigo, _texto(nombre) or codigo, siglas, color),
        )
        return codigo

    def guardar(self, obj):
        if isinstance(obj, Iniciativa):
            return self.iniciativa(obj)
        if isinstance(obj, Votacion):
            return self.votacion(obj)
        raise TypeError(type(obj).__name__)

    def iniciativa(self, i):
        leg = self.leg(i.cuerpo, i.legislatura, i.fecha_presentacion or "9999-12-31")
        tipo = i.tipo_iniciativa if i.tipo_iniciativa in TIPOS_INICIATIVA else None
        extra = {"url": i.url, **(i.extra or {})}
        self.con.execute(
            """INSERT INTO iniciativa(legislatura, expediente, prefijo, tipo, titulo, titulo_norm, autor,
                 fecha_presentacion, resultado_tramitacion, sintetica, fuente, extra_json)
               VALUES (?,?,?,?,?,?,?,?,?,0,'catalogo',?)
               ON CONFLICT(legislatura, expediente) DO UPDATE SET
                 prefijo=COALESCE(excluded.prefijo, iniciativa.prefijo), tipo=COALESCE(excluded.tipo, iniciativa.tipo),
                 titulo=excluded.titulo, titulo_norm=excluded.titulo_norm, autor=COALESCE(excluded.autor, iniciativa.autor),
                 fecha_presentacion=COALESCE(excluded.fecha_presentacion, iniciativa.fecha_presentacion),
                 resultado_tramitacion=COALESCE(excluded.resultado_tramitacion, iniciativa.resultado_tramitacion),
                 sintetica=0, fuente='catalogo', extra_json=excluded.extra_json""",
            (leg, _texto(i.expediente).replace(":", "-"), tipo, TIPOS_INICIATIVA[tipo][0] if tipo else None,
             _texto(i.titulo), None, _texto(i.autor) or None, i.fecha_presentacion,
             _texto(i.resultado) or None, json.dumps(extra, ensure_ascii=False)),
        )
        self.n["iniciativas"] += 1

    def votacion(self, v):
        leg = self.leg(v.cuerpo, v.legislatura, v.fecha)
        titulo = _texto(v.titulo)
        exp, sintetica = expediente_de(v)
        tipo = v.tipo_iniciativa if v.tipo_iniciativa in TIPOS_INICIATIVA else None
        # La iniciativa: la del catálogo manda; si no hay, la primera votación la describe.
        self.con.execute(
            """INSERT INTO iniciativa(legislatura, expediente, prefijo, tipo, titulo, titulo_norm, autor,
                 fecha_presentacion, sintetica, fuente)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(legislatura, expediente) DO UPDATE SET
                 prefijo=COALESCE(iniciativa.prefijo, excluded.prefijo), tipo=COALESCE(iniciativa.tipo, excluded.tipo),
                 autor=COALESCE(iniciativa.autor, excluded.autor),
                 fecha_presentacion=MIN(COALESCE(iniciativa.fecha_presentacion, excluded.fecha_presentacion),
                                        excluded.fecha_presentacion)""",
            (leg, exp, tipo, TIPOS_INICIATIVA[tipo][0] if tipo else None, titulo, None,
             _texto(v.autor) or None, v.fecha, int(sintetica), self.modulo or v.fuente),
        )
        # Totales: si faltan y hay voto nominal, se cuentan.
        tot = {"a_favor": v.a_favor, "en_contra": v.en_contra, "abstenciones": v.abstenciones, "no_votan": v.no_votan}
        if v.nominal and v.a_favor is None:
            c = Counter(n.sentido for n in v.nominal)
            tot = {"a_favor": c["si"], "en_contra": c["no"], "abstenciones": c["abstencion"], "no_votan": c["no_vota"]}
        cur = self.con.execute(
            """INSERT INTO votacion(camara, legislatura, sesion, numero, fecha, seccion, texto_expediente, titulo_subgrupo,
                 texto_subgrupo, votaciones_conjuntas, asentimiento, presentes, a_favor, en_contra, abstenciones, no_votan,
                 expediente, enlace_metodo, prefijo, tipo_votacion, tipo_votacion_fuente, mayoria, resultado_oficial,
                 fuente, url)
               VALUES (?,?,?,?,?,?,?,?,?,'[]',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(legislatura, fecha, sesion, numero) DO UPDATE SET
                 camara=excluded.camara, seccion=excluded.seccion, texto_expediente=excluded.texto_expediente,
                 titulo_subgrupo=excluded.titulo_subgrupo, texto_subgrupo=excluded.texto_subgrupo,
                 asentimiento=excluded.asentimiento, presentes=excluded.presentes, a_favor=excluded.a_favor,
                 en_contra=excluded.en_contra, abstenciones=excluded.abstenciones, no_votan=excluded.no_votan,
                 expediente=excluded.expediente, enlace_metodo=excluded.enlace_metodo, prefijo=excluded.prefijo,
                 tipo_votacion=excluded.tipo_votacion, tipo_votacion_fuente=excluded.tipo_votacion_fuente,
                 mayoria=excluded.mayoria, resultado_oficial=excluded.resultado_oficial, fuente=excluded.fuente,
                 url=excluded.url
               RETURNING id""",
            (v.cuerpo, leg, int(v.sesion or 0), int(v.numero or 0), v.fecha, TIPOS_INICIATIVA[tipo][0] if tipo else None,
             titulo, _texto(v.subtitulo) or None, _texto(v.extra.get("texto_subgrupo")) or None, int(bool(v.asentimiento)),
             v.presentes, tot["a_favor"], tot["en_contra"], tot["abstenciones"], tot["no_votan"], exp,
             "sintetica" if sintetica else "fuente", tipo, v.tipo_votacion, "fuente" if v.tipo_votacion else None,
             v.mayoria, v.resultado, v.fuente, v.url),
        )
        vid = cur.fetchone()[0]
        self.con.execute("DELETE FROM voto WHERE votacion_id=?", (vid,))
        self.con.execute("DELETE FROM voto_grupo WHERE votacion_id=?", (vid,))
        grupos = {}
        for g in v.grupos:
            codigo = self.grupo(leg, g.grupo)
            o = grupos.setdefault(codigo, {"si": 0, "no": 0, "abstencion": 0, "no_vota": 0, "sentidos": set(), "cuentas": False})
            for k in ("si", "no", "abstencion", "no_vota"):
                if getattr(g, k) is not None:
                    o[k] += getattr(g, k)
                    o["cuentas"] = True
            if g.sentido:
                o["sentidos"].add(g.sentido)
        if v.nominal:
            filas = []
            desde_nominal = not grupos
            for n in v.nominal:
                codigo = self.grupo(leg, n.grupo)
                filas.append((vid, self.diputado_id(v.cuerpo, _texto(n.nombre)), codigo, n.sentido, None))
                if desde_nominal:
                    o = grupos.setdefault(codigo, {"si": 0, "no": 0, "abstencion": 0, "no_vota": 0, "sentidos": set(), "cuentas": True})
                    o[n.sentido] += 1
            self.con.executemany("INSERT OR REPLACE INTO voto(votacion_id, diputado_id, grupo, sentido, asiento) VALUES (?,?,?,?,?)", filas)
            self.n["votos nominales"] += len(filas)
        filas = []
        for codigo, o in grupos.items():
            if o["cuentas"]:
                sentido = _sentido_grupo(o["si"], o["no"], o["abstencion"])
            else:
                sentido = next(iter(o["sentidos"])) if len(o["sentidos"]) == 1 else ("dividido" if o["sentidos"] else None)
            filas.append((vid, codigo, o["si"], o["no"], o["abstencion"], o["no_vota"], sentido))
        self.con.executemany(
            "INSERT INTO voto_grupo(votacion_id, grupo, si, no, abstencion, no_vota, sentido) VALUES (?,?,?,?,?,?,?)", filas)
        self.n["votaciones"] += 1
        self.sesiones.setdefault((leg, v.fecha, int(v.sesion or 0)), set()).add(vid)
        return vid

    def limpiar_sesiones(self):
        """Borra de cada sesión recién guardada las votaciones que ya no ha devuelto el conector.

        Si un conector cambia cómo numera las votaciones de una sesión (lee mejor un PDF, parte de otra
        forma los puntos…), al volver a guardarla quedarían las filas con la numeración vieja. Solo se usa
        cuando el conector ha terminado bien, y nunca toca lo leído de actas (numeración 500001…).
        """
        borradas = 0
        for (leg, fecha, sesion), ids in self.sesiones.items():
            viejas = [r[0] for r in self.con.execute(
                "SELECT id FROM votacion WHERE legislatura=? AND fecha=? AND sesion=? AND numero < 500000",
                (leg, fecha, sesion)) if r[0] not in ids]
            for vid in viejas:
                for tabla in ("voto", "voto_grupo", "grupo_decisivo"):
                    self.con.execute(f"DELETE FROM {tabla} WHERE votacion_id=?", (vid,))
                self.con.execute("DELETE FROM votacion WHERE id=?", (vid,))
            borradas += len(viejas)
        self.n["sustituidas"] += borradas
        return borradas


def ultimas_fechas(con):
    """Fecha de la última votación guardada de cada institución territorial."""
    return dict(con.execute(
        """SELECT l.cuerpo, MAX(v.fecha) FROM votacion v JOIN legislatura l ON l.id=v.legislatura
           WHERE l.cuerpo<>'congreso' GROUP BY l.cuerpo"""))


def borrar_cuerpo(con, cuerpo, log=print):
    """Borra lo guardado de una institución (para recargarla entera si su conector cambia de numeración).

    Las fichas de las iniciativas se conservan: van por expediente y se reutilizan al recargar.
    """
    legs = [r[0] for r in con.execute("SELECT id FROM legislatura WHERE cuerpo=?", (cuerpo,))]
    if not legs or cuerpo == "congreso":
        return 0
    marcas = ",".join("?" * len(legs))
    votos = f"SELECT id FROM votacion WHERE legislatura IN ({marcas})"
    for tabla in ("voto", "voto_grupo", "grupo_decisivo"):
        con.execute(f"DELETE FROM {tabla} WHERE votacion_id IN ({votos})", legs)
    n = con.execute(f"DELETE FROM votacion WHERE legislatura IN ({marcas})", legs).rowcount
    for tabla in ("iniciativa", "grupo", "afinidad"):
        con.execute(f"DELETE FROM {tabla} WHERE legislatura IN ({marcas})", legs)
    con.commit()
    log(f"  {cuerpo}: {n} votaciones borradas para recargarlas")
    return n
