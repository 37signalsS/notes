# Skopeo: Манипуляции образами без демона

## Определения

**Skopeo** — это гибкий инструмент командной строки для работы с образами контейнеров и их репозиториями. Главной особенностью Skopeo является его способность взаимодействовать с реестрами (Registry) напрямую через HTTP API (Distribution API v2), не требуя локального запуска Docker-демона, Podman или наличия прав root. Написан на Go, распространяется под лицензией Apache-2.0.

Skopeo входит в состав набора инструментов Red Hat для управления контейнерами:
- **Buildah** — сборка (Build).
- **Podman** — запуск (Run).
- **Skopeo** — передача и инспекция (Transport & Inspect).

Кроме CLI, Skopeo используется как Go-библиотека (модули `containers/image`, `containers/storage`) внутри Podman, Buildah и CRI-O для операций с реестрами и манифестами.

**Transport (транспорт)** — абстракция Skopeo, определяющая способ доступа к источнику или назначению образа: удалённый реестр, локальное хранилище, директория или архив (см. таблицу транспортов).

**Multi-arch образ** — образ, хранящийся в реестре как манифест-список (manifest list / OCI index), содержащий варианты образа для нескольких платформ (архитектура + ОС) под одним тегом.

---

## Основные концепции

### Ключевые возможности

- **Копирование без посредников:** Перемещение образов напрямую между двумя реестрами без промежуточного скачивания на диск.
- **Инспекция метаданных:** Получение информации об образе (манифест, архитектура, переменные окружения, метки) без скачивания слоев.
- **Поддержка Multi-arch:** Возможность копирования всех архитектурных вариантов образа одной командой или выборочных платформ.
- **Шифрование образов:** Поддержка шифрования и дешифрования слоев образа при передаче.
- **Синхронизация реестров:** Зеркалирование репозиториев с поддержкой фильтрации по тегам.
- **Манипуляция манифестами:** Получение, редактирование и удаление записей манифест-списков, вычисление дайджестов без скачивания данных.
- **Управление тегами:** Список тегов репозитория (`list-tags`) и удаление образов из реестра (`delete`).
- **Подписи:** Проверка и создание подписей образов — GPG «simple signing» и sigstore (cosign-совместимые).
- **Без демона и без root:** Почти все операции выполняются в обычном пользовательском окружении.

### Подкоманды

| Подкоманда | Назначение |
| :--- | :--- |
| `copy` | Копирование образа между любыми транспортами. |
| `inspect` | Получение метаданных образа без скачивания слоев. |
| `list-tags` | Вывод списка тегов репозитория. |
| `delete` | Удаление образа (тега) из реестра. |
| `sync` | Синхронизация (зеркалирование) реестров и каталогов. |
| `login` / `logout` | Управление учетными данными реестров. |
| `manifest` | Работа с манифестами и манифест-списками (get, add, remove, digest). |
| `generate-sigstore-key` | Генерация пары ключей sigstore (совместимы с cosign). |
| `standalone-sign` / `standalone-verify` | Отладочные подпись и проверка локальных файлов манифестов. |
| `manifest-digest` | Вычисление дайджеста манифеста. |
| `version` | Вывод версии инструмента. |

```bash
skopeo --version
# → skopeo version 1.23.0
```

### Типы транспортов (Transports)

Skopeo использует префиксы для определения источника и назначения данных:

| Транспорт | Описание |
| :--- | :--- |
| `docker://` | Удаленный реестр по Distribution API v2 (Docker Hub, Quay, Harbor, GHCR, ECR, Artifactory). |
| `containers-storage:` | Локальное хранилище Podman/Buildah/CRI-O (общее для всех инструментов). |
| `docker-daemon:` | Локальный кэш Docker-демона (через сокет; требует запущенного демона). |
| `docker-archive:` | Файл архива (tar), созданный через `docker save`. |
| `oci:` | Директория в формате OCI Layout. |
| `oci-archive:` | Архив (tar) в формате OCI Layout. |
| `dir:` | Локальная директория с несжатыми слоями (для отладки и air-gapped). |
| `sif:` | Образ формата SIF (Apptainer/Singularity) — только чтение. |

