# Продвижение образов Docker в CI/CD

**Актуально для:** Docker 24.x–27.x, Kubernetes 1.29.x–1.32.x, CI/CD-раннеры на основе Linux

## Определения

- **Продвижение образа (Image Promotion)** — процесс переноса и квалификации одного и того же неизменяемого артефакта через цепочку окружений (например, `Dev` → `Staging` → `Production`) после успешного прохождения проверок (тестов, сканирований). На каждом шаге продвижения физические слои образа не пересобираются, а лишь изменяется его «адрес» в реестре (тег, дайджест или расположение).
- **Build Once, Deploy Anywhere** (Собери один раз, развертывай везде) — фундаментальный принцип CI/CD, согласно которому Docker-образ собирается только один раз в начале конвейера. Дальнейшее движение осуществляется через смену метаданных (тегов), физическое копирование манифестов или перенос дайджеста, но никогда через повторный запуск `docker build`. Это гарантирует, что в Production попадает бинарно тот же артефакт, который тестировался.
- **Quality Gates (Ворота качества)** — набор автоматизированных критериев (покрытие тестами, отсутствие критических уязвимостей CVE, успешный lint/SAST, наличие подписи), которые должен выполнить образ для получения права на продвижение в следующее окружение. При невыполнении хотя бы одного критерия пайплайн блокируется.
- **Иммутабельный дайджест (Content Digest)** — уникальный криптографический хеш (`sha256:...`) всего манифеста образа, вычисляемый по его содержимому (слоям и конфигурации). Дайджест является адресом по принципу content-addressable storage: один и тот же набор байт всегда даёт один и тот же хеш, поэтому ссылка по дайджесту гарантирует бинарную идентичность независимо от имени тега.
- **Подпись образа (Image Signing)** — наложение криптографической подписи на манифест образа (инструмент `cosign`, формат Sigstore/Notation), подтверждающей, что артефакт прошёл проверки и исходит из доверенного источника. В целевом кластере admission-контроллер (Kyverno, OPA/Gatekeeper) отвергает запуск неподписанных или подписанных чужим ключом образов.
- **Promotion Gate / Одобрение (Approval)** — явная или автоматическая точка принятия решения о переводе артефакта на следующий контур. Может быть ручной (кнопка «Approve» в GitLab/Jenkins) или автоматической (политика на основе прохождения Quality Gates и подписи).

## Основные концепции

### Проблема идемпотентности сборки

Повторная сборка образа для каждого окружения («сборка для прода», «сборка для staging») является критическим антипаттерном. Образ, собранный заново, почти никогда не бывает бинарно идентичным предыдущему, даже при неизменном `Dockerfile` и исходном коде. Факторы риска при пересборке:

- **Дрейф зависимостей:** базовые образы (например, `node:18-alpine`) могут обновиться в публичном реестре между сборками, даже без изменения тега.
- **Внешние пакеты:** `apt update`, `npm install` или `pip install` могут загрузить разные минорные/патч-версии пакетов, если они не зафиксированы жестко (lock-файлы `package-lock.json`, `poetry.lock`, `Gemfile.lock`).
- **Окружение сборки:** различия в версиях компиляторов, `buildkit`, библиотек и даже часовом поясе CI-раннера влияют на итоговый слой.
- **Недетерминированные метаданные слоёв:** отметки времени (`mtime`), порядок записи файлов, `ARG`, переданные во время сборки, и встроенные в бинарь пути/версии (`-X main.version`) меняют хеш слоя.
- **Порядок и параллелизм слоёв:** для multi-stage сборок незафиксированные инструкции копирования могут давать разный порядок слоёв.

**Результат:** образ, протестированный в QA, может бинарно отличаться от образа в Production, что сводит на нет ценность предварительного тестирования — баг, не проявившийся в Staging, может всплыть в Prod из-за отличающейся версии транзитивной зависимости.

Решение — собрать образ ровно один раз, зафиксировать его дайджест и двигать дальше только ссылки (теги/копии), опираясь на `Build Once, Deploy Anywhere`.

### Модели продвижения

1. **Внутри одного реестра (Promotion by Tagging):**
   - Образ остаётся в том же репозитории.
   - Продвижение осуществляется добавлением нового тега (например, `:sha-abcdef` → `:staging` → `:1.2.3`).
   - Подходит для небольших команд с единым доверенным реестром.
   - Недостаток: теги перезаписываемы (mutable), поэтому один и тот же тег `:staging` в разное время может указывать на разные образы — для гарантии идентичности всё равно используйте дайджест.

