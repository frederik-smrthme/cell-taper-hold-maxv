# Venus Cell Taper

**Version: 0.2.0**

Experimenteller Spannungsregler für **eine** Marstek Venus E mit Omnibattery in Home Assistant.

## Installation

1. Lade dieses Repository in ein eigenes öffentliches GitHub-Repository hoch.
2. HACS → Drei Punkte → Benutzerdefinierte Repositories → URL deines Repositories → **Integration**.
3. Installieren und Home Assistant neu starten.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → **Venus Cell Taper**.
5. Die sieben Entitäten **derselben** Batterie auswählen. Es werden keine Zugangsdaten benötigt.
6. Unter Einstellungen → Geräte & Dienste → Venus Cell Taper → **Konfigurieren** sind alle sieben ausgewählten Entitäten sichtbar und änderbar. Dort lässt sich auch die Mindestleistung ändern (10 bis 50 W in 10-W-Schritten, Vorgabe 40 W). Die angezeigten Werte stammen aus der Ersteinrichtung bzw. der letzten Änderung.

Ohne GitHub lässt sich `custom_components/venus_cell_taper` auch direkt in das gleichnamige Verzeichnis unter Home Assistants `config/custom_components` kopieren; danach neu starten.

## Bedienung

1. **Battery Manual Mode** in Omnibattery selbst einschalten. Dieser Schalter wird von der Integration niemals betätigt.
2. Den neuen Schalter **Venus Cell Taper – Spannungsregelung** einschalten.
3. Zum Beenden diesen Schalter ausschalten. Er setzt `Force Mode` auf `None`; Omnibatterys manueller Modus bleibt eingeschaltet.

Der Regler startet nur bei verfügbarem `Vmax` unter 3,52 V und eingeschaltetem manuellem Modus. Startleistung: 500 W unter 3,45 V; 200 W bis 3,48 V; sonst 50 W. Alle 10 Sekunden wird die Zellspannung gelesen. Nach einer Änderung werden mindestens 30 Sekunden Einschwingzeit gewährt. In der Spannungsflanke reduzieren ein Spannungsfehler gegenüber 3,48 V und ein gefilterter Anstieg die Leistung; je nach Abweichung um eine bis drei Stufen pro Schritt. Stufen: 100 W oberhalb 200 W, 50 W bis 50 W, danach 10 W bis zur **konfigurierten Mindestleistung**. Vorgabe 40 W; dabei wurden an dieser Batterie 8–11 W DC gemessen. 30 W kann über die Integrationsoptionen für Versuche gewählt werden. Unter 50 W kann nach 90 Sekunden mit fallender Spannung wieder um 10 W bis maximal 50 W erhöht werden.

Bei `Vmax ≥ 3,55 V`, bei **3,52 V trotz bereits erreichter Mindestleistung**, fehlendem oder länger als 90 Sekunden nicht aktualisiertem Spannungssensor oder ausgeschaltetem manuellem Modus stoppt die Integration und setzt, **sofern der manuelle Modus noch eingeschaltet ist**, `Force Mode` auf `None`. Gleiches gilt, wenn `Force Mode` nicht mehr `Charge` ist, die DC-Leistung fehlt oder nach dem Start drei Prüfungen hintereinander höchstens 2 W DC gemeldet werden. Bei jedem Befehl wird der zurückgelesene Entitätswert bis zu fünf Sekunden lang kontrolliert; ein nicht bestätigter Schreibvorgang führt zum Stopp. Der Statussensor zeigt dann die zugeordnete Entität, Soll und Rückmeldung. Vor dem Start wird geprüft, ob die angegebene Entity existiert und ob ihr angezeigter Maximalwert die Startleistung zulässt. Falls `Force Mode → None` nicht bestätigt wird, versucht die Integration ersatzweise `0 W` Ladesollwert und meldet den Fehler im Statussensor. Der Spannungsstopp reagiert auf Zustandsänderungen des HA-Sensors; seine Geschwindigkeit hängt daher vom Mess- und Aktualisierungsintervall von Omnibattery ab. Der BMS-Schutz der Batterie bleibt maßgeblich. Bei HA-Neustart bleibt der Regler aus und startet nicht automatisch erneut.

Änderungen an den Optionen laden die Integration neu. Ein laufender Ladevorgang wird dabei gestoppt und muss bewusst neu gestartet werden.

Die Statusentität zeigt `Vmax`, `Vmin`, AC- und DC-Leistung sowie den letzten Sollwert als Attribute. Die DC-Leistung wird überwacht, damit der Regler bei ausbleibender Ladung stoppt; sie bestimmt noch nicht die Höhe des Sollwerts. Bei kleinen AC-Sollwerten kann die DC-Ladung gegen null gehen.

**Vor dem ersten Versuch:** Prüfe, ob der Force-Mode-Schalter tatsächlich die Optionen `None` und `Charge` anbietet. Ein 40-W-Sollwert wurde über `number.set_value` angenommen und ergab 8–11 W DC. Bei einem abgewiesenen Schreibbefehl stoppt der Regler; der Status zeigt den Fehler. Die Integration selbst wurde noch nicht an einer realen Venus E getestet.

## GitHub-Veröffentlichung

Dieses Projekt liegt unter `https://github.com/frederik-smrthme/cell-taper-hold-maxv`. Für HACS nutze die Repository-URL als benutzerdefiniertes Repository vom Typ **Integration**. Eine GitHub-Release ist optional.
