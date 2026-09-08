# Продвинутые сценарии Helm: OCI, мутации и адаптивные чарты

> Область применения: on-premise и изолированные (air-gapped) Kubernetes-кластеры, GitOps-пайплайны на собственной инфраструктуре. Тематика облачных managed-сервисов и AI/LLM-сценариев намеренно исключена.

## Определения

**Продвинутые сценарии Helm** — это совокупность практических методик промышленной эксплуатации чартового менеджера в Kubernetes, направленных на решение задач DevOps/SRE/sysadmin:

- **Безопасность цепочки поставок (Supply Chain Security):** защита от подмены артефактов на этапах сборка → публикация → деплой через подпись чартов и их дигестов.
- **Сложная мутация сторонних чартов:** наложение организационных политик безопасности и конфигурации на чарты, чей исходный код недоступен или не должен модифицироваться напрямую (vendor lock-in, multi-tenant).
- **Адаптивные (универсальные) чарты:** шаблоны, которые автоматически подстраиваются под целевой кластер (версию API, наличие CRD, версию Helm, присутствие операторов), исключая необходимость поддержки множества форков под разные окружения.

Актуальный базовый релиз на момент обновления: **Helm 4.2.x** (Helm v4.0.0 выпущен 12 ноября 2025 года, текущая стабильная ветвь — 4.2.4). Helm v3 продолжает получать баг-фиксы до 8 июля 2026 года и security-фиксы до 11 ноября 2026 года, после чего официально завершает жизненный цикл (EOL). В данном документе синтаксис по умолчанию приводится для Helm v4; отличия от v3 явно отмечаются.

---

## Основные концепции

### 1. Доверительная дистрибуция (OCI + Sigstore/Cosign)

С Helm v3.8 OCI-реестры стали штатным механизмом хранения чартов наравне с классическими HTTP-репозиториями (`index.yaml`), а в v4 — рекомендуемым и фактически единственным «родным» способом. В отличие от облачных registry, on-premise OCI-реестры (Harbor, CNCF Distribution, Zot, Sonatype Nexus Repository) разворачиваются полностью внутри периметра и не требуют интернет-доступа, что критично для финансов, госсектора, промышленности и режимных объектов.

В 2026 году использование OCI-реестров без подписи артефактов считается техническим долгом. Продвинутый подход включает не только хранение, но и криптографическую фиксацию чарта через Sigstore/Cosign:

- **Helm OCI-artifact** — сам чарт как OCI-манифест с дигестом `sha256:...`.
- **Cosign signature** — отдельный OCI-артефакт (артефакт-приложение по спецификации `application/vnd.dev.sigstore.cosign`), связанный с основным чартом по идентификатору (аналог OCI referrers).
- **Rekor transparency log** — публичный (или частный) журнал аудита, фиксирующий факт подписи; при использовании keyless-режима подпись привязывается к identity провайдера (OIDC).

Подпись гарантирует: а) неизменность артефакта между этапами (целостность), б) подтверждённое авторство (аутентичность), в) возможность автоматической блокировки деплоя неподписанных/недоверенных чартов через admission-контроллер (Kyverno, OPA Gatekeeper, Connaisseur) или политику GitOps-контроллера (Flux v2 `OCIRepository`/`HelmRelease`, Argo CD `cosign`-интеграция).

### 2. Декларативная мутация (Post-rendering)

Механизм `--post-renderer` позволяет передавать сгенерированные Helm манифесты внешней утилите перед отправкой в API-сервер. Это критично для внедрения сквозных политик безопасности в чарты, исходный код которых недоступен или нежелателен для форка (например, публичные `ingress-nginx`, `cert-manager`, `kube-prometheus-stack`).

