# Docker: Драйвер хранения OverlayFS

**Актуально для:** Docker 24.x–29.x, containerd 1.7.x–2.4.x

## Определения

- **OverlayFS**: Современная объединяющая файловая система (union filesystem), используемая Docker по умолчанию в большинстве дистрибутивов Linux. Она позволяет эффективно "накладывать" одну файловую систему поверх другой, создавая единое, целостное представление из нескольких слоев.
- **`lowerdir` (Нижние слои)**: Один или несколько каталогов, доступных **только для чтения**. В контексте Docker — это неизменяемые слои образа. Драйвер `overlay2` поддерживает до 128 нижних слоев.
- **`upperdir` (Верхний слой)**: Единственный каталог, доступный **для чтения и записи**. В контексте Docker — это записываемый слой контейнера (`container layer`), где фиксируются все изменения, сделанные во время работы.
- **`merged` (Объединенное представление)**: Виртуальное объединение всех `lowerdir` и одного `upperdir`. Это именно то, что видит процесс внутри контейнера как свою корневую файловую систему.
- **`workdir` (Рабочая директория)**: Служебная директория для атомарных операций (например, подготовки файлов при "copy-up"). Должна находиться на той же файловой системе, что и `upperdir`.
- **Copy-on-Write (CoW)**: Механизм, при котором данные копируются из нижних слоев в верхний только в момент первой попытки их модификации.

**Жизненный цикл данных:**
- `upperdir` **сохраняется** при остановке (`docker stop`) или перезагрузке (`docker restart`) контейнера.
- `upperdir` **безвозвратно удаляется** вместе с контейнером (`docker rm`).

## Основные концепции

Драйвер хранения `overlay2` является современным стандартом в Docker. Он реализует механизм слоеных образов с помощью OverlayFS, что обеспечивает высокую эффективность хранения и скорость запуска контейнеров.

### Принцип работы Copy-on-Write (CoW)

В основе эффективности `overlay2` лежит стратегия CoW.

- **Чтение (Read)**: Когда процесс внутри контейнера читает файл, существующий только в `lowerdir` (слоях образа), он получает к нему прямой и мгновенный доступ без каких-либо накладных расходов.

- **Запись/Изменение (Write/Modify)**:
  1. При первой попытке изменить файл из `lowerdir`, ядро перехватывает операцию.
  2. Выполняется операция **"copy up"**: файл копируется из `lowerdir` в `upperdir` (записываемый слой контейнера).
  3. Изменения вносятся в новую копию файла в `upperdir`. Оригинал в `lowerdir` остается нетронутым.
  4. Все последующие обращения к этому файлу будут направлены к его измененной версии в `upperdir`.

- **Удаление (Delete)**:
  1. Физически удалить файл из `lowerdir` нельзя, так как слои образа неизменяемы.
  2. Вместо этого в `upperdir` создается специальный маркер — **"whiteout"** файл (символьное устройство с мажорным/минорным номерами 0/0). Этот маркер скрывает оригинальный файл, и он перестает быть видимым в `merged` (файловой системе контейнера).

- **Работа с метаданными и атрибутами**:
  - Изменение только метаданных файла (например, `chmod`, `chown`, `utime`) также инициирует **copy-up** всего файла целиком. Это важно учитывать при массовых операциях с правами доступа в Dockerfile.
  - **Жесткие ссылки (Hard Link)**: Если файл в `lowerdir` имеет несколько жестких ссылок, то при copy-up ссылки разрываются. В `upperdir` попадает копия файла, которая больше не связана с другими ссылками из нижних слоев.

- **Opaque директории**:
  При удалении всей директории в контейнере, которая существовала в образе, OverlayFS создает в `upperdir` пустую директорию с расширенным атрибутом `trusted.overlay.opaque=y`. Это указывает драйверу полностью игнорировать содержимое этой директории во всех нижних слоях.

```
+---------------------------------+
| Merged View (ФС Контейнера)     | <--- То, что видит процесс
+---------------------------------+
                ^
  (запись идет в upperdir, copy-up из lowerdir)
                |
+---------------------------------+
| Upperdir (Слой контейнера R/W)  | <--- Все изменения здесь
+---------------------------------+
| Lowerdir[] (Слои образа RO)     | <--- Неизменяемые слои образа
+---------------------------------+
```

### Преимущества и технические особенности

- **Экономия места на диске**: Слои образа являются общими для всех контейнеров на хосте. Дублируются только измененные данные в `upperdir`.
- **Совместное использование Page Cache**: Поскольку нижние слои (`lowerdir`) неизменяемы, ядро Linux может кэшировать файлы из них в оперативной памяти и совместно использовать эти страницы кэша (Page Cache) между всеми контейнерами, использующими тот же образ. Это значительно снижает нагрузку на RAM.
- **Мгновенный запуск**: Docker не копирует файлы при старте, а лишь создает структуру директорий для нового `upperdir` и выполняет операцию `mount`.
- **Эффективность Inodes**: В отличие от старого драйвера `overlay`, который создавал жесткие ссылки для каждого файла в каждом слое, `overlay2` использует более эффективный механизм адресации, что предотвращает быстрое исчерпание лимита Inodes в файловой системе.

