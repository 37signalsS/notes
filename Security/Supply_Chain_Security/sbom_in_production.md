# SBOM в продакшене: чтение, интерпретация, реакция

**Актуально для:** CycloneDX 1.7, SPDX 3.0, Trivy ≥ 0.71.0, Syft v1.54+, Grype v0.35+, GUAC v1.x, Kyverno v1.19+ (ImageValidatingPolicy), Kubernetes 1.31+, Harbor v2.15+

## Определения

* **SBOM (Software Bill of Materials):** Машиночитаемый инвентарный список всех компонентов программного продукта (библиотеки, пакеты, модули, зависимости). Основные форматы — CycloneDX 1.7 и SPDX 3.0+.
* **VEX (Vulnerability Exploitability eXchange):** Сопроводительный документ к SBOM, в котором производитель указывает статус уязвимостей (`not_affected`, `fixed`, `affected`, `under_investigation`) с обоснованием. Позволяет фильтровать ложные срабатывания CVE на основе фактической конфигурации продукта.
* **Blast Radius (Радиус поражения):** Масштаб затронутых сервисов при обнаружении уязвимости в общем компоненте. Определяется по графу зависимостей SBOM.
* **Reachability Analysis (Анализ достижимости):** Определение того, вызывается ли уязвимая функция библиотеки в конкретном приложении. Снижает количество ложных срабатываний CVE на 80–90%.
* **SBOM-as-Artifact:** Модель, при которой SBOM прикрепляется к OCI-образу как аттестация через Referrers API (OCI 1.1) и верифицируется перед деплоем.
* **Living SBOM:** Динамический граф зависимостей, непрерывно обогащаемый данными об уязвимостях (VEX) и их статусе. Заменяет статический «снимок» SBOM.
* **PURL (Package URL):** Унифицированный идентификатор пакета, позволяющий однозначно ссылаться на компонент независимо от экосистемы. Формат: `pkg:type/namespace/name@version`.
* **CycloneDX:** Спецификация SBOM, ориентированная на DevSecOps и автоматизацию. Поддерживает родную интеграцию VEX, CBOM и CDXA.
* **SPDX (Software Package Data Exchange):** ISO-стандартизированный формат SBOM с модульной архитектурой (Profiles) и JSON-LD поддержкой. Преимущественно для юридического комплаенса.
* **Trivy:** Сканер уязвимостей и лицензий, поддерживающий чтение SBOM в форматах CycloneDX и SPDX. Используется для быстрой поиска CVE по SBOM и образам.
* **GUAC (Graph for Understanding Artifact Composition):** Графовая база данных для агрегации SBOM, SLSA-аттестаций и VEX. Позволяет мгновенно определить blast radius при обнаружении новой уязвимости.
* **EU CRA (Cyber Resilience Act):** Регламент ЕС (Regulation (EU) 2024/2847), обязывающий производителей предоставлять SBOM и реагировать на эксплуатируемые уязвимости в течение 24 часов (раннее предупреждение) и 72 часов (полное уведомление) через CRA Single Reporting Platform (SRP), управляемый ENISA. Применяется с 11 сентября 2026 года для отчётности и с 11 декабря 2027 года для полного комплаенса.

## Основные концепции

### Зачем нужен SBOM в продакшене

SBOM — это не просто комплаенс-документ. В продакшене он решает три критические задачи:

1. **Реагирование на CVE:** Когда появляется новая уязвимость, SBOM позволяет за минуты определить, какие сервисы затронуты, и оценить blast radius.
2. **Аудит зависимостей:** Позволяет ответить на вопрос «где используется библиотека X?» без поиска по коду или образам.
3. **Проверка перед деплоем:** Admission-контроллер (Kyverno/OPA) блокирует образ без валидного SBOM или с критичными CVE, для которых нет VEX-исключения.

### Архитектура потребления SBOM в продакшене

