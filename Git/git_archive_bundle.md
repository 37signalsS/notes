# Git Archive и Git Bundle — экспорт и офлайн-передача

**Актуально для:** Git 2.38–2.56 (локально проверено на 2.54.0); формат bundle v3 появился в 2.38.0, v2 — более старый, совместимый только с SHA-1. Описание остаётся корректным для 2.54–2.56 — изменений в описанных командах не было.

## Определения

**git archive** — команда для создания архива (zip, tar, tar.gz) содержимого конкретного коммита или ветки без `.git` директории.

**git bundle** — команда для упаковки репозитория (или его части) в один файл `.bundle`, содержащий объекты Git и ссылки. Позволяет передавать репозиторий офлайн.

**export-ignore** — атрибут `.gitattributes`, исключающий файлы из архива `git archive`.

**export-subst** — атрибут `.gitattributes`, подставляющий переменные Git (`$Format:...$`) в файлы при архивации.

---

## Базовые концепции

### archive vs bundle vs clone

| Критерий | git archive | git bundle | git clone |
| :--- | :--- | :--- | :--- |
| Содержит `.git` | Нет | Да (упакованный) | Да |
| История коммитов | Нет | Да (опционально) | Да |
| Дельты/объекты | Нет | Да | Да |
| Remote-ссылки | Нет | Нет | Да |
| Использование | Release архивы | Офлайн-передача | Копирование репо |
| Формат | .zip, .tar, .tar.gz | .bundle | Полный репо |

### Формат bundle

Bundle — это pack-файл с заголовком, указывающим содержимые ссылки. Структура:

```text
# v2 git bundle
<SHA-1> HEAD
<SHA-1> refs/heads/main
<SHA-1> refs/heads/feature

[объекты Git]
```

**Версии формата (проверено локально 2.54.0):**

| Версия | Появление | Возможности | Ограничения |
| :--- | :--- | :--- | :--- |
| v2 | По умолчанию (старше 2.38) | SHA-1, базовые prereq | Не поддерживает SHA-256, фильтры, shallow-clone |
| v3 | Git 2.38.0+ | `@object-format=sha256`, `@filter=blob:none` | Не совместим со старыми клиентами |

Команды управления версией:
```bash
# Создать bundle v3
git bundle create --version=3 repo.bundle --all

# Проверить версию bundle
git bundle verify repo.bundle
```

**Компоненты bundle:**
- **Prerequisites** (`- obj-id comment`) — объекты, которые читатель должен уже иметь. Не являются границей shallow-clone — это разные механизмы.
- **References** (`obj-id refname`) — вершины, которые можно получить через `git fetch`.
- **Pack** — поток данных, который `git fetch` отправил бы при получении refs из References в репозиторий, указывающий на объекты из Prerequisites.
- **Capabilities** (только v3) — расширения: `object-format` (алгоритм хэша), `filter` (фильтр объектов, как в `--filter`).

**Особенности:**
- Bundle с prereq создаётся как *thin pack* (опция `--thin` у `git-pack-objects`), распаковывается через `--fix-thin` в `git-index-pack`.
- Не существует «thick pack» для bundle с prereq.
- Prereq-объекты могут использоваться как basis для delta-сжатия.
- Неверные capabilities приводят к ошибке: неизвестные capabilities заставляют `git bundle` завершиться сбоем.

---

## Практические сценарии

### Сценарий 1: Создание архива для релиза

```bash
# Архив текущей ветки (HEAD)
git archive -o release.zip HEAD

# Архив конкретного тега
git archive -o v1.0.0.tar.gz v1.0.0

# Архив с префиксом внутри архива
git archive --prefix=myapp-1.0/ -o release.zip v1.0.0

# Архив конкретного каталога
git archive --prefix=src/ -o source.zip HEAD -- src/
```

**Валидация:**
```bash
# Проверить содержимое архива
unzip -l release.zip
# → ... (файлы без .git)
```

### Сценарий 2: Исключение файлов из архива

```bash
# Создать/отредактировать .gitattributes
echo "tests/ export-ignore" >> .gitattributes
echo ".gitignore export-ignore" >> .gitattributes
echo "*.md export-ignore" >> .gitattributes

# Теперь архив НЕ будет содержать эти файлы
git archive -o release.zip HEAD
```

**Валидация:**
```bash
unzip -l release.zip | grep "tests/"
# → (пусто — файлы исключены)
```

### Сценарий 3: Подстановка переменных в архиве

```bash
# В файле VERSION.txt:
# $Format:%(describe:tags=true)$

# При архивации переменная заменяется
git archive -o release.zip HEAD
# → Внутри VERSION.txt будет: v1.0.0-5-gabc1234
```

