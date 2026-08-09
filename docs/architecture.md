# Architektur

> Entwurfsstand — es existiert noch keine Implementierung. Dieses Dokument beschreibt die geplante Architektur auf Basis der drei vorliegenden FEGA & Schmitt/Branchen-Spezifikationen in [`specs/`](specs/).

## 1. Kontext

FEGA & Schmitt stellt Kunden (Handwerksbetriebe, deren Warenwirtschaftssysteme) drei technisch unabhängige Schnittstellen zur Verfügung. Sie unterscheiden sich stark in Protokoll, Interaktionsmuster und Automatisierbarkeit:

| | SOAP Preis-/Verfügbarkeit | IDS-Schnittstelle | UGL Version 4 |
|---|---|---|---|
| Quelle | FEGA & Schmitt-eigene Doku | BVBS/ITEK-Branchenstandard, v2.5 | GC-Gruppe-Branchenstandard (SHK) |
| Protokoll | SOAP 1.1 / XML über HTTPS POST | HTTP-Formular-POST (`multipart/form-data`) an eine Shop-URL, Rückkanal über "Hook-URL" | Flatfile (ASCII, feste Satzlänge 200 Byte) über FTP oder Webportal-Verzeichnis |
| Interaktionsmuster | Synchron, zustandslos, Server-zu-Server | Öffnet ein Browserfenster im GH-Shop; Nutzer agiert dort manuell; Shop schickt Ergebnis per Formular-POST an die Hook-URL zurück ("halbautomatisch") | Asynchron/Batch: Datei ablegen, später Antwortdatei abholen |
| Auth | Kundennummer + Shop-Kennwort im XML-Body je Anfrage | Kundennummer/Benutzername/Passwort als POST-Parameter beim Öffnen des Shops | Vermutlich FTP-Zugangsdaten (nicht in den ersten Seiten der Spec spezifiziert) |
| Für MCP geeignet? | **Ja** — klassischer Request/Response-API-Aufruf | **Bedingt** — benötigt Browser-Kontext bzw. Nachbau der Shop-Formularlogik, kein reines API-Muster | **Bedingt** — benötigt Scheduler/Polling, kein Live-Request |

**Konsequenz für den Zuschnitt:** v1 dieses MCP-Servers deckt ausschließlich den SOAP-Preis-/Verfügbarkeitsservice ab. IDS und UGL4 werden in Abschnitt 7 als mögliche spätere Erweiterungen skizziert, aber bewusst nicht in v1 implementiert.

## 2. Komponentenübersicht (v1)

```
MCP-Client (Claude Desktop / Claude Code / anderer MCP-Host)
    │  stdio, JSON-RPC (MCP-Protokoll)
    ▼
fega-schmitt-mcp — Server-Prozess
    │
    ├── Tool-Layer (MCP-Tools)
    │     └── get_price_availability(items, shipment_type?, warehouse?,
    │                                 postal_code?, country_code?, currency?)
    │
    ├── FegaPriceAvailClient
    │     ├── Request-Builder:  Items → PRICE_AVAIL_REQUEST-XML (SOAP-Envelope)
    │     ├── Transport:        HTTPS POST → https://soap.fega.de/priceavail.php
    │     └── Response-Parser:  SOAP/XML → strukturierte Ergebnisliste
    │
    └── Konfiguration (Umgebungsvariablen, keine Secrets im Code)
          ├── FEGA_PARTNER_PURCHASER   (Kundennummer, PARTNER_PURCHASER)
          ├── FEGA_LEGITIMATION_ID     (Shop-Kennwort, LEGITIMATION_ID)
          ├── FEGA_PARTNER_COMPANY     (Firmennummer, default "50")
          └── FEGA_ESHOP_ID            (optional, eigene Lieferanten-ID)
```

Der Server ist zustandslos: jede Tool-Aufruf entspricht 1:1 einer SOAP-Anfrage. Es wird kein lokaler Datenbestand gehalten (keine Artikelstammdaten, kein Preis-Cache in v1).

## 3. Ablauf `get_price_availability`

