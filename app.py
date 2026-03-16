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
app.secret_key = "sofia-shadow-works-2026"
CORS(app)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_system_prompt(perfil, gastos):
    now = datetime.now()
    fecha = now.strftime("%B %Y")
    dia = now.day

    ingreso = perfil.get("ingreso", 0)
    meta = perfil.get("meta", 0)
    meta_plazo = perfil.get("plazo", "")
    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado

    contexto = f"""PERFIL DEL USUARIO:
- Ingreso mensual: ${ingreso:,.0f} pesos
- Meta: ahorrar ${meta:,.0f} pesos {meta_plazo}
- Gastos registrados este mes: {json.dumps(gastos, ensure_ascii=False)}
- Total gastado: ${total_gastado:,.0f} pesos
- Disponible real: ${disponible:,.0f} pesos
- Día del mes: {dia}"""

    return f"""Eres SOFIA, una asistente financiera personal en español para jóvenes mexicanos. Hoy es {fecha}, día {dia}.

{contexto if ingreso > 0 else "El usuario aún no ha dado su perfil financiero."}

CATEGORIAS: Comida (restaurantes, super, tacos), Transporte (uber, taxi, metro, gasolina), Entretenimiento (Netflix, Spotify, cine, juegos), Tecnologia (apps, Claude, ChatGPT, software), Ropa, Salud (gym, doctor), Gustos (perfumes, caprichos, lujos), Otros.

REGLAS:
- Español casual y amigable, nunca condescendiente
- USA SIEMPRE los números del PERFIL DEL USUARIO — nunca inventes cifras
- El disponible real es ${disponible:,.0f} — usa ese número, no calcules por tu cuenta
- Nunca regañes, enfoca en lo que SÍ puede gastar
- Máximo 4 líneas por respuesta

INSTRUCCION CRITICA: Al final de CADA respuesta agrega exactamente:
BUDGET_DATA:{{"comida_pct":0,"transporte_pct":0,"tecnologia_pct":0,"gustos_pct":0,"ahorro_pct":0,"meta_pct":0,"disponible":{disponible}}}

Rellena los _pct con porcentajes reales basados en los gastos del perfil vs el ingreso.
disponible siempre debe ser {disponible}."""

def get_session():
    if "messages" not in session:
        session["messages"] = []
    if "perfil" not in session:
        session["perfil"] = {"ingreso": 0, "meta": 0, "plazo": ""}
    if "gastos" not in session:
        session["gastos"] = {
            "comida": 0, "transporte": 0, "tecnologia": 0,
            "gustos": 0, "ropa": 0, "salud": 0, "entretenimiento": 0, "otros": 0
        }
    return session["messages"], session["perfil"], session["gastos"]

def extract_numbers(text):
    numbers = re.findall(r'[\$]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:pesos?|mxn)?', text.lower())
    return [float(n.replace(',', '')) for n in numbers]

def update_perfil_and_gastos(user_message, perfil, gastos):
    msg = user_message.lower()
    numbers = extract_numbers(user_message)

    # Detect ingreso
    if any(w in msg for w in ['gano', 'gana', 'ingreso', 'salario', 'sueldo', 'recibo']) and numbers:
        perfil["ingreso"] = numbers[0]

    # Detect meta
    if any(w in msg for w in ['meta', 'ahorrar', 'quiero tener', 'objetivo']) and numbers:
        for n in numbers:
            if n > perfil.get("ingreso", 0):
                perfil["meta"] = n
                break

    # Detect plazo
    for plazo in ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
                  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']:
        if plazo in msg:
            perfil["plazo"] = f"para {plazo}"

    if 'año' in msg or 'meses' in msg or 'semanas' in msg:
        for w in ['12 meses', '6 meses', '3 meses', '1 año', '2 años']:
            if w in msg:
                perfil["plazo"] = f"en {w}"

    # Detect gastos
    if any(w in msg for w in ['gasté', 'gaste', 'compré', 'compre', 'pagué', 'pague', 'costó', 'costo']) and numbers:
        amount = numbers[0]

        if any(w in msg for w in ['super', 'supermercado', 'comida', 'taco', 'tacos', 'restaurante', 'comer', 'almorzar', 'desayun', 'cenar', 'pizza', 'hamburguesa', 'torta']):
            gastos["comida"] += amount
        elif any(w in msg for w in ['uber', 'taxi', 'camion', 'metro', 'gasolina', 'transporte', 'bus', 'didi']):
            gastos["transporte"] += amount
        elif any(w in msg for w in ['netflix', 'spotify', 'cine', 'juego', 'hbo', 'disney', 'prime', 'entretenimiento']):
            gastos["entretenimiento"] += amount
        elif any(w in msg for w in ['claude', 'chatgpt', 'app', 'software', 'hosting', 'dominio', 'tecnologia', 'suscripcion']):
            gastos["tecnologia"] += amount
        elif any(w in msg for w in ['ropa', 'zapatos', 'camisa', 'pantalon', 'vestido', 'tenis']):
            gastos["ropa"] += amount
        elif any(w in msg for w in ['gym', 'doctor', 'medicina', 'farmacia', 'salud', 'hospital']):
            gastos["salud"] += amount
        elif any(w in msg for w in ['perfume', 'capricho', 'lujo', 'gusto', 'regalo']):
            gastos["gustos"] += amount
        else:
            gastos["otros"] += amount

    return perfil, gastos

def calculate_budget_data(perfil, gastos):
    ingreso = perfil.get("ingreso", 0)
    meta = perfil.get("meta", 0)
    if ingreso == 0:
        return None

    total_gastado = sum(gastos.values())
    disponible = ingreso - total_gastado

    def pct(cat):
        return round((gastos.get(cat, 0) / ingreso) * 100, 1) if ingreso > 0 else 0

    ahorro = max(0, disponible)
    ahorro_pct = round((ahorro / ingreso) * 100, 1) if ingreso > 0 else 0
    meta_pct = round((ahorro / meta) * 100, 1) if meta > 0 else 0

    return {
        "comida_pct": pct("comida"),
        "transporte_pct": pct("transporte"),
        "tecnologia_pct": pct("tecnologia") + pct("entretenimiento"),
        "gustos_pct": pct("gustos") + pct("ropa"),
        "ahorro_pct": ahorro_pct,
        "meta_pct": min(meta_pct, 100),
        "disponible": round(disponible)
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    messages, perfil, gastos = get_session()

    # Update perfil and gastos from user message
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

    # Extract and strip BUDGET_DATA
    clean_response = full_response
    budget_match = re.search(r'BUDGET_DATA:(\{.*?\})', full_response)
    if budget_match:
        try:
            clean_response = full_response.replace(budget_match.group(0), "").strip()
        except:
            pass

    messages.append({"role": "assistant", "content": clean_response})
    session["messages"] = messages

    # Always calculate budget from real data
    budget_data = calculate_budget_data(perfil, gastos)

    return jsonify({
        "response": clean_response,
        "budget": budget_data
    })

@app.route("/api/reset", methods=["POST"])
def reset():
    session.clear()
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(debug=True)
