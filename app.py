from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
from datetime import datetime
import os
import json
import re

load_dotenv()

app = Flask(__name__)
app.secret_key = "aldia-shadow-works-2026"
CORS(app)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Porcentajes sugeridos por Andy
PORCENTAJES_BASE = {
    "vivienda": 30,
    "comida": 12,
    "transporte": 12,
    "salud": 8,
    "educacion": 2,
    "ocio": 7,
    "ropa": 3,
    "deudas": 8,
    "ahorro": 15,
    "imprevistos": 3
}

GASTO_PATTERN = re.compile(
    r'(?:gasté|gaste|compré|compre|pagué|pague|costó|costo|gasto)\s+\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?\s*(?:en\s+(.{1,60}))?',
    re.IGNORECASE
)

def classify_gasto(desc):
    if not desc:
        return "otros"
    d = desc.lower()
    if any(w in d for w in ['renta', 'alquiler', 'hipoteca', 'luz', 'agua', 'gas', 'internet', 'telefono', 'celular', 'seguro casa', 'vivienda']):
        return "vivienda"
    if any(w in d for w in ['super', 'supermercado', 'comida', 'taco', 'tacos', 'restaurante', 'comer', 'almuerzo', 'desayuno', 'cena', 'pizza', 'hamburguesa', 'torta', 'delivery', 'rappi', 'uber eats', 'snack', 'mercado']):
        return "comida"
    if any(w in d for w in ['uber', 'taxi', 'camion', 'metro', 'gasolina', 'transporte', 'bus', 'didi', 'autobus', 'tren', 'peaje', 'estacionamiento', 'mantenimiento auto', 'seguro auto']):
        return "transporte"
    if any(w in d for w in ['doctor', 'medico', 'medicina', 'farmacia', 'hospital', 'consulta', 'gym', 'gimnasio', 'dentista', 'salud', 'higiene', 'farmacia']):
        return "salud"
    if any(w in d for w in ['curso', 'libro', 'certificacion', 'escuela', 'universidad', 'colegio', 'educacion', 'formacion', 'capacitacion', 'clase']):
        return "educacion"
    if any(w in d for w in ['netflix', 'spotify', 'cine', 'juego', 'hbo', 'disney', 'prime', 'entretenimiento', 'concierto', 'evento', 'hobby', 'streaming', 'claude', 'chatgpt', 'app', 'software', 'suscripcion', 'tecnologia']):
        return "ocio"
    if any(w in d for w in ['ropa', 'zapatos', 'camisa', 'pantalon', 'vestido', 'tenis', 'calzado', 'accesorio', 'bolsa', 'cartera']):
        return "ropa"
    if any(w in d for w in ['deuda', 'credito', 'prestamo', 'tarjeta', 'pago minimo', 'abono', 'credito']):
        return "deudas"
    if any(w in d for w in ['ahorro', 'inversion', 'fondo', 'deposito']):
        return "ahorro"
    if any(w in d for w in ['impuesto', 'isr', 'iva', 'sat', 'imptos', 'declaracion', 'fiscal']):
        return "imprevistos"
    return "imprevistos"

def get_system_prompt(perfil, gastos):
    now = datetime.now()
    fecha = now.strftime("%B %Y")
    dia = now.day
    ingreso = perfil.get("ingreso", 0)
    meta = perfil.get("meta", 0)
    meta_plazo = perfil.get("plazo", "")
    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado

    # Calcular límites y alertas
    limites = {cat: round(ingreso * pct / 100) for cat, pct in PORCENTAJES_BASE.items()} if ingreso > 0 else {}
    alertas = []
    for cat, limite in limites.items():
        gastado = gastos.get(cat, 0)
        if limite > 0 and gastado >= limite * 0.85:
            pct_usado = round(gastado / limite * 100)
            alertas.append(f"{cat}: {pct_usado}% usado (límite ${limite:,.0f})")

    contexto = f"""PERFIL DEL USUARIO:
- Ingreso mensual: ${ingreso:,.0f} pesos
- Meta: ahorrar ${meta:,.0f} pesos {meta_plazo}
- Gastos registrados: {json.dumps(gastos, ensure_ascii=False)}
- Total gastado: ${total_gastado:,.0f} pesos
- Disponible real: ${disponible:,.0f} pesos
- Límites sugeridos por categoría: {json.dumps(limites, ensure_ascii=False)}
- ALERTAS ACTIVAS: {alertas if alertas else 'ninguna'}
- Día del mes: {dia}""" if ingreso > 0 else "El usuario aún no ha dado su perfil financiero."

    return f"""Eres ALD.IA (Automatización de Liquidación Diaria con Inteligencia Artificial), una asistente financiera personal en español para jóvenes mexicanos. Hoy es {fecha}, día {dia}.

{contexto}

CATEGORIAS (usa estas exactas):
- vivienda: renta, luz, agua, internet, teléfono, seguro de casa
- comida: super, restaurantes, delivery, snacks, mercado
- transporte: uber, taxi, metro, gasolina, mantenimiento auto
- salud: doctor, medicamentos, gym, higiene personal
- educacion: cursos, libros, certificaciones, escuela
- ocio: streaming, cine, eventos, hobbies, apps, software, Claude, ChatGPT
- ropa: ropa, zapatos, accesorios
- deudas: tarjetas de crédito, préstamos
- ahorro: fondo de emergencia, inversiones
- imprevistos: impuestos, regalos, mascotas, gastos inesperados

REGLAS:
- Español casual y amigable, nunca condescendiente
- USA SIEMPRE los números del PERFIL — nunca inventes cifras
- El disponible real es ${disponible:,.0f} — usa ese número exacto
- Si hay ALERTAS ACTIVAS, menciónalas con emoji ⚠️ de forma amigable, no regañona
- Si la meta es imposible con el ingreso actual, dilo con respeto y sugiere una meta realista
- Cuando no hay perfil, haz máximo 2 preguntas: ingreso y meta
- Máximo 4 líneas por respuesta
- Si detectas un gasto de impuestos, clasifícalo en imprevistos y explícalo

INSTRUCCION CRITICA: Al final de CADA respuesta agrega exactamente:
BUDGET_DATA:{{"vivienda_pct":0,"comida_pct":0,"transporte_pct":0,"salud_pct":0,"educacion_pct":0,"ocio_pct":0,"ropa_pct":0,"deudas_pct":0,"ahorro_pct":0,"meta_pct":0,"disponible":{disponible},"ingreso":{ingreso}}}

Rellena los _pct con porcentajes reales (gasto de esa categoria / ingreso * 100).
disponible siempre debe ser {disponible}, ingreso siempre debe ser {ingreso}."""

