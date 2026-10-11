# Безопасность Buildx builders

**Актуально для:** Buildx v0.37.x, BuildKit 0.33.x, Docker Engine 29.x. Использование buildx (драйверы, bake) — SSoT в [docker_buildx.md](../Dockerfile/docker_buildx.md). CVE BuildKit (CVE-2024/23651/23652/23653, CVE-2026/61711/15792/61712/75593/93318) — в [docker_security_interview_qa.md](./docker_security_interview_qa.md). Аттестации — в [image_signature_and_verification.md](./image_signature_and_verification.md).

## Определения

**Builder** — экземпляр BuildKit (демон сборки), выполняющий сборку. Создаётся через `docker buildx create`, выбирается через `docker buildx use`.

**Builder pool** — набор builders для распределения сборок (например, `docker-container` builders на разных хостах).

**Remote builder** — builder на другом хосте (драйвер `remote` по SSH) или в Kubernetes (драйвер `kubernetes`).

**Build cache** — кэш слоёв сборки: `inline` (в образе), `registry` (в реестре), `local` (на диске builder).

**Provenance** — SLSA-аттестация происхождения образа: кто, чем и из каких материалов собрал (см. [image_signature_and_verification.md](./image_signature_and_verification.md)).

## Базовые концепции

### Драйверы builders и границы доверия

| Драйвер | Где выполняется сборка | Изоляция | Аттестации |
| :--- | :--- | :--- | :--- |
| `docker` | Контейнеры через демон Docker | Нет изоляции кэша; сборка в контейнерах демона | Нет (ограниченно) |
| `docker-container` | Отдельный контейнер BuildKit | Изолированный кэш и окружение | Полные (SBOM, provenance) |
| `kubernetes` | Pod в Kubernetes | Изоляция K8s | Полные |
| `remote` | Удалённый хост по SSH | Зависит от хоста | Полные |

**Правило: builder — граница доверия.** Не используйте один builder для проектов с разным уровнем доверия: недоверенный Dockerfile на shared builder может отравить кэш или использовать entitlements доверенных сборок.

### Угрозы

1. **Недоверенный Dockerfile** — BuildKit выполняет инструкции с правами builder: CVE-2024-23651/23652/23653 (BuildKit ≤ 0.12.4) — race condition на cache-mount'ах, удаление файлов хоста через `RUN --mount`, эскалация через зловредный frontend. Фикс: BuildKit ≥ 0.12.5.
2. **Недоверенный frontend** — CVE-2026-61711 (CVSS 5.3, BuildKit ≤ 0.31.0, фикс 0.31.1+): кастомный frontend отключает Seccomp и AppArmor для build-контейнера, даже если `security.insecure` не разрешён. CVE-2026-15792 (BuildKit < 0.31.2, фикс 0.31.2): зловредный client/frontend вызывает panic buildkitd через некорректные параметры запроса. Фикс: только frontend от доверенных провайдеров.
3. **Cache poisoning** — CVE-2026-93318 (CVSS 7.5 High, BuildKit < 0.33.1, фикс 0.33.1+): зловредный образ рекламирует DiffIDs другого образа при отличном содержимом слоёв; BuildKit использует эти DiffIDs для идентификации кэша без валидации содержимого. В shared/persistent cache последующие сборки могут подменить базовый слой на зловредный, выполнить код, прочитать секреты или изменить артефакты.
4. **DoS через зловредный образ** — CVE-2026-61712 (CVSS 2.3, BuildKit ≤ 0.31.0, фикс 0.31.1+): unbounded group parsing при создании контейнера из зловредного образа → OOM-kill buildkitd.
5. **Утечка файлов через control API** — CVE-2026-75593 (CVSS 6.5 High, BuildKit < 0.31.2, фикс 0.31.2): аутентифицированный client с доступом к BuildKit control API может выйти за пределы state directory через path traversal в upload request. Результат: модификация/удаление файлов хоста.
6. **Утечка секретов через build args** — `--build-arg` значения видны в `docker history`, слоях и **в provenance `mode=max`**.
7. **Entitlements** — `--allow network.host`, `--allow security.insecure` расширяют привилегии сборки (сеть хоста, небезопасные операции).

### Provenance по умолчанию

