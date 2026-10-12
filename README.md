# 宠物影像识别与荐购系统

> 一个面向面试的全栈实战项目：**拍一张宠物照片 → 识别品种 / 体型 / 毛发状况 → 按识别可信度分级荐购**。
> 多模态识别 + 可信度分级 + 多 Agent 工作流 + RAG + Human-in-the-loop，一个项目把这几件事串成一条完整链路。
> 前后端分离、Docker 一键部署、GitHub Actions CI，覆盖从产品到工程化的完整链路。

**作者**：Wang Jin Xing  
**仓库**：https://github.com/Wang-Jin-Xing/pet-vision-recommend

---

## 技术亮点

- **AI 多 Agent 工作流**：基于 LangGraph 编排 8 个节点（视觉识别 → Supervisor 意图分类 → 专职 Agent → 安全分析 → 人工审核 → Writer），支持 Human-in-the-loop
- **多模态输入 + 可信度分级（本项目的核心设计）**：上传宠物照片识别品种 / 体型 / 毛发状况，识别的**置信度会一路传到推荐与审核**——高置信按品种+体型精确筛选，中置信只按物种，低置信转人工确认，而不是"识别出来就直接拿去推荐"
- **RAG 知识检索**：ChromaDB 向量库 + 混合检索（词法 0.75 + 向量 0.25），避免 LLM 编造
- **流式输出**：SSE 打字机效果（event: progress / delta / done），类 ChatGPT 体验
- **LLM 集成 + 优雅降级**：接入智谱 GLM-4-Flash（文本）/ GLM-4V（视觉），未配置 Key 时自动回退本地确定性逻辑，应用仍可完整运行
- **工程化**：Docker Compose 一键部署、GitHub Actions 自动化测试与镜像构建、**159 个 pytest 用例**

---

## 一、最快上手：Docker 一键启动（推荐）

### 前置条件（只需要装一次）

1. 安装 **Docker Desktop**（Windows）：https://www.docker.com/products/docker-desktop/
2. 安装后**重启电脑**，打开 Docker Desktop，等右下角鲸鱼图标不再转圈
3. 确认 Docker 正常：终端里执行 `docker --version` 能看到版本号

### 启动

在**项目根目录**（有 `docker-compose.yml` 的那个文件夹）打开终端：

```bash
docker compose up -d --build
```

第一次会慢（5~15 分钟，要下载镜像和依赖），之后再启动几秒就好。看到两个容器状态都是 `Up` 即成功：

```bash
docker compose ps
```

### 打开网站

浏览器访问 👉 **http://localhost:8080**

- 第一次使用先点右上角「注册」，自己填邮箱/用户名/密码（邮箱格式正确即可，不会真的发邮件）
- 注册后登录就能用全部功能

### 配置 AI 大模型（可选）

项目默认已接入智谱 GLM-4-Flash（免费）。在项目根目录创建 `.env` 文件并填入：

```env
LLM_API_KEY=你的智谱 API Key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL=glm-4-flash
```

> 不配置也能跑：AI 工作流会自动降级为本地关键词路由 + 模板回答，所有功能仍可用。

### 停止 / 重启 / 看日志

```bash
docker compose down              # 停止（数据不会丢）
docker compose up -d             # 再次启动（不用 --build）
docker compose logs -f backend   # 看后端日志（Ctrl+C 退出查看，不会停服务）
docker compose restart backend   # 只重启后端
```

### 数据存在哪？

数据在 Docker「数据卷」里，**容器删除重建数据也在**：

| 卷名 | 存的内容 |
|------|----------|
| `petvision-data` | SQLite 数据库（用户/商品/订单/对话）+ Chroma 向量知识库 |
| `petvision-uploads` | 上传的知识文档原文 |
| `petvision-cache` | ChromaDB 嵌入模型缓存（首次下载后重建容器不丢失） |

> ⚠️ 只有执行 `docker compose down -v`（多了 `-v`）才会删除数据卷，平时不要加。

---

## 二、这个项目实现了什么功能？

### 商城部分

| 功能 | 说明 |
|------|------|
| 商品首页 | 6 个预置演示商品（狗粮/猫粮/猫砂/玩具等），分类、标签、价格、库存 |
| 注册 / 登录 | JWT 令牌登录，密码 bcrypt 加密存储；登录/注册有防暴力破解限流 |
| 购物车 | 加入购物车、改数量、结算下单（未登录会被拦截到登录页） |
| 订单 | 下单自动**扣库存、算总价、记录下单时单价**；订单列表、状态流转（待付款→已付款→已发货→已签收）；**只能看自己的订单**，越权访问返回 403 |
| 商品搜索 | 首页可按关键词、分类筛选 |

