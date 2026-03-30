# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from groq import Groq
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime
import calendar
import os
import json
import re
import uuid

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "aldia-shadow-works-2026")
CORS(app)

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
        res = sb.table("mensajes").select("rol, contenido").eq("session_id", session_id).order("created_at").execute()
        return [{"role": m["rol"], "content": m["contenido"]} for m in (res.data or [])]
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
    limites_custom = perfil.get("limites_custom", {})
    for cat, pct in limites_custom.items():
        if cat in base:
            base[cat] = pct
    return base

def get_system_prompt(perfil, gastos):
    now = datetime.now()
    fecha = now.strftime("%B %Y")
    dia = now.day
    dias_mes = calendar.monthrange(now.year, now.month)[1]
    dias_restantes = dias_mes - dia
    ingreso = perfil.get("ingreso", 0)
    meta = perfil.get("meta", 0)
    plazo = perfil.get("plazo_meses", 12)
    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado

    # Velocidad de gasto y proyeccion mensual
    tasa_diaria = total_gastado / dia if dia > 0 else 0
    proyeccion_fin_mes = round(tasa_diaria * dias_mes)
    superavit_proyectado = ingreso - proyeccion_fin_mes
    en_buen_ritmo = proyeccion_fin_mes <= ingreso

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

    contexto = f"""PERFIL DEL USUARIO:
- Ingreso mensual: ${ingreso:,.0f} pesos
- Meta: ${meta:,.0f} pesos en {plazo} meses
- Total gastado este mes: ${total_gastado:,.0f} pesos
- Disponible real: ${disponible:,.0f} pesos
- Dia {dia} de {dias_mes} ({dias_restantes} dias restantes)
- Tasa de gasto diaria: ${tasa_diaria:,.0f}/dia
- Proyeccion a fin de mes: ${proyeccion_fin_mes:,.0f} ({'+' if superavit_proyectado >= 0 else ''}{superavit_proyectado:,.0f} vs ingreso)
- Ritmo: {'✅ bien encaminado' if en_buen_ritmo else '⚠️ gastando mas de lo que entra'}
- Categoria mas presionada: {cat_top} ({round(top_uso)}% de su limite)
- Limites por categoria: {json.dumps(limites, ensure_ascii=False)}
- ALERTAS: {alertas if alertas else 'ninguna'}""" if ingreso > 0 else "El usuario aun no ha dado su perfil."

    return f"""Eres ALD.IA, asistente financiera personal para jovenes mexicanos. Hoy es {fecha}, dia {dia}.

{contexto}

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
- Espanol casual mexicano, nunca condescendiente (usa "oye", "va", "chido", "sale")
- USA SIEMPRE los numeros del PERFIL, nunca inventes cifras
- Si hay ALERTAS activas, mencionalas con urgencia amigable
- Si el ritmo de gasto proyecta sobrepasar el ingreso, advertir con tono de aliado
- Si la meta es imposible con el ritmo actual, decirlo con alternativa concreta
- Cuando registres un gasto, siempre confirma categoria + disponible restante

INSTRUCCION CRITICA: Al final de CADA respuesta agrega exactamente esto (con los numeros reales):
BUDGET_DATA:{{"vivienda_pct":0,"comida_pct":0,"transporte_pct":0,"salud_pct":0,"educacion_pct":0,"ocio_pct":0,"ropa_pct":0,"deudas_pct":0,"ahorro_pct":0,"meta_pct":0,"disponible":{disponible},"ingreso":{ingreso}}}

Rellena los _pct con (gasto_categoria / ingreso * 100). disponible e ingreso son fijos del perfil."""

def extract_ingreso(line):
    match = re.search(r'\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?', line, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(',', ''))
    return None

