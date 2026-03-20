# Git Submodules — подмодули

## Определения

**`.gitmodules`:** Файл конфигурации для Git submodules, хранящий пути, URL и ветки подмодулей.

---

## .gitmodules

### Назначение

Файл конфигурации для Git submodules. Git записывает в него информацию при выполнении `git submodule add` и читает при `git submodule update`.

### Формат

```ini
[submodule "vendor/lib"]
    path = vendor/lib
    url = https://github.com/example/lib.git
    branch = main

[submodule "themes/default"]
    path = themes/default
    url = https://github.com/example/theme.git
```

### Особенности submodules

* **Расположение:** Файл находится в корне репозитория.
* **Автоматическая инициализация:** `git clone` не загружает содержимое подмодулей автоматически. Требуется:
  ```bash
  git submodule update --init --recursive
  # или
  git clone --recurse-submodules <url>
  ```
* **Версионирование:** Подмодули отслеживают конкретный коммит, а не диапазон версий.
* **Проблемы:** Вложенные `.git` директории, забывчивость обновления создают запутанные состояния.
* **Применение:** Вендоринг контролируемого кода, монорепозитории с частичной выгрузкой.

---

## Связанные документы

- **Обзор**: [git_special_files_overview.md](./git_special_files_overview.md)
