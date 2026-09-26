# Dés PF1

La page `index.html` est le lanceur humain. Elle n'est pas un outil que ChatGPT peut appeler.

`mcp_server.py` est le serveur MCP. Son seul outil est `roll`.

```json
{"formula":"1d20+16","id":"AZULA-ATT1"}
```

Réponse : `expr`, `bruts`, `total`, `line`.

ChatGPT n'est pas connecté par ce dépôt. Le mode développeur n'accepte qu'une adresse HTTPS publique (SSE ou HTTP streamable), pas une page GitHub. Ce fichier écoute seulement sur 127.0.0.1 tant qu'il n'est pas hébergé.
