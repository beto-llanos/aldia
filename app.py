from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from groq import Groq
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime
import os
import json
import re
import uuid

load_dotenv()

app = Flask(__name__)
app.secret_key = "aldia-shadow-works-2026"
CORS(app)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

PORCENTAJES_BASE = {
    "vivienda": 25, "comida": 12, "transporte": 12, "salud": 8,
    "educacion": 2, "ocio": 7, "ropa": 8, "deudas": 8,
    "ahorro": 15, "imprevistos": 3
}

GASTO_PATTERN = re.compile(
    r'(?:gasté|gaste|compré|compre|pagué|pague|costó|costo|gasto)\s+\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?\s*(?:en\s+(.{1,60}))?',
    re.IGNORECASE
)

def classify_gasto(desc):
    if not desc:
        return "imprevistos"
    d = desc.lower()
    if any(w in d for w in ['renta','alquiler','hipoteca','luz','agua','gas','internet','telefono','celular','vivienda']):
        return "vivienda"
    if any(w in d for w in ['super','supermercado','comida','taco','tacos','restaurante','comer','pizza','hamburguesa','delivery','rappi','uber eats','snack','mercado']):
        return "comida"
    if any(w in d for w in ['uber','taxi','camion','metro','gasolina','transporte','bus','didi','autobus','tren','peaje','estacionamiento']):
        return "transporte"
    if any(w in d for w in ['doctor','medico','medicina','farmacia','hospital','consulta','gym','gimnasio','dentista','salud']):
        return "salud"
    if any(w in d for w in ['curso','libro','certificacion','escuela','universidad','educacion','formacion','clase']):
        return "educacion"
    if any(w in d for w in ['netflix','spotify','cine','juego','hbo','disney','prime','concierto','evento','hobby','streaming','claude','chatgpt','app','software','suscripcion']):
        return "ocio"
    if any(w in d for w in ['ropa','zapatos','camisa','pantalon','vestido','tenis','calzado','accesorio']):
        return "ropa"
    if any(w in d for w in ['deuda','credito','prestamo','tarjeta','abono']):
        return "deudas"
    if any(w in d for w in ['ahorro','inversion','fondo','deposito']):
        return "ahorro"
    return "imprevistos"

# ─── Supabase helpers ────────────────────────────────────────────────────────

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

# ─── Core logic ──────────────────────────────────────────────────────────────

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
    return base

def get_system_prompt(perfil, gastos):
    now = datetime.now()
    fecha = now.strftime("%B %Y")
    dia = now.day
    ingreso = perfil.get("ingreso", 0)
    meta = perfil.get("meta", 0)
    plazo = perfil.get("plazo_meses", 12)
    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado

    porcentajes_activos = calcular_porcentajes_activos(perfil)
    limites = {cat: round(ingreso * pct / 100) for cat, pct in porcentajes_activos.items()} if ingreso > 0 else {}
    alertas = []
    for cat, limite in limites.items():
        gastado = gastos.get(cat, 0)
        if limite > 0 and gastado >= limite * 0.85:
            alertas.append(f"{cat}: {round(gastado/limite*100)}% usado")

    contexto = f"""PERFIL DEL USUARIO:
- Ingreso mensual: ${ingreso:,.0f} pesos
- Meta: ${meta:,.0f} pesos en {plazo} meses
- Gastos registrados: {json.dumps({k:v for k,v in gastos.items() if v > 0}, ensure_ascii=False)}
- Total gastado: ${total_gastado:,.0f} pesos
- Disponible real: ${disponible:,.0f} pesos
- Límites por categoría: {json.dumps(limites, ensure_ascii=False)}
- ALERTAS: {alertas if alertas else 'ninguna'}
- Día del mes: {dia}""" if ingreso > 0 else "El usuario aún no ha dado su perfil."

    return f"""Eres ALD.IA (Automatización de Liquidación Diaria con Inteligencia Artificial), asistente financiera personal para jóvenes mexicanos. Hoy es {fecha}, día {dia}.

{contexto}

CATEGORIAS: vivienda, comida, transporte, salud, educacion, ocio, ropa, deudas, ahorro, imprevistos.

REGLAS:
- Español casual y amigable, nunca condescendiente
- USA SIEMPRE los números del PERFIL — nunca inventes cifras
- Disponible real: ${disponible:,.0f} — usa ese número exacto
- Si hay ALERTAS, menciónalas con ⚠️ de forma amigable
- Si la meta es imposible, dilo con respeto y sugiere alternativa
- Máximo 4 líneas por respuesta
- Enseña el porqué de cada consejo financiero
- Si el usuario pregunta "¿qué pasa si compro X?", "¿puedo comprarme X?", "¿me alcanza para X?" o similar:
  1. Calcula el impacto exacto: disponible después de la compra
  2. Di si afecta su meta y cuántos días/semanas se retrasa
  3. Sugiere una alternativa si no alcanza (ej: ahorrar X semanas primero)
  4. Termina con una decisión clara: "Sí puedes" o "Te recomiendo esperar"
  Usa los números reales del perfil, nunca inventes.

INSTRUCCION CRITICA: Al final de CADA respuesta agrega:
BUDGET_DATA:{{"vivienda_pct":0,"comida_pct":0,"transporte_pct":0,"salud_pct":0,"educacion_pct":0,"ocio_pct":0,"ropa_pct":0,"deudas_pct":0,"ahorro_pct":0,"meta_pct":0,"disponible":{disponible},"ingreso":{ingreso}}}

Rellena los _pct con (gasto_categoria / ingreso * 100). disponible e ingreso siempre fijos."""

