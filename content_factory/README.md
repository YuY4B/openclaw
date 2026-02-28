# AI Content Factory (TikTok Swarm) Architecture

## 概要 | Overview

このドキュメントは、Azure Functions + Markdown Agent を活用した大規模SNS投稿自動化システムのアーキテクチャを定義します。

**アーキテクチャタイプ**: Cloud-Local Hybrid Orchestration  
**投稿プラットフォーム**: TikTok (via OpenClaw)  
**実行環境**: Windows + Python 3.11+ / PowerShell (UTF-8)

---

## 1. システム構成図 | System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AZURE CLOUD (Azure Functions)                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ beauty_agent    │  │ gadget_agent    │  │ food_agent      │   ...       │
│  │ (Function App)  │  │ (Function App)  │  │ (Function App)  │              │
│  │ /api/beauty     │  │ /api/gadget     │  │ /api/food       │              │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │
│           │                    │                    │                        │
│           └────────────────────┼────────────────────┘                        │
│                                │                                             │
│                    ┌───────────▼───────────┐                                │
│                    │   Azure API Gateway   │                                │
│                    │   (Traffic Manager)   │                                │
│                    └───────────┬───────────┘                                │
└────────────────────────────────┼────────────────────────────────────────────┘
                                 │
                                 │ HTTPS REST API Calls
                                 │
┌────────────────────────────────┼────────────────────────────────────────────┐
│                        LOCAL EXECUTION (Windows)                             │
│                                │                                             │
│                    ┌───────────▼───────────┐                                │
│                    │  MASTER CONTROLLER    │                                │
│                    │  (master_controller)  │                                │
│                    │  - Job Queue           │                                │
│                    │  - Agent Scheduler    │                                │
│                    │  - Error Handler      │                                │
│                    └───────────┬───────────┘                                │
│                                │                                             │
│           ┌────────────────────┼────────────────────┐                       │
│           │                    │                    │                       │
│  ┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐             │
│  │ Video Creator   │  │ Script Cache     │  │ OpenClaw Poster │             │
│  │ (video_creator) │  │ (JSON Storage)   │  │ (openclaw_poster)│            │
│  │ - edge-tts      │  │                  │  │ - Device Pool   │             │
│  │ - Image Synthesis│ │                  │  │ - IP Rotation  │             │
│  └─────────────────┘  └──────────────────┘  └─────────────────┘             │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────┐        │
│  │  EXECUTION ENVIRONMENT POOL (Swarm Mode)                        │        │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐                 │        │
│  │  │ Instance 1 │  │ Instance 2 │  │ Instance N │  (Multiple      │        │
│  │  │ (VM/Docker)│  │ (VM/Docker)│  │ (VM/Docker)│   Windows VMs)  │        │
│  │  └────────────┘  └────────────┘  └────────────┘                 │        │
│  └──────────────────────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. コンポーネント詳細 | Component Details

### 2.1 Azure Functions (Cloud Agent Layer)

各エージェントは独立したAzure Functionとしてデプロイ:

| Agent Name | Endpoint | 担当ニッチ | 出力形式 |
|------------|----------|-----------|---------|
| beauty_agent | `/api/beauty` | 美容・スキンケア | JSON Script |
| gadget_agent | `/api/gadget` | ガジェット・Tech | JSON Script |
| food_agent | `/api/food` |  food・レシピ | JSON Script |
| fashion_agent | `/api/fashion` | コーディネート | JSON Script |
| fitness_agent | `/api/fitness` | フィットネス | JSON Script |

**Agent内部フロー**:
```
Markdown Persona File (beauty_agent.md)
        │
        ▼
Azure Functions (Python)
        │
        ▼
Gemini API (script generation)
        │
        ▼
JSON Response (UGC-style script)
```

### 2.2 Master Controller (Local Orchestration)

**責務**:
- Azure Agent APIの順次呼び出し
- 台本収集とジョブキューへの格納
- 動画生成タスクのスケジューリング
- OpenClawポスタへのタスク分配
- 24時間全年無停止稼働

**動作フロー**:
```python
while True:
    1. Azure Agentsからスクリプトを取得
    2. ビデオクリエイターにジョブを投入
    3. 動画生成完了を待機
    4. OpenClaw Posterに投稿タスクを分配
    5. エラーチェック & リトライ
    6. 次のサイクルまで待機
```

### 2.3 Video Creator (動画生成)

- edge-tts による音声合成
- 静止画 + 音声 = 動画生成
- ローカルGPU最適化 (Windows)

### 2.4 OpenClaw Poster (投稿実行)

- OpenClaw CLIを活用したスマホ操作エミュレーション
- シャドウバン対策:
  - IP分散 (プロキシプール)
  - デバイス切り替え (複数のOpenClawセッション)
  - 投稿間隔のランダム化

---

## 3. データフロー | Data Flow

