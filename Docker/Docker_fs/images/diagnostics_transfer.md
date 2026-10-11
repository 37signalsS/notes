# Docker: Перенос и экспорт образов (save, load, export, import)

**Актуально для:** Docker 24.x–29.x, containerd 1.7.x–2.4.x, Kubernetes 1.29.x–1.32.x, Podman 5.x–6.x, nerdctl v2.x, skopeo v1.14+–v1.24+

Команды сериализации данных в архивы формата `tar` позволяют перемещать образы и файловые системы в изолированные среды (air-gapped) или выполнять миграцию данных без использования сетевых реестров. Это критически важный механизм для доставки артефактов в закрытые контуры, резервного копирования и аварийного восстановления.

## Предварительные требования

Перед выполнением практических сценариев убедитесь, что соблюдены условия:

- **Docker Engine** версии **24.0+** (BuildKit включён по умолчанию с 23.0+). Проверка: `docker version --format '{{.Server.Version}}'` → `29.8.1`. Для старых версий сборки multi-arch потребуется явный `docker buildx`.
- **Доступ к рантайму**: сокет `/var/run/docker.sock` (штатный демон) либо `DOCKER_HOST`, либо сокет целевого рантайма (containerd `/run/containerd/containerd.sock`). Без прав — `permission denied while trying to connect to the Docker daemon socket`.
- **Утилиты хоста** для диагностики и целостности: `tar`, `file`, `sha256sum`; для сжатия — `gzip` и (рекомендуется) `zstd`; для подписанной доставки — `gpg` (опционально).
- **Целевые инструменты по сценариям**:
  - Для загрузки в Kubernetes-рантайм — `nerdctl` v2.x (Docker-совместимый CLI для containerd) или низкоуровневый `ctr` (containerd); для CRI-O — `podman` v5.x–v6.x.
  - Для daemonless-переноса и multi-arch — `skopeo` ≥ 1.14 (проверка: `skopeo --version` → `skopeo version 1.23.0`).
  - Для сборки/инспекта multi-arch — `docker buildx` (проверка: `docker buildx version`).
- **Для air-gapped**: физический носитель (USB/внешний диск) с достаточным объёмом под архивы; носитель должен быть доверенным (целостность проверяется `sha256sum`/`gpg` на обоих концах).
- **Для Kubernetes**: кластер на базе containerd или CRI-O; образы должны попасть в пространство имён `k8s.io`, иначе kubelet их «не увидит».

## Определения

Docker предоставляет два набора команд для работы с архивами, которые имеют принципиальные различия в объектах обработки и сохраняемых метаданных.

- **`docker save` / `docker load`** — инструменты для работы с **образами**.
  - **`save`**: Сохраняет один или несколько образов в архив, полностью сохраняя структуру слоев, теги, историю сборки и метаданные (ENV, CMD, ENTRYPOINT).
  - **`load`**: Восстанавливает образы из архива в локальное хранилище Docker.
- **`docker export` / `docker import`** — инструменты для работы с **файловой системой контейнера**.
  - **`export`**: Создает "плоский" (flattened) архив текущего состояния файловой системы конкретного контейнера. Вся информация о слоях и история сборки теряется.
  - **`import`**: Создает **новый, однослойный** образ на основе архива файловой системы.
- **OCI Archive** — стандартизированный формат архива Open Container Initiative. Поддерживается современными инструментами (`skopeo`, `buildx`) для кросс-платформенного переноса. Отличается от «родного» формата `docker save` структурой манифеста, но семантически совместим — `skopeo` и `buildx` умеют конвертировать между ними.
- **Flatten (сплющивание)** — операция объединения всех слоёв образа в один слой файловой системы. Происходит при `docker export` и `docker import`. После неё теряется польза послойного кэширования и вся image-метаданная часть (см. «Особые случаи»).
- **Sneakernet** — перенос данных физическим носителем (буквально «сетью кроссовок»): единственный способ доставки в полностью изолированный контур без сетевого канала.

## Основные концепции

### Сравнение механизмов переноса