```text
┌─────────────────────────────────────────────────────────┐
│  Build-time: CI/CD генерирует SBOM + VEX + подпись     │
│  (Syft, Trivy, Cosign) → Harbor (Referrers API)        │
└─────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  Admission Control (Kyverno ImageValidatingPolicy)     │
│  • Проверка подписи SBOM                               │
│  • Проверка наличия критических CVE                    │
│  • Применение VEX (not_affected)                       │
└─────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  Production: потребление SBOM                            │
│  • GUAC (blast radius, patch plan)                      │
│  • Prometheus/Alertmanager (drift, new CVE)             │
│  • Тикет-система (автоматические тикеты)                │
│  • Runtime eBPF (Falco/Tetragon)                        │
└─────────────────────────────────────────────────────────┘
```

### Структура SBOM (CycloneDX 1.7)

Ключевые поля для чтения в продакшене:

| Поле | Описание | Использование |
| :--- | :--- | :--- |
| `components[].name` / `version` | Имя и версия компонента | Поиск vulnerable компонентов |
| `components[].purl` | Package URL (pkg:type/name@version) | Уника**л**ьный идентификатор для cross-service поиска |
| `components[].scope` | `required` или `optional` | Фильтрация production-зависимостей |
| `components[].licenses` | Лицензии | Комплаенс и restricted licenses |
| `vulnerabilities[].id` | CVE ID | Быстрый поиск по базе |
| `vulnerabilities[].ratings[].severity` | CRITICAL, HIGH, MEDIUM, LOW | Приоритизация триажа |
| `vulnerabilities[].affects[].ref` | Ссылка на затронутый компонент | Точная привязка CVE к компоненту |
| `metadata.timestamp` | Время генерации SBOM | Проверка актуальности |
| `metadata.tools` | Инструменты генерации | Аудит цепочки поставок |

Пример минимального SBOM для production-потребления:

```json
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.7",
  "version": 1,
  "metadata": {
    "timestamp": "2026-09-21T10:00:00Z",
    "tools": [{"vendor": "anchore", "name": "syft", "version": "1.54.0"}],
    "component": {
      "type": "application",
      "name": "my-app",
      "version": "1.2.3",
      "bom-ref": "my-app-1.2.3"
    }
  },
  "components": [
    {
      "type": "library",
      "name": "requests",
      "version": "2.31.0",
      "purl": "pkg:pypi/requests@2.31.0",
      "scope": "required",
      "licenses": [{"license": {"id": "Apache-2.0"}}],
      "hashes": [{"alg": "SHA-256", "value": "abcd1234..."}]
    }
  ],
  "vulnerabilities": [
    {
      "id": "CVE-2024-EXAMPLE",
      "source": {"name": "NVD"},
      "ratings": [{"severity": "CRITICAL", "score": 9.8}],
      "affects": [{"ref": "pkg:pypi/requests@2.31.0"}]
    }
  ]
}
```

### Процесс реагирования на новую CVE

```text
Новая CVE опубликована
    │
    ├── 1. Получение CVE ID и описания
    │       (NVD, GitHub Advisory, vendor security bulletin)
    │
    ├── 2. Проверка SBOM: есть ли затронутый компонент?
    │       trivy sbom sbom.json --format json | jq --arg c "CVE-2024-EXAMPLE" \
    │         '.Results[].Vulnerabilities[]? | select(.VulnerabilityID == $c)'
    │       → Да / Нет
    │
    ├── 3. Reachability: вызывается ли уязвимая функция?
    │       govulncheck ./...  (для Go) / osv-scanner --call-analysis=go  (call-graph)
    │       → Reachable / Unreachable
    │
    ├── 4. Определение Blast Radius: какие сервисы используют компонент?
    │       guacone query patch --start-purl "pkg:pypi/requests@2.31.0" --search-depth 10
    │       → Список сервисов и фронтеров для патчинга
    │
    ├── 5. Триаж и решение:
    │       ├── Critical + Reachable → немедленный hotfix
    │       ├── Critical + Unreachable → VEX not_affected + мониторинг
    │       ├── High → плановое обновление (SLA 7 дней)
    │       └── Low/Medium → следующий релиз
    │
    └── 6. Отчёт: какой SBOM, какой компонент, какое решение
```

> **См. также:** Полный triage-процесс с матрицей CVSS + Reachability и автоматическим CI-скриптом — в [Триаже CVE](./cve_triage_workflow.md).

## Предварительные требования

