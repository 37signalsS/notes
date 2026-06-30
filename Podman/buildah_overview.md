# Buildah: Концепции и практика

## Определения

* **Buildah** — специализированный инструмент командной строки для сборки образов контейнеров, соответствующих стандартам **OCI (Open Container Initiative)**.
* **Daemonless** — архитектура без постоянно запущенного фонового процесса (демона). Buildah работает как обычная утилита: запустилась, выполнила задачу, завершилась.
* **Rootless** — возможность работы от имени обычного пользователя без привилегий `root`.
* **Working Container** — временный контейнер, созданный Buildah для внесения изменений, которые впоследствии будут "закоммичены" в образ.

## Основные концепции

### Почему Buildah, а не Docker build?

1. **Безопасность (No Daemon, No Root):** Docker требует `root` для демона. Buildah не имеет демона и может работать полностью в userspace, что критично для CI/CD и многопользовательских систем.
2. **Минимализм образов:** Buildah позволяет собрать образ вообще без пакетного менеджера внутри (например, используя `dnf` хоста для установки пакетов в примонтированный `rootfs` контейнера). Это уменьшает размер образа и количество уязвимостей.
3. **Гибкость скриптования:** Вместо жесткого формата `Dockerfile`, Buildah предоставляет гранулярные команды (`run`, `copy`, `mount`), которые можно использовать в обычных bash-скриптах.
4. **Контроль слоев:** Вы сами решаете, когда создавать слой, используя команду `commit`.

### Две стадии работы Buildah

В отличие от Docker, Buildah разделяет процесс на две четкие фазы:

1.  **Container-фаза (рабочий контейнер):** Команда `buildah from` создает "черновик" образа. Файловая система контейнера смонтирована (обычно в `/var/lib/containers/`), вы можете копировать в неё файлы и менять конфиги, но **процесс контейнера не запущен** как сервис. Это просто песочница для подготовки файловой системы.
2.  **Commit (фиксация):** Команда `buildah commit` превращает подготовленный "черновик" в статичный неизменяемый образ, готовый к развертыванию.

Запуск готового образа для проверки выполняется отдельно через **Podman** или **Docker**.

### Связь с Podman и Skopeo

* **Buildah** — для **сборки** (Build).
* **Podman** — для **запуска** (Run). Хотя `podman build` существует, под капотом он использует код Buildah.
* **Skopeo** — для **перемещения** и инспекции (Transport/Inspect).

Вместе они составляют "Red Hat Container Tools" — модульную замену монолитному Docker.

## Практические сценарии

### 1. Базовый цикл сборки (Pipeline)

Конвейер сборки через Buildah выглядит следующим образом:

1.  `buildah from nginx:latest` — создание рабочего контейнера (например, `nginx-working`).
2.  `buildah copy <container> <src> <dest>` — копирование файлов внутрь "черновика".
3.  `buildah config` — (опционально) настройка `CMD`, `ENTRYPOINT`, портов и переменных окружения.
4.  `buildah commit <container> <image-name>` — фиксация образа в локальном хранилище.
5.  `buildah rm <container>` — удаление временного рабочего контейнера.
6.  `podman run -d -p 8080:80 <image-name>` — запуск и проверка готового образа.

**Пример скрипта:**

```bash
# 1. Создаем рабочий контейнер из базового образа
container=$(buildah from fedora)

# 2. Выполняем команды (создаются изменения, но не новые слои до коммита)
buildah run $container -- dnf install -y httpd
buildah copy $container index.html /var/www/html/

# 3. Настраиваем метаданные
buildah config --author "DevOps Team" --port 80 --entrypoint "/usr/sbin/httpd -D FOREGROUND" $container

# 4. Сохраняем изменения в новый образ
buildah commit $container my-custom-httpd

# 5. Удаляем рабочий контейнер
buildah rm $container
```

### 2. Сборка "с нуля" (From Scratch)

Это позволяет создать максимально пустой образ, куда вы копируете только бинарный файл.

```bash
newcontainer=$(buildah from scratch)
scratchmnt=$(buildah mount $newcontainer)

# Копируем только нужные файлы с хоста в корень контейнера
cp my_app_binary ${scratchmnt}/usr/bin/
# ...настройка библиотек...

buildah unmount $newcontainer
buildah commit $newcontainer my-minimal-app
```

### 3. Использование инструментов хоста (Mount)

Вы можете примонтировать файловую систему контейнера к хосту и использовать `apt`/`dnf` хоста. Внутри образа пакетный менеджер не останется.

```bash
container=$(buildah from ubi8-micro)
mountpoint=$(buildah mount $container)

# Используем dnf хоста для установки в путь mountpoint
dnf install --installroot $mountpoint --releasever 8 -y httpd

buildah unmount $container
buildah commit $container ubi8-httpd-no-dnf
```

### 4. Работа с Dockerfile (buildah bud)

Buildah полностью поддерживает сборку по Dockerfile (или Containerfile).

```bash
buildah bud -t my-image:v1 .
```
*Примечание: `bud` расшифровывается как "Build Using Dockerfile".*

### 5. Многоэтапная сборка (Multi-stage) в скриптах

Аналог Multi-stage Dockerfile, но более гибкий.

```bash
# Этап 1: Сборка артефакта
builder=$(buildah from golang:alpine)
buildah run $builder -- go build -o app main.go
mount_builder=$(buildah mount $builder)

# Этап 2: Финальный образ
runtime=$(buildah from alpine)
mount_runtime=$(buildah mount $runtime)

# Копируем бинарник между монтированными путями на хосте
cp ${mount_builder}/go/src/app ${mount_runtime}/usr/bin/

buildah unmount $runtime
buildah commit $runtime final-app
```

## Дополнительная информация

### Buildah vs Podman Build

| Особенность | Buildah (CLI) | Podman build |
| :--- | :--- | :--- |
| **Формат** | Скрипты (bash) + Dockerfile | Только Dockerfile |
| **Гранулярность** | Полный контроль над слоями | Один шаг — один слой (обычно) |
| **Монтирование** | `buildah mount` (очень мощно) | Недоступно напрямую |
| **Назначение** | Сложная, оптимизированная сборка | Стандартная сборка по шаблону |

### См. также

* **[Podman: Основные команды](./podman_basic_commands.md)**
* **[Сравнение Podman и Docker](./podman_vs_docker.md)**
* **[Интеграция Buildah и Ansible](../Ansible/ansible_buildah_image_building.md)**
