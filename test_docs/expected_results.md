# Erwartete Resultate für den Schnelltest

## 1) Extraction (Erwartung grob)

| Feld | vertrag_1_saas_msa | vertrag_2_it_services | vertrag_3_nda |
|---|---|---|---|
| Kündigungsfrist ordentlich | found (90 Tage) | found (30 Tage) | not_specified |
| Vertragslaufzeit initial | found (24 Monate) | found (12 Monate) | not_specified |
| Zahlungsziel (Tage) | found (30) | found (14) | not_specified |
| Haftungsobergrenze | found (200% Jahresvergütung) | found (50% total fees) | not_specified |
| Anwendbares Recht | found (Deutschland) | found (Österreich) | found (Schweiz) |
| Gerichtsstand | found (München) | found (Wien) | not_specified |
| SLA Verfügbarkeit | not_specified | found (98.0%) | not_specified |
| AVV erwähnt | found (ja) | not_specified / uncertain | not_specified |

## 2) Rule Review (Erwartung grob)

| Regel | vertrag_1_saas_msa | vertrag_2_it_services | vertrag_3_nda |
|---|---|---|---|
| Kündigung >= 90 Tage | ok | deviation | missing |
| Zahlungsziel >= 30 Tage | ok | deviation | missing |
| Haftung <= 100% Jahresvergütung | deviation (200%) | ok (50%) | missing |
| Deutsches Recht | ok | deviation | deviation |
| Gerichtsstand München | ok | deviation | missing |
| AVV muss vorgesehen sein | ok | missing / deviation | missing |
| SLA >= 99.5% | missing | deviation (98.0%) | missing |

## 3) Q&A (Erwartung)
- Antworten sollen kurz sein und konkrete Quellenzitate enthalten.
- Bei nicht vorhandener Information muss die Antwort das explizit sagen.
- Für Vergleichsfragen über mehrere Dokumente sollten mehrere Quellen genannt werden.

## Hinweise
- Einzelne Zellen können je nach Modell zwischen `missing` und `deviation` bzw. `not_specified` und `uncertain` schwanken.
- Für robuste Bewertung: mindestens 5 Laufwiederholungen und Abweichungen pro Feld/Regel notieren.