**Технические ограничения и нюансы:**
- **Максимальное количество слоев**: Хотя OverlayFS в ядре Linux теоретически поддерживает глубокую вложенность, Docker ограничивает стек `lowerdir` до **128 слоев**. Это связано с ограничением длины аргументов при вызове системного вызова `mount`.
- **Производительность (Page Cache)**: При copy-up файла в `upperdir`, закэшированные страницы старого файла в Page Cache не используются для нового файла. Это может привести к временному всплеску потребления памяти и I/O при массовом изменении файлов сразу после запуска контейнера.
- **Отсутствие поддержки разреженных файлов (Sparse files)**: При copy-up разреженного файла он превращается в обычный файл в `upperdir`, полностью занимая место на диске.

### Требования к базовой файловой системе

Для корректной работы `overlay2` файловая система хоста (обычно `/var/lib/docker/`) должна поддерживать параметр **`d_type`**.

- **XFS**: Обязательно должна быть отформатирована с опцией `ftype=1`. В противном случае Docker может вести себя непредсказуемо (например, некорректно удалять файлы).
- **EXT4**: Поддерживает `d_type` по умолчанию.
- **Ядро Linux**: Требуется версия 4.0 или выше (для большинства дистрибутивов) или 3.10.0-514 и выше для RHEL/CentOS 7.2+.

## Предварительные требования

Перед работой с OverlayFS убедитесь, что окружение соответствует требованиям.

### Аппаратные и программные требования

- **Ядро Linux**: версия **4.0+** для базовой поддержки OverlayFS; версия **4.18+** для работы `overlay2` поверх `overlay2` (вложенный overlay, Docker-in-Docker); версия **5.11+** для нативного `overlay` в rootless-режиме; версия **5.13+** для rootless overlay с SELinux. В production-средах 2026 года преобладают ядра **6.x**.
- **Docker Engine**: **20.10+** (стабильная поддержка `overlay2`); **24.0+** (рекомендуется для cgroups v2 и современных функций); **29.0+** для containerd snapshotter по умолчанию. Локально установлен Docker **29.8.1**.
- **Файловая система** для `/var/lib/docker/` или `/var/lib/containerd/`:
  - **XFS**: обязательно `ftype=1`; рекомендуется `reflink=1` для ускорения сборки образов.
  - **EXT4**: поддерживается по умолчанию.
  - **Btrfs**: поддерживается, но имеет особенности CoW для баз данных.
  - **F2FS**: поддерживается, но менее распространена на серверах.
- **Доступ к хосту**: для инспекции путей `lowerdir`/`upperdir`/`merged` требуются права `root` (или доступ к Rootless-каталогу `~/.local/share/docker`).

### Проверка окружения

```bash
# Проверка версии ядра
uname -r
# → 5.15.0-xx-generic (должен быть ≥ 4.0)

# Проверка storage driver
docker info | grep "Storage Driver"
# → Storage Driver: overlay2

# Проверка версии Docker
docker --version
# → Docker version 29.8.1, build 4a63305

# Проверка d_type для XFS
xfs_info /var/lib/docker | grep ftype
# → naming   =version 2              bsize=4096   ascii-ci=0 ftype=1

# Проверка режима cgroups
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs
```

## Практические сценарии

### Сценарий 1: Проверка используемого драйвера хранения

Вы можете легко проверить, какой storage driver использует ваш Docker.

```bash
docker info | grep "Storage Driver"
# Ожидаемый вывод: Storage Driver: overlay2
```

### Сценарий 2: Исследование слоев на хосте

Давайте на практике посмотрим, как работает CoW.

1. **Запустим простой контейнер:**

    ```bash
    docker run -d --name overlay-test alpine:latest sleep 3600
    ```

2. **Найдем директории контейнера:**
    С помощью `docker inspect` можно найти пути к `lowerdir`, `upperdir` и `merged` в файловой системе хоста (`/var/lib/docker/overlay2`).

    ```bash
    docker inspect overlay-test | grep -E "LowerDir|UpperDir|MergedDir|WorkDir"
    
    # Примерный вывод:
    # "MergedDir": "/var/lib/docker/overlay2/a1b2c3d4.../merged",
    # "UpperDir": "/var/lib/docker/overlay2/a1b2c3d4.../diff",
    # "WorkDir": "/var/lib/docker/overlay2/a1b2c3d4.../work",
    # "LowerDir": "/var/lib/docker/overlay2/e5f6g7h8.../diff"
    ```

3. **Создадим новый файл в контейнере:**

    ```bash
    docker exec overlay-test touch /new_file_in_container.txt
    ```

4. **Проверим `upperdir` на хосте:**
    Теперь, если мы посмотрим на содержимое `UpperDir` на хосте (путь из шага 2), мы увидим там наш новый файл.

    ```bash
    # Путь из вывода docker inspect
    sudo ls /var/lib/docker/overlay2/a1b2c3d4.../diff
    
    # Вывод:
    # new_file_in_container.txt
    ```

    Это демонстрирует, что все изменения, сделанные в контейнере, записываются в его `upperdir`.

### Сценарий 3: Проверка поддержки d_type (для XFS)

Если ваша базовая файловая система — XFS, крайне важно убедиться, что она поддерживает `d_type`.