**Важно для Helm v4:** начиная с v4.0.0 произошёл **breaking change** — пост-рендереры реализованы только как **плагины типа `postrenderer/v1`** (см. [HIP-0026](https://github.com/helm/community/blob/main/hips/hip-0026.md)). Передача исполняемого файла напрямую через `--post-renderer ./patcher.sh` больше **не поддерживается**. Любой ранее работавший shell-скрипт или Kustomize-обёртка должна быть оформлена как плагин (`plugin.yaml` с типом `postrenderer/v1` и `apiVersion: helm.sh/v1`). Helm v3 продолжает принимать прямые пути к исполняемым файлам; мигрирующие пользователи должны либо оставаться на v3 для этого сценария, либо переоформить инструмент в виде плагина.

Типичные задачи, решаемые через пост-рендеринг:

- Инъекция Sidecar-контейнеров безопасности (Falco, Aqua, Vector, OTel-collector) в существующие Deployment-ы без форка чарта.
- Добавление стандартных меток/аннотаций для мониторинга, логирования, биллинга.
- Принудительное ужесточение `securityContext` (readOnlyRootFilesystem, runAsNonRoot, seccompProfile).
- Добавление `PodDisruptionBudget`, `NetworkPolicy`, `ServiceAccount` ссылок.
- Инъекция initContainer-ов для ожидания зависимостей (wait-for-db, Istio-прокси).

Ограничение: пост-рендерер работает только с уже отрендеренным YAML; он **не видит состояние кластера** и не может принимать решения на основе реального состава ресурсов. Для динамических мутаций нужен admission webhook (Kyverno mutate, OPA Gatekeeper) или operator.

### 3. Изолированная расширяемость (WASM-плагины, HIP-0026)

В Helm v4 плагинная система полностью переработана. Наряду с классическими CLI-плагинами (наследие v3, по-прежнему поддерживаются) появился опциональный **WebAssembly-runtime** на базе [Extism](https://extism.io/), реализующий три типа плагинов с первой версии:

| Тип | Назначение |
|-----|-----------|
| `cli/v1` | Дополнительные подкоманды Helm (аналог v3-плагинов). |
| `getter/v1` | Новые протоколы загрузки чартов и зависимостей. |
| `postrenderer/v1` | Пост-рендереры (см. п. 2). |

Архитектура позволяет добавлять новые типы плагинов (например, `templater/v1`, `valuesprocessor/v1`) без модификации ядра Helm — этим Helm v4 решает историческое ограничение v3, где любое расширение поведения требовало форка.

Преимущества WASM-плагинов для корпоративного sysadmin:

- **Sandbox:** плагин не имеет прямого доступа к файловой системе хоста и произвольным системным вызовам — он работает через разрешённый host-контекст, описанный в манифесте плагина.
- **Кроссплатформенность:** один бинарный артефакт `.wasm` исполняется одинаково на Linux/amd64, Linux/arm64, macOS, Windows — не нужны Python, Bash, Go в окружениях CI.
- **Распространение через OCI:** плагины упаковываются тем же `helm plugin package` и публикуются в OCI-реестр рядом с чартами; подпись Cosign распространяется и на них.

### 4. Адаптивность на уровне движка (`.Capabilities`)

Создание «умных» чартов, которые самостоятельно определяют возможности целевого кластера (версию Kubernetes, наличие API-групп, доступность CRD) и адаптируют состав манифестов без изменения `values.yaml`. Это снижает количество форков под разные окружения (dev/staging/prod, on-prem/edge, миграция 1.25 → 1.30+) и упрощает поддержку в долгоживущих продуктах.

Ключевые свойства объекта `.Capabilities`:

- `.Capabilities.KubeVersion.Version` — семантическая версия API-сервера (например, `v1.30.3`).
- `.Capabilities.APIVersions.Has "<group>/<version>/<resource>"` — проверка наличия конкретного API.
- `.Capabilities.HelmVersion.Version` — версия клиента Helm (полезно для условной активации v4-фич).

Адаптивность применяется для:

- Переключения между устаревшими и актуальными API (`networking.k8s.io/v1beta1` → `v1`, `policy/v1beta1` → `v1`, `batch/v1beta1` → `v1`).
- Условного создания CRD-зависимых ресурсов (Cert-Manager `Certificate`, Istio `VirtualService`, Argo CD `Application`, SealedSecrets и т.п.) только если соответствующие CRD установлены в кластере.
- Выбора между встроенными провайдерами (LoadBalancer Service, Ingress, Gateway API HTTPRoute) в зависимости от установленного контроллера.

### 5. Иммутабельность через дигесты (OCI install by digest)

С Helm v3.8 и усилением в v4 поддерживается установка/обновление чарта **по дигесту** `oci://registry.example.com/charts/app@sha256:abc123...` вместо семантического тега `:1.2.3`. Helm автоматически отклоняет установку, если вычисленный дигест не совпадает с указанным, что даёт криптографическую гарантию неизменности артефакта между пайплайном сборки и продакшен-кластером. Это критично для аудита, регуляторных требований (ФСТЭК, SOC 2) и соответствия SLSA L3.

---

## Практические сценарии

### 1. Безопасная дистрибуция в OCI с подписью (Cosign)

Сценарий обеспечивает защиту от подмены чарта в реестре и от roll-back на уязвимую версию. Реализуется в три этапа: упаковка и публикация, подпись, верификация перед деплой.

**Предусловия:**

- Локальный OCI-реестр (Harbor 2.10+, CNCF Distribution 3.x, Zot 0.1+, Sonatype Nexus 3.65+) с поддержкой OCI referrers и проектом `charts`.
- Утилиты: `helm` ≥ 4.0.0, `cosign` ≥ 2.4.0, опционально `oras` ≥ 1.2.0 для инспекции.
- Учетные данные реестра в `~/.docker/config.json` (или через `helm registry login`).

**Шаг 1: Упаковка и публикация**

```bash
# Логин в реестр (Helm v4: только домен, без протокола/пути)
helm registry login registry.example.com -u svc-deployer

# Упаковка чарта (создаёт my-chart-1.2.3.tgz)
helm package ./my-chart

# Публикация в OCI
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts
# → Pushed: registry.example.com/charts/my-chart:1.2.3
```

**Шаг 2: Подпись артефакта через Cosign (key-based)**

```bash
# Генерация ключевой пары (один раз, держать в секрете)
cosign generate-key-pair
# → cosign.key, cosign.pub

# Подпись OCI-артефакта чарта
cosign sign --key cosign.key registry.example.com/charts/my-chart:1.2.3
# → Pushing signature to: registry.example.com/charts/my-chart:sha256-<digest>.sig
```

> **Примечание по тегам:** Helm при пуше преобразует `+` в `_` (например, `1.2.3+build.5` → `1.2.3_build.5`) из-за ограничений OCI. Cosign **не** выполняет такое преобразование — при подписи/верификации версий с `+` используйте преобразованный тег с подчёркиванием.

**Шаг 3: Подпись по дигесту (рекомендуется для аудита)**

```bash
DIGEST=$(helm show chart oci://registry.example.com/charts/my-chart --version 1.2.3 \
  | awk '/^appVersion:/{print $2}')

# Получаем реальный sha256 чарта в реестре
oras manifest fetch resolve registry.example.com/charts/my-chart:1.2.3 \
  | jq -r '.digest'   # в более ранних версиях oras: использовать resolve-подкоманду
```

**Шаг 4: Верификация перед деплоем**

В CI/CD пайплайне или через admission controller выполняется верификация. Команда возвращает exit code 0 только при валидной подписи:

```bash
# Верификация по публичному ключу
cosign verify --key cosign.pub registry.example.com/charts/my-chart:1.2.3
# → Verification for registry.example.com/charts/my-chart:1.2.3 --
# → The following checks were performed on each of these signatures:
# →   - The cosign claims were validated
# →   - The signatures were verified against the specified public key
# → {"critical":{"identity":{"docker-reference":"registry.example.com/charts/my-chart"},...}

# Установка по дигесту (иммутабельно)
DIGEST="sha256:$(oras manifest fetch resolve \
  registry.example.com/charts/my-chart:1.2.3 | jq -r '.digest' | cut -d: -f2)"

helm install my-app oci://registry.example.com/charts/my-chart@${DIGEST} \
  --version 1.2.3
```

**Альтернатива: keyless-подпись через Sigstore + OIDC**

Для CI, где невозможно хранить долгоживущий ключ, используется keyless-режим:

```bash
export COSIGN_EXPERIMENTAL=1
cosign sign registry.example.com/charts/my-chart:1.2.3
# → подпись привязывается к OIDC-токену ($ACTIONS_ID_TOKEN_REQUEST_TOKEN в GitHub Actions,
#   OIDC_ID_TOKEN в GitLab CI), а факт подписи фиксируется в Rekor transparency log
```

### 2. Глубокая мутация через Post-rendering

#### 2.1. Helm v3 — оставлено для обратной совместимости

В Helm v3 пост-рендерер — это произвольный исполняемый файл, получающий манифесты через stdin и возвращающий модифицированный YAML в stdout. Классический пример — обёртка над Kustomize:

**Скрипт-обёртка `patcher.sh` (v3-only):**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Читаем YAML от Helm
cat > all.yaml

# Применяем kustomize и выводим в stdout
kustomize build .
rc=$?

# Очистка временного файла
rm -f all.yaml

exit $rc
```

**Запуск (v3):**

```bash
chmod +x ./patcher.sh
helm upgrade --install web oci://registry.example.com/charts/web-chart \
  --version 2.4.1 \
  --post-renderer ./patcher.sh
```

**Минимальный `kustomization.yaml`:**

```yaml
resources:
  - all.yaml   # helm пишет сюда отрендеренные манифесты

patches:
  - target:
      kind: Deployment
      name: web
    patch: |-
      - op: add
        path: /spec/template/spec/containers/-
        value:
          name: security-proxy
          image: registry.internal/security-proxy:1.8.2
          env:
            - name: LOG_LEVEL
              value: info
```

> В Helm v3 параметр `--post-renderer` может быть указан **множественно** (`--post-renderer ./a.sh --post-renderer ./b.sh`); выходные манифесты передаются по цепочке. Это поведение сохранено как legacy в v4 через плагины.

#### 2.2. Helm v4 — пост-рендерер как плагин

В v4 тот же сценарий реализуется через плагин типа `postrenderer/v1`. Структура проекта:

```
kustomize-postrenderer/
├── plugin.yaml
└── kustomize-postrenderer.sh
```

**`plugin.yaml`:**

```yaml
apiVersion: helm.sh/v1
type: postrenderer/v1
name: kustomize
runtime: binary   # или "wasm" для WASM-реализации
version: 0.1.0
description: |
  Post-renderer, применяющий Kustomize-патчи к отрендеренным Helm манифестам.
config:
  - name: kustomizationDir
    type: string
    description: Путь к директории с kustomization.yaml
    required: true
commands:
  - name: run
    description: Применить Kustomize и вернуть модифицированные манифесты
```

**`kustomize-postrenderer.sh`:**

```bash
#!/usr/bin/env bash
set -euo pipefail

KUZM_DIR="${HELM_PLUGIN_CONFIG_KUSTOMIZATIONDIR:-./kustomize}"

cat > "${KUZM_DIR}/all.yaml"
kustomize build "${KUZM_DIR}"
rm -f "${KUZM_DIR}/all.yaml"
```

**Установка и запуск:**

```bash
# Установка плагина из локального каталога
helm plugin install ./kustomize-postrenderer

# Использование
helm upgrade --install web oci://registry.example.com/charts/web-chart \
  --version 2.4.1 \
  --post-renderer kustomize
```

В Helm v4 параметр `--post-renderer` принимает **имя плагина** (например, `kustomize`), а не путь к исполняемому файлу. Это меняет всю цепочку CI-скриптов: вместо копирования бинарника на раннер требуется установить плагин (через `helm plugin install oci://...` или маунт локального каталога).

### 3. Создание универсальных адаптивных чартов

Сценарий для организаций с множеством кластеров разных версий и составов (например, миграция с Kubernetes 1.25 на 1.30+, частичный переход на Gateway API, пилотные Istio-кластеры).

#### 3.1. Динамический выбор API для Ingress и PDB

**Шаблон `templates/ingress.yaml`:**

```yaml
{{- /* Проверка доступности Ingress API */ -}}
{{- $ingressApi := "networking.k8s.io/v1" -}}
{{- if not (.Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress") -}}
  {{- $ingressApi = "networking.k8s.io/v1beta1" -}}
{{- end -}}

{{- /* Проверка Gateway API (предпочтительный путь в новых кластерах) */ -}}
{{- $hasGatewayAPI := .Capabilities.APIVersions.Has "gateway.networking.k8s.io/v1/HTTPRoute" -}}

{{- /* Проверка наличия Istio */ -}}
{{- $hasIstio := .Capabilities.APIVersions.Has "networking.istio.io/v1beta1/VirtualService" -}}

{{- if $hasGatewayAPI }}
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: {{ include "mychart.fullname" . }}
  labels:
    {{- include "mychart.labels" . | nindent 4 }}
spec:
  parentRefs:
    - name: {{ .Values.gateway.name | default "default" }}
      namespace: {{ .Values.gateway.namespace | default "gateway-system" }}
  hostnames:
    - {{ .Values.app.host | required "app.host required" }}
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: {{ include "mychart.fullname" . }}
          port: {{ .Values.service.port }}
{{- else }}
---
apiVersion: {{ $ingressApi }}
kind: Ingress
metadata:
  name: {{ include "mychart.fullname" . }}
  annotations:
    {{- if $hasIstio }}
    kubernetes.io/ingress.class: istio
    {{- end }}
spec:
  rules:
    - host: {{ .Values.app.host }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "mychart.fullname" . }}
                port:
                  number: {{ .Values.service.port }}
{{- end }}
```

**Шаблон `templates/pdb.yaml`:**

```yaml
{{- if .Capabilities.APIVersions.Has "policy/v1/PodDisruptionBudget" }}
apiVersion: policy/v1
{{- else }}
apiVersion: policy/v1beta1
{{- end }}
kind: PodDisruptionBudget
metadata:
  name: {{ include "mychart.fullname" . }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable | default 1 }}
  selector:
    matchLabels:
      {{- include "mychart.selectorLabels" . | nindent 6 }}
```

#### 3.2. Условное создание ресурсов по наличию CRD

```yaml
{{- /* Создаём Certificate только если установлен cert-manager */ -}}
{{- if .Capabilities.APIVersions.Has "cert-manager.io/v1/Certificate" }}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: {{ include "mychart.fullname" . }}
spec:
  secretName: {{ include "mychart.fullname" . }}-tls
  dnsNames:
    - {{ .Values.app.host }}
  issuerRef:
    name: {{ .Values.cert.issuerName | default "letsencrypt-prod" }}
    kind: ClusterIssuer
{{- end }}
```

#### 3.3. Адаптация по версии Helm-клиента

```yaml
{{- /* В Helm v4 доступен новый OCI-install-by-digest workflow — можно безопасно использовать его */ -}}
{{- if semverCompare ">=4.0.0" .Capabilities.HelmVersion.Version }}
{{- /* предполагаем, что CI публикует манифест с дигестом рядом */ -}}
{{- end }}
```

> **Лучшая практика:** всегда проверяйте `.Capabilities.APIVersions.Has` **вместо** сравнения версий ядра через `semverCompare`. API-группы могут быть включены/выключены, установлены через CRD или deprecation-флагами независимо от версии Kubernetes. Подробный справочник — в [Проверке версий API и возможностей](../templating/scenarios/api_versions.md).

### 4. Работа с WASM-плагинами (Helm v4)

В v4 плагины становятся частью OCI-экосистемы: распространяются, подписываются и устанавливаются через те же реестры, что и чарты.

**Структура WASM-плагина:**

```
policy-checker/
├── plugin.yaml
└── policy.wasm        # скомпилированный WASM-модуль
```

**`plugin.yaml`:**

```yaml
apiVersion: helm.sh/v1
type: cli/v1              # или postrenderer/v1
name: policy-checker
runtime: wasm
version: 1.0.0
description: Проверка манифестов на соответствие внутренним политикам безопасности.
wasm:
  filename: policy.wasm
  allowedHosts:
    - "files"
  config:
    - name: policyPath
      type: string
      required: true
```

**Публикация и подпись:**

```bash
# Упаковка плагина в OCI-артефакт
helm plugin package ./policy-checker
# → policy-checker-1.0.0.tgz

# Публикация
helm plugin push policy-checker-1.0.0.tgz oci://registry.example.com/plugins

# Подпись (аналогично чартам)
cosign sign --key cosign.key registry.example.com/plugins/policy-checker:1.0.0
```

**Установка и использование:**

```bash
helm plugin install oci://registry.example.com/plugins/policy-checker --version 1.0.0

helm upgrade --install my-app ./chart --verify-policies
```

> **Миграция с v3-плагинов:** классические CLI-плагины на базе shell-скриптов (`plugin.yaml` с `apiVersion: v1` и командой в `bin/<name>`) **продолжают работать** в v4 без изменений. WASM-runtime — опциональный путь; переход оправдан при требованиях к sandbox-изоляции или кросс-платформенной сборке без интерпретаторов.

### 5. Установка по дигесту в GitOps-конвейере

Связка OCI + дигест + Cosign — канонический паттерн для on-premise GitOps.

**Шаг 1: Сборка → подпись → получение дигеста (CI-джоба)**

```bash
set -euo pipefail

helm package ./charts/my-chart
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts
DIGEST="sha256:$(oras manifest fetch resolve \
  oci://registry.example.com/charts/my-chart:1.2.3 | jq -r '.digest' | cut -d: -f2)"

cosign sign --key cosign.key registry.example.com/charts/my-chart:1.2.3

# Экспорт дигеста для следующего шага
echo "CHART_DIGEST=${DIGEST}" >> "${GITHUB_ENV:-/dev/stdout}"
```

**Шаг 2: Верификация → деплой (CD-джоба)**

```bash
set -euo pipefail

cosign verify --key cosign.pub \
  registry.example.com/charts/my-chart:1.2.3

helm upgrade --install my-app \
  oci://registry.example.com/charts/my-chart@${CHART_DIGEST} \
  --version 1.2.3 \
  --wait \
  --history-max 10
```

Такой пайплайн соответствует уровню **SLSA Build L3** для артефактов чартов: подписанный источник, воспроизводимая сборка, защита от roll-back на старую уязвимую версию.

---

## Диагностика и устранение неисправностей

| Проблема | Причина | Решение |
|----------|---------|---------|
| `cosign verify` падает с `no matching signatures` | Чарт перезалит в реестр с тем же тегом, но другим содержимым; подпись старого дигеста | Использовать установку по дигесту; включить immutable-теги в Harbor (`Tag Immutability Policy`) |
| `--post-renderer` в v4 выдаёт `unknown flag` | Передан путь к исполняемому файлу вместо имени плагина | Оформить пост-рендерер как плагин `postrenderer/v1` (см. п. 2.2); для обратной совместимости оставаться на v3.18 |
| `helm registry login` в v4 ругается на `oci://` в аргументе | В v4 принимается только домен | `helm registry login registry.example.com -u user` без протокола |
| Адаптивный шаблон падает при `--dry-run=client` без кластера | `.Capabilities` заполняется из живого API-сервера, в client-mode данных нет | Использовать `--dry-run=server` для подключения к API, либо указать capabilities явно через флаг `--kube-version` и `--api-versions` (синтаксис Helm) |
| `Error: failed to download "<name>" at version "1.2.3+build.5"` после подписи Cosign | Cosign не выполняет преобразование `+` → `_` | Подписывать по преобразованному тегу: `1.2.3_build.5` (см. шаг 2 в п. 1) |
| WASM-плагин возвращает `permission denied` на файловую операцию | В манифесте плагина не указан host `files` или функция недоступна через `allowedHosts` | Расширить `wasm.allowedHosts` в `plugin.yaml`; ограничить только действительно нужными разрешениями (least privilege) |
| Установка по дигесту не проходит при наличии `--version` | Некоторые старые версии Helm (≤ 3.7) не поддерживают digest-install | Обновиться до Helm ≥ 3.8 (v3) или ≥ 4.0 (v4) |
| Kyverno/OPA блокирует деплой неподписанного чарта, хотя подпись есть | Admission controller не имеет доступа к публичному ключу или keyless-идентичности | Проверить маунт `cosign.pub` в ConfigMap контроллера; для keyless — настроить `trustedIdentities` или `keylessPrefix` |

---

## Ограничения и границы применимости

- **WASM-плагины и долгие операции:** runtime Extism накладывает ограничения на интенсивный I/O и CPU-bound задачи в песочнице. Для ресурсоёмких плагинов остаётся путь классических бинарных CLI-плагинов.
- **Post-renderer без доступа к API:** пост-рендерер работает со статическим YAML, не может делать запросы к API-серверу. Для мутаций, зависящих от состояния кластера, нужен admission webhook (Kyverno mutate, OPA Gatekeeper) или operator-паттерн.
- **Capabilities в client-side dry-run:** при `helm install --dry-run=client` объект `.Capabilities` пуст/дефолтен; рендеринг адаптивных шаблонов в этом режиме может давать результат, отличный от server-side. Для CI-проверки адаптивной логики используйте `--dry-run=server` либо явно задавайте capabilities флагами.
- **Rekor и air-gapped среды:** keyless-режим Cosign требует доступа к Rekor transparency log. В полностью изолированных средах разворачивается собственный Rekor (см. [Sigstore/Rekor в on-premise](../../../../Security/Tools/sigstore.md)), либо используется key-based режим.
- **OCI в Helm v3 vs v4:** в v3 OCI-реестры уже GA (с v3.8), но некоторые фичи (digest install, multi-doc values) появились позже. Перед переходом на v4 сверьтесь с [Helm 4 Full Changelog](https://helm.sh/docs/changelog/).
- **Helm v3 EOL:** баг-фиксы до 8 июля 2026, security-фиксы до 11 ноября 2026. Планируйте миграцию на v4 в этот промежуток.

---

## Связанные документы

- **[Обзор Helm](../helm_overview.md)** — архитектура v4, SSA, OCI-реестры, lifecycle релиза.
- **[Зависимости и библиотечные чарты](../helm_dependencies_and_library_charts.md)** — композиция и Blueprint-паттерн.
- **[Проверка версий API и возможностей](../templating/scenarios/api_versions.md)** — детальный справочник по `.Capabilities`.
- **[Безопасность Helm](./security_best_practices.md)** — управление секретами (SOPS), RBAC, multi-tenant.
- **[Sigstore/Cosign](../../../../Security/Tools/sigstore.md)** — подробное руководство по подписи артефактов.