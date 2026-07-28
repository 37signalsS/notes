# Buildah: Концепции и практика сборки образов

## Определения

**Buildah** — специализированный инструмент командной строки для сборки образов контейнеров, полностью соответствующих стандартам **OCI (Open Container Initiative)**. Buildah спроектирован как модульный инструмент, который не требует фонового демона и предоставляет низкоуровневый ("хирургический") доступ к файловой системе и метаданным образа.

**Daemonless** — архитектура без постоянно запущенного фонового процесса. Buildah работает по модели fork-exec: процесс запускается, выполняет конкретную операцию (например, копирование файла или коммит слоя) и немедленно завершается.

**Working Container (Рабочий контейнер)** — это временная сущность в локальном хранилище, представляющая собой распакованную файловую систему базового образа с наложенным на нее записываемым слоем. Buildah манипулирует этим слоем, позволяя "закоммитить" его в итоговый образ в любой момент.

**Extreme Distroless** — методика создания минимальных образов (часто на базе `scratch`), в которых отсутствуют даже базовые утилиты ОС (пакетные менеджеры, оболочки, coreutils).

---

## Уникальные преимущества Buildah (за пределами Dockerfile)

Buildah предоставляет возможности, которые технически невозможно или крайне сложно реализовать через стандартный `docker build`.

### 1. Изолированная установка через `buildah mount`
В Docker для установки софта (`RUN apt install`) вы обязаны иметь пакетный менеджер *внутри* образа.
- **Решение Buildah:** Вы можете смонтировать файловую систему будущего образа как папку на хосте и использовать пакетный менеджер **хоста** для установки софта внутрь образа.
- **Практический пример:**
  ```bash
  # Создаем пустой контейнер
  newcontainer=$(buildah from scratch)
  # Монтируем его ФС в директорию на хосте
  scratchmnt=$(buildah mount $newcontainer)
  
  # Установка софта через менеджер пакетов хоста (dnf) прямо в точку монтирования образа
  # В итоговом образе НЕ будет dnf, rpm или их зависимостей
  dnf install --installroot=$scratchmnt --releasever=40 python3-minimal -y
  
  # Очистка и фиксация
  buildah unmount $newcontainer
  buildah commit $newcontainer my-pure-python
  ```
- **Результат:** Образ содержит только бинарные файлы Python и библиотеки. Поверхность атаки минимизирована, так как в образе нет инструментов для скачивания или компиляции вредоносного кода.

### 2. Полный контроль над гранулярностью слоев
- **Проблема Docker:** Каждая инструкция (`COPY`, `RUN`) создает слой. Объединение команд через `&&` — единственный способ уменьшить их количество, что портит читаемость.
- **Решение Buildah:** Вы можете выполнить сотни операций (копирование, изменение прав, удаление временных файлов) в рамках одного рабочего контейнера и вызвать `buildah commit` только один раз в самом конце.
- **Результат:** Итоговый образ имеет ровно один слой, при этом сборочный скрипт остается чистым и структурированным.

### 3. Сборка «снаружи» (Out-of-band manipulation)
- **Проблема Docker:** Код сборки выполняется *внутри* контейнера. Это требует запуска процессов из базового образа, что может быть небезопасно.
- **Решение Buildah:** Вы можете манипулировать файлами образа снаружи, просто копируя их в точку монтирования. Вам вообще не обязательно запускать какой-либо код из образа во время сборки.
- **Результат:** Максимальная безопасность при работе с образами из недоверенных источников.

---

## Настройка и внедрение в Production

### 1. Настройка Storage Driver для Rootless режима

В безрутовом режиме Buildah часто сталкивается с ограничениями ядра на монтирование. Для стабильной работы необходимо использовать **fuse-overlayfs**.

**Файл конфигурации:** `~/.config/containers/storage.conf` (создайте, если отсутствует):

```ini
[storage]
# Использование overlay драйвера (стандарт OCI)
driver = "overlay"

[storage.options]
# Программа монтирования для работы без прав root
mount_program = "/usr/bin/fuse-overlayfs"
# Опция для ускорения работы в некоторых файловых системах
mountopt = "nodev,metacopy=on"
```

### 2. Сборка в Kubernetes (Image-in-Image)

Для запуска Buildah внутри Pod'а (например, в GitLab Runner или Tekton) требуются специфические настройки изоляции.

**Пример манифеста (фрагмент SecurityContext):**