| Критерий | `save` / `load` | `export` / `import` |
| :--- | :--- | :--- |
| **Объект** | Образ (Image) | Контейнер (Container) |
| **Слои (Layers)** | Сохраняются (вся история) | Объединяются в один слой (Flatten) |
| **Метаданные (ENV, CMD)** | Сохраняются | Теряются (нужно указывать заново) |
| **Многофайловость** | Можно сохранить несколько образов в один `.tar` | Только одна ФС за раз |
| **Назначение** | Перенос артефактов в закрытые контуры, бэкап | Миграция ФС, создание базовых образов ("golden images") |

### Важные особенности

1. **Целостность данных**: При ручном переносе файлов через физические носители всегда проверяйте контрольные суммы (`sha256sum`). Для доверенной доставки — подпись `gpg` (см. Сценарий 7).
2. **Размер архивов**: `docker save` сохраняет все слои. Если образ основан на тяжелом базовом слое, архив будет весить много. Для уменьшения размера используйте сжатие (`gzip`, `zstd`).
3. **Метаданные при импорте**: При использовании `docker import` можно заново задать инструкции (`--change`), чтобы восстановить базовую функциональность (например, `CMD` или `ENV`).
4. **Многоархитектурность (Multi-arch)**: Стандартный `docker save` сохраняет образ только для текущей архитектуры. Для переноса multi-arch манифестов рекомендуется использовать `skopeo` или `buildx imagetools`.

### Архитектура архивов

Архивы, создаваемые `docker save`, `docker export` и `skopeo`, имеют принципиально разную внутреннюю структуру, что определяет их применение в операционных процессах.

**Формат `docker save` (Docker 25.0+ — OCI Image Layout):**
- **`oci-layout`**: маркер `{"imageLayoutVersion": "1.0.0"}`.
- **`index.json`**: OCI image index; дескрипторы манифестов несут аннотации `org.opencontainers.image.ref.name` (тег) и имя образа.
- **`blobs/sha256/<digest>`**: все blob'ы — OCI-манифесты, config blob'ы и слои. Слои — **несжатые** tar (`application/vnd.oci.image.layer.v1.tar`), именованные по `diff_id`.
- **`manifest.json`** (обратная совместимость): список записей `RepoTags` + пути к blobs (`Config`, `Layers`). Один архив может содержать несколько образов.
- **`repositories`**: отображение тегов на дайджесты для обратного разрешения имён; присутствует только при наличии тегов.
- Таймстемпы в архиве стабильны (epoch) с Docker 27.0 — вывод воспроизводим.
- При загрузке `docker load` восстанавливает теги, дайджесты и слои в том же порядке, сохраняя возможность кэширования.
- Архивы Docker ≤24 (legacy-формат): `config/<sha256>.json`, `<layer-id>/layer.tar` вместо `blobs/`; `docker load` читает оба формата.

**Формат `docker export` (Container FS Archive):**
- Единственный плоский tar-архив без манифеста и слоёв.
- Содержит смонтированное представление `merged` из overlay2: все файлы из образов + writable layer, объединённые в единое дерево.
- Device-файлы, симлинки, права доступа копируются как есть; extended attributes (xattr/ACL) могут обрезаться.
- Нет информации о том, какой файл от какого слоя — whiteout-файлы (`.wh.`) отсутствуют, так как слой уже применён.

**Формат OCI Archive (`skopeo copy`):**
- Соответствует спецификации OCI Image Layout (версия layout `1.0.0`; OCI Image Spec 1.1 — полная структура — в **[OCI Image Spec: структура образа изнутри](./oci_image_spec.md)**).
- Содержит `oci-layout` (версия схемы), `index.json` (manifest list для multi-arch) или `manifest.json` (одиночный образ), `blobs/sha256/<digest>`.
- Идентификаторы — content-addressable: каждый blob адресуется своим дайджестом.
- `skopeo inspect oci-archive:...` читает `index.json`/`manifest.json` без загрузки в демон, что критично для air-gapped диагностики.