2. **Между разными реестрами (Promotion by Copy):**
   - Копирование из «недоверенного» реестра (Build/Dev) в «доверенный» (Production).
   - Обеспечивает строгую изоляцию: доступ к Production-реестру имеют только проверенные артефакты.
   - Реализуется инструментами `skopeo` или `crane`, которые работают напрямую с API реестра без локального Docker-демона.

3. **Использование неизменяемых дайджестов (Digest-based):**
   - Использование `sha256` вместо тегов в манифестах Kubernetes/Compose.
   - Гарантирует 100% бинарную идентичность независимо от того, был ли перезаписан тег в реестре.
   - Часто комбинируется с предыдущими моделями: копируется/тегируется образ, но в рантайме фиксируется по дайджесту.

Сравнение моделей:

| Модель | Изоляция реестров | Требует демона | Гарантия идентичности | Сложность |
| --- | --- | --- | --- | --- |
| Tagging (внутри реестра) | Нет | Да (`docker`) | Слабая (тег mutable) | Низкая |
| Copy (между реестрами) | Да | Нет (`skopeo`/`crane`) | Сильная (копия слоёв) | Средняя |
| Digest-based (фиксация) | Опц. | Нет (на стороне рантайма) | Максимальная (хеш) | Средняя |

**Как выбрать:** для старта достаточно Tagging; для регуляторных требований и строгого разделения сред — Copy между реестрами; для production-деплоя в Kubernetes — всегда фиксируйте образ по дайджесту поверх любой модели.

### Жизненный цикл артефакта в пайплайне

Типичная последовательность стадий продвижения (один образ, много проверок):

1. **Build** — сборка единственного образа, вывод его дайджеста в артефакт пайплайна (например, файл `image_digest.txt`).
2. **Test** — прогон unit/integration тестов внутри образа или против него (например, `docker run <image> pytest`).
3. **Scan (Quality Gate)** — сканирование на CVE (`trivy`, `grype`); блокировка при критических уязвимостях.
  4. **Sign (Quality Gate)** — подпись образа (`cosign sign`) после успешных проверок.
  5. **Promote** — копирование/тегирование в целевой реестр/репозиторий (`:staging`, `:production`).
  6. **Deploy** — развёртывание в Kubernetes/Compose с фиксацией по дайджесту.
  7. **Verify** — проверка, что в кластере крутится именно подписанный образ нужного дайджеста.

### Выбор стратегии именования тегов при продвижении

Чтобы продвижение было отслеживаемым, теги должны нести смысловую нагрузку и не перезаписываться бесконтрольно:

- **По SHA коммита** (`my-reg.com/app:sha-9f3a1c2`) — однозначно связывает образ с исходным кодом; основной «внутренний» тег для перемещения.
- **По SemVer** (`my-reg.com/app:1.2.3`, `:1.2`, `:1`, `:latest`) — стабильные «внешние» теги для релиза; перезаписываются осознанно при выпуске.
- **По окружению** (`my-reg.com/app:staging`, `:production`) — указатели на текущий релиз контура; mutable по определению, используются только как ярлыки поверх дайджеста.
- **По версии пайплайна/run-id** (`my-reg.com/app:build-42`) — удобно для отладки и отката к конкретному прогону CI.

Рекомендация: внутри пайплайна всегда оперируйте дайджестом и тегом `:sha-<commit>`, а «человекочитаемые» теги окружений/SemVer навешивайте как алиасы в самом конце продвижения. Подробнее — в разделе «Версионирование и тегирование образов» (см. См. также).

### Эфемерные CI-раннеры и безопасность хранения артефактов

В современных пайплайнах раннеры часто являются эфемерными (одноразовыми контейнерами или виртуальными машинами), что накладывает ограничения на хранение промежуточных данных:

- **Нет персистентного состояния:** любые данные, записанные на локальный диск раннера, теряются после завершения job. Поэтому дайджест и промежуточные артефакты должны передаваться между стадиями через артефакты пайплайна (GitHub Actions outputs, GitLab artifacts) или внешнее хранилище.
- **Очистка кеша Docker:** если пайплайн использует `docker pull`/`docker push`, после завершения job необходимо очищать кеш, чтобы исключить утечку данных между запусками:
  ```bash
  docker image prune -f --filter "until=1h"
  docker builder prune -f --filter "until=1h"
  ```