```yaml
spec:
  containers:
  - name: buildah-builder
    image: quay.io/buildah/stable:latest
    securityContext:
      # Требуются для корректного маппинга UID/GID в User Namespaces
      capabilities:
        add: ["SETUID", "SETGID"]
    env:
    - name: STORAGE_DRIVER
      value: "overlay"
    - name: BUILDAH_ISOLATION
      value: "chroot" # Важно для работы внутри контейнера
    volumeMounts:
    - name: varlibcontainers
      mountPath: /var/lib/containers
  volumes:
  - name: varlibcontainers
    emptyDir: {}
```

---

## Практические сценарии

### 1. Базовый цикл сборки через скрипт

```bash
#!/bin/bash
# 1. Создаем рабочий контейнер
container=$(buildah from alpine:latest)

# 2. Выполняем действия (без создания промежуточных слоев)
buildah run $container -- apk add --no-cache nodejs npm
buildah copy $container ./package.json /app/
buildah run $container --workingdir /app -- npm install
buildah copy $container ./src /app/src

# 3. Настраиваем метаданные (Config)
buildah config --author "DevOps Team" \
               --port 3000 \
               --env NODE_ENV=production \
               --entrypoint '["node", "/app/src/index.js"]' \
               $container

# 4. Фиксируем образ (создается единственный слой со всеми изменениями)
buildah commit --rm $container my-node-app:v1
```

### 2. Многоэтапная сборка (Multi-stage) в Bash

Buildah позволяет копировать файлы между любыми образами на хосте без ограничений, накладываемых синтаксисом Dockerfile.

```bash
# Этап 1: Сборка артефакта (Builder)
builder=$(buildah from golang:1.22-alpine)
buildah run $builder -- go build -o /app/server main.go
b_mnt=$(buildah mount $builder)

# Этап 2: Финальный образ (Runtime)
runtime=$(buildah from alpine:latest)
r_mnt=$(buildah mount $runtime)

# Копируем бинарник напрямую между смонтированными путями
cp ${b_mnt}/app/server ${r_mnt}/usr/bin/server

# Финализация
buildah unmount $runtime
buildah commit $runtime my-app-prod
buildah rm $builder $runtime
```

### 3. Работа с Multi-arch манифестами

Buildah — основной инструмент для создания манифестов, объединяющих образы для разных платформ под одним тегом.

```bash
# Создание пустого манифеста
buildah manifest create my-app:latest

# Добавление архитектур (может быть как локальный образ, так и удаленный)
buildah manifest add my-app:latest docker://my-app-amd64:v1
buildah manifest add my-app:latest docker://my-app-arm64:v1

# Пуш манифеста со всеми архитектурами в реестр
buildah manifest push --all my-app:latest docker://registry.com/my-app:latest
```

---

## Сравнение механизмов сборки

| Характеристика | Buildah (CLI) | Podman Build / `bud` | Docker BuildKit |
| :--- | :--- | :--- | :--- |
| **Формат описания** | Скрипты (Bash/Python/etc) | Dockerfile / Containerfile | Dockerfile + расширения |
| **Управление слоями** | Ручное (через `commit`) | Автоматическое | Автоматическое + кэш |
| **OCI Manifests** | Нативная поддержка | Через `podman manifest` | Через `buildx` |
| **Сборка без демона** | Полная (Daemonless) | Полная (через код Buildah) | Требует `buildkitd` |
| **Монтирование ФС** | Да (`buildah mount`) | Нет | Только внутри `RUN` |

---

## Дополнительная информация

### Связанные разделы
- **[Podman: Основные команды](./podman_basic_commands.md)** — использование образов.
- **[Skopeo: Транспортировка](./skopeo_overview.md)** — перемещение образов между реестрами.
- **[Rootless режим в Podman](./podman_rootless.md)** — детали работы `fuse-overlayfs`.
- **[Изоляция в Linux](../Docker/Concepts/linux_isolation.md)** — база по Namespaces и Cgroups.
- **[Интеграция с Ansible](../Ansible/ansible_buildah_image_building.md)** — автоматизация через плейбуки.

### Рекомендации
- Используйте `buildah bud` для простых задач и совместимости с существующими Dockerfile.
- Переходите на скриптовую сборку Buildah, если вам нужны сверхмалые образы (Distroless) или сложная логика на этапе билда.
- Для отладки используйте `buildah unshare`, чтобы войти в пространство имен пользователя и увидеть файловую систему так же, как её видит Buildah.
