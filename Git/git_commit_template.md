# Git Commit Template — шаблон коммитов

## Определения

**`.gitmessage`:** Шаблон для сообщений коммитов.

---

## .gitmessage

### Назначение

Шаблон для сообщений коммитов. Git предварительно заполняет редактор сообщений этим содержимым.

### Пример

```text
# .gitmessage
# <type>: <subject>
#
# <body>
#
# <footer>
#
# Types: feat, fix, docs, style, refactor, test, chore
```

### Настройка

```bash
git config commit.template .gitmessage
```

### Особенности

* **Требует ручной настройки:** Каждый разработчик должен выполнить `git config` после клонирования.
* **Автоматизация:** Команды используют setup-скрипты или husky для автоматической настройки.
* **Альтернатива:** Хук `commit-msg` для валидации формата вместо шаблона.

---

## Связанные документы

- **Обзор**: [git_special_files_overview.md](./git_special_files_overview.md)
