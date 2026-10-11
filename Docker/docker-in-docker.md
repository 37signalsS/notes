# Docker-in-Docker (DinD): Запуск Docker внутри контейнера

**Актуально для:** Docker Engine 29.x

## Определения

**Docker-in-Docker (DinD)** — подход, позволяющий запускать Docker-демон и управлять контейнерами внутри другого Docker-контейнера. Используется в CI/CD-пайплайнах для создания изолированных сред сборки и тестирования.

**Docker-out-of-Docker (DooD)** — альтернативный подход, при котором контейнер подключается к Docker-демону хоста через монтирование сокета (`/var/run/docker.sock`). Контейнеры создаются на уровне хоста, а не внутри контейнера.

## Основные концепции

### Как работает DinD

Контейнер — это изолированный процесс на **общем ядре хоста**, а не виртуальная машина. Чтобы внутренний `dockerd` мог создавать namespaces и монтировать файловые системы (overlay2), ему требуется `CAP_SYS_ADMIN`, доступ к cgroups и устройствам, а также отключённые профили безопасности (seccomp, AppArmor). Всё это и даёт режим `--privileged`: внутренний демон работает на том же ядре, что и хост, и его возможности монтирования неотделимы от хостовых. Именно поэтому классический DinD невозможен без `--privileged` — гранулярных capabilities (например, только `SYS_ADMIN`) в общем случае недостаточно.

### 1. Подход: Docker-in-Docker (официальный образ docker:dind)

Официальный образ `docker:dind` запускает полноценный Docker-демон внутри контейнера. Требует привилегированного режима (`--privileged`), так как демону нужен доступ к cgroups, namespaces, устройствам и возможность монтирования. Устройство `/dev/fuse` требуется только для `fuse-overlayfs` (rootless-режим или fallback), для стандартного `overlay2` оно не нужно.

**Архитектура:**

```
Хост (dockerd)
 └── Контейнер (dockerd — привилегированный)
     ├── Контейнер A
     ├── Контейнер B
     └── Контейнер C
```

**Преимущества:**

- Полная изоляция: контейнеры DinD не видны демону хоста
- Чистая среда: каждый запуск начинает с нуля
- Идеально для CI/CD: воспроизводимые сборки

**Недостатки и риски:**

- Требует `--privileged` — все capabilities хоста, отключённые seccomp/AppArmor, прямой доступ к `/dev` (риск побега из контейнера)
- Накладные расходы: дополнительный демон и слой файловой системы потребляют CPU/RAM
- Двойное хранение: образ `docker:dind` на хосте плюс образы внутри вложенного демона
- Сложность отладки: логи и артефакты внутри вложенного демона

**Пример запуска:**

```bash
docker run --privileged -d --name dind docker:29.8-dind
docker exec -it dind docker run --rm hello-world
# → Hello from Docker!
```

**Валидация:**

```bash
docker exec dind docker info --format '{{.Driver}}'
# → overlay2
docker exec dind docker version --format '{{.Server.Version}}'
# → 29.8.x
```

### 2. Подход: Docker-out-of-Docker (монтирование сокета)

Контейнер получает доступ к Docker API хоста через Unix-сокет. Docker CLI внутри контейнера отправляет команды демону на хосте.

**Архитектура:**

```
Хост (dockerd)
 ├── Контейнер A (с доступом к /var/run/docker.sock)
 ├── Контейнер B (создан через сокет)
 └── Контейнер C (создан через сокет)
```

**Преимущества:**

- Нет привилегированного режима — безопаснее
- Образы хранятся на хосте — экономия места и кэширование
- Простая отладка: все контейнеры видны через `docker ps` на хосте

**Недостатки и риски:**

- Равносильно root-доступу к хосту: через сокет можно смонтировать любую директорию хоста
- Нет изоляции: контейнеры соседствуют с основными на хосте
- Конфликты имён: несколько пайплайнов могут создать контейнеры с одинаковыми именами

**Пример с docker-compose:**

```yaml
services:
  builder:
    image: docker:29-cli
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: docker build -t myapp .
```

