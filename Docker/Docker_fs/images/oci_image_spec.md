# OCI Image Spec: структура образа изнутри

**Актуально для:** OCI Image Spec 1.1, Docker 24.x–29.x, containerd 1.7.x–2.4.x, skopeo v1.14+–v1.24+

## Предварительные требования

Перед выполнением практических сценариев убедитесь, что окружение готово:

- **Docker Engine** версии **24.0+** (BuildKit включён по умолчанию с 23.0+). Проверка: `docker version --format '{{.Server.Version}}'` → `29.8.1`.
- **Утилиты для инспекции**: `jq` (парсинг JSON), `tar` (распаковка слоёв), `sha256sum` (проверка дайджестов). Опционально: `skopeo` ≥ 1.14 (daemonless-инспекция), `crane` (работа с манифестами без демона).
- **Доступ к реестру** (для сценариев с удалёнными образами): `docker login` для приватных реестров.
- **Базовые навыки Linux**: `cat`, `find`, `du`, понимание JSON и tar-архивов.

## Определения

- **OCI Image Spec** — спецификация Open Container Initiative, описывающая формат образа контейнера: манифест, конфигурацию и слои. Стандарт де-факто для всех рантаймов (Docker, containerd, CRI-O, Podman). Репозиторий: [opencontainers/image-spec](https://github.com/opencontainers/image-spec).
- **Manifest** — JSON-документ (`application/vnd.oci.image.manifest.v1+json`), описывающий образ: ссылка на config blob и массив ссылок на layer blobs. Каждый blob адресуется своим SHA256-дайджестом.
- **Config blob** — JSON-документ (`application/vnd.oci.image.config.v1+json`) с метаданными образа: архитектура, ОС, переменные окружения, команда по умолчанию (`CMD`/`ENTRYPOINT`), история сборки и `rootfs.diff_ids` — хеши **несжатых** слоёв.
- **Layer blob** — tar-архив (обычно gzip/zstd-сжатый в реестре), представляющий дельту файловой системы (changeset). Слои **применяются** (apply) в порядке от `layers[0]` (базовый) к последнему — они не просто распаковываются, а накладываются с учётом whiteout-записей (см. «Формат слоя: changeset, whiteout и атрибуты»); итоговое дерево ФС — результат последовательного наложения всех слоёв на пустой каталог.
- **Whiteout** — специальная пустая запись в tar-слое с именем вида `.wh.<basename>`, означающая удаление пути `<basename>` из нижележащих слоёв. Непрозрачный whiteout `.wh..wh..opq` скрывает всё содержимое каталога из нижних слоёв. Подробнее — в «Формат слоя: changeset, whiteout и атрибуты».
- **Image Index (Manifest List)** — JSON-документ (`application/vnd.oci.image.index.v1+json`), ссылающийся на несколько манифестов для разных платформ (`linux/amd64`, `linux/arm64`). Используется для multi-arch образов; один тег указывает на индекс, а рантайм выбирает нужный манифест по платформе хоста.
- **Descriptor** — объект `{mediaType, digest, size}`, адресующий blob по содержимому (content-addressable). Один и тот же blob (по дайджесту) может переиспользоваться разными образами — это основа дедупликации слоёв.
- **OCI Image Layout** — стандартная структура каталогов для хранения OCI-образов на диске: `blobs/sha256/<digest>`, маркер `oci-layout` и точка входа `index.json`. Используется `skopeo copy ... oci-archive:`, `crane export` и containerd.
- **Media type** — MIME-тип, идентифицирующий формат blob (например, `application/vnd.oci.image.layer.v1.tar+gzip`). Реестры и рантаймы используют его для корректной интерпретации содержимого.
- **diff_id** — SHA256-хеш **несжатого** tar-слоя, хранящийся в config blob (`rootfs.diff_ids`). Отличается от дайджеста слоя в манифесте, который вычисляется от **сжатого** blob. Пара (digest, diff_id) позволяет верифицировать целостность при распаковке.

## Основные концепции

### Анатомия образа

Образ — не один файл, а набор связанных content-addressable blob'ов:

```text
Image Index (multi-arch, один тег)
  └── Manifest (linux/amd64)
        ├── Config blob (метаданные + diff_ids)
        └── Layer blobs (дельты ФС, gzip/zstd)
```

Манифест — это «оглавление»: он не содержит данных, а ссылается на config и слои по дайджесту. При `docker pull` рантайм скачивает манифест, затем — только те blobs, которых нет в локальном кэше (проверка по дайджесту).

### Структура манифеста (schemaVersion 2)

```json
{
  "schemaVersion": 2,
  "mediaType": "application/vnd.oci.image.manifest.v1+json",
  "config": {
    "mediaType": "application/vnd.oci.image.config.v1+json",
    "digest": "sha256:b5b2b2c507a0944348e0303114d8d93aaaa081732b86451d9bce1f432a537bc7",
    "size": 7023
  },
  "layers": [
    {
      "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
      "digest": "sha256:9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee8f0",
      "size": 32654
    },
    {
      "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
      "digest": "sha256:3c3a4604a545cdc127456d94e421cd355bca5b528f4a9c1905b15da2eb4a4c6b",
      "size": 16724
    }
  ],
  "annotations": {
    "org.opencontainers.image.created": "2026-08-22T12:00:00Z"
  }
}
```

Ключевые свойства:
- **Порядок слоёв фиксирован**: `layers[0]` — базовый слой, последующие — в порядке наложения (stack order). Финальное дерево ФС должно совпадать с результатом применения всех слоёв к пустому каталогу.
- **`subject`** (опционально) — ссылка на объект, к которому прикреплён данный манифест (используется для аттестаций через OCI 1.1 Referrers API: SBOM, provenance).
- **`annotations`** — метаданные (время создания, версия, источник). Меняют дайджест манифеста, но не содержимое слоёв.

### Структура config blob

Config blob содержит всё, что нужно для запуска контейнера:

```json
{
  "architecture": "amd64",
  "os": "linux",
  "config": {
    "Env": ["PATH=/usr/local/sbin:/usr/local/bin:...", "NGINX_VERSION=1.27"],
    "Cmd": ["nginx", "-g", "daemon off;"],
    "Entrypoint": ["/docker-entrypoint.sh"],
    "WorkingDir": "/usr/share/nginx/html",
    "ExposedPorts": {"80/tcp": {}},
    "Labels": {"maintainer": "NGINX Docker Maintainers"}
  },
  "rootfs": {
    "type": "layers",
    "diff_ids": [
      "sha256:5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef",
      "sha256:7268d8f7a5b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4b4"
    ]
  },
  "history": [
    {"created": "2026-08-01T00:00:00Z", "created_by": "/bin/sh -c #(nop) ADD file:abc in / "},
    {"created": "2026-08-02T00:00:00Z", "created_by": "/bin/sh -c #(nop) CMD [\"nginx\" \"-g\" \"daemon off;\"]", "empty_layer": true}
  ]
}
```

- **`rootfs.diff_ids`** — хеши **несжатых** слоёв. Их количество может быть меньше, чем `layers` в манифесте: инструкции, не меняющие ФС (`ENV`, `LABEL`, `CMD`, `WORKDIR`), создают запись в `history` с флагом `"empty_layer": true` и не добавляют слой в `rootfs`.
- **`history`** — история сборки (то, что показывает `docker history`). Полезна для аудита: каждая запись соответствует инструкции Dockerfile.

### Формат слоя: changeset, whiteout и атрибуты

Layer blob — это не просто tar-архив, а **changeset** (набор изменений), который **применяется** к нижележащим слоям, а не просто распаковывается:

- **Типы изменений**: добавление, модификация, удаление. Добавления и модификации записываются в tar как обычные файлы; удаления — через **whiteout**-записи.
- **Whiteout** — пустой файл с именем `.wh.<basename>`, означающий, что путь `<basename>` удалён из нижележащих слоёв. После применения whiteout сам скрывается. Запись `.wh.` без basename невалидна — реализации SHOULD вернуть ошибку.
- **Непрозрачный whiteout** (`.wh..wh..opq`) в каталоге скрывает **всё** содержимое этого каталога из нижних слоёв, включая подкаталоги и всех потомков (эквивалент явного whiteout на каждый элемент). Реализации SHOULD генерировать явные whiteout'ы, но MUST принимать оба формата.
- **Область действия**: whiteout действует только на ресурсы из нижних/родительских слоёв. Файл, созданный в том же слое, что и whiteout, может быть скрыт только whiteout'ом из последующего слоя.
- **Атрибуты**: для добавлений и модификаций сохраняются `mtime`, `uid`/`gid`, `mode`, расширенные атрибуты (`xattrs`), ссылки (`linkname` для symlink/hardlink). Hardlink'и хранятся как tar-записи типа `1` (GNU tar format). Sparse-файлы не рекомендуются (ненадёжная поддержка в tar-реализациях). Windows-атрибуты кодируются через PAX-расширения (`MSWINDOWS.fileattr`, `MSWINDOWS.rawsd`, `MSWINDOWS.mountpoint`).
- **Семантика применения**: если запись и существующий путь — оба каталога, атрибуты каталога заменяются атрибутами из changeset; во всех остальных случаях путь удаляется (`unlink`) и создаётся заново с содержимым и атрибутами из changeset.

Пример changeset (удаление `etc/my-app-config`, добавление `etc/my-app.d/default.cfg`):

```text
./etc/my-app.d/
./etc/my-app.d/default.cfg
./etc/.wh.my-app-config
```

Практическое следствие для SRE: `RUN rm` в Dockerfile создаёт whiteout, но файл **физически остаётся** в нижнем слое и извлекается при распаковке (Сценарий 3). Секреты, попавшие в слой, не удаляются последующими инструкциями — только multi-stage сборка или `RUN --mount=type=secret` (BuildKit) не оставляют их в слоях.

### Вычисление дайджестов и каноническая форма JSON

Все blob'ы адресуемы по содержимому (content-addressable): дайджест — это SHA256 от **точных байт** blob'а в том виде, в каком он хранится в реестре. Следствия:

- **Любое изменение байт меняет дайджест** — включая аннотации и конкретную сериализацию JSON манифеста. Порядок ключей в JSON семантически несущественен, но дайджест считается от конкретной последовательности байт, поэтому пересборка манифеста другим инструментом может дать другой дайджест при том же семантическом содержимом.
- **JSON-блоб'ы** (все media types `+json`) обязаны следовать I-JSON (RFC 7493): кодировка UTF-8, числа — IEEE 754 double precision, дублирующихся имён в объектах быть не должно. Реализации **MAY** использовать Canonical JSON (RFC 8785) — это повышает шанс, что разные инструменты запишут один и тот же семантический контент как один blob.
- **Дедупликация**: один и тот же слой (по дайджесту) физически хранится в реестре один раз и переиспользуется разными образами — основа экономии места в реестре и кэша `docker pull`.
- **Невозможность «молча» исправить**: реестры, кэширующие прокси и инструменты копирования **MUST NOT** модифицировать содержимое так, чтобы менялся дайджест — иначе артефакт перестаёт быть тем же самым образом.

Это объясняет, почему `docker save` → `docker load` сохраняет дайджесты: байты blob'ов переносятся без изменений.

### Media types: Docker vs OCI

Два семейства media types сосуществуют в реестрах. Реестры и рантаймы должны поддерживать оба для совместимости:

| Назначение | Docker (legacy) | OCI (стандарт) |
| :--- | :--- | :--- |
| Manifest | `application/vnd.docker.distribution.manifest.v2+json` | `application/vnd.oci.image.manifest.v1+json` |
| Config | `application/vnd.docker.container.image.v1+json` | `application/vnd.oci.image.config.v1+json` |
| Layer (gzip) | `application/vnd.docker.image.rootfs.diff.tar.gzip` | `application/vnd.oci.image.layer.v1.tar+gzip` |
| Layer (zstd) | — | `application/vnd.oci.image.layer.v1.tar+zstd` |
| Image Index | `application/vnd.docker.distribution.manifest.list.v2+json` | `application/vnd.oci.image.index.v1+json` |

**Практическое следствие:** при `skopeo copy` между реестрами media types могут конвертироваться; `docker save` (Docker 25+) записывает blob'ы с **OCI** media types, а `docker load` читает и Docker, и OCI media types. Инструменты (`crane`, `skopeo`) умеют читать оба формата.

Помимо перечисленных, спецификация определяет служебные media types без Docker-эквивалента: `application/vnd.oci.descriptor.v1+json` (дескриптор), `application/vnd.oci.layout.header.v1+json` (маркер `oci-layout`) и `application/vnd.oci.empty.v1+json` (пустой документ для неиспользуемых дескрипторов и не-образных артефактов).

### Аннотации (annotations)

`annotations` — опциональная карта `string → string` в манифесте, image index и дескрипторах. Правила: ключи уникальны в пределах карты; ключи SHOULD использовать обратную доменную нотацию (`com.example.myKey`); префикс `org.opencontainers` зарезервирован за OCI-спецификациями и не должен использоваться другими; потребители MUST NOT падать на неизвестных ключах.

Предопределённые ключи (OCI Image Spec):

| Ключ | Значение |
| :--- | :--- |
| `org.opencontainers.image.created` | время сборки (RFC 3339) |
| `org.opencontainers.image.authors` | контактные данные авторов |
| `org.opencontainers.image.url` | URL с информацией об образе |
| `org.opencontainers.image.documentation` | URL документации |
| `org.opencontainers.image.source` | URL исходного кода |
| `org.opencontainers.image.version` | версия упакованного ПО |
| `org.opencontainers.image.revision` | идентификатор ревизии в VCS |
| `org.opencontainers.image.vendor` | имя дистрибьютора |
| `org.opencontainers.image.licenses` | лицензии (выражение SPDX) |
| `org.opencontainers.image.ref.name` | имя ссылки (тег); валиден на дескрипторах в `index.json` |
| `org.opencontainers.image.title` | человекочитаемое название |
| `org.opencontainers.image.description` | описание упакованного ПО |
| `org.opencontainers.image.base.digest` | дайджест базового образа (инструкция `FROM`) |
| `org.opencontainers.image.base.name` | ссылка на базовый образ (инструкция `FROM`) |

Аннотации заменяют устаревшую Label Schema (`org.label-schema.*`); инструменты MAY поддерживать оба префикса для совместимости (например, `org.label-schema.build-date` ↔ `org.opencontainers.image.created`).

### OCI Image Layout

Стандартная структура для хранения образа на диске (используется `skopeo copy ... oci-archive:`, containerd, buildx `--output type=oci`):

```text
my-image/
├── oci-layout              # маркер: {"imageLayoutVersion": "1.0.0"}
├── index.json              # точка входа: список дескрипторов с аннотациями ref.name
└── blobs/
    └── sha256/
        ├── <manifest-digest>     # манифест
        ├── <config-digest>       # config blob
        └── <layer-digest>...     # слои
```

`index.json` — multi-descriptor entry point: может содержать несколько манифестов (multi-arch) с аннотацией `org.opencontainers.image.ref.name` (имя тега/платформы).

### Как `docker save`/`load` соотносится с OCI Layout

Начиная с **Docker 25.0** (`moby/moby#44598`), `docker save` создаёт **OCI Image Layout**: `oci-layout` (маркер `{"imageLayoutVersion": "1.0.0"}`), `index.json` (OCI image index; дескрипторы манифестов несут аннотации `org.opencontainers.image.ref.name` — тег, и имя образа), `blobs/sha256/<digest>` (OCI-манифесты, config blob'ы и слои). Для обратной совместимости в архиве дополнительно присутствуют `manifest.json` (список `RepoTags` + пути к blobs) и `repositories` (только при наличии тегов). Слои в таком архиве хранятся **несжатыми** (`application/vnd.oci.image.layer.v1.tar`) и именованы по `diff_id` — хешу несжатого tar. С **Docker 27.0** таймстемпы в архиве стабильны (epoch), что делает вывод воспроизводимым. Архивы Docker ≤24 использовали legacy-формат (`config/<sha>.json`, `<layer-id>/layer.tar`) — `docker load` читает оба. Подробности — в **[Переносе и экспорте образов](./diagnostics_transfer.md)**.

## Практические сценарии

### Сценарий 1: Инспекция манифеста напрямую (без демона)

Позволяет увидеть точную структуру образа в реестре — что именно тянется при `docker pull`.

```bash
# Через skopeo (daemonless)
skopeo inspect --raw docker://docker.io/library/nginx:1.27 | jq '{schemaVersion, mediaType, config, layers: [.layers[] | {mediaType, size, digest}]}'
# → {
# →   "schemaVersion": 2,
# →   "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
# →   "config": {"mediaType": "...", "digest": "sha256:...", "size": 7023},
# →   "layers": [{"mediaType": "...layer.v1.tar+gzip", "size": 32654, "digest": "sha256:..."}]
# → }

# Через crane (только дайджест манифеста)
crane digest docker.io/library/nginx:1.27
# → sha256:f6a02b669bf8e59b20d361e148045a5f15915a7704b4df915340156f4a883a45

# Через buildx (локально, после pull)
docker buildx imagetools inspect nginx:1.27 --format '{{json .Manifest}}' | jq .
```

**Валидация:** JSON содержит `config` и массив `layers`; сумма `size` слоёв приблизительно равна размеру образа в `docker images` (с учётом сжатия).

### Сценарий 2: Извлечение и анализ config blob

Config blob — источник правды о метаданных образа (Env, Cmd, Entrypoint, Labels).

```bash
# 1. Получить дайджест config из манифеста
CONFIG_DIGEST=$(skopeo inspect --raw docker://nginx:1.27 | jq -r '.config.digest')

# 2. Скачать config blob напрямую через Registry API (см. Registry API v2)
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://registry-1.docker.io/v2/library/nginx/blobs/$CONFIG_DIGEST" | jq '{architecture, os, config: .config | {Env, Cmd, Entrypoint, Labels}, diff_ids: .rootfs.diff_ids}'
# → {
# →   "architecture": "amd64",
# →   "os": "linux",
# →   "config": {"Env": [...], "Cmd": ["nginx", "-g", "daemon off;"], ...},
# →   "diff_ids": ["sha256:...", ...]
# → }
```

**Валидация:** `diff_ids` — хеши несжатых слоёв; их количество ≤ количества `layers` в манифесте (разница — `empty_layer` инструкции).

### Сценарий 3: Распаковка слоёв вручную

Когда нужно точно понять, какие файлы содержит конкретный слой (аудит секретов, поиск мусора).

```bash
# 1. Сохранить образ
docker save nginx:1.27 -o nginx.tar

# 2. Распаковать архив
mkdir -p /tmp/nginx-img && tar -xf nginx.tar -C /tmp/nginx-img

# 3. Найти слой по дайджесту и распаковать.
# В Docker 25+ слои в `docker save` — несжатые tar-блобы: blobs/sha256/<diff_id>
# (пути перечислены в manifest.json и в OCI-манифесте внутри blobs/sha256/)
LAYER_DIGEST="sha256:9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee8f0"
mkdir -p /tmp/layer-inspect
tar -xf /tmp/nginx-img/blobs/sha256/${LAYER_DIGEST#sha256:} -C /tmp/layer-inspect
# Для архивов Docker ≤24 (legacy-формат) слой лежит в <layer-id>/layer.tar:
#   tar -xf /tmp/nginx-img/<layer-id>/layer.tar -C /tmp/layer-inspect

# 4. Просмотреть содержимое (whiteout-записи .wh.* видны — это маркеры удалений)
find /tmp/layer-inspect | head
# → /tmp/layer-inspect/etc/nginx/nginx.conf
# → /tmp/layer-inspect/usr/sbin/nginx
```

**Валидация:** в `/tmp/layer-inspect` — плоское дерево ФС, соответствующее изменениям этого слоя. Пустой результат `find` означает 0B-слой (только метаданные). Записи вида `.wh.<name>` — whiteout'ы: они означают удаление `<name>` из нижних слоёв, а не наличие файла.

### Сценарий 4: Проверка целостности по дайджесту

Верификация, что скачанный blob не повреждён и соответствует манифесту.

```bash
# 1. Скачать слой
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://registry-1.docker.io/v2/library/nginx/blobs/sha256:9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee8f0" \
  -o /tmp/layer.tar.gz

# 2. Проверить дайджест
echo "9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee8f0  /tmp/layer.tar.gz" | sha256sum -c -
# → /tmp/layer.tar.gz: OK

# 3. Проверить diff_id (несжатый хеш) — распаковать и захешировать
gunzip -c /tmp/layer.tar.gz | sha256sum
# → 5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef  (должен совпасть с diff_ids в config)
```

**Валидация:** дайджест сжатого blob совпадает с `layers[].digest` манифеста; хеш несжатого tar совпадает с `rootfs.diff_ids` config blob. Несовпадение — повреждение или подмена.

### Сценарий 5: OCI Layout через skopeo

Создание стандартного OCI Layout на диске для аудита или переноса в air-gapped среду.

```bash
# Копировать образ в OCI Layout на диске
skopeo copy docker://nginx:1.27 oci:/tmp/nginx-oci:nginx
# → Copying blob sha256:...
# → Writing manifest to image destination

# Структура
find /tmp/nginx-oci -maxdepth 2
# → /tmp/nginx-oci/oci-layout
# → /tmp/nginx-oci/index.json
# → /tmp/nginx-oci/blobs/sha256/...

# Инспекция без демона
skopeo inspect oci:/tmp/nginx-oci:nginx
# → {"Name": "nginx", "Digest": "sha256:...", "Layers": ["sha256:..."], ...}
```

**Валидация:** `oci-layout` содержит `{"imageLayoutVersion": "1.0.0"}`; `index.json` — массив дескрипторов; каждый blob в `blobs/sha256/` адресуется своим дайджестом.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `manifest unknown` при инспекции | Неверный тег или реестр | `skopeo inspect --raw docker://<registry>/<name>:<tag>`; проверьте имя репозитория и тег |
| `blob unknown` при скачивании | Blob удалён GC реестра или неверный дайджест | Проверьте дайджест в манифесте; `skopeo inspect --raw` для актуального манифеста |
| Дайджест слоя не совпадает с `diff_ids` | Повреждение при переносе или подмена | Перекачайте blob; сравните `sha256sum` сжатого и `gunzip \| sha256sum` несжатого |
| `docker save` не содержит OCI Layout | Архив создан Docker ≤24 (legacy-формат) или используется `skopeo copy` без `oci:`-назначения | Docker 25+ создаёт OCI Layout штатно; для старых версий и daemonless-конвертации используйте `skopeo copy ... oci-archive:` или `buildx --output type=oci` |
| Media type unknown при `skopeo copy` | Реестр хранит образ в формате, не поддерживаемом инструментом | Обновите `skopeo`/`crane`; реестры должны поддерживать и Docker, и OCI media types |
| `index.json` пуст после `skopeo copy oci:` | Не указан reference (тег) для OCI Layout | `skopeo copy docker://img oci:/path:tag` — reference обязателен для записи в `index.json` |
| Количество `diff_ids` ≠ количеству `layers` | Норма: `empty_layer` инструкции (ENV, LABEL, CMD) не создают слоёв | Сравните `history` в config blob: записи с `"empty_layer": true` не имеют слоя |
| Размер образа не уменьшается после `RUN rm` | Whiteout: файл скрыт в нижнем слое, но физически остаётся | `docker history` покажет слой с `rm`; распакуйте слои (Сценарий 3) — файл на месте. Для удаления данных используйте multi-stage сборку или `RUN --mount=type=secret` |

## Рекомендации и очистка

**Лучшие практики:**
- Для аудита состава образа используйте `skopeo inspect --raw` + `jq` — это быстрее, чем `docker pull` + `docker save`, и не требует демона.
- При верификации целостности проверяйте и дайджест сжатого blob (совпадение с `layers[].digest`), и `diff_id` (совпадение с `rootfs.diff_ids`) — это покрывает и транспорт, и содержимое.
- Для multi-arch образов всегда инспектируйте **Image Index** (`--raw`), а не один манифест — иначе можно пропустить платформу.
- При переносе в air-gapped среду используйте OCI Layout (`skopeo copy ... oci-archive:`) — он стандартизирован и поддерживается containerd/nerdctl напрямую.
- Не полагайтесь на `docker history` для точного состава слоёв — он показывает `history` из config blob, где `empty_layer` записи не соответствуют реальным слоям. Для точного состава — `skopeo inspect --raw` + распаковка слоёв.
- При аудите слоёв учитывайте whiteout: `RUN rm` не удаляет данные из нижних слоёв — файл извлекается при распаковке архива (Сценарий 3). Секреты не удаляйте из образа инструкцией `RUN rm` — используйте BuildKit secret-mount (`RUN --mount=type=secret`) или multi-stage сборку.

**Очистка окружения:**
```bash
# Удалить временные распакованные образы
rm -rf /tmp/nginx-img /tmp/layer-inspect /tmp/nginx-oci /tmp/nginx.tar /tmp/layer.tar.gz
```

## Особые случаи и ограничения

- **`empty_layer`**: инструкции `ENV`, `LABEL`, `CMD`, `ENTRYPOINT`, `WORKDIR`, `EXPOSE` меняют только config blob (и его дайджест), но не создают layer blob. Поэтому `docker history` показывает их с размером 0B, а `rootfs.diff_ids` короче `layers`.
- **diff_id ≠ digest**: дайджест слоя в манифесте вычисляется от **сжатого** blob; `diff_id` в config — от **несжатого** tar. Это разные хеши одного слоя; оба нужны для верификации.
- **Docker vs OCI media types**: один и тот же образ может храниться в обоих форматах; дайджесты манифестов будут различаться (разный JSON), но слои (blobs) — те же. При сравнении образов из разных реестров сравнивайте дайджесты **слоёв**, а не манифестов.
- **OCI Artifacts**: тот же манифест-формат используется для не-образных артефактов (Helm-чарты, SBOM, подписи) через OCI 1.1 Referrers API — `config.mediaType` при этом может быть `application/vnd.oci.empty.v1+json`.
- **Non-distributable layers (deprecated)**: media types `application/vnd.oci.image.layer.nondistributable.v1.tar[+gzip|+zstd]` помечали слои с юридическими ограничениями на распространение. В OCI Image Spec 1.1 они **deprecated** (PR #965): реализации SHOULD NOT создавать новые такие слои, но должны поддерживать существующие образы. Дескрипторы таких слоёв MAY содержать поле `urls` для прямой загрузки у дистрибьютора.
- **Windows-контейнеры**: используют те же media types, но слои и конфигурация платформо-специфичны (`os: windows`); не переносимы на Linux-хост и наоборот.
- **containerd image store (Docker 29.0+ / containerd 2.3.x–2.4.x)**: хранит образы нативно в containerd content store (`/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256/`) — это и есть OCI-совместимые blobs; `docker save` прозрачен, но layout отличается от классического `/var/lib/docker`.

## Примечания по версиям

- **OCI Image Spec 1.1** (релиз — январь 2024): добавлены `subject` в манифесте и `artifactType` в дескрипторах (основа для Referrers API, определённой в OCI Distribution Spec 1.1), zstd-сжатие слоёв, аннотации на дескрипторах; non-distributable layers объявлены deprecated. Поддерживается Docker 27+, containerd 1.7+, Harbor 2.11+. На ветке `main` (пока не в релизе) зарегистрированы дополнительные алгоритмы дайджестов (`blake3`, `sha256+b64u`) — не применяйте их в продакшене до выхода релиза.
- **OCI Image Spec 1.0**: базовая спецификация (manifest, config, layers, image index). Поддерживается всеми современными рантаймами.
- **`docker save`**: с Docker 25.0 создаёт OCI Image Layout (см. «Как `docker save`/`load` соотносится с OCI Layout»); архивы Docker ≤24 — legacy-формат. Конвертация между форматами — через `skopeo`/`buildx`. С Docker 27.0 таймстемпы в архиве стабильны (воспроизводимый вывод).
- **`skopeo` ≥ 1.14**: поддерживает `oci-archive:`, `oci:`, `--all` для multi-arch, `inspect --raw` для daemonless-инспекции. Текущий стабильный релиз — 1.24.1 (1.24.1, 2026-09).
- **containerd**: актуальные линии — 2.4.x (2026-09) и 2.3.x LTS (апрель 2026); minor-релизы выходят по 4-месячному циклу (апрель/август/декабрь).

## Дополнительная информация

- **Спецификации**: [OCI Image Spec](https://github.com/opencontainers/image-spec) (manifest, config, layers, media types, image layout), [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec) (Registry API v2).
- **Структура образа в контексте Kubernetes** (pull lifecycle, kubelet → CRI → registry, snapshotter) — **[Ошибки загрузки образов: Определения](../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)**.
- **Перенос образов** (`docker save`/`load` vs `skopeo` vs OCI Layout) — **[Перенос и экспорт образов](./diagnostics_transfer.md)**.
- **Registry API v2** (прямая работа с реестром: auth flow, endpoints, удаление манифестов) — **[Registry HTTP API v2](../../Docker_registries/registry_api_v2.md)**.

### См. также

- **[Основы Docker-образов](./docker_images_basics.md)** — анатомия образа на уровне Docker CLI.
- **[Анализ и управление слоями](./layer_management.md)** — оптимизация структуры слоёв.
- **[Альтернативные среды выполнения](../../alternative_runtimes_and_tools.md)** — стандарты CRI и OCI, runc, containerd.
