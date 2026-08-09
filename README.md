# fega-schmitt-mcp

> **Status: Konzeptphase.** Dieses Repository enthält aktuell nur Dokumentation (README + Architekturbeschreibung + Original-Spezifikationen). Es ist noch kein Code implementiert.

Ein geplanter [MCP](https://modelcontextprotocol.io)-Server, der KI-Assistenten (z. B. Claude) lesenden Zugriff auf Daten der **FEGA & Schmitt Elektrogroßhandel** Schnittstellen gibt — in erster Linie Preis- und Verfügbarkeitsabfragen für Artikel.

## Über FEGA & Schmitt

FEGA & Schmitt ist ein deutscher Elektrogroßhändler. Kunden erhalten Zugriff auf mehrere, technisch sehr unterschiedliche B2B-Schnittstellen zum Datenaustausch mit ihrer Warenwirtschaft/Handwerkersoftware. Details siehe [docs/architecture.md](docs/architecture.md).

## Schnittstellen im Überblick

| Schnittstelle | Typ | Zweck | Eignung für MCP v1 |
|---|---|---|---|
| **SOAP Preis-/Verfügbarkeitsservice** | Synchrones SOAP/XML über HTTPS | Preis & Verfügbarkeit für bis zu 1000 Artikel je Anfrage | ✅ Basis für v1 — einzige echte Request/Response-API |
| **IDS-Schnittstelle** (BVBS/ITEK-Branchenstandard, v2.5) | Browser-Redirect + Hook-URL, halbautomatisch | Warenkorb-Austausch, Artikelsuche, Artikel-Deeplinks, Heizungslabel (ErP) | ⚠️ Später — erfordert Browser-Interaktion, kein reines API-Muster |
| **UGL Version 4** (SHK-Branchenstandard) | Datei-basiert (FTP/Portal), ASCII Fixed-Length | Anfragen, Abrufaufträge, Auftragsbestätigungen als Batch-Dateien | ⚠️ Später — Batch/Polling statt Live-Antwort |

Die vollständigen Original-Spezifikationen liegen als PDF in [docs/specs/](docs/specs/):

- `Schnittstellenbeschreibung_SOAP.pdf` — Preis-/Verfügbarkeits-Webservice (FEGA & Schmitt, Stand März 2016)
- `IDS_Schnittstelle_2_5_final_NEU.pdf` — IDS-Schnittstelle für Warenkorb/Artikelsuche/Heizlabel (BVBS/ITEK, Version 2.5, Stand 02.11.2020)
- `ugl4neutral.pdf` — UGL Version 4, Datenaustausch Handwerk ↔ SHK-Großhandel (GC-Gruppe, Stand 16.06.2006)

## Geplanter Funktionsumfang (v1)

Ein MCP-Tool zur Preis-/Verfügbarkeitsabfrage, das intern den SOAP-Webservice unter `https://soap.fega.de/priceavail.php` anspricht:

- Eingabe: Liste von Artikelnummern (FEGA & Schmitt-Artikelnummer) mit Menge und optionaler Mengeneinheit
- Ausgabe je Artikel: Verfügbarkeitsstatus (voll verfügbar / Teilmenge / nicht verfügbar / Beschaffung), Nettopreis, Listenpreis, Zu-/Abschläge, Lagerzuordnung
- Fehlerfälle (unbekannte Artikelnummer, ungültige Mengeneinheit, Mengenüberlauf) werden je Position gemeldet, ohne die gesamte Anfrage abzubrechen

Details zu Datenfluss, Fehlerbehandlung und Architektur: siehe [docs/architecture.md](docs/architecture.md).

## Offene Punkte

Diese Punkte sind vor der Implementierung mit FEGA & Schmitt bzw. dem Auftraggeber zu klären:

- Test-/Produktivzugangsdaten für den SOAP-Service (Kundennummer, Shop-Kennwort, ggf. abweichende Firmennummer)
- Ob und in welcher Form FEGA & Schmitt die IDS-Schnittstelle über den eigenen Webshop anbietet, inkl. der referenzierten XSD-Schemas (`Warenkorb_senden.xsd`, `Warenkorb_empfangen_2-5.xsd`, `heatinglabel_*.xsd` — in der vorliegenden PDF nicht enthalten)
- Ob UGL4 für dieses Projekt relevant ist, und falls ja: FTP-Zugangsdaten/Verzeichnis
- Zielumgebung des MCP-Servers (lokal per stdio, oder als gehosteter Dienst?)

## Lizenz

MIT, siehe [LICENSE](LICENSE).