Примечание: `oci:` — это каталог с подкаталогами `blobs/`, `index.json` и `oci-layout` (используется такими инструментами, как Buildah, и удобен для промежуточного хранения), тогда как `dir:` — плоский каталог с отдельными файлами слоев и `manifest.json` (удобен для ручной инспекции и передачи на носителе).

Подробнее о типах реестров: [Реестры образов](../Docker/docker_registries.md).

### Авторизация и хранение учетных данных

Учетные данные для реестров хранятся в общем файле `auth.json` в формате:

```json
{
  "auths": {
    "registry.example.com": { "auth": "dXNlcm5hbWU6cGFzc3dvcmQ=" }
  }
}
```

- **Расположение по умолчанию:** `$XDG_RUNTIME_DIR/containers/auth.json` (например, `/run/user/1000/containers/auth.json` для rootless-сессий); для root и отдельных платформ используется свой путь по умолчанию.
- **Переопределение:** переменная окружения `REGISTRY_AUTH_FILE` или флаг `--authfile` для каждой команды.
- **Совместимость:** один и тот же файл используется `podman login`, `buildah login` и Skopeo; при отсутствии файла Skopeo может прочитать учётные данные из `~/.docker/config.json` (формат Docker). Флаг `--compat-auth-file` указывает на файл в формате Docker явно.
- **Безопасный ввод:** если флаг `-p/--password` не передан, пароль запрашивается интерактивно (не попадает в историю команд).
- **Credential helpers:** на macOS и Windows возможна интеграция с системными хранилищами ключей (Keychain / Credential Manager) через `credential-helpers`.

### Общее хранилище с Podman и Buildah

Транспорт `containers-storage:` использует тот же слой локального хранилища, что и Podman/Buildah/CRI-O. Образы, загруженные через `skopeo copy` в `containers-storage:`, немедленно доступны для `podman run`:

```bash
# Загрузить образ в локальное хранилище (эквивалент podman pull)
skopeo copy docker://docker.io/library/nginx:latest containers-storage:nginx:latest

# Проверить доступность образа
podman run --rm nginx:latest nginx -v
# → nginx version: nginx/1.27.0
```

Конфигурация хранилища: `/etc/containers/storage.conf` (глобально) и `~/.config/containers/storage.conf` (rootless). В rootless-режиме для overlay требуется `fuse-overlayfs` — подробнее в [Podman: Rootless](./podman_rootless.md).

### Переменные окружения

| Переменная | Назначение |
| :--- | :--- |
| `REGISTRY_AUTH_FILE` | Путь к файлу `auth.json` (переопределяет расположение по умолчанию). |
| `XDG_RUNTIME_DIR` | Базовый каталог, в котором ищется `containers/auth.json` (rootless). |
| `CONTAINERS_REGISTRIES_CONF` | Путь к `registries.conf` (списки реестров, зеркала, политика unqualified). |
| `CONTAINERS_REGISTRIES_CONF_D` | Каталог дополнительных конфигурационных файлов реестров. |
| `CONTAINERS_POLICY` | Путь к `policy.json` (политика доверия и подписей). |
| `CONTAINERS_STORAGE_CONF` | Путь к `storage.conf` (драйвер хранилища, монтирования). |
| `SSL_CERT_FILE` / `SSL_CERT_DIR` | CA-сертификаты для HTTPS-соединений. |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | HTTP(S)-проксирование для операций с реестрами. |

### Архитектура и принципы работы

Skopeo построен на библиотеке `containers/image` (Go), которая абстрагирует работу с реестрами и транспортами. При выполнении операций Skopeo:

1. **Разбор URI:** Определяет транспорт по префиксу (`docker://`, `oci:`, `containers-storage:` и т.д.).
2. **Получение манифеста:** Через Distribution API v2 запрашивает манифест образа по тегу или дайджесту. Реестр возвращает Content-Addressable манифест (Docker v2.2 или OCI).
3. **Обработка манифест-списков:** Для multi-arch образов реестр возвращает `manifest list` (Docker) или `index` (OCI). Skopeo может:
   - копировать весь список (`--all`);
   - выбирать конкретные платформы (`--multi-arch=linux/amd64,linux/arm64`);
   - создавать sparse-индексы (только выбранные платформы).