```bash
# Проверка параметров монтирования
xfs_info /var/lib/docker | grep ftype

# Ожидаемый вывод:
# naming   =version 2              bsize=4096   ascii-ci=0 ftype=1
```

Если `ftype=0`, вам необходимо пересоздать файловую систему с параметром `-n ftype=1`. Без этого `overlay2` не сможет корректно обрабатывать удаление файлов (whiteouts).

### Сценарий 4: Где именно OverlayFS применяется в процессе сборки образа

OverlayFS используется **на каждом шаге `docker build`**, а не только при запуске контейнера.

#### Этап 1: Сборка — OverlayFS как временная рабочая среда

Когда Docker выполняет `docker build`, для **каждой инструкции** `Dockerfile` (`RUN`, `COPY`, `ADD`) происходит следующее:

```
Dockerfile:
  FROM ubuntu:22.04        # Шаг 1: берём базовый образ (слои RO)
  RUN apt-get update       # Шаг 2: выполняем команду
  COPY app.py /app/        # Шаг 3: копируем файлы
  RUN pip install flask    # Шаг 4: устанавливаем зависимости
```

**Что происходит под капотом на каждом шаге:**

1. Docker берёт все предыдущие слои (commit-ы) как `lowerdir[]` (только чтение).
2. Создаёт **новый пустой `upperdir`** — временный записываемый слой.
3. Монтирует OverlayFS: `lowerdir[] + upperdir -> merged`.
4. Запускает команду (`RUN apt-get update`) **внутри этого merged-представления**.
5. После выполнения команды Docker **фиксирует (commit)** `upperdir` как **новый неизменяемый слой** (слой образа).
6. Повторяет процесс для следующей инструкции — новый `upperdir`, новые `lowerdir[]` (включая только что закоммиченный слой).

```
Шаг N сборки:
┌─────────────────────────────────────────┐
│  Merged (временный, для выполнения RUN)  │
├─────────────────────────────────────────┤
│  Upperdir (временный R/W)               │ # сюда пишется результат RUN
├─────────────────────────────────────────┤
│  Lowerdir[0]: слой FROM ubuntu          │ # RO, уже закоммичен
│  Lowerdir[1]: слой RUN apt-get update   │ # RO, уже закоммичен
│  Lowerdir[2]: слой COPY app.py /app/    │ # RO, уже закоммичен
└─────────────────────────────────────────┘
```

#### Этап 2: Commit — превращение upperdir в слой

После выполнения команды Docker:

1. **Фиксирует содержимое `upperdir`** как новый слой в хранилище образов.
2. Слой становится **неизменяемым** (read-only) — он больше не будет изменён.
3. Временный `upperdir` и `workdir` **удаляются**.
4. Новый слой добавляется в стек `lowerdir[]` для следующей инструкции.

**Ключевой момент:** Каждый `RUN` = один OverlayFS mount -> один commit -> один слой. Поэтому:

```dockerfile
# ПЛОХО: 3 слоя, 3 раза mount overlay, 3 commit
RUN apt-get update
RUN apt-get install -y nginx
RUN rm -rf /var/lib/apt/lists/*

# ХОРОШО: 1 слой, 1 mount, 1 commit
RUN apt-get update && \
    apt-get install -y nginx && \
    rm -rf /var/lib/apt/lists/*
```

#### Этап 3: Запуск контейнера — финальное применение

После того как образ собран (все слои закоммичены), при `docker run`:

1. Все слои образа становятся `lowerdir[]` (неизменяемые).
2. Создаётся **один новый `upperdir`** — записываемый слой контейнера.
3. Монтируется финальный OverlayFS: `lowerdir[] + upperdir -> merged`.
4. Процесс внутри контейнера работает с `merged`.

#### Итого: где именно OverlayFS участвует

| Фаза | OverlayFS роль | Сколько раз |
| :--- | :--- | :--- |
| **`docker build` (каждый `RUN`/`COPY`/`ADD`)** | Временный merged для выполнения команды | N раз (по числу инструкций) |
| **[`docker commit`](./docker_commit.md)** | Фиксация `upperdir` как нового слоя | N раз (после каждой инструкции) |
| **`docker pull`** | Распаковка слоёв на диск (без overlay) | 1 раз (слои скачиваются, overlay не монтируется) |
| **`docker run`** | Финальный merged: слои образа + writable layer | 1 раз на контейнер |
| **Жизнь контейнера** | CoW: запись в upperdir, whiteout при удалении | Постоянно |

#### Почему это важно понимать

- **Кэш слоёв**: Docker кэширует результат каждого шага. Если `Dockerfile` не изменился — Docker **пропускает** выполнение и берёт готовый слой из кэша. OverlayFS не монтируется — слой просто подключается как `lowerdir`.
- **Размер образа**: Каждый `RUN` создаёт отдельный слой. Файлы, удалённые в следующем `RUN`, **не уменьшают размер образа** — они всё ещё есть в нижнем слое.
- **BuildKit**: Современный BuildKit (`DOCKER_BUILDKIT=1`) оптимизирует этот процесс — выполняет шаги в изолированных sandbox, не всегда используя полный OverlayFS mount, но результат тот же: каждый шаг = слой.

