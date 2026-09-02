# Interview RAG

熟練者へのインタビューから、経験・判断・理由・学びなどを構造化して抽出し、
Vector RAGで質問できる最小実験環境です。

```text
対話型インタビュー
    ↓ interview.txt
構造化知識抽出
    ↓ knowledge.json
Ollama Embedding + FAISS
    ↓ Top-k Knowledge
根拠限定QA
    ↓
10問の人手評価
```

生成とEmbeddingは別PC上のOllamaへ依頼します。GraphRAG、Neo4j、Agent、Web UIは
このMVPには含めていません。

## 必要環境

- Python 3.11以上（3.15未満）
- [uv](https://docs.astral.sh/uv/)
- クライアントPCから到達できるOllamaサーバー
- Ollama側に次のモデル（または同等の任意モデル）
  - Chat: `qwen3:8b`
  - Embedding: `embeddinggemma`

Ollamaサーバーの公開範囲は信頼できるLANまたはVPN内に限定してください。このツールは
Ollamaの認証や暗号化を追加しません。

## セットアップ

```bash
git clone https://github.com/fumin0ri/interview.git
cd interview
uv sync --all-groups
```

`.env.example` を `.env` にコピーし、`OLLAMA_HOST` を別PCのアドレスへ変更します。

```dotenv
OLLAMA_HOST=http://192.0.2.10:11434
OLLAMA_CHAT_MODEL=qwen3:8b
OLLAMA_EMBED_MODEL=embeddinggemma
OLLAMA_TIMEOUT_SECONDS=120
DEFAULT_TOP_K=3
DATA_DIR=data/sessions
```

Ollama側でモデルを準備します。

```bash
ollama pull qwen3:8b
ollama pull embeddinggemma
```

接続とモデルを診断します。

```bash
uv run interview-rag doctor
```

## 基本的な実験手順

### 1. インタビュー

```bash
uv run interview-rag interview --session interview_001 \
  --topic "研究で困った経験と意思決定" --minutes 30
```

Ollamaが質問を一つずつ生成します。入力後は各発話が即座に保存されます。終了時は
`:done` または `：done` を入力してください。Ctrl+Cでも入力済みの内容は残ります。

### 2. Knowledge抽出

```bash
uv run interview-rag extract --session interview_001
```

抽出するKnowledgeの種類は次の6種類です。

- `fact`
- `experience`
- `decision`
- `reason`
- `lesson`
- `preference`

OllamaへJSON Schemaを渡し、Pydanticでも検証します。不正な出力は一度だけ修復を試み、
再度失敗した場合は既存の `knowledge.json` を変更せず終了します。

### 3. FAISS索引

```bash
uv run interview-rag index --session interview_001
```

KnowledgeをバッチEmbeddingし、L2正規化したベクトルを `IndexFlatIP` へ保存します。
Embeddingモデル、次元数、Knowledgeのハッシュも保存するため、設定変更やKnowledge更新後に
古い索引を誤用しません。

### 4. 質問

```bash
uv run interview-rag ask --session interview_001 \
  --question "私は技術選定で何を重視する傾向がありますか？" --top-k 3
```

回答とともに、引用したKnowledge IDおよびTop-kの類似度を表示します。取得知識だけでは
答えられない場合、回答は `情報不足` になります。

### 5. 10問評価

`examples/evaluation_questions.json` をセッションの `evaluation/questions.json` へコピーし、
自分のインタビューに合う10問へ編集してから回答を生成します。質問は `fact`、
`reasoning`、`synthesis` の全カテゴリを含めます。

```bash
mkdir -p data/sessions/interview_001/evaluation
cp examples/evaluation_questions.json data/sessions/interview_001/evaluation/questions.json
uv run interview-rag eval-run --session interview_001 \
  --questions data/sessions/interview_001/evaluation/questions.json
uv run interview-rag eval-score --session interview_001
```

採点は正確性 `2 / 1 / 0` とHallucination `0 / 1` です。1問ごとに保存されるため、
Ctrl+Cで中断しても同じコマンドで続きから再開できます。完了時に全体平均、カテゴリ別平均、
Hallucination率を出力します。

## 保存構成

```text
data/sessions/<session_id>/
├── interview.txt
├── manifest.json
├── knowledge.json
├── index/
│   ├── faiss.index
│   └── metadata.json
├── qa.jsonl
└── evaluation/
    ├── questions.json
    ├── results.json
    └── summary.json
```

`data/sessions/` 以下の実データはGit管理から除外されます。コミット可能な匿名例は
`examples/sample_session/` にあります。

## Knowledge Schema

```json
{
  "id": "k001",
  "type": "decision",
  "topic": "技術選定",
  "content": "複雑なモデルから単純な手法へ変更した。",
  "reason": "少量データでは分散を抑えることが重要だと判断したため。",
  "source": "interview_001"
}
```

## 開発・テスト

外部Ollamaを使わない通常テストと静的チェックは次で実行できます。

```bash
uv run ruff check .
uv run pytest
```

実Ollamaとの疎通テストは明示的に有効化します。

```bash
RUN_OLLAMA_TESTS=1 uv run pytest -m integration
```

## トラブルシュート

- `doctor` が接続失敗する: Ollamaの待受アドレス、OSファイアウォール、LAN/VPN経路、
  `.env` の `OLLAMA_HOST` を確認してください。
- モデルがないと表示される: Ollamaサーバー側で対象モデルを `ollama pull` してください。
- 索引の不一致: Chat/Embeddingモデルまたは `knowledge.json` の変更後に
  `interview-rag index` を再実行してください。
- タイムアウト: 大きいモデルや低速ネットワークでは `OLLAMA_TIMEOUT_SECONDS` を増やしてください。
- `情報不足` が多い: 先にインタビューで具体的な行動、判断理由、結果、学びを追加してください。

## 将来拡張

パッケージを機能別に分離し、OllamaとFAISSをadapterとして隔離しています。次の候補は、
高度なAdaptive Interview、Raw transcript RAGとの比較、Knowledge Graph/GraphRAGです。

Ollama API仕様:
[Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs) /
[Embeddings](https://docs.ollama.com/api/embed)