4. **Копирование слоев:** Для каждого варианта платформы запрашивает конфигурацию и список слоев (blobs). Слои копируются напрямую между источником и назначением без промежуточного сохранения на диск (при `copy` между реестрами).
5. **Проверка целостности:** По завершении копирования сверяет дайджесты (`digestfile`) и при необходимости проверяет подписи через `policy.json`.

**Важно:** При копировании между `docker://` и `containers-storage:` слои записываются на диск, поэтому операция занимает место, аналогичное `docker pull`.

### Предварительные требования

Перед использованием Skopeo в production-сценариях убедитесь, что выполнены условия:

- **Версия:** `skopeo` ≥ 1.14 (тестировано на 1.23.x). Проверка: `skopeo --version`.
- **Сеть:** Доступ к реестрам по HTTPS (443/tcp). Для самоподписанных реестров — CA-сертификаты в `/etc/containers/certs.d/<registry>/` или флаг `--cert-dir`.
- **Аутентификация:** Файл `auth.json` в `$XDG_RUNTIME_DIR/containers/` (rootless) или `/etc/containers/auth.json` (root). Или переменная `REGISTRY_AUTH_FILE`.
- **Хранилище:** Для `containers-storage:` требуется настроенный `storage.conf` (см. [Podman: Rootless](./podman_rootless.md) для rootless-режима).
- **Реестр назначения:** Права на запись (`push`) для копирования и удаления. Некоторые реестры (Docker Hub, Amazon ECR) имеют ограничения на удаление через API.
- **Для air-gapped:** Физический носитель достаточного объёма или промежуточный реестр для sneakernet-переноса.

---

## Практические сценарии

### Установка

```bash
# Fedora / RHEL / Rocky Linux
sudo dnf install -y skopeo

# Debian / Ubuntu
sudo apt update && sudo apt install -y skopeo

# macOS (Homebrew)
brew install skopeo

# Контейнерный образ (для CI/CD и локальных проверок)
docker run --rm quay.io/skopeo/stable:latest inspect docker://docker.io/library/nginx:latest
```

Статические сборки для Linux и другие пакеты публикуются в разделе Releases проекта на GitHub. Актуальная стабильная версия — v1.23.x.

### 1. Инспекция удаленного образа

Позволяет проверить наличие нужной архитектуры или тега перед скачиванием.

```bash
# Просмотр общей информации (JSON): Name, Digest, RepoTags, Labels, Architecture, Os, Layers, Env
skopeo inspect docker://docker.io/library/nginx:latest

# Получение только дайджеста образа
skopeo inspect --format "{{.Digest}}" docker://docker.io/library/nginx:latest
# → sha256:4f4d1d2b3f2f2f3f3c0e0a0b0c0d0e0f0102030405060708090a0b0c0d0e0f00

# Сырой вывод манифеста без обработки (полезен для отладки и анализа тегов)
skopeo inspect --raw docker://docker.io/library/nginx:latest | jq .manifests

# Конфигурация образа (Cmd, Entrypoint, Env, Labels)
skopeo inspect --config docker://docker.io/library/nginx:latest

# Инспекция варианта для другой платформы без скачивания слоев
skopeo inspect --override-arch arm64 --override-os linux docker://docker.io/library/nginx:latest

# Пропустить запрос списка тегов (быстрее, если RepoTags не нужен)
skopeo inspect --no-tags docker://docker.io/library/nginx:latest
```

### 2. Копирование образов

#### Между реестрами (Direct Copy)
```bash
skopeo copy \
    --src-creds user:pass1 \
    --dest-creds user:pass2 \
    docker://registry-1.com/app:v1 \
    docker://registry-2.com/app:v1
# → stdout пуст при успехе; проверка: skopeo inspect docker://registry-2.com/app:v1
```

