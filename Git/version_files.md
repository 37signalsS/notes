# Version Files — файлы версий языков

## Определения

Файлы для указания версий языков программирования и инструментов.

---

## .ruby-version, .node-version, .python-version

**Назначение:** Указание версии языка для менеджеров версий (rbenv, nodenv, pyenv, nvm, asdf).

**Пример:**

```text
# .ruby-version
3.3.0

# .node-version
20.11.0
```

**Поведение:** Инструменты автоматически переключают версию при `cd` в директорию.

---

## .tool-versions

**Назначение:** Мультиязычный файл версий для asdf.

**Пример:**

```text
ruby 3.3.0
nodejs 20.11.0
python 3.12.0
```

---

## Связанные документы

- **Обзор**: [git_special_files_overview.md](./git_special_files_overview.md)
- **Editorconfig**: [editorconfig.md](./editorconfig.md)