### Сценарий 5: Ручное монтирование OverlayFS (отладка)

```bash
# Создание директорий для демонстрации
sudo mkdir -p /mnt/overlay-demo/{lower,upper,work,merged}

# Создание файла в нижнем (read-only) слое
echo "lower-content" | sudo tee /mnt/overlay-demo/lower/hello.txt

# Монтирование OverlayFS
sudo mount -t overlay overlay \
  -o lowerdir=/mnt/overlay-demo/lower,upperdir=/mnt/overlay-demo/upper,workdir=/mnt/overlay-demo/work \
  /mnt/overlay-demo/merged

# Чтение из merged (видит lower)
cat /mnt/overlay-demo/merged/hello.txt
# → lower-content

# Запись в merged (пишется в upper)
echo "upper-change" | sudo tee /mnt/overlay-demo/merged/world.txt

# Проверка upperdir
sudo ls /mnt/overlay-demo/upper/
# → world.txt

# Очистка
sudo umount /mnt/overlay-demo/merged
sudo rm -rf /mnt/overlay-demo
```

**Валидация:** файл `world.txt` появился только в `upperdir`, при этом `lowerdir` остался неизменным. Это демонстрирует механизм CoW на уровне ядра Linux без Docker.

### Сценарий 6: Диагностика проблем с nested overlay и rootless

При запуске Docker внутри Docker или в rootless-средах может потребоваться `fuse-overlayfs`:

```bash
# Проверка, какой драйвер использует внутренний демон DinD
docker exec dind-container docker info | grep "Storage Driver"
# → Storage Driver: overlay2

# Если overlay2 не работает, проверьте поддержку в ядре:
docker exec dind-container uname -r
# Должен быть ≥ 4.18 для overlay2 поверх overlay2

# Альтернатива для rootless: fuse-overlayfs
dockerd-rootless-setuptool.sh install
# → Устанавливает fuse-overlayfs как драйвер для rootless-окружения

# Проверка драйвера после установки
docker info | grep "Storage Driver"
# → Storage Driver: fuse-overlayfs
```

## Валидация

После любого изменения конфигурации storage driver или файловой системы выполните проверку:

```bash
# 1. Storage driver активен и поддерживает overlay2
docker info | grep -E "Storage Driver|overlay2"
# → Storage Driver: overlay2

# 2. Контейнер запускается и монтирует overlay
docker run -d --name overlay-validation-test alpine sleep 3600
docker inspect overlay-validation-test | grep -E "LowerDir|UpperDir|MergedDir|WorkDir"
# Должны присутствовать все четыре директории в /var/lib/docker/overlay2/...
# При containerd snapshotter пути начинаются с /var/lib/containerd/...

# 3. CoW работает: изменение файла в контейнере затрагивает только upperdir
docker exec overlay-validation-test sh -c "echo 'test' > /etc/test_cow.txt"
docker inspect --format '{{.GraphDriver.Data.UpperDir}}' overlay-validation-test
sudo ls $(docker inspect --format '{{.GraphDriver.Data.UpperDir}}' overlay-validation-test)/etc/test_cow.txt
# → /etc/test_cow.txt

# 4. d_type поддерживается (для XFS)
xfs_info /var/lib/docker | grep ftype
# → ftype=1

# 5. Лимит слоев не превышен
docker history alpine:latest | wc -l
# → число должно быть разумным (< 100 для большинства образов)

# 6. Нет ошибок в ядерном логе
dmesg | grep -i overlay
# → чистый вывод (без ошибок "overlay: ... failed")

# 7. Проверка inodes на файловой системе
df -i /var/lib/docker
# → IUse% должен быть низким (< 80%)

# 8. Проверка дискового пространства (SRE)
docker system df -v
# → VOLUMES    ...    SIZE
# → IMAGES     ...    SIZE
# → Containers ...    SIZE
df -h /var/lib/docker
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1       20G  8.5G   11G  45% /var/lib/docker

# 9. Проверка работы whiteout (опционально)
docker run --rm -it alpine sh -c "rm -f /etc/hostname && ls -la /etc"
# → hostname отсутствует (скрыт whiteout), остальные файлы на месте
```

Очистка тестового контейнера:
```bash
docker rm -f overlay-validation-test
```