#### Копирование всех архитектур (Multi-arch)
Флаг `--all` (эквивалент `--multi-arch=all`) гарантирует, что будут скопированы все варианты образа (x86_64, arm64 и т.д.), а также сам манифест-список.
```bash
skopeo copy --all docker://quay.io/libpod/alpine:latest oci:alpine-multi:latest
# → создаётся каталог alpine-multi/ с blobs/ и index.json; проверка: ls alpine-multi/blobs/sha256
```

#### Выборочное копирование платформ
Флаг `--multi-arch` принимает `system` (по умолчанию), `all`, `index-only` или список платформ. Режимы `index-only` и список платформ создают разреженные (sparse) манифест-списки:
```bash
skopeo copy --multi-arch=linux/amd64,linux/arm64 \
    docker://registry-1.com/app:v1 \
    docker://registry-2.com/app:v1
# → создаётся sparse manifest list только с amd64+arm64; проверка: skopeo inspect --raw docker://registry-2.com/app:v1 | jq '.manifests | length'
```

#### Прочие полезные опции `copy`

```bash
# Смена формата манифеста (oci | v2s1 | v2s2)
skopeo copy --format oci docker://registry-1.com/app:v1 oci:app-local:latest
# → создаётся каталог app-local/ в формате OCI Layout (blobs/, index.json, oci-layout)

# Сохранение дайджеста результата в файл (для CI/CD и аудита)
skopeo copy --digestfile image.digest docker://registry-1.com/app:v1 docker://registry-2.com/app:v1
# → файл image.digest содержит sha256:...

# Копирование для другой платформы (кросс-архитектурный перенос)
skopeo copy --override-arch arm64 --override-os linux \
    docker://registry-1.com/app:v1 docker://registry-2.com/app:v1
# → на стороне назначения будет запись только для linux/arm64

# Небезопасный реестр (HTTP / самоподписанный TLS)
skopeo copy --dest-tls-verify=false docker://registry-1.com/app:v1 docker://internal-registry.local/app:v1
# → используется только для тестовых сред; в production добавьте CA в /etc/containers/certs.d/

# Сжатие слоев при сохранении в dir-каталог (gzip | zstd | zstd:chunked)
skopeo copy --dest-compress --dest-compress-format zstd \
    docker://registry-1.com/app:v1 dir:/tmp/app
# → слои в /tmp/app/ сжаты в формат zstd; проверка: file /tmp/app/*.zst

# Архив, совместимый с docker load
skopeo copy docker://busybox:latest docker-archive:busybox.tar:busybox:latest
# → файл busybox.tar; проверка: tar -tf busybox.tar | head

# Сохранение дайджестов при копировании между OCI Layout (иначе слои могут пересжиматься)
skopeo copy --preserve-digests oci:src:latest oci:dst:latest
# → дайджест blobs совпадает с источником; проверка: diff <(skopeo inspect --raw oci:src:latest | jq -r .layers[].digest) <(skopeo inspect --raw oci:dst:latest | jq -r .layers[].digest)

# Устойчивость к сбоям сети
skopeo copy --retry-times 3 --retry-delay 5s docker://... docker://...
# → при обрыве соединения повторяется до 3 раз с задержкой 5 секунд
```

### 3. Синхронизация репозиториев (Mirroring)

Для зеркалирования используется команда `sync`. Она полезна для наполнения внутренних реестров и air-gapped-сред. В отличие от остальных команд, транспорты источника и назначения задаются отдельными флагами `--src` и `--dest`.