- **Минимизация прав:** на CI-раннере используйте `skopeo`/`crane` вместо монтирования Docker socket. Если Docker необходим, применяйтеrootless mode или ограниченный контекст (`docker context create` с правами только на целевой реестр).
- **Секреты в рантайме:** секреты (ключи подписи, credentials реестра) должны передаваться через защищённые переменные окружения пайплайна, а не фиксироваться в конфигурационных файлах или образах.

## Практические сценарии

### Предварительные требования

Перед выполнением сценариев убедитесь, что выполнены общие условия:

- **Доступ к реестру:** настроенный Docker credential helper или переменные окружения с логином/паролем (или токеном) для исходного и целевого реестров.
- **Аутентификация в CI:** секреты `REGISTRY_USER` / `REGISTRY_PASS` (или OIDC-токены для ECR/GAR) добавлены в переменные пайплайна как *masked* секреты.
- **Наличие исходного образа:** образ уже собран и запушен в реестр-источник; известен его тег или дайджест.
- **Установленные инструменты** (по сценариям): `docker` ≥ 24 (с buildkit), `skopeo` ≥ 1.14, `crane` (из пакета `go-containerregistry`), `cosign` ≥ 2.0, `trivy` ≥ 0.45, `jq`.
- **Сеть:** исходящий доступ CI-раннера к API реестров по HTTPS (443); для air-gapped — настроенный зеркальный реестр.

Проверка инструментов (пример, вывод зависит от версии):

```bash
docker --version           # → Docker version 24.0.7, build afdd53b
skopeo --version           # → skopeo version 1.23.0
crane version              # → v0.20.2
cosign version             # → 2.2.3
trivy --version            # → Version: 0.50.1
```

### Кэширование сборок в CI (BuildKit Cache)

Для ускорения повторных сборок в CI настройте удалённое кэширование BuildKit. Это особенно полезно при частых запусках пайплайна на одном коде — повторная сборка будет использовать кэш слоёв вместо полной перекачки.

**Настройка кэша в GitHub Actions:**

```yaml
- name: Build with cache
  run: |
    docker buildx build \
      --platform linux/amd64,linux/arm64 \
      -t my-reg.com/app:sha-${{ github.sha }} \
      --cache-from type=registry,ref=my-reg.com/app:buildcache \
      --cache-to type=registry,ref=my-reg.com/app:buildcache,mode=max \
      --push .
```

**Настройка кэша в GitLab CI:**

```yaml
build:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  variables:
    DOCKER_BUILDKIT: "1"
  script:
    - docker buildx build \
        --cache-from type=registry,ref=$CI_REGISTRY_IMAGE:buildcache \
        --cache-to type=registry,ref=$CI_REGISTRY_IMAGE:buildcache,mode=max \
        -t $CI_REGISTRY_IMAGE:sha-$CI_COMMIT_SHORT_SHA --push .
```

Параметры: `--cache-from` указывает, откуда импортировать кэш; `--cache-to` — куда экспортировать после сборки; `mode=max` сохраняет полный кэш (включая неиспользованные слои), `mode=min` — только использованные (меньше места в реестре).

### Сценарий 1: Продвижение через стандартный Docker CLI

Метод требует скачивания всех слоев на CI-агент (`docker pull`/`docker push`), что замедляет пайплайн и требует запущенного Docker-демона (или socket-mount в runner). Подходит для простых случаев и когда демон уже есть.

Шаги:

1. **Аутентификация** в целевом реестре (если он отличается от исходного):

   ```bash
   echo "$REGISTRY_PASS" | docker login my-reg.com -u "$REGISTRY_USER" --password-stdin
   # → Login Succeeded
   ```

2. **Загрузка проверенного образа** по точному тегу (или дайджесту):

   ```bash
   docker pull my-reg.com/app:sha-abcdef
   # → sha-abcdef: Pulling from app
   # → Digest: sha256:71676f4d...
   # → Status: Downloaded newer image for my-reg.com/app:sha-abcdef
   ```

3. **Добавление целевого тега** (алиаса окружения/релиза):

   ```bash
   docker tag my-reg.com/app:sha-abcdef my-reg.com/app:staging
   # без вывода при успехе
   ```

4. **Пуш в реестр:**

   ```bash
   docker push my-reg.com/app:staging
   # → staging: Pushing [========>] ...
   # → staging: digest: sha256:71676f4d... size: 1234
   ```

**Валидация:** образ доступен и имеет тот же дайджест, что и исходный:

```bash
docker inspect --format='{{index .RepoDigests 0}}' my-reg.com/app:staging
# → my-reg.com/app@sha256:71676f4d...
```