**SRE-значение структуры:**
- В `docker save` удалённые секреты физически остаются в нижних слоях (whiteout скрывает, но не удаляет). Для аудита содержимого архива используйте `tar -tf` + grep на чувствительные имена файлов.
- В `docker export` writable layer сплющивается, но временные файлы и логи из running контейнера могут попасть в архив — проверяйте содержимое перед переносом.
- Размер `docker save` напрямую пропорционален сумме всех уникальных слоёв; `docker export` — размеру верхнего слоя. Планируйте объём носителя под максимальный из этих вариантов.

## Практические сценарии

### Сценарий 1: Перенос образа в изолированную среду (`save`/`load`)

Этот метод используется для доставки протестированных образов на серверы без доступа к интернету.

1. **Экспорт (на машине с интернетом)**:
   ```bash
   # Сохранение одного образа
   docker save -o nginx-stable.tar nginx:latest
   # → (файл nginx-stable.tar создаётся; stdout пуст при указании -o)

   # Проверка, что файл появился и имеет ожидаемый размер
   ls -lh nginx-stable.tar
   # → -rw------- 1 user user 142M Aug 21 13:00 nginx-stable.tar

   # Сохранение нескольких образов в один файл
   docker save -o app-stack.tar my-app:1.0 redis:7 alpine:latest
   # → (app-stack.tar содержит три образа и их общие слои без дублирования)
   ```

2. **Проверка целостности**:
   ```bash
   sha256sum nginx-stable.tar > nginx-stable.tar.sha256
   # → (файл контрольной суммы создан)
   cat nginx-stable.tar.sha256
   # → 3b8a...c4 nginx-stable.tar
   ```

3. **Импорт (на целевом сервере)**:
   ```bash
   # Проверка суммы перед импортом
   sha256sum -c nginx-stable.tar.sha256
   # → nginx-stable.tar: OK

   # Загрузка
   docker load -i nginx-stable.tar
   # → Loaded image: nginx:latest

   # Подтверждение, что образ загружен с историей слоёв
   docker images nginx
   # → REPOSITORY   TAG       IMAGE ID       CREATED        SIZE
   # → nginx        latest    021283c8eb95   2 weeks ago    142MB

   docker history nginx:latest
   # → IMAGE         CREATED       CREATED BY                  SIZE      COMMENT
   # → 021283c8eb95  2 weeks ago   /bin/sh -c #(nop) CMD [...]  0B
   # → <base> ...                                  (все слои образа на месте)
   ```

### Сценарий 2: Загрузка образов в кластер Kubernetes (containerd/CRI-O)

В современных средах Kubernetes Docker часто заменен на `containerd` или `CRI-O`.

**Для containerd (через nerdctl или ctr):**
```bash
# Рекомендуемый способ (nerdctl — Docker-совместимый CLI для containerd)
nerdctl -n k8s.io load -i my-app.tar
# → unpacking docker.io/library/my-app:latest...
# → Loaded image: docker.io/library/my-app:latest

nerdctl -n k8s.io images my-app
# → REPOSITORY                 TAG       IMAGE ID        CREATED        SIZE
# → docker.io/library/my-app   latest    abc123...        ...            120MB

# Низкоуровневый способ (ctr)
sudo ctr -n k8s.io images import my-app.tar
# → unpacking docker.io/library/my-app:latest (sha256:...)...done
```

**Для CRI-O (через podman):**
```bash
podman load -i my-app.tar
# → Loaded image(s): docker.io/library/my-app:latest

podman images my-app
# → REPOSITORY            TAG       IMAGE ID       CREATED        SIZE
# → docker.io/library/my-app  latest   def456...       ...            120MB
```
*Примечание: Использование пространства имен `k8s.io` обязательно для того, чтобы Kubernetes (kubelet) "увидел" загруженные образы. Если загрузить без `-n k8s.io`, команда `nerdctl images` покажет образ, но kubelet при попытке запуска Pod вернёт `ErrImageNeverPull` / `ImagePullBackOff`.*

### Сценарий 3: Создание образа из работающего контейнера (`export`/`import`)

Используется для создания минималистичного образа из контейнера, который был настроен вручную.

