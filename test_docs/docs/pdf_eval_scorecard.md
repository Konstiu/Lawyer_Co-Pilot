# PDF Hard Test Scorecard

## Ziel
Systematisch messen, wie stabil `Extraction`, `Rule Review` und `Q&A` auf großen, realen PDFs funktionieren.

## 1) Test-Setup
- Nutze mindestens 3 große Vertrags-PDFs mit unterschiedlicher Struktur (MSA, DPA/AVV, SLA, Anhang).
- Führe jeden Testlauf mindestens 3-mal aus (gleiche Inputs), um Stabilität zu sehen.
- Halte Modell/Provider konstant pro Durchlauf (OpenAI oder Ollama nicht mischen).

## 2) Extraction-Bewertung
- Input: `pdf_hard_extraction_fields.txt`
- Pro Feld und Dokument erfassen:
  - `status` korrekt? (`found`, `uncertain`, `not_specified`)
  - `value` fachlich korrekt?
  - `quote` tatsächlich stützend und präzise?
  - `page/location_hint` plausibel?

Bewertung pro Zelle:
- 2 Punkte: korrekt + belastbare Quelle
- 1 Punkt: teilweise korrekt / unpräzise Quelle
- 0 Punkte: falsch oder halluziniert

## 3) Rule-Review-Bewertung
- Input: `pdf_hard_review_rules.txt`
- Pro Regel und Dokument prüfen:
  - richtige Klasse (`ok`, `deviation`, `missing`)
  - Begründung juristisch konsistent?
  - Quelle ausreichend konkret?

Bewertung pro Finding:
- 2 Punkte: richtige Klasse + tragfähige Begründung
- 1 Punkt: richtige Tendenz, aber schwache Begründung/Quelle
- 0 Punkte: falsche Klassifikation

## 4) Q&A-Bewertung
- Input: `pdf_hard_qa_questions.txt`
- Prüfen:
  - Frage direkt beantwortet?
  - Nur claims mit Quellen?
  - Mehrdokument-Fragen korrekt zusammengeführt?
  - Bei Lücken explizit "nicht aus Passagen ableitbar"?

Bewertung pro Frage:
- 2 Punkte: präzise, knapp, quellengestützt
- 1 Punkt: teilweise korrekt / zu allgemein
- 0 Punkte: falsch, ohne Quelle, halluziniert

## 5) Ampellogik
- Grün: >= 85% Gesamtpunkte
- Gelb: 70–84%
- Rot: < 70%

## 6) Typische Fehlermuster (notieren)
- `missing` statt `deviation` bei implizitem Widerspruch
- falscher Seitenbezug bei langen PDFs
- Zitat enthält nicht den behaupteten Wert
- Vermischung von Hauptvertrag und Annex ohne Rangfolgeprüfung
