# 🎬 MEU SubSearch

YouTube 直播字幕全局搜索 + 双语字幕 + 在线管理后台。

## 启动

```bash
# 安装依赖（仅 yt-dlp 用于 YouTube 同步）
# 下载 yt-dlp.exe 放到 D:\Tool\yt-dlp\ 或修改 sync_playlist.py 中的路径

# 启动服务器
python server.py

# 打开浏览器
#   搜索页面：http://localhost:8080/
#   管理后台：http://localhost:8080/admin
```

## 功能

### 搜索页面 (`/`)
- **全局搜索** — 在所有视频的所有语言字幕中查找关键词
- **浏览模式** — 网格卡片展示全部视频，支持排序和筛选
- **多语言字幕** — 韩/英/日/中 四语切换
- **双语模式** — 同时显示两种语言字幕（交错排列，颜色区分）
- **YouTube 播放器** — 点击字幕跳转对应时间，自动同步高亮

### 管理后台 (`/admin`)
- **单文件上传** — 上传 .srt，选择语言，绑定视频
- **📦 批量导入** — 拖入多个 .srt，自动检测语言（文本内容分析），自动匹配视频（文件名相似度 ≥70%）
- **表格管理** — 查看/绑定/解绑所有视频的字幕
- **智能扫描** — 发现未分配的 .srt 并一键匹配
- **YouTube 同步** — 从播放列表拉取最新视频

## 字幕文件命名

| 后缀 | 语言 | 颜色 |
|------|------|------|
| `.srt` 或无标识 | 한국어 (ko) | 粉色 |
| `.ko.srt` | 한국어 (ko) | 粉色 |
| `.en.srt` | English (en) | 紫色 |
| `.ja.srt` | 日本語 (ja) | 红色 |
| `.zh.srt` | 中文 (zh) | 绿色 |

## 项目结构

```
MEUfan/
├── server.py           # 主服务器（API + 静态文件）
├── index.html          # 搜索页面
├── admin.html          # 管理后台
├── mapping.json        # 视频→字幕映射表（自动维护）
├── sync_playlist.py    # YouTube 播放列表同步脚本
├── build_data.py       # 从 CSV 构建 mapping.json（备用）
├── *.srt               # 字幕源文件（直接编辑）
└── youtube-*.csv       # YouTube 播放列表导出（历史数据）
```

## 日常操作

### 添加新字幕
1. 把 `.srt` 文件放入项目目录
2. 打开管理后台 → 点击 **📦 일괄 가져오기** → 拖入文件
3. 系统自动检测语言 + 匹配视频 → 点击 **모두 가져오기**
4. 或手动：**📤 SRT 업로드** → 选择文件/语言/视频 → 上传

### 修正字幕
1. 直接编辑 `.srt` 文件
2. 在搜索页面点击 **🔄** 刷新

### 同步 YouTube 最新视频
1. 管理后台点击 **🔄 YouTube 동기화**
2. 或命令行：`python sync_playlist.py`

### 新增语言
1. 放入 `.xx.srt` 文件
2. 编辑 `server.py` / `sync_playlist.py` / `build_data.py` 中的 `KNOWN_LANGS` 和 `LANG_LABELS`
3. 编辑 `index.html` 中的 `LANG_LABELS` 和对应 CSS

## 端口

默认 `8080`，可通过 `python server.py --port 3000` 修改。