```bash
# Синхронизация всех тегов из одного проекта в другой
# (если тег не указан, копируются ВСЕ теги репозитория)
skopeo sync --src docker --dest docker \
    my-registry.com/my-project \
    internal-registry.com/my-project
# → прогресс копирования по каждому тегу; при успехе все теги появляются в целевом репозитории

# Сохранение пути источника в структуре назначения (без потери namespace)
skopeo sync --src docker --dest docker --scoped \
    my-registry.com/a/b internal-registry.com
# → my-registry.com/a/b/* → internal-registry.com/a/b/*

# Добавление суффикса к тегам на стороне назначения
skopeo sync --src docker --dest docker --append-suffix '-mirror' \
    my-registry.com/busybox internal-registry.com
# → теги latest → latest-mirror, 1.0 → 1.0-mirror

# Режим пробного прогона (ничего не копируется)
skopeo sync --src docker --dest docker --dry-run my-registry.com/busybox internal-registry.com
# → вывод списка операций без выполнения

# Из локального каталога (dir:) в реестр
skopeo sync --src dir --dest docker /media/usb/busybox:1-glibc my-registry.local.lan/test/
# → образы из /media/usb/ загружаются в реестр

# Продолжить обработку остальных образов при ошибках, в конце завершиться с ошибкой
skopeo sync --src docker --dest docker --keep-going my-registry.com internal-registry.com
# → возвращает ненулевой код, если хотя бы один образ не скопирован
```

#### Синхронизация по YAML-файлу

Позволяет задавать списки образов, фильтры по тегам (regex, semver) и учетные данные для каждого реестра:

```yaml
registry.example.com:
    images:
        busybox: []
        redis:
            - "1.0"
            - "2.0"
    images-by-tag-regex:
        nginx: ^1\.13\.[12]-alpine-perl$
    images-by-semver:
        alpine: ">= 3.12.0"
    credentials:
        username: john
        password: this is a secret
    tls-verify: true
quay.io:
    tls-verify: false
    images:
        coreos/etcd:
            - latest
```

```bash
skopeo sync --src yaml --dest docker sync.yml my-registry.local.lan/repo/
# → создаётся структура реестров; проверка: skopeo list-tags docker://my-registry.local.lan/repo/busybox
```

### 4. Авторизация (Login)

Вместо передачи учетных данных в каждой команде можно авторизоваться один раз.

```bash
skopeo login registry.example.com -u username -p password
# → Login Succeeded (или аналогичное подтверждение); файл auth.json обновлён

# Безопасный ввод пароля (не будет виден в истории)
skopeo login registry.example.com -u username
# Password: **** (интерактивный ввод)

# Указание собственного файла учетных данных
skopeo login --authfile /path/to/auth.json registry.example.com -u username

# Совместимость с файлом Docker (~/.docker/config.json)
skopeo login --compat-auth-file ~/.docker/config.json registry.example.com -u username

# Завершение сессии
skopeo logout registry.example.com
# → credentials удалены из auth.json для указанного реестра
```

### 5. Удаление образов из реестра

```bash
# Удаление тега из реестра (требует поддержки метода DELETE реестром)
skopeo delete docker://registry.example.com/team/app:v1.0.0
# → stdout пуст при успехе; тег больше не возвращается в list-tags
```

Примечания:
- Работает по протоколу Distribution API v2; некоторые реестры запрещают или ограничивают удаление через API (например, Amazon ECR — удаление выполняется через untag, Docker Hub — через веб-интерфейс).
- Удаление тега не удаляет слои (blobs) — это делается отдельной процедурой очистки (garbage collection) реестра.
- Удаление по дайджесту: `skopeo delete docker://registry.example.com/team/app@sha256:...`.

### 6. Список тегов репозитория

```bash
skopeo list-tags docker://docker.io/library/nginx
# → {"Repository":"docker.io/library/nginx","Tags":["1.25","1.26","latest",...]}

# Только имена тегов (полезно для скриптов)
skopeo list-tags --format "{{.Tag}}" docker://docker.io/library/nginx
```

### 7. Манипуляции манифестами

Команда `manifest` позволяет получать и изменять манифесты и манифест-списки напрямую в реестре.

```bash
# Получение манифеста (или манифест-списка) в JSON
skopeo manifest get docker://registry.example.com/team/app:latest
# → JSON-структура манифеста (schemaVersion, config, layers)

# Сырой вывод без обработки
skopeo manifest get --raw docker://registry.example.com/team/app:latest
# → сырые байты/base64 манифеста

# Добавление варианта в существующий манифест-список (требует прав на запись)
skopeo manifest add --all docker://registry.example.com/team/app:latest docker://registry.example.com/team/app:arm64
# → манифест-список обновлён; проверка: skopeo inspect --raw docker://... | jq '.manifests | length'

# Удаление варианта из списка по дайджесту
skopeo manifest remove docker://registry.example.com/team/app:latest sha256:6d6b7d4f...
# → запись удалена из списка; остальные платформы сохранены

# Вычисление дайджеста манифеста из файла
skopeo manifest digest manifest.json
# → sha256:...
```

