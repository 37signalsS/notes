# RAG-система для поиска по заметкам

Гибридная RAG-система (Retrieval-Augmented Generation) с двумя эмбеддинг-движками (E5 + BGE-M3), BM25-поиском и cross-encoder реранкером. Поиск объединяется через RRF (Reciprocal Rank Fusion) с диверсификацией через MMR.

---

## Перенос на новую машину (полная ручная установка)

### 1. Требования

- macOS / Linux
- Python 3.9+
- Docker (для режима Qdrant-сервера) *или* режим `local` (без Docker)
- ~3 ГБ свободного места для моделей эмбеддингов

### 2. Клонирование и окружение

```bash
# Перейти в директорию с RAG-системой
cd AI/rag_system

# Создать виртуальное окружение
python3 -m venv venv

# Активировать и установить зависимости
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Запуск Qdrant

**Вариант A — Docker (серверный режим, рекомендуется):**

```bash
# Запустить Qdrant в Docker-контейнере
./qdrant_server.sh start

# Другие команды:
# ./qdrant_server.sh stop   — остановить
# ./qdrant_server.sh status — проверить статус
```

**Вариант B — Локальный режим (без Docker):**

В файле `config.yaml` заменить `mode: server` на `mode: local`. Данные будут храниться на диске в `qdrant_db/` и `qdrant_bge/`.

### 4. Сборка индексов

```bash
# Полная сборка (BGE-M3 + E5) — потребуется интернет для загрузки моделей (~2-3 ГБ)
chmod +x refresh_rag.sh
./refresh_rag.sh
```

Или по отдельности:

```bash
python3 ingest.py bge
python3 ingest.py e5
```

### 5. Проверка

```bash
# Статус коллекций
python3 check_db.py
```

---

## Использование: задаём вопросы и получаем ответы

### Сценарий 1 — быстрый вопрос через скрипт `ask.sh`

```bash
./ask.sh "Что такое attention mechanism?"
```

### Сценарий 2 — гибридный поиск (E5 + BGE-M3 + реранкер)

```bash
python3 unified_search.py "Как работает backpropagation?"
```

### Сценарий 3 — с ограничением количества результатов

```bash
python3 unified_search.py "Transformer architecture" --top-k 10
```

### Сценарий 4 — исключить источники

```bash
python3 unified_search.py "RLHF" --exclude "AI/ML"
```

### Сценарий 5 — без реранкера (быстрее)

```bash
python3 unified_search.py "Что такое LoRA?" --no-rerank
```

### Сценарий 6 — сравнение движков

```bash
# Только E5
python3 query.py "Knowledge distillation"

# Только BGE-M3
python3 query_compare.py bge "Preference optimization"

# Сравнить E5 vs BGE-M3
python3 query_compare.py e5 "DPO vs PPO"
```

### Сценарий 7 — BM25 (ключевые слова)

```bash
python3 rag_bm25.py "градиентный спуск learning rate"
```

### Сценарий 8 — произвольный вопрос одной строкой (если `ask.sh` уже `chmod +x`)

```bash
./ask.sh "Как устроен GPT?"
```

### Формат вывода

Результаты возвращаются в JSON:

```json
[
  {
    "engine": "BGE-M3",
    "source": "AI/ML/attention.md",
    "content": "# Attention > Scaled Dot-Product Attention\n...",
    "rerank_score": 8.4321
  }
]
```

Поля: `engine` (какой движок нашёл), `source` (путь к файлу), `content` (текст чанка), `rerank_score` или `score` (оценка релевантности).

---

## Обслуживание

```bash
# Перестроить индексы (после массовых изменений в заметках)
./refresh_rag.sh

# Полная перестройка с очисткой
python3 ingest.py e5 --force
python3 ingest.py bge --force

# Проверка состояния индексов
python3 check_db.py
```

---

## Исключение файлов из поиска

Список исключённых директорий, файлов и расширений задаётся в `config.yaml`:

```yaml
excluded:
  dirs: [".git", ".obsidian", "venv", "rag_system"]
  files: ["GEMINI.md", "MEMORY.md", ".DS_Store"]
  extensions: [".doc", ".docx", ".pdf", ".xls", ...]
```

После добавления нового исключения запустите `ingest.py` — система сама удалит старые чанки из индекса.

---

## Структура репозитория

| Файл | Назначение |
|---|---|
| `unified_search.py` | Главный поисковый движок (гибридный поиск + реранкер + MMR) |
| `ingest.py` | Индексирование markdown-файлов в Qdrant |
| `query.py` | Поиск только через E5 |
| `query_compare.py` | Сравнение результатов E5 и BGE-M3 |
| `rag_bm25.py` | Классический BM25-поиск |
| `rag_utils.py` | Общие утилиты (загрузка моделей, конфиг, работа с Qdrant) |
| `rag_config.py` | Загрузка и мерж конфигурации |
| `rag_models.py` | Модели данных |
| `config.yaml` | Конфигурация движков, реранкера, исключений |
| `ask.sh` | Удобная обёртка для `unified_search.py` |
| `refresh_rag.sh` | Перестроение индексов (BGE-M3 + E5) |
| `qdrant_server.sh` | Управление Qdrant в Docker |
| `check_db.py` | Проверка состояния коллекций |
| `requirements.txt` | Зависимости |
| `pyproject.toml` | Метаданные проекта |

| В Git | Игнорируются |
|---|---|
| `*.py` — движок RAG | `qdrant_db/`, `qdrant_bge/` — векторные индексы |
| `requirements.txt` | `venv/` — виртуальное окружение |
| `*.sh` — скрипты управления | `manifest.json` — привязан к конкретной машине |
| `config.yaml`, `README.md` | `__pycache__/`, `*.log`, `.pyc` |