1. **Экспорт**:
   ```bash
   docker export my-running-container > snapshot.tar
   # → (snapshot.tar создан; содержит только дерево файлов, без слоёв)
   file snapshot.tar
   # → snapshot.tar: POSIX tar archive
   ```

2. **Импорт с восстановлением метаданных**:
   При импорте мы создаем новый образ. Так как метаданные (`CMD`, `WORKDIR`) были потеряны, их стоит указать через флаг `--change`.
   ```bash
   docker import \
     --change "ENV APP_HOME=/app" \
     --change "WORKDIR /app" \
     --change 'CMD ["./start.sh"]' \
     - my-custom-image:latest
   # → sha256:7f9a...   (возвращается ID нового образа)

   docker images my-custom-image
   # → REPOSITORY        TAG       IMAGE ID       CREATED         SIZE
   # → my-custom-image    latest    7f9a...          3 seconds ago   110MB
   ```
   Подтверждаем, что образ однослойный (вся история сборки потеряна при flatten):
   ```bash
   docker history my-custom-image:latest
   # → IMAGE      CREATED         CREATED BY      SIZE      COMMENT
   # → 7f9a...    4 seconds ago    /bin/sh -c #(nop)  CMD ["./start.sh"]   0B
   # → <missing>  4 seconds ago    import from snapshot.tar                 110MB
   ```
   Порядок флагов `--change` важен: они применяются к итоговому образу в том же порядке, что и инструкции Dockerfile, поэтому `ENV`/`WORKDIR` следует задавать до `CMD`.

### Сценарий 4: Использование Skopeo для синхронизации (Modern approach)

`skopeo` позволяет копировать образы между реестрами и архивами без участия Docker-демона (daemonless). Это безопаснее и легче на CI-раннерах.

```bash
# Копирование из реестра в локальный архив формата OCI
skopeo copy docker://registry.com/app:v1 oci-archive:app-v1.tar
# → Copying blob sha256:...
# → Copying config sha256:...
# → Writing manifest to image destination

# Проверка содержимого архива без загрузки (daemonless-инспект)
skopeo inspect oci-archive:app-v1.tar
# → {
# →     "Name": "app-v1",
# →     "Digest": "sha256:...",
# →     "DockerVersion": "...",
# →     "Labels": {...},
# →     "Layers": ["sha256:..."]
# → }

# Загрузка из OCI архива в локальный Docker-демон
skopeo copy oci-archive:app-v1.tar docker-daemon:app:v1
# → Copying blob sha256:...
# → Copying config sha256:...
# → Writing manifest to image destination

docker images app
# → REPOSITORY   TAG       IMAGE ID       CREATED        SIZE
# → app          v1        def456...        ...            95MB
```

### Сценарий 5: Перенос многоархитектурных образов (multi-arch)

`docker save` по умолчанию сохраняет образ **только для текущей архитектуры хоста**. Если целевой контур работает на другой платформе (например, переносим amd64-образ на arm64), нужно передавать весь manifest list.

```bash
# Сначала убедиться, что образ действительно multi-arch
docker buildx imagetools inspect nginx:latest
# → Name:      docker.io/library/nginx:latest
# → MediaType: application/vnd.docker.distribution.manifest.list.v2+json
# → Digest:    sha256:...
# →
# → Manifests:
# →   Platform: linux/amd64
# →   Platform: linux/arm64
# →   Platform: linux/arm/v7

# Перенос ВСЕХ архитектур: обязателен флаг --all
skopeo copy --all docker://nginx:latest oci-archive:nginx-multi.tar
# → Copying blob sha256:amd64...
# → Copying blob sha256:arm64...
# → Writing manifest list to image destination

# Альтернатива — собрать multi-arch локально и выгрузить в OCI-архив
docker buildx build --platform linux/amd64,linux/arm64 \
  -t nginx-multi:local --output type=oci,dest=nginx-multi.tar .
# → [+] Building 12.3s ...  # образ собран для обеих платформ и записан в nginx-multi.tar
```
Если забыть `--all` (или `--platform`), целевой хост на другой архитектуре при `docker run` вернёт `no matching manifest for linux/arm64/v8`.

