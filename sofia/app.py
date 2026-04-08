# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from groq import Groq
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime
import calendar
import math
import os
import json
import re
import uuid

load_dotenv()

from datetime import timedelta
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "aldia-shadow-works-2026")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
CORS(app, supports_credentials=True)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

PORCENTAJES_BASE = {
    "vivienda": 25, "comida": 12, "transporte": 12, "salud": 8,
    "educacion": 2, "ocio": 7, "ropa": 8, "deudas": 8,
    "ahorro": 15, "imprevistos": 3
}

GASTO_PATTERN = re.compile(
    r'(?:me\s+)?(?:gast[eé]|compr[eé]|pagu[eé]|cost[oó]|gasto|'
    r'solt[eé]|baj[eé]|di|dej[eé]|me\s+cobr[oó]|me\s+cost[oó]|invert[ií])\s+'
    r'\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn|varos?|lana)?\s*(?:en\s+(.{1,80}))?',
    re.IGNORECASE
)

CADA_PATTERN = re.compile(
    r'(?:gast[eé]|pagu[eé])\s+\$?(\d[\d,\.]*)\s+en\s+(?:cada|todas)\s+(?:las\s+)?categor',
    re.IGNORECASE
)

INGRESO_PATTERN = re.compile(
    r'(?:recibi|recibí|me\s+cay[oó]|me\s+pagar[oó]n|me\s+deposit[oó]|'
    r'cobr[eé]|me\s+lleg[oó]|me\s+transfer[ei]ieron|me\s+entreg[oó]|'
    r'gano|gan[eé]|me\s+pagan?)\s+\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn|varos?)?',
    re.IGNORECASE
)

LIMITE_PATTERN = re.compile(
    r'(?:cambia|cambi[oó]|ajusta|pon|sube|baja|modifica|actualiza|quiero?)\s+'
    r'(?:mi\s+)?(?:l[ií]mite|presupuesto|tope|budget)\s+de\s+(\w+)\s+'
    r'(?:a|en|por)\s+\$?\s*(\d[\d,\.]*)',
    re.IGNORECASE
)

CAT_ALIASES = {
    'vivienda': 'vivienda', 'casa': 'vivienda', 'renta': 'vivienda', 'depa': 'vivienda',
    'comida': 'comida', 'food': 'comida', 'super': 'comida', 'restaurante': 'comida',
    'transporte': 'transporte', 'uber': 'transporte', 'gasolina': 'transporte',
    'salud': 'salud', 'medico': 'salud', 'gym': 'salud',
    'educacion': 'educacion', 'educación': 'educacion', 'cursos': 'educacion',
    'ocio': 'ocio', 'entretenimiento': 'ocio', 'netflix': 'ocio',
    'ropa': 'ropa', 'moda': 'ropa', 'clothes': 'ropa',
    'deudas': 'deudas', 'deuda': 'deudas', 'credito': 'deudas',
    'ahorro': 'ahorro', 'ahorros': 'ahorro', 'meta': 'ahorro',
}

# Suscripciones conocidas → categoria automatica
SUSCRIPCIONES = {
    'netflix': ('ocio', 299), 'spotify': ('ocio', 99), 'hbo': ('ocio', 149),
    'disney': ('ocio', 159), 'apple tv': ('ocio', 99), 'prime video': ('ocio', 99),
    'amazon prime': ('ocio', 99), 'crunchyroll': ('ocio', 119), 'paramount': ('ocio', 99),
    'youtube premium': ('ocio', 99), 'apple music': ('ocio', 79), 'deezer': ('ocio', 79),
    'xbox game pass': ('ocio', 299), 'playstation plus': ('ocio', 299),
    'chatgpt': ('ocio', 350), 'claude': ('ocio', 350), 'copilot': ('ocio', 350),
    'canva': ('ocio', 299), 'notion': ('ocio', 200), 'figma': ('ocio', 0),
    'dropbox': ('ocio', 150), 'google one': ('ocio', 59), 'icloud': ('ocio', 29),
    'rappi prime': ('ocio', 99), 'uber one': ('transporte', 99),
    'gym': ('salud', 500), 'gimnasio': ('salud', 500),
}

def detect_suscripcion(text):
    """Detecta si el mensaje menciona pagar una suscripcion conocida."""
    t = text.lower()
    for nombre, (cat, precio_default) in SUSCRIPCIONES.items():
        if nombre in t:
            # Buscar monto explicito, si no usar el default
            match = re.search(r'\$?\s*(\d[\d,\.]*)', t)
            monto = float(match.group(1).replace(',','')) if match else precio_default
            if monto > 0:
                return cat, monto, nombre
    return None

def classify_gasto(desc):
    if not desc:
        return "imprevistos"
    d = desc.lower()
    if any(w in d for w in [
        'renta','alquiler','hipoteca','luz','agua','gas','internet','telefono','celular',
        'vivienda','cuarto','depa','departamento','casa','cuota','mantenimiento','condominio'
    ]):
        return "vivienda"
    if any(w in d for w in [
        'super','supermercado','comida','taco','tacos','restaurante','comer','pizza',
        'hamburguesa','delivery','rappi','snack','mercado','antojitos','torta','birria',
        'pozole','tamales','elotes','quesadilla','gordita','sopa','desayuno','almuerzo',
        'cena','cafe','cafeteria','panaderia','fruteria','carneceria','pollo','sushi',
        'ubereats','didi food','ifood','jugo','agua de','refresco'
    ]):
        return "comida"
    if any(w in d for w in [
        'uber','taxi','camion','metro','gasolina','transporte','bus','didi','autobus',
        'tren','peaje','estacionamiento','caseta','moto','scooter','bici','ecobici',
        'cabify','indriver','beat','litro','magna','premium','diesel'
    ]):
        return "transporte"
    if any(w in d for w in [
        'doctor','medico','medicina','farmacia','hospital','consulta','gym','gimnasio',
        'dentista','salud','pastilla','vitamina','suplemento','psico','terapia',
        'optometrista','lentes','sangre','analisis','laboratorio','fisio'
    ]):
        return "salud"
    if any(w in d for w in [
        'curso','libro','certificacion','escuela','universidad','educacion','formacion',
        'clase','taller','diplomado','udemy','platzi','coursera','maestria','colegiatura',
        'inscripcion','material','cuaderno','lapiz','mochila'
    ]):
        return "educacion"
    if any(w in d for w in [
        'netflix','spotify','cine','juego','hbo','disney','prime','concierto','evento',
        'hobby','streaming','claude','chatgpt','app','software','suscripcion','antro',
        'bar','chela','cerveza','caguama','mezcal','tequila','botana','fiesta','show',
        'teatro','museo','parque','videojuego','steam','youtube premium','twitch',
        'apple music','deezer','crunchyroll'
    ]):
        return "ocio"
    if any(w in d for w in [
        'ropa','zapatos','camisa','pantalon','vestido','tenis','calzado','accesorio',
        'bolsa','cartera','cinturon','sombrero','gorra','calcetines','ropa interior',
        'zara','shein','h&m','nike','adidas','liverpool','palacio'
    ]):
        return "ropa"
    if any(w in d for w in [
        'deuda','credito','prestamo','tarjeta','abono','pago minimo','mensualidad',
        'kueski','meses sin intereses','credito infonavit','fonacot'
    ]):
        return "deudas"
    if any(w in d for w in [
        'ahorro','inversion','fondo','deposito','cetes','gbm','bitso','crypto',
        'bitcoin','acciones','bolsa','retiro','afore'
    ]):
        return "ahorro"
    return "imprevistos"

def get_session_id():
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    return session["session_id"]

def load_perfil(session_id):
    try:
        res = sb.table("usuarios").select("*").eq("session_id", session_id).execute()
        if res.data:
            return res.data[0]
    except:
        pass
    return {
        "session_id": session_id, "ingreso": 0, "meta": 0,
        "plazo_meses": 12, "estrictez": "equilibrado", "meta_tipo": "ahorrar",
        "tiene_vivienda": True, "tiene_transporte": True,
        "tiene_deudas": True, "tiene_educacion": True, "onboarding_done": False
    }

def save_perfil(perfil):
    try:
        existing = sb.table("usuarios").select("id").eq("session_id", perfil["session_id"]).execute()
        if existing.data:
            sb.table("usuarios").update(perfil).eq("session_id", perfil["session_id"]).execute()
        else:
            sb.table("usuarios").insert(perfil).execute()
    except Exception as e:
        print(f"Error saving perfil: {e}")

def load_gastos(session_id):
    gastos = {cat: 0 for cat in PORCENTAJES_BASE.keys()}
    try:
        res = sb.table("gastos").select("categoria, monto").eq("session_id", session_id).execute()
        for row in (res.data or []):
            cat = row["categoria"]
            if cat in gastos:
                gastos[cat] += row["monto"]
    except Exception as e:
        print(f"Error loading gastos: {e}")
    return gastos

def save_gasto(session_id, categoria, monto, descripcion=""):
    try:
        sb.table("gastos").insert({
            "session_id": session_id,
            "categoria": categoria,
            "monto": monto,
            "descripcion": descripcion
        }).execute()
    except Exception as e:
        print(f"Error saving gasto: {e}")

