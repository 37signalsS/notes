# Buildah: Концепции и практика

## Определения

* **Buildah** — специализированный инструмент командной строки для сборки образов контейнеров, соответствующих стандартам **OCI (Open Container Initiative)**.
* **Daemonless** — архитектура без постоянно запущенного фонового процесса (демона). Buildah работает как обычная утилита: запустилась, выполнила задачу, завершилась.
* **Rootless** — возможность работы от имени обычного пользователя без привилегий `root`.
* **Working Container** — временный контейнер, созданный Buildah для внесения изменений, которые впоследствии будут "закоммичены" в образ.

## Основные концепции

## Уникальные преимущества Buildah (за пределами Dockerfile)

Buildah предоставляет возможности, которые технически невозможно или крайне сложно реализовать через стандартный `docker build` и Dockerfile.

### 1. Образы без пакетного менеджера (Extreme Distroless)
В стандартных "slim" образах (например, `python:slim`) все равно присутствуют `apt`, `dash`, `coreutils`, что увеличивает поверхность атаки.

- **Проблема Docker:** Чтобы собрать образ `FROM scratch`, вы не сможете использовать `RUN apt-get install`, так как в образе нет пакетного менеджера.
- **Решение Buildah:** Использование `buildah mount`. Вы монтируете файловую систему будущего образа как папку на хосте и используете пакетный менеджер хоста для установки софта внутрь образа.
  ```bash
  newcontainer=$(buildah from scratch)
  scratchmnt=$(buildah mount $newcontainer)
  # Установка софта через менеджер пакетов хоста прямо в образ
  dnf install --installroot=$scratchmnt --releasever=39 python3 -y
  buildah unmount $newcontainer
  buildah commit $newcontainer my-pure-python
  ```
- **Итог:** В итоговом образе нет пакетного менеджера, шелла и лишних утилит. Только ваше приложение и его зависимости.

### 2. Полный контроль над структурой слоев
- **Проблема Docker:** Каждая инструкция `RUN`, `COPY`, `ADD` создает новый слой. Чтобы уменьшить количество слоев, приходится объединять команды в гигантские цепочки через `&&`, что ухудшает читаемость.
- **Решение Buildah:** Вы можете выполнить любое количество команд (изменять, удалять, перемещать файлы) и вызвать `buildah commit` только один раз в самом конце.
- **Итог:** Вы получаете образ ровно с одним слоем (или столько, сколько захотите), сохраняя при этом чистоту и читаемость сборочного bash-скрипта.

### 3. Сборка «снаружи» (Повышенная безопасность)
- **Проблема Docker:** Команды `RUN` выполняются *внутри* контейнера. Если пакетный менеджер или базовая система скомпрометированы, вредоносный код может попытаться атаковать ядро через системные вызовы.
- **Решение Buildah:** Вы можете манипулировать файлами образа снаружи, просто копируя их в точку монтирования. Вам вообще не обязательно запускать какой-либо код из образа во время сборки.
- **Итог:** Минимизация рисков при сборке образов из недоверенных источников.

### 4. Отсутствие демона и root-прав
Buildah — это просто CLI-утилита. Она не требует запуска фонового процесса (в отличие от `buildkitd`) и может работать полностью в userspace без привилегий `root`.
4. **Контроль слоев:** Вы сами решаете, когда создавать слой, используя команду `commit`.

### Две стадии работы Buildah

В отличие от Docker, Buildah разделяет процесс на две четкие фазы:

1.  **Container-фаза (рабочий контейнер):** Команда `buildah from` создает "черновик" образа. Файловая система контейнера смонтирована (обычно в `/var/lib/containers/`), вы можете копировать в неё файлы и менять конфиги, но **процесс контейнера не запущен** как сервис. Это просто песочница для подготовки файловой системы.
2.  **Commit (фиксация):** Команда `buildah commit` превращает подготовленный "черновик" в статичный неизменяемый образ, готовый к развертыванию.

Запуск готового образа для проверки выполняется отдельно через **Podman** или **Docker**.

### Связь с Podman и Skopeo

- **Buildah** — для **сборки** (Build).
- **Podman** — для **запуска** (Run). Хотя `podman build` существует, под капотом он использует код Buildah.
- **[Skopeo](./skopeo_overview.md)** — для **перемещения** и инспекции (Transport/Inspect). Buildah может делать `push`, но Skopeo предоставляет гораздо более гибкие возможности по управлению репозиториями в CI/CD.

## Настройка и внедрение в Production

### 1. Настройка Storage Driver для Rootless режима

В режиме "без рута" Buildah часто сталкивается с ограничениями ядра на монтирование слоев. Стандартный `overlay` драйвер может не работать без специфических патчей ядра.

**Решение:** Использование **fuse-overlayfs**.

1. Установите пакет: `sudo apt install fuse-overlayfs` (или `dnf install`).
2. Настройте конфигурацию хранилища в `~/.config/containers/storage.conf`:

```ini
[storage]
driver = "overlay"

[storage.options]
mount_program = "/usr/bin/fuse-overlayfs"
```

Это гарантирует стабильную сборку в userspace на большинстве дистрибутивов.

### 2. Сборка образов в Kubernetes (Image-in-Image)

Запуск Buildah внутри Pod'а позволяет собирать образы прямо в кластере без доступа к `/var/run/docker.sock`.

**Основные требования к Pod:**
- Использование `fuse-overlayfs` (см. выше).
- SecurityContext: Потребуются `CAP_SETUID` и `CAP_SETGID` для корректного маппинга пользователей.
- Хранилище: Рекомендуется монтировать `emptyDir` в `/var/lib/containers` для временных слоев.

**Пример манифеста (фрагмент):**

```yaml
spec:
  containers:
  - name: buildah
    image: quay.io/buildah/stable
    securityContext:
      capabilities:
        add: ["SETUID", "SETGID"]
    volumeMounts:
    - name: storage
      mountPath: /var/lib/containers
  volumes:
  - name: storage
    emptyDir: {}
```

Для более удобного управления в K8s существует **Buildah Operator**, который автоматизирует создание сборочных ресурсов.

### 3. Интеграция в CI/CD со Skopeo

Типичный пайплайн доставки:
1. `buildah bud` — сборка образа.
2. `buildah commit` — локальная фиксация.
3. **[Skopeo](./skopeo_overview.md)** — перемещение из локального хранилища `containers-storage:` в удаленный Registry `docker://`.

```bash
# Копирование из хранилища Buildah в реестр через Skopeo
skopeo copy containers-storage:localhost/my-app:latest docker://my-registry.com/my-app:latest
```

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

### Когда выбирать Buildah?

1. Вам нужен «хирургический» контроль над процессом сборки (сборка без Dockerfile).
2. Вы создаете сверхмалые **Distroless** образы, не содержащие даже пакетного менеджера.
3. Вы находитесь в экосистеме **Red Hat / OpenShift**, где Buildah является нативным стандартом.
4. Вам требуется сборка без фоновых процессов (демонов) для максимальной легковесности.

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