### Сценарий 6: Диагностика архива без загрузки

Перед загрузкой полезно убедиться, что архив не повреждён и содержит ожидаемое.

```bash
# Содержимое tar-архива от docker save (Docker 25+: OCI Layout)
tar -tf nginx-stable.tar
# → oci-layout
# → index.json
# → manifest.json
# → repositories
# → blobs/sha256/...

# Проверка типа и целостности (нет ли обрыва архива)
tar -tvf nginx-stable.tar >/dev/null && echo "ARCHIVE_OK"
# → ARCHIVE_OK

# Дайджест уже загруженного образа — для сверки с источником
docker inspect --format '{{index .RepoDigests 0}}' app:v1
# → app@sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
```

### Сценарий 7: Подписанная и проверенная доставка (GPG)

Для доверенного sneakernet-переноса подпишите архив, чтобы исключить подмену носителя.

```bash
# Создание отсоединённой подписи
gpg --detach-sign --armor nginx-stable.tar
# → nginx-stable.tar.asc

# На целевом хосте: проверка подписи и контрольной суммы
gpg --verify nginx-stable.tar.asc nginx-stable.tar
# → Good signature from "Release <release@example.com>"
sha256sum -c nginx-stable.tar.sha256
# → nginx-stable.tar: OK
```
При несовпадении подписи `gpg` вернёт `BAD signature`, при повреждённом архиве `sha256sum -c` выведет `FAILED`.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `open ...: no such file or directory` при `load`/`import` | Неверный путь к архиву или архив не скопирован на хост | `ls -l <file>.tar`; проверьте, что файл доставлен на целевой хост |
| `unexpected EOF` / `archive/tar: invalid tar header` | Архив обрезан или повреждён при переносе | `sha256sum -c` против исходной суммы; `tar -tvf` покажет обрыв; повторите копию носителя |
| `no space left on device` | Закончилось место под архив или под распакованные слои | `df -h`; очищайте старые архивы и `docker image prune` |
| `no matching manifest for linux/<arch>` | Перенесли одну архитектуру вместо multi-arch | `docker buildx imagetools inspect`; переносите `skopeo copy --all` (Сценарий 5) |
| `ImagePullBackOff` / образ не виден kubelet после `ctr import` | Забыто пространство имён `-n k8s.io` | `ctr -n k8s.io images list \| grep <name>`; повторите импорт с `-n k8s.io` |
| Импортированный образ не запускается (`exec: "...": executable file not found`) | `docker import` потерял `ENTRYPOINT`/`CMD` | Добавьте `--change 'CMD [...]'` / `ENTRYPOINT`; проверьте `docker inspect .Config` |
| `failed to decrypt` при `load` | Образ подписан/зашифрован (cosign) | сначала расшифруйте через `cosign`/`skopeo copy` с ключом; обычный `load` не расшифровывает |
| `manifest unknown` / `404` при загрузке из архива в реестр | В архиве нет нужного тега/дайджеста | `skopeo inspect oci-archive:...`; исправьте имя назначения `docker-daemon:<name>:<tag>` |
| `ctr: image already exists` при повторном импорте | Образ с тем же ID уже в хранилище | `ctr -n k8s.io images rm <ref>` перед повторным импортом |
| Архив `docker save` превышает лимит `/tmp` на CI-раннере | Образ с большим базовым слоем; недостаточно места для распаковки | Используйтеpipe с `zstd -T0`; проверьте размер через `docker save ... | wc -c`; выносите `/var/lib/docker` на отдельный раздел |
| `docker load` проходит, но образ имеет тег `none` | В архиве нет `repositories` или тег не восстановился | `docker images` — проверьте теги; используйте `docker tag <id> <name>:<tag>` вручную |
| Образ после `docker load` не запускается на другой архитектуре | Сохранён образ только для архитектуры источника | `docker buildx imagetools inspect`; переносите `skopeo copy --all` или соберите multi-arch локально |
| Dайджест образа после `docker load` не совпадает с исходным | В архиве altered слои или повреждение при переносе | `docker inspect --format '{{index .RepoDigests 0}}'` до и после; перезагрузите из исходного архива |
| Накопление архивов `.tar` на хосте заполняет диск | `docker save` не удалён после успешной `load`; кэш BuildKit растёт | Автоматизируйте `rm` архивов после загрузки; `docker system prune -f` |

