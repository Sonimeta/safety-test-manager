# app/profile_templates.py
from .data_models import Test, Limit

# Modello base per la norma IEC 62353
TEMPLATE_BASE = [
    Test(name="Resistenza conduttore di terra", parameter="", limits={"::ST": Limit(unit="Ohm", high_value=0.3)}),
    Test(name="Corrente dispersione diretta dispositivo", parameter="Normale", limits={"::ST": Limit(unit="uA", high_value=500.0)}),
    Test(name="Corrente dispersione diretta dispositivo", parameter="Inversa", limits={"::ST": Limit(unit="uA", high_value=500.0)}),
]

# Modello che include anche test per parti applicate
TEMPLATE_CON_PA = TEMPLATE_BASE + [
    Test(name="Corrente dispersione diretta P.A.", parameter="Normale", limits={"::BF": Limit(unit="uA", high_value=5000.0)}, is_applied_part_test=True),
    Test(name="Corrente dispersione diretta P.A.", parameter="Inversa", limits={"::CF": Limit(unit="uA", high_value=5000.0)}, is_applied_part_test=True),
]

# Dizionario per accedere facilmente ai template
PROFILE_TEMPLATES = {
    "Profilo Vuoto": [],
    "Verifica Base (IEC 62353)": TEMPLATE_BASE,
    "Verifica con Parti Applicate (BF/CF)": TEMPLATE_CON_PA,
}