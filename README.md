# MEUfan

MEU YouTube 直播字幕检索与管理工具。公开搜索端可以导出为纯静态站点部署到 Cloudflare Pages；管理端只建议在本地运行，用来上传字幕、绑定视频、编辑字幕和同步 YouTube 播放列表。

## 本地运行

```bash
python server.py
```

默认地址：

- 搜索页：http://127.0.0.1:8080/
- 管理页：http://127.0.0.1:8080/admin

修改端口：

```bash
python server.py --port 3000
```

`server.py` 默认只监听 `127.0.0.1`。本地没有配置管理员账号时，`/admin` 会自动以 `local` 身份进入，不需要密码。

如果确实需要让其他设备访问本地服务，可以显式绑定地址：

```bash
python server.py --host 0.0.0.0 --port 8080
```

绑定到非本机地址前，建议先配置管理员密码。

## 管理后台密码

本地单人使用可以不配置密码。需要启用登录时，创建 `data/admin_config.json`：

```json
{
  "admins": [
    {"alias": "owner", "password": "change-me"}
  ],
  "sessionHours": 24
}
```

也可以使用环境变量：

```powershell
$env:MEUFAN_ADMIN_PASSWORDS = "owner:change-me"
python server.py
```

生成哈希密码：

```bash
python server.py --hash-password "change-me"
```

再写入：

```json
{
  "admins": [
    {"alias": "owner", "passwordHash": "pbkdf2_sha256$..."}
  ],
  "sessionHours": 24
}
```

`data/`、`.git/`、`.omc/`、`__pycache__/` 已被本地服务器禁止静态访问。CORS 默认只允许当前端口的 `localhost` / `127.0.0.1`；需要额外来源时设置：

```powershell
$env:MEUFAN_ALLOWED_ORIGINS = "https://example.com,http://localhost:3000"
```

## Cloudflare Pages 部署

生产部署只发布公开搜索端，不发布管理后台和本地 API。

发布前运行：

```bash
python sync_playlist.py
python check_project.py
python export_static.py
```

`export_static.py` 会生成 `dist/`，内容包括：

- `index.html`
- `assets/index.css`
- `assets/index.js`
- `mapping.json`
- `data/manifest.json`
- `data/glossary.json`
- `subtitles/*.srt`
- `dist/_headers`

不会导出：

- `admin.html`
- `assets/admin.css`
- `assets/admin.js`
- `server.py`
- `data/admin_config.json`
- `data/admin_sessions.json`
- `data/backups/`

Cloudflare Pages Git 集成建议配置：

- Build command: `python export_static.py`
- Build output directory: `dist`

如果用 Direct Upload / Wrangler：

```bash
python export_static.py
npx wrangler pages deploy dist
```

部署时不要把仓库根目录作为输出目录，避免把本地管理文件一起发布。

## 数据更新流程

推荐把 YouTube 播放列表同步和字幕管理留在本地：

1. 本地运行 `python server.py`。
2. 在 `/admin` 上传、绑定、编辑字幕。
3. 在管理表格的 `Sources` 列填写可选的 Bilibili 视频链接。
4. 运行 `python sync_playlist.py` 更新视频列表。
5. 运行 `python check_project.py` 检查数据。
6. 运行 `python export_static.py` 生成 `dist/`。
7. 将 `dist/` 部署到 Cloudflare Pages。

## YouTube 同步

当前同步脚本不依赖 `yt-dlp`。`sync_playlist.py` 使用 Python 标准库抓取公开播放列表页面，并提取：

- 视频 ID
- 视频地址
- 标题
- 封面图链接
- 发布时间
- 时长，如果页面数据提供

常用命令：

```bash
python sync_playlist.py
python sync_playlist.py --dry-run
python sync_playlist.py --no-match
```

## 视频源

每个视频默认使用 YouTube 链接：

```json
{
  "videoId": "CHCwjMfkb-I",
  "videoUrl": "https://www.youtube.com/watch?v=CHCwjMfkb-I"
}
```

如果同一个视频也有 Bilibili 版本，可以在本地管理页表格的 `Sources` 列填写 Bilibili 地址。保存后 `mapping.json` 会增加：

```json
{
  "bilibiliUrl": "https://www.bilibili.com/video/BV...",
  "bilibiliSubtitleOffset": 0
}
```

公开搜索页右上角可以切换 `YouTube` / `Bilibili`。YouTube 使用官方 iframe API 精确同步；Bilibili 使用外链播放器的起始时间参数，点击字幕跳转后会按本地计时显示字幕。

`bilibiliSubtitleOffset` 单位是秒，只影响前端显示，不会生成或改写 SRT 文件。正数表示字幕整体晚显示，例如 `+2` 会让原本 10 秒的字幕在 Bilibili 12 秒时显示；负数表示字幕提前显示，例如 `-1.5` 会让 10 秒字幕在 8.5 秒时显示。

## 字幕文件

字幕统一放在 `subtitles/`：

```text
subtitles/[ko-videoId] title.srt
subtitles/[zh-videoId] title.srt
```

支持语言：

| 标识 | 语言 |
| --- | --- |
| `ko` | 韩语 |
| `en` | English |
| `ja` | 日本語 |
| `zh` | 中文 |

普通 `.srt` 默认按韩语处理。中文文件名支持 `zh`、`zh-CN`、`zh-TW`、`cn`、`chinese` 等别名。

## 项目检查

```bash
python check_project.py
```

检查内容：

- `mapping.json` 结构
- 视频 ID 是否重复
- 字幕引用是否存在
- `subtitles/` 是否有未引用文件
- Python 文件语法
- 前端 JS 语法
- 本地敏感文件提示

归档未引用字幕：

```bash
python archive_orphaned_srts.py
```

文件会移动到 `data/orphaned_subtitles/YYYYMMDD-HHMMSS/`，不会直接删除。

## 目录结构

```text
MEUfan/
├─ server.py
├─ index.html
├─ admin.html
├─ export_static.py
├─ sync_playlist.py
├─ check_project.py
├─ meufan_core.py
├─ mapping.json
├─ assets/
│  ├─ index.css
│  ├─ index.js
│  ├─ admin.css
│  └─ admin.js
├─ subtitles/
├─ data/
└─ dist/
```

`data/` 和 `dist/` 默认不提交。`data/` 保存本地配置、日志、备份和归档文件；`dist/` 是每次发布前重新生成的静态输出。
