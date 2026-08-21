# Идентичность и неизменяемость артефактов Docker в CI/CD

## Определения

- **Артефакт сборки (Build Artifact)** — Docker-образ, созданный в процессе непрерывной интеграции (CI). Является материальным результатом сборки, имеющим фиксированное содержимое и уникальный идентификатор. Однажды собранный артефакт рассматривается как финальный «груз», который доставляется во все окружения без пересборки.
- **Неизменяемость (Immutability)** — принцип, согласно которому артефакт никогда не изменяется после создания. Любое исправление или обновление требует сборки нового образа с новым тегом/дайджестом. В реестрах неизменяемость обеспечивается запретом перезаписи тегов (immutable tags) и использованием дайджестов вместо тегов.
- **Воспроизводимость сборки (Reproducible Build)** — процесс, при котором из идентичных исходных данных (код, зависимости, инструменты, окружение) всегда получается побайтово идентичный артефакт (совпадающий SHA256 дайджест манифеста). Это гарантирует, что локальная, тестовая и продакшен-сборки эквивалентны.
- **Дайджест (Digest / Immutable Identifier)** — уникальный криптографический хэш содержимого образа (обычно SHA256), вычисляемый по его манифесту. Гарантирует, что образ не был подменён или изменён. Дайджест является адресом по принципу content-addressable storage (CAS): один и тот же набор байт всегда даёт один и тот же хэш независимо от имени тега и реестра.
- **Аттестация (Attestation)** — дополнительные метаданные (например, SBOM или Provenance), прикрепляемые к дайджесту образа через OCI 1.1 Referrers API, которые подтверждают его состав и условия сборки. Аттестации не меняют основной дайджест слоёв, поэтому динамические метаданные можно добавлять без нарушения детерминизма.
- **Build Once, Deploy Anywhere (Принцип единой сборки)** — фундаментальный подход CI/CD: образ собирается ровно один раз в начале конвейера, а дальше движется по контурам (Dev → Staging → Production) только через смену метаданных (тегов), копирование или фиксацию по дайджесту, но никогда через повторный `docker build`.

## Основные концепции

### Проблема идентичности образов между ветками и окружениями

Одной из критических ошибок в CI/CD является повторная сборка образа для разных контуров (например, сборка из `develop` для `staging` и затем повторная сборка из `main` для `production`).

**Проблема:** Даже при идентичном коде и `Dockerfile`, результат двух разных запусков `docker build` почти никогда не будет бинарно идентичным. Это нарушает принцип **Build Once, Deploy Anywhere** и может привести к ситуации, когда протестированный артефакт ведёт себя иначе в эксплуатации из-за незаметных различий в слоях.

Типичный неправильный поток (антипаттерн):

```text
Ветка develop ──► docker build ──► :staging   ──► тесты пройдены
Ветка main    ──► docker build ──► :production ──► (другой бинарь!) ──► баг в Prod
```

Правильный поток (единый артефакт на все контуры):

```text
Любая ветка ──► docker build (ОДИН раз) ──► :sha-<commit>@sha256:...
                                            │
                       ┌────────────────────┼─────────────────────┐
                  тесты                 тег :staging           тег :production
                  (по дайджесту)         (алиас)               (алиас)
```

Образ, прошедший проверки в одном контуре, продвигается в следующий без пересборки — гарантируется, что в Production попадает бинарно тот же артефакт, который тестировался.

### Факторы, нарушающие детерминизм сборки