Важно: Монтирование с флагом `:ro` (read-only) не защищает — Docker API не является read-only API. Даже с `:ro` контейнер может создавать новые контейнеры, монтировать файловые системы хоста и выполнять команды. Подробнее см. в [Обзор безопасности Docker](./Docker_security/overview.md).

**Альтернатива сокету:** вместо монтирования можно подключиться к демону по TCP (`DOCKER_HOST=tcp://хост:2375`), но это требует открытия порта и TLS — без TLS трафик передаётся в открытом виде и даёт тот же root-доступ. Для управления извне предпочтительнее `docker context` с TLS-сертификатами.

### 3. Подход: Rootless DinD (демон от непривилегированного пользователя)

Официальный образ `docker:dind-rootless` запускает Docker-демон внутри контейнера от пользователя `rootless` (UID 1000) с использованием **RootlessKit** и **slirp4netns** для эмуляции сетевого стека и управления пространствами имен.

**Важная поправка:** образу **всё равно требуется `--privileged`** — для отключения seccomp, AppArmor и mount masks (docker-library/docker#281). Разница в том, что демон работает от UID 1000: при компрометации внутреннего демона злоумышленник остаётся в рамках непривилегированного пользователя, а не получает root хоста.

**Особенности:**

- **Безопасность:** значительно выше, чем у стандартного DinD, но не равна безопасности Kaniko/Buildah
- **Ограничения:** некоторые драйверы хранения и сетевые функции требуют дополнительной настройки; для публикации привилегированных портов (<1024) нужен `CAP_NET_BIND_SERVICE` на `rootlesskit`
- **Требования хоста:** поддержка user namespaces, `newuidmap`/`newgidmap`, записи в `/etc/subuid` и `/etc/subgid` (минимум 65536 подчинённых UID/GID)

**Пример:**

```bash
docker run -d --name dind-rootless --privileged docker:29.8-dind-rootless
docker exec -it dind-rootless docker-entrypoint.sh docker run --rm hello-world
# → Hello from Docker!
```

### 4. Подход: Sysbox (изолированный DinD без --privileged)

**Sysbox** — open-source рантайм (специализированный `runc`), разработанный Nestybox (приобретена Docker в мае 2022). Sysbox позволяет запускать Docker, systemd и Kubernetes внутри контейнеров **без `--privileged`** за счёт виртуализации `/proc` и `/sys` и обязательного user namespace для всех контейнеров: root внутри системного контейнера имеет все capabilities только внутри него и ноль привилегий на хосте.

**Статус:** проект сообщества, основной спонсор — Docker; официальной поддержки Docker в подписках нет (support best-effort через GitHub). Sysbox Enterprise включён в Docker Desktop (Docker Hardened Desktop).

**Особенности и ограничения:**

- **Совместимость:** внутренний Docker работает как на обычном хосте; `--privileged`, `--userns=host`, `--pid=host`, `--net=host` внутри Sysbox **не работают** (ломают изоляцию)
- **Требования:** Sysbox должен работать от root на хосте; id-mapped mounts требуют ядро 5.12+ (или shiftfs), id-mapped overlayfs — 5.19+; вложенность Sysbox-в-Sysbox не поддерживается
- **Удобство:** не требует настройки storage drivers или монтирования сокетов

**Пример:**

```bash
docker run --runtime=sysbox-runc -d --name dind-sysbox docker:29.8-dind
docker exec -it dind-sysbox docker run --rm hello-world
```

### 5. Подход: Kaniko (сборка без демона)

**[Kaniko](./Dockerfile/dockerfile_kaniko.md)** — альтернатива DinD для сборки образов. Выполняет сборку в userspace без Docker-демона. Google-репозиторий `GoogleContainerTools/kaniko` архивирован в июне 2025; актуальный форк — `osscontainertools/kaniko` (образы `ghcr.io/osscontainertools/kaniko`, зеркало на Docker Hub — `martizih/kaniko`).

### Выбор метода сборки: DinD vs DooD vs Kaniko

Выбор между подходами — это баланс между **совместимостью** и **безопасностью**.

**DinD (Docker-in-Docker)** — запуск полноценного Docker-демона (`dockerd`) внутри контейнера.

- **Плюсы:** 100% совместимость с `Dockerfile` (включая multi-stage и специфичные флаги); полноценный BuildKit (параллелизм, продвинутое кэширование); привычный опыт (`docker build`, `docker push`)
- **Минусы:** низкая безопасность (`--privileged` — риск захвата хоста при компрометации пайплайна); ресурсоёмкость (демон + CPU/RAM); управление хранилищем внутри контейнера

**Kaniko** — сборка образов в user-space без Docker-демона.

- **Плюсы:** высокая безопасность (non-root, совместим с Pod Security Standards: restricted); лёгкость (нет фонового демона); удалённый кэш в реестре
- **Минусы:** эмуляция поведения Docker — редкие сложные инструкции могут не сработать; BuildKit-функции частично (`RUN --mount=type=cache/secret/bind` с v1.28+); сложнее диагностировать ошибки эмуляции

**Сравнительная таблица:**

| Критерий | DinD (Docker-in-Docker) | DooD (socket mount) | Kaniko |
| :--- | :--- | :--- | :--- |
| **Демон Docker** | Требуется (внутри) | Хост-демон | Не требуется |
| **Безопасность** | Низкая (`--privileged`) | Низкая (доступ к сокету = root хоста) | Высокая (`non-root`) |
| **Совместимость** | 100% | 100% | Высокая (с ограничениями) |
| **BuildKit** | Поддерживается | Поддерживается | Частично (`RUN --mount` в v1.28+) |
| **Ресурсы** | Высокие | Низкие | Низкие |
| **Кэширование** | Локальное | На хосте | Удалённое (в реестре) |

### Технические нюансы и оптимизация

При работе с DinD возникает ряд проблем, связанных с вложенностью и изоляцией.

#### Производительность и Storage Drivers

По умолчанию Docker-демон внутри DinD может выбрать драйвер **vfs**, который крайне медленен и неэффективен по дисковому пространству (каждый слой копируется целиком).

**Рекомендация:** Используйте **overlay2**.

- Для корректной работы `overlay2` поверх `overlay2` (на хосте) требуется ядро Linux версии 4.18+ и поддержка со стороны файловой системы.
- В образе `docker:dind` по умолчанию настроено использование `overlay2`. Если возникли проблемы, проверьте вывод `docker info` внутри контейнера.
- В Docker 29.x при свежей установке внутренний демон может использовать containerd image store (образы хранятся нативно в containerd) — проверяйте `docker info | grep -i storage`.

#### Сетевые проблемы и MTU

Если DinD-контейнер запущен в сети с MTU меньше 1500 (например, через VPN, VXLAN или у провайдеров с уменьшенным MTU), внутренние контейнеры DinD могут иметь проблемы с сетевым доступом (**Fragmentation needed**). Это происходит потому, что пакеты, инкапсулированные внутри контейнера, могут превышать MTU внешней сети при добавлении заголовков виртуализации.

**Решение:** Установите MTU для внутреннего демона:

```json
// В /etc/docker/daemon.json внутри DinD
{
  "mtu": 1400
}
```

Или через флаг запуска: `dockerd --mtu=1400`.

#### Ограничение ресурсов

Поскольку DinD запускает полноценный демон, он потребляет значительное количество ресурсов.

- **RAM:** демон и BuildKit потребляют сотни мегабайт; для крупных multi-stage сборок выделяйте больше памяти через `--memory`.
- **Диск:** Используйте именованные тома для `/var/lib/docker` внутри DinD, чтобы избежать переполнения writable layer внешнего контейнера и сохранить кэш образов между запусками:

```bash
docker run --privileged -d --name dind \
  -v dind-data:/var/lib/docker \
  docker:29.8-dind
```

#### Оптимизация BuildKit в DinD

BuildKit значительно ускоряет сборку в DinD, особенно при использовании параллелизма и продвинутого кэширования.

**Рекомендации:**

1. **Включение BuildKit:** В современных образах Docker (23+) BuildKit включен по умолчанию. Для старых версий используйте `DOCKER_BUILDKIT=1`.
2. **Inline Cache:** Для эффективного кэширования в CI используйте флаг `--cache-from` и опцию `--build-arg BUILDKIT_INLINE_CACHE=1`. Это позволяет упаковывать метаданные кэша прямо в образ.
3. **Garbage Collection:** GC BuildKit запускается автоматически по политикам (по умолчанию: удаление неиспользуемого кэша старше 48 часов при превышении 512MB, и старше 60 дней). Для тонкой настройки в `daemon.json` используйте актуальные поля (`defaultKeepStorage` переименован в `defaultReservedSpace`):

   ```json
   {
     "builder": {
       "gc": {
         "enabled": true,
         "defaultReservedSpace": "20GB",
         "policy": [
           { "reservedSpace": "2.76GB", "keepDuration": "48h",
             "filter": ["type=source.local,type=exec.cachemount,type=source.git.checkout"] },
           { "reservedSpace": "20GB", "keepDuration": "1440h" }
         ]
       }
     }
   }
   ```

   Ручная очистка кэша: `docker builder prune` (или `docker buildx prune` для custom builders).

### Настройка прав доступа при монтировании директорий

При использовании DinD и DooD часто возникают сложности с правами доступа к файлам (UID/GID) при монтировании директорий с хоста или между контейнерами.

Подробные решения (именованные тома, совпадение UID/GID, entrypoint-скрипты) описаны в файле: **[Настройка прав доступа](./Docker_fs/docker_volumes.md#настройка-прав-доступа)**.

## Предварительные требования

| Требование | Значение | Проверка |
| :--- | :--- | :--- |
| Ядро Linux | 4.18+ для вложенного `overlay2` | `uname -r` |
| User namespaces (rootless) | включены, `newuidmap`/`newgidmap` | `cat /proc/sys/kernel/unprivileged_userns_clone` |
| `/etc/subuid`, `/etc/subgid` (rootless) | минимум 65536 подчинённых UID/GID | `grep $USER /etc/subuid` |
| Sysbox (при использовании) | установлен `sysbox-runc`, ядро 5.12+ (id-mapped mounts) | `sysbox-runc --version` |
| Диск | ~10 ГБ на образы внутри DinD | `df -h` |

## Практические сценарии

### Архитектурная разница: Namespaces против User-space

Основной вопрос безопасности заключается в том, **как** инструменты выполняют команды `RUN` из вашего `Dockerfile`.

#### Как это делает Docker (DinD)

Когда Docker выполняет `RUN`, он создает **настоящий изолированный контейнер** средствами ядра Linux:

1. **Namespaces:** Ядро изолирует процессы, сеть и файловую систему.
2. **Cgroups:** Ограничиваются ресурсы (CPU/RAM).
3. **OverlayFS:** Монтируется многослойная файловая система.

**Почему это опасно:** Чтобы создавать namespaces и монтировать файловые системы, процессу нужны высшие привилегии ядра (`CAP_SYS_ADMIN`). Внутренний `dockerd` работает на том же ядре, что и хост, поэтому для DinD приходится давать всему контейнеру флаг `--privileged`. Это открывает прямой путь к устройствам и файловой системе хоста.

#### Как это делает Kaniko

Kaniko **вообще не создает контейнеров** и не использует механизмы ядра для изоляции:

1. **Распаковка:** Базовый образ просто распаковывается в обычную папку на диске.
2. **Эмуляция (chroot):** Команды `RUN` запускаются через системный вызов `chroot` (или аналоги). Процессу говорят: "Твой корень `/` — это вот эта папка".
3. **Манипуляция файлами:** Процесс (например, `apt-get`) думает, что он в реальной ОС, но на самом деле он просто пишет файлы в обычную директорию в пространстве пользователя (**user-space**).

**Почему это безопасно:** Поскольку Kaniko не создает namespaces и не монтирует реальные устройства, ему **не нужны привилегии ядра**. Он работает как обычная программа, ограниченная своей рабочей папкой.

### Сценарий 1: CI/CD с DinD (GitLab CI)

Используется для сборки и тестирования в изолированной среде:

```yaml
build:
  stage: build
  image: docker:29
  services:
    - docker:29.8-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker build -t myapp:${CI_COMMIT_SHA} .
    - docker push myapp:${CI_COMMIT_SHA}
```

Параметры:

- `DOCKER_TLS_CERTDIR` — включает TLS-аутентификацию между контейнером и DinD. GitLab автоматически выставляет `DOCKER_HOST`, `DOCKER_TLS_VERIFY` и `DOCKER_CERT_PATH`.
- `services` — GitLab CI запускает DinD как sidecar-контейнер.

### Сценарий 2: Тестирование с DooD (монтирование сокета)

Для локальной разработки, когда нужен доступ к образам хоста:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd):/workspace \
  docker:29-cli \
  sh -c "cd /workspace && docker build -t test:local ."
```

### Сценарий 3: GitLab Runner с доступом к сокету

Регистрация Runner'а с монтированием сокета для сборки образов:

```bash
docker run -d --name gitlab-runner \
  --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:19.4.1-alpine
```

Безопасность: Runner с доступом к сокету эквивалентен root-доступу. Используйте только для доверенных пайплайнов. Альтернатива — Kaniko.

### Сценарий 4: DinD в Kubernetes

DinD-под требует Pod Security Standard `privileged`, что запрещено в кластерах с политиками `baseline`/`restricted`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: dind
spec:
  containers:
    - name: docker
      image: docker:29.8-dind
      securityContext:
        privileged: true
```

В общих кластерах используйте Kaniko или Sysbox (`runtimeClassName: sysbox`) вместо `privileged`.

### Сценарий 5: Sysbox (DinD без --privileged)

```bash
docker run --runtime=sysbox-runc -d --name dind-sysbox \
  -v sysbox-dind-data:/var/lib/docker \
  docker:29.8-dind
docker exec dind-sysbox docker run --rm hello-world
```

Подробнее: [Sysbox в docker_systemd.md](./docker_systemd.md) и [Альтернативные среды выполнения](./alternative_runtimes_and_tools.md).

### Сценарий 6: CI/CD с Kaniko (без DinD)

Рекомендуемый подход для сборки образов в Kubernetes/GitLab CI (актуальный форк `osscontainertools`):

```yaml
build:
  stage: build
  image:
    name: ghcr.io/osscontainertools/kaniko:v1.28.5-debug
    entrypoint: [""]
  script:
    - /kaniko/executor \
        --context "dir://${CI_PROJECT_DIR}" \
        --dockerfile "${CI_PROJECT_DIR}/Dockerfile" \
        --destination "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}" \
        --credential-helpers gitlab \
        --cache=true \
        --cache-repo "${CI_REGISTRY_IMAGE}/cache"
```

Подробнее: **[Kaniko: Сборка без демона](./Dockerfile/dockerfile_kaniko.md)**.

### Сценарий 7: kind (Kubernetes in Docker) с DinD

Локальный Kubernetes-кластер в Docker-контейнере:

```bash
kind create cluster --name local-dev
# kind использует DinD для создания нод как Docker-контейнеров
```

Подробнее: **[kind: Практические сценарии](../Kubernetes/Installation/kind/kind_practical_scenarios.md)**.

### Глубокий разбор безопасности: Векторы атак в CI/CD

В CI-системах (GitLab CI, GitHub Actions, Jenkins) использование Docker для сборки образов в многопользовательской среде без должной изоляции создаёт критические риски.

#### 1. Вариант А: Docker-in-Docker (флаг `--privileged`)

Для работы DinD требуются максимальные привилегии. Режим `--privileged` технически означает:

- **Все Capabilities:** Контейнер получает все 40+ привилегий ядра (включая `CAP_SYS_ADMIN`).
- **Отключение изоляции:** Профили безопасности (AppArmor, Seccomp) переводятся в режим `unconfined`.
- **Доступ к `/dev`:** Прямой доступ ко всем устройствам хоста, включая физические диски.

**Сценарий атаки:** Вредоносный скрипт (например, в `npm install` внутри `Dockerfile`) может выполнить команду `mount /dev/sda1 /mnt` и получить доступ к файловой системе хоста — фактически полный контроль над CI-нодой.

#### 2. Вариант Б: Монтирование Docker Socket (`-v /var/run/docker.sock:/var/run/docker.sock`)

Это часто считается "лёгкой" альтернативой DinD, но на деле это **эквивалент полного root-доступа к хосту**.

**Сценарий атаки:** Любой процесс в CI-контейнере может отправить команду локальному демону: `docker run --privileged -v /:/host alpine`. Злоумышленник мгновенно получает контроль над всей CI-нодой, секретами и данными других проектов.

### Как Kaniko обеспечивает безопасность

Kaniko спроектирован по принципу **минимальных привилегий** и устраняет описанные выше векторы атак:

1. **Отсутствие демона и сокета:** Kaniko — это CLI-утилита. У неё нет фонового процесса и ей не нужен доступ к `docker.sock`. Этот вектор атаки отсутствует физически.
2. **Работа без `--privileged`:** Kaniko успешно работает со стандартными строгими профилями безопасности Kubernetes (**Pod Security Standards: restricted**).
3. **Запуск от non-root пользователя:** Kaniko можно настроить на работу от обычного пользователя (UID 1000). Вредоносный код в процессе сборки будет ограничен правами этого пользователя.
4. **Изоляция в user-space:** Kaniko использует механизмы вроде `chroot` на уровне пользовательского пространства. Он манипулирует только той файловой системой, которую сам распаковал, и не взаимодействует с реальным ядром хоста для создания пространств имен.

#### Сравнительная таблица векторов атак

| Вектор атаки / Действие | DinD (`--privileged`) | Docker Socket Mount | Kaniko (non-root) |
| :--- | :---: | :---: | :---: |
| **Чтение файлов хостовой ОС** | Да (через `mount`) | Да (через новый контейнер) | Нет (изоляция в папке) |
| **Загрузка модулей ядра** | Да | Да | Нет |
| **Требует `--privileged`** | Обязательно | Нет (но даёт root хоста) | Нет |
| **Совместимость с PSS Restricted** | Нет | Нет | Да |
| **Риск при вредоносном `RUN`** | Критический (побег) | Критический (побег) | Низкий (ограничен папкой) |

### Итог: что выбрать?

#### Выбирайте Kaniko, если:

- Вы работаете в **Kubernetes** или **GitLab CI** (на общих раннерах).
- У вас строгие политики безопасности, и администраторы запрещают `--privileged` контейнеры.
- Ваши Dockerfile относительно стандартные (базовые `FROM`, `RUN`, `COPY`, `WORKDIR`).
- Вам нужно максимально безопасно пушить образы в реестр (Docker Hub, Harbor, GitLab Registry, Quay).

#### Выбирайте DinD, если:

- Вам критически важна **100% совместимость** с Docker и использование **BuildKit** для ускорения сложных сборок.
- Ваш CI работает в изолированной среде (например, выделенные раннеры, где не страшен выход за пределы контейнера на хост).
- Вы используете сложные Dockerfile, которые падают при сборке через Kaniko.
- Вы не хотите переучиваться и привыкли к стандартной экосистеме Docker.

**Совет:** Начинайте с **Kaniko**. В большинстве случаев он покрывает все потребности и избавляет от проблем с безопасностью. Если столкнетесь с несовместимостью — переключайтесь на **Buildah** или настраивайте **DinD**.

### Альтернативы и расширенные инструменты

#### 1. Buildah и Podman (от Red Hat)

Позволяют собирать образы без демона (как Kaniko), но при этом полностью совместимы с Docker и поддерживают `rootless`-режим.

- **Преимущество:** Отличный "средний путь", если Kaniko не справляется, а DinD нельзя использовать по соображениям безопасности.
- **Подробно:** [Buildah: Концепции и практика](../Podman/buildah_overview.md).

#### 2. Docker Buildx (Rootless / Remote)

Позволяет вынести процесс сборки за пределы CI-контейнера.

- **Remote Builder:** Выполнение сборки на удаленном выделенном сервере, что снимает проблемы безопасности внутри CI-пайплайна.
- **Подробно:** [BuildKit и Buildx](./Dockerfile/dockerfile_buildkit.md).

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Cannot connect to the Docker daemon` | Демон не успел стартовать или неверный `DOCKER_HOST` | `docker logs dind`; в GitLab проверьте `DOCKER_HOST`, `DOCKER_TLS_CERTDIR`, `DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH` |
| `overlay2: unsupported backing filesystem` / `not supported` | Ядро < 4.18 или ФС хоста не поддерживает вложенный overlay | `uname -r`; обновите ядро; fallback — `vfs` (медленно) |
| `Fragmentation needed` / обрывы сети | MTU внутреннего демона больше MTU внешней сети | `"mtu": 1400` в `daemon.json` или `dockerd --mtu=1400` |
| `permission denied` на сокете (DooD) | UID контейнера не входит в группу `docker` хоста | `group_add: ["docker"]` в compose или запуск от root |
| Диск заполнен в writable layer | Образы и кэш растут внутри слоя контейнера | Именованный том для `/var/lib/docker`; `docker system prune` внутри DinD |
| `operation not permitted` при `mount` | Недостаточно capabilities | DinD требует `--privileged`; гранулярных capabilities недостаточно |
| Rootless DinD: ошибки `rootlesskit: child` | Нет user namespaces или subuid/subgid | Проверьте `/etc/subuid`, `/etc/subgid`, `kernel.unprivileged_userns_clone` |
| Sysbox: `docker --privileged` не работает | Ограничение Sysbox (ломает изоляцию) | Запускайте внутренний Docker без `--privileged` — Sysbox сам обеспечивает необходимые возможности |

## Лучшие практики и очистка

1. **Избегайте DinD в мультитенантных кластерах:** Привилегированный режим дает почти полный доступ к хосту. Используйте Kaniko, Buildah или Sysbox.
2. **Ограничивайте доступ к сокету:** Если используете DooD, помните, что доступ к сокету — это root-доступ на хосте.
3. **Изолируйте CI-ноды:** Если DinD необходим, запускайте его на выделенных физических или виртуальных машинах, не содержащих чувствительных данных.
4. **Используйте Sysbox (альтернатива):** Рантайм для запуска Docker-в-Docker без флага `--privileged` (за счёт user namespaces и виртуализации `/proc`/`/sys`).
5. **Ограничивайте ресурсы:** `--memory`, `--cpus` для DinD-контейнера; именованный том для `/var/lib/docker`.
6. **Очистка после работы:**

   ```bash
   docker rm -f dind dind-rootless dind-sysbox
   docker volume rm dind-data sysbox-dind-data   # если использовались тома
   docker builder prune                           # кэш BuildKit на хосте
   ```

## Дополнительная информация

### См. также

- **[Kaniko: Сборка без демона](./Dockerfile/dockerfile_kaniko.md)** — глубокий разбор работы Kaniko
- **[Buildah: Сборка без демона](../Podman/buildah_overview.md)** — альтернатива от Red Hat
- **[Обзор безопасности Docker](./Docker_security/overview.md)** — векторы атак через сокет
- **[Docker: Драйвер хранения OverlayFS](./Docker_fs/docker_overlayfs.md)** — вложенный overlay и требования к ядру
- **[Docker и systemd](./docker_systemd.md)** — Sysbox и стратегии для системных служб в контейнерах
- **[Альтернативные среды выполнения](./alternative_runtimes_and_tools.md)** — Sysbox, Kata, gVisor
