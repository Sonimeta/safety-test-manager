# Smoke test wizard profili funzionali (offscreen) - file temporaneo
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QMessageBox

def _no_modal(*args, **kwargs):
    raise AssertionError(f"QMessageBox inaspettato: {args}")
QMessageBox.information = _no_modal
QMessageBox.warning = _no_modal
QMessageBox.critical = _no_modal

app = QApplication([])

from app.functional_templates import FUNCTIONAL_PROFILE_TEMPLATES
from app.functional_models import validate_functional_profile
from app.ui.dialogs.functional_profile_manager_dialog import FunctionalProfileWizard

w = FunctionalProfileWizard()

# La lista template deve riflettere i template reali
assert w.template_list.count() == len(FUNCTIONAL_PROFILE_TEMPLATES), \
    f"attesi {len(FUNCTIONAL_PROFILE_TEMPLATES)} template, trovati {w.template_list.count()}"
print("1) lista template dinamica:", w.template_list.count(), "voci")

# Selezione 'da template' del defibrillatore
w.create_method_combo.setCurrentIndex(1)  # template
for i in range(w.template_list.count()):
    if w.template_list.item(i).data(0x0100) == "defibrillatore_fun":  # Qt.UserRole
        w.template_list.setCurrentRow(i)
        break
w.wizard_name_edit.setText("DEFIBRILLATORE REPARTO X")
profile = w.get_profile()
assert profile is not None
assert len(profile.sections) == 5, f"attese 5 sezioni dal template defib, trovate {len(profile.sections)}"
assert profile.profile_key == "defibrillatore_reparto_x"
assert profile.device_type == "DEFIBRILLATORE"  # ereditato dal template
assert validate_functional_profile(profile) == []
print("2) profilo da template defibrillatore: 5 sezioni, chiave/tipo corretti, valido")

# Metodo 'vuoto'
w2 = FunctionalProfileWizard()
w2.create_method_combo.setCurrentIndex(0)
w2.wizard_name_edit.setText("PROVA VUOTA")
p2 = w2.get_profile()
assert p2 is not None and p2.sections == []
print("3) profilo vuoto: OK")

print("\nSMOKE WIZARD SUPERATO")