def get_session():
    if "messages" not in session:
        session["messages"] = []
    if "perfil" not in session:
        session["perfil"] = {"ingreso": 0, "meta": 0, "plazo": ""}
    if "gastos" not in session:
        session["gastos"] = {cat: 0 for cat in PORCENTAJES_BASE.keys()}
    return session["messages"], session["perfil"], session["gastos"]

def extract_ingreso(line):
    match = re.search(r'\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?', line, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(',', ''))
    return None

def update_perfil_and_gastos(user_message, perfil, gastos):
    msg = user_message.lower()

    # Detect ingreso — line by line to avoid confusing with gastos
    for line in msg.split('\n'):
        if any(w in line for w in ['gano', 'gana', 'ingreso', 'salario', 'sueldo', 'recibo', 'gano como']):
            n = extract_ingreso(line)
            if n and n > 0:
                perfil["ingreso"] = n
                break

    # Detect meta
    if any(w in msg for w in ['meta', 'ahorrar', 'quiero tener', 'objetivo', 'guardar']):
        ingreso = perfil.get("ingreso", 0)
        matches = re.findall(r'\$?\s*(\d[\d,\.]*)\s*(?:pesos?|mxn)?', msg)
        for m in matches:
            n = float(m.replace(',', ''))
            if n > ingreso and n > 1000:
                perfil["meta"] = n
                break

    # Detect plazo
    for plazo in ['enero','febrero','marzo','abril','mayo','junio',
                  'julio','agosto','septiembre','octubre','noviembre','diciembre']:
        if plazo in msg:
            perfil["plazo"] = f"para {plazo}"
    for w in ['12 meses','6 meses','3 meses','1 año','2 años']:
        if w in msg:
            perfil["plazo"] = f"en {w}"

    # Detect gastos with GASTO_PATTERN
    for match in GASTO_PATTERN.finditer(user_message):
        amount_str = match.group(1).replace(',', '')
        try:
            amount = float(amount_str)
        except:
            continue
        desc = match.group(2) or ""
        cat = classify_gasto(desc)
        gastos[cat] = gastos.get(cat, 0) + amount

    return perfil, gastos

def calculate_budget_data(perfil, gastos):
    ingreso = perfil.get("ingreso", 0)
    meta = perfil.get("meta", 0)
    if ingreso == 0:
        return None

    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado

    def pct(cat):
        return round((gastos.get(cat, 0) / ingreso) * 100, 1)

    ahorro_real = max(0, disponible)
    ahorro_pct = round((ahorro_real / ingreso) * 100, 1)
    meta_pct = round((ahorro_real / meta) * 100, 1) if meta > 0 else 0

    return {
        "vivienda_pct":   pct("vivienda"),
        "comida_pct":     pct("comida"),
        "transporte_pct": pct("transporte"),
        "salud_pct":      pct("salud"),
        "educacion_pct":  pct("educacion"),
        "ocio_pct":       pct("ocio"),
        "ropa_pct":       pct("ropa"),
        "deudas_pct":     pct("deudas"),
        "ahorro_pct":     ahorro_pct,
        "meta_pct":       min(meta_pct, 100),
        "disponible":     round(disponible),
        "ingreso":        ingreso
    }

def check_alerts(perfil, gastos):
    ingreso = perfil.get("ingreso", 0)
    if ingreso == 0:
        return False
    for cat, pct in PORCENTAJES_BASE.items():
        limite = ingreso * pct / 100
        gastado = gastos.get(cat, 0)
        if limite > 0 and gastado >= limite * 0.85:
            return True
    return False

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    messages, perfil, gastos = get_session()

    perfil, gastos = update_perfil_and_gastos(user_message, perfil, gastos)
    session["perfil"] = perfil
    session["gastos"] = gastos

    messages.append({"role": "user", "content": user_message})

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

    messages.append({"role": "assistant", "content": clean_response})
    session["messages"] = messages

    budget_data = calculate_budget_data(perfil, gastos)
    has_alert = check_alerts(perfil, gastos)

    return jsonify({
        "response": clean_response,
        "budget": budget_data,
        "alert": has_alert
    })

@app.route("/api/reset", methods=["POST"])
def reset():
    session.clear()
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(debug=True)