## Устранение неполадок

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`too many levels of symbolic links`** | Превышен лимит 128 нижних слоев (`lowerdir`) в `overlay2`. | Уменьшите число слоев (объедините `RUN` через `&&`, используйте multi-stage builds). При необходимости перейдите на `fuse-overlayfs` в rootless-режиме. |
| **`cannot mount overlay: invalid argument`** или **`workdir` ошибка** | `workdir` и `upperdir` находятся на разных файловых системах; или `d_type` не поддерживается (XFS с `ftype=0`). | Убедитесь, что обе директории на одной ФС; проверьте `xfs_info /var/lib/docker \| grep ftype`. Если `ftype=0` — пересоздайте ФС с `ftype=1`. |
| **`no space left on device`** (OverlayFS) | Диск заполнен или исчерпаны inodes на файловой системе `/var/lib/docker`. | Проверьте `df -h` и `df -i`; очистите неиспользуемые ресурсы (`docker system prune -a --volumes`). |
| **`permission denied` при монтировании overlay** | Пользователь не имеет прав `CAP_SYS_ADMIN` (требуется для `mount`), или SELinux блокирует операцию. | Для rootless-режима используйте `fuse-overlayfs`; проверьте `getenforce` и добавьте `:z`/`:Z` для bind mounts. |
| **Данные теряются после перезагрузки хоста** | Том/tmpfs или overlay хранился на непостоянном носителе; или контейнер был удалён. | Используйте именованные тома (`type=volume`) на постоянном диске; помните: `upperdir` удаляется вместе с контейнером (`docker rm`). |
| **Whiteout не работает (удалённый файл всё ещё виден)** | Используется драйвер `overlay` (устаревший) вместо `overlay2`, или базовая ФС не поддерживает `d_type`. | Переключитесь на `overlay2`; проверьте `docker info | grep "Storage Driver"`. |
| **Медленная запись / высокая задержка CoW** | Большие файлы копируются из `lowerdir` в `upperdir` при первой записи (copy-up). | Вынесите интенсивно изменяемые данные в **[тома (volumes)](./docker_volumes.md)**; избегайте хранения БД и логов в writable layer. |
| **`docker build` падает с ошибкой overlay** | В BuildKit используется `fuse-overlayfs` без поддержки в ядре, или не хватает прав для монтирования. | Проверьте, что BuildKit работает в том же окружении, что и демон; для DinD используйте официальный образ `docker:dind` с настроенным `overlay2`. |
| **containerd snapshotter: слои занимают диск дважды** | Включён режим `containerd-snapshotter` (Docker 29.0+); слои хранятся в content store и snapshotter. | Это ожидаемое поведение; для экономии места используйте `docker system prune` и настройте GC в BuildKit. |
| **`docker inspect` показывает пустые `LowerDir`/`UpperDir`** | Контейнер в состоянии `RemovalInProgress`/`Dead`, или используется `--read-only` с `tmpfs` без overlay. | Проверьте `docker inspect --format '{{.State.Status}}' <id>`; для `--read-only` контейнеры без writable layer не имеют `UpperDir`. |
| **SELinux блокирует запись в bind mount** | Отсутствуют метки `:z` (shared) или `:Z` (private) при монтировании. | Добавьте `:z` или `:Z` к опции монтирования; проверьте `getenforce`. |
| **Rootless: `overlay` не доступен** | Ядро < 5.11 или недостаточно прав для нативного overlay. | Используйте `dockerd-rootless-setuptool.sh install` для установки `fuse-overlayfs`. |
| **Исчерпание inodes (`df -i` показывает 100%)** | Слишком много мелких файлов в слоях или контейнерах (миллионы). | Очистите неиспользуемые ресурсы (`docker system prune -a --volumes`); при необходимости пересоздайте ФС с большим лимитом inodes. |
| **Page Cache сжирает RAM после массового copy-up** | При запуске большого числа контейнеров одновременно ядро кэширует страницы из lowerdir. | Ожидаемое поведение; при нехватке RAM ядро вытесняет кеш. Настройте `vm.swappiness=10` и ограничьте `memory.max` для групп контейнеров. |
| **`docker build` очень медленный на XFS без `reflink=1`** | Файловая система XFS создана без поддержки reflinks; copy-up происходит через полное копирование. | Пересоздайте ФС с опцией `-m reflink=1` или используйте `cp --reflink` для ускорения. |
| **`docker history` показывает `<missing>` для локальных слоёв** | Слой собран в BuildKit или импортирован из реестра без локальной метаданной. | Нормальное поведение для современных сборок. Полные данные видны после локальной сборки с `--no-cache`. |
| **Вложенный overlay в DinD нестабилен** | Ядро хоста не поддерживает nested overlay или не хватает прав `CAP_SYS_ADMIN`. | Проверьте `uname -r` ≥ 4.18; запускайте DinD с `--privileged` или предоставьте нужные capabilities. |
| **Containerd snapshotter: `docker system df` показывает меньше, чем реально** | Часть данных хранится в `/var/lib/containerd` и не учитывается в summary `docker system df`. | Используйте `docker system df -v` для детализации; дополнительно проверяйте `df -h /var/lib/containerd`. |

## Рекомендации и очистка

### Рекомендации