### 拍照建档：多模态识别 + 可信度分级（核心亮点）

入口：登录后点导航栏「我的宠物」（`/pets`）。上传一张宠物照片，识别出物种、品种、体型、毛发状况与健康建议，确认后建档。

难点不在"能不能识别"，而在**识别结果有多可信、以及这个可信度如何影响后续决策**：

| 识别置信度 | 档位 | 后续行为 |
|---|---|---|
| ≥ 0.75 且认出是猫/狗 | 高 | 推荐按 **品种 + 体型 + 毛发诉求** 全量匹配 |
| 0.50 ~ 0.75 | 中 | **只按物种**（猫/狗）推荐，不区分具体品种 |
| < 0.50 | 低 | 档案标记为**待人工确认**，不参与推荐；本次请求转人工审核 |

- **为什么不做成"低置信就拒绝"**：拒掉等于服务失败，用户白拍一张还得重来。改成转人工确认后，用户仍能走完流程——这是把 Human-in-the-loop 从"订单风控"复用成了"识别兜底"
- **不想重复识别？** 聊天页可直接选用已建好的档案（走 `pet_profile_id`），不必每轮重传照片
- **结构化筛选**：商品的适用条件从"中文自由文本"改成结构化字段（`species` / `size` / `stage`），文案改动不会再让筛选失效
- **鲁棒性**：模型输出三层兜底解析（剥代码块 → 截取 `{...}` → 逐行 key:value），畸形输出不会让服务崩；无 Key / 调用失败一律降级，绝不抛异常

### AI 养宠助手（核心亮点）

入口：登录后点导航栏「AI 助手」（`/chat`）。用自然语言和它对话，它是一个**多 Agent 工作流**，由大模型（智谱 GLM-4-Flash）驱动意图识别与回答生成：

```
你的问题（可随消息带一张宠物照片）
   │
   ▼
vision_agent（只有带了照片才走这一步：识别宠物 → 判出可信度档位）
   │
   ▼
supervisor（LLM 意图分类：knowledge / shopping / order）
   ├─── 养宠知识类（疫苗/驱虫/生病症状…）→ knowledge_agent
   │        └─ 从知识库向量检索（ChromaDB），LLM 基于片段合成自然语言回答（RAG）
   ├─── 购物推荐类（推荐/哪款好/多少钱…）→ shopping_agent
   │        └─ 查商品库；有宠物档案时按档位筛（高档：物种+体型+诉求；中档：只按物种）
   └─── 订单核算类（下单/运费/多久到…）  → order_agent
            └─ 调工具算总价、查配送、报时间
                    │
                    ▼
            安全分析节点：金额 > 500 元 / 出现「退款/投诉/取消订单」等词 / 照片识别置信度过低
                    │
          需要人工审核 → 工作流暂停（LangGraph interrupt），页面弹出确认/驳回
                    │
                    ▼
                 生成最终回答（Markdown 渲染，支持流式 SSE 打字机效果）
```

**特点**：

- **真实 LLM + RAG**：知识问答由大模型基于检索到的文档合成回答，底部附带来源引用（不是关键词匹配）
- **意图分类由 LLM 完成**：比硬编码关键词更准确，能理解自然语言
- **流式输出**：回答一个字一个字蹦出来（SSE），左侧是历史会话列表，可随时继续旧对话
- **人工审核（Human-in-the-loop）**：触发风控规则时工作流真的会"暂停等你拍板"，这是 LangGraph 的 interrupt 机制
- **RAG 知识库**：`backend/uploads/` 里预置了 7 篇养宠文档，启动时自动索引进 ChromaDB；上传 `.txt/.md` 文档会自动切块向量化入库
- **优雅降级**：未配置 `LLM_API_KEY` 时自动回退到本地关键词路由 + 模板回答，应用仍可完整运行

### 安全加固

- 全部 SQL 经 ORM/参数化，无注入风险
- JWT 鉴权覆盖所有需登录接口，资源归属校验
- 上传：文件名路径穿越清洗、2MB 限制、UTF-8 校验、防同名覆盖
- 宠物照片：按用户分子目录落盘；前端回传的 `image_path` **必须落在本人目录下**才接受（否则丢弃，防止借接口写任意路径）
- 宠物档案：查询/删除均校验归属，跨用户访问一律 404（不泄露"该 id 是否存在"）
- 识别档位由**服务端重新计算**，前端硬塞 `confidence_grade: high` 无效（防止低置信结果被"洗白"跳过审核）
- CORS 白名单、统一错误响应（不向前端泄露堆栈）、登录限流、弱密钥启动告警

---

## 三、目录结构

