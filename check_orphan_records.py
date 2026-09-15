#!/usr/bin/env python3
"""
check_orphan_records.py
=======================
Script di diagnosi avanzata e bonifica per il database PostgreSQL online di Safety Test Manager (STM).

Verifica la presenza di:
 1. Record Orfani (Foreign Key mancanti, NULL o inesistenti nella tabella genitore)
 2. Riferimenti Fantasma (figli attivi is_deleted=FALSE collegati a genitori soft-deleted is_deleted=TRUE)
 3. UUID Mancanti o Vuoti
 4. UUID Duplicati all'interno della stessa tabella

Utilizzo:
    # Modalità sola lettura (Diagnosi):
    python check_orphan_records.py

    # Modalità bonifica interattiva:
    python check_orphan_records.py --fix

    # Specificando parametri personalizzati:
    python check_orphan_records.py --host 195.149.221.71 --dbname safety_test_db --user postgres
"""

import os
import sys
import argparse
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# Carica variabili d'ambiente da .env
def load_environment():
    search_dirs = [
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ]
    for d in search_dirs:
        env_file = os.path.join(d, '.env')
        if os.path.isfile(env_file):
            load_dotenv(env_file)
            print(f"[+] File .env caricato da: {env_file}")
            return
    load_dotenv()

# Definizione dei controlli di integrità relazionale
RELATIONSHIP_CHECKS = [
    {
        "table": "destinations",
        "parent_table": "customers",
        "fk_column": "customer_id",
        "parent_pk": "id",
        "name": "Destinazioni (Sedi) con Cliente inesistente o NULL",
        "ghost_name": "Destinazioni attive con Cliente eliminato (soft-deleted)",
    },
    {
        "table": "devices",
        "parent_table": "destinations",
        "fk_column": "destination_id",
        "parent_pk": "id",
        "name": "Apparecchiature con Destinazione (Sede) inesistente o NULL",
        "ghost_name": "Apparecchiature attive con Destinazione eliminata",
    },
    {
        "table": "verifications",
        "parent_table": "devices",
        "fk_column": "device_id",
        "parent_pk": "id",
        "name": "Verifiche Elettriche con Apparecchio inesistente o NULL",
        "ghost_name": "Verifiche Elettriche attive su Apparecchio eliminato",
    },
    {
        "table": "functional_verifications",
        "parent_table": "devices",
        "fk_column": "device_id",
        "parent_pk": "id",
        "name": "Verifiche Funzionali con Apparecchio inesistente o NULL",
        "ghost_name": "Verifiche Funzionali attive su Apparecchio eliminato",
    },
    {
        "table": "profile_tests",
        "parent_table": "profiles",
        "fk_column": "profile_id",
        "parent_pk": "id",
        "name": "Prove di Verifica con Profilo Elettrico inesistente o NULL",
        "ghost_name": "Prove di Verifica attive su Profilo eliminato",
    },
    {
        "table": "system_verifications",
        "parent_table": "destinations",
        "fk_column": "destination_id",
        "parent_pk": "id",
        "name": "Verifiche di Sistema con Destinazione inesistente o NULL",
        "ghost_name": "Verifiche di Sistema attive su Destinazione eliminata",
    },
    {
        "table": "system_verification_devices",
        "parent_table": "system_verifications",
        "fk_column": "system_verification_id",
        "parent_pk": "id",
        "name": "Dispositivi in Verifica Sistema con Scheda Madre inesistente",
        "ghost_name": "Dispositivi attivi collegati a Verifica Sistema eliminata",
    },
    {
        "table": "system_verification_devices",
        "parent_table": "devices",
        "fk_column": "device_id",
        "parent_pk": "id",
        "name": "Dispositivi in Verifica Sistema con Apparecchio inesistente",
        "ghost_name": "Dispositivi in Verifica Sistema collegati ad Apparecchio eliminato",
    },
    {
        "table": "device_unavailability_reports",
        "parent_table": "devices",
        "fk_column": "device_id",
        "parent_pk": "id",
        "name": "Segnalazioni Non Disponibile con Apparecchio inesistente",
        "ghost_name": "Segnalazioni Non Disponibile attive su Apparecchio eliminato",
    },
    {
        "table": "device_unavailability_reports",
        "parent_table": "destinations",
        "fk_column": "destination_id",
        "parent_pk": "id",
        "name": "Segnalazioni Non Disponibile con Sede inesistente",
        "ghost_name": "Segnalazioni Non Disponibile attive su Sede eliminata",
    },
    {
        "table": "ecografo_quality_checks",
        "parent_table": "devices",
        "fk_column": "device_id",
        "parent_pk": "id",
        "name": "Controlli CQ Ecografi con Apparecchio inesistente",
        "ghost_name": "Controlli CQ Ecografi attivi su Apparecchio eliminato",
    },
    {
        "table": "ecografo_quality_probes",
        "parent_table": "ecografo_quality_checks",
        "fk_column": "check_id",
        "parent_pk": "id",
        "name": "Sonde CQ con Controllo Ecografo inesistente",
        "ghost_name": "Sonde CQ attive su Controllo Ecografo eliminato",
    },
    {
        "table": "ecografo_quality_controls",
        "parent_table": "ecografo_quality_probes",
        "fk_column": "probe_id",
        "parent_pk": "id",
        "name": "Valutazioni Parametri CQ con Sonda inesistente",
        "ghost_name": "Valutazioni Parametri CQ attive su Sonda eliminata",
    },
    {
        "table": "verification_assignments",
        "parent_table": "devices",
        "fk_column": "device_id",
        "parent_pk": "id",
        "name": "Assegnazioni Lavori con Apparecchio inesistente (non-NULL)",
        "ghost_name": "Assegnazioni Lavori attive su Apparecchio eliminato",
        "allow_null": True
    },
]

