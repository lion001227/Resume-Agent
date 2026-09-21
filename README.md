# Resume Agent

基于 LangGraph 的简历优化助手：根据目标岗位检索招聘信息、生成岗位画像、改写简历，并在你确认满意后输出高频面试问答。

## 功能

- 读取本地 Word 简历（`resume.docx`）
- 按意向岗位检索并结构化 20 条招聘信息
- 聚合岗位画像，分析技能匹配度，给出优化建议
- 基于画像与建议改写简历
- 人工审核：满意则进入面试题生成；不满意则按你的意见继续改写
- 输出最终简历与面试高频问答

## 工作流

```
START → researcher → profiler → resume → human_review
                                          ├─ 满意 (Y) → interview → END
                                          └─ 不满意 (N) → resume（按修改意见再改）
```

| 节点 | 作用 |
|------|------|
| `researcher` | 按求职意向收集岗位列表 |
| `profiler` | 生成岗位画像、技能分析、简历建议 |
| `resume` | 改写完整简历正文 |
| `human_review` | 中断等待你确认或提出修改意见 |
| `interview` | 根据岗位画像与最终简历生成面试问答 |

状态由 LangGraph `MemorySaver` 按 `thread_id` 保存，中断后可恢复执行。

## 环境要求

- Python 3.10+
- DeepSeek API Key（代码通过 OpenAI 兼容接口调用 `deepseek-chat`）

## 安装

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

## 配置

在项目根目录创建 `.env`（该文件已加入 `.gitignore`，请勿提交）：

```env
OPENAI_API_KEY=your_deepseek_api_key
```

代码使用变量名 `OPENAI_API_KEY`，值为 DeepSeek API Key。默认模型与接口：

- 模型：`deepseek-chat`
- `base_url`：`https://api.deepseek.com/v1`

如需换模型或网关，修改 `resume_agent.py` 中的 `ChatOpenAI` 配置。

将待优化简历放到项目根目录，文件名必须为：

```
resume.docx
```

程序会读取文档中的段落文本，忽略空行。

## 使用

```bash
python resume_agent.py
```

交互顺序：

1. 输入目标岗位（例如：`Python 后端开发`）
2. 等待检索岗位、画像分析和简历改写
3. 查看改写结果，输入 `Y` 表示满意，或输入 `N` 并给出修改意见
4. 满意后打印最终简历和面试高频问答

## 项目结构

```
resume_agent/
├── resume_agent.py    # 主程序：状态、节点、图编排与交互循环
├── requirements.txt
├── README.md
├── .env               # 本地密钥，不入库
└── resume.docx        # 本地简历，不入库
```

## 注意事项

- `researcher` 依赖大模型按提示“搜索招聘网站”并返回结构化结果；当前未接入独立招聘爬虫或搜索 API，岗位真实性取决于模型与接口能力。
- HTTP 客户端使用 `httpx` 且 `trust_env=False`，不会走系统代理环境变量。
- 简历改写节点要求模型只输出正文，不含解释或 markdown 代码块标记。
- 人工审核时输入不区分大小写的 `y` / `Y` 视为满意。

## 许可证

按你的仓库约定自行补充。