def load_mensajes(session_id):
    try:
        res = sb.table("mensajes").select("rol, contenido").eq("session_id", session_id).order("created_at", desc=True).limit(20).execute()
        return [{"role": m["rol"], "content": m["contenido"]} for m in reversed(res.data or [])]
    except:
        return []

def save_mensaje(session_id, rol, contenido):
    try:
        sb.table("mensajes").insert({
            "session_id": session_id,
            "rol": rol,
            "contenido": contenido
        }).execute()
    except Exception as e:
        print(f"Error saving mensaje: {e}")

def calcular_porcentajes_activos(perfil):
    base = dict(PORCENTAJES_BASE)
    liberado = 0
    if not perfil.get("tiene_vivienda", True):
        liberado += base.pop("vivienda", 0)
    if not perfil.get("tiene_transporte", True):
        liberado += base.pop("transporte", 0)
    if not perfil.get("tiene_deudas", True):
        liberado += base.pop("deudas", 0)
    if not perfil.get("tiene_educacion", True):
        liberado += base.pop("educacion", 0)
    if liberado > 0:
        base["ahorro"] = base.get("ahorro", 15) + liberado
    # Aplicar límites personalizados del usuario
    limites_custom = perfil.get("limites_custom") or {}
    if isinstance(limites_custom, dict):
        for cat, pct in limites_custom.items():
            if cat in base:
                base[cat] = pct
    return base

def evaluar_perfil_inversor(perfil, gastos):
    """Detecta si el usuario tiene perfil de inversor y actualiza el campo."""
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return False
    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado
    pct_disponible = disponible / ingreso
    # Criterios: ingreso > 10k, disponible > 40%, onboarding hecho
    es_inversor = (
        ingreso >= 10000 and
        pct_disponible >= 0.40 and
        perfil.get("onboarding_done", False)
    )
    return es_inversor

def generar_recomendaciones(perfil, gastos):
    """Genera recomendaciones de productos financieros reales según el perfil."""
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return ""
    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado
    pct_disp = disponible / ingreso
    deudas = gastos.get("deudas", 0)
    ahorro = gastos.get("ahorro", 0)
    es_inversor = perfil.get("perfil_inversor", False)
    recomendaciones = []

    # Banco Azteca siempre primero (track del hackathon)
    if pct_disp >= 0.30:
        recomendaciones.append(
            "💙 BANCO AZTECA — Guardadito Digital: sin comisiones, retiro en cualquier Elektra. "
            "Ideal para empezar tu fondo de emergencia con lo que te sobra este mes."
        )
    if pct_disp >= 0.30:
        recomendaciones.append(
            "🟣 Nu Cuenta: rendimiento 15% anual sin monto mínimo. "
            f"Si depositas ${round(disponible*0.5):,}/mes, en un año tienes ~${round(disponible*0.5*12*1.15):,}."
        )
        recomendaciones.append(
            "🟡 CETES Directo (gobierno federal): 11% anual garantizado. "
            "Desde $100 pesos, sin riesgo. Lo ideal para tu meta de ahorro."
        )
        recomendaciones.append(
            "🟢 Mercado Pago Cuenta: 15% anual, dinero disponible al instante. "
            "Perfecto si ya usas Mercado Libre."
        )
    if deudas > ingreso * 0.15:
        recomendaciones.append(
            "⚠️ Tus deudas están por encima del 15% de tu ingreso. "
            "Considera consolidarlas en un crédito personal a menor tasa — pregúntame cómo."
        )
    if ahorro < ingreso * 0.10:
        recomendaciones.append(
            "🤖 Tip de automatización: programa una transferencia automática el día de quincena. "
            "Aunque sea $500, el hábito vale más que el monto."
        )
    if es_inversor:
        recomendaciones.append(
            "📈 Con tu perfil podrías explorar: GBM+ (fondos indexados desde $100), "
            "CETES a 28 días para liquidez, o FIBRAS para exposición a bienes raíces sin comprar un depa."
        )
    return "\n".join(recomendaciones) if recomendaciones else ""

def get_system_prompt(perfil, gastos):
    now = datetime.now()
    fecha = now.strftime("%B %Y")
    dia = now.day
    dias_mes = calendar.monthrange(now.year, now.month)[1]
    dias_restantes = dias_mes - dia
    nombre = perfil.get("nombre", "")
    nombre_str = f" ({nombre})" if nombre else ""
    ingreso = perfil.get("ingreso", 0)
    ingreso_extra = perfil.get("ingreso_extra_mes", 0)
    ingreso_total = ingreso + ingreso_extra
    meta = perfil.get("meta", 0)
    plazo = perfil.get("plazo_meses", 12)
    gastos_fijos_mensuales = perfil.get("gastos_fijos_mensuales", perfil.get("gastos_fijos_inicio", 0))
    total_gastado = sum(gastos.values()) + gastos_fijos_mensuales
    disponible = max(0, ingreso_total - total_gastado)

    # Velocidad de gasto y proyeccion mensual
    tasa_diaria = total_gastado / dia if dia > 0 else 0
    proyeccion_fin_mes = round(tasa_diaria * dias_mes)
    superavit_proyectado = ingreso_total - proyeccion_fin_mes
    en_buen_ritmo = proyeccion_fin_mes <= ingreso_total

    # Cat mas usada
    porcentajes_activos = calcular_porcentajes_activos(perfil)
    limites = {cat: round(ingreso * pct / 100) for cat, pct in porcentajes_activos.items()} if ingreso > 0 else {}
    alertas = []
    cat_top = None
    top_uso = 0
    for cat, limite in limites.items():
        gastado = gastos.get(cat, 0)
        if limite > 0:
            uso = gastado / limite * 100
            if uso > top_uso:
                top_uso = uso
                cat_top = cat
            if gastado >= limite * 0.85:
                alertas.append(f"{cat}: {round(uso)}% usado")

    recomendaciones = generar_recomendaciones(perfil, gastos) if ingreso > 0 else ""
    es_inversor = evaluar_perfil_inversor(perfil, gastos)
    tono_inversor = "\n- Este usuario tiene PERFIL DE INVERSOR. Habla de instrumentos financieros más sofisticados: fondos indexados, CETES directo, GBM+, FIBRAS. Usa lenguaje más técnico pero accesible." if es_inversor else ""

    meta_tipo = perfil.get("meta_tipo", "")
    _meta_labels = {
        'ahorro':     'ahorrar para un objetivo específico',
        'deudas':     'salir de deudas',
        'emergencia': 'construir fondo de emergencia',
        'invertir':   'empezar a invertir',
        'control':    'solo controlar y entender sus gastos (sin meta de ahorro específica)',
    }
    meta_tipo_str = _meta_labels.get(meta_tipo, 'no definido')
    meta_tipo_rule = ""
    if meta_tipo == 'control':
        meta_tipo_rule = "\n- OBJETIVO DEL USUARIO: solo quiere controlar gastos, NO tiene meta de ahorro. NO hables de metas de ahorro, inversiones ni plazos a menos que él lo pregunte. Enfócate en ayudarle a entender su gasto."
    elif meta_tipo == 'deudas':
        meta_tipo_rule = "\n- OBJETIVO DEL USUARIO: salir de deudas. Prioriza siempre el pago de deudas sobre el ahorro. Sugiere estrategia bola de nieve o avalancha cuando sea relevante."
    elif meta_tipo == 'emergencia':
        meta_tipo_rule = "\n- OBJETIVO DEL USUARIO: construir fondo de emergencia (3-6 meses de gastos). Recuérdalo cuando haya margen de ahorro."
    elif meta_tipo == 'invertir':
        meta_tipo_rule = "\n- OBJETIVO DEL USUARIO: empezar a invertir. Menciona instrumentos de bajo riesgo (CETES, fondos indexados) cuando haya superávit."

    ingreso_extra_str = f"\n- Ingresos extra este mes (ventas/negocio): ${ingreso_extra:,.0f} pesos" if ingreso_extra > 0 else ""
    contexto = f"""PERFIL DEL USUARIO{nombre_str}:
- Ingreso mensual base: ${ingreso:,.0f} pesos{ingreso_extra_str}
- Ingreso total disponible este mes: ${ingreso_total:,.0f} pesos
- Meta: ${meta:,.0f} pesos en {plazo} meses
- Objetivo financiero: {meta_tipo_str}
{f"- Gastos fijos recurrentes mensuales (renta, servicios, etc.): ${gastos_fijos_mensuales:,.0f} pesos — se descuentan AUTOMÁTICAMENTE cada mes del disponible, NO los menciones como gasto nuevo ni generes ninguna alerta por ellos" if gastos_fijos_mensuales > 0 else ""}- Total gastado este mes (incluyendo fijos): ${total_gastado:,.0f} pesos
- Disponible real: ${disponible:,.0f} pesos
- Dia {dia} de {dias_mes} ({dias_restantes} dias restantes)
- Tasa de gasto diaria: ${tasa_diaria:,.0f}/dia
- Proyeccion a fin de mes: ${proyeccion_fin_mes:,.0f} ({'+' if superavit_proyectado >= 0 else ''}{superavit_proyectado:,.0f} vs ingreso)
- Ritmo: {'✅ bien encaminado' if en_buen_ritmo else '⚠️ gastando mas de lo que entra'}
- Categoria mas presionada: {cat_top} ({round(top_uso)}% de su limite)
- Limites por categoria: {json.dumps(limites, ensure_ascii=False)}
- ALERTAS: {alertas if alertas else 'ninguna'}
- Perfil inversor: {'SÍ' if es_inversor else 'no'}""" if ingreso > 0 else "El usuario aun no ha dado su perfil."


    pending = perfil.get("pending_gasto")
    _pamount = str(int(pending["amount"])) if pending else ""
    pending_str = ("\n\nGASTO PENDIENTE DE CLASIFICAR: El usuario menciono un gasto de $" + _pamount + " pesos sin decir en que. Ya fue detectado pero NO guardado aun. Preguntale con curiosidad de amigo en que lo gasto, una sola pregunta corta y natural, sin listar categorias. Cuando responda el sistema lo clasificara solo.") if pending else ""
    recomendaciones_str = f"\n\nRECOMENDACIONES FINANCIERAS ACTIVAS (menciona 1-2 cuando sea relevante, siempre con Banco Azteca primero):\n{recomendaciones}" if recomendaciones else ""

    nombre_directive = f"- El usuario se llama {nombre}. Llamalo por su nombre de vez en cuando (no en cada mensaje, solo cuando sea natural).\n" if nombre else ""
    meta_tipo_rule_str = meta_tipo_rule if meta_tipo_rule else ""
    return f"""Eres ALD.IA, asistente financiera personal para jovenes mexicanos. Hoy es {fecha}, dia {dia}.

{contexto}{recomendaciones_str}{pending_str}

CATEGORIAS: vivienda, comida, transporte, salud, educacion, ocio, ropa, deudas, ahorro, imprevistos.

EJEMPLOS DE RESPUESTAS CORRECTAS:
Usuario: "gaste 500 en uber" -> "Transporte registrado ✅ Te quedan ${disponible-500:,.0f} disponibles."
Usuario: "como voy?" -> "Llevas ${total_gastado:,.0f} gastados. A este ritmo terminas el mes en ${proyeccion_fin_mes:,.0f} — {'bien 👍' if en_buen_ritmo else 'cuidado ⚠️'}."
Usuario: "que puedo recortar?" -> Analiza las categorias con mayor uso vs limite y sugiere 1-2 concretas.
Usuario: "si compro X de $Y me afecta?" -> Calcula disponible - Y y di si es viable o no.

FORMATO OBLIGATORIO:
- Maximo 2-3 oraciones cortas con emojis
- NUNCA expliques calculos ni escribas operaciones como $X - $Y = $Z
- NUNCA listes todas las categorias a menos que el usuario las pida explicitamente
- Solo da el resultado final y una recomendacion concreta

REGLAS:
{nombre_directive}- Espanol casual mexicano, nunca condescendiente (usa "oye", "va", "chido", "sale")
- USA SIEMPRE los numeros del PERFIL, nunca inventes cifras
- Si hay ALERTAS activas, mencionalas con urgencia amigable
- Si el ritmo de gasto proyecta sobrepasar el ingreso, advertir con tono de aliado
- Si la meta es imposible con el ritmo actual, decirlo con alternativa concreta
- Cuando registres un gasto, siempre confirma categoria + disponible restante{tono_inversor}{meta_tipo_rule_str}

ANALISIS DE CREDITO (REGLA CRITICA):
Si el usuario menciona una tarjeta de credito, prestamo, credito, meses sin intereses, MSI, CAT, BNPL, deuda nueva, o cualquier producto financiero:
1. Calcula el pago mensual y el costo total con interes. Referencias CAT Mexico: tarjeta deptl 80-120%, tarjeta banco 36-70%, credito personal 24-50%, automotriz 12-18%, hipoteca 10-14%. Si el usuario da la tasa, usala.
   Formula: pago_mensual = monto * (r*(1+r)^n) / ((1+r)^n-1)  donde r=CAT/12/100, n=plazo_meses.
   Costo total = pago_mensual * n. Intereses = costo_total - monto.
2. Impacto real: disponible_actual - pago_mensual = nuevo_disponible.
3. Riesgo a la meta: si nuevo_disponible deja sin margen para el ahorro necesario, advertirlo.
4. Da veredicto claro: SI conviene o NO, con los 3 numeros clave (pago/mes, total pagado, nuevo disponible).
5. EXCEPCION de formato: para analisis de credito puedes usar hasta 6 lineas. Tono de amigo con inteligencia financiera, nunca de banco.
Ejemplo: "Esa tarjeta con CAT 70% a 24 meses: pagas $X/mes, terminas pagando $Y total ($Z puros intereses). Con tu disponible de $D te quedarian $Q — justo al filo de tu meta. Yo esperaria a que la necesites de verdad 👀"

INSTRUCCION CRITICA: Al final de CADA respuesta agrega exactamente esto (con los numeros reales):
BUDGET_DATA:{"vivienda_pct":0,"comida_pct":0,"transporte_pct":0,"salud_pct":0,"educacion_pct":0,"ocio_pct":0,"ropa_pct":0,"deudas_pct":0,"ahorro_pct":0,"meta_pct":0,"disponible":{disponible},"ingreso":{ingreso}}

Rellena los _pct con (gasto_categoria / ingreso * 100). disponible e ingreso son fijos del perfil."""