ALL_TABLES = [
    "users", "customers", "destinations", "devices", "verifications",
    "functional_verifications", "profiles", "profile_tests", "functional_profiles",
    "mti_instruments", "signatures", "verification_attachments", "system_verifications",
    "system_verification_devices", "verification_assignments", "device_unavailability_reports",
    "ecografo_quality_checks", "ecografo_quality_probes", "ecografo_quality_controls", "audit_log"
]

def check_table_exists(cur, table_name: str) -> bool:
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = %s
        )
    """, (table_name,))
    return cur.fetchone()['exists']

def has_column(cur, table_name: str, column_name: str) -> bool:
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        )
    """, (table_name, column_name))
    return cur.fetchone()['exists']

def run_diagnostic(cur):
    print("\n" + "="*80)
    print("🔍 AVVIO DIAGNOSI INTEGRITÀ DATABASE ONLINE (PostgreSQL)")
    print("="*80 + "\n")

    total_issues = 0
    orphan_records_map = {}

    # 1. Controllo UUID Mancanti / Vuoti
    print("--- 1. CONTROLLO UUID MANCANTI O VUOTI ---")
    for t in ALL_TABLES:
        if not check_table_exists(cur, t):
            continue
        if not has_column(cur, t, "uuid"):
            continue
        cur.execute(f"SELECT id FROM {t} WHERE uuid IS NULL OR TRIM(uuid) = ''")
        rows = cur.fetchall()
        if rows:
            print(f"  ❌ Tabella '{t}': {len(rows)} record con UUID mancante o vuoto (IDs: {[r['id'] for r in rows[:10]]}{'...' if len(rows) > 10 else ''})")
            total_issues += len(rows)
            orphan_records_map.setdefault("missing_uuid", []).append({"table": t, "ids": [r["id"] for r in rows]})
        else:
            print(f"  ✓ Tabella '{t}': tutti i record hanno un UUID valido")

    # 2. Controllo UUID Duplicati
    print("\n--- 2. CONTROLLO UUID DUPLICATI ---")
    for t in ALL_TABLES:
        if not check_table_exists(cur, t) or not has_column(cur, t, "uuid"):
            continue
        cur.execute(f"""
            SELECT uuid, COUNT(*) as cnt 
            FROM {t} 
            WHERE uuid IS NOT NULL AND TRIM(uuid) <> ''
            GROUP BY uuid 
            HAVING COUNT(*) > 1
        """)
        dups = cur.fetchall()
        if dups:
            print(f"  ❌ Tabella '{t}': {len(dups)} UUID duplicati rilevati!")
            for d in dups[:5]:
                print(f"     • UUID: {d['uuid']} (compare {d['cnt']} volte)")
            total_issues += len(dups)
        else:
            print(f"  ✓ Tabella '{t}': nessun UUID duplicato")

    # 3. Controllo Relazioni e Record Orfani
    print("\n--- 3. CONTROLLO RECORD ORFANI (FK NON VALIDE O GENITORE MANCANTE) ---")
    for rel in RELATIONSHIP_CHECKS:
        child_tbl = rel["table"]
        parent_tbl = rel["parent_table"]
        fk_col = rel["fk_column"]
        parent_pk = rel["parent_pk"]
        allow_null = rel.get("allow_null", False)

        if not check_table_exists(cur, child_tbl) or not check_table_exists(cur, parent_tbl):
            continue

        # A) Record orfani duri (FK non esiste affatto nella tabella genitore)
        null_condition = f"AND c.{fk_col} IS NOT NULL" if allow_null else ""
        sql_orphan = f"""
            SELECT c.id, c.uuid
            FROM {child_tbl} c
            LEFT JOIN {parent_tbl} p ON c.{fk_col} = p.{parent_pk}
            WHERE p.{parent_pk} IS NULL {null_condition}
        """
        cur.execute(sql_orphan)
        orphans = cur.fetchall()
        if orphans:
            print(f"  ❌ {rel['name']}: {len(orphans)} RECORD ORFANI TROVATI!")
            for o in orphans[:5]:
                print(f"     • id={o['id']}, uuid={o.get('uuid', 'N/D')}")
            if len(orphans) > 5:
                print(f"     • ... e altri {len(orphans)-5} record")
            total_issues += len(orphans)
            orphan_records_map.setdefault("hard_orphans", []).append({
                "table": child_tbl,
                "fk_column": fk_col,
                "ids": [o["id"] for o in orphans]
            })
        else:
            print(f"  ✓ {rel['name']}: OK (0 orfani)")

        # B) Riferimenti Fantasma (genitore eliminato ma figlio attivo)
        if has_column(cur, child_tbl, "is_deleted") and has_column(cur, parent_tbl, "is_deleted"):
            sql_ghost = f"""
                SELECT c.id, c.uuid
                FROM {child_tbl} c
                JOIN {parent_tbl} p ON c.{fk_col} = p.{parent_pk}
                WHERE (c.is_deleted = FALSE OR c.is_deleted IS NULL)
                  AND (p.is_deleted = TRUE)
            """
            cur.execute(sql_ghost)
            ghosts = cur.fetchall()
            if ghosts:
                print(f"  ⚠️  {rel['ghost_name']}: {len(ghosts)} record attivi con genitore cancellato")
                total_issues += len(ghosts)
                orphan_records_map.setdefault("ghost_orphans", []).append({
                    "table": child_tbl,
                    "ids": [g["id"] for g in ghosts]
                })

    # 4. Controllo Allegati Verifiche
    print("\n--- 4. CONTROLLO ALLEGATI (verification_attachments) ---")
    if check_table_exists(cur, "verification_attachments"):
        # Allegati di verifiche elettriche
        cur.execute("""
            SELECT va.id, va.uuid, va.filename
            FROM verification_attachments va
            LEFT JOIN verifications v ON va.verification_id = v.id
            WHERE va.verification_type = 'electrical' AND v.id IS NULL
        """)
        va_orphans_el = cur.fetchall()

        # Allegati di verifiche funzionali
        cur.execute("""
            SELECT va.id, va.uuid, va.filename
            FROM verification_attachments va
            LEFT JOIN functional_verifications fv ON va.verification_id = fv.id
            WHERE va.verification_type = 'functional' AND fv.id IS NULL
        """)
        va_orphans_fn = cur.fetchall()

        # Allegati di strumenti MTI
        cur.execute("""
            SELECT va.id, va.uuid, va.filename
            FROM verification_attachments va
            LEFT JOIN mti_instruments mi ON va.verification_id = mi.id
            WHERE va.verification_type = 'instrument' AND mi.id IS NULL
        """)
        va_orphans_ins = cur.fetchall()

        tot_va = len(va_orphans_el) + len(va_orphans_fn) + len(va_orphans_ins)
        if tot_va > 0:
            print(f"  ❌ Allegati orfani: {tot_va} (Elettriche: {len(va_orphans_el)}, Funzionali: {len(va_orphans_fn)}, Strumenti: {len(va_orphans_ins)})")
            total_issues += tot_va
            all_va_ids = [r["id"] for r in va_orphans_el + va_orphans_fn + va_orphans_ins]
            orphan_records_map.setdefault("hard_orphans", []).append({
                "table": "verification_attachments",
                "fk_column": "verification_id",
                "ids": all_va_ids
            })
        else:
            print("  ✓ verification_attachments: tutti gli allegati sono correttamente collegati")

    print("\n" + "="*80)
    if total_issues == 0:
        print("🎉 NESSUNA ANOMALIA RISCONTRATA! Il database online è perfettamente integro.")
        print("="*80 + "\n")
    else:
        print(f"⚠️  RILEVATE {total_issues} ANOMALIE CHE POSSONO GENERARE CONFLITTI DI SINCRONIZZAZIONE.")
        print("="*80 + "\n")

    return total_issues, orphan_records_map