### 8. Шифрование и дешифрование образов

Skopeo может шифровать образы при копировании. Поддерживаемые протоколы: `jwe:` (RFC7516), `pgp:` (RFC4880), `pkcs7:` (RFC2315).

```bash
# Шифрование образа при копировании в локальный каталог
skopeo copy \
    --encryption-key jwe:/path/to/public_key.pem \
    docker://nginx:latest oci:encrypted-nginx:latest
# → слои в oci:encrypted-nginx:latest зашифрованы; проверка: skopeo inspect --raw oci:encrypted-nginx:latest | jq '.["layers"][0]["annotations"]'

# Дешифрование при копировании
skopeo copy \
    --decryption-key /path/to/private_key.pem \
    oci:encrypted-nginx:latest docker://registry.example.com/nginx:latest
# → на стороне назначения обычные (незашифрованные) слои

# Шифрование по PGP-получателю
skopeo copy --encryption-key pgp:recipient@example.com docker://nginx:latest oci:encrypted-nginx:latest
# → слои зашифрованы ключом recipient@example.com

# Частичное шифрование отдельных слоев (экспериментально; индексы с 0, отрицательные с конца)
skopeo copy --encryption-key jwe:./public.key --encrypt-layer 1 oci:local_nginx:1.17.8 oci:try-encrypt:encrypted
# → только слой с индексом 1 зашифрован; проверка: skopeo inspect --raw oci:try-encrypt:encrypted | jq '.["layers"][] | {digest, annotations}'
```

### 9. Подписи (Signatures)

Skopeo поддерживает два основных механизма подписи: «simple signing» (GPG) и sigstore (cosign-совместимые подписи).

```bash
# Генерация пары ключей sigstore (формат cosign, ECDSA-P256)
skopeo generate-sigstore-key --output-prefix cosign
# → создаются файлы cosign.key и cosign.pub

# Подпись образа при копировании приватным ключом sigstore
skopeo copy \
    --sign-by-sigstore-private-key cosign.key \
    docker://source/app:v1 docker://prod/app:v1
# → образ подписан; проверка: skopeo inspect --raw docker://prod/app:v1 | jq '.["signatures"]'

# GPG-подпись (simple signing), ключ определяется по ID
skopeo copy --sign-by dev@example.com docker://source/app:v1 docker://prod/app:v1
# → добавлена запись в сигнатуры с ID dev@example.com

# Копирование без переноса подписей (если реестр назначения их не поддерживает)
skopeo copy --remove-signatures docker://signed/app:v1 docker://plain/app:v1
# → на стороне назначения массив signatures пуст
```

Отладочные подкоманды `standalone-sign` / `standalone-verify` работают с локальными файлами манифестов и не взаимодействуют с реестром:

```bash
skopeo standalone-sign manifest.json docker://registry.example.com/app:v1 private.key --output signature
skopeo standalone-verify manifest.json docker://registry.example.com/app:v1 public.key
```

---

## Безопасность и политики

### Политики подписи (Signature Verification)
Skopeo поддерживает проверку подписей образов через файл конфигурации `/etc/containers/policy.json`. Это позволяет блокировать запуск или копирование образов из недоверенных источников. Файл по умолчанию поставляется в проекте как `default-policy.json` (обычно разрешает всё, кроме подписей, которые проверяются при наличии ключей).

Ключевые сценарии использования `policy.json`:
- требовать подпись определенными ключами для конкретных реестров;
- разрешать только зеркала (`mirrors`) для уязвимых образов;
- блокировать полностью недоверенные источники.

Подробнее: **[Политики подписи образов](../Docker/Docker_security/image_signature_and_verification.md)**.

### Проверка TLS

