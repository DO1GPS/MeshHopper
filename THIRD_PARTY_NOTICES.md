# MeshHopper Quellen und Fremdsoftware

MeshHopper verwendet das MeshCore-Protokoll und externe Python-Bibliotheken.
Dieses Quellpaket enthält keine mitkopierten Bibliotheks- oder Firmwareordner.
Die eigenen MeshHopper-Beiträge stehen unter der MIT-Lizenz,
Copyright (c) 2026 DO1GPS; der vollständige Text liegt in `LICENSE`.
Fremdsoftware und übernommene Bestandteile behalten ihre eigenen Lizenzen
und Copyrightvermerke.

## MeshCore Firmware

Die Paket- und Empfangsimplementierung beschreibt das Firmwareprofil
`1.17.1-d929643`. Die bestehenden Quellenhinweise bleiben in den Dateien
`group_sender.py`, `reception_evidence.py` und `report_engine.py` erhalten.
Sie beziehen sich insbesondere auf:

- [BaseChatMesh.cpp](https://github.com/meshcore-dev/MeshCore/blob/d929643/src/helpers/BaseChatMesh.cpp#L442)
- [Utils.cpp](https://github.com/meshcore-dev/MeshCore/blob/d929643/src/Utils.cpp#L117)
- [MyMesh.cpp](https://github.com/meshcore-dev/MeshCore/blob/d929643/examples/companion_radio/MyMesh.cpp#L266)

Das [Firmwareprojekt am genannten Stand](https://github.com/meshcore-dev/MeshCore/tree/d929643)
nennt MIT als Lizenz. Protokollquellen und Autorenhinweise nicht entfernen.
Diese Hinweise behaupten weder eine vollständig unabhängige Neuimplementierung
noch eine nachgewiesene wörtliche Codeübernahme.

## Python Bibliotheken

| Bibliothek | Verwendete Version | Lizenz und Quelle |
| --- | --- | --- |
| meshcore | 2.3.14 | [MIT](https://github.com/meshcore-dev/meshcore_py/blob/main/LICENSE) |
| bleak | 3.0.2 | [MIT](https://github.com/hbldh/bleak/blob/v3.0.2/LICENSE) |
| pycryptodome | 3.23.0 | [Public-Domain- und BSD-2-Clause-Anteile](https://github.com/Legrandin/pycryptodome/blob/v3.23.0/LICENSE.rst) |
| pycayennelpp | 2.4.0 | [Paketbeschreibung und MIT-Hinweis](https://pypi.org/project/pycayennelpp/2.4.0/) |
| pyserial-asyncio-fast | 0.16 | [Paketbeschreibung und BSD-3-Clause-Hinweis](https://pypi.org/project/pyserial-asyncio-fast/0.16/) |
| pyserial | 3.5 | [BSD-Lizenz](https://github.com/pyserial/pyserial/blob/v3.5/LICENSE.txt) |

Die Bibliotheken werden bei Bedarf über den Paketmanager installiert; ihre
Lizenzen bleiben eigenständig maßgeblich. Plattformabhängige Zusatzpakete
bringen weitere eigene Hinweise mit.

Wer später Fremdsoftware oder übernommene Fremdtexte in einem Paket mitliefert,
muss die jeweils erforderlichen vollständigen Lizenz- und Copyrighttexte
beilegen. Diese Übersicht ersetzt sie nicht.
