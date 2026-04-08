The user owns this repository and expects practical end-to-end engineering work.

Project conventions:
- keep generated runtime data under `workplace/runtime/`
- 如果用户没有明确指定文件的生成目录，那么默认 agent 使用 `write_file` 的所有 file 全部写在 `/Users/wangyc/Desktop/projects/Pooh-code/workplace/output`
- use `uv` for dependency management