| Фактор | Причина различий | Способ устранения |
| :--- | :--- | :--- |
| **Плавающие теги (Floating Tags)** | `FROM ubuntu:latest` сегодня и завтра может указывать на разные версии ОС. | Фиксация по мажорной версии или дайджесту (`@sha256:...`). |
| **Временные метки (Timestamps)** | Docker по умолчанию записывает время создания каждого слоя. | Использование `SOURCE_DATE_EPOCH` в BuildKit для фиксации времени. |
| **Недетерминированные пакеты** | `apt-get install -y nginx` установит актуальную версию, если она не зафиксирована. | Жёсткая фиксация версий пакетов (`nginx=1.24.0-1`) и lock-файлов (`package-lock.json`, `poetry.lock`). |
| **Порядок файлов** | Команда `COPY . .` может упаковывать файлы в разном порядке в зависимости от ФС. | BuildKit автоматически нормализует порядок файлов при сборке. |
| **Контекст сборки** | Лишние файлы (логи, кэш), не попавшие в `.dockerignore`. | Строгая настройка `.dockerignore` и использование multi-stage сборок. |
| **Метаданные (Labels)** | Изменение текста `LABEL` (даже даты сборки) меняет дайджест конфигурации образа. | Использование внешних аттестаций для динамических метаданных. |
| **Сетевые источники (Network sources)** | `pip install`/`npm install` без lock-файла тянут разные версии зависимостей в разное время. | Фиксация lock-файлов и зеркал; запрет `latest`/`@latest` в зависимостях. |

### Жизненный цикл неизменяемого артефакта

В корректном пайплайне с образом происходят следующие стадии, причём **физические слои собираются только один раз**:

1. **Build** — сборка единственного образа; дайджест манифеста сохраняется как артефакт пайплайна (переменная/файл `image_digest`).
2. **Test** — прогон тестов против образа, зафиксированного по дайджесту (без повторной сборки).
3. **Scan / Attest** — генерация SBOM, provenance, сканирование CVE; аттестации крепятся к тому же дайджесту.
4. **Promote** — навешивание тегов окружений (`staging`, `production`) или копирование в доверенный реестр поверх дайджеста.
5. **Deploy** — развёртывание с фиксацией по дайджесту; возврат (rollback) осуществляется переключением тега на предыдущий дайджест.

## Практические сценарии

### Предварительные требования

Перед выполнением сценариев убедитесь, что:

- **Docker Engine ≥ 23.0** (BuildKit — движок по умолчанию) либо явно включен `DOCKER_BUILDKIT=1` для старых версий.
- **Docker Buildx ≥ 0.14** (поддержка встроенных аттестаций `--attest` и линтинга `# check`).
- **BuildKit ≥ v1.8** (детерминированные метки времени, LLB-граф, кэш).
- **jq ≥ 1.6** — для извлечения дайджеста из JSON-метаданных сборки.
- **git** — для получения `SOURCE_DATE_EPOCH` и хэша коммита.
- **Доступ к реестру** с правами `push` (для сценариев с публикацией) и настроенным credential helper.
- **Реестр с поддержкой OCI 1.1 Referrers API** (Harbor 2.11+, GitHub Container Registry, GitLab 16.6+) — для нативного хранения SBOM/provenance.

Проверка версий (вывод зависит от установленной версии):

```bash
docker version --format '{{.Server.Version}}'   # → 26.1.3
docker buildx version                            # → github.com/docker/buildx v0.14.1
jq --version                                      # → jq-1.7.1
```

### Сценарий 1: Создание детерминированного Docker-образа

Для обеспечения 100% идентичности артефакта необходимо минимизировать влияние внешних факторов на каждом этапе.

**Шаг 1: Подготовка Dockerfile для воспроизводимости**

```dockerfile
# 1. Фиксация базового образа по дайджесту (рекомендуется для Production)
FROM ubuntu:24.04@sha256:72297848457d5d37d126263012759e6d3e707bc4ef415303ee5b40cf3957cc98

# 2. Передача метаданных сборки через ARG (только статичные данные)
ARG GIT_COMMIT
ARG APP_VERSION=unknown

# 3. Фиксация версий системных пакетов
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl=8.5.0-2ubuntu10.1 \
  && rm -rf /var/lib/apt/lists/*
# → Пакеты зафиксированы, кэш очищен

WORKDIR /app
COPY . .

# 4. Внедрение стандартизированных метаданных (OCI Labels)
LABEL \
    org.opencontainers.image.source="https://github.com/my-org/my-app" \
    org.opencontainers.image.revision=$GIT_COMMIT \
    org.opencontainers.image.version=$APP_VERSION
```

