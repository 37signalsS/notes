# Version Files — файлы версий языков

## Определения

**Version Files** — конфигурационные файлы, содержащие версию языка программирования или инструмента. Используются менеджерами версий (rbenv, nodenv, pyenv, nvm, asdf) для автоматического переключения версии при входе в директорию проекта.

---

## Базовые концепции

### .ruby-version, .node-version, .python-version — моноязыковые файлы

**Назначение:** Указание версии языка для менеджеров версий (rbenv, nodenv, pyenv, nvm, asdf).

**Пример:**

```text
# .ruby-version
3.3.0

# .node-version
20.11.0
```

**Поведение:** Инструменты автоматически переключают версию при `cd` в директорию.

### .tool-versions — мультиязычный файл asdf

**Назначение:** Единый файл версий для asdf, поддерживающий несколько языков и инструментов.

**Пример:**

```text
ruby 3.3.0
nodejs 20.11.0
python 3.12.0
```

---

## Практические сценарии

### Сценарий 1: Фиксация версии в проекте

```bash
# Указать версию Ruby для rbenv
echo "3.3.0" > .ruby-version

# Указать версию Node.js для nodenv
echo "20.11.0" > .node-version
```

### Сценарий 2: Использование .tool-versions с asdf

```bash
# Установить версии
asdf install ruby 3.3.0
asdf install nodejs 20.11.0

# Создать .tool-versions в текущей директории
asdf local ruby 3.3.0
asdf local nodejs 20.11.0
```

### Сценарий 3: Проверка текущей версии

```bash
# Проверить активную версию
ruby --version
node --version

# asdf: список версий для инструмента
asdf list ruby
```

---

## Дополнительная информация

### Связанные документы

- [git_special_files_overview.md](./git_special_files_overview.md) — обзор специальных файлов Git
- [editorconfig.md](./editorconfig.md) — конфигурация редакторов кода