def extract_ingreso(line):
    match = re.search(r'\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?', line, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(',', ''))
    return None

_ONE_TIME_INCOME_WORDS = [
    'vendí','vendi','vendiendo','en vender','de vender','por vender',
    'del negocio','de mi negocio','de negocio','de ventas','por ventas',
    'de un proyecto','de trabajo extra','de freelance','de un cliente',
    'de la venta','sudader','playera','ropa','producto','servicio',
    'en el negocio','invertí','invert',
]
_RECURRING_INCOME_WORDS = [
    'sueldo','salario','quincena','mensualidad','nómina','nomina',
    'mi ingreso mensual','ingreso fijo','al mes','por mes','mensual',
    'me pagaron mi','cobré mi sueldo','cobré mi quincena',
]

def _classify_income(msg):
    """Return 'recurring', 'extra', or 'extra' (default to safe)."""
    if any(w in msg for w in _ONE_TIME_INCOME_WORDS):
        return 'extra'
    if any(w in msg for w in _RECURRING_INCOME_WORDS):
        return 'recurring'
    return 'extra'  # ambiguous → treat as extra to avoid overwriting monthly income

def update_perfil_from_message(user_message, perfil):
    msg = user_message.lower()

    # Detectar ingreso desde frase directa o INGRESO_PATTERN
    ingreso_match = INGRESO_PATTERN.search(msg)
    if ingreso_match:
        n = float(ingreso_match.group(1).replace(',', ''))
        if n > 0:
            if _classify_income(msg) == 'recurring':
                perfil["ingreso"] = n
            else:
                # Ingreso extra (venta, negocio, etc.) — acumular sin pisar el salario mensual
                perfil["ingreso_extra_mes"] = perfil.get("ingreso_extra_mes", 0) + n
    else:
        for line in msg.split('\n'):
            if any(w in line for w in ['gano','gana','ingreso','salario','sueldo','recibo','quincena','mensualidad']):
                n = extract_ingreso(line)
                if n and n > 0:
                    perfil["ingreso"] = n
                    break
    if any(w in msg for w in ['meta','ahorrar','quiero tener','objetivo','guardar']):
        matches = re.findall(r'\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?', msg)
        for m in matches:
            n = float(m.replace(',', ''))
            if n > 0:
                perfil["meta"] = n
                break
    return perfil

def calculate_budget_data(perfil, gastos):
    ingreso = perfil.get("ingreso", 0)
    ingreso_extra = perfil.get("ingreso_extra_mes", 0)
    ingreso_total = ingreso + ingreso_extra
    meta = perfil.get("meta", 0)
    if ingreso == 0:
        return None
    gastos_fijos = perfil.get("gastos_fijos_mensuales", perfil.get("gastos_fijos_inicio", 0))
    total_gastado = sum(gastos.values()) + gastos_fijos
    disponible = max(0, ingreso_total - total_gastado)

    def pct(cat):
        return round((gastos.get(cat, 0) / ingreso_total) * 100, 1) if ingreso_total > 0 else 0

    ahorro_real = gastos.get("ahorro", 0)
    ahorro_pct = round((ahorro_real / ingreso_total) * 100, 1) if ingreso_total > 0 else 0
    meta_pct = round((ahorro_real / meta) * 100, 1) if meta > 0 else 0

    return {
        "vivienda_pct": pct("vivienda"), "comida_pct": pct("comida"),
        "transporte_pct": pct("transporte"), "salud_pct": pct("salud"),
        "educacion_pct": pct("educacion"), "ocio_pct": pct("ocio"),
        "ropa_pct": pct("ropa"), "deudas_pct": pct("deudas"),
        "imprevistos_pct": pct("imprevistos"),
        "ahorro_pct": ahorro_pct, "meta_pct": min(meta_pct, 100),
        "disponible": round(disponible),
        "ingreso": ingreso_total,
        "ingreso_base": ingreso, "ingreso_extra": round(ingreso_extra),
        "gastos_fijos": round(gastos_fijos)
    }

