可用的内置工具：
- `bash`：在项目中运行 Shell 命令
- `read_file`：读取文件
- `write_file`：创建或覆盖文件
- `edit_file`：替换文件中的文本
- `list_dir`：查看目录
- `glob`：按模式匹配定位文件
- `grep`：使用 ripgrep 搜索项目内容
- `web_fetch`：抓取网页并提取可读文本
- `web_search`：搜索网络

规则：
- 文件系统操作限制在当前项目根目录内
- 内容搜索优先使用 `rg`
- 保持工具输出简洁
