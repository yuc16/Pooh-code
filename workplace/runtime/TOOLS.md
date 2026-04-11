可用的内置工具：
- `bash`：在项目中运行 Shell 命令
- `read_file`：读取文件
- `write_file`：创建或覆盖文件
- `edit_file`：替换文件中的文本
- `list_dir`：查看目录
- `glob`：按模式匹配定位文件
- `grep`：使用 ripgrep 搜索项目内容
- `web_fetch`：抓取网页并提取干净正文（自动去除导航、广告等无关内容）
- `web_search`：联网搜索，默认多引擎并行（Tavily + Brave），结果按 URL 去重并给多源命中加权，全部失败时降级到 DuckDuckGo
- `web_search_and_read`：联网搜索并自动抓取 top 结果的完整正文，适合需要深入了解的场景

规则：
- 文件系统操作限制在当前项目根目录内
- 内容搜索优先使用 `rg`
- 保持工具输出简洁
- 联网搜索：简单问题用 `web_search`，需要详细内容时用 `web_search_and_read`
- 已有具体 URL 时直接用 `web_fetch`，无需先搜索