- **`mode=min` генерируется по умолчанию** — но только для образов, push-имых в реестр (`--push`). Содержит: timestamps, frontend, материалы, ревизию исходников, платформу, reproducibility. Не содержит значений build args.
- **`mode=max`** — полная информация, включая **значения build args** (предупреждение Docker docs: не передавайте секреты через build args — используйте secret mounts).
- Отключение: `--provenance=false` или `BUILDX_NO_DEFAULT_ATTESTATIONS=1`.
- `BUILDX_DEFAULT_POLICY=1` — встроенная source policy: проверка подписанных тегов для Docker-managed образов (builder-образы, frontend'ы Dockerfile).

## Практические сценарии

### Сценарий 1: изоляция builders по trust boundary

```bash
# Отдельный builder на каждую границу доверия
docker buildx create --name trusted-builder --driver docker-container
docker buildx create --name untrusted-builder --driver docker-container

# Выбор builder
docker buildx use trusted-builder
docker buildx ls
# → NAME               DRIVER       ENDPOINT
# → trusted-builder    docker-container  unix:///var/run/docker.sock

# Изоляция кэша: отдельный cache-репозиторий на builder
docker buildx build --cache-to type=registry,ref=my-registry.com/trusted-cache:latest --push .
```

### Сценарий 2: cache security

```bash
# Registry cache — шарится только внутри trust boundary
docker buildx build \
  --cache-from type=registry,ref=my-registry.com/project-cache:latest \
  --cache-to type=registry,ref=my-registry.com/project-cache:latest,mode=max \
  --push .

# Недоверенный Dockerfile — без кэша
docker buildx build --no-cache --push untrusted/Dockerfile
```

**Правила:**
- inline-кэш (`type=inline`) — только для финальных образов, не для промежуточных стадий;
- registry-кэш не шарить между проектами с разным доверием;
- `--no-cache` для недоверенных Dockerfile;
- **CVE-2026-93318:** после обработки недоверенного образа — принудительная очистка кэша (`docker buildx prune --all --force`) или использование ephemeral builder, потому что зловредный образ может отравить shared cache через подмену DiffIDs и запустить код в последующих сборках.

### Сценарий 3: build secrets (не build args)

```bash
# Секрет передаётся как mount, не как ARG
docker buildx build --secret id=mysecret,src=./secret.txt .

# В Dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=mysecret \
  cat /run/secrets/mysecret && rm -f /run/secrets/mysecret
```

Секрет не попадает в слои образа, `docker history` и provenance-аттестацию. SSH-ключи — через `--ssh default` (см. [ssh-agent-rootless.md](./ssh-agent-rootless.md)).

### Сценарий 4: доверенные frontend'ы и доступ к control API

**CVE-2026-61711 / CVE-2026-15792:** кастомный frontend (`#syntax` в Dockerfile или `--frontend` в `buildctl`) может отключить Seccomp/AppArmor или вызвать panic buildkitd. Используйте только встроенный `docker/dockerfile:1` или frontend'ы из доверенных реестров.

**CVE-2026-75593:** BuildKit control API (порт 1624-1625 в `buildkitd` или Unix-сокет) доступен аутентифицированным клиентам. Ограничьте доступ к control API только доверенными CI/CD-воркерами и сервисными аккаунтами.

```bash
# Проверка frontend в Dockerfile
head -1 Dockerfile
# → syntax=docker/dockerfile:1

# Валидация версии BuildKit (должна быть ≥ 0.33.1 из-за CVE-2026-93318)
docker buildx version
# → github.com/docker/buildx v0.37.2
# → github.com/moby/buildkit v0.33.1

# buildkitd: слушает только localhost, TLS на control API
# /etc/buildkit/buildkitd.toml
[grpc]
  address = ["tcp://127.0.0.1:1625"]
  tls = true
  tlsCert = "/etc/buildkit/cert.pem"
  tlsKey = "/etc/buildkit/key.pem"
  tlsCA = "/etc/buildkit/ca.pem"
```

### Сценарий 5: проверка provenance образа

```bash
# Inspect provenance (SLSA) опубликованного образа
docker buildx imagetools inspect my-registry.com/app:v1 \
  --format '{{ json .Provenance.SLSA }}'
# → {"buildType":"https://mobyproject.org/buildkit@v1", ...}

# Проверка: образ собран из ожидаемого source revision
docker buildx imagetools inspect my-registry.com/app:v1 \
  --format '{{ json .Provenance.SLSA.predicate.buildConfig }}'
```

Для `mode=max` можно извлечь полный Dockerfile из аттестации — полезно для аудита «что именно собрано».

### Сценарий 6: remote builder через SSH

```bash
# Создание remote builder
docker buildx create --name remote-builder --driver remote ssh://builder-host

# Использование
docker buildx use remote-builder
docker buildx build --push .
```

**Безопасность:** аутентификация SSH-ключами (не паролями); ключ builder-хоста — отдельный, без доступа к production-реестрам на запись сверх необходимости; не передавать `/var/run/docker.sock` на builder-хост (это эквивалентно root — см. [api_authorization.md](./api_authorization.md)).

### Сценарий 7: ограничение entitlements

```bash
# Недоверенная сборка: без entitlements, без сети
docker buildx build --network=none --push .

# Entitlements — только для доверенных сборок
docker buildx build --allow network.host --allow security.insecure .
```

`--allow security.insecure` отключает часть защит BuildKit — применять только к доверенным Dockerfile.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Сборка падает с `security.insecure` | Entitlement не разрешён | `--allow security.insecure` — только для доверенных Dockerfile |
| Секрет виден в слоях образа | Передан через `--build-arg` | `--secret` + `RUN --mount=type=secret` |
| Provenance не прикреплена к образу | Образ не push-ился в реестр | Provenance по умолчанию прикрепляется только при `--push`; либо `--provenance=mode=max,inline-only=true` |
| Кэш отравлен / чужие слои в сборке | CVE-2026-93318: shared cache с недоверенным образом | Отдельный cache per project; `--no-cache` для недоверенных; `docker buildx prune --all --force` после недоверенных сборок |
| `mode=max` утекает секрет | Секрет в `--build-arg` | Рефакторинг на secret mounts; `mode=min` по умолчанию безопасен |
| buildkitd падает с OOM | CVE-2026-61712: зловредный образ с unbounded group parsing | Обновить BuildKit ≥ 0.33.1; только доверенные образы |
| Remote builder недоступен | SSH-ключ/хост недоступен | `ssh -T builder-host`; права ключа; `docker buildx inspect remote-builder --bootstrap` |
| Frontend отключил Seccomp/AppArmor | CVE-2026-61711: недоверенный frontend | Проверить `# syntax=` в Dockerfile; только `docker/dockerfile:1` или доверенные frontend'ы |
| Паника buildkitd при сборке | CVE-2026-15792: зловредный client/frontend | Обновить BuildKit ≥ 0.31.2; валидировать frontend |
| Файлы хоста изменены через build | CVE-2026-75593: path traversal в control API | Ограничить доступ к BuildKit control API; обновить BuildKit ≥ 0.31.2 |

## Лучшие практики

1. **Отдельный builder per trust boundary** — никогда не шарить builder между доверенными и недоверенными проектами.
2. **Секреты — через `--secret`**, не `--build-arg`: build args утекают в слои, history и provenance `mode=max`.
3. **Не шарить кэш** между проектами с разным доверием; `--no-cache` для недоверенных Dockerfile; `docker buildx prune --all --force` после недоверенных сборок (CVE-2026-93318).
4. **Патчить BuildKit** — CVE-2024-23651/23652/23653 исправлены в ≥ 0.12.5; CVE-2026-61711/61712/15792/75593 — в ≥ 0.31.2; CVE-2026-93318 — в ≥ 0.33.1.
5. **Проверять provenance** — `docker buildx imagetools inspect`; `mode=max` для аудита (без секретов в args).
6. **Ограничивать entitlements** — `--allow` только для доверенных сборок; `--network=none` по умолчанию.
7. **`BUILDX_DEFAULT_POLICY=1`** — проверка подписанных тегов Docker-managed образов и frontend'ов.
8. **Только доверенные frontend'ы** — CVE-2026-61711/15792: проверяйте `# syntax=` в Dockerfile; используйте `docker/dockerfile:1` или frontend'ы из доверенных реестров.
9. **Ограничить control API** — CVE-2026-75593: firewall по IP / TLS на `buildkitd` control API (1624-1625); доступ только CI/CD-воркерам.

## Дополнительная информация

**Связанные документы:**

- [Использование buildx](../Dockerfile/docker_buildx.md) — драйверы, bake, команды.
- [Подпись и аттестации образов](./image_signature_and_verification.md) — provenance, SBOM, Cosign.
- [Docker SBOM](./docker_sbom.md) — генерация SBOM при сборке.
- [Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md) — SLSA, build integrity.
- [ssh-agent в rootless Docker](./ssh-agent-rootless.md) — безопасная передача SSH в сборку.
- [Вопросы на собеседованиях](./docker_security_interview_qa.md) — CVE BuildKit.

**Инструменты:** `docker buildx` (create, use, inspect, imagetools), `BUILDX_DEFAULT_POLICY`, `BUILDX_NO_DEFAULT_ATTESTATIONS`.