> **Почему фиксация по дайджесту:** тег `ubuntu:24.04` технически может быть переназначен владельцем репозитория; `@sha256:...` гарантирует бинарную неизменность базового слоя. Получить дайджест текущего тега: `docker buildx imagetools inspect ubuntu:24.04 --format '{{.Digest}}'`.

**Шаг 2: Использование BuildKit для воспроизводимых меток времени**

Современный движок **BuildKit** позволяет фиксировать время создания слоёв через переменную `SOURCE_DATE_EPOCH`, что исключает влияние текущего времени на дайджест.

```bash
# Использование фиксированной метки времени (время последнего коммита)
export SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)

docker buildx build \
  --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
  --build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
  -t my-registry.com/my-app:1.0.0 \
  --metadata-file build-metadata.json \
  --push .
# → извлечение дайджеста из метаданных сборки
DIGEST=$(jq -r '."containerimage.digest"' build-metadata.json)
echo "$DIGEST"
# → sha256:a1b2c3d4...
```

*Параметры:* `--build-arg` передаёт фиксированные значения в `ARG` Dockerfile; `--metadata-file` сохраняет JSON с дайджестом (`containerimage.digest`) и конфигом (`containerimage.configdigest`); `--push` публикует образ сразу после сборки.

*Использование `--attest` (Buildx ≥ 0.14 / BuildKit ≥ v1.8) позволяет вынести информацию о сборке (Provenance) и составе (SBOM) в отдельные метаданные, не меняя основной дайджест слоёв при повторных запусках с теми же исходниками:*

```bash
docker buildx build \
  --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
  --build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
  --attest type=sbom \
  --attest type=provenance,mode=max \
  -t my-registry.com/my-app:1.0.0 \
  --metadata-file build-metadata.json \
  --push .
# → аттестации прикреплены к тому же дайджесту через OCI 1.1 Referrers
```

> **Версионно:** нативные аттестации доступны в Docker v27+ / BuildKit v1.8+; реестры отображают их нативно при поддержке OCI 1.1 Referrers API (Harbor 2.11+, GHCR). Для `provenance` `mode=max` включает полную историю сборки, `mode=min` — минимальный набор (безопаснее для чувствительных окружений).

**Валидация:** образ собран и опубликован, дайджест зафиксирован:

```bash
docker buildx imagetools inspect my-registry.com/my-app:1.0.0 --format '{{.Manifest.Digest}}'
# → sha256:a1b2c3d4...
```

### Сценарий 2: Проверка идентичности через дайджесты

Чтобы убедиться, что образ в `dev` и `prod` идентичен, сравнивайте не теги, а **RepoDigests** (или манифест-дайджест). Теги мутабельны и могут указывать на разные образы в разное время.

Через Docker CLI (локально загруженный образ):

```bash
docker inspect --format='{{index .RepoDigests 0}}' my-app:1.0.0
# → my-registry.com/my-app@sha256:a1b2c3d4...
```

Через `crane` (без Docker-демона, версия v0.20+):

```bash
crane digest my-registry.com/my-app:dev
# → sha256:a1b2c3d4...
crane digest my-registry.com/my-app:production
# → sha256:a1b2c3d4...
# если дайджесты совпадают — артефакты бинарно идентичны
```

Через `skopeo` (межреестровое сравнение, версия ≥ 1.14):

```bash
skopeo inspect --format '{{.Digest}}' docker://registry-dev.com/my-app:1.0.0
# → sha256:a1b2c3d4...
skopeo inspect --format '{{.Digest}}' docker://registry-prod.com/my-app:1.0.0
# → sha256:a1b2c3d4...
```

**Валидация:** скрипт-сравнение для CI:

```bash
D1=$(crane digest my-registry.com/my-app:dev)
D2=$(crane digest my-registry.com/my-app:production)
[ "$D1" = "$D2" ] && echo "IDENTICAL" || echo "MISMATCH"
# → IDENTICAL
```

### Сценарий 3: Захват дайджеста как артефакта пайплайна и повторное использование

