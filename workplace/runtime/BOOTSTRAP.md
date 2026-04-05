Bootstrap sequence:
1. Load settings from `workplace/runtime/config/settings.json` and environment variables.
2. Load bootstrap markdown files from `workplace/runtime/`.
3. Load skills from `workplace/runtime/skills/`.
4. Restore session history from JSONL.
5. Run the tool-using model loop until a final assistant reply is produced.
