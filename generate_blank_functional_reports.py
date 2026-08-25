"""
Genera un PDF "vuoto" (bozza/modello stampabile) per ciascun profilo di verifica
funzionale presente nel database locale.

Ogni PDF riproduce la struttura del profilo (sezioni, checklist, tabelle e campi)
con i valori non compilati, così da poter essere stampato e compilato a mano,
oppure usato come anteprima/modello del profilo.

Uso:
    python generate_blank_functional_reports.py [cartella_output]

Se non specificata, la cartella di output è "PDF_Profili_Vuoti" nella cartella
corrente.
"""
import os
import re
import sys
import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from app import config
import database
import report_generator


def _blank_value(field) -> str:
    """Valore da mostrare per un campo non compilato: il default se presente,
    altrimenti stringa vuota."""
    if field.default not in (None, ""):
        return field.default
    return ""


def _build_blank_structured_results(profile) -> dict:
    """Ricostruisce la struttura 'functional_results' attesa da report_generator,
    con tutti i valori vuoti (o il default del campo, se previsto dal profilo)."""
    structured: dict[str, dict] = {}

    for idx, section in enumerate(profile.sections):
        section_data = {
            "title": section.title or section.key,
            "section_type": section.section_type,
            "show_in_summary": section.show_in_summary,
            "order": idx,
        }

        if section.section_type in ("fields", "form"):
            section_data["fields"] = [
                {
                    "key": field.key,
                    "label": field.label or field.key.replace("_", " ").title(),
                    "value": _blank_value(field),
                }
                for field in section.fields
                if field.field_type != "header"
            ]
        else:
            rows_out = []
            for row in section.rows:
                rows_out.append(
                    {
                        "key": row.key,
                        "label": row.label or row.key,
                        "values": [
                            {
                                "key": field.key,
                                "label": field.label or field.key.replace("_", " ").title(),
                                "value": _blank_value(field),
                            }
                            for field in row.fields
                        ],
                    }
                )
            section_data["rows"] = rows_out

        structured[section.key] = section_data

    return structured


def _get_logo_path() -> str:
    """Recupera il percorso del logo impostato nell'app (stesso QSettings usato
    dalla finestra principale), se presente."""
    try:
        settings = QSettings("ELSON META", "Safety Test Manager")
        return settings.value("logo_path", "") or ""
    except Exception:
        return ""


def _instruments_for_profile(profile) -> list[dict]:
    """Converte gli snapshot strumenti del profilo nel formato atteso dal report."""
    instruments = []
    for snap in (profile.instrument_snapshots or []):
        if not isinstance(snap, dict):
            continue
        instruments.append(
            {
                "instrument": snap.get("instrument", "N/A"),
                "serial": snap.get("serial", "N/A"),
                "version": snap.get("version", "N/A"),
                "cal_date": snap.get("cal_date", "N/A"),
            }
        )
    return instruments


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    output_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "PDF_Profili_Vuoti")
    os.makedirs(output_dir, exist_ok=True)

    # QApplication è necessaria perché report_generator usa componenti Qt
    # (QImage, ecc.) per elaborare logo/immagini.
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Safety Test Manager")
    app.setOrganizationName("ELSON META")

    config.load_functional_profiles()
    profiles = config.FUNCTIONAL_PROFILES
    if not profiles:
        print("Nessun profilo funzionale trovato nel database.")
        return

    report_settings = {"logo_path": _get_logo_path()}

    generated = 0
    failed = []

    for profile_key, profile in profiles.items():
        raw_name = (profile.name or profile_key).replace("\n", " ").replace("\r", " ")
        safe_name = re.sub(r'[\\/*?:"<>|]', "_", raw_name)
        safe_name = re.sub(r"\s+", " ", safe_name).strip() or profile_key
        filename = os.path.join(output_dir, f"{safe_name}.pdf")

        used_instruments = _instruments_for_profile(profile)
        mti_info = used_instruments[0] if len(used_instruments) == 1 else {}

        verification_data = {
            "date": "",
            "profile_name": profile.name,
            "overall_status": "CONFORME",
            "results": [],
            "visual_inspection_data": {},
            "verification_code": "MODELLO",
            "functional_results": _build_blank_structured_results(profile),
            "used_instruments": used_instruments,
        }

        try:
            report_generator.create_report(
                filename,
                {},   # device_info
                {},   # customer_info
                {},   # destination_info
                mti_info,
                report_settings,
                verification_data,
                "",   # technician_name
                None,  # signature_data
            )
            print(f"OK  -> {filename}")
            generated += 1
        except Exception as e:
            logging.error(f"Errore generando il PDF per il profilo '{profile.name}': {e}", exc_info=True)
            failed.append(profile.name)

    print(f"\nCompletato: {generated} PDF generati in '{output_dir}'.")
    if failed:
        print(f"Falliti ({len(failed)}): {', '.join(failed)}")


if __name__ == "__main__":
    main()