Если дайджест исходного и целевого тега совпадает — продвижение корректно.

### Сценарий 2: Продвижение без Docker-демона (Skopeo)

**Skopeo** работает напрямую с реестрами через их HTTP API. Это позволяет копировать образы между реестрами (например, из GitLab Registry в AWS ECR) без скачивания слоёв на локальный диск и без Docker-демона — идеально для легковесных CI-раннеров.

Версия: `skopeo` ≥ 1.14 (проверено на 1.23.0).

1. **Прямое копирование между реестрами** (тег → тег):

   ```bash
   skopeo copy \
     --src-creds "$DEV_USER:$DEV_PASS" \
     --dest-creds "$PROD_USER:$PROD_PASS" \
     docker://registry-dev.com/app:v1.2-beta \
     docker://registry-prod.com/app:v1.2
   # → Copying blob sha256:abcd...
   # → Copying config sha256:1234...
   # → Writing manifest to image destination
   ```

   Параметры: `--src-creds`/`--dest-creds` — учётные данные `user:pass` для исходного и целевого реестров (можно опустить, если настроен `~/.docker/config.json`); `docker://` — транспорт OCI/Docker-реестра.

2. **Копирование по дайджесту** (самый надёжный вариант — гарантирует нужный артефакт):

   ```bash
   skopeo copy \
     docker://registry-dev.com/app@sha256:71676f4d... \
     docker://registry-prod.com/app:v1.2
   ```

3. **Копирование всех архитектур (multi-arch индекс):**

   ```bash
   skopeo copy --all \
     docker://registry-dev.com/app:v1.2-beta \
     docker://registry-prod.com/app:v1.2
   # флаг --all копирует индекс манифеста и все дочерние образы
   ```

**Валидация:** убедитесь, что дайджест в целевом реестре совпадает с исходным:

```bash
skopeo inspect --format '{{.Digest}}' docker://registry-prod.com/app:v1.2
# → sha256:71676f4d...
```

### Сценарий 3: Работа с Multi-arch образами (Google Crane)

**Crane** — современный инструмент от Google (пакет `go-containerregistry`) для манипуляций с образами. Он эффективнее Skopeo при работе с индексами манифестов (multi-arch), так как копирует только JSON манифеста, если слои уже есть в целевом реестре, и умеет быстро перетегировать без полной перекачки.

Версия: `crane` v0.20+ (проверено на v0.20.2).

1. **Быстрое перетегирование (retag) внутри реестра:**

   ```bash
   crane tag my-reg.com/app:build-42 staging
   # без вывода при успехе; создаёт тег :staging, указывающий на тот же манифест
   ```

   Параметр `staging` — имя нового тега (без префикса реестра, т.к. реестр берётся из исходного образа).

2. **Копирование по дайджесту (между реестрами/тегами):**

   ```bash
   crane copy \
     my-reg.com/app@sha256:71676f4d... \
     my-reg.com/app:production
   # → (прогресс в stderr); при успехе — тихо
   ```

3. **Получение дайджеста образа** (полезно для фиксации в манифестах):

   ```bash
   crane digest my-reg.com/app:build-42
   # → sha256:71676f4d...
   ```

**Валидация:** проверьте, что тег указывает на ожидаемый дайджест:

```bash
crane validate --remote my-reg.com/app:production
# → (успех, если манифест корректен)
crane digest my-reg.com/app:production
# → sha256:71676f4d...
```

### Сценарий 4: Продвижение в GitOps (ArgoCD / Flux)

В GitOps-модели продвижение образа часто означает обновление тега (или дайджеста) в Git-репозитории с конфигурацией (Helm или Kustomize). Истина (source of truth) о том, какой образ в каком окружении, хранится в Git, а не в реестре.

**Вариант А. Автоматический Image Updater (ArgoCD Image Updater v1.x):** сервис опрашивает реестр и сам коммитит новый тег в Git при появлении версии, подходящей под маску (SemVer). Пример `ImageUpdater` CR:

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: staging-image-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/infra.git"
      branch: "main"
      writeBackTarget: "helmvalues:./apps/my-app/values.yaml"
  applicationRefs:
  - namePattern: "my-app-staging"
    images:
    - alias: "app"
      imageName: "my-reg.com/app:^1.2"
      commonUpdateSettings:
        updateStrategy: "semver"
        allowTags: "^v?[0-9]+\\.[0-9]+\\.[0-9]+$"
        ignoreTags: ["latest", "dev", "rc"]