def check_alerts(perfil, gastos):
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return False
    porcentajes_activos = calcular_porcentajes_activos(perfil)
    for cat, pct in porcentajes_activos.items():
        limite = ingreso * pct / 100
        if limite > 0 and gastos.get(cat, 0) >= limite * 0.85:
            return True
    return False

@app.route("/")
def index():
    if "email" not in session:
        session.clear()
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    session_id = get_session_id()

    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    messages = load_mensajes(session_id)

    perfil = update_perfil_from_message(user_message, perfil)

    # Detectar cambio de límite de categoría
    limite_match = LIMITE_PATTERN.search(user_message)
    if limite_match and perfil.get("ingreso", 0) > 0:
        cat_raw = limite_match.group(1).lower()
        cat = CAT_ALIASES.get(cat_raw, cat_raw)
        nuevo_monto = float(limite_match.group(2).replace(',', ''))
        nuevo_pct = round((nuevo_monto / perfil["ingreso"]) * 100, 1)
        limites_custom = perfil.get("limites_custom") or {}
        limites_custom[cat] = nuevo_pct
        perfil["limites_custom"] = limites_custom

    # Detect "gaste X en cada categoria"
    cada_match = CADA_PATTERN.search(user_message)
    new_gastos = []
    if cada_match:
        amount = float(cada_match.group(1).replace(',', ''))
        cats_activas = [c for c in ['vivienda','comida','transporte','salud','educacion','ocio','ropa','deudas']
                        if perfil.get('tiene_' + c, True) is not False]
        for cat in cats_activas:
            gastos[cat] = gastos.get(cat, 0) + amount
            new_gastos.append((cat, amount, "cada categoria"))
    else:
        # Detectar suscripciones conocidas primero
        sus = detect_suscripcion(user_message)
        if sus:
            cat, amount, nombre = sus
            gastos[cat] = gastos.get(cat, 0) + amount
            new_gastos.append((cat, amount, nombre))
        else:
            # Resolve pending gasto from previous message
            if perfil.get("pending_gasto"):
                pamt = perfil["pending_gasto"]["amount"]
                cat = classify_gasto(user_message)
                if cat != "imprevistos":
                    gastos[cat] = gastos.get(cat, 0) + pamt
                    new_gastos.append((cat, pamt, user_message.strip()))
                    perfil.pop("pending_gasto", None)
                # if still unrecognized keep pending — AI will ask again
            for match in GASTO_PATTERN.finditer(user_message):
                amount_str = match.group(1).replace(",", "")
                try:
                    amount = float(amount_str)
                except:
                    continue
                desc = match.group(2) or ""
                if not desc.strip():
                    # No context given — ask the user instead of guessing imprevistos
                    perfil["pending_gasto"] = {"amount": amount}
                else:
                    cat = classify_gasto(desc)
                    gastos[cat] = gastos.get(cat, 0) + amount
                    new_gastos.append((cat, amount, desc))

    # Evaluar y persistir perfil inversor si cambió
    es_inversor_ahora = evaluar_perfil_inversor(perfil, gastos)
    if perfil.get("perfil_inversor") != es_inversor_ahora:
        perfil["perfil_inversor"] = es_inversor_ahora
    save_perfil(perfil)
    for cat, amount, desc in new_gastos:
        save_gasto(session_id, cat, amount, desc)

    messages.append({"role": "user", "content": user_message})
    save_mensaje(session_id, "user", user_message)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": get_system_prompt(perfil, gastos)}] + messages[-14:],
        temperature=0.7,
        max_tokens=400
    )

    full_response = response.choices[0].message.content
    clean_response = full_response
    budget_match = re.search(r'BUDGET_DATA:(\{.*?\})', full_response)
    if budget_match:
        clean_response = full_response.replace(budget_match.group(0), "").strip()

    save_mensaje(session_id, "assistant", clean_response)

    return jsonify({
        "response": clean_response,
        "budget": calculate_budget_data(perfil, gastos),
        "alert": check_alerts(perfil, gastos)
    })

@app.route("/api/setup", methods=["POST"])
def setup():
    data = request.json
    session_id = get_session_id()
    perfil = load_perfil(session_id)

    if data.get("ingreso"):
        perfil["ingreso"] = float(data["ingreso"])
    if data.get("meta"):
        perfil["meta"] = float(data["meta"])
    if data.get("meta_tipo"):
        perfil["meta_tipo"] = data["meta_tipo"]
    if data.get("plazo_meses"):
        perfil["plazo_meses"] = int(data["plazo_meses"])
    if data.get("estrictez"):
        perfil["estrictez"] = data["estrictez"]

    if data.get("nombre"):
        perfil["nombre"] = data["nombre"].strip()
    perfil["tiene_vivienda"]   = data.get("vivienda", True) is not False
    perfil["tiene_transporte"] = data.get("transporte", True) is not False
    perfil["tiene_deudas"]     = data.get("deudas", True) is not False
    perfil["tiene_educacion"]  = data.get("educacion", True) is not False
    perfil["onboarding_done"]  = True
    perfil["session_id"]       = session_id

    # gastos_iniciales = gastos ya pagados este mes → registrar como gasto real
    gastos_iniciales = float(data.get("gastos_iniciales") or 0)
    if gastos_iniciales > 0:
        save_gasto(session_id, "imprevistos", gastos_iniciales, "gastos previos al registro")

    save_perfil(perfil)

    return jsonify({"status": "ok"})