def extract_ingreso(line):
    match = re.search(r'\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?', line, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(',', ''))
    return None

def update_perfil_from_message(user_message, perfil):
    msg = user_message.lower()
    for line in msg.split('\n'):
        if any(w in line for w in ['gano','gana','ingreso','salario','sueldo','recibo']):
            n = extract_ingreso(line)
            if n and n > 0:
                perfil["ingreso"] = n
                break
    if any(w in msg for w in ['meta','ahorrar','quiero tener','objetivo','guardar']):
        ingreso = perfil.get("ingreso", 0)
        matches = re.findall(r'\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?', msg)
        for m in matches:
            n = float(m.replace(',', ''))
            if n > ingreso and n > 1000:
                perfil["meta"] = n
                break
    return perfil

def calculate_budget_data(perfil, gastos):
    ingreso = perfil.get("ingreso", 0)
    meta = perfil.get("meta", 0)
    if ingreso == 0:
        return None
    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado

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
        "disponible": round(disponible), "ingreso": ingreso
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

# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    session_id = get_session_id()

    perfil = load_perfil(session_id)
    gastos = load_gastos(session_id)
    messages = load_mensajes(session_id)

    # Update perfil from message
    perfil = update_perfil_from_message(user_message, perfil)

    # Detect gastos
    new_gastos = []
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

    # Save to Supabase
    save_perfil(perfil)
    for cat, amount, desc in new_gastos:
        save_gasto(session_id, cat, amount, desc)

    messages.append({"role": "user", "content": user_message})
    save_mensaje(session_id, "user", user_message)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": get_system_prompt(perfil, gastos)}] + messages[-14:],
        temperature=0.7,
        max_tokens=600
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
    meta_tipo = data.get("meta_tipo", "ahorrar")

    pct_ahorro = {"relajado": 0.10, "equilibrado": 0.20, "agresivo": 0.35}.get(estrictez, 0.20)
    ahorro_mensual = round(ingreso * pct_ahorro)
    ahorro_necesario = round(meta / plazo) if plazo > 0 else 0
    es_viable = ahorro_necesario <= ahorro_mensual

    prompt = f"""Eres ALD.IA, asistente financiero empático para jóvenes mexicanos.

Datos del usuario:
- Ingreso: ${ingreso:,.0f}/mes
- Meta: ${meta:,.0f} ({meta_tipo}) en {plazo} meses
- Plan: {estrictez} ({int(pct_ahorro*100)}% de ahorro = ${ahorro_mensual:,.0f}/mes)
- Necesita ahorrar: ${ahorro_necesario:,.0f}/mes para lograrlo
- ¿Es viable?: {es_viable}

Genera en máximo 5 líneas:
1. Si la meta es viable o no (empático si no lo es)
2. Si no es viable, sugiere meta alternativa en ese plazo: ${ahorro_mensual*plazo:,.0f}
3. Cuánto ahorrar al mes y en cuánto tiempo llega a la meta real
4. Un consejo concreto para su situación
5. Frase motivadora corta

Emojis, español casual, directo."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=300
    )
    return jsonify({"plan": response.choices[0].message.content.strip()})

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

@app.route("/ping")
def ping():
    return "ok", 200

@app.route("/api/register", methods=["POST"])
def register():
    import bcrypt
    data = request.json
    email = data.get("email", "").lower().strip()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email y contraseña requeridos"}), 400
    if len(password) < 6:
        return jsonify({"error": "La contraseña debe tener al menos 6 caracteres"}), 400
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
            return jsonify({"error": "Email o contraseña incorrectos"}), 401
        usuario = res.data[0]
        if not bcrypt.checkpw(password.encode(), usuario["password_hash"].encode()):
            return jsonify({"error": "Email o contraseña incorrectos"}), 401
        session["session_id"] = usuario["session_id"]
        session["email"] = email
        return jsonify({"status": "ok", "email": email, "onboarding_done": usuario.get("onboarding_done", False), "ingreso": usuario.get("ingreso", 0), "meta": usuario.get("meta", 0), "plazo_meses": usuario.get("plazo_meses", 12), "tiene_vivienda": usuario.get("tiene_vivienda", True), "tiene_transporte": usuario.get("tiene_transporte", True), "tiene_deudas": usuario.get("tiene_deudas", True), "tiene_educacion": usuario.get("tiene_educacion", True)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})

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
    
    # Categoría más gastada
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
    
    prompt = f"""Eres ALD.IA, asistente financiera empática para jóvenes mexicanos.

El usuario acaba de abrir la app. Genera un resumen proactivo del mes en máximo 3 líneas:

Datos:
- Día del mes: {dia}
- Ingreso mensual: ${ingreso:,.0f}
- Total gastado: ${total_gastado:,.0f}
- Disponible: ${disponible:,.0f}
- Categoría más usada: {cat_critica} ({round(pct_critico)}% de su límite)
- Meta: ${perfil.get('meta', 0):,.0f}

El mensaje debe:
1. Saludar de vuelta brevemente
2. Dar 1-2 datos clave del mes en curso
3. Una observación o consejo corto
4. Terminar con pregunta corta tipo "¿seguimos?"

Español casual, emojis, máximo 3 líneas."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=150
    )
    return jsonify({"resumen": response.choices[0].message.content.strip()})

if __name__ == "__main__":
    app.run(debug=True)


