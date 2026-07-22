# Git — внутреннее устройство

## Определения

**Git** — распределённая система контроля версий, представляющая собой **контентно-адресуемую файловую систему** (content-addressable filesystem) с интерфейсом VCS поверх неё. В основе лежит база данных объектов, к которым можно обращаться по SHA-1 хэшу.

**Хэш (SHA-1)** — 40-символьный шестнадцатеричный идентификатор (20 байт), вычисляемый от содержимого объекта + заголовка. Хэш является одновременно чексуммой и адресом объекта.

**Объектная модель Git** — четыре типа сущностей: blob, tree, commit, tag. Всё остальное (ветки, HEAD, теги) — указатели на эти объекты.

---

## Анатомия `.git/`

Критически важные компоненты (без них репозиторий не работает):

| Компонент | Обязателен | Назначение |
|-----------|-----------|------------|
| `HEAD` | Да | Указывает на текущую ветку или коммит |
| `objects/` | Да | База данных всех объектов (blob, tree, commit, tag) |
| `refs/` | Да | Директория с указателями (ветки, теги, удалённые refs) |

Опциональные компоненты:
- `config` — настройки репозитория
- `description` — описание (используется GitWeb)
- `hooks/` — примеры скриптов-хуков
- `info/` — вспомогательная информация (exclude, attributes)
- `branches/` — устаревшая директория (legacy)
- `logs/` — журнал reflog
- `index` — бинарный файл staging area
- `COMMIT_EDITMSG` — последнее сообщение коммита
- `packed-refs` — упакованные refs

```bash
# Проверка: без objects/ или HEAD Git перестаёт видеть репозиторий
rm -rf .git/objects
git status
# → fatal: not a git repository
```

### Эксперимент: минимальный репозиторий вручную

```bash
mkdir -p .git/objects .git/refs/heads
echo "ref: refs/heads/main" > .git/HEAD
git status
# → On branch main
# → No commits yet
```

Эти две команды воспроизводят `git init`. Git был создан за 10 дней как набор утилит на C, обёрнутых bash-скриптами.

---

## Четыре типа объектов

Git хранит четыре вида объектов в `.git/objects/`. Все они сжаты zlib и идентифицируются SHA-1 хэшем.

### Blob (Binary Large Object)

Хранит содержимое файла как есть. Не содержит имени файла — только данные.

```bash
# Просмотр blob напрямую
git cat-file -p <sha>
# → содержимое файла

# Тип объекта
git cat-file -t <sha>
# → blob
```

Формат хранимых данных: `blob <размер>\0<содержимое>`.

### Tree (Дерево)

Хранит структуру директории: отображение имён файлов в blob-хэши + права доступа. Аналог inode в файловых системах.

```bash
# Просмотр дерева
git cat-file -p <sha_tree>
# → 100644 blob a1b2c3d4    hello.txt
# → 100755 blob e5f6g7h8    script.sh
```

Запись в дереве: `<режим> <тип> <хэш>\t<имя>`.

### Commit (Коммит)

Снимок состояния проекта — ссылается на дерево и хранит метаданные.

```bash
git cat-file -p HEAD
# → tree <sha_дерева>
# → parent <sha_родителя>   # отсутствует у первого коммита
# → author Vasya <vasya@example.com> 1719000000 +0300
# → committer Vasya <vasya@example.com> 1719000000 +0300
# →
# → my new file
```

Поля коммита:
- `tree` — ссылка на корневое дерево проекта
- `parent` — ссылка на родительский коммит (один для обычного, два для merge, отсутствует для root-коммита)
- `author` — автор изменений (имя + email + timestamp)
- `committer` — кто создал коммит (может отличаться от автора при rebase/cherry-pick)
- Пустая строка
- Сообщение коммита

### Tag (Аннотированный тег)

Именованная ссылка на коммит с метаданными (аналог коммита, но указывает на коммит).

```bash
git cat-file -p <sha_тега>
# → object <sha_коммита>
# → type commit
# → tag v1.0
# → tagger Vasya <vasya@example.com> 1719000000 +0300
# →
# → Release v1.0
```

### Иерархия объектов

```
HEAD → refs/heads/main → commit (метаданные + сообщение)
                              │
                              ▼
                            tree (структура директорий)
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                 blob (file1)        blob (file2)
```