```

После запуска Image Updater сам делает коммит вида `build(app): pin image my-reg.com/app to 1.2.3`, ArgoCD синхронизирует кластер, и в Staging попадает новый образ без ручного вмешательства.

> **Примечание:** В v0.x использовался `ImageUpdaterConfiguration` CRD и аннотации на Application. В v1.0+ это заменено на `ImageUpdater` CR с полями `applicationRefs`, `images`, `writeBackConfig`. См. [миграцию](../GitOps/ArgoCD/argocd_image_updater.md#миграция-с-v0x-аннотации-на-v1x-crd).

**Вариант Б. Ручное продвижение через CI (Kustomize):** обновляем дайджест в `kustomization.yaml` и коммитим:

```bash
# получаем дайджест собранного образа
DIGEST=$(crane digest my-reg.com/app:sha-abcdef)
# обновляем images в kustomization.yaml
kustomize edit set image app=my-reg.com/app@$DIGEST
git add kustomization.yaml && git commit -m "Promote app to $DIGEST" && git push
```

**Вариант В. Ручное продвижение через CI (Helm values):**

```bash
# В конце CI-пайплайна обновляем версию в Helm chart
sed -i "s/tag: .*/tag: v1.2.3/" ./deploy/values.yaml
git add ./deploy/values.yaml && git commit -m "Bump version to v1.2.3" && git push
```

**Валидация:** Git-коммит принят, ArgoCD/Flux показывает `Synced` и `Healthy`, а в кластере крутится ожидаемый образ:

```bash
kubectl get deploy app -o jsonpath='{.spec.template.spec.containers[0].image}'
# → my-reg.com/app@sha256:71676f4d...
```

### Сценарий 5: Продвижение по дайджесту в Kubernetes

Для production-деплоя зафиксируйте образ по дайджесту, чтобы исключить ситуацию, когда перезапись тега `:production` незаметно подменит артефакт.

1. **Получение дайджеста продвинутого образа:**

   ```bash
   DIGEST=$(crane digest my-reg.com/app:production)
   echo "$DIGEST"   # → sha256:71676f4d...
   ```

2. **Обновление Deployment по дайджесту** (без правки файлов, через `kubectl set image`):

   ```bash
   kubectl set image deploy/app app=my-reg.com/app@$DIGEST -n production
   # → deployment.apps/app image updated
   ```

3. **Фиксация в манифесте (пример в YAML):**

   ```yaml
   spec:
     containers:
       - name: app
         # тег + @digest: человекочитаемо и бинарно-детерминировано
         image: my-reg.com/app:1.2.3@sha256:71676f4d...
   ```

**Валидация:** убедитесь, что под использует именно этот дайджест:

```bash
kubectl get pods -n production -l app=app \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
# → docker-pullable://my-reg.com/app@sha256:71676f4d...
```

### Сценарий 6: Полный пример пайплайна с Quality Gates

Ниже — самодостаточный пример GitHub Actions, реализующий `Build Once, Deploy Anywhere`: сборка единственного образа, сканирование, подпись, продвижение через `crane` по окружениям и фиксация по дайджесту. Аналогичная логика применима в GitLab CI.

```yaml
name: image-promotion
on:
  push:
    branches: [main]

jobs:
  build-test-promote:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write   # для OIDC-пуша в GHCR (без логина/пароля)
    steps:
      - uses: actions/checkout@v4

      # 1. Сборка ОДИН раз (buildx), вывод дайджеста в файл
      - name: Build image
        id: build
        run: |
          docker buildx build \
            --platform linux/amd64,linux/arm64 \
            -t ghcr.io/${{ github.repository }}:sha-${{ github.sha }} \
            --push .
          crane digest ghcr.io/${{ github.repository }}:sha-${{ github.sha }} > digest.txt

      # 2. Quality Gate: сканирование на критические CVE
      - name: Scan (Trivy)
        run: |
          trivy image --exit-code 1 --severity CRITICAL \
            ghcr.io/${{ github.repository }}@$(cat digest.txt)

      # 3. Подпись образа (Cosign, ключ из секрета)
      - name: Sign image
        env:
          COSIGN_KEY: ${{ secrets.COSIGN_KEY }}
          COSIGN_PASSWORD: ${{ secrets.COSIGN_PASSWORD }}
        run: |
          cosign sign --key env://COSIGN_KEY \
            ghcr.io/${{ github.repository }}@$(cat digest.txt)

      # 4. Продвижение: тег staging (алиас поверх дайджеста)
      - name: Promote to staging
        run: |
          crane tag ghcr.io/${{ github.repository }}@$(cat digest.txt) staging