1. MCP-Client ruft das Tool mit einer Liste von `{material_number, quantity, unit?}` auf (max. 1000 Positionen laut Spezifikation, siehe [`specs/Schnittstellenbeschreibung_SOAP.pdf`](specs/Schnittstellenbeschreibung_SOAP.pdf), Abschnitt "Allgemeiner Ablauf").
2. Der Request-Builder erzeugt eine `PRICE_AVAIL_REQUEST`-Nachricht:
   - `PREFIX`: Firmennummer ("50"), Kundennummer, Shop-Kennwort, eine pro Aufruf generierte `TRANSACTION_ID`
   - `HEADER`: Versandart (Lieferung/Abholung), Zielwährung ("EUR"), optional PLZ/Länderkennzeichen für lieferabhängige Verfügbarkeit
   - `ITEM_LIST`: eine `ITEM`-Position je angefragtem Artikel, mit fortlaufender `LINE_ITEM_NUMBER` zur Zuordnung der Antwort
3. HTTPS-POST des SOAP-Envelopes an `https://soap.fega.de/priceavail.php`.
4. Response-Parser liest `PRICE_AVAIL_RESPONSE` und mappt jede `ITEM`-Position zurück auf die ursprüngliche Anfrageposition (über `LINE_ITEM_NUMBER`).
5. Das Tool gibt pro Position ein strukturiertes Ergebnis zurück (siehe Abschnitt 5) und aggregiert Fehler/Hinweise, statt bei einem einzelnen fehlerhaften Artikel die gesamte Anfrage abzubrechen — das entspricht dem Verhalten der Schnittstelle selbst (Returncode ist je Position, nicht global).

## 4. Fehler- und Hinweisbehandlung (Returncodes)

Aus [`specs/Schnittstellenbeschreibung_SOAP.pdf`](specs/Schnittstellenbeschreibung_SOAP.pdf), Abschnitt 4:

| Prefix | Bedeutung | Verhalten im MCP-Tool |
|---|---|---|
| `I…` (z. B. `I720`) | Erfolgreiche Ermittlung | Position wird als Erfolg zurückgegeben |
| `H…` (z. B. `H014`, Abholverzögerung) | Erfolgreich, aber mit Hinweis | Position wird als Erfolg zurückgegeben, `hint`-Feld gesetzt |
| `E…` (z. B. `E999`: unbekannte Artikelnummer, unbekannter ISO-Mengeneinheitscode, Mengenüberlauf) | Fehler bei dieser Position | Position wird als Fehler markiert (`error`-Feld mit `RETURNCODE_TEXT`), übrige Positionen bleiben unberührt |

Der `RETURNCODE_TEXT` wird unverändert durchgereicht, da er laut Spezifikation für die Anzeige beim Endnutzer vorgesehen ist.

## 5. Datenmodell (geplant)

```
PriceAvailRequestItem
  material_number: str        # FEGA & Schmitt-Artikelnummer, Pflicht
  quantity: Decimal            # Pflicht
  unit: str | None             # ISO-Code, z. B. "PCE", "MTR"; optional

PriceAvailResultItem
  line_item_number: int
  material_number: str
  status: "ok" | "hint" | "error"
  return_code: str
  return_code_text: str
  availability_status: "V" | "T" | "N" | "B" | "0" | None   # voll/teilw./nicht verfügbar/Beschaffung/keine Aussage
  warehouse_number: str | None
  warehouse_name: str | None
  price_amount: Decimal | None      # Nettowert vor Zu-/Abschlägen
  net_amount: Decimal | None        # Nettowert inkl. Zu-/Abschläge, vor Steuer
  list_amount: Decimal | None       # Listenpreis
  surcharges: list[Surcharge]       # z. B. Kupfer-/Metallzuschlag

Surcharge
  code: str
  text: str
  amount: Decimal
```

Die Felder orientieren sich 1:1 an der XML-Struktur aus der Spezifikation (Abschnitt 3.3 "Nachrichtenaufbau Antwort"), um verlustfrei zu bleiben.

## 6. Sicherheit & Credential-Handling

- Kundennummer und Shop-Kennwort werden ausschließlich über Umgebungsvariablen/Secret-Storage injiziert, nie im Code oder in Logs.
- Die Schnittstelle verlangt HTTPS (`https://soap.fega.de/...`); Klartext-HTTP wird nicht unterstützt und nicht implementiert.
- Da jede Anfrage Kundennummer + Kennwort im Klartext-XML-Body enthält, sind Request-Logs standardmäßig zu maskieren (Kennwort nie mitloggen).
- Keine Persistierung von Preisdaten in v1 — jede Abfrage ist eine Live-Abfrage. Ein optionaler kurzlebiger In-Memory-Cache (TTL im Minutenbereich) ist als spätere Optimierung denkbar, aber wegen tagesaktueller Preise (siehe `SURCHARGE_REBATE_AMOUNT`-Hinweis "wertmäßig akt. Tagespreisen") mit Vorsicht zu dosieren.

