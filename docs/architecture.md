# Architektur

> v1 implementiert (Preis-/Verfügbarkeitsabfrage über `get_price_availability`).

## 1. Zuschnitt dieses Repos

`fega-schmitt-mcp` ist bewusst dünn gehalten: Es kennt das MCP-Protokoll (Tools, Schemas, stdio-Transport) und übersetzt Tool-Aufrufe in Aufrufe der Library [`fega-schmitt-client`](../../../Python/fega-schmitt-client). Alles, was FEGA & Schmitt-Protokolldetails betrifft (SOAP, Auth, XML, Returncodes, Datenmodell), lebt dort — siehe [dessen Architekturbeschreibung](../../../Python/fega-schmitt-client/docs/architecture.md).

```mermaid
graph TD
    subgraph Host["MCP-Host-Prozess"]
        Client["MCP-Client<br/>(Claude Desktop / Claude Code / ...)"]
    end

    subgraph Server["fega-schmitt-mcp — Server-Prozess"]
        Transport["stdio-Transport<br/>(JSON-RPC, MCP-Protokoll)"]
        Tool["Tool-Layer<br/>get_price_availability(...)"]
        Config["Konfiguration<br/>(Env-Variablen, keine Secrets im Code)"]
    end

    subgraph Lib["fega-schmitt-client (separates PyPI-Paket)"]
        FC["FegaSchmittClient"]
    end

    API["FEGA & Schmitt<br/>SOAP-Preis-/Verfügbarkeitsservice"]

    Client -->|stdio, JSON-RPC| Transport
    Transport --> Tool
    Config -.->|Kundennummer, Kennwort| Tool
    Tool -->|Python-Funktionsaufruf| FC
    FC -->|SOAP/HTTPS| API

    style Server fill:#2b6cb0,color:#fff
    style Lib fill:#2f855a,color:#fff
```

Der Server ist zustandslos: jeder Tool-Aufruf entspricht 1:1 einem Aufruf der Library. Es wird kein lokaler Datenbestand gehalten (keine Artikelstammdaten, kein Preis-Cache in v1).

## 2. Ablauf `get_price_availability` (Tool-Sicht)

```mermaid
sequenceDiagram
    participant Host as MCP-Host
    participant Server as fega-schmitt-mcp
    participant Lib as fega-schmitt-client
    participant API as FEGA & Schmitt

    Host->>Server: tools/call get_price_availability(items)
    Server->>Server: Tool-Input validieren (MCP-Schema)
    Server->>Lib: FegaSchmittClient(...).get_price_availability(items)
    Lib->>API: SOAP-Request (siehe fega-schmitt-client Architektur)
    API-->>Lib: SOAP-Response
    Lib-->>Server: list[PriceAvailResultItem]
    Server->>Server: in MCP-Tool-Result serialisieren
    Server-->>Host: strukturiertes Ergebnis (JSON)
```

Die eigentliche Request-/Response-Logik, das Fehler-/Returncode-Mapping und das Datenmodell sind in der [Architekturbeschreibung von `fega-schmitt-client`](../../../Python/fega-schmitt-client/docs/architecture.md) dokumentiert (Abschnitte 3–5) und werden hier nicht dupliziert.

## 3. Aufgabe dieses Repos im Detail

- **MCP-Tool-Definition**: Name, Beschreibung, Input-/Output-Schema für `get_price_availability` (und perspektivisch weitere Tools)
- **Konfiguration/Secrets**: Einlesen von Zugangsdaten (Kundennummer, Shop-Kennwort) aus Umgebungsvariablen oder MCP-Client-Konfiguration und Weiterreichen an `FegaSchmittClient` — die Library selbst liest keine Umgebungsvariablen (siehe deren Architektur, Abschnitt 6)
- **Fehler-Serialisierung**: Exceptions aus `fega-schmitt-client` (`FegaTransportError`, `FegaAuthError`) in MCP-konforme Fehlerantworten übersetzen; Positions-Fehler (`status = "error"` je Artikel) werden als Teil des normalen Tool-Ergebnisses zurückgegeben, nicht als MCP-Fehler
- **Kein** eigenes SOAP-/XML-Handling, keine eigene Kopie der FEGA & Schmitt-Spezifikationen (siehe [`fega-schmitt-client`/docs/specs/](../../../Python/fega-schmitt-client/docs/specs/))

## 4. Technologiewahl

- **MCP-Framework:** FastMCP (`mcp[cli]`, offizielles Python-SDK)
- **Paketverwaltung:** `uv`, Linting/Formatting mit `ruff`
- **Abhängigkeit:** `fega-schmitt-client` als reguläre PyPI-Dependency (kein Vendoring, kein Git-Submodule); während der lokalen Entwicklung per `[tool.uv.sources]`-Pfad-Override auf den Checkout unter `GIT/Python/fega-schmitt-client` umgeleitet, im Release-Workflow entfernt
- **Tests:** `pytest`, mit einem gemockten `FegaSchmittClient` (`_build_client` wird gepatcht), damit Server-Tests keine echte SOAP-Verbindung benötigen
- **Veröffentlichung:** PyPI, via Trusted Publishing (GitHub Actions)

## 5. Warum IDS und UGL4 hier ohnehin kein Thema sind

Beide Schnittstellen sind kein Request/Response-Muster (Browser-Redirect-Flow bzw. Batch-Datei-Austausch, siehe [`fega-schmitt-client`/docs/architecture.md](../../../Python/fega-schmitt-client/docs/architecture.md), Abschnitt 7). Sollten sie später als Erweiterung der Library folgen, würde dieses Repo lediglich ein weiteres, dünnes Tool ergänzen, das die dann in `fega-schmitt-client.ids` / `fega-schmitt-client.ugl4` liegende Funktion aufruft — die architektonische Rolle dieses Repos (dünner MCP-Wrapper, keine Protokolllogik) ändert sich dadurch nicht.

## 6. Offene Fragen

Siehe README, Abschnitt "Offene Punkte".
