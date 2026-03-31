# Git LFS Config — конфигурация Git LFS

## Определения

**`.lfsconfig`** — файл конфигурации Git LFS, который путешествует с репозиторием и содержит настройки LFS-сервера для всех разработчиков.

---

## Базовые концепции

### Назначение

Файл `.lfsconfig` позволяет закоммитить настройки LFS (URL эндпоинта, параметры передачи), чтобы все разработчики использовали одинаковые настройки без ручной конфигурации.

### Формат файла

```ini
[lfs]
    url = https://lfs.example.com/repo

[lfs "transfer"]
    maxretries = 3
    timeout = 60
```

### Основные директивы

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `url` | URL LFS-сервера | `https://lfs.github.com/org/repo` |
| `access` | Тип доступа | `basic`, `private` |
| `maxretries` | Максимум повторных попыток | `3` |
| `timeout` | Таймаут операции (сек) | `60` |
| `batch` | Включить batch API | `true` |

### Особенности

- Git LFS читает `.lfsconfig` автоматически при выполнении LFS-команд
- Без этого файла разработчикам нужно вручную настраивать локальный LFS
- LFS также использует `.gitattributes` для указания, какие файлы обрабатывать через LFS
- **Миграция:** Если добавляете паттерны LFS после того, как файлы уже закоммичены, нужно выполнить `git lfs migrate` для переписывания истории

---

## Практические сценарии

### Сценарий 1: Настройка кастомного LFS-сервера

Для использования собственного LFS-сервера вместо встроенного в платформу:

```bash
# Создать файл .lfsconfig в корне репозитория
cat > .lfsconfig << 'EOF'
[lfs]
    url = https://lfs.internal.company.com/project
    access = basic
EOF

# Закоммитить конфигурацию
git add .lfsconfig
git commit -m "Configure custom LFS server"
git push origin main
```

### Сценарий 2: Настройка параметров передачи

Для оптимизации работы с нестабильным соединением:

```ini
# .lfsconfig
[lfs]
    url = https://lfs.example.com/repo

[lfs "transfer"]
    maxretries = 5
    timeout = 120
    concurrent = 3
```

### Сценарий 3: Миграция существующих файлов в LFS

Если файлы уже закоммичены в репозиторий:

```bash
# Найти большие файлы в истории
git lfs migrate info --top=10

# Мигрировать файлы определённого типа
git lfs migrate import --include="*.psd,*.zip" --everything

# После миграции добавить .lfsconfig и .gitattributes
git add .lfsconfig .gitattributes
git commit -m "Migrate large files to LFS"
```

### Сценарий 4: Проверка текущей конфигурации

```bash
# Показать текущую LFS конфигурацию
git lfs env

# Проверить отслеживаемые файлы
git lfs ls-files

# Показать статус LFS
git lfs status
```

---

## Дополнительная информация

### Официальные ресурсы

- **Git LFS:** [git-lfs.com](https://git-lfs.com/)
- **Документация Git LFS:** [github.com/git-lfs/git-lfs/wiki/Configuration](https://github.com/git-lfs/git-lfs/wiki/Configuration)

### Связанные темы

Основы Git LFS в [git_lfs.md](./git_lfs.md). Специальные файлы Git в [git_special_files_overview.md](./git_special_files_overview.md). Обработка файлов через `.gitattributes` в [git_attributes.md](./git_attributes.md).