## Рекомендации и очистка

**Лучшие практики:**
- Всегда сверяйте `sha256sum` (и, при необходимости, `gpg`) на обоих концах переноса — это единственная защита от повреждения/подмены носителя.
- Для daemonless-переноса и CI предпочитайте `skopeo` — он не требует запущенного Docker-демона и не оставляет локальных слоёв.
- Сжимайте архивы (zstd быстрее gzip при сопоставимом размере), чтобы ускорить передачу и сэкономить место.
- При `docker import` восстанавливайте через `--change` минимально необходимый набор: `ENTRYPOINT`, `CMD`, `ENV`, `WORKDIR`, `EXPOSE`, `USER`.
- Для multi-arch всегда используйте `skopeo copy --all` или `buildx`; `docker save` сохраняет только текущую платформу.
- Не сохраняйте секреты в образе перед `docker save`: удалённые в следующем `RUN` файлы физически остаются в нижних слоях и видны через распаковку архива (см. **[Управление слоями](./layer_management.md)**, раздел о whiteout). Для секретов используйте `RUN --mount=type=secret` (BuildKit).

**SRE-паттерны для переноса и инвентаря образов:**
- В CI/CD pipelines используйте `docker save`/`load` или `skopeo copy` вместо прямого `docker pull` из реестра в air-gapped джобах — это даёт контроль над целостностью и RTO.
- Планируйте размер архива под Writetime: `docker save` одного образа с базовым alpine может быть 10–50 MB, а с базовым ubuntu — 100–300 MB; на CI-раннерах с ограниченным `/tmp` это критично.
- Для compliance-сред (PCI-DSS, ФЗ-152, внутренние политики) фиксируйте дайджест образа до и после переноса: `docker inspect --format '{{index .RepoDigests 0}}'` → sha256. Несоответствие означает подмену или повреждение.
- На Kubernetes-узлах с containerd: `docker save`/`load` работают через shim, но для прямого управления используйте `nerdctl -n k8s.io` или `ctr` — это исключает конфликты с kubelet.
- При аварийном восстановлении (DR) тестируйте `docker load` на «чистом» хосте периодически: битые архивы или изменившиеся форматы обнаруживаются только при реальной загрузке.
- Архивируйте не только образы, но и манифесты развёртываний (Helm values, Kustomize overlays) — перенос образа без конфигурации деплоя не даёт рабочего сервиса.

**Очистка окружения (revert / cleanup):**
```bash
# Удалить локальный архив после успешной загрузки
rm -f nginx-stable.tar nginx-stable.tar.sha256 nginx-stable.tar.asc

# Удалить импортированный образ, если он больше не нужен
docker rmi nginx:latest
# → Untagged: nginx:latest
# → Deleted: sha256:021283c8eb95...

# Очистка неиспользуемых образов и кэша BuildKit
docker image prune -a
docker buildx prune -f

# Очистка в containerd (через nerdctl)
nerdctl -n k8s.io rmi docker.io/library/my-app:latest
# или низкоуровнево:
sudo ctr -n k8s.io images rm docker.io/library/my-app:latest
```
Любую очистку можно откатить только повторной загрузкой из архива/реестра — удалённые образы и слои безвозвратны.

## Особые случаи и ограничения