1. **Предпочитайте `overlay2` устаревшим драйверам**. `overlay`, `aufs` и `devicemapper` имеют ограничения по производительности, количеству слоев или поддерживаемым ФС. `overlay2` — стандарт де-факто с Docker 1.13+.
2. **Используйте XFS с `ftype=1` и `reflink=1`**. Это обеспечивает корректную работу whiteout и ускоряет сборку образов за счёт reflinks (Copy-on-Write на уровне файлов).
3. **Минимизируйте количество слоев**. Каждый `RUN` в Dockerfile создаёт слой. Объединяйте команды через `&&`, используйте multi-stage builds. Цель — держать число слоев в разумных пределах (< 50 для production-образов), чтобы не приближаться к лимиту 128.
4. **Не храните изменяемые данные в writable layer**. Для баз данных, логов и кэша используйте **[тома (volumes)](./docker_volumes.md)** или bind mounts. Это обходит CoW и обеспечивает нативную производительность.
5. **Настраивайте ротацию логов**. Если приложение пишет логи в writable layer, используйте логи-драйверы (`json-file` с `max-size`, `local`) или ограничивайте размер файлов, чтобы том не разрастался бесконтрольно.
6. **В rootless-режиме используйте `fuse-overlayfs`** при необходимости. На ядрах Linux < 5.11 нативный overlay недоступен без привилегий; `fuse-overlayfs` работает в userspace, но с меньшей производительностью.
7. **Для Docker Desktop (Mac/Windows)** помните, что OverlayFS работает внутри VM (HyperKit/WSL2). Named volumes находятся внутри VM и недоступны напрямую из хоста; производительность bind mounts ниже, чем у named volumes.
8. **Мониторинг диска**: на хостах с большим количеством контейнеров (CI-раннеры, оркестраторы) регулярно проверяйте `docker system df -v` и `df -h /var/lib/docker`. Установите алерты на рост `Reclaimable` в разделе `IMAGES` и `CONTAINERS`, а также на заполнение раздела, на котором хранятся слои. Для Docker 29+ с containerd snapshotter также мониторьте `/var/lib/containerd`.
9. **Мониторинг inodes**: отслеживайте `IUse%` через `df -i /var/lib/docker`. Высокое значение indicates риск отказа overlay2 из-за исчерпания inodes. Настройте алерты при `IUse% > 80%`.
10. **CI/CD**: для кэширования зависимостей в пайплайнах используйте BuildKit cache mounts (`--mount=type=cache`) или registry-backed кэш (`--cache-to type=registry`), а не локальные bind mounts на хост-директорию — это обеспечивает изоляцию и переносимость между раннерами.
11. **Политика очистки**: настройте `docker system prune` по расписанию (cron) или используйте TTL-метки (`--filter "until=24h"`) для автоматического удаления неиспользуемых ресурсов в dev-средах. В production используйте registry lifecycle policies для удаления устаревших тегов.
12. **Аудит слоёв**: периодически запускайте `docker system df -v` и `docker history` для неиспользуемых образов, чтобы обнаружить "мертвые" слои, оставшиеся после пересборки. На хостах с containerd snapshotter проверяйте оба пути: `/var/lib/docker` и `/var/lib/containerd`.

### Очистка

```bash
# Показать использование диска томами и образами
docker system df -v

# Удалить все неиспользуемые тома (dangling)
docker volume prune

# Удалить неиспользуемые тома старше 24 часов
docker volume prune --filter "until=24h"

# Удалить висячие (dangling) образы
docker image prune

# Удалить все неиспользуемые образы (не привязанные к контейнерам)
docker image prune -a

# Очистка Build Cache (BuildKit)
docker buildx prune -a

# Полная очистка всех неиспользуемых ресурсов
docker system prune -a --volumes

# Принудительное удаление зависшего контейнера и его тома
docker rm -f <container_id>
docker volume rm <volume_name>
```

## Граничные случаи

### Лимит 128 слоев

OverlayFS ограничивает стек `lowerdir` до 128 элементов. При превышении возникает ошибка `too many levels of symbolic links`.

**Диагностика:**
```bash
docker history my-app:latest | wc -l
# → если > 120 — риск превышения лимита
```

**Решение:** Уменьшите число слоев (объедините `RUN`, используйте multi-stage builds) или примените `docker-slim` / `--squash` (с потерей кэшируемости).

### Rootless Docker и fuse-overlayfs

В rootless-режиме (`dockerd-rootless.sh`) нативный overlay требует ядра 5.11+ (для SELinux — 5.13+). На более старых ядрах или при проблемах с правами используется `fuse-overlayfs`:

```bash
# Установка fuse-overlayfs для rootless
dockerd-rootless-setuptool.sh install

# Проверка драйвера
docker info | grep "Storage Driver"
# → Storage Driver: fuse-overlayfs
```

**Особенности:** `fuse-overlayfs` работает в userspace, поэтому производительность ниже нативного overlay2. Подходит для development-сред и CI, но для production с высокой нагрузкой предпочтителен rootful `overlay2`.

### Docker Desktop (Mac/Windows)

На не-Linux хостах Docker работает внутри VM (HyperKit на macOS, WSL2 на Windows):

- **Пути на хосте**: bind mounts (`/Users/mac/...`) транслируются во внутреннюю ФС VM. Named volumes остаются внутри VM и недоступны напрямую из хоста.
- **Производительность**: запись в bind mounts на macOS/Windows может быть в разы медленнее, чем в named volumes, из-за транслирования системных вызовов через гостевую ОС.
- **Shared Mounts**: на macOS требуется настройка файлового доступа (Settings → Resources → File Sharing).

### Вложенный Overlay (Docker-in-Docker)

При запуске `docker:dind` overlay2 монтируется поверх уже существующего overlay2 хоста:

- Требуется ядро Linux **4.18+**.
- В образе `docker:dind` по умолчанию настроен `overlay2`.
- Если возникают проблемы с производительностью или стабильностью, проверяйте поддержку nested overlay на хосте.

### SELinux и метки

На системах с SELinux (RHEL, CentOS, Fedora, Ubuntu по умолчанию) OverlayFS требует корректных меток:

```bash
# Общий доступ (shared) для bind mount
docker run -v /host/data:/container/data:z nginx

# Эксклюзивный доступ (private) для bind mount
docker run -v /host/data:/container/data:Z nginx

# Проверка режима SELinux
getenforce
# → Enforcing
```

Без `:z`/`:Z` контейнер может получить `permission denied` при доступе к файлам, даже если права Unix (`chmod 777`) корректны.

### Containerd Snapshotter (Docker 29.0+)

Начиная с Docker 29.0, по умолчанию используется containerd со snapshotters (overlayfs):

- **Место хранения образов**: `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/` вместо `/var/lib/docker/overlay2/`. Тома продолжают храниться в `/var/lib/docker/volumes/`.
- **Принцип работы**: вместо классического драйвера `overlay2`, управляемого напрямую демоном Docker, используется механизм снапшотов containerd.
- **Дублирование данных**: слои хранятся дважды — в сжатом виде (content store) и в распакованном (snapshotter). Это упрощает интеграцию с CRI-раннерами, но требует больше дискового пространства.
- **Мониторинг**: для отслеживания потребления диска используйте `docker system df -v` и проверяйте оба пути: `/var/lib/docker` и `/var/lib/containerd`.
- **Классический режим**: если feature flag отключён, продолжает использоваться `overlay2` по пути `/var/lib/docker/overlay2/`.

### Ограничение inodes

В отличие от старого драйвера `overlay`, `overlay2` не создаёт жёстких ссылок для каждого файла в каждом слое, поэтому не исчерпывает inodes так быстро. Однако при очень большом количестве мелких файлов (миллионы) inodes могут закончиться:

```bash
# Проверка использования inodes
df -i /var/lib/docker
# → Filesystem     Inodes  IUsed  IFree IUse% Mounted on
# → /dev/sda1      655360  61200 594160    10% /var/lib/docker
```

### Whiteout и прозрачность

- **Whiteout** (символьное устройство 0/0) скрывает файл из нижнего слоя.
- **Opaque directory** (`trusted.overlay.opaque=y`) скрывает всю директорию из нижних слоев.
- **Важно:** whiteout не удаляет файл физически — он остаётся в нижнем слое и виден через `docker save`/`docker export`. Для удаления секретов из слоёв используйте multi-stage builds или `docker-slim`.

### Размер `upperdir` и дисковое пространство

Записываемый слой (`upperdir`) может неожиданно разрастаться из-за:
- Логов приложения, пишущих в корень контейнера.
- Временных файлов сборки, не удалённых в том же `RUN`.
- Кэша пакетных менеджеров (`apt`, `npm`, `pip`).

**Решение:** Выносите данные в volumes, используйте `--tmpfs` для временных путей, настраивайте ротацию логов.

### BuildKit и overlay

BuildKit (`DOCKER_BUILDKIT=1`) использует оптимизированный механизм сборки, но результат тот же: каждый шаг `Dockerfile` создаёт слой. BuildKit может использовать `fuse-overlayfs` в certaines окружениях (например, DinD), что требует проверки поддержки в ядре.

**Для SRE:** на CI-раннерах с ограниченным диском используйте `--mount=type=cache` для кэширования зависимостей вместо создания их в слоях образа. Это сокращает размер образа и ускоряет сборку.

### Live-restore и overlay

При включённом `live-restore` в `daemon.json` контейнеры продолжают работать после перезапуска демона Docker. В этом случае:
- `upperdir` контейнера остаётся примонтированным, даже если демон перезапущен.
- При остановке контейнера `upperdir` размонтируется, но данные сохраняются.
- При удалении контейнера (`docker rm`) `upperdir` удаляется безвозвратно, независимо от `live-restore`.

## Дополнительная информация

### Производительность и лучшие практики

Механизм Copy-on-Write не является бесплатным. Операция "copy up" вносит задержку и потребляет дисковые I/O. Поэтому для рабочих нагрузок с интенсивной записью (например, базы данных, активное логирование, сборка артефактов) **категорически не рекомендуется** хранить данные в записываемом слое контейнера.

**Лучшая практика:** Для данных, которые часто изменяются, всегда используйте **[тома (volumes)](./docker_volumes.md)**. Volumes монтируются напрямую в файловую систему контейнера, обходя механизм OverlayFS и CoW, что обеспечивает нативную производительность дисковых операций.

### SRE/DevOps: мониторинг и эксплуатация

**Ключевые метрики для мониторинга overlay2:**
- **Дисковое пространство**: `docker system df -v` показывает использование по образам, контейнерам и томам. В production-средах настройте алерты на рост `Reclaimable` > 20% или заполнение раздела `/var/lib/docker` > 80%.
- **Inodes**: `df -i /var/lib/docker` — отслеживайте `IUse%`. Высокое значение указывает на риск отказа overlay2 из-за исчерпания inodes. Типичные виновники: миллионы мелких файлов в контейнерах, неограниченная ротация логов Docker, утечки временных файлов.
- **Page Cache**: при массовом copy-up (запуск множества контейнеров одновременно) наблюдается всплеск потребления RAM. Ядро Linux автоматически вытесняет кеш при нехватке памяти; мониторьте `memory.stat` cgroups v2 для detection pressure.
- **Количество слоёв**: `docker history <image> | wc -l` — поддерживайте < 50 для production-образов. Приближение к 128 требует немедленной оптимизации.

