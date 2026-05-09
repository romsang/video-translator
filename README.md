# 🎬 Video Translator

上传中文视频，自动翻译为目标语言视频、字幕和文字稿。

## 功能

- 🎤 中文语音识别（Qwen3-ASR-Flash）
- 🌐 上下文感知翻译，自动约束时长（OpenAI）
- 🔊 自然语音合成（OpenAI TTS）
- 👄 智能口型同步，自动跳过无人脸画面（Sync.so）
- 📝 输出翻译视频、双语字幕、配音音轨、对照文稿

## 环境要求

- macOS（M1/M2/M3）或 Linux
- Python 3.10+
- FFmpeg

```bash
brew install ffmpeg
```

## 安装

```bash
git clone https://github.com/你的用户名/video-translator.git
cd video-translator

pip install -r requirements.txt
```

## 配置

复制配置模板并填入 API Keys：

```bash
cp config.example.yaml config.yaml
```

打开 `config.yaml`，填入以下三个 Key：

| 字段 | 获取地址 |
|---|---|
| `api_keys.dashscope` | [阿里云百炼控制台](https://bailian.console.aliyun.com/) |
| `api_keys.openai` | [OpenAI Platform](https://platform.openai.com/api-keys) |
| `api_keys.syncso` | [Sync.so Dashboard](https://sync.so/) |

其他可选配置：

```yaml
translation:
  target_language: "English"   # 目标语言

lipsync:
  enabled: true                # 是否启用口型同步
```

## 使用

### 方式一：Gradio 可视化界面

```bash
python run.py
```

浏览器自动打开 `http://127.0.0.1:7860`，上传视频后点击「开始翻译」。

### 方式二：REST API

启动后端服务：

```bash
python main.py
# → http://127.0.0.1:8000
```

关闭服务：终端按 `Ctrl + C`，或：

```bash
lsof -ti:8000 | xargs kill -9
```

接口文档：`http://127.0.0.1:8000/docs`

**提交任务：**

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -F "file=@your_video.mp4" \
  -F "target_language=English"
# 返回 {"task_id": "a1b2c3d4", ...}
```

**查询进度：**

```bash
curl http://127.0.0.1:8000/tasks/a1b2c3d4
```

## 输出文件

任务完成后，结果保存在 `outputs/<task_id>/`：

| 文件 | 说明 |
|---|---|
| `output.mp4` | 翻译后视频（含字幕） |
| `output.srt` | 双语字幕文件 |
| `dubbed.mp3` | 目标语言配音音轨 |
| `transcript.txt` | 原文 + 译文对照文稿 |

## 处理流程

```
视频输入
  │
  ├─ Step 1  FFmpeg + Demucs   音视频分离 · 人声提取
  ├─ Step 2  Qwen3-ASR-Flash   中文语音识别 · 时间轴对齐
  ├─ Step 3  OpenAI            约束时长翻译 · 字幕生成
  ├─ Step 4  OpenAI TTS        语音合成 · 三阶段时长对齐
  ├─ Step 5  OpenCV + Sync.so  人脸检测 · 口型同步
  └─ Step 6  FFmpeg            片段拼接 · 字幕烧录
```

## 项目结构

```
video-translator/
├── run.py                        # Gradio 界面启动入口
├── main.py                       # FastAPI 后端启动入口
├── config.yaml                   # 配置文件（本地，不上传 Git）
├── config.example.yaml           # 配置模板
├── requirements.txt
└── app/
    ├── models/schemas.py         # 数据结构定义
    ├── pipeline/
    │   ├── step1_preprocess.py   # 音视频预处理
    │   ├── step2_asr.py          # 语音识别
    │   ├── step3_translate.py    # 翻译
    │   ├── step4_tts.py          # 语音合成
    │   ├── step5_lipsync.py      # 口型同步
    │   └── step6_assemble.py     # 最终合成
    ├── utils/
    │   ├── ffmpeg_utils.py       # FFmpeg 封装
    │   └── file_utils.py         # 文件管理
    └── ui/
        └── gradio_app.py         # Gradio 界面
```

## 注意事项

- `config.yaml` 已加入 `.gitignore`，不会上传到 GitHub
- 处理时间约为视频时长的 2～4 倍
- 口型同步仅对含人脸的画面生效，其他场景自动跳过以节省费用
- 如系统配置了代理，启动前确保 `127.0.0.1` 不走代理