Ключевая практика «Build Once»: дайджест, полученный при сборке, передаётся между стадиями пайплайна, а тесты/продвижение обращаются к образу **строго по дайджесту** — повторная `docker build` в последующих стадиях запрещена.

Пример GitHub Actions:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      digest: ${{ steps.meta.outputs.digest }}
    steps:
      - uses: actions/checkout@v4
      - name: Build (once)
        id: meta
        run: |
          docker buildx build \
            --build-arg GIT_COMMIT=${{ github.sha }} \
            --build-arg SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) \
            -t my-registry.com/my-app:sha-${{ github.sha }} \
            --metadata-file meta.json --push .
          echo "digest=$(jq -r '."containerimage.digest"' meta.json)" >> "$GITHUB_OUTPUT"
  test:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - run: |
          # используем ТОТ ЖЕ дайджест — никакой повторной сборки
          docker pull my-registry.com/my-app@${{ needs.build.outputs.digest }}
          docker run --rm my-registry.com/my-app@${{ needs.build.outputs.digest }} pytest
  promote:
    needs: [build, test]
    runs-on: ubuntu-latest
    steps:
      - run: |
          crane tag my-registry.com/my-app@${{ needs.build.outputs.digest }} production
```

Пример GitLab CI (`gitlab-ci.yml`):

```yaml
build:
  stage: build
  script:
    - docker buildx build -t $CI_REGISTRY_IMAGE:sha-$CI_COMMIT_SHORT_SHA \
        --build-arg GIT_COMMIT=$CI_COMMIT_SHA \
        --build-arg SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) \
        --metadata-file meta.json --push .
    - echo "IMAGE_DIGEST=$(jq -r '."containerimage.digest"' meta.json)" >> build.env
  artifacts:
    reports:
      dotenv: build.env   # дайджест доступен следующим стадиям

test:
  stage: test
  needs: [build]
  script:
    - docker pull $CI_REGISTRY_IMAGE@$IMAGE_DIGEST
    - docker run --rm $CI_REGISTRY_IMAGE@$IMAGE_DIGEST pytest

promote:
  stage: deploy
  needs: [build, test]
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  script:
    - crane tag $CI_REGISTRY_IMAGE@$IMAGE_DIGEST production
```

**Валидация:** стадия `promote` навешивает тег `:production` поверх того же дайджеста, что и `:sha-...`:

```bash
crane digest $CI_REGISTRY_IMAGE:production
# → равен $IMAGE_DIGEST
```

### Сценарий 4: Самопроверка воспроизводимости (build twice, compare)

Чтобы гарантировать, что сборка детерминирована, соберите образ дважды из одних исходников и сравните дайджесты. Несовпадение указывает на недетерминированный фактор (см. таблицу выше).

```bash
# сборка дважды из одних исходников
docker buildx build -t my-app:run1 --metadata-file m1.json --push .
docker buildx build -t my-app:run2 --metadata-file m2.json --push .

D1=$(jq -r '."containerimage.digest"' m1.json)
D2=$(jq -r '."containerimage.digest"' m2.json)
[ "$D1" = "$D2" ] && echo "REPRODUCIBLE" || echo "NON-DETERMINISTIC"
# → REPRODUCIBLE
```

**Валидация:** вывод `REPRODUCIBLE` подтверждает побайтовую идентичность; при `NON-DETERMINISTIC` — последовательно исключите факторы (плавающие теги, время, lock-файлы).

### Сценарий 5: Извлечение и проверка SBOM / Provenance (аттестации)

Аттестации (SBOM, Provenance) прикрепляются к дайджесту образа и позволяют аудировать состав и происхождение без пересборки и сканирования работающего контейнера.

Верификация Provenance (SLSA) через `cosign` (≥ 2.0):

```bash
cosign verify-attestation my-registry.com/my-app@$DIGEST \
  --type slsaprovenance \
  --certificate-identity "https://github.com/my-org/my-app/.github/workflows/ci.yml" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
# → Verification successful!
```

Извлечение SBOM из аттестации (формат CycloneDX):

```bash
cosign verify-attestation my-registry.com/my-app@$DIGEST \
  --type cyclonedx \
  --output-file sbom.cdx.json