```
[1] Azure Agent Call          [2] Script Collection        [3] Video Generation
    POST /api/beauty              Response:                      Call video_creator.py
    {topic: "skincare"}    ──►   {script: "...",                {script_id: "xxx",
                                   duration: 45,                    voice: "ja-JP-Nanami",
                                   keywords: [...]}                background: "image.jpg"}
                                        │
                                        ▼
[6] Posted ✓              [5] OpenClaw Post              [4] Video Ready
    Log to DB                   Call openclaw_poster.py          {video_path: "xxx.mp4"}
    Update status         ──►   {video: "xxx.mp4",                   │
                                 account: "account_1"}             │
                                 │                                  │
                                 ▼                                  │
                          [Check Shadowban] ◄──────────────────────┘
```

---

## 4. シャドウバン対策 | Shadowban Prevention

### 4.1 IP分散戦略

| レイヤー | 対策 | 実装 |
|---------|------|------|
| L3 | プロキシプール回転 | Residential Proxies (Bright Data, Smartproxy) |
| L4 | キャリアIP利用 | 4G/5G SIMベースプロキシ |
| L7 | User-Agentローテーション | ランダムUA文字列 |

### 4.2 デバイス戦略

- **アカウントバケット**: 10-20アカウント/1デバイス
- **セッションローテーション**: 投稿ごとにセッション切替
- **行動パターン多様化**: スクロール履歴、いいね、コメント自動化

### 4.3 投稿パターン

| パラメータ | 推奨値 | 備考 |
|----------|--------|------|
| 投稿間隔 | 30-120分 (ランダム) | 人間的な間隔 |
| 1日投稿数 | 3-5本/アカウント | 過剰投稿回避 |
| ハッシュタグ | 3-8個 (ローテーション) | キーワードローテーション |

---

## 5. エラーハンドリング | Error Handling

### 5.1 リトライ戦略 (Exponential Backoff)

```python
MAX_RETRIES = 5
BASE_DELAY = 5  # 秒
MAX_DELAY = 300  # 最大5分

def retry_with_backoff(func):
    for attempt in range(MAX_RETRIES):
        try:
            return func()
        except RetryableError as e:
            delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
            sleep(delay + random.uniform(0, 1))
    raise MaxRetriesExceeded()
```

### 5.2 エラー分類

| エラータイプ | 対応 | リトライ回数 |
|------------|------|-------------|
| NetworkTimeout | 等待後再試行 | 3回 |
| APIRateLimit | 等待+Backoff | 5回 |
| TikTokShadowban | アカウント切替 | 10回 |
| VideoGenerationError | 再生成 | 3回 |
| OpenClawConnectionError | 再接続 | 5回 |

---

## 6. スケーリング戦略 | Scaling Strategy

### 6.1 水平スケーリング

```
単一VM (1-10アカウント)
       │
       ▼
VM Cluster (10-100アカウント)
       │
       ▼
Kubernetes/Docker Swarm (100-1000アカウント)
```

### 6.2 アカウントバケット管理

```yaml
account_pools:
  - pool_id: "pool_beauty"
    accounts: ["acc_001", "acc_002", ..., "acc_020"]
    agents: ["beauty_agent"]
    max_daily_posts: 5
    
  - pool_id: "pool_gadget"  
    accounts: ["acc_021", "acc_022", ..., "acc_040"]
    agents: ["gadget_agent"]
    max_daily_posts: 5
```

---

## 7. 監視とロギング | Monitoring

### 7.1 監視項目

| 指標 | 閾値 | アラート |
|-----|------|---------|
| 投稿成功率 | < 95% | Slack/Discord通知 |
| API応答時間 | > 5s | 要調査 |
| シャドウバン検出 | > 3回/日 | 緊急対応 |
| キュー滞留数 | > 100 | スケール調査 |

### 7.2 ロギング

- **構造化ログ** (JSON)
- **トレースID** (リクエスト追跡)
- **メトリクス** (Prometheus compatible)

---

## 8. セキュリティ | Security

- Azure Functions: API Key認証
- Local: 環境変数によるシークレット管理
- プロキシ認証: Azure Key Vault統合
- アカウント認証情報: 暗号化されたJSONVault

---

## 9. ファイル構造 | File Structure

```
content_factory/
├── README.md                    # このファイル
├── master_controller.py         # メインコントローラー
├── config.yaml                  # 設定ファイル
├── requirements.txt             # Python依存
│
├── agents/                      # Azure Agent定義
│   ├── beauty_agent.md
│   ├── gadget_agent.md
│   ├── food_agent.md
│   └── template.md
│
├── scripts/                     # ローカル実行スクリプト
│   ├── video_creator.py        # (既存: 参照のみ)
│   └── openclaw_poster.py      # (既存: 参照のみ)
│
└── utils/                       # ユーティリティ
    ├── error_handler.py
    ├── proxy_manager.py
    ├── account_pool.py
    └── logger.py
```

---

## 10. クイックスタート | Quick Start

```powershell
# 1. 依存インストール
pip install -r requirements.txt

# 2. 設定編集
notepad config.yaml

# 3. コントローラー起動
python master_controller.py

# 4. テストモード (投稿なし)
python master_controller.py --dry-run
```

---

*最終更新: 2026-02-28*
*Architecture Version: 1.0*