def update_perfil_from_message(user_message, perfil):
    msg = user_message.lower()

    # Detectar ingreso desde frase directa o INGRESO_PATTERN
    ingreso_match = INGRESO_PATTERN.search(msg)
    if ingreso_match:
        n = float(ingreso_match.group(1).replace(',', ''))
        if n > 0:
            perfil["ingreso"] = n
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
    meta = perfil.get("meta", 0)
    if ingreso == 0:
        return None
    total_gastado = sum(gastos.values())
    disponible = max(0, ingreso - total_gastado)

    def pct(cat):
        return round((gastos.get(cat, 0) / ingreso) * 100, 1)

    ahorro_real = gastos.get("ahorro", 0)
    ahorro_pct = round((ahorro_real / ingreso) * 100, 1)
    meta_pct = round((ahorro_real / meta) * 100, 1) if meta > 0 else 0

    return {
        "vivienda_pct": pct("vivienda"), "comida_pct": pct("comida"),
        "transporte_pct": pct("transporte"), "salud_pct": pct("salud"),
        "educacion_pct": pct("educacion"), "ocio_pct": pct("ocio"),
        "ropa_pct": pct("ropa"), "deudas_pct": pct("deudas"),
        "ahorro_pct": ahorro_pct, "meta_pct": min(meta_pct, 100),
        "disponible": round(disponible),
        "ingreso": ingreso if ingreso > 0 else perfil.get("ingreso", 0)
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
        limites_custom = perfil.get("limites_custom", {})
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
            for match in GASTO_PATTERN.finditer(user_message):
                amount_str = match.group(1).replace(',', '')
                try:
                    amount = float(amount_str)
                except:
                    continue
                desc = match.group(2) or ""
                cat = classify_gasto(desc)
                gastos[cat] = gastos.get(cat, 0) + amount
                new_gastos.append((cat, amount, desc))

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

    perfil["tiene_vivienda"]   = data.get("vivienda", True) is not False
    perfil["tiene_transporte"] = data.get("transporte", True) is not False
    perfil["tiene_deudas"]     = data.get("deudas", True) is not False
    perfil["tiene_educacion"]  = data.get("educacion", True) is not False
    perfil["onboarding_done"]  = True
    perfil["session_id"]       = session_id

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

    prompt = f"""Eres ALD.IA, asistente financiero empatico para jovenes mexicanos. Se directo y usa los numeros exactos, sin rodeos.

NUMEROS REALES DEL USUARIO (usa exactamente estos, no los cambies):
- Ingreso actual: ${ingreso:,.0f}/mes
- Meta: ${meta:,.0f} en {plazo} meses
- Puede ahorrar: ${ahorro_mensual:,.0f}/mes ({int(pct_ahorro*100)}% de su ingreso)
- Total que ahorraria en {plazo} meses: ${ahorro_posible_en_plazo:,.0f}
- Le faltarian: ${brecha:,.0f}
- Ingreso EXTRA necesario cada mes para cerrar la brecha: ${ingreso_extra_mes:,.0f}/mes
- Con ingreso actual solo (sin extra): llegaría en {meses_con_ingreso_actual} meses
- Meta viable con ingreso actual: {"SI" if es_viable else "NO"}

INSTRUCCIONES ESTRICTAS:
- Usa SIEMPRE los numeros de arriba, jamas inventes otros
- Si NO es viable: di cuanto ahorraria en el plazo (${ahorro_posible_en_plazo:,.0f}), cuanto le falta (${brecha:,.0f}), y que necesita ${ingreso_extra_mes:,.0f}/mes extra (freelance, trabajo extra, etc.) para llegar exacto a la meta en el plazo
- Si SI es viable: confirma el plan con entusiasmo
- Da 1 consejo concreto de como conseguir ese ingreso extra si aplica
- Maximo 5 lineas, emojis, espanol casual y directo"""

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
            "tiene_educacion": usuario.get("tiene_educacion", True)
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
        ahorro_actual = ahorro_real
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
    """¿Puedo permitirme este gasto sin afectar mi meta?"""
    data = request.json
    monto = float(data.get("monto", 0))
    session_id = get_session_id()
    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0 or monto <= 0:
        return jsonify({"error": "datos insuficientes"})

    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado
    meta = perfil.get("meta", 0)
    plazo = perfil.get("plazo_meses", 12)
    ahorro_mensual_necesario = meta / plazo if meta > 0 and plazo > 0 else 0
    ahorro_actual = gastos.get("ahorro", 0)
    colchon_meta = max(0, ahorro_mensual_necesario - ahorro_actual)
    disponible_real = disponible - colchon_meta

    puede = monto <= disponible_real
    impacto_pct = round(monto / ingreso * 100, 1)

    return jsonify({
        "puede": puede,
        "monto": monto,
        "disponible": round(disponible),
        "disponible_real": round(disponible_real),
        "impacto_pct": impacto_pct,
        "colchon_meta": round(colchon_meta),
        "mensaje": (
            f"✅ Sí puedes. Te quedarán ${disponible_real - monto:,.0f} libres." if puede
            else f"⚠️ Cuidado. Solo tienes ${disponible_real:,.0f} disponibles sin tocar tu meta."
        )
    })


@app.route("/ping")
def ping():
    return "ok", 200

if __name__ == "__main__":
    app.run(debug=True)

