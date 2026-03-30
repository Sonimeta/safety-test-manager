"""
Dialog per la scansione QR/Barcode da telefono per trovare dispositivi.
Permette di scansionare codici contenenti:
- Numero inventario AMS
- Numero di serie
- Numero inventario cliente
"""

import logging
import socket
import threading
import json
from urllib.parse import parse_qs
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage

import qtawesome as qta

from app import config

# Flag per dipendenze opzionali
QRCODE_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    logging.warning("qrcode non installato per QR device scanner")


class QRScannerHTTPHandler(BaseHTTPRequestHandler):
    """Handler HTTP per ricevere scansioni QR dal telefono."""
    
    scan_callback = None
    last_result = None
    
    def log_message(self, format, *args):
        """Disabilita logging HTTP standard."""
        pass
    
    def _send_cors_headers(self):
        """Invia headers CORS."""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def do_OPTIONS(self):
        """Gestisce preflight CORS."""
        try:
            self.send_response(200)
            self._send_cors_headers()
            self.end_headers()
        except:
            pass
    
    def do_GET(self):
        """Serve la pagina web o i file PWA."""
        try:
            if self.path == '/last':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                payload = QRScannerHTTPHandler.last_result or {}
                self.wfile.write(json.dumps(payload).encode('utf-8'))
                return

            # --- ALLEGATI: lista allegati per una verifica ---
            if self.path.startswith('/attachments/'):
                self._handle_get_attachments()
                return

            # --- ALLEGATI: scarica singolo allegato ---
            if self.path.startswith('/attachment/') and not self.path.startswith('/attachment/upload'):
                self._handle_download_attachment()
                return

            # --- VERIFICHE: cerca per codice verifica ---
            if self.path.startswith('/verifications/search'):
                self._handle_search_verification()
                return

            # --- VERIFICHE: lista recenti per un dispositivo ---
            if self.path.startswith('/verifications/recent'):
                self._handle_recent_verifications()
                return

            if self.path == '/manifest.json':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                manifest = {
                    "name": "Scanner Verifiche",
                    "short_name": "Scanner",
                    "start_url": "/",
                    "display": "standalone",
                    "background_color": "#121212",
                    "theme_color": "#4CAF50",
                    "icons": [
                        {
                            "src": "https://cdn-icons-png.flaticon.com/512/2435/2435281.png",
                            "sizes": "512x512",
                            "type": "image/png"
                        }
                    ]
                }
                self.wfile.write(json.dumps(manifest).encode('utf-8'))
                return

            if self.path == '/sw.js':
                self.send_response(200)
                self.send_header('Content-type', 'application/javascript')
                self._send_cors_headers()
                self.end_headers()
                sw = '''
                self.addEventListener('install', (e) => {
                    self.skipWaiting();
                });
                self.addEventListener('fetch', (e) => {
                    e.respondWith(fetch(e.request));
                });
                '''
                self.wfile.write(sw.encode('utf-8'))
                return

            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self._send_cors_headers()
            self.end_headers()
            
            html = self._get_scanner_html()
            self.wfile.write(html.encode('utf-8'))
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
    
    def do_POST(self):
        """Riceve i dati della scansione QR, immagine da decodificare, o allegato."""
        try:
            # --- ALLEGATI: upload allegato ---
            if self.path == '/attachment/upload':
                self._handle_upload_attachment()
                return

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)

            content_type = (self.headers.get('Content-Type') or '').lower()
            raw_text = post_data.decode('utf-8', errors='replace')

            def _escape_control_chars(text: str) -> str:
                return ''.join(
                    ch if ord(ch) >= 32 else '\\u%04x' % ord(ch)
                    for ch in text
                )

            data = {}
            try:
                if 'application/json' in content_type or raw_text.strip().startswith('{'):
                    try:
                        data = json.loads(raw_text)
                    except json.JSONDecodeError:
                        data = json.loads(_escape_control_chars(raw_text))
            except Exception:
                data = {}

            if not data:
                if 'application/x-www-form-urlencoded' in content_type or '=' in raw_text:
                    parsed = parse_qs(raw_text, keep_blank_values=True)
                    data = {k: (v[0] if v else '') for k, v in parsed.items()}
                else:
                    data = {"code": raw_text}

            # Check if it's a direct code or an image to decode
            scan_result = data.get('code', '') or ''
            image_data = data.get('image', '') or ''

            scan_result = self._sanitize_scan_code(scan_result)
            
            if image_data and not scan_result:
                # Decode barcode from image on server side
                scan_result = self._decode_barcode_from_image(image_data)
            
            logging.info(f"[QR Scanner] Ricevuto codice: {scan_result}")
            
            if scan_result:
                # Chiama il callback
                logging.info(f"[QR Scanner] Callback disponibile: {QRScannerHTTPHandler.scan_callback is not None}")
                if QRScannerHTTPHandler.scan_callback:
                    logging.info(f"[QR Scanner] Chiamata callback con: {scan_result}")
                    QRScannerHTTPHandler.scan_callback(scan_result)
                    logging.info(f"[QR Scanner] Callback completata")
                else:
                    logging.warning("[QR Scanner] Nessun callback configurato!")
                
                # Risposta di successo
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok', 'code': scan_result}).encode('utf-8'))
            else:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'not_found', 'message': 'Nessun codice trovato'}).encode('utf-8'))
            
        except Exception as e:
            logging.error(f"Errore ricezione scansione: {e}")
            try:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
            except:
                pass

    def _sanitize_scan_code(self, code: str) -> str:
        """Normalizza il codice ricevuto per evitare caratteri di controllo."""
        if not code:
            return ''
        # GS (ASCII 29) da DataMatrix -> separatore visibile
        code = code.replace(chr(29), '|')
        # Rimuovi altri caratteri di controllo non stampabili
        code = ''.join(ch for ch in code if ch >= ' ' or ch in '\n\r\t')
        return code.strip()
    
    def _decode_barcode_from_image(self, image_data_base64: str) -> str:
        """Decodifica barcode da immagine base64 usando pylibdmtx e pyzbar."""
        try:
            # Rimuovi header data URL se presente
            if ',' in image_data_base64:
                image_data_base64 = image_data_base64.split(',')[1]
            
            # Decodifica base64
            image_bytes = base64.b64decode(image_data_base64)
            
            # Carica immagine con PIL
            from PIL import Image, ImageEnhance
            from io import BytesIO
            image = Image.open(BytesIO(image_bytes))
            
            # Correggi orientamento EXIF se necessario
            try:
                from PIL import ExifTags
                exif = image._getexif()
                if exif:
                    for tag, value in exif.items():
                        if ExifTags.TAGS.get(tag) == 'Orientation':
                            if value == 3:
                                image = image.rotate(180, expand=True)
                            elif value == 6:
                                image = image.rotate(270, expand=True)
                            elif value == 8:
                                image = image.rotate(90, expand=True)
                            break
            except:
                pass
            
            gray_image = image.convert('L')
            code = None
            
            # ============ PROVA CON PYLIBDMTX (DataMatrix) ============
            try:
                from pylibdmtx.pylibdmtx import decode as dmtx_decode
                logging.info("[QR Scanner] Provo con pylibdmtx...")
                
                # Ridimensiona per velocizzare (max 800px)
                max_size = 800
                w, h = gray_image.size
                if w > max_size or h > max_size:
                    ratio = min(max_size / w, max_size / h)
                    work_image = gray_image.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
                    logging.info(f"[QR Scanner] Immagine ridimensionata per dmtx")
                else:
                    work_image = gray_image
                
                timeout_ms = 2000  # 2 secondi max
                
                # Tentativo 1: Immagine grigia
                try:
                    results = dmtx_decode(work_image, timeout=timeout_ms)
                    if results:
                        code = results[0].data.decode('utf-8', errors='ignore')
                        logging.info(f"[QR Scanner] DataMatrix trovato: {code}")
                        return code
                except Exception as e:
                    logging.debug(f"[QR Scanner] dmtx errore 1: {e}")
                
                # Tentativo 2: Contrasto
                try:
                    enhancer = ImageEnhance.Contrast(work_image)
                    contrast = enhancer.enhance(2.0)
                    results = dmtx_decode(contrast, timeout=timeout_ms)
                    if results:
                        code = results[0].data.decode('utf-8', errors='ignore')
                        logging.info(f"[QR Scanner] DataMatrix (contrasto): {code}")
                        return code
                except Exception as e:
                    logging.debug(f"[QR Scanner] dmtx errore 2: {e}")
                        
            except ImportError:
                logging.debug("pylibdmtx non disponibile")
            
            # ============ PROVA CON PYZBAR (QR, Code128, etc.) ============
            try:
                from pyzbar import pyzbar
                logging.info("[QR Scanner] Provo con pyzbar...")
                
                barcodes = pyzbar.decode(image)
                if not barcodes:
                    barcodes = pyzbar.decode(gray_image)
                if not barcodes:
                    enhancer = ImageEnhance.Contrast(gray_image)
                    barcodes = pyzbar.decode(enhancer.enhance(2.0))
                
                if barcodes:
                    code = barcodes[0].data.decode('utf-8', errors='ignore')
                    logging.info(f"[QR Scanner] pyzbar trovato: {code}")
                    return code
                    
            except ImportError:
                logging.debug("pyzbar non disponibile")
            
            logging.info("[QR Scanner] Nessun barcode trovato")
            return ''
            
        except Exception as e:
            logging.error(f"Errore decodifica barcode: {e}")
            return ''

    # ==================================================================
    # GESTIONE ALLEGATI (Attachment endpoints)
    # ==================================================================

    def _handle_upload_attachment(self):
        """Gestisce l'upload di un allegato scannerizzato dal telefono."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 20 * 1024 * 1024:  # Max 20MB
                self._send_json_response(413, {'status': 'error', 'message': 'File troppo grande (max 20MB)'})
                return

            post_data = self.rfile.read(content_length)
            content_type = (self.headers.get('Content-Type') or '').lower()

            if 'application/json' in content_type:
                # JSON con immagine base64
                data = json.loads(post_data.decode('utf-8', errors='replace'))
                verification_code = data.get('verification_code', '')
                verification_id = data.get('verification_id', 0)
                description = data.get('description', '')
                filename = data.get('filename', 'scan.jpg')
                image_b64 = data.get('image_data', '')

                if not image_b64:
                    self._send_json_response(400, {'status': 'error', 'message': 'Nessuna immagine fornita'})
                    return

                # Rimuovi header data URL se presente
                if ',' in image_b64 and image_b64.startswith('data:'):
                    image_b64 = image_b64.split(',', 1)[1]

                file_data = base64.b64decode(image_b64)
                mime_type = data.get('mime_type', 'image/jpeg')
            else:
                self._send_json_response(400, {'status': 'error', 'message': 'Content-Type non supportato'})
                return

            # Risolvi la verifica se abbiamo solo il codice
            if not verification_id and verification_code:
                import database
                verif = database.get_functional_verification_by_code(verification_code)
                if verif:
                    verification_id = verif['id']

            if not verification_id:
                self._send_json_response(404, {
                    'status': 'error',
                    'message': 'Verifica non trovata. Specifica verification_id o verification_code valido.'
                })
                return

            # Salva nel database
            import database
            att_id = database.save_verification_attachment(
                verification_id=verification_id,
                filename=filename,
                file_data=file_data,
                mime_type=mime_type,
                description=description,
                verification_type='functional',
            )

            self._send_json_response(200, {
                'status': 'ok',
                'message': 'Allegato salvato con successo',
                'attachment_id': att_id,
                'verification_id': verification_id,
            })
            logging.info(f"[Allegato] Upload completato: id={att_id}, verifica={verification_id}, file={filename}")

        except Exception as e:
            logging.error(f"[Allegato] Errore upload: {e}", exc_info=True)
            self._send_json_response(500, {'status': 'error', 'message': str(e)})

    def _handle_get_attachments(self):
        """Restituisce la lista degli allegati per una verifica (senza dati binari)."""
        try:
            # Path: /attachments/<verification_id>
            parts = self.path.strip('/').split('/')
            if len(parts) < 2:
                self._send_json_response(400, {'status': 'error', 'message': 'verification_id mancante'})
                return
            verification_id = int(parts[1])

            import database
            attachments = database.get_verification_attachments(verification_id, 'functional')

            self._send_json_response(200, {
                'status': 'ok',
                'verification_id': verification_id,
                'count': len(attachments),
                'attachments': attachments,
            })
        except Exception as e:
            logging.error(f"[Allegato] Errore lista: {e}", exc_info=True)
            self._send_json_response(500, {'status': 'error', 'message': str(e)})

    def _handle_download_attachment(self):
        """Scarica un singolo allegato (dati binari)."""
        try:
            # Path: /attachment/<id>
            parts = self.path.strip('/').split('/')
            if len(parts) < 2:
                self._send_json_response(400, {'status': 'error', 'message': 'attachment_id mancante'})
                return
            attachment_id = int(parts[1])

            import database
            att = database.get_attachment_data(attachment_id)
            if not att:
                self._send_json_response(404, {'status': 'error', 'message': 'Allegato non trovato'})
                return

            if not att.get('file_data'):
                self._send_json_response(404, {'status': 'error', 'message': 'File allegato non trovato su disco'})
                return

            self.send_response(200)
            self.send_header('Content-type', att['mime_type'])
            self.send_header('Content-Length', str(len(att['file_data'])))
            self.send_header('Content-Disposition', f'inline; filename="{att["filename"]}"')
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(att['file_data'])

        except Exception as e:
            logging.error(f"[Allegato] Errore download: {e}", exc_info=True)
            self._send_json_response(500, {'status': 'error', 'message': str(e)})

    def _handle_search_verification(self):
        """Cerca una verifica funzionale per codice o UUID."""
        try:
            from urllib.parse import urlparse, parse_qs as url_parse_qs
            parsed = urlparse(self.path)
            params = url_parse_qs(parsed.query)
            code = (params.get('code', [''])[0]).strip()

            if not code:
                self._send_json_response(400, {'status': 'error', 'message': 'Parametro code mancante'})
                return

            import database
            verif = database.get_functional_verification_by_code(code)
            if not verif:
                # Prova anche come UUID
                verif = database.get_functional_verification_by_uuid(code)

            if verif:
                # Conta allegati
                att_count = database.get_attachments_count(verif['id'], 'functional')
                self._send_json_response(200, {
                    'status': 'ok',
                    'found': True,
                    'verification': {
                        'id': verif['id'],
                        'uuid': verif['uuid'],
                        'verification_code': verif.get('verification_code', ''),
                        'verification_date': verif.get('verification_date', ''),
                        'profile_key': verif.get('profile_key', ''),
                        'overall_status': verif.get('overall_status', ''),
                        'technician_name': verif.get('technician_name', ''),
                        'notes': verif.get('notes', ''),
                        'attachments_count': att_count,
                    },
                })
            else:
                self._send_json_response(200, {'status': 'ok', 'found': False})
        except Exception as e:
            logging.error(f"[Verifica] Errore ricerca: {e}", exc_info=True)
            self._send_json_response(500, {'status': 'error', 'message': str(e)})

    def _handle_recent_verifications(self):
        """Restituisce le verifiche funzionali recenti (ultime 20)."""
        try:
            from urllib.parse import urlparse, parse_qs as url_parse_qs
            parsed = urlparse(self.path)
            params = url_parse_qs(parsed.query)
            device_id = params.get('device_id', [''])[0]

            import database
            if device_id:
                verifications = database.get_functional_verifications_for_device(int(device_id))
            else:
                # Ultime 20 verifiche
                from datetime import datetime as dt, timedelta
                end_date = dt.now().strftime('%Y-%m-%d')
                start_date = (dt.now() - timedelta(days=90)).strftime('%Y-%m-%d')
                verifications = database.get_functional_verifications_by_date_range(start_date, end_date)

            result = []
            for v in (verifications or [])[:20]:
                v_dict = dict(v) if not isinstance(v, dict) else v
                att_count = database.get_attachments_count(v_dict['id'], 'functional')
                result.append({
                    'id': v_dict['id'],
                    'uuid': v_dict.get('uuid', ''),
                    'verification_code': v_dict.get('verification_code', ''),
                    'verification_date': v_dict.get('verification_date', ''),
                    'profile_key': v_dict.get('profile_key', ''),
                    'overall_status': v_dict.get('overall_status', ''),
                    'technician_name': v_dict.get('technician_name', ''),
                    'attachments_count': att_count,
                })

            self._send_json_response(200, {
                'status': 'ok',
                'count': len(result),
                'verifications': result,
            })
        except Exception as e:
            logging.error(f"[Verifica] Errore lista recenti: {e}", exc_info=True)
            self._send_json_response(500, {'status': 'error', 'message': str(e)})

    def _send_json_response(self, status_code: int, data: dict):
        """Helper per inviare risposte JSON."""
        try:
            self.send_response(status_code)
            self.send_header('Content-type', 'application/json')
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(data, default=str).encode('utf-8'))
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
    
    def _get_scanner_html(self):
        """Restituisce la pagina HTML per lo scanner QR (modalità foto, decodifica server-side)."""
        return '''<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Scanner Dispositivo</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#4CAF50">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black">
    <script>
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js');
        }
    </script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
            color: white;
        }
        h1 { font-size: 1.5em; margin-bottom: 10px; text-align: center; }
        .subtitle { font-size: 0.9em; color: #aaa; margin-bottom: 20px; text-align: center; }
        
        .scan-btn {
            width: 100%;
            max-width: 350px;
            padding: 20px 30px;
            font-size: 1.2em;
            font-weight: bold;
            color: white;
            background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
            border: none;
            border-radius: 15px;
            cursor: pointer;
            margin: 10px 0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            box-shadow: 0 4px 15px rgba(76, 175, 80, 0.4);
        }
        .scan-btn:active { transform: scale(0.98); }
        
        #fileInput { display: none; }
        
        #preview {
            width: 100%;
            max-width: 350px;
            margin: 15px 0;
            border-radius: 10px;
            display: none;
        }
        
        #result {
            margin-top: 15px;
            padding: 15px 20px;
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            text-align: center;
            width: 100%;
            max-width: 350px;
            min-height: 50px;
        }
        #result.success { background: rgba(76, 175, 80, 0.3); border: 2px solid #4CAF50; }
        #result.error { background: rgba(244, 67, 54, 0.3); border: 2px solid #f44336; }
        #result.processing { background: rgba(255, 193, 7, 0.3); border: 2px solid #FFC107; }
        
        .code-display { font-family: monospace; font-size: 1.1em; word-break: break-all; }
        
        .manual-input {
            margin-top: 25px;
            width: 100%;
            max-width: 350px;
            padding-top: 20px;
            border-top: 1px solid rgba(255,255,255,0.2);
        }
        .manual-input label {
            display: block;
            margin-bottom: 10px;
            color: #aaa;
            font-size: 0.9em;
        }
        .manual-input input {
            width: 100%;
            padding: 15px;
            font-size: 1.1em;
            border: 2px solid #444;
            border-radius: 10px;
            background: rgba(255,255,255,0.1);
            color: white;
            margin-bottom: 10px;
        }
        .manual-input input::placeholder { color: #666; }
        .manual-input button {
            width: 100%;
            padding: 15px;
            font-size: 1em;
            background: linear-gradient(135deg, #FF9800 0%, #F57C00 100%);
            border: none;
            border-radius: 10px;
            color: white;
            cursor: pointer;
            font-weight: bold;
        }
        
        .instructions {
            margin-top: 20px;
            padding: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            font-size: 0.8em;
            color: #aaa;
            max-width: 350px;
        }
    </style>
</head>
<body>
    <h1>📱 Scanner Dispositivo</h1>
    <p class="subtitle">Scatta una foto del barcode/QR code</p>
    
    <input type="file" id="fileInput" accept="image/*" capture="environment">
    
    <button class="scan-btn" onclick="document.getElementById('fileInput').click()">
        📷 Scatta Foto Barcode
    </button>
    
    <img id="preview" alt="Anteprima">
    
    <div id="result">
        <span>📸 Scatta una foto del codice...</span>
    </div>
    
    <div class="manual-input">
        <label>Oppure inserisci manualmente:</label>
        <input type="text" id="manualCode" placeholder="Numero serie / Inventario...">
        <button onclick="sendManualCode()">📤 Invia Codice</button>
    </div>
    
    <div class="instructions">
        <b>💡 Suggerimenti:</b><br>
        • Inquadra bene il barcode/QR<br>
        • Assicurati che sia ben illuminato<br>
        • Evita riflessi e ombre<br>
        • La foto viene analizzata sul PC
    </div>

    <script>
        const fileInput = document.getElementById('fileInput');
        const preview = document.getElementById('preview');
        const resultDiv = document.getElementById('result');
        
        fileInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            // Mostra anteprima
            preview.src = URL.createObjectURL(file);
            preview.style.display = 'block';
            
            resultDiv.className = 'processing';
            resultDiv.innerHTML = '⏳ Invio immagine al PC...';
            
            try {
                // Converti in base64 e invia al server
                const base64 = await fileToBase64(file);
                
                resultDiv.innerHTML = '🔍 Analisi barcode...';
                
                const response = await fetch(window.location.href, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: base64 })
                });
                
                const data = await response.json();
                
                if (data.status === 'ok' && data.code) {
                    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
                    resultDiv.className = 'success';
                    resultDiv.innerHTML = '✅ <span class="code-display">' + data.code + '</span>';
                } else {
                    resultDiv.className = 'error';
                    resultDiv.innerHTML = '❌ Nessun codice trovato.<br>Riprova o inserisci manualmente.';
                }
            } catch (err) {
                console.error(err);
                resultDiv.className = 'error';
                resultDiv.innerHTML = '❌ Errore: ' + err.message;
            }
            
            fileInput.value = '';
        });
        
        function fileToBase64(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result);
                reader.onerror = reject;
                reader.readAsDataURL(file);
            });
        }
        
        function sendManualCode() {
            const code = document.getElementById('manualCode').value.trim();
            if (!code) return;
            
            if (navigator.vibrate) navigator.vibrate(100);
            resultDiv.className = 'processing';
            resultDiv.innerHTML = '📤 Invio...';
            
            fetch(window.location.href, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code })
            })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'ok') {
                    resultDiv.className = 'success';
                    resultDiv.innerHTML = '✅ <span class="code-display">' + code + '</span>';
                    document.getElementById('manualCode').value = '';
                } else {
                    resultDiv.className = 'error';
                    resultDiv.innerHTML = '❌ Errore invio';
                }
            })
            .catch(err => {
                resultDiv.className = 'error';
                resultDiv.innerHTML = '❌ Errore: ' + err.message;
            });
        }
        
        document.getElementById('manualCode').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendManualCode();
        });
    </script>
</body>
</html>'''


class ThreadedQRServer(ThreadingMixIn, HTTPServer):
    """Server HTTP multi-threaded per scansione QR."""
    daemon_threads = True
    allow_reuse_address = True


class QRDeviceScannerDialog(QDialog):
    """Dialog per scansione QR dispositivi da telefono - modalità ascolto continuo."""
    
    # Segnale per ricezione codice thread-safe
    _code_received_signal = Signal(str)
    
    # Segnale per notificare la main window di cercare un dispositivo
    device_scan_requested = Signal(str)
    
    def __init__(self, parent=None, continuous_mode=True, external_server=False):
        super().__init__(parent)
        self.setWindowTitle("📱 Scanner QR Dispositivo")
        self.setMinimumSize(550, 650)
        self.resize(600, 700)
        self.setStyleSheet(config.get_current_stylesheet())
        
        self.server = None
        self.server_thread = None
        self.running = False
        self.scanned_code = None
        self.continuous_mode = continuous_mode
        self.external_server = external_server  # Se True, il server è gestito esternamente
        self.scan_history = []  # Storico scansioni
        
        self._setup_ui()
        
        # Connetti segnale per thread-safety
        self._code_received_signal.connect(self._on_code_received)
        
        # Avvia il server solo se non è gestito esternamente
        if not external_server:
            QTimer.singleShot(100, self._start_server)
    
    def _setup_ui(self):
        """Configura l'interfaccia."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Header
        header = QLabel("📱 Scanner QR Dispositivo - Ascolto Continuo")
        header.setStyleSheet("font-size: 14pt; font-weight: bold;")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        # Istruzioni
        instructions = QLabel(
            "🔄 Il server rimane in ascolto. Scansiona più codici in sequenza!"
        )
        instructions.setStyleSheet("color: #4CAF50; font-size: 10pt; font-weight: bold;")
        instructions.setAlignment(Qt.AlignCenter)
        layout.addWidget(instructions)
        
        # Layout orizzontale: QR a sinistra, storico a destra
        content_layout = QHBoxLayout()
        
        # QR Code container (sinistra)
        self.qr_group = QGroupBox("📷 QR Code Connessione")
        qr_layout = QVBoxLayout(self.qr_group)
        qr_layout.setContentsMargins(10, 10, 10, 10)
        
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setMinimumSize(220, 220)
        self.qr_label.setStyleSheet("background: white; border: 1px solid #ccc; padding: 5px;")
        qr_layout.addWidget(self.qr_label)
        
        self.url_label = QLabel()
        self.url_label.setStyleSheet("font-family: monospace; font-size: 9pt; color: #0066cc;")
        self.url_label.setAlignment(Qt.AlignCenter)
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.url_label.setWordWrap(True)
        qr_layout.addWidget(self.url_label)
        
        self.qr_group.setMinimumWidth(250)
        content_layout.addWidget(self.qr_group)
        
        # Storico scansioni (destra)
        history_group = QGroupBox("📋 Ultime Scansioni")
        history_layout = QVBoxLayout(history_group)
        
        from PySide6.QtWidgets import QListWidget
        self.history_list = QListWidget()
        self.history_list.setStyleSheet("font-family: monospace; font-size: 10pt;")
        self.history_list.setMaximumHeight(180)
        self.history_list.itemDoubleClicked.connect(self._on_history_item_clicked)
        history_layout.addWidget(self.history_list)
        
        content_layout.addWidget(history_group)
        
        layout.addLayout(content_layout)
        
        # Status con animazione
        self.status_label = QLabel("⏳ Avvio server...")
        self.status_label.setStyleSheet("""
            font-size: 12pt; 
            padding: 10px; 
            background: #e3f2fd;
            border-radius: 8px;
            border: 2px solid #2196F3;
        """)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Ultimo codice ricevuto (grande e visibile)
        self.code_group = QGroupBox("🎯 Ultimo Codice Scansionato")
        code_layout = QVBoxLayout(self.code_group)
        
        self.code_label = QLabel("In attesa di scansione...")
        self.code_label.setStyleSheet("""
            font-family: monospace; 
            font-size: 16pt; 
            font-weight: bold;
            padding: 20px; 
            background: #f5f5f5; 
            border-radius: 8px;
            min-height: 60px;
        """)
        self.code_label.setAlignment(Qt.AlignCenter)
        self.code_label.setWordWrap(True)
        code_layout.addWidget(self.code_label)
        
        # Risultato ricerca
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("font-size: 11pt; padding: 5px;")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setWordWrap(True)
        code_layout.addWidget(self.result_label)
        
        layout.addWidget(self.code_group)
        
        # Contatore scansioni
        self.counter_label = QLabel("Scansioni: 0")
        self.counter_label.setStyleSheet("font-size: 10pt; color: #666;")
        self.counter_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.counter_label)
        
        # Pulsanti
        btn_layout = QHBoxLayout()
        
        clear_btn = QPushButton(qta.icon('fa5s.trash'), " Pulisci Storico")
        clear_btn.setObjectName("editButton")
        clear_btn.setMinimumHeight(35)
        clear_btn.clicked.connect(self._clear_history)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton(qta.icon('fa5s.times'), " Chiudi Scanner")
        close_btn.setObjectName("deleteButton")
        close_btn.setMinimumHeight(35)
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def _get_local_ip(self):
        """Ottiene l'IP locale."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def _start_server(self):
        """Avvia il server HTTP."""
        try:
            ip = self._get_local_ip()
            port = 8766  # Porta diversa da OCR
            
            # Imposta callback
            QRScannerHTTPHandler.scan_callback = self._on_code_received_threadsafe
            
            # Crea server
            self.server = ThreadedQRServer(("0.0.0.0", port), QRScannerHTTPHandler)
            self.running = True
            
            # Avvia in thread
            self.server_thread = threading.Thread(target=self._serve_forever, daemon=True)
            self.server_thread.start()
            
            # Genera QR
            url = f"https://{ip}:{port}"
            self._show_qr_code(url)
            
            self.status_label.setText("✅ Server attivo - Scansiona il QR con il telefono")
            self.status_label.setStyleSheet("font-size: 12pt; padding: 10px; color: #4CAF50;")
            
            logging.info(f"[QR Scanner] Server avviato su {url}")
            
        except Exception as e:
            logging.error(f"Errore avvio server QR: {e}")
            self.status_label.setText(f"❌ Errore: {str(e)}")
            self.status_label.setStyleSheet("font-size: 12pt; padding: 10px; color: #f44336;")
    
    def _serve_forever(self):
        """Loop del server."""
        while self.running:
            try:
                self.server.handle_request()
            except:
                pass
    
    def _stop_server(self):
        """Ferma il server."""
        self.running = False
        if self.server:
            try:
                self.server.socket.close()
            except:
                pass
            self.server = None
    
    def _show_qr_code(self, url: str):
        """Mostra il QR code."""
        if not QRCODE_AVAILABLE:
            self.qr_label.setText("qrcode non installato\n\nApri manualmente:\n" + url)
            self.url_label.setText(url)
            return
        
        try:
            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Converti in QPixmap
            from io import BytesIO
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            
            qimg = QImage()
            qimg.loadFromData(buffer.getvalue())
            pixmap = QPixmap.fromImage(qimg)
            
            # Scala il QR code per adattarlo al label
            scaled_pixmap = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.qr_label.setPixmap(scaled_pixmap)
            self.url_label.setText(url)
            
        except Exception as e:
            logging.error(f"Errore generazione QR: {e}")
            self.qr_label.setText(f"Errore QR\n\nApri: {url}")
    
    def _on_code_received_threadsafe(self, code: str):
        """Callback thread-safe per codice ricevuto."""
        self._code_received_signal.emit(code)
    
    def _on_code_received(self, code: str):
        """Gestisce il codice ricevuto (thread principale) - modalità continua."""
        import datetime
        
        self.scanned_code = code
        
        # Aggiorna UI
        self.code_label.setText(code)
        self.code_label.setStyleSheet("""
            font-family: monospace; 
            font-size: 16pt; 
            font-weight: bold;
            padding: 20px; 
            background: #e8f5e9; 
            border: 3px solid #4CAF50; 
            border-radius: 8px;
            min-height: 60px;
        """)
        
        # Aggiungi allo storico
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        history_entry = f"[{timestamp}] {code}"
        self.scan_history.insert(0, {'code': code, 'time': timestamp})
        self.history_list.insertItem(0, history_entry)
        
        # Limita storico a 20 elementi
        while self.history_list.count() > 20:
            self.history_list.takeItem(self.history_list.count() - 1)
        
        # Aggiorna contatore
        self.counter_label.setText(f"Scansioni: {len(self.scan_history)}")
        
        # Status
        self.status_label.setText("🔍 Ricerca dispositivo in corso...")
        self.status_label.setStyleSheet("""
            font-size: 12pt; 
            padding: 10px; 
            background: #fff3e0;
            border-radius: 8px;
            border: 2px solid #FF9800;
        """)
        
        self.result_label.setText("⏳ Ricerca...")
        
        # Emetti segnale per la ricerca (la main window gestirà la ricerca)
        self.device_scan_requested.emit(code)
    
    def show_search_result(self, found: bool, device_info: str = ""):
        """Mostra il risultato della ricerca."""
        if found:
            self.result_label.setText(f"✅ TROVATO: {device_info}")
            self.result_label.setStyleSheet("font-size: 11pt; padding: 5px; color: #4CAF50; font-weight: bold;")
            self.status_label.setText("✅ Dispositivo trovato e selezionato! Pronto per nuova scansione...")
            self.status_label.setStyleSheet("""
                font-size: 12pt; 
                padding: 10px; 
                background: #e8f5e9;
                border-radius: 8px;
                border: 2px solid #4CAF50;
            """)
        else:
            self.result_label.setText(f"❌ Non trovato: {device_info}")
            self.result_label.setStyleSheet("font-size: 11pt; padding: 5px; color: #f44336; font-weight: bold;")
            self.status_label.setText("❌ Dispositivo non trovato. Riprova o scansiona altro codice...")
            self.status_label.setStyleSheet("""
                font-size: 12pt; 
                padding: 10px; 
                background: #ffebee;
                border-radius: 8px;
                border: 2px solid #f44336;
            """)
    
    def _on_history_item_clicked(self, item):
        """Rieffettua la ricerca per un elemento dello storico."""
        text = item.text()
        # Estrai il codice dal formato "[HH:MM:SS] codice"
        if '] ' in text:
            code = text.split('] ', 1)[1]
            self.device_scan_requested.emit(code)
    
    def _clear_history(self):
        """Pulisce lo storico."""
        self.scan_history.clear()
        self.history_list.clear()
        self.counter_label.setText("Scansioni: 0")
        self.code_label.setText("In attesa di scansione...")
        self.code_label.setStyleSheet("""
            font-family: monospace; 
            font-size: 16pt; 
            font-weight: bold;
            padding: 20px; 
            background: #f5f5f5; 
            border-radius: 8px;
            min-height: 60px;
        """)
        self.result_label.setText("")
    
    def get_scanned_code(self):
        """Restituisce il codice scansionato."""
        return self.scanned_code
    
    def closeEvent(self, event):
        """Gestisce la chiusura del dialog."""
        # Ferma il server solo se non è gestito esternamente
        if not self.external_server:
            self._stop_server()
        super().closeEvent(event)
    
    def reject(self):
        """Override reject."""
        # Ferma il server solo se non è gestito esternamente
        if not self.external_server:
            self._stop_server()
        super().reject()
    
    def accept(self):
        """Override accept."""
        # Ferma il server solo se non è gestito esternamente
        if not self.external_server:
            self._stop_server()
        super().accept()