**Форматы подстановки:**
| Переменная | Результат |
| :--- | :--- |
| `%H` | Полный SHA-1 коммита |
| `%h` | Короткий SHA-1 |
| `%D` | Описание (describe) |
| `%t` | Тег (describe, tags=true) |
| `%ci` | Дата коммита (ISO) |

### Сценарий 4: Создание bundle для офлайн-передачи

```bash
# Упаковать весь репозиторий
git bundle create repo.bundle --all

# Упаковать конкретную ветку
git bundle create feature.bundle main

# Упаковать последние 10 коммитов ветки
git bundle create recent.bundle main~10..main

# Упаковать с тегами
git bundle create release.bundle --all --tags
```

**Валидация:**
```bash
# Проверить bundle
git bundle verify repo.bundle
# → repo.bundle is okay

# Посмотреть содержимое
git bundle list-heads repo.bundle
# → abc1234 refs/heads/main
# → def5678 refs/heads/feature
```

### Сценарий 5: Восстановление из bundle

```bash
# Клонировать из bundle
git clone repo.bundle restored-repo

# Или добавить как remote
cd existing-repo
git remote add bundle /path/to/repo.bundle
git fetch bundle
git merge bundle/main
```

### Сценарий 6: Инкрементальный bundle

```bash
# Первый bundle — полный
git bundle create full.bundle main

# Второй bundle — только дельта
git bundle create incremental.bundle main~5..main

# Проверить, что incremental зависит от full
git bundle verify incremental.bundle
# → incremental.bundle requires prerequisite: full.bundle
```

### Сценарий 7: Использование в CI/CD

