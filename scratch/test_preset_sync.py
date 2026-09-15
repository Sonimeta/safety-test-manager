import os
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-chars-long-123456789"
import json
import sys
from unittest.mock import MagicMock
import unittest.mock as mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock psycopg2 connection on module import so it doesn't block waiting for postgres
import psycopg2
psycopg2.connect = MagicMock()

import database
from app import services
from app import sync_manager
import real_server

def test_preset_sync_mechanism():
    print("Testing preset sync mechanism...")
    
    # 1. Verify real_server configuration
    assert "applied_parts_presets" in real_server.BOOL_FIELDS_BY_TABLE
    assert "applied_parts_presets" in real_server.SyncChanges.model_fields
    print("[OK] real_server models and boolean columns include applied_parts_presets")

    # 2. Verify sync_manager configuration
    assert "applied_parts_presets" in sync_manager.SYNC_ORDER
    print("[OK] sync_manager SYNC_ORDER includes applied_parts_presets")

    # 3. Create a local preset and verify _get_local_changes collects it
    preset_name = "Sync Test Monitor Preset"
    preset_parts = [
        {"name": "ECG TORACE", "part_type": "CF"},
        {"name": "SPO2 DITO", "part_type": "BF"}
    ]
    preset_id = services.save_applied_parts_preset(name=preset_name, parts=preset_parts, description="Test sync preset")
    assert preset_id > 0
    
    # Check that is_synced == 0
    with database.DatabaseConnection() as conn:
        row = conn.execute("SELECT * FROM applied_parts_presets WHERE id = ?", (preset_id,)).fetchone()
        assert row is not None
        assert row['is_synced'] == 0
        preset_uuid = row['uuid']
        print(f"[OK] Preset created with UUID {preset_uuid} and is_synced = 0")

    # Collect local changes using SyncManager helper
    local_changes = sync_manager._get_unsynced_local_changes()
    assert "applied_parts_presets" in local_changes
    found_preset = any(p['uuid'] == preset_uuid for p in local_changes["applied_parts_presets"])
    assert found_preset, "Created preset was not found in local changes!"
    print(f"[OK] sync_manager._get_unsynced_local_changes successfully collected preset: {len(local_changes['applied_parts_presets'])} presets ready to push")

    # 4. Test applying server changes locally via _apply_server_changes_batch
    server_preset_uuid = "test-server-preset-uuid-12345"
    server_changes = {
        "applied_parts_presets": [
            {
                "uuid": server_preset_uuid,
                "name": "Server Synced Defibrillator",
                "description": "Preset from server",
                "parts_json": json.dumps([{"name": "PIASTRE", "part_type": "BF"}, {"name": "ECG", "part_type": "CF"}]),
                "last_modified": "2026-08-31T09:00:00+00:00",
                "is_deleted": 0,
                "is_synced": 1
            }
        ]
    }
    
    with database.DatabaseConnection() as conn:
        counts, conflicts = sync_manager._apply_server_changes(conn, server_changes)
        print("Batch apply counts:", counts)
        assert counts.get("applied_parts_presets", 0) >= 1

    # Verify that server preset is in local database
    with database.DatabaseConnection() as conn:
        server_row = conn.execute("SELECT * FROM applied_parts_presets WHERE uuid = ?", (server_preset_uuid,)).fetchone()
        assert server_row is not None
        assert server_row['name'] == "Server Synced Defibrillator"
        assert server_row['is_synced'] == 1
        print("[OK] Server preset successfully applied to local SQLite database with is_synced = 1")

    # 5. Clean up test records
    services.delete_applied_parts_preset(preset_id)
    with database.DatabaseConnection() as conn:
        conn.execute("DELETE FROM applied_parts_presets WHERE uuid IN (?, ?)", (preset_uuid, server_preset_uuid))

    print("\nALL PRESET SYNC TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_preset_sync_mechanism()
