用户拥有此仓库，期望实际的端到端工程工作。

项目约定：
- 你的工作目录是/Users/wangyc/Desktop/projects/Pooh-code/workplace，你只被允许访问你的工作目录中的文件
- 生成的运行时数据存放在 `workplace/runtime/` 下
- 如果用户没有明确指定文件的生成目录，那么默认 agent 使用 `write_file` 的所有 file 全部写在 `/Users/wangyc/Desktop/projects/Pooh-code/workplace/output/<session_id>/`
- 使用 `uv` 进行依赖管理，python解释器在/Users/wangyc/Desktop/projects/Pooh-code/.venv/bin/python