Для реализации потребления SBOM в продакшене на bare metal / on-prem инфраструктуре необходимы компоненты из [Обзора безопасности цепочки поставок](./overview.md#предварительные-требования). Здесь приведены только production-специфичные детали:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Trivy** | ≥ 0.71.0 | Сканирование SBOM и образов на CVE, VEX-фильтрация. |
| **Grype** | v0.35+ | Анализ достижимости (reachability) уязвимостей. |
| **GUAC** | v1.x | Граф зависимостей для blast radius и patch plan. |
| **Kyverno** | v1.19+ | Admission-контроль через `ImageValidatingPolicy` для верификации SBOM и VEX. |
| **Harbor** | v2.15+ | OCI-реестр с поддержкой Referrers API для хранения SBOM и подписей. |

**Аппаратные требования:**
* CPU с поддержкой AES-NI для ускорения криптографических операций при проверке подписей.
* Минимум 4 ГБ ОЗУ на узел, где запущен GUAC (граф может потребовать 8–16 ГБ для больших кластеров).
* Минимум 8 ГБ ОЗУ на узел CI/CD-сканера (Trivy + Grype).

**Начальное состояние окружения:**
* SBOM и VEX генерируются на этапе сборки и прикрепляются к образу через Referrers API (см. [Целостность сборки](./build_integrity.md#нативная-аттестация-в-docker-buildkit-034)).
* Pod-сигнатуры и SBOM подписаны (keyless через Cosign или ключи Notation) — см. [Подпись артефактов](./artifact_signing.md).
* Внутренний DNS-сервер, разрешающий `harbor.internal` и `guac.internal`.

## Практические сценарии

### Сценарий 1: Быстрый поиск затронутых сервисов по CVE

```bash
# 1. Сканирование SBOM на конкретную CVE (jq-фильтрация — --vuln флаг не поддерживается trivy sbom)
trivy sbom sbom.json --format json | \
  jq --arg c "CVE-2024-EXAMPLE" \
  '.Results[].Vulnerabilities[]? | select(.VulnerabilityID == $c)'
# → {"VulnerabilityID":"CVE-2024-EXAMPLE","PkgName":"requests","InstalledVersion":"2.31.0","FixedVersion":"2.32.0","Severity":"CRITICAL"}

# Альтернатива: сканирование образа напрямую с фильтрацией по CVE
trivy image --format json harbor.internal/my-app:v1.2.3 | \
  jq --arg c "CVE-2024-EXAMPLE" \
  '.Results[].Vulnerabilities[]? | select(.VulnerabilityID == $c)'
# → {"VulnerabilityID":"CVE-2024-EXAMPLE","PkgName":"requests","InstalledVersion":"2.31.0","FixedVersion":"2.32.0","Severity":"CRITICAL"}

# 2. Массовое сканирование всех образов в проекте Harbor
for img in $(curl -s -u admin:$HARBOR_PASS "https://harbor.internal/api/v2.0/projects/myapp/repositories" | jq -r '.[].name'); do
  digest=$(curl -s -u admin:$HARBOR_PASS "https://harbor.internal/api/v2.0/projects/myapp/repositories/$img/artifacts?tags=true" | jq -r '.[0].digest')
  echo "Checking $img@$digest..."
  trivy image --format json "harbor.internal/$img@$digest" | \
    jq --arg c "CVE-2024-EXAMPLE" '.Results[].Vulnerabilities[]? | select(.VulnerabilityID == $c) | .VulnerabilityID'
done
# → CVE-2024-EXAMPLE
# → (пусто для не затронутых образов)
```

**Валидация:** Убедитесь, что все затронутые образы перечислены и их версии совпадают с уязвимой.

### Сценарий 2: Чтение SBOM и извлечение компонентов

```bash
# 1. Генерация SBOM из образа (Syft v1.54+)
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json > sbom.json

# 2. Список всех компонентов с версиями
jq '.components[] | {name: .name, version: .version, purl: .purl}' sbom.json

# 3. Фильтрация по типу (только Python-пакеты)
jq '.components[] | select(.purl | startswith("pkg:pypi")) | {name: .name, version: .version}' sbom.json

# 4. Поиск конкретной библиотеки по PURL
jq '.components[] | select(.purl == "pkg:pypi/requests@2.31.0")' sbom.json
# → {"type":"library","name":"requests","version":"2.31.0","purl":"pkg:pypi/requests@2.31.0",...}

# 5. Подсчёт общего количества компонентов
jq '.components | length' sbom.json
# → 142

# 6. Проверка наличия required-scope компонентов (production-зависимости)
jq '.components[] | select(.scope == "required") | .name' sbom.json
```

> **Важно:** Генерация SBOM из исходного кода и восстановление в air-gapped средах — подробно описана в [Анализе зависимостей и SBOM](./dependency_and_sbom_analysis.md).

**Валидация:** Убедитесь, что SBOM содержит ожидаемые компоненты и PURL корректны.

```bash
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json | jq '.components | length'
# → 142
```

### Сценарий 3: Определение Blast Radius через GUAC

```bash
# 1. Импорт SBOM в GUAC (v1.x, guacone CLI)
guacone collect --add-vuln-on-ingest files sbom.json

# 2. Запрос: какие артефакты используют requests@2.31.0?
#    (patch plan показывает все зависимые сервисы)
guacone query patch --start-purl "pkg:pypi/requests@2.31.0" --search-depth 10
# → ---FRONTIER  LEVEL 0---
# → pkg:harbor.internal/my-app:v1.2.3
# → pkg:harbor.internal/my-worker:v1.0.0
# → ---FRONTIER  LEVEL 1---
# → pkg:harbor.internal/gateway:v2.0.0

# 3. Альтернатива: прямой поиск по всем SBOM в репозитории
find . -name "sbom.json" -exec jq -r '.components[] | select(.name=="requests") | input_filename' {} \;
# → ./apps/api/sbom.json
# → ./apps/auth/sbom.json
# → ./apps/gateway/sbom.json

# 4. Проверка через GraphQL (для кастомных запросов)
curl -s -X POST http://guac.internal:8080/query -H 'content-type: application/json' -d '{
  "query": "{
    packages(pkgSpec: {name: \"requests\", version: \"2.31.0\"}) {
      id
      locations {
        nodes {
          ... on Artifact {
            hash
          }
        }
      }
    }
  }"
}'
```

> **Важно:** Полный lifecycle GUAC — генерация, импорт, запросы и визуализация — в [Обзоре безопасности цепочки поставок](./overview.md#3-supply-chain-observability-наблюдаемость).

**Валидация:** Убедитесь, что все сервисы, использующие уязвимый компонент, перечислены в patch plan.

### Сценарий 4: VEX-отчёт для подтверждения not_affected

```bash
# 1. Проверка: вызывается ли уязвимая функция?
govulncheck ./...  # для Go; Grype OSS не имеет --show-vulnerability-reachability
# → CVE-2024-EXAMPLE: unreachable

# 2. Создание VEX-отчёта (CycloneDX 1.7)
cat > vex-cve-2024-example.json << 'EOF'
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.7",
  "version": 1,
  "vulnerabilities": [
    {
      "id": "CVE-2024-EXAMPLE",
      "source": {"name": "NVD"},
      "status": "not_affected",
      "justification": "vulnerable_code_not_present",
      "detail": "Библиотека requests установлена, но уязвимый модуль HTTPDigestAuth не используется в приложении."
    }
  ]
}
EOF

# 3. Применение VEX к SBOM при сканировании
trivy sbom --vex vex-cve-2024-example.json sbom.json --severity CRITICAL
# → 0 vulnerabilities (CVE-2024-EXAMPLE исключена из отчёта)

# 4. Коммит VEX-отчёта в репозиторий для аудита
git add vex-cve-2024-example.json
git commit -m "VEX: mark CVE-2024-EXAMPLE as not_affected for my-app"
```

> **Важно:** Формат VEX и статусы (`not_affected`, `fixed`, `affected`, `under_investigation`) — подробно описаны в [Триаже CVE](./cve_triage_workflow.md) и [Анализе зависимостей и SBOM](./dependency_and_sbom_analysis.md).

**Валидация:** VEX-исключенная CVE больше не появляется в Trivy-отчёте.

```bash
trivy sbom sbom.json --severity CRITICAL | grep "CVE-2024-EXAMPLE"
# → (пустой вывод — CVE исключена)
```

### Сценарий 5: Сравнение SBOM между версиями для обнаружения drift

```bash
# 1. Генерация SBOM для текущей и новой версии
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json > sbom-current.json
syft harbor.internal/my-app:v1.2.4 -o cyclonedx-json > sbom-new.json

# 2. Сравнение через Trivy diff
trivy diff sbom:./sbom-current.json sbom:./sbom-new.json
# → Total: 2 dependencies added, 0 removed, 3 changed.
#   + log4j@2.20.0    (новая зависимость — проверить на CVE)
#   + jakarta.annotation-api@2.1.0
#   ~ requests@2.31.0 → requests@2.32.0
#   ~ urllib3@2.0.7 → urllib3@2.1.0
#   ~ flask@2.3.0 → flask@2.3.2

# 3. Проверка новых компонентов на CVE (сканируем новый SBOM)
trivy sbom sbom-new.json --format json --scanners vuln | \
  jq '.Results[].Vulnerabilities[]? | {id: .VulnerabilityID, pkg: .PkgName, severity: .Severity}'
```

> **Важно:** Runtime-сравнение (сравнение SBOM в памяти с build-time) — в [Runtime drift detection](./runtime_drift_detection.md).

### Сценарий 6: Admission-контроль по SBOM и VEX в Kubernetes

```yaml
# Kyverno ImageValidatingPolicy (v1.19+): блокировка подов без SBOM или с критичными CVE
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: require-sbom-and-vex
spec:
  failurePolicy: Enforce
  rules:
    - name: check-sbom-attestation
      image: harbor.internal/*
      attestations:
        - type: https://cyclonedx.org/bom
          attestors:
            - entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
                      -----END PUBLIC KEY-----
```

```bash
# Применение политики
kubectl apply -f require-sbom-and-vex.yaml

# Проверка: попытка запуска без SBOM
kubectl run test --image=harbor.internal/my-app:unsigned --dry-run=server
# → Error: admission webhook denied the request: image validation failed

# Проверка: попытка запуска с SBOM, содержащим unfixed CVE
kubectl run test --image=harbor.internal/my-app:v1.2.3 --dry-run=server
# → Error: image validation failed: CRITICAL vulnerability found without VEX not_affected

# Проверка: попытка запуска с SBOM + VEX
kubectl run test --image=harbor.internal/my-app:v1.2.4 --dry-run=server
# → pod/test created (dry-run)
```

> **Важно:** Полный пайплайн аттестации (SBOM + Provenance + подпись) и admission control описаны в [Обзоре безопасности цепочки поставок](./overview.md), [Целостности сборки](./build_integrity.md) и [Подписи артефактов](./artifact_signing.md).

## Валидация внедрения

После настройки потребления SBOM в продакшене выполните комплексную проверку:

```bash
# 1. Проверка наличия SBOM в реестре через Referrers API
curl -u "robot$ci-bot:$ROBOT_SECRET" \
  "https://harbor.internal/v2/my-app/manifests/sha256:$(skopeo inspect docker://harbor.internal/my-app:v1.2.3 --format '{{.Digest}}' | cut -d: -f2)/referrers"
# → {"manifest":{"layers":[{"mediaType":"application/vnd.cyclonedx.bom.v1+json",...}]}}

# 2. Проверка: SBOM содержит ожидаемые компоненты
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json | jq '.components | length'
# → 142

# 3. Проверка: VEX применяется корректно
trivy sbom --vex vex-cve-2024-example.json sbom.json --severity CRITICAL | grep -c "CVE-2024-EXAMPLE"
# → 0 (CVE исключена)

# 4. Проверка: admission control блокирует образ без SBOM
kubectl run test --image=harbor.internal/my-app:unsigned --dry-run=server 2>&1 | grep "denied"
# → Error: admission webhook denied the request

# 5. Проверка: GUAC возвращает blast radius для уязвимого пакета
guacone query patch --start-purl "pkg:pypi/requests@2.31.0" --search-depth 10 | grep "my-app"
# → pkg:harbor.internal/my-app:v1.2.3

# 6. Проверка: Drift Detection (runtime vs build-time)
trivy diff sbom:./build-sbom.json sbom:./runtime-sbom.json
# → Total: 0 dependencies added, 0 removed, 0 changed.
```

## Лучшие практики

1. **SBOM при каждом релизе:** Генерация SBOM — часть пайплайна сборки. SBOM подписывается и прикрепляется к образу через Referrers API (OCI 1.1). Храните SBOM минимум 12 месяцев (требование EU CRA).
2. **VEX для каждого false positive:** Не оставляйте решение в голове — фиксируйте в VEX-отчёте и коммитьте в репозиторий. Это документирует решение для аудита и позволяет автоматически применять его в admission control.
3. **GUAC для blast radius:** В кластере с несколькими сервисами используйте GUAC для мгновенного определения затронутых артефактов. Автоматизируйте запросы через `guacone query patch` и интегрируйте с тикет-системой.
4. **Digest-pinning:** Никогда не используйте теги `latest` или `v1` в продакшене. Фиксируйте образы и зависимости по digest (`image@sha256:...`).
5. **Сравнение SBOM между версиями:** Перед деплоем сравнивайте SBOM текущей и новой версии для обнаружения неожиданных изменений (новых зависимостей, upgrade'ов).
6. **Least Privilege для сканеров:** Используйте robot-аккаунты с минимальными правами для доступа к реестру и GUAC. Отдельные узлы для сканирования и запросов к графу.
7. **Ротация ключей:** Периодически (раз в 90 дней) ротируйте ключи подписи SBOM. Для keyless-сценария обновляйте Fulcio CA-корневой сертификат.
8. **Runtime monitoring:** Используйте eBPF-агенты (Falco/Tetragon) для обнаружения загрузки библиотек, отсутствующих в SBOM. Регулярно сравнивайте runtime-SBOM с build-time SBOM.
9. **Эфемерные среды:** Сканирование и реакция на CVE выполняются в изолированных эфемерных средах без доступа к внешней сети для предотвращения подмены пакетов.

```bash
# Пример очистки старых артефактов в Harbor (через API с robot-аккаунтом)
curl -u "robot$ci-bot:$ROBOT_SECRET" -X POST \
  "https://harbor.internal/api/v2.0/projects/my-app/repositories/my-app/artifacts/sha256:abc123" \
  -H "Content-Type: application/json" \
  -d '{"with_tag":false,"with_label":false}'
# → 200 OK (артефакт помечен для удаления)
```

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| SBOM не содержит ожидаемых компонентов | Syft не распознал экосистему | `syft dir:. -o cyclonedx-json` | Используйте `cdxgen` как fallback для неподдерживаемых языков |
| CVE не отображается в SBOM | Trivy DB устарела | `trivy image --download-db-only` | Обновите базу: `trivy image --reset && trivy image ...` |
| VEX не применяется | Неверный формат VEX или отсутствие `status` | `cat vex.json \| jq .` | Убедитесь, что VEX соответствует CycloneDX 1.7 профилю с `bomFormat` и `specVersion` |
| GUAC не возвращает результатов | SBOM не импортирован или certifier OSV не запущен | `guacone collect files sbom.json` | Импортируйте SBOM и запустите `guacone certifier osv` для загрузки данных об уязвимостях |
| Kyverno блокирует валидный образ | Политика содержит устаревший public key или использует ClusterPolicy | `kubectl get imagevalidatingpolicy require-sbom-and-vex -o yaml` | Используйте `ImageValidatingPolicy` (v1.19+), обновите public key |
| Trivy sbom не находит CVE | SBOM не содержит компонент или Trivy не поддерживает формат | `trivy sbom sbom.json --format json \| jq '.Results'` | Проверьте, что SBOM валидный CycloneDX/SPDX и содержит vulnerable компонент |
| Referrers API 404 | Реестр не поддерживает OCI 1.1 | `curl -v /v2/.../referrers` | Обновите Harbor до v2.15+ или используйте альтернативный реестр |
| Blast radius пуст | Зависимость не проиндексирована в GUAC | `guacone query patch --start-purl "pkg:..." --search-depth 10` | Импортируйте все SBOM сервисов в GUAC перед запросами |

## Граничные случаи и ограничения

* **Динамические зависимости (dlopen):** SBOM фиксирует зависимости на этапе сборки. В рантайме могут загружаться дополнительные библиотеки через `dlopen` (Java ClassLoader, Python importlib, Go plugin). Для детекции — eBPF-агенты (Falco/Tetragon), сравнение runtime-SBOM с build-time через `syft runtime:process`.
* **Mono-repo:** В монорепозитории с несколькими сервисами SBOM генерируется для каждого сервиса отдельно. Общий SBOM не отражает изоляцию сервисов. Используйте per-service SBOM с метаданными о сервисе.
* **Обратная совместимость:** SBOM в формате CycloneDX 1.7 может не читаться старыми версиями Trivy (< v0.71.0). Проверяйте версию формата и инструмента. Для legacy-сред используйте SPDX 3.0+ как fallback.
* **Multi-architecture образы:** SBOM и аттестации должны генерироваться для каждого архитектурного варианта (`linux/amd64`, `linux/arm64`) отдельно. Используйте `docker buildx imagetools inspect` для просмотра constituent-манифестов.
* **Air-gapped среды:** Отсутствие доступа к базам CVE требует развертывания локального зеркала Trivy DB и использования offline-режимов Syft/cdxgen. Все обновления баз должны проходить через механизм "data diode".
* **EU CRA compliance:** SBOM должен включать CBOM (Cryptography Bill of Materials) для оценки готовности к постквантовой миграции. Используйте `cdxgen` для генерации CBOM и проверяйте наличие уязвимых алгоритмов (RSA < 3072, ECDSA < P-384).
* **VEX accuracy:** Reachability-анализ имеет ограниченную точность для транзитивных цепочек (A → B → C, где C уязвим). При сомнениях используйте `under_investigation` статус вместо `not_affected`.

## Дополнительная информация

### Стандарты и ресурсы

* **CycloneDX Specification (v1.7):** <https://cyclonedx.org/> — формат SBOM с родной поддержкой VEX, CBOM и CDXA.
* **SPDX Specification (v3.0+):** <https://spdx.dev/> — модульный формат с JSON-LD поддержкой и ISO-стандартизацией.
* **EU CRA:** <https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act> — официальный текст закона о киберустойчивости ЕС.
* **NIST SSDF:** <https://csrc.nist.gov/projects/secure-software-development-framework> — Secure Software Development Framework (SP 800-218 Rev 1).
* **OpenSSF:** <https://openssf.org/> — инициативы GUAC, Scorecard и Sigstore.
* **Trivy:** <https://github.com/aquasecurity/trivy> — все-в-одном сканер для образов, filesystems, SBOM, IaC.
* **GUAC:** <https://guac.sh/> — графовая база данных для анализа цепочки поставок.

### Связанные документы

* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — генерация SBOM, VEX, SCA.
* [Подпись артефактов](./artifact_signing.md) — подпись SBOM через Cosign/Notation.
* [Целостность сборки](./build_integrity.md) — аттестации SLSA и интеграция SBOM в пайплайн.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз и регуляторика.
* [Триаж CVE](./cve_triage_workflow.md) — процесс классификации и приоритизации CVE.
* [Runtime drift detection](./runtime_drift_detection.md) — обнаружение расхождений SBOM в рантайме.
* [SBOM-политика для разработчиков](./sbom_developer_policy.md) — RACI и quality gate для SBOM.
* [Реагирование на инциденты supply chain](./supply_chain_incident_response.md) — пошаговый incident response.
* [Сравнение SCA-инструментов](./sca_tools_comparison.md) — Trivy vs Grype vs Syft для сканирования SBOM.
* [SBOM для Docker](../../Docker/Docker_security/docker_sbom.md) — генерация аттестаций через BuildKit.
* [Сканирование уязвимостей](../../Docker/Docker_security/vulnerability_scanning.md) — детальное использование Trivy и Grype.
* [ASPM: Управление безопасностью приложений](../../CI-CD/DevSecOps/devsecops_overview.md) — оркестрация рисков и результатов сканирования.