```
pet-vision-recommend/
├── docker-compose.yml            # Docker 一键编排（前后端 + 数据卷）
├── .env                           # 本机国内镜像加速配置（不要提交到 git）
├── .github/workflows/deploy.yml  # CI：推送到 main 自动跑测试→构建前端→构建镜像
├── README.md                      # 项目说明（本文件）
│
├── backend/                       # 后端（Python 3.11 + FastAPI）
│   ├── main.py                    # 程序入口：启动后端（建表+种子商品+知识库索引）
│   ├── config.py                  # 所有配置项（环境变量）
│   ├── database.py                # 数据库连接
│   ├── models.py                  # 数据表定义（用户/商品/订单/对话/文档/宠物档案）
│   ├── schemas.py                 # 接口入参校验规则
│   ├── auth.py                    # 密码哈希、JWT 签发解析、登录依赖
│   ├── routers/                   # 接口（每个文件一组 API）
│   │   ├── auth.py                #   注册 / 登录 / 当前用户
│   │   ├── products.py            #   商品列表/搜索/管理
│   │   ├── orders.py              #   下单 / 订单 / 状态
│   │   ├── chat.py                #   AI 对话（普通 + SSE 流式 + 人工审核恢复）
│   │   ├── history.py             #   历史会话
│   │   ├── pets.py                #   宠物档案（照片识别 + 建档 + 增删查）
│   │   └── upload.py              #   知识文档上传
│   ├── agents/                    # AI 多 Agent 工作流
│   │   ├── graph.py               #   LangGraph 图的组装（8 节点）
│   │   ├── nodes.py               #   各 Agent 节点逻辑（含 vision_agent）
│   │   ├── vision.py              #   宠物照片识别（三层鲁棒解析 + 双层拒识 + 降级）
│   │   ├── tools.py               #   Agent 可调用的工具（查商品/检索知识库/算价等）
│   │   ├── review.py              #   人工审核桥接（review_store）
│   │   ├── llm.py                 #   LLM 封装（意图分类 + RAG 回答生成）
│   │   └── state.py               #   工作流状态结构
│   ├── services/                  # 业务服务层
│   │   ├── pet_profile.py         #   档案 CRUD + 置信度三档判定
│   │   └── recommend.py           #   按档位筛选商品（高/中/低三种策略）
│   ├── uploads/                   # 预置的 7 篇知识库文档（也可在网页上传）
│   ├── data/chroma/               # Chroma 向量库文件（运行后生成）
│   ├── data/pet_images/           # 宠物照片（按用户分子目录，运行后生成）
│   ├── tests/                     # 159 个自动化测试
│   ├── requirements.txt           # 后端依赖
│   └── Dockerfile
│
└── frontend/                      # 前端（React 19 + Vite + TailwindCSS）
    ├── src/
    │   ├── pages/                 # Home 首页 / Login / Register / Cart 购物车
    │   │                          # Orders 订单 / Chat AI 助手 / MyPets 我的宠物
    │   ├── components/            # Navbar 导航栏 / ProductCard 商品卡等
    │   ├── context/               # 购物车全局状态
    │   └── api/client.js          # 统一请求封装（自动带 JWT，401 自动跳登录）
    ├── nginx.conf                 # 部署时 Nginx 配置：/api 转发后端，支持 SSE
    └── Dockerfile                 # 多阶段：node 编译 → nginx 托管
```

---

## 四、开发者模式：本地分别启动

适合要改代码的人。需要本机装 **Python 3.11** 和 **Node.js 20**。