@app.route("/api/generar-plan", methods=["POST"])
def generar_plan():
    data = request.json
    ingreso = float(data.get("ingreso", 0))
    meta = float(data.get("meta", 0))
    plazo = int(data.get("plazo_meses", 12))
    estrictez = data.get("estrictez", "equilibrado")

    # Calcular ahorro real basado en categorias activas
    # Gastos verdaderamente fijos (compromisos ineludibles)
    gastos_fijos_pct = 0
    if data.get("vivienda", True) is not False:
        gastos_fijos_pct += 25
    if data.get("transporte", True) is not False:
        gastos_fijos_pct += 12
    if data.get("deudas", True) is not False:
        gastos_fijos_pct += 8
    if data.get("educacion", True) is not False:
        gastos_fijos_pct += 2
    # Gastos variables (comida, salud, ocio, ropa) — reducibles si el usuario se lo propone
    gastos_variables_pct = 12 + 8 + 7 + 8  # 35%

    # pct_base normal (incluye variables): para modo relajado/equilibrado
    pct_base = max(0, 100 - gastos_fijos_pct - gastos_variables_pct)
    # pct_base agresivo (solo fijos): para quien dice que puede ahorrar casi todo
    pct_base_sin_variables = max(0, 100 - gastos_fijos_pct)

    pct_ahorro_map = {"relajado": pct_base * 0.5, "equilibrado": pct_base * 0.75, "agresivo": pct_base}
    pct_ahorro = pct_ahorro_map.get(estrictez, pct_base * 0.75) / 100
    pct_ahorro = max(pct_ahorro, 0.05)

    ahorro_disponible = data.get("ahorro_disponible", "mitad")
    if ahorro_disponible == "todo":
        # Usa pct_base_sin_variables menos un 5% de colchon realista
        pct_ahorro = max(pct_ahorro, (pct_base_sin_variables - 5) / 100)
    elif ahorro_disponible == "mitad":
        # Punto medio entre pct_base y pct_base_sin_variables
        pct_mitad = (pct_base + pct_base_sin_variables) / 2
        pct_ahorro = max(pct_ahorro, pct_mitad / 100)
    elif ahorro_disponible == "poco":
        pct_ahorro = min(pct_ahorro, 0.15)
    ahorro_mensual = round(ingreso * pct_ahorro)
    ahorro_necesario = round(meta / plazo) if plazo > 0 else 0
    es_viable = ahorro_necesario <= ahorro_mensual

    ahorro_posible_en_plazo = ahorro_mensual * plazo
    brecha = max(0, meta - ahorro_posible_en_plazo)
    ingreso_extra_mes = round(brecha / plazo) if plazo > 0 else 0
    meses_con_ingreso_actual = round(meta / ahorro_mensual) if ahorro_mensual > 0 else 0

    meta_tipo = data.get("meta_tipo", "ahorro")

    # Si meta es 0, estimar según capacidad de ahorro
    if meta == 0:
        if meta_tipo == "ahorro":
            meta = ahorro_mensual * plazo
            ahorro_necesario = round(meta / plazo) if plazo > 0 else 0
            es_viable = True
        elif meta_tipo == "emergencia":
            meta = ingreso * 3  # fondo sugerido: 3 meses de ingreso
            ahorro_necesario = round(meta / plazo) if plazo > 0 else 0
            es_viable = ahorro_necesario <= ahorro_mensual
        elif meta_tipo == "deudas":
            meta = ahorro_mensual * plazo  # no hay deuda conocida, usar capacidad
            ahorro_necesario = round(meta / plazo) if plazo > 0 else 0
            es_viable = True
        elif meta_tipo == "invertir":
            meta = round(ahorro_mensual * 0.5)  # invertir mitad de lo disponible
            ahorro_necesario = meta
            es_viable = meta <= ahorro_mensual

    # Para invertir, meta = monto mensual a invertir (no total)
    if meta_tipo == "invertir":
        es_viable = meta <= ahorro_mensual
        meses_con_ingreso_actual = plazo  # ya tiene el plazo definido
        brecha = max(0, meta - ahorro_mensual)
        ingreso_extra_mes = round(brecha / plazo) if plazo > 0 and brecha > 0 else 0

    if meta_tipo == "control":
        prompt = f"""Eres ALD.IA, asistente financiero para jovenes mexicanos. Este usuario SOLO quiere controlar y entender sus gastos, no tiene una meta de ahorro específica.

DATOS DEL USUARIO:
- Ingreso: ${ingreso:,.0f}/mes
- Si ahorra algo de lo que le sobra: ${ahorro_mensual:,.0f}/mes es posible (pero no es su prioridad)

INSTRUCCIONES:
- NO hables de metas de ahorro ni plazos
- Explica en 2-3 lineas qué puede hacer ALD.IA por él: registrar gastos por chat, ver a dónde va su dinero, recibir alertas antes de pasarse del presupuesto
- Tono amigable, casual mexicano, máximo 4 lineas, emojis"""
    else:
        meses_pago_deuda = round(meta / ahorro_mensual) if meta_tipo == "deudas" and ahorro_mensual > 0 else 0
        meses_fondo = round(meta / ahorro_mensual) if meta_tipo == "emergencia" and ahorro_mensual > 0 else 0
        _goal_context = {
            'deudas':     f"Debe ${meta:,.0f} en total. Con ${ahorro_mensual:,.0f}/mes disponibles quedaría libre en ~{meses_pago_deuda} meses. Objetivo del usuario: liquidar en {plazo} meses.",
            'emergencia': f"Quiere fondo de ${meta:,.0f}. Con ${ahorro_mensual:,.0f}/mes lo alcanza en ~{meses_fondo} meses. Objetivo: lograrlo en {plazo} meses.",
            'invertir':   f"Quiere invertir ${meta:,.0f}/mes. {'VIABLE: puede hacerlo' if es_viable else f'Le faltan ${brecha:,.0f}/mes para lograrlo'}. Plazo: {plazo} meses.",
            'ahorro':     f"Meta: ${meta:,.0f} en {plazo} meses. Necesita ${ahorro_necesario:,.0f}/mes.",
        }.get(meta_tipo, f"Meta: ${meta:,.0f} en {plazo} meses.")

        prompt = f"""Eres ALD.IA, asistente financiero empatico para jovenes mexicanos. Se directo y usa los numeros exactos.

OBJETIVO DEL USUARIO: {meta_tipo} — {_goal_context}

NUMEROS REALES (usa exactamente estos):
- Ingreso actual: ${ingreso:,.0f}/mes
- Puede destinar al objetivo: ${ahorro_mensual:,.0f}/mes ({int(pct_ahorro*100)}% de su ingreso)
- Total posible en {plazo} meses: ${ahorro_posible_en_plazo:,.0f}
- Viable: {"SI" if es_viable else "NO — le faltan $" + f"{brecha:,.0f}"}

INSTRUCCIONES:
- Adapta el mensaje al objetivo ({meta_tipo}), no lo trates como ahorro genérico
- Si NO es viable: di cuanto lograria, cuanto falta, y cuanto extra necesita o cuánto más tiempo
- Si SI es viable: confirma con entusiasmo y da fecha aproximada
- 1 consejo concreto relacionado con el objetivo
- Maximo 5 lineas, emojis, espanol casual"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=300
    )
    return jsonify({"plan": response.choices[0].message.content.strip()})

@app.route("/api/budget", methods=["GET"])
def budget():
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    return jsonify({"budget": calculate_budget_data(perfil, gastos)})

@app.route("/api/resumen", methods=["GET"])
def resumen():
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)

    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return jsonify({"resumen": None})

    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado
    dia = datetime.now().day

    porcentajes_activos = calcular_porcentajes_activos(perfil)
    cat_critica = None
    pct_critico = 0
    for cat, pct in porcentajes_activos.items():
        limite = ingreso * pct / 100
        gastado = gastos.get(cat, 0)
        if limite > 0:
            uso = gastado / limite * 100
            if uso > pct_critico:
                pct_critico = uso
                cat_critica = cat

    prompt = f"""Eres ALD.IA, asistente financiera empatica para jovenes mexicanos.

El usuario acaba de abrir la app. Genera un resumen proactivo del mes en maximo 2 oraciones:

Datos:
- Dia del mes: {dia}
- Ingreso mensual: ${ingreso:,.0f}
- Total gastado: ${total_gastado:,.0f}
- Disponible: ${disponible:,.0f}
- Categoria mas usada: {cat_critica} ({round(pct_critico)}% de su limite)

El mensaje debe saludar brevemente y dar 1-2 datos clave. Termina con pregunta corta.
Espanol casual, emojis, maximo 2 oraciones."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=150
    )
    return jsonify({"resumen": response.choices[0].message.content.strip()})

@app.route("/api/register", methods=["POST"])
def register():
    import bcrypt
    data = request.json
    email = data.get("email", "").lower().strip()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email y contrasena requeridos"}), 400
    if len(password) < 6:
        return jsonify({"error": "La contrasena debe tener al menos 6 caracteres"}), 400
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return jsonify({"error": "Email invalido"}), 400
    try:
        existing = sb.table("usuarios").select("id").eq("email", email).execute()
        if existing.data:
            return jsonify({"error": "Este email ya tiene una cuenta"}), 409
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        session_id = get_session_id()
        perfil = load_perfil(session_id)
        perfil["email"] = email
        perfil["password_hash"] = password_hash
        perfil["session_id"] = session_id
        save_perfil(perfil)
        session.permanent = True
        session["email"] = email
        return jsonify({"status": "ok", "email": email})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/login", methods=["POST"])
def login():
    import bcrypt
    data = request.json
    email = data.get("email", "").lower().strip()
    password = data.get("password", "")
    try:
        res = sb.table("usuarios").select("*").eq("email", email).execute()
        if not res.data:
            return jsonify({"error": "Email o contrasena incorrectos"}), 401
        usuario = res.data[0]
        if not bcrypt.checkpw(password.encode(), usuario["password_hash"].encode()):
            return jsonify({"error": "Email o contrasena incorrectos"}), 401
        session.permanent = True
        session["session_id"] = usuario["session_id"]
        session["email"] = email
        return jsonify({
            "status": "ok", "email": email,
            "onboarding_done": usuario.get("onboarding_done", False),
            "ingreso": usuario.get("ingreso", 0),
            "meta": usuario.get("meta", 0),
            "plazo_meses": usuario.get("plazo_meses", 12),
            "tiene_vivienda": usuario.get("tiene_vivienda", True),
            "tiene_transporte": usuario.get("tiene_transporte", True),
            "tiene_deudas": usuario.get("tiene_deudas", True),
            "tiene_educacion": usuario.get("tiene_educacion", True),
            "nombre": usuario.get("nombre", "")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/check-session", methods=["GET"])
def check_session():
    if "email" not in session:
        return jsonify({"logged_in": False})
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    return jsonify({
        "logged_in": True,
        "email": session.get("email", ""),
        "onboarding_done": perfil.get("onboarding_done", False),
        "ingreso": perfil.get("ingreso", 0),
        "meta": perfil.get("meta", 0),
        "plazo_meses": perfil.get("plazo_meses", 12),
        "tiene_vivienda": perfil.get("tiene_vivienda", True),
        "tiene_transporte": perfil.get("tiene_transporte", True),
        "tiene_deudas": perfil.get("tiene_deudas", True),
        "tiene_educacion": perfil.get("tiene_educacion", True),
        "nombre": perfil.get("nombre", ""),
    })

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})


@app.route("/api/reset-data", methods=["POST"])
def reset_data():
    session_id = get_session_id()
    try:
        sb.table("mensajes").delete().eq("session_id", session_id).execute()
        sb.table("gastos").delete().eq("session_id", session_id).execute()
        # Reset monthly extra income accumulator
        perfil = load_perfil(session_id)
        perfil["ingreso_extra_mes"] = 0
        save_perfil(perfil)
    except Exception as e:
        print(f"Error resetting data: {e}")
    return jsonify({"status": "ok"})

@app.route("/api/reset", methods=["POST"])
def reset():
    session_id = get_session_id()
    try:
        sb.table("mensajes").delete().eq("session_id", session_id).execute()
        sb.table("gastos").delete().eq("session_id", session_id).execute()
        sb.table("usuarios").delete().eq("session_id", session_id).execute()
    except Exception as e:
        print(f"Error resetting: {e}")
    session.clear()
    return jsonify({"status": "ok"})

