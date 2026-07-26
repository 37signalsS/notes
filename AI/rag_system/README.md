# Инструкция по развертыванию RAG-системы

Полное восстановление системы поиска RAG (Retrieval-Augmented Generation) после клонирования репозитория на новую машину.

## Требования
- **macOS / Linux**
- **Python 3.9+**
- **Git**

## Быстрый старт

```bash
# 1. Перейти в директорию RAG
cd AI/rag_system

# 2. Создать виртуальное окружение
python3 -m venv venv

# 3. Активировать и установить зависимости
source venv/bin/activate
pip install -r requirements.txt

# 4. Собрать поисковые индексы
chmod +x refresh_rag.sh
./refresh_rag.sh
```

**Внимание:** При первом запуске система скачает модели эмбеддингов (BGE-M3 и MPNet) с HuggingFace (~2-3 ГБ). Требуется интернет.

## Что попадает в Git

В репозиторий сохраняются только исходные скрипты и конфигурация:

| В Git | Игнорируются |
|-------|-------------|
| `*.py` — движок RAG | `chroma_db/`, `chroma_bge/` — векторные индексы |
| `requirements.txt` | `venv/` — виртуальное окружение |
| `*.sh` — скрипты управления | `manifest.json` — привязан к конкретной машине |
| `README.md` | `__pycache__/`, `*.log`, `.pyc` |

## Использование

```bash
# Поиск через объединённый движок (MPNet + BGE-M3 + гибридный поиск)
python unified_search.py "твой запрос"

# Поиск только через MPNet
python query.py "твой запрос"

# Сравнение результатов двух движков
python query_compare.py mpnet "твой запрос"
python query_compare.py bge "твой запрос"
```

## Обслуживание

```bash
# Перестроить индексы (после массовых изменений в заметках)
./refresh_rag.sh

# Полная перестройка с очисткой
python ingest.py mpnet --force
python ingest.py bge --force

# Проверка состояния индексов
python check_db.py
```

## Исключение файлов из поиска

Список исключённых директорий, файлов и расширений задаётся в `rag_utils.py`:

```python
EXCLUDED_DIRS = ["Vagrant", ".git", ".obsidian", "venv", "rag_system"]
EXCLUDED_FILES = ["GEMINI.md", "MEMORY.md", ".DS_Store"]
EXCLUDED_EXTENSIONS = [".doc", ".docx", ".pdf", ".xls", ...]
```

После добавления нового исключения запустите `ingest.py` — система сама удалит старые чанки из индекса.
