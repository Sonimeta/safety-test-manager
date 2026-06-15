Profili elettrici alternativi (CEI EN 62353)

File creati:
- cei62353_alt_classe_i_b_bf_ve.json
- cei62353_alt_classe_i_cf_ve.json
- cei62353_alt_classe_ii_b_bf_ve.json
- cei62353_alt_classe_ii_cf_ve.json

Formato JSON:
- Struttura compatibile con il modello profili elettrici storico (`{ profile_key: { name, tests[] } }`)
- Ogni test usa i nomi supportati dal software:
  - `Resistenza conduttore di terra`
  - `Corrente dispersione diretta dispositivo`
  - `Corrente dispersione diretta P.A.`

Riferimenti norma usati (estratti dal PDF allegato):
- Tabella 2 (resistenza isolamento, solo riferimento informativo)
- Correnti Allegato A (valori riscontrati nell'estratto testo):
  - Classe I: contatto 500 µA; paziente B/BF 500 µA; paziente CF 50 µA
  - Classe II: contatto 100 µA; paziente B/BF 100 µA; paziente CF 10 µA

Nota importante:
- Il software esegue attualmente prove con nomi/metodi strumento già implementati.
- Questi profili sono pronti per importazione come profili elettrici "alternativi" e per uso operativo,
  ma i limiti vanno sempre validati internamente dal tuo responsabile tecnico/normativo prima dell'adozione ufficiale.