# → SBOM сохранён в sbom.cdx.json
```

Инспекция через `buildx imagetools` (показывает прикреплённые аттестации):

```bash
docker buildx imagetools inspect my-registry.com/my-app@$DIGEST --raw | jq '.manifests'
# → список referrers (sbom, provenance) с их дайджестами
```

**Валидация:** команда `verify-attestation` возвращает `Verification successful!`, а в `sbom.cdx.json` присутствуют компоненты образа. Если реестр не поддерживает Referrers API, аттестации не отобразятся — используйте `cosign attach` или обновите реестр.

### Сценарий 6: Multi-arch воспроизводимая сборка

Для кросс-платформенных образов детерминизм достигается фиксацией **индексного** дайджеста (manifest list), который охватывает все архитектуры.

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --build-arg SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) \
  -t my-registry.com/my-app:1.0.0 \
  --metadata-file meta.json --push .

# индексный дайджест фиксирует ВСЕ платформы сразу
crane digest my-registry.com/my-app:1.0.0
# → sha256:<index-digest>
```

**Валидация:** фиксируйте в манифестах Kubernetes/Compose именно индексный дайджест, чтобы на любой платформе подтягивалась корректная архитектура:

```bash
kubectl set image deploy/my-app my-app=my-registry.com/my-app@$(crane digest my-registry.com/my-app:1.0.0) -n production
# → deployment.apps/my-app image updated
```

## Дополнительная информация

### Иерархия идентификации артефактов

1.  **RepoDigest (SHA256):** Наивысший приоритет. Гарантирует идентичность манифеста и всех слоёв в конкретном реестре. Формат: `my-registry.com/my-app@sha256:...`.
2.  **Image ID:** Идентификатор конфигурации (config digest). Может совпадать для разных тегов, если слои идентичны, но зависит от метаданных конфигурации (env, labels).
3.  **Tags (v1.2.3):** Мутабельные ссылки. Удобны для людей, но должны использоваться только как указатели на проверенные дайджесты.

> **Тонкость:** в выводе `docker images` поле `IMAGE ID` соответствует `config digest`, тогда как `RepoDigest` — это `manifest digest`. Они различаются: один и тот же бинарный образ (config) под разными тегами даст одинаковый `IMAGE ID`, но `RepoDigest` включает имя реестра и является адресом для pull/push.

### Рекомендации по эксплуатации

- **Принцип одного раза:** Никогда не запускайте `docker build` для продвижения кода в Production. Используйте `docker tag` / `crane tag` / `skopeo copy` или специализированные инструменты.
- **Фиксация по дайджесту:** Всегда развёртывайте и тестируйте образ по `@sha256:...`, даже если продвигаете по тегу.
- **Immutable Tags:** Включите запрет перезаписи тегов в реестре (Harbor: Project → Configuration → Prevent image from being overwritten by a re-push), чтобы защитить опубликованные артефакты.
- **Анализ SBOM:** Автоматизируйте генерацию SBOM при сборке для упрощения аудита безопасности без необходимости сканирования работающих контейнеров.
- **Целостность цепочки поставок:** Для обеспечения доверия используйте фреймворк **[SLSA](../../../Security/Supply_Chain_Security/overview.md)** и подписывайте образы (см. См. также).

### Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Дайджесты `:dev` и `:production` различаются при «одинаковом» коде | Образ пересобран повторно вместо переиспользования | Сравните `crane digest` обоих тегов | Уберите `docker build` из поздних стадий; передавайте дайджест из стадии сборки |
| `SOURCE_DATE_EPOCH` проигнорирован | Используется legacy builder, а не BuildKit | `docker version` → проверьте BuildKit | Включите `DOCKER_BUILDKIT=1` / обновите Docker ≥ 23.0 |
| Дайджест меняется после добавления `LABEL` | Метки меняют `config digest` | `docker inspect` → `Config` | Вынесите динамические метаданные в аттестации (`--attest`) |
| Аттестации не видны в реестре | Реестр не поддерживает OCI 1.1 Referrers API | `docker buildx imagetools inspect --raw` | Обновите реестр (Harbor ≥ 2.11) или используйте `cosign attach` |
| Multi-arch pull падает на одной архитектуре | Скопирована только одна платформа без `--all` | `skopeo inspect --raw` → один манифест | Копируйте индекс целиком (`skopeo copy --all` / `crane copy` индекса) |
| Сборка «воспроизводимая» всё равно даёт разные дайджесты | Плавающий базовый тег или нет lock-файла | Проверьте `FROM` и `npm install` без lock | Зафиксируйте базу по `@sha256:` и lock-файлы зависимостей |
| `jq` выдаёт `null` для `containerimage.digest` | Неверный ключ / сборка без `--metadata-file` | Проверьте структуру `meta.json` | Используйте `--metadata-file` и ключ `."containerimage.digest"` |

### Лучшие практики и очистка окружения (Best Practices & Cleanup)

- **Один build на пайплайн.** Физические слои собираются ровно один раз; всё остальное — теги, копии, фиксация по дайджесту.
- **Фиксируйте базу по дайджесту** (`FROM image@sha256:...`), чтобы дрейф базового образа не ломал воспроизводимость.
- **Храните дайджест как артефакт пайплайна** (переменная/dotenv/json), чтобы все стадии ссылались на один хэш.
- **Аттестуйте SBOM и Provenance** при каждой сборке; верифицируйте перед деплоем.
- **Включайте immutable tags** в реестре, чтобы исключить случайную перезапись опубликованных артефактов.
- **Очистка CI-агента:** BuildKit и `crane`/`skopeo` не оставляют локальных слоёв при `--push`/`copy`, но если использовали `docker pull`, очищайте кэш:

  ```bash
  docker buildx prune -f      # → Total: 1.2 GB reclaimable
  docker image prune -f       # → Total reclaimed space: 800MB
  ```

- **Откат (rollback):** продвижение обратимо переключением тега на предыдущий дайджест без пересборки:

  ```bash
  crane tag my-registry.com/my-app@<previous_sha256> production
  kubectl rollout undo deploy/my-app -n production
  ```

### Граничные случаи и ограничения (Edge Cases)

- **Config Digest ≠ Manifest Digest:** `IMAGE ID` (config) и `RepoDigest` (manifest) — разные хэши; при сравнении идентичности всегда используйте manifest-дайджест (`crane digest`/`RepoDigests`).
- **Дрейф базового образа:** даже собранный один раз образ «стареет», если `FROM ubuntu:24.04` обновился в реестре; для долгосрочной воспроизводимости фиксируйте базу по `@sha256:`.
- **Репозиторий в имени дайджеста:** `RepoDigest` включает hostname реестра (`registry/a@sha256:`), тогда как чистый manifest-digest реестр-независим. При копировании через `skopeo`/`crane` хэш сохраняется — образ бинарно идентичен в разных реестрах.
- **Provenance `mode=max` и секреты:** расширенная история сборки может включать пути и `build-args`; для чувствительных окружений используйте `mode=min`.
- **Кэш не нарушает детерминизм:** BuildKit-кэш только ускоряет сборку; при одинаковых входах выход детерминирован. Недетерминизм даёт не кэш, а внешние факторы из таблицы выше.
- **OCI 1.1 Referrers и старые реестры:** до Harbor 2.11/GHCR аттестации хранятся «по тегу» (отдельный образ), что усложняет очистку; учитывайте при настройке retention.
- **Multi-arch:** индексный дайджест фиксирует все платформы; фиксация отдельной платформы в проде на другой архитектуре приведёт к ошибке pull — всегда пинить индекс.

## См. также

- **[Продвижение образов в CI/CD](./promotion_cicd.md)** — стратегии перемещения неизменяемых артефактов по контурам.
- **[Версионирование и тегирование образов](../../Docker_registries/image_versioning_and_tagging.md)** — выбор стратегии именования и фиксация по дайджесту.
- **[Подписание и верификация образов](../../Docker_security/image_signature_and_verification.md)** — обеспечение целостности через Cosign.