def repair_database(conn, cur, orphan_map):
    print("\n" + "="*80)
    print("🛠️  AVVIO BONIFICA RECORD ORFANI E ANOMALIE")
    print("="*80 + "\n")

    # 1. Assegna UUID mancanti
    if "missing_uuid" in orphan_map:
        for item in orphan_map["missing_uuid"]:
            t = item["table"]
            ids = item["ids"]
            print(f"[+] Generazione UUID per {len(ids)} record in '{t}'...")
            for rid in ids:
                new_u = str(uuid.uuid4())
                cur.execute(f"UPDATE {t} SET uuid = %s WHERE id = %s", (new_u, rid))
        conn.commit()
        print("  ✓ UUID mancanti generati con successo.")

    # 2. Soft-delete per i record figli con genitore cancellato (ghosts)
    if "ghost_orphans" in orphan_map:
        now_ts = datetime.now(timezone.utc)
        for item in orphan_map["ghost_orphans"]:
            t = item["table"]
            ids = item["ids"]
            print(f"[+] Allineamento stato cancellazione (soft-delete) per {len(ids)} record in '{t}'...")
            cur.execute(
                f"UPDATE {t} SET is_deleted = TRUE, last_modified = %s WHERE id = ANY(%s)",
                (now_ts, ids)
            )
        conn.commit()
        print("  ✓ Record allineati a soft-deleted con successo.")

    # 3. Bonifica orfani duri (hard orphans)
    if "hard_orphans" in orphan_map:
        now_ts = datetime.now(timezone.utc)
        for item in orphan_map["hard_orphans"]:
            t = item["table"]
            ids = item["ids"]
            print(f"[+] Disattivazione / Soft-delete record orfani in '{t}' ({len(ids)} record)...")
            if has_column(cur, t, "is_deleted"):
                cur.execute(
                    f"UPDATE {t} SET is_deleted = TRUE, last_modified = %s WHERE id = ANY(%s)",
                    (now_ts, ids)
                )
            else:
                cur.execute(f"DELETE FROM {t} WHERE id = ANY(%s)", (ids,))
        conn.commit()
        print("  ✓ Record orfani neutralizzati con successo.")

    print("\n🎉 BONIFICA COMPLETATA CON SUCCESSO! Ora puoi effettuare 'Sincronizza tutto' dal Desktop.")