- `--tls-verify=true|false` — включать/отключать проверку HTTPS-сертификатов (для `inspect`, `delete`, `list-tags`, `login`).
- `--src-tls-verify` / `--dest-tls-verify` — раздельная настройка для источника и назначения (для `copy`, `sync`).
- `--cert-dir` / `--src-cert-dir` / `--dest-cert-dir` — каталог с собственными CA-сертификатами (`*.crt`, `*.cert`, `*.key`).
- Альтернатива — каталог системного формата `/etc/containers/certs.d/<registry>/ca.crt`.

---

## Интеграция в CI/CD

Skopeo является стандартом для современных CI/CD пайплайнов благодаря своей легковесности и безопасности: не требует демона, привилегий root и лишнего дискового пространства (слои не скачиваются на диск раннера).

**Пример в GitLab CI (Promote image):**

```yaml
promote-to-production:
  stage: release
  image: quay.io/skopeo/stable:v1.23
  script:
    - skopeo copy --all
        --src-creds $CI_REGISTRY_USER:$CI_REGISTRY_PASSWORD
        --dest-creds $PROD_REGISTRY_USER:$PROD_REGISTRY_PASSWORD
        docker://$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
        docker://$PROD_REGISTRY_IMAGE:stable
    - skopeo copy --digestfile image.digest
        docker://$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
        docker://$PROD_REGISTRY_IMAGE:stable
    - cat image.digest
```

**Рекомендации для пайплайнов:**
- Используйте `--all` / `--multi-arch=all` для продвижения мультиархитектурных образов, чтобы не потерять варианты под другие архитектуры.
- Передавайте учетные данные через секреты (переменные CI) или монтируйте `--authfile` с заранее выполненным `skopeo login` вместо пароля в открытом виде.
- Добавляйте `--retry-times 3 --retry-delay 5s` для устойчивости к временным сбоям реестра.
- Для самоподписанных внутренних реестров настраивайте `--dest-tls-verify=false` только в изолированных внутренних сетях.
- Для air-gapped-окружений используйте `skopeo sync` из внешнего реестра в переносимые каталоги — сценарий описан в **[Air-gapped кластеры](../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)**.

---

## Валидация и проверка

После каждой операции с образами рекомендуется выполнять проверку целостности и корректности:

```bash
# 1. Проверка версии и доступности бинарника
skopeo --version
# → skopeo version 1.23.0

# 2. Проверка доступности удалённого образа (до копирования)
skopeo inspect --no-tags docker://registry.example.com/app:v1.0.0
# → JSON с метаданными (Name, Digest, Architecture, Os)

# 3. Сравнение дайджестов после копирования между реестрами
SRC_DIGEST=$(skopeo inspect --format '{{.Digest}}' docker://source-reg/app:v1)
DEST_DIGEST=$(skopeo inspect --format '{{.Digest}}' docker://dest-reg/app:v1)
[ "$SRC_DIGEST" = "$DEST_DIGEST" ] && echo "OK: дайджесты совпадают" || echo "FAIL: расхождение"

# 4. Проверка multi-arch копирования (все архитектуры на месте)
skopeo inspect --raw docker://dest-reg/app:v1 | jq '.manifests | length'
# → ожидается >= 2 для multi-arch образа

# 5. Проверка подписи образа
skopeo inspect --raw docker://registry.example.com/signed-app:v1 | jq -r '.["signatures"] // "no signatures"'

# 6. Проверка политик подписи (файл policy.json)
cat /etc/containers/policy.json | jq '.transports.docker["registry.example.com"].signature.pull'

# 7. Проверка доступности storage.conf (для containers-storage)
podman info --format '{{.Store.Info}}'
# → содержит путь к storage driver и graphRoot
```