- **`docker save` — только текущая архитектура.** Архив не содержит manifest list для других платформ; для multi-arch используйте `skopeo copy --all` (Сценарий 5).
- **`export` теряет всё, кроме файловой системы.** Исчезают `CMD`, `ENTRYPOINT`, `ENV`, `WORKDIR`, `EXPOSE`, `USER`, история слоёв и метаданные реестра. Восстанавливайте их через `--change` при `import`.
- **Whiteout и секреты.** В `docker save` удалённые в поздних слоях файлы физически остаются в нижних слоях (whiteout только скрывает их). Распаковка архива раскроет «удалённые» секреты — не кладите их в образ.
- **`import` без `--change`** даёт образ без точки входа и переменных окружения — контейнер не запустится корректно.
- **containerd image store (Docker 29.0+ fresh installs / containerd 2.3.x):** образы хранятся нативно в containerd; `docker save`/`load` прозрачны, но поведение `RepoDigests` и интеграция с Kubernetes меняются (см. «Примечания по версиям»).
- **Специальные файлы:** `docker export` переносит обычную ФС; симлинки копируются как ссылки, но device-файлы, пайпы и расширенные атрибуты (xattr/ACL) могут обрабатываться неполно — для спец-образов это ограничение.
- **Размер:** `docker save` включает ВСЕ базовые слои образа, даже если вам нужен только один верхний слой приложения. Для частичного переноса используйте `skopeo copy` выборочно.
- **CRI-O/Podman vs Docker:** `podman save`/`load` совместимы по формату OCI с Docker, но `podman load` не примет `--change` как `docker import` (для сборки используйте `podman build`/`Containerfile`).
- **Windows-контейнеры:** используют иной формат слоёв и изоляцию; архивы Windows-образов не переносимы на Linux-хост и наоборот.
- **Air-gapped audit trail:** при переносе через физический носитель фиксируйте в ITSM/ tickets: source host, дату, дайджест архива (`sha256sum`), ответственный. Это покрывает compliance-требования и упрощает расследование инцидентов.
- **RTO/RPO для image recovery:** `docker load` на 1 GB архиве занимает 30–120 секунд; `docker save` на production-хосте может создавать archive в течение минут. Планируйте DR-тесты с учётом этих цифр.
- **Build Cache и registry mirror:** `docker save` не включает Build Cache. При переносе для повторной сборки используйте `docker buildx build --cache-from` или registry mirror, а не архив образа.
- **Signing и admission control:** в Kubernetes с `cosign`/`Kyverno`/`Gatekeeper` импортированный через `docker load` образ должен быть повторно подписан или пройти admission, иначе Pod останется в `ImageInspectError`/`CreateContainerConfigError`.

## Примечания по версиям

- **Docker Engine 24.0+**: BuildKit используется по умолчанию; команды `save`/`load`/`export`/`import` стабильны и применимы ко всем современным версиям (27/28/29).
- **skopeo ≥ 1.14**: поддерживает `oci-archive:`, флаг `--all` для multi-arch, `skopeo inspect` для daemonless-проверки. Текущий стабильный релиз — 1.24.1 (проверено на 1.24.1).
- **nerdctl v2.x**: Docker-совместимый CLI для containerd; флаг `-n k8s.io` обязателен для загрузки образов в Kubernetes.
- **containerd image store (Docker 29.1 / containerd 2.0):** образы физически лежат в containerd; `docker save`/`skopeo` прозрачны, но `RepoDigests` формируется иначе, и дефолтное хранилище может отличаться от классического `/var/lib/docker`. Для SRE: при миграции на containerd image store проверьте скрипты, парсящие `/var/lib/docker`, и мониторинг диска.
- **podman v5.x–v6.x**: полностью совместимы по OCI-формату с Docker для `save`/`load`/`import`.

## Дополнительная информация

### Сжатие "на лету"

Для экономии места и ускорения передачи архивы следует сжимать.

- **Gzip (Классический способ)**:
  ```bash
  # Сохранение со сжатием
  docker save my-app:latest | gzip > my-app.tar.gz
  # → (my-app.tar.gz создан)

  # Загрузка из сжатого архива
  gunzip -c my-app.tar.gz | docker load
  # → Loaded image: my-app:latest
  ```

- **Zstd (Современный способ)**:
  Обеспечивает гораздо более высокую скорость сжатия и распаковки при аналогичном или лучшем размере.
  ```bash
  docker save my-app:latest | zstd > my-app.tar.zst
  # → (my-app.tar.zst создан)
  zstdcat my-app.tar.zst | docker load
  # → Loaded image: my-app:latest
  ```