```

Тот же подход в GitLab CI (`gitlab-ci.yml`):

```yaml
stages: [build, test, promote]

build:
  stage: build
  script:
    - docker build -t $CI_REGISTRY_IMAGE:sha-$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:sha-$CI_COMMIT_SHORT_SHA

scan:
  stage: test
  script:
    - trivy image --exit-code 1 --severity CRITICAL $CI_REGISTRY_IMAGE:sha-$CI_COMMIT_SHORT_SHA

promote:
  stage: promote
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'   # Quality Gate: только main
  script:
    - crane tag $CI_REGISTRY_IMAGE:sha-$CI_COMMIT_SHORT_SHA production
```

**Валидация:** в реестре появился тег `:staging`/`:production` с тем же дайджестом, что и `:sha-...`, образ подписан, а скан не нашёл критических CVE (пайплайн дошёл до шага promote).

### Сценарий 7: Продвижение в Jenkins

Jenkins требует явного управления Docker-демоном (обычно через `docker` плагин или `docker-in-docker` в агентах). Ниже — пример Declarative Pipeline, использующий `crane` для promotion по дайджесту.

```groovy
pipeline {
    agent any
    environment {
        REGISTRY = 'my-reg.com'
        IMAGE = "${REGISTRY}/app"
        COSIGN_KEY = credentials('cosign-key')
    }
    stages {
        stage('Build') {
            steps {
                script {
                    docker.build("${IMAGE}:sha-${env.GIT_COMMIT}")
                    sh "docker push ${IMAGE}:sha-${env.GIT_COMMIT}"
                    env.IMAGE_DIGEST = sh(
                        script: "crane digest ${IMAGE}:sha-${env.GIT_COMMIT}",
                        returnStdout: true
                    ).trim()
                }
            }
        }
        stage('Test') {
            steps {
                sh "docker run --rm ${IMAGE}@${env.IMAGE_DIGEST} pytest"
            }
        }
        stage('Scan') {
            steps {
                sh "trivy image --exit-code 1 --severity CRITICAL ${IMAGE}@${env.IMAGE_DIGEST}"
            }
        }
        stage('Sign') {
            steps {
                withCredentials([string(credentialsId: 'cosign-password', variable: 'COSIGN_PASSWORD')]) {
                    sh "cosign sign --key env://COSIGN_KEY ${IMAGE}@${env.IMAGE_DIGEST}"
                }
            }
        }
        stage('Promote') {
            when {
                branch 'main'
            }
            steps {
                sh "crane tag ${IMAGE}@${env.IMAGE_DIGEST} production"
            }
        }
    }
    post {
        always {
            sh 'docker image prune -f'
            cleanWs()
        }
    }
}
```

**Валидация:** Jenkins-раннер выполнил все стадии, в реестре появился тег `:production`, привязанный к тому же дайджесту, что и `:sha-...`.

## Дополнительная информация

### Безопасность и проверка подписи

Перед продвижением образа в Production рекомендуется выполнять:

1. **Vulnerability Scanning (Quality Gate):** Проверка на критические CVE (`trivy`, `grype`). Пример с явным выходом:

   ```bash
   trivy image --severity CRITICAL,HIGH my-reg.com/app:staging
   # → app (debian 12.4)
   # → ====================
   # → Total: 2 (CRITICAL: 1, HIGH: 1)
   # → CRITICAL: CVE-2024-..., fixed in 1.2.4
   ```

   Флаг `--exit-code 1` превращает наличие уязвимостей в провал пайплайна (блокировка продвижения).

2. **Image Signing (Cosign):** Подпись образа после прохождения Quality Gates. В Prod-кластере контроллер (например, Kyverno) запретит запуск образа без подписи «QA-Approved».

   Подпись с локальным ключом:

   ```bash
   # Подпись образа перед продвижением
   cosign sign --key cosign.key my-reg.com/app:staging
   # → Enter password for private key: ****
   # → Successfully signed my-reg.com/app:staging@sha256:71676f4d...
   ```

   Верификация (на стороне приёма/в пайплайне):

   ```bash
   cosign verify --key cosign.pub my-reg.com/app:staging
   # → Verification successful. Signed by valid signer
   ```

   **Keyless-режим (Sigstore, без управления ключами):** подпись через Fulcio/Rekor с OIDC-идентичностью CI-раннера:

   ```bash
   cosign sign --yes my-reg.com/app:staging        # подпись
   cosign verify --certificate-identity "https://github.com/owner/repo/.github/workflows/ci.yml" \
                --certificate-oidc-issuer https://token.actions.githubusercontent.com \
                my-reg.com/app:staging              # верификация
   ```

### Политики очистки (Retention Policies)

Продвижение через уникальные теги (например, по SHA коммита) создаёт тысячи артефактов. Настройте политики в реестре (Harbor, Artifactory, GitLab Registry):

- **Keep last N:** Оставлять только 10 последних тегов для каждой ветки.
- **Delete untagged:** Автоматически удалять слои, на которые больше не ссылаются теги.
- **Garbage Collection (GC):** в Harbor периодический запуск GC физически освобождает место от «осиротевших» blob'ов. Пример запуска GC через API/CLI Harbor:

  ```bash
  # принудительный GC (требует прав администратора проекта)
  docker exec harbor-jobservice /bin/sh -c "harbor gc --all"
  # → GC completed. Reclaimed space: 1.2 GB
  ```

- **Tag retention в GitLab:** правила в `Settings → Repository → Tag rules` автоматически удаляют старые теги по регулярке/возрасту.

### Политики продвижения на уровне кластера (Policy-as-Code)

Помимо сканирования и подписи на этапе CI, продвижение можно дополнительно контролировать на стороне кластера с помощью **Admission Controllers**. Это обеспечивает defense-in-depth: даже если злоумышленник получит доступ к реестру и зальёт непроверенный образ, кластер отклонит его запуск.

**Kyverno — проверка подписи и источника при promotion:**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-promoted-images
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-signature
      match:
        any:
        - resources:
            kinds:
            - Pod
      verifyImages:
      - imageReferences:
        - "my-reg.com/production/*"
        attestations:
        - predicateType: cosign.sigstore.dev/attestation/v1
          attestor:
            entries:
            - keys:
                publicKeys: |-
                  -----BEGIN PUBLIC KEY-----
                  ...
                  -----END PUBLIC KEY-----
```