**Автоматизация очистки:**
```bash
# Ежедневный cron для dev-сред
0 2 * * * docker system prune -a --volumes --filter "until=24h" -f

# На self-hosted CI-раннерах: после каждого job
docker buildx prune -f --filter "until=1h"
docker image prune -a -f --filter "until=24h"
```

**Для SRE:** на хостах с большим количеством контейнеров (оркестраторы, CI-раннеры) настройте мониторинг диска и inodes. Используйте `docker system df -v` для детального анализа; `docker system df` показывает только summary.

### Сравнение с другими драйверами

- **`overlay` vs `overlay2`**: `overlay2` является современным стандартом. Старый драйвер `overlay` имел серьезные проблемы с исчерпанием `inode`, особенно при большом количестве слоев, и его использование не рекомендуется.
- **`aufs`**: Исторически первый union-драйвер в Docker. Никогда не был включен в основное ядро Linux, что усложняло его поддержку.
- **`devicemapper`**: Работает на блочном уровне, а не на файловом. Требует сложной предварительной настройки LVM (`direct-lvm`) и показывает меньшую производительность для типичных контейнерных нагрузок по сравнению с `overlay2`.
- **containerd snapshotter**: Начиная с Docker 29.0, по умолчанию используется containerd со snapshotters (overlayfs), который является современным стандартом для containerd.
  - **Место хранения**: Слои образов перемещены в `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/`.
  - **Принцип работы**: Вместо классического драйвера `overlay2`, управляемого напрямую демоном Docker, используется механизм снапшотов containerd.
  - **Дублирование данных**: В этом режиме слои могут храниться на диске дважды: сначала в сжатом виде (content store), затем в распакованном виде (snapshotter) для использования в контейнерах. Это упрощает интеграцию с CRI, но требует больше дискового пространства.
   - Для классического Docker daemon (с отключенным feature flag `containerd-snapshotter`) по-прежнему используется `overlay2` и путь `/var/lib/docker/overlay2`.

**Матрица выбора storage driver:**

| Драйвер | Когда использовать | Когда НЕ использовать | Особенности |
| :--- | :--- | :--- | :--- |
| **overlay2** | Default choice для Linux (ядро ≥ 4.18); production-нагрузки | Ядро < 4.18 без fuse-overlayfs; SELinux на ядре < 5.13 | Стандарт де-факто; требует `d_type` (XFS с `ftype=1`); лимит 128 lowerdir |
| **fuse-overlayfs** | Rootless Docker на ядрах < 5.11; DinD без привилегий | Production с высокой нагрузкой I/O | Работает в userspace; медленнее нативного overlay2 |
| **btrfs** | Хост на Btrfs; нужны снапшоты слоёв | Хост на ext4/XFS; production без опыта Btrfs | Нативные снапшоты; reflink copy-up; требует Btrfs-раздела для `/var/lib/docker` |
| **zfs** | Хост на ZFS; нужны снапшоты и сжатие | Хост без ZFS; production без опыта ZFS | Сжатие и снапшоты на уровне ФС; высокое потребление RAM |
| **devicemapper** | Legacy-системы (RHEL 7) без overlay2 | Любые новые развёртывания | Блочный уровень; требует `direct-lvm`; медленнее overlay2; deprecated |
| **vfs** | Отладка; ФС без поддержки CoW | Production | Без CoW — каждый слой полная копия; огромный расход диска |
| **containerd snapshotter** | Docker 29.0+ (дефолт); интеграция с CRI-раннерами | Классический Docker daemon с feature flag отключён | Слои в `/var/lib/containerd`; дублирование (content store + snapshotter) |

**Feature-флаги файловых систем:**
- **XFS `ftype=1`**: обязателен для overlay2 (иначе `cannot mount overlay: invalid argument`). Проверка: `xfs_info /var/lib/docker \| grep ftype`.
- **XFS `reflink=1`**: ускоряет copy-up через reflinks (вместо полного копирования). Проверка: `xfs_info / \| grep reflink`.
- **Btrfs/ZFS**: включают нативные снапшоты слоёв, но требуют соответствующей ФС для `/var/lib/docker`.

### Связанные темы

- **[Основы Docker-образов](./images/docker_images_basics.md)** — концепция слоев в образах
- **[Управление слоями образа](./images/layer_management.md)** — анализ, squash и оптимизация слоёв
- **[Сравнение образа и контейнера](./images/image_vs_container.md)** — записываемый слой и CoW в контексте жизненного цикла
- **[Тома (Volumes) в Docker](./docker_volumes.md)** — рекомендуемый способ для персистентных и write-heavy данных
- **[Создание образов через Docker Commit](./docker_commit.md)** — как OverlayFS участвует при фиксации контейнера в образ
- **[Copy-on-Write в Linux](../../Linux/Core/processes/basic_concepts.md)** — базовый принцип работы CoW в ядре
- **[Производительность Docker](../Docker_performance_tuning.md)** — оптимизация CPU, памяти, I/O и сети в контейнерах.
