# Git Ignore — игнорирование файлов

## Определения

**`.gitignore`** — файл с паттернами файлов, которые Git никогда не должен отслеживать.

**Игнорируемые файлы** — файлы, исключённые из системы контроля версий: временные файлы, логи, скомпилированные артефакты, зависимости, чувствительные данные.

---

## Базовые концепции

### Назначение .gitignore

Файл `.gitignore` указывает Git, какие файлы и директории следует игнорировать и не включать в систему контроля версий.

### Синтаксис паттернов

| Паттерн | Описание |
| :--- | :--- |
| `*.log` | Игнорировать все файлы с расширением `.log` |
| `build/` | Игнорировать директорию `build` и всё её содержимое |
| `/TODO` | Игнорировать файл `TODO` только в корневой директории |
| `!important.log` | Не игнорировать `important.log` (исключение из правил) |
| `docs/**/*.txt` | Игнорировать все `.txt` файлы в `docs` и поддиректориях |
| `**/node_modules/` | Игнорировать `node_modules` на любом уровне вложенности |

### Порядок проверки игнорирования

Git проверяет ignore-файлы в следующем порядке:

1. `.gitignore` в каждой директории (от корня к текущей папке)
2. `.git/info/exclude` — локальные игноры, не коммитятся
3. Глобальный файл (`~/.config/git/ignore` или путь из `core.excludesFile`)

Глобальные игноры удобны для OS-специфичных файлов (`.DS_Store`, `Thumbs.db`), которые не должны загромождать каждый проект.

### Важные особенности

* **Только для неотслеживаемых файлов:** `.gitignore` влияет только на новые, не отслеживаемые Git файлы. Файлы, которые уже были закоммичены до добавления в `.gitignore`, остаются в репозитории.
* **Удаление из трекинга:** Для удаления уже отслеживаемого файла из Git (но оставления на диске) используйте `git rm --cached <файл>`.
* **Веб-интерфейсы форджей:** GitHub, GitLab, Forgejo и Gitea позволяют создать файл,_matching_ игнорируемый паттерн, через веб-редактор без предупреждений.
* **Менеджеры пакетов:** Часто поставляются с собственными игнор-паттернами (`node_modules/`, `vendor/`, `target/`), которые ожидаются в `.gitignore`.

### Практические примеры

```gitignore
# Зависимости
node_modules/
vendor/
target/

# Логи
*.log
logs/

# Переменные окружения
.env
.env.local

# Артефакты сборки
dist/
build/
*.exe
*.dll

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
```

### Временное игнорирование изменений в отслеживаемом файле

```bash
# Начать игнорировать изменения в файле, который уже в репозитории
git update-index --assume-unchanged <файл>

# Возобновить отслеживание изменений
git update-index --no-assume-unchanged <файл>
```

---

## Практические сценарии

### Сценарий 1: Настройка .gitignore для нового проекта

Создайте файл в корне репозитория:

```bash
# Создать .gitignore с шаблоном для вашего стека
curl -o .gitignore https://raw.githubusercontent.com/github/gitignore/main/Global/Node.gitignore
```

### Сценарий 2: Удаление уже отслеживаемого файла из Git

Если файл уже закоммичен, простое добавление в `.gitignore` не поможет:

```bash
# Удалить файл из репозитория, но оставить на диске
git rm --cached <файл>

# Закоммитить изменения
git commit -m "chore: remove file from tracking"
```

### Сценарий 3: Глобальный .gitignore для OS-файлов

Для игнорирования системных файлов на всех проектах:

```bash
# Создать глобальный ignore-файл
echo ".DS_Store" >> ~/.gitignore_global
echo "Thumbs.db" >> ~/.gitignore_global

# Настроить Git
git config --global core.excludesFile ~/.gitignore_global
```

### Сценарий 4: .dockerignore для сборки образов

```dockerignore
# Исключить из контекста сборки Docker
.git
node_modules
*.log
.env
Dockerfile
docker-compose.yml
```

**Преимущества:**
* Ускоряет сборку (меньше файлов отправляется демону)
* Предотвращает попадание секретов в образы
* Синтаксис идентичен `.gitignore`: wildcards, negation, directory markers

---

## Дополнительная информация

### Официальные ресурсы

* **Документация Git по gitignore:** [git-scm.com/docs/gitignore](https://git-scm.com/docs/gitignore)
* **Шаблоны .gitignore:** [github.com/github/gitignore](https://github.com/github/gitignore)
* **toptal gitignore generator:** [toptal.com/developers/gitignore](https://www.toptal.com/developers/gitignore)

### Связанные темы

Обзор специальных файлов в [git_special_files_overview.md](./git_special_files_overview.md). Обработка файлов через .gitattributes описана в [git_attributes.md](./git_attributes.md).