**OPA Gatekeeper — ограничение тегов в production-неймспейсе:**

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sBlockedTag
metadata:
  name: production-must-use-digest
spec:
  match:
    kinds:
    - apiGroups: [""]
      kinds: ["Pod"]
    namespaces: ["production"]
  parameters:
    allowedTags: ["production"]
    requireDigest: true
```

Эти политики гарантивают, что в production попадают только те образы, которые:
1. Прошли все Quality Gates в CI (подпись, скан, тесты).
2. Зафиксированы по дайджесту или доверенному тегу.

### Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Диагностика | Решение |
| --- | --- | --- | --- |
| `denied: requested access to the resource is denied` | Нет прав/логина в целевой реестр | `docker login` / проверьте `REGISTRY_PASS`; для ECR — `aws ecr get-login-password` | Корректно настройте credentials helper или OIDC-токен |
| `manifest unknown` / `404` при `crane copy` | Образ/тег не существует или указан неверный дайджест | `skopeo inspect docker://registry/app:tag` | Проверьте имя репозитория и дайджест; пересоберите, если нужно |
| `toomanyrequests` (docker.io) | Превышен лимит анонимных пуллов | Счётчик пуллов Docker Hub | Используйте авторизованный pull или зеркало (proxy cache) |
| Разные дайджесты у `:staging` и `:sha-...` | Образ пересобран вместо перетегирования | Сравните `crane digest` обоих тегов | Не запускайте `docker build` повторно; только tag/copy |
| `cosign verify` падает с `no matching signatures` | Образ не подписан или ключ не тот | `cosign triangulate image` + проверка публичного ключа | Подпишите тем же ключом/идентичностью, что и при верификации |
| Multi-arch скопирован не полностью | Забыт флаг `--all` в `skopeo`/`crane copy` | `skopeo inspect --raw` показывает один манифест вместо индекса | Повторите копию с `--all` |
| Тег `:production` указывает не на тот образ | Перезапись тега другим прогоном CI | `crane digest :production` ≠ ожидаемому | Фиксируйте деплой по `@sha256:...`, а не по тегу |
| `no space left on device` на CI-раннере | Кэш Docker или временные файлы заполнили диск | `docker system df` | Очистите кеш: `docker system prune -f --filter "until=1h"` |
| `crane: tag not found` | Исходный тег удален или не запушен | `crane ls my-reg.com/app` | Убедитесь, что исходный тег существует и доступен |
| `trivy: failed to download vulnerability DB` | Проблемы с сетью или устаревшая база Trivy | `trivy --skip-db-update image ...` | Обновите базу: `trivy image --download-db-only` или используйте кешированный mirror |
| `cosign: certificate expired` | Keyless-подпись через Fulcio/Rekor с истёкшим сертификатом | Проверьте срок действия сертификата в логах | Ротойтируйте ключи или используйте ключ-based подпись для критических образов |