## 7. Bewusst nicht in v1 abgedeckt

### 7.1 IDS-Schnittstelle (BVBS/ITEK, v2.5)

Beschrieben in [`specs/IDS_Schnittstelle_2_5_final_NEU.pdf`](specs/IDS_Schnittstelle_2_5_final_NEU.pdf). Diese Schnittstelle ist ein **Branchenstandard**, kein FEGA & Schmitt-spezifisches Protokoll — ob und wie FEGA & Schmitt ihn im eigenen Webshop implementiert, ist ungeklärt (offener Punkt, siehe README).

Warum nicht v1:

- Das Muster ist "Browserfenster öffnen → Nutzer agiert im Shop (Blackbox) → Shop postet Ergebnis an Hook-URL". Das ist für eine headless MCP-Tool-Aufruf-Semantik ungeeignet, ohne entweder (a) einen echten Nutzer im Loop zu haben oder (b) eine Headless-Browser-Automatisierung zu bauen, die die individuelle FEGA & Schmitt-Shopoberfläche nachbildet.
- Referenzierte XSD-Schemas (`Warenkorb_senden.xsd`, `Warenkorb_empfangen_2-5.xsd`, `heatinglabel_senden.xsd`, `heatinglabel_empfangen.xsd`) liegen der vorliegenden PDF nicht bei.
- Für Anwendungsfälle wie "Warenkorb senden" oder "Artikelsuche" wäre eher eine spätere, separate Automatisierungskomponente (z. B. Playwright-basiert) sinnvoll — architektonisch klar getrennt vom stdio-MCP-Server, z. B. als eigenständiger Dienst, der vom MCP-Tool nur angestoßen wird.

### 7.2 UGL Version 4

Beschrieben in [`specs/ugl4neutral.pdf`](specs/ugl4neutral.pdf). Ebenfalls ein **Branchenstandard** (SHK-Großhandel/GC-Gruppe), keine FEGA & Schmitt-spezifische Erfindung.

Warum nicht v1:

- Datenaustausch erfolgt batchweise als Datei (feste Satzlänge, 200 Byte/Satz) über FTP oder ein Portalverzeichnis — kein synchrones Request/Response.
- Ein MCP-Tool bräuchte entweder Polling ("Antwortdatei liegt vor?") oder einen Hintergrund-Job, der Dateien abholt und zwischenspeichert — ein grundsätzlich anderes Betriebsmodell als der stdio-basierte MCP-Server.
- Zugangsdaten/Verzeichnisstruktur beim FEGA & Schmitt-FTP sind nicht bekannt (offener Punkt).

Falls IDS oder UGL4 später gebraucht werden, sollten sie als **separate Komponenten/Prozesse** entstehen, die eigene Betriebslogik (Browser-Automatisierung bzw. FTP-Scheduler) kapseln und dem MCP-Server nur ein einfaches, synchrones Tool-Interface anbieten — nicht als direkte Erweiterung des SOAP-Clients.

## 8. Technologiewahl (Vorschlag, noch nicht festgelegt)

Konsistent mit den übrigen MCP-Servern in diesem Workspace (`vnbdigital-mcp`, `holy-moly-mcp`, u. a.):

- **Sprache/Tooling:** Python, verwaltet mit `uv`, Linting/Formatting mit `ruff`
- **MCP-Framework:** FastMCP (oder offizielles `mcp`-Python-SDK)
- **SOAP/XML:** leichtgewichtiges XML-Templating (`lxml`/`xml.etree`) statt eines vollen WSDL-getriebenen SOAP-Stacks wie `zeep` — die Schnittstelle ist klein, statisch und ohne WSDL-Dokument in der Spec referenziert
- **HTTP-Transport:** `httpx`
- **Tests:** `pytest`, mit den Beispiel-Request/-Response-Paaren aus dem Anhang der SOAP-Spezifikation als Fixtures

Diese Wahl ist ein Vorschlag und noch mit dem Auftraggeber abzustimmen, bevor Code entsteht.

## 9. Offene Fragen

Siehe README, Abschnitt "Offene Punkte".