```yaml
# GitHub Actions: создание архива
- name: Create release archive
  run: |
    git archive --prefix=myapp-${{ github.ref_name }}/ \
      -o myapp-${{ github.ref_name }}.zip HEAD

- name: Upload release
  uses: actions/upload-artifact@v4
  with:
    name: myapp-${{ github.ref_name }}
    path: myapp-${{ github.ref_name }}.zip
```

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: not a tree object` | Некорректный ref | Указать существующий тег или ветку |
| `fatal: not a valid bundle file` | Повреждённый bundle | Пересоздать bundle |
| `Repository lacks these prerequisite commits` | Инкрементальный bundle без base | Добавить base bundle через `git fetch` |
| Файлы не исключаются из архива | `.gitattributes` не закоммичен | Сделать `git add .gitattributes && git commit` |
| `fatal: bad bundle version` / `unknown capability` | Клиент старше 2.38 читает bundle v3 | Использовать `--version=2` или обновить Git |
| `--worktree-attributes` игнорируется | `.gitattributes` не в рабочем дереве | Закоммить `.gitattributes` или использовать `--worktree-attributes` с существующим файлом |
| `--add-file` добавляет файл, но он не в индексе | Файл временный, не коммитируется | Сознательный выбор: добавляется только в архив, не влияет на индекс |
| Инкрементальный bundle не применяется | Базовый bundle не загружен | Загрузить base bundle через `git fetch` перед `git pull` из инкрементального |
| `git archive` включает `.gitignore` | `export-ignore` не настроен | Добавить `.gitignore export-ignore` в `.gitattributes` и закоммить |
| `git bundle verify` показывает `requires prerequisite` | Bundle создан с prereq (например, `main~5..main`) | Иметь в репозитории коммиты от `main~5` до `main` |

### Best Practices

1. **Используйте `--prefix`** для архивов — чтобы файлы были в подпапке.
2. **Настройте `export-ignore`** в `.gitattributes` для исключения тестов/документации.
3. **Используйте bundle для оффлайн-передачи** — например, на air-gapped серверы.
4. **Проверяйте целостность bundle** — `git bundle verify` перед использованием. Подписи GPG/SSH для bundle **не существуют** (опция `--sign` отсутствует): аутентификация достигается через проверку SHA-256/SHA-512 хеша переданного файла или через GPG-подписанный external-архив (например, `tar czf repo.tar.gz repo.bundle && gpg --armor --sign repo.tar.gz`).
5. **Используйте формат v3** (`git bundle create --version=3`) для репозиториев с SHA-256 или для передачи фильтрованных объектов (`--filter=blob:none`) — v2 не поддерживает эти возможности.
6. **Ограничьте bundle-файл размером:** инкрементальные bundle должны опираться на предыдущий (через тег-маркер `lastR2bundle`), иначе получится дублирование данных.

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `git archive -o release.zip HEAD` | Архив HEAD без `.git` | `git archive -o release.zip HEAD` |
| `git archive -o v1.0.0.tar.gz v1.0.0` | Архив тега | `git archive -o v1.0.0.tar.gz v1.0.0` |
| `git archive --prefix=myapp-1.0/ -o release.zip v1.0.0` | Архив с префиксом | `git archive --prefix=myapp-1.0/ -o release.zip v1.0.0` |
| `git archive --worktree-attributes -o release.zip HEAD` | Учитывать `.gitattributes` рабочего дерева | `git archive --worktree-attributes -o release.zip HEAD` |
| `git archive --add-file=extra.txt -o release.zip HEAD` | Добавить файл не из индекса | `git archive --add-file=extra.txt -o release.zip HEAD` |
| `git archive --exec=/path/to/git-upload-archive -o release.zip HEAD` | Использовать внешний архиватор | `git archive --exec=/path/to/git-upload-archive -o release.zip HEAD` |
| `git bundle create repo.bundle --all` | Упаковать все refs | `git bundle create repo.bundle --all` |
| `git bundle create --version=3 repo.bundle --all` | Упаковать в формат v3 | `git bundle create --version=3 repo.bundle --all` |
| `git bundle create recent.bundle main~10..main` | Инкрементальный bundle | `git bundle create recent.bundle main~10..main` |
| `git bundle verify repo.bundle` | Проверить целостность | `git bundle verify repo.bundle` |
| `git bundle list-heads repo.bundle` | Список refs в bundle | `git bundle list-heads repo.bundle` |
| `git bundle unbundle repo.bundle` | Распаковать bundle | `git bundle unbundle repo.bundle` |
| `git clone repo.bundle restored-repo` | Клонировать из bundle | `git clone repo.bundle restored-repo` |
| `git remote add bundle /path/to/repo.bundle` | Добавить bundle как remote | `git remote add bundle /path/to/repo.bundle` |

## Автоматизация и мониторинг (SRE / DevOps-аспект)

Конфигурация Git — часть инфраструктуры, а не только личные предпочтения. Ключевые аспекты для автоматизированных сред:

- **Идентификация в CI/CD:** `user.name` / `user.email` для ботов (например, `github-actions[bot]`) задаются через `git config` в скрипте инициализации или через переменные окружения `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` / `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL`. Это исключает коммиты от случайного пользователя.
- **Хуки и безопасность:** `core.hooksPath` позволяет централизованно внедрять проверки (lint, тесты, секреты) в `.githooks/`. Каталог должен быть защищён от записи посторонних — модифицированный хук может украсть секреты или внести вредоносный код.
- **Мониторинг размера репозитория:** Утилита `git-sizer` анализирует размер репозитория и выявляет узкие места (количество объектов, pack-файлов, веток). Регулярный запуск в CI/CD позволяет ловить несанкционированный рост (например, при добавлении больших бинарных файлов).
- **Фоновое обслуживание:** `git maintenance start` с планировщиком (`maintenance.<task>.schedule`) заменяет ручной `git gc`. В shared-средах (multiuser-серверы) фоновый `git gc` конкурирует за I/O — ограничивайте расписание через `cron`/`systemd` timers с nice-приоритетом.
- **Блокировки ODB:** `git gc` и `git maintenance run` используют разную семантику блокировки object database. Не запускайте их параллельно на одном репозитории — один из процессов не выполнит задачи.
- **Доверенные директории (`safe.directory`):** В Docker-контейнерах и CI-runners репозиторий часто владеет другой пользователь. `safe.directory '*'` разрешает всё, что опасно в shared-средах; ограничивайте конкретными путями, где возможно.
- **Конфигурация и версионирование:** Настройки, специфичные для репозитория (`blame.ignoreRevsFile`, `core.hooksPath`, `safe.directory`), не передаются при `git clone`. Добавляйте их в скрипт инициализации (`setup.sh`) или в `.gitconfig` репозитория (если совместимость с Git < 2.20 не требуется).
- **Секреты в конфиге:** Никогда не храните пароли/токены в `~/.gitconfig` — файл бэкапируется и синхронизируется. Используйте credential helpers или переменные окружения (`GIT_ASKPASS`, `GITHUB_TOKEN`, `GITLAB_TOKEN`).

---

## Дополнительная информация

### Связанные темы

- [Git Attributes](./git_attributes.md) — export-ignore, export-subst для настройки архивов.
- [Git Tags](./git_tags.md) — архивы для релизов и интеграция с CI/CD.
- [Git Performance](./git_performance.md) — bundle URIs для кэширования и ускорения clone.
- [Синхронизация репозиториев](./git_synchronization.md) — офлайн-передача через bundle вместо push/pull.
- [Внутреннее устройство Git](./git_internals.md) — объекты, pack files и структура bundle.

### Официальные ресурсы

- **Git Archive Documentation:** [git-scm.com/docs/git-archive](https://git-scm.com/docs/git-archive)
- **Git Bundle Documentation:** [git-scm.com/docs/git-bundle](https://git-scm.com/docs/git-bundle)
- **Pro Git Book:** [git-scm.com/book/ru/v2/Git-инструменты](https://git-scm.com/book/ru/v2/Git-инструменты)
