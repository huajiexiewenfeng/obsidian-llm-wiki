The doctor reports risk category, file path, line number, and repair hint. It never prints secret values in text or JSON output.

# Safety Rules

- Report the risk category, file path, line number, and repair hint when available.
- Never copy secret values, matched source lines, tokens, passwords, cookies, private keys, credentialed URLs, or connection strings into chat.
- Treat `sensitive-pattern` as a cleanup signal, not as permission to expose the underlying value.
- If the user asks for exact secret content, refuse that part and offer a safe path-and-line summary instead.
- If the user asks for repairs, hand off to `obsidian-wiki-maintain` and keep the repair scope narrow.