@app.route("/api/stats", methods=["GET"])
def stats():
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return jsonify({"error": "sin perfil"})

    now = datetime.now()
    dia = now.day
    dias_mes = calendar.monthrange(now.year, now.month)[1]
    dias_restantes = dias_mes - dia
    total_gastado = sum(gastos.values())
    tasa_diaria = total_gastado / dia if dia > 0 else 0
    proyeccion = round(tasa_diaria * dias_mes)

    porcentajes_activos = calcular_porcentajes_activos(perfil)
    limites = {cat: round(ingreso * pct / 100) for cat, pct in porcentajes_activos.items()}

    categorias = []
    for cat, limite in limites.items():
        gastado = gastos.get(cat, 0)
        uso_pct = round(gastado / limite * 100) if limite > 0 else 0
        categorias.append({
            "nombre": cat, "gastado": round(gastado),
            "limite": limite, "uso_pct": uso_pct,
            "estado": "rojo" if uso_pct >= 90 else "amarillo" if uso_pct >= 70 else "verde"
        })
    categorias.sort(key=lambda x: x["uso_pct"], reverse=True)

    return jsonify({
        "ingreso": ingreso,
        "total_gastado": round(total_gastado),
        "disponible": max(0, round(ingreso - total_gastado)),
        "proyeccion_fin_mes": proyeccion,
        "superavit_proyectado": round(ingreso - proyeccion),
        "tasa_diaria": round(tasa_diaria),
        "dia": dia, "dias_mes": dias_mes, "dias_restantes": dias_restantes,
        "en_buen_ritmo": proyeccion <= ingreso,
        "categorias": categorias,
        "meta": perfil.get("meta", 0),
        "plazo_meses": perfil.get("plazo_meses", 12),
    })

def calcular_health_score(perfil, gastos):
    """Calcula un score financiero de 0-100 basado en 4 dimensiones."""
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return None

    now = datetime.now()
    dia = now.day
    dias_mes = calendar.monthrange(now.year, now.month)[1]
    total_gastado = sum(gastos.values())
    tasa_diaria = total_gastado / dia if dia > 0 else 0
    proyeccion = tasa_diaria * dias_mes

    porcentajes_activos = calcular_porcentajes_activos(perfil)
    limites = {cat: ingreso * pct / 100 for cat, pct in porcentajes_activos.items()}

    # Dimensión 1: Tasa de ahorro (0-30 pts)
    ahorro_real = gastos.get("ahorro", 0)
    pct_ahorro = ahorro_real / ingreso if ingreso > 0 else 0
    pts_ahorro = min(30, round(pct_ahorro * 150))  # 20% ahorro = 30 pts

    # Dimensión 2: Categorías bajo control (0-30 pts)
    cats_ok = sum(1 for cat, lim in limites.items() if lim > 0 and gastos.get(cat, 0) <= lim)
    total_cats = sum(1 for lim in limites.values() if lim > 0)
    pts_control = round((cats_ok / total_cats) * 30) if total_cats > 0 else 15

    # Dimensión 3: Ritmo de gasto (0-25 pts)
    if proyeccion <= ingreso * 0.75:
        pts_ritmo = 25
    elif proyeccion <= ingreso:
        pts_ritmo = round(25 * (1 - (proyeccion - ingreso * 0.75) / (ingreso * 0.25)))
    else:
        exceso = (proyeccion - ingreso) / ingreso
        pts_ritmo = max(0, round(10 - exceso * 20))

    # Dimensión 4: Progreso hacia meta (0-15 pts)
    meta = perfil.get("meta", 0)
    plazo = perfil.get("plazo_meses", 12)
    if meta > 0 and plazo > 0:
        ahorro_mensual_necesario = meta / plazo
        ahorro_actual = gastos.get("ahorro", 0)
        pts_meta = min(15, round((ahorro_actual / ahorro_mensual_necesario) * 15)) if ahorro_mensual_necesario > 0 else 7
    else:
        pts_meta = 7  # neutral si no hay meta

    score = pts_ahorro + pts_control + pts_ritmo + pts_meta

    # Personalidad financiera
    pct_comida = gastos.get("comida", 0) / ingreso if ingreso > 0 else 0
    pct_ocio = gastos.get("ocio", 0) / ingreso if ingreso > 0 else 0
    pct_ropa = gastos.get("ropa", 0) / ingreso if ingreso > 0 else 0
    pct_transporte = gastos.get("transporte", 0) / ingreso if ingreso > 0 else 0

    if pct_ahorro >= 0.20:
        personalidad = ("🏦 Ahorrador", "Tienes mentalidad de largo plazo. ¡Sigue así!")
    elif pct_comida >= 0.20:
        personalidad = ("🍔 Foodie", "La buena comida es prioridad para ti. Cuida no pasarte.")
    elif pct_ropa >= 0.15:
        personalidad = ("👗 Fashionista", "Te gusta verte bien. Considera un presupuesto fijo de moda.")
    elif pct_ocio >= 0.15:
        personalidad = ("🎮 Entretenido", "Disfrutas el entretenimiento. ¿Estás usando todas tus suscripciones?")
    elif pct_transporte >= 0.20:
        personalidad = ("🚗 Movilero", "El transporte se lleva mucho. ¿Podrías optimizar rutas?")
    elif score >= 70:
        personalidad = ("⚖️ Equilibrado", "Buen balance entre disfrutar y ahorrar. Vas bien.")
    else:
        personalidad = ("📊 En construcción", "Aún construyendo tus hábitos. ¡Cada peso cuenta!")

    nivel = "Excelente 🌟" if score >= 85 else "Muy bien 💪" if score >= 70 else "Regular ⚠️" if score >= 50 else "Atención 🔴"

    return {
        "score": score,
        "nivel": nivel,
        "personalidad": personalidad[0],
        "personalidad_desc": personalidad[1],
        "breakdown": {
            "ahorro": pts_ahorro, "control": pts_control,
            "ritmo": pts_ritmo, "meta": pts_meta
        }
    }


@app.route("/api/health-score", methods=["GET"])
def health_score():
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    result = calcular_health_score(perfil, gastos)
    if not result:
        return jsonify({"error": "sin perfil"})
    return jsonify(result)