### 终端 1：启动后端（端口 8000）

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -r requirements.txt
uvicorn main:app --reload             # 改代码自动重启
```

后端文档（自动生成的接口调试页）：http://localhost:8000/docs （Swagger UI，可直接在网页上试接口）

### 终端 2：启动前端（端口 5173）

```powershell
cd frontend
npm install
npm run dev
```

访问 👉 **http://localhost:5173** （Vite 会自动把 `/api` 请求代理到 8000 端口）

### 跑测试

```powershell
cd backend
pip install -r requirements-dev.txt   # pytest + httpx
pytest -q                             # 159 个用例
```

---

## 五、配置项说明（不改也能跑）

后端所有配置在 [backend/config.py](backend/config.py)，可用环境变量或 `.env` 覆盖：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | 内置开发值（启动会告警） | **上线必须改成随机长字符串** |
| `DATABASE_URL` | `sqlite:///./petvision.db` | 数据库连接串 |
| `UPLOAD_DIR` | `./uploads` | 上传文件目录 |
| `CHROMA_DIR` | `./data/chroma` | 向量库目录 |
| `MAX_UPLOAD_BYTES` | `2097152`（2MB） | 单文件大小上限 |
| `CORS_ORIGINS` | 本地 5173 等 | 允许的前端来源，逗号分隔 |
| `LLM_API_KEY` | 空 | 大模型 API Key（兼容 OpenAI 协议，如智谱 GLM）；空则降级为本地确定性逻辑 |
| `LLM_BASE_URL` | 智谱 GLM 网关 | OpenAI 兼容网关地址 |
| `LLM_MODEL` | `glm-4-flash` | 模型名称 |
| `LLM_TEMPERATURE` | `0.3` | 采样温度，偏低减少随机性 |
| `KNOWLEDGE_SEED_DIR` | 空 | 启动时自动索引到 ChromaDB 的种子文档目录（Docker 中为 `/app/seed_docs`） |
| `VLM_API_KEY` | 空（复用 `LLM_API_KEY`） | 视觉模型 API Key，**留空则自动复用文本模型那把**；想让识图走另一家厂商时单独填 |
| `VLM_BASE_URL` | 空（复用 `LLM_BASE_URL`） | 视觉模型网关地址，同上 |
| `VLM_MODEL` | `glm-4v-flash` | 主视觉模型名（智谱免费档，够用） |
| `VLM_FALLBACK_MODELS` | `glm-4v` | 主模型失败后依次重试的备用模型，逗号分隔 |
| `VLM_TIMEOUT` | `30` | 单次识图请求超时（秒） |
| `PET_IMAGE_DIR` | `./data/pet_images` | 宠物照片落盘目录（按用户分子目录隔离） |
| `MAX_IMAGE_BYTES` | `8388608`（8MB） | 单张照片大小上限 |
| `MIN_CONFIDENCE` | `0.5` | 识别置信度**及格线**：低于此判为低档，转人工确认 |
| `CONFIDENCE_HIGH` | `0.75` | 识别置信度**高档线**：达到此值且是猫/狗，才按品种+体型+毛发全量匹配 |

Docker 构建加速配置在**项目根目录的 `.env`**（1ms.run 基础镜像 / 华为云 pip / npmmirror / 清华 apt）。在国外网络或 CI 环境删掉该文件即自动回退官方源，无需改 Dockerfile。

> 切换其他兼容 OpenAI 协议的模型（DeepSeek/通义/豆包）只需改 `LLM_BASE_URL` 和 `LLM_MODEL` 两个环境变量。

---

## 六、CI 持续集成

文件：[.github/workflows/deploy.yml](.github/workflows/deploy.yml)。代码 **push 到 GitHub 的 main 分支**后自动执行：

1. 后端 159 个 pytest 测试
2. 前端 `npm run build`
3. `docker compose build` 构建前后端镜像

结果在 GitHub 仓库的 **Actions** 页查看。（目前只构建不推送镜像、不自动部署服务器。）

---

## 七、常见问题

**Q：打开 8080 是空白/502？**
A：后端启动较慢（要加载向量库），等 30 秒刷新；用 `docker compose logs backend` 看是否报错。

**Q：8080/8000 端口被占用？**
A：改 `docker-compose.yml` 里的端口映射，如 `"8081:80"`。

**Q：想清空所有数据从头来？**
A：`docker compose down -v`（⚠️ 删除全部用户/订单/知识库），再 `docker compose up -d`，演示商品会自动重建。

**Q：Docker 报虚拟化错误？**
A：Windows 需要启用「适用于 Linux 的 Windows 子系统」和「虚拟机平台」两项功能并重启；Docker Desktop 设置里确认用 WSL2 后端。

**Q：AI 回答要收费吗？**
A：项目默认接入智谱 GLM-4-Flash（有免费额度）。未配置 `LLM_API_KEY` 时自动降级为本地确定性逻辑，完全免费且功能完整。

**Q：怎么往知识库加内容？**
A：登录后在 AI 助手相关页面上传 `.txt`/`.md`（≤2MB），或直接把文件放进 `backend/uploads/` 对应数据卷目录，文档会切块向量化。

---

## 八、技术栈一览

| 层 | 技术 |
|----|------|
| 前端 | React 19、Vite 6、TailwindCSS 4、React Router 7、Axios、react-markdown |
| 后端 | Python 3.11、FastAPI、Uvicorn、SQLAlchemy 2.0、Pydantic v2 |
| 数据库 | SQLite（单文件，零运维） |
| AI | LangGraph（多 Agent + interrupt 人工审核）、LangChain、ChromaDB 0.5（本地向量库）、智谱 GLM-4-Flash（文本）、GLM-4V-Flash（识图） |
| 鉴权 | python-jose（JWT）、passlib + bcrypt |
| 部署 | Docker、Docker Compose、Nginx |
| 质量 | pytest（159 用例）、GitHub Actions CI |