---

## Хранение объектов

### SHA-1 + zlib

Каждый объект перед записью:
1. Формируется заголовок: `blob <размер>\0` (аналог для tree/commit/tag)
2. Вычисляется SHA-1 хэш от конкатенации заголовка + данных
3. Всё сжимается zlib (уровень сжатия по умолчанию)

```bash
# Ручное создание blob
echo -n "hello git" | git hash-object --stdin -w
# → a1b2c3d4e5f6g7h8i9j0...

# Эмуляция через Python (для понимания)
python3 -c "
import hashlib, zlib
content = b'hello git'
header = f'blob {len(content)}'.encode() + b'\0'
sha = hashlib.sha1(header + content).hexdigest()
compressed = zlib.compress(header + content)
print(sha)
"
```

### Loose-объекты и структура директорий

Хэш разбивается: первые 2 символа — имя поддиректории, остальные 38 — имя файла:

```
.git/objects/a1/b2c3d4e5f6g7h8i9j0...
```

Это ускоряет поиск при большом количестве объектов, без логической группировки (коммиты, деревья и blob'ы находятся в одних и тех же директориях).

### Pack-файлы

При достижении ~6700 loose-объектов Git запускает упаковку в pack-файлы:
- `.pack` — сжатые данные с дельта-компрессией
- `.idx` — индекс для быстрого поиска по хэшу

В pack-файлах Git от дельты считает относительно базового объекта — это единственное место в Git, где используется дельта-компрессия (в отличие от SVN, где дельта — основной принцип). Концептуально Git остаётся snapshot-системой.

```bash
# Ручная упаковка
git gc

# Просмотр pack-файлов
ls .git/objects/pack/
# → pack-a1b2c3d4e5f6g7h8i9j0.idx
# → pack-a1b2c3d4e5f6g7h8i9j0.pack
```

Git — не фоновый сервис. Все операции (включая сборку мусора `git gc`) выполняются только при вызове команд пользователем.

---

## Указатели: HEAD, Refs, Branches

### HEAD

Простой текстовый файл `.git/HEAD`. Может быть в двух состояниях:

```bash
# Привязан к ветке
cat .git/HEAD
# → ref: refs/heads/main

# Detached HEAD — указывает напрямую на коммит
cat .git/HEAD
# → a1b2c3d4e5f6g7h8i9j0...
```

### Refs (ссылки)

Файлы в `refs/heads/`, `refs/tags/`, `refs/remotes/`, содержащие SHA-1 хэш:

```bash
cat .git/refs/heads/main
# → a1b2c3d4e5f6g7h8i9j0...
```

Ветки — это **перемещаемые указатели** на коммиты. При каждом новом коммите файл ветки обновляется.

**Аналогия с DNS:** SHA-1 — IP-адрес, refs — доменные имена. Разница: в DNS IP меняется редко, а refs (ветки) смещаются при каждом коммите.

### Анатомия switch / checkout

`git switch <branch>` меняет содержимое `.git/HEAD`:

```
HEAD → refs/heads/main → commit (текущий)
HEAD → refs/heads/feature → commit (после switch)
```

### Reflog

Журнал всех перемещений HEAD. Хранится в `.git/logs/`. Единственное средство восстановления после потери коммитов (до истечения срока хранения или запуска GC).

```bash
git reflog
# → a1b2c3d HEAD@{0}: commit: superfile added
# → e5f6g7h HEAD@{1}: checkout: moving from main to my-new-branch
# → i9j0k1l HEAD@{2}: commit: I by txt file
```

Reflog фиксирует каждое изменение HEAD, включая «холостые» переключения между ветками. Коммиты, на которые больше не ссылается ни одна ветка, остаются доступными через reflog до очистки.

### ORIG_HEAD

Файл `.git/ORIG_HEAD` — предыдущее положение HEAD перед опасными операциями (merge, reset). Автоматически создаётся Git.

---

## Staging Area (Index)

Индекс — бинарный файл `.git/index` с кастомным форматом. Хранит метаинформацию о файлах, готовых к следующему коммиту (путь, хэш blob, метаданные).

```bash
# Просмотр индекса
git ls-files --stage
# → 100644 a1b2c3d4 0       hello.txt
```

Staging area — исторически отдельная утилита в наборе Git (философия Unix: одна утилита — одна задача). Позволяет:
- Готовить драфт коммита
- Дробить изменения одного файла на несколько коммитов (через `git add -p`)
- Откатывать только часть изменений

---

## Git как DAG (Directed Acyclic Graph)

История Git — направленный ациклический граф. Каждый коммит движется вперёд, даже откат — это новый коммит впереди.

```bash
git log --oneline --graph --all
# → * a1b2c3d (HEAD -> feature) third commit
# → * e5f6g7h (main) second commit
# → * i9j0k1l initial commit
```

**Ключевые свойства:**
- Один хэш — одно содержимое навсегда (иммутабельность)
- Изменение файла = новый blob-объект
- Новый коммит = новый объект коммита с parent-ссылкой на предыдущий
- Ветки и теги — только указатели на существующие коммиты
- При `checkout` меняется HEAD, объекты не удаляются
- При `reset` переставляется указатель ветки, объекты остаются

---

## Низкоуровневые команды (plumbing)

| Команда | Назначение |
|---------|-----------|
| `git cat-file -p <sha>` | Просмотр содержимого объекта |
| `git cat-file -t <sha>` | Тип объекта |
| `git hash-object` | Вычисление хэша / запись blob |
| `git ls-tree <sha>` | Содержимое дерева |
| `git ls-files --stage` | Содержимое индекса |
| `git update-index` | Низкоуровневая работа с индексом |
| `git read-tree` | Чтение дерева в индекс |
| `git write-tree` | Запись дерева из индекса |
| `git commit-tree` | Создание коммита напрямую |
| `git rev-parse` | Преобразование ref → SHA-1 |
| `git gc` | Сборка мусора / упаковка в pack |
| `git fsck` | Проверка целостности объектов |
| `git count-objects` | Статистика loose-объектов |

---

## Процесс коммита под капотом

```bash
# 1. hash-object — создать blob
echo "hello git" | git hash-object -w --stdin
# → a1b2c3d4e5f6g7h8i9j0...

# 2. update-index — добавить в staging
git update-index --add --cacheinfo 100644 a1b2c3d4 hello.txt

# 3. write-tree — создать tree из индекса
git write-tree
# → b2c3d4e5f6g7h8i9j0...

# 4. commit-tree — создать commit
echo "initial commit" | git commit-tree b2c3d4e5 -p <parent_sha>

# 5. update-ref — передвинуть ветку
git update-ref refs/heads/main <commit_sha>
```

Обычный `git commit -m "..."` выполняет шаги 2–5 атомарно.

---

## Дополнительная информация

### Особенности и ограничения

- **Файлы большого размера:** Git не умеет считать дельты от blob'ов (в отличие от Perforce/SVN), поэтому большие бинарные файлы быстро раздувают репозиторий — используйте Git LFS.
- **Права доступа:** Внутри Git права хранятся (100644 — обычный, 100755 — исполняемый), но из-за различий между Unix и Windows могут «пропадать» при смене платформы.
- **Сборщик мусора:** `git gc` удаляет недостижимые объекты и упаковывает loose-объекты. Коммиты, на которые не указывает ни одна ссылка и которые вышли за пределы reflog, теряются безвозвратно.
- **Распространение:** Git не работает как фоновый сервис (нет `gitd`). Все операции — результат явного вызова команд пользователем.

### Связанные темы

- [Git — основы](./git_basics.md) — базовые концепции и команды
- [Управление ветками и слияние](./git_branching.md) — ветки, merge, rebase
- [Манипуляции с историей (Rebase, Amend)](./git_history_manipulation.md) — переписывание истории
- [Производительность Git](./git_performance.md) — commit-graph, shallow clone, Scalar
- [Git LFS](./git_lfs.md) — хранение больших файлов

### Официальные ресурсы

- **Pro Git — Git Internals:** [git-scm.com/book/ru/v2/Git-Internals-Plumbing-and-Porcelain](https://git-scm.com/book/ru/v2/Git-Internals-Plumbing-and-Porcelain)
- **Git Object Storage:** [git-scm.com/book/ru/v2/Git-Internals-Git-Objects](https://git-scm.com/book/ru/v2/Git-Internals-Git-Objects)
- **git cat-file docs:** [git-scm.com/docs/git-cat-file](https://git-scm.com/docs/git-cat-file)