## Типичные проблемы и решения

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `tls: failed to verify certificate` | Самоподписанный или неверный CA-сертификат реестра | Добавить CA в `/etc/containers/certs.d/<registry>/ca.crt` или использовать `--cert-dir` / `--dest-tls-verify=false` (только для тестовых сред). |
| `unauthorized: authentication required` | Неверные учетные данные или отсутствующий `auth.json` | Проверить `skopeo login <registry>`, существование файла `auth.json`, права доступа (`chmod 600`). |
| `manifest unknown` / `404` | Тег не существует или удален; неверный дайджест | Проверить `skopeo list-tags docker://<registry>/<repo>`, убедиться что тег не был удален или перезаписан. |
| `no matching manifest for linux/<arch>` | Multi-arch образ не содержит запрошенной архитектуры | `skopeo inspect --raw docker://image \| jq .manifests` — проверить список доступных платформ. |
| `rate limit exceeded` | Превышен лимит запросов Docker Hub или другого реестра | Добавить аутентификацию (увеличенные лимиты для authenticated pull), использовать кэширующий прокси (Harbor), добавить `--retry-times`. |
| `no space left on device` | Недостаточно места в `graphRoot` при копировании в `containers-storage:` | Проверить `df -h $(podman info --format '{{.Store.GraphRoot}}')`, очистить неиспользуемые образы `podman system prune -a`. |
| `connection timed out` / `i/o timeout` | Сетевая недоступность реестра, firewall, DNS | Проверить `curl -v https://<registry>/v2/`, DNS (`dig <registry>`), proxy (`HTTP_PROXY`, `NO_PROXY`). |
| `signature not found` или `policy.json rejection` | Образ не подписан или подписан неизвестным ключом | Проверить `skopeo inspect --raw` на наличие `signatures`, импортировать публичный ключ в `/etc/containers/policy.json` или использовать `--remove-signatures` при копировании, если политика источника позволяет. |

## Рекомендации и ограничения

### Production-hardening

- **Учетные данные:** Никогда не передавайте пароль через флаг `-p` в CI/CD — используйте `--authfile` с предварительным `skopeo login` или переменные окружения через секрет-менеджер (Vault, SOPS).
- **TLS:** В production используйте `--tls-verify=true` (по умолчанию). Самоподписанные сертификаты размещайте в `/etc/containers/certs.d/`.
- **Ретраи:** Для нестабильных сетей добавляйте `--retry-times 5 --retry-delay 10s`.
- **Дайджесты:** Для критичных операций сохраняйте дайджест (`--digestfile`) и проверяйте его после копирования.
- **Сетевые лимиты:** Для больших пакетов образов используйте `--retry-times` и ограничьте параллельность через shell-скрипты, чтобы не превысить лимиты реестра.

### Ограничения

- **Нет сборки образов:** Skopeo работает только с существующими образами и манифестами. Для сборки используйте Buildah или Docker BuildKit.
- **Ограничения удаления:** Не все реестры поддерживают DELETE Distribution API (Docker Hub — ограниченно, Amazon ECR — через untag). Удаление по дайджесту (`@sha256:`) работает шире, чем по тегу.
- **Производительность при больших образах:** При копировании между реестрами слои передаются напрямую, но крупные слои (>1 ГБ) чувствительны к таймаутам. Используйте `--retry-times` и проверьте `TCP keepalive` на уровне ОС.
- **Referrers и связанные артефакты:** В версиях < 1.23 копирование с `--all` не переносит связанные аттестации (attestations) и артефакты. Обновитесь или повторно подпишите образ после импорта.
- **Режим offline:** Skopeo требует сетевого доступа к реестру-источнику и реестру-назначению. Для полностью air-gapped сред используйте промежуточные транспорты (`dir:`, `oci-archive:`) и физические носители.

---

## Дополнительная информация

### Связанные разделы
- **[Buildah: Сборка образов](./buildah_overview.md)** — подготовка артефактов для передачи.
- **[Podman vs Docker](./podman_vs_docker.md)** — общая экосистема инструментов.
- **[Продвижение образов в CI/CD](../Docker/Docker_fs/images/promotion_cicd.md)** — стратегии перемещения между окружениями.

### Ссылки
- **[Официальный репозиторий Skopeo](https://github.com/podman-container-tools/skopeo)**
- **[Руководство по синхронизации (Sync)](https://github.com/containers/skopeo/blob/main/docs/skopeo-sync.1.md)**