@app.route("/api/puede-pagar", methods=["POST"])
def puede_pagar():
    """Evalúa si un gasto es viable considerando tipo de pago, plazos e intereses."""
    data = request.json
    monto = float(data.get("monto", 0))
    tipo = data.get("tipo", "unico")          # unico | msi | credito
    meses = int(data.get("meses", 1))
    tasa_anual = float(data.get("tasa_anual", 0))
    gastos_extra = float(data.get("gastos_extra", 0))
    nombre = data.get("nombre", "")

    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0 or monto <= 0:
        return jsonify({"error": "datos insuficientes"})

    monto_total = monto + gastos_extra

    # Cálculo de pago mensual y costo total según tipo
    if tipo == "unico":
        pago_mensual = monto_total
        costo_total = monto_total
        costo_intereses = 0
    elif tipo == "msi":
        meses = max(meses, 1)
        pago_mensual = monto_total / meses
        costo_total = monto_total
        costo_intereses = 0
    else:  # credito con interés
        if tasa_anual <= 0:
            tasa_anual = 50.0  # CAT promedio tarjeta bancaria México
        r = tasa_anual / 12 / 100
        meses = max(meses, 1)
        if r > 0:
            pago_mensual = monto_total * (r * (1 + r) ** meses) / ((1 + r) ** meses - 1)
        else:
            pago_mensual = monto_total / meses
        costo_total = pago_mensual * meses
        costo_intereses = costo_total - monto_total

    # Estado actual del presupuesto
    gastos_fijos = perfil.get("gastos_fijos_mensuales", perfil.get("gastos_fijos_inicio", 0))
    total_gastado = sum(gastos.values()) + gastos_fijos
    disponible = max(0, ingreso - total_gastado)
    meta = perfil.get("meta", 0)
    plazo = perfil.get("plazo_meses", 12)
    ahorro_mensual_necesario = meta / plazo if meta > 0 and plazo > 0 else 0
    ahorro_actual = gastos.get("ahorro", 0)
    colchon_meta = max(0, ahorro_mensual_necesario - ahorro_actual)
    disponible_real = disponible - colchon_meta

    # ¿Puede pagarlo?
    impacto_mensual = pago_mensual if tipo != "unico" else monto_total
    # puede_cash: si hay dinero real disponible para el gasto
    # puede_meta: si además no sacrifica el colchón de meta
    puede_cash = impacto_mensual <= disponible
    puede_meta = impacto_mensual <= disponible_real
    # "puede" = sí hay efectivo (aunque afecte meta)
    puede = puede_cash
    afecta_meta = puede_cash and not puede_meta
    impacto_pct = round(impacto_mensual / ingreso * 100, 1)
    deficit_meta = round(max(0, impacto_mensual - disponible_real))
    max_sin_meta = round(max(0, disponible_real))

    horas_trabajadas = round(costo_total / (ingreso / 160), 1) if ingreso > 0 else 0
    dias_trabajados = round(horas_trabajadas / 8, 1)

    # ¿Qué categorías se sacrifican? — slacks por categoría
    porcentajes_activos = calcular_porcentajes_activos(perfil)
    slacks = []
    for cat, pct_cat in porcentajes_activos.items():
        limite_cat = ingreso * pct_cat / 100
        gastado_cat = gastos.get(cat, 0)
        slack_cat = max(0, limite_cat - gastado_cat)
        if limite_cat > 0:
            slacks.append({
                "cat": cat,
                "slack": round(slack_cat),
                "limite": round(limite_cat),
                "gastado": round(gastado_cat),
                "uso_pct": round(gastado_cat / limite_cat * 100) if limite_cat > 0 else 0
            })
    slacks.sort(key=lambda x: x["slack"], reverse=True)

    # ¿Cuándo sí puedo comprarlo?
    meses_para_poder = 0
    fecha_puede_str = ""
    ahorro_mes_requerido = 0
    if not puede_cash:
        faltante = impacto_mensual - disponible
        ahorro_mensual_posible = ingreso * 0.15
        if ahorro_mensual_posible > 0 and faltante > 0:
            meses_para_poder = math.ceil(faltante / ahorro_mensual_posible)
            ahorro_mes_requerido = round(faltante / max(meses_para_poder, 1))
            fecha_target = datetime.now() + timedelta(days=30 * meses_para_poder)
            meses_es = ["","ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
            fecha_puede_str = f"{meses_es[fecha_target.month]} {fecha_target.year}"

    return jsonify({
        "puede": puede,
        "afecta_meta": afecta_meta,
        "nombre": nombre,
        "monto": round(monto),
        "monto_total": round(monto_total),
        "tipo": tipo,
        "meses": meses if tipo != "unico" else 1,
        "tasa_anual": tasa_anual if tipo == "credito" else 0,
        "pago_mensual": round(pago_mensual),
        "costo_total": round(costo_total),
        "costo_intereses": round(costo_intereses),
        "disponible": round(disponible),
        "disponible_real": round(disponible_real),
        "impacto_pct": impacto_pct,
        "colchon_meta": round(colchon_meta),
        "deficit_meta": deficit_meta,
        "max_sin_meta": max_sin_meta,
        "horas_trabajadas": horas_trabajadas,
        "dias_trabajados": dias_trabajados,
        "ingreso": ingreso,
        "slacks": slacks[:4],
        "meses_para_poder": meses_para_poder,
        "fecha_puede": fecha_puede_str,
        "ahorro_mes_requerido": ahorro_mes_requerido,
    })


@app.route("/api/recomienda-compra", methods=["POST"])
def recomienda_compra():
    """Genera recomendación IA personalizada sobre una decisión de compra."""
    data = request.json
    nombre = data.get("nombre", "esta compra")
    monto = data.get("monto_total", 0)
    puede = data.get("puede", False)
    afecta_meta = data.get("afecta_meta", False)
    tipo = data.get("tipo", "unico")
    meses = data.get("meses", 1)
    pago_mensual = data.get("pago_mensual", 0)
    costo_total = data.get("costo_total", 0)
    costo_intereses = data.get("costo_intereses", 0)
    ingreso = data.get("ingreso", 0)
    impacto_pct = data.get("impacto_pct", 0)
    meses_para_poder = data.get("meses_para_poder", 0)
    disponible = data.get("disponible", 0)
    if ingreso == 0:
        return jsonify({"recomendacion": ""})

    tipo_label = {"unico": "pago único", "msi": f"MSI a {meses} meses", "credito": f"crédito a {meses} meses con interés"}.get(tipo, tipo)
    prompt = f"""Eres ALD.IA, asistente financiera para jovenes mexicanos. Genera UNA recomendacion de exactamente 2 oraciones para esta decision de compra.

DATOS:
- Producto: {nombre or "compra"}
- Monto total: ${monto:,.0f}
- Tipo de pago: {tipo_label}
- Pago mensual: ${pago_mensual:,.0f}
- Costo total: ${costo_total:,.0f}{(' (incluye $' + f'{costo_intereses:,.0f}' + ' de intereses)') if costo_intereses > 0 else ''}
- Puede pagarlo: {'SI' if puede else 'NO — le faltan $' + f'{max(0, pago_mensual - disponible):,.0f}'}
- Afecta meta de ahorro: {'SI' if afecta_meta else 'NO'}
- Impacto en ingreso: {impacto_pct}%
- Meses para poder comprarlo: {meses_para_poder if meses_para_poder > 0 else 'ya puede'}

REGLAS:
1. Exactamente 2 oraciones, texto fluido sin bullets ni listas
2. Si hay mejor opcion de pago, sugierela con numeros concretos
3. Si no puede comprar, da consejo accionable especifico
4. Tono: amigo directo que sabe de finanzas, espanol casual mexicano
5. Sin emojis"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.65,
        max_tokens=130
    )
    return jsonify({"recomendacion": response.choices[0].message.content.strip()})


@app.route("/api/eliminar-ultimo", methods=["POST"])
def eliminar_ultimo():
    session_id = get_session_id()
    try:
        res = sb.table("gastos").select("id,categoria,monto,descripcion") \
               .eq("session_id", session_id) \
               .order("created_at", desc=True).limit(1).execute()
        if not res.data:
            return jsonify({"error": "No hay gastos para deshacer"})
        row = res.data[0]
        sb.table("gastos").delete().eq("id", row["id"]).execute()
        return jsonify({"status": "ok", "eliminado": row})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/exportar-reporte", methods=["GET"])
def exportar_reporte():
    import csv, io
    from flask import Response
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    try:
        res = sb.table("gastos").select("categoria, monto, descripcion, created_at") \
               .eq("session_id", session_id) \
               .order("created_at", desc=True).execute()
        if not res.data:
            return jsonify({"error": "No hay gastos para exportar"}), 404

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Fecha", "Categoría", "Monto", "Descripción"])

        for row in res.data:
            writer.writerow([row.get("created_at","")[:10], row["categoria"], row["monto"], row.get("descripcion","")])

        output.seek(0)
        return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=reporte_gastos.csv"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/actualizar-perfil", methods=["POST"])
def actualizar_perfil():
    data = request.json or {}
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    if data.get("ingreso") and float(data["ingreso"]) > 0:
        perfil["ingreso"] = float(data["ingreso"])
    if "tiene_vivienda" in data:
        perfil["tiene_vivienda"] = bool(data["tiene_vivienda"])
    if "tiene_transporte" in data:
        perfil["tiene_transporte"] = bool(data["tiene_transporte"])
    if "tiene_deudas" in data:
        perfil["tiene_deudas"] = bool(data["tiene_deudas"])
    if "tiene_educacion" in data:
        perfil["tiene_educacion"] = bool(data["tiene_educacion"])
    if data.get("meta") and float(data["meta"]) > 0:
        perfil["meta"] = float(data["meta"])
    if data.get("plazo_meses"):
        perfil["plazo_meses"] = int(data["plazo_meses"])
    if data.get("estrictez"):
        perfil["estrictez"] = data["estrictez"]
    save_perfil(perfil)
    return jsonify({
        "status": "ok",
        "tiene_vivienda": perfil.get("tiene_vivienda", True),
        "tiene_transporte": perfil.get("tiene_transporte", True),
        "tiene_deudas": perfil.get("tiene_deudas", True),
        "tiene_educacion": perfil.get("tiene_educacion", True),
        "ingreso": perfil.get("ingreso", 0)
    })


@app.route("/api/comparativa-mes", methods=["GET"])
def comparativa_mes():
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return jsonify({"error": "sin perfil"})
    now = datetime.now()
    mes_actual_inicio = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 1:
        mes_ant_year, mes_ant_month = now.year - 1, 12
    else:
        mes_ant_year, mes_ant_month = now.year, now.month - 1
    mes_ant_inicio = f"{mes_ant_year}-{mes_ant_month:02d}-01T00:00:00"
    mes_act_str = mes_actual_inicio.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        res_act = sb.table("gastos").select("categoria,monto").eq("session_id", session_id).gte("created_at", mes_act_str).execute()
        res_ant = sb.table("gastos").select("categoria,monto").eq("session_id", session_id).gte("created_at", mes_ant_inicio).lt("created_at", mes_act_str).execute()
        actual = {}
        for r in (res_act.data or []):
            actual[r["categoria"]] = actual.get(r["categoria"], 0) + r["monto"]
        anterior = {}
        for r in (res_ant.data or []):
            anterior[r["categoria"]] = anterior.get(r["categoria"], 0) + r["monto"]
        total_actual = sum(actual.values())
        total_anterior = sum(anterior.values())
        all_cats = set(list(actual.keys()) + list(anterior.keys()))
        comparativas = []
        for cat in all_cats:
            a = actual.get(cat, 0)
            p = anterior.get(cat, 0)
            comparativas.append({"categoria": cat, "actual": round(a), "anterior": round(p), "diff": round(a - p), "mejor": (a - p) <= 0})
        comparativas.sort(key=lambda x: abs(x["diff"]), reverse=True)
        meses_es = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
        return jsonify({
            "mes_actual": meses_es[now.month - 1],
            "mes_anterior": meses_es[mes_ant_month - 1],
            "total_actual": round(total_actual),
            "total_anterior": round(total_anterior),
            "diff_total": round(total_actual - total_anterior),
            "comparativas": comparativas[:10]
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/historial", methods=["GET"])
def historial():
    session_id = get_session_id()
    try:
        res = sb.table("gastos").select("categoria,monto,descripcion,created_at") \
               .eq("session_id", session_id) \
               .order("created_at", desc=True).limit(15).execute()
        rows = []
        for r in (res.data or []):
            rows.append({
                "fecha": r.get("created_at", "")[:10],
                "categoria": r.get("categoria", ""),
                "monto": r.get("monto", 0),
                "descripcion": r.get("descripcion", "") or r.get("desc", ""),
            })
        return jsonify({"transacciones": rows})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/alertas-detalle", methods=["GET"])
def alertas_detalle():
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return jsonify({"alertas": []})
    porcentajes_activos = calcular_porcentajes_activos(perfil)
    now = datetime.now()
    dia = now.day
    dias_mes = calendar.monthrange(now.year, now.month)[1]
    dias_restantes = dias_mes - dia
    consejos = {
        "comida": "Cocina en casa 2-3 días esta semana — ahorras ~${ahorro} pesos.",
        "ocio": "Revisa tus suscripciones activas. Cancelar una te da ${ahorro} extra.",
        "ropa": "Pausa compras de moda este mes y ahorra ${ahorro} para tu meta.",
        "transporte": "Comparte gasolin con alguien o usa transporte público 2 días: ~${ahorro} menos.",
        "deudas": "Paga más del mínimo para reducir intereses — cada peso extra cuenta.",
        "salud": "Checa si tu gym tiene plan económico o busca opciones gratuitas al aire libre.",
        "vivienda": "Tu vivienda está al tope. Considera si puedes negociar o buscar alternativas.",
        "educacion": "Evalúa si todos los cursos activos te están dando retorno real.",
    }
    alertas = []
    for cat, pct_asignado in porcentajes_activos.items():
        if cat in ("ahorro", "imprevistos"):
            continue
        limite = ingreso * pct_asignado / 100
        if limite <= 0:
            continue
        gastado = gastos.get(cat, 0)
        uso_pct = round(gastado / limite * 100)
        if uso_pct >= 70:
            sobrante = max(0, limite - gastado)
            exceso = max(0, gastado - limite)
            ahorro_posible = round(gastado - limite * 0.8)
            estado = "rojo" if uso_pct >= 90 else "amarillo"
            consejo = consejos.get(cat, "Intenta reducir ${ahorro} en esta categoría.").replace("${ahorro}", f"${ahorro_posible:,}")
            alertas.append({
                "categoria": cat, "estado": estado, "uso_pct": uso_pct,
                "gastado": round(gastado), "limite": round(limite),
                "sobrante": round(sobrante), "exceso": round(exceso),
                "consejo": consejo, "dias_restantes": dias_restantes,
            })
    alertas.sort(key=lambda x: x["uso_pct"], reverse=True)
    return jsonify({"alertas": alertas, "dia": dia, "dias_mes": dias_mes})


@app.route("/api/grafica-mes", methods=["GET"])
def grafica_mes():
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return jsonify({"error": "sin perfil"})
    porcentajes_activos = calcular_porcentajes_activos(perfil)
    cats = [c for c in porcentajes_activos if c not in ("imprevistos",) and porcentajes_activos[c] > 0]
    bar_h, gap, label_w, bar_max_w = 22, 8, 90, 200
    total_h = (bar_h + gap) * len(cats) + 10
    svg_w = label_w + bar_max_w + 60
    rows = []
    for i, cat in enumerate(cats):
        limite = ingreso * porcentajes_activos[cat] / 100
        gastado = gastos.get(cat, 0)
        pct = min(gastado / limite, 1.0) if limite > 0 else 0
        bar_w = round(pct * bar_max_w)
        y = i * (bar_h + gap) + 5
        color = "#ef4444" if pct >= 0.90 else "#f59e0b" if pct >= 0.70 else "#10b981"
        rows.append(
            f'<text x="{label_w-6}" y="{y+bar_h-6}" fill="#9ca3af" font-size="11" text-anchor="end">{cat}</text>'
            f'<rect x="{label_w}" y="{y}" width="{bar_max_w}" height="{bar_h}" rx="4" fill="#1f2937"/>'
            f'<rect x="{label_w}" y="{y}" width="{max(bar_w,2)}" height="{bar_h}" rx="4" fill="{color}"/>'
            f'<text x="{label_w+bar_max_w+6}" y="{y+bar_h-6}" fill="{color}" font-size="11">{round(pct*100)}%</text>'
        )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{total_h}" style="background:#111827;border-radius:8px;padding:4px">{"".join(rows)}</svg>'
    return jsonify({"svg": svg})


@app.route("/api/importar-estado", methods=["POST"])
def importar_estado():
    import csv, io
    session_id = get_session_id()
    if "archivo" not in request.files:
        return jsonify({"error": "No se recibió archivo"}), 400
    archivo = request.files["archivo"]
    nombre = archivo.filename.lower()
    transacciones = []
    try:
        if nombre.endswith(".csv"):
            content = archivo.read().decode("utf-8-sig", errors="replace")
            reader = csv.reader(io.StringIO(content))
            for row in list(reader)[1:]:
                if not row:
                    continue
                monto, desc = None, ""
                for cell in row:
                    cell_clean = cell.strip().replace(",", "").replace("$", "")
                    try:
                        val = float(cell_clean)
                        if val > 0 and monto is None:
                            monto = val
                    except:
                        if len(cell.strip()) > 2:
                            desc = cell.strip()
                if monto and monto > 0:
                    transacciones.append({"monto": monto, "desc": desc, "cat": classify_gasto(desc.lower())})
        else:
            return jsonify({"error": "Solo se aceptan archivos .csv"}), 400
    except Exception as e:
        return jsonify({"error": f"Error procesando archivo: {str(e)}"}), 500
    if not transacciones:
        return jsonify({"error": "No se encontraron transacciones"}), 400
    totales = {}
    for t in transacciones:
        save_gasto(session_id, t["cat"], t["monto"], t["desc"])
        totales[t["cat"]] = totales.get(t["cat"], 0) + t["monto"]
    return jsonify({"importadas": len(transacciones), "totales": totales, "mensaje": f"✅ {len(transacciones)} movimientos importados."})


@app.route("/api/conectar-banco", methods=["POST"])
def conectar_banco():
    data = request.json or {}
    banco = data.get("banco", "Banco Azteca")
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    perfil["banco_conectado"] = banco
    save_perfil(perfil)
    return jsonify({
        "status": "conectado",
        "banco": banco,
        "mensaje": f"✅ {banco} conectado exitosamente.",
        "cuentas": [
            {"tipo": "Débito", "numero": "****3421", "saldo": 8240},
            {"tipo": "Crédito", "numero": "****7890", "limite": 20000, "usado": 4500},
        ]
    })


@app.route("/api/dashboard-insight", methods=["GET"])
def dashboard_insight():
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return jsonify({"bullets": []})

    now = datetime.now()
    dia = now.day
    dias_mes = calendar.monthrange(now.year, now.month)[1]
    total_gastado = sum(gastos.values())
    tasa_diaria = total_gastado / dia if dia > 0 else 0
    proyeccion = round(tasa_diaria * dias_mes)
    disponible = max(0, ingreso - total_gastado)
    meta = perfil.get("meta", 0)
    plazo = perfil.get("plazo_meses", 12)
    ahorro_real = gastos.get("ahorro", 0)
    ahorro_necesario = round(meta / plazo) if meta > 0 and plazo > 0 else 0

    porcentajes_activos = calcular_porcentajes_activos(perfil)
    cats_excedidas = []
    cats_bien = []
    for cat, pct in porcentajes_activos.items():
        limite = ingreso * pct / 100
        gastado = gastos.get(cat, 0)
        if limite > 0 and gastado > limite:
            cats_excedidas.append(f"{cat} (${gastado:,.0f} vs limite ${limite:,.0f})")
        elif limite > 0 and gastado <= limite * 0.7 and gastado > 0:
            cats_bien.append(cat)

    nombre = perfil.get("nombre", "")
    meta_desc = perfil.get("meta_desc", "")

    prompt = f"""Eres ALD.IA, asistente financiera para jovenes mexicanos. Analiza estos datos y genera exactamente 3 bullets de retroalimentacion inteligente en espanol casual.

DATOS DEL MES:
- Dia: {dia}/{dias_mes}
- Ingreso: ${ingreso:,.0f}
- Gastado hasta hoy: ${total_gastado:,.0f}
- Disponible restante: ${disponible:,.0f}
- Proyeccion fin de mes: ${proyeccion:,.0f} {'(EXCEDE ingreso!)' if proyeccion > ingreso else ''}
- Ahorro registrado: ${ahorro_real:,.0f} {'/ meta mensual $' + f'{ahorro_necesario:,.0f}' if ahorro_necesario > 0 else ''}
- Categorias excedidas: {', '.join(cats_excedidas) if cats_excedidas else 'ninguna'}
- Categorias bajo control: {', '.join(cats_bien) if cats_bien else 'N/A'}
- Meta de ahorro: {meta_desc if meta_desc else ('$' + f'{meta:,.0f}' if meta > 0 else 'sin meta')}

REGLAS:
1. Exactamente 3 bullets, cada uno en 1 sola oracion corta (max 12 palabras).
2. Cada bullet empieza con un emoji relevante.
3. Sé especifico con numeros reales del usuario.
4. Tono: amigo que sabe de finanzas, directo y util.
5. Formato: una linea por bullet, sin numeracion, sin markdown extra.
6. Si hay algo critico (proyeccion excede ingreso, categoria excedida) mencionalo primero."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=200
    )
    text = response.choices[0].message.content.strip()
    bullets = [line.strip() for line in text.split('\n') if line.strip()][:4]
    return jsonify({"bullets": bullets})


@app.route("/ping")
def ping():
    return "ok", 200

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(debug=True)