def main():
    parser = argparse.ArgumentParser(description="Verifica e bonifica record orfani database PostgreSQL STM")
    parser.add_argument("--fix", action="store_true", help="Esegue la riparazione e bonifica automatica delle anomalie")
    parser.add_argument("--host", help="Host PostgreSQL (default da .env DB_HOST)")
    parser.add_argument("--port", help="Porta PostgreSQL (default da .env DB_PORT o 5432)")
    parser.add_argument("--dbname", help="Nome database (default da .env DB_NAME)")
    parser.add_argument("--user", help="Utente database (default da .env DB_USER)")
    parser.add_argument("--password", help="Password database (default da .env DB_PASSWORD)")

    args = parser.parse_args()
    load_environment()

    db_host = args.host or os.getenv("DB_HOST", "localhost")
    db_port = args.port or os.getenv("DB_PORT", "5432")
    db_name = args.dbname or os.getenv("DB_NAME", "safety_test_db")
    db_user = args.user or os.getenv("DB_USER", "postgres")
    db_password = args.password or os.getenv("DB_PASSWORD", "")

    print(f"[*] Connessione a PostgreSQL su {db_host}:{db_port}, database='{db_name}', user='{db_user}'...")
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
            connect_timeout=10
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        print("[+] Connessione stabilita con successo.\n")
    except Exception as e:
        print(f"\n❌ ERRORE DI CONNESSIONE AL DATABASE POSTGRESQL: {e}")
        print("Verifica i parametri di connessione in .env o passa gli argomenti da riga di comando.")
        sys.exit(1)

    try:
        total_issues, orphan_map = run_diagnostic(cur)

        if total_issues > 0 and args.fix:
            confirm = input("Vuoi procedere con la bonifica automatica di queste anomalie? [s/N]: ").strip().lower()
            if confirm in ("s", "si", "y", "yes"):
                repair_database(conn, cur, orphan_map)
            else:
                print("Operazione di bonifica annullata.")
        elif total_issues > 0 and not args.fix:
            print("💡 Suggerimento: Per riparare automaticamente le anomalie trovate, esegui:")
            print("   python check_orphan_records.py --fix\n")

    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