### Лучшие практики и очистка окружения (Best Practices & Cleanup)

- **Один build на пайплайн.** Никогда не пересобирайте образ для разных контуров — только tag/copy/digest.
- **Фиксируйте деплой по дайджесту**, даже если продвигаете по тегу.
- **Храните дайджест как артефакт пайплайна** (файл/переменная), чтобы все стадии ссылались на один хеш.
- **Подписывайте и верифицируйте** образы; включайте проверку подписи на входе в кластер (Kyverno/OPA).
- **Используйте skopeo/crane без демона** на CI-раннерах — быстрее и безопаснее, чем монтировать Docker socket.
- **Настраивайте retention/GC**, иначе реестр переполнится уникальными SHA-тегами.
- **Очистка CI-раннера:** `skopeo`/`crane` не оставляют локальных слоёв; если использовали `docker pull`, очищайте кеш:
  ```bash
  docker image prune -f   # → Total reclaimed space: 1.1GB
  docker builder prune -f --filter "until=1h"
  ```
- **Откат (rollback):** продвижение обратимо перетегированием/копированием предыдущего дайджеста:
  ```bash
  crane tag my-reg.com/app@<previous_sha256> production
  kubectl rollout undo deploy/app -n production   # или переставить image по старому дайджесту
  ```
- **Canary / Blue-Green с фиксацией по дайджесту:** при стратегиях canary или blue-green используйте дайджест как источник истины для версии; тег `:canary`/`:blue` — лишь алиас. Это позволяет атомарно переключать трафик между точными версиями артефактов.
- **Изоляция секретов:** ключи подписи (`cosign.key`) и credentials реестра никогда не фиксируются в репозитории; используйте защищённые переменные CI и секрет-менеджеры (HashiCorp Vault, SOPS).

### Граничные случаи и ограничения (Edge Cases)

- **Перезаписываемость тегов (tag mutability):** тег не гарантирует идентичность — два последовательных `docker push :staging` укажут на разные образы. Всегда дублируйте дайджестом.
- **Multi-arch race condition:** при копии индекса между реестрами без `--all` может скопироваться только одна архитектура; в проде на другой платформе pull упадёт.
- **Дрейф базового образа в FROM:** даже собранный один раз образ «стареет» в реестре, если базовый `node:18-alpine` обновился; для воспроизводимости фиксируйте базу по дайджесту (`FROM node@sha256:...`).
- **Отзыв подписи:** при компрометации ключа нужно ротировать ключи и перевыпустить подписи; старые образы перестанут проходить верификацию, что может заблокировать легитимный откат — держите запасной (старый) ключ в политике верификации на переходный период.
- **Размер и квоты реестра:** тысячи SHA-тегов быстро исчерпывают квоту; без GC реестр «захлебнётся» даже при наличии retention по тегам (blobs очищаются только GC).
- **Cross-registry без общего доступа (air-gapped):** между полностью изолированными реестрами `skopeo copy` напрямую не пройдёт — используйте `skopeo copy` в `oci-archive:` с переносом носителя (sneakernet) или зеркалирование через Bastion.
- **Лимиты rate-limit публичных реестров:** массовое продвижение множества образов упирается в `toomanyrequests` Docker Hub — применяйте pull-through proxy cache (Harbor) или приватные зеркала.

## См. также

- **[Идентичность и неизменяемость артефактов](./branch_artifacts.md)** — глубокий разбор SHA-дайджестов и антипаттерна повторной сборки.
- **[Registry HTTP API v2](../../Docker_registries/registry_api_v2.md)** — протокол, поверх которого работают `skopeo`/`crane`: auth flow, эндпоинты, ошибки.
- **[Версионирование и тегирование образов](../../Docker_registries/image_versioning_and_tagging.md)** — стратегии выбора имён тегов (SemVer, SHA, окружения).
- **[Подпись и верификация Docker-образов](../../Docker_security/image_signature_and_verification.md)** — работа с Cosign, keyless и политики Kyverno.
