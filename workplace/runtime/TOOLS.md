Available built-in tools:
- `bash`: run shell commands in the project
- `read_file`: read files
- `write_file`: create or overwrite files
- `edit_file`: replace text inside files
- `list_dir`: inspect directories
- `glob`: locate files by pattern
- `grep`: search project content with ripgrep
- `web_fetch`: fetch a page and extract readable text
- `web_search`: search the web

Rules:
- stay inside the current project root for filesystem operations
- prefer `rg` for content search
- keep tool outputs compact