**Производительность save/load:**

- **Без сжатия** — максимальная скорость; архив занимает больше места. Подходит для быстрого локального переноса по SSD.
- **gzip** — универсальная совместимость; сжатие медленнее zstd. Используйте `gzip -1` для скорости или `gzip -6` (дефолт) для баланса.
- **zstd** — рекомендуемый выбор: сжатие и распаковка в разы быстрее gzip при сопоставимом размере (для `docker push` zstd/fastest — дефолт, ~10x быстрее gzip). Уровни: `zstd -3` (быстро), `zstd -19` (максимальное сжатие, медленно).

**Чанкирование больших архивов** (для USB-носителей и файловых лимитов):
```bash
# Разбиение архива на чанки по 20 ГБ
docker save my-app:latest | zstd | split -b 20G - my-app.tar.zst.
# → my-app.tar.zst.aa, my-app.tar.zst.ab, ...

# Сборка и загрузка на целевом хосте
cat my-app.tar.zst.* | zstdcat | docker load
# → Loaded image: my-app:latest
```

**Частичное извлечение из архива `docker save`** (без полной распаковки):
```bash
# Только manifest.json
tar -xOf nginx-stable.tar manifest.json | jq .

# Список слоёв
tar -tf nginx-stable.tar | grep blobs/

# Извлечение одного слоя (в Docker 25+ слои — несжатые tar-блобы)
tar -xOf nginx-stable.tar blobs/sha256/<digest> | tar -tvf -
```

**Глубокий разбор `docker import --change`:**

Флаг `--change` (`-c`) применяет инструкции Dockerfile к создаваемому образу. Поддерживаются **только метаданные (configuration) инструкции** — `CMD`, `ENTRYPOINT`, `ENV`, `EXPOSE`, `HEALTHCHECK`, `LABEL`, `ONBUILD`, `STOPSIGNAL`, `USER`, `VOLUME`, `WORKDIR`. Инструкции `RUN`, `COPY`, `ADD` **не поддерживаются** — `import` не выполняет команды, только задаёт метаданные.

```bash
# Полный набор метаданных при импорте
docker import \
  --change "ENV APP_HOME=/app" \
  --change "WORKDIR /app" \
  --change "EXPOSE 8080" \
  --change "USER appuser" \
  --change 'ENTRYPOINT ["./start.sh"]' \
  --change 'CMD ["--port", "8080"]' \
  snapshot.tar my-image:latest

# Проверка восстановленных метаданных
docker inspect my-image:latest --format '{{.Config}}'

# Комментарий к импорту (отображается в истории)
docker import --message "Imported from prod snapshot" snapshot.tar my-image:latest
docker history my-image:latest
# → IMAGE   CREATED   CREATED BY   SIZE    COMMENT
# → abc123  ...                   110MB   Imported from prod snapshot
```

Порядок флагов `--change` важен (см. Сценарий 3): они применяются в том же порядке, что и инструкции в Dockerfile, поэтому `ENV`/`WORKDIR` следует задавать до `CMD`/`ENTRYPOINT`.

### Сравнение с Commit

Команда `docker commit` создает образ на основе изменений в контейнере, но, в отличие от `docker export`, она сохраняет всю историю слоев и метаданные исходного образа. `export` же полностью "сплющивает" (flattens) файловую систему.

Подробнее см. **[Создание образов через Docker Commit](../docker_commit.md)**.

### См. также

- **[Основы Docker-образов](./docker_images_basics.md)** — структура и слои.
- **[OCI Image Spec: структура образа изнутри](./oci_image_spec.md)** — манифест, config blob, media types, OCI Layout.
- **[Реестры Docker](../../docker_registries.md)** — хранение артефактов.
- **[Работа в изолированных средах (Air-gapped)](../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)** — стратегии доставки в закрытые контуры.
- **[Резервное копирование и восстановление](../docker_backup_restore.md)** — стратегии бэкапа томов, образов и данных контейнеров.
