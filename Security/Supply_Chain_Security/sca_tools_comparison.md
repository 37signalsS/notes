# Сравнение SCA-инструментов (Software Composition Analysis)

## Определения

* **SCA (Software Composition Analysis):** Автоматизированный процесс идентификации сторонних компонентов (open-source библиотек, коммерческих модулей) и оценки связанных с ними рисков безопасности, лицензионной чистоты и качества.
* **Vulnerability Database (База уязвимостей):** Структурированный источник данных о известных CVE, связанных с конкретными компонентами. Основные: NVD (National Vulnerability Database), OSV (Open Source Vulnerabilities от Google), GitHub Advisory Database, SecurityTrack.
* **Reachability Analysis (Анализ достижимости):** Определение того, вызывается ли уязвимая функция библиотеки в конкретном приложении. Снижает количество ложных срабатываний на 80–90%.
* **EPSS (Exploit Prediction Scoring System):** Вероятностная модель, оценивающаяlikelihood эксплуатации CVE в ближайшие 30 дней. Дополняет CVSS оценкой реального риска.
* **OSV (Open Source Vulnerabilities):** Открытый формат и база уязвимостей от Google, агрегирующая данные из NVD, GitHub Advisory, и экосистемных баз (PyPI, npm, Go, Rust).

## Основные концепции

### Роль SCA в цепочке поставок

SCA — это первый линия обнаружения известных уязвимостей в зависимостях. Интегрируется в CI/CD для блокировки пайплайна при обнаружении критичных CVE и используется в production для непрерывного мониторинга.

### Сравнение инструментов

| Критерий | **Trivy** | **Grype** | **Snyk** | **osv-scanner** | **Syft** |
|:--- |:--- |:--- |:--- |:--- |:--- |
| **Тип** | Сканер + SBOM | Сканер | Платформа (SaaS + CLI) | Сканер | Генератор SBOM |
| **Фокус** | Образы, FS, SBOM, IaC | Образы, SBOM | Код, образы, IaC, контейнеры | Зависимости (lock-файлы) | Генерация SBOM |
| **Базы CVE** | NVD, GitHub Advisory, Alpine, Red Hat, Ubuntu | NVD, GitHub Advisory | NVD + собственная (Snyk Vuln DB) | OSV (агрегатор NVD + экосистемы) | Нет (генератор) |
| **Reachability** | Ограниченная | Да (statistic) | Да (core) | Нет | Нет |
| **EPSS** | Да | Нет | Да | Нет | Нет |
| **SBOM** | Чтение (CycloneDX, SPDX) | Чтение (CycloneDX) | Чтение + генерация | Нет | Генерация (CycloneDX, SPDX) |
| **VEX** | Да (применение) | Нет | Да | Нет | Нет |
| **IaC scanning** | Да (Terraform, K8s, Dockerfile) | Нет | Да | Нет | Нет |
| **Лицензия** | Apache 2.0 | Apache 2.0 | Snyk Agent (freemium) | Apache 2.0 | Apache 2.0 |
| **Self-hosted** | Да (CLI) | Да (CLI) | Да (CLI) + SaaS | Да (CLI) | Да (CLI) |
| **OIDC/интеграция** | GitLab, GitHub, CI | CI | GitLab, GitHub, Jira, Slack | CI | CI |

### Когда использовать

| Задача | Рекомендуемый инструмент | Почему |
|:--- |:--- |:--- |
| Сканирование Docker-образов в CI | **Trivy** | Единый инструмент: CVE + SBOM + IaC + конфиги |
| Сканирование SBOM (post-build) | **Trivy** или **Grype** | Trivy — шире покрытие, Grype — reachability |
| Reachability analysis | **Grype** или **Snyk** | Grype — free, Snyk — глубже |
| Генерация SBOM | **Syft** | Де-факто стандарт, CycloneDX + SPDX |
| Сканирование lock-файлов (npm, pip, Go) | **osv-scanner** | Быстрый, агрегирует несколько баз |
| Корпоративная платформа (Jira, SLA, policies) | **Snyk** | Интеграция с трекерами, policy engine |
| Air-gapped среда | **Trivy** + **Syft** | Offline-режим, локальные базы |

## Практические сценарии

### Сценарий 1: Сканирование Docker-образа (Trivy)

```bash
# 1. Базовое сканирование на CVE
trivy image harbor.internal/my-app:v1.2.3
# → scanned in 5.2s, 142 packages, 3 critical, 12 high

# 2. Сканирование с фильтрацией по severity
trivy image --severity CRITICAL,HIGH harbor.internal/my-app:v1.2.3

# 3. Сканирование с reachability (Trivy v0.55+)
trivy image --format json harbor.internal/my-app:v1.2.3 | \
  jq '.Results[].Vulnerabilities[]? | select(.Reachability == "REACHABLE")'

# 4. Сканирование с EPSS (Trivy v0.55+)
trivy image --epss-score 0.5 harbor.internal/my-app:v1.2.3
# → Показывает только CVE с EPSS > 0.5 (вероятность эксплуатации > 50%)

# 5. Сканирование IaC (Dockerfile, K8s манифесты)
trivy config ./k8s/ --severity CRITICAL,HIGH
```

### Сценарий 2: Reachability analysis через Grype

```bash
# 1. Сканирование с reachability
grype harbor.internal/my-app:v1.2.3 --show-vulnerability-reachability
# → REACHABLE:   CVE-2024-1234 (requests@2.31.0) — уязвимый код вызывается
# → UNREACHABLE: CVE-2024-5678 (flask@2.3.0) — уязвимый модуль не используется

# 2. Экспорт результатов
grype harbor.internal/my-app:v1.2.3 -o json > grype-result.json

# 3. Фильтрация: только reachable critical
jq '.matches[] | select(.vulnerability.severity == "CRITICAL" and .matchDetails[0].maxReachability == "REACHABLE")' \
  grype-result.json
```

### Сценарий 3: Быстрое сканирование lock-файлов (osv-scanner)

```bash
# 1. Сканирование всех lock-файлов в проекте
osv-scanner --lockfile=./package-lock.json
# → Found 3 vulnerabilities

# 2. Сканирование всего репозитория
osv-scanner -r ./
# → Автоматически находит package-lock.json, requirements.txt, go.sum, Cargo.lock

# 3. Вывод в формате SARIF (для интеграции с GitHub)
osv-scanner --format sarif -r ./ > results.sarif
```

### Сценарий 4: Генерация SBOM через Syft

```bash
# 1. SBOM из Docker-образа (CycloneDX)
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json > sbom.json

# 2. SBOM из исходного кода (директория)
syft dir:. -o cyclonedx-json > sbom-source.json

# 3. SBOM из lock-файла
syft ./package-lock.json -o spdx-json > sbom-npm.json

# 4. Проверка SBOM
jq '.components | length' sbom.json
# → 142

# 5. Фильтрация по экосистеме
jq '.components[] | select(.purl | startswith("pkg:pypi"))' sbom.json
```

### Сценарий 5: Комбинированный пайплайн в CI

```yaml
# GitLab CI: SCA + SBOM + VEX
stages:
  - build
  - scan
  - sign

build:
  stage: build
  script:
    - docker buildx build --sbom --provenance --push -t $REGISTRY:$TAG .

sbom-generate:
  stage: scan
  image: anchore/syft:v1.5.0
  script:
    - syft $REGISTRY:$TAG -o cyclonedx-json > sbom.json
  artifacts:
    paths: [sbom.json]

trivy-scan:
  stage: scan
  image: aquasec/trivy:0.55.0
  script:
    - trivy sbom sbom.json --severity CRITICAL --exit-code 1
    - trivy sbom --vex vex.json sbom.json --severity CRITICAL
  dependencies: [sbom-generate]

grype-reachability:
  stage: scan
  image: anchore/grype:0.35.0
  script:
    - grype sbom:sbom.json --show-vulnerability-reachability -o json > grype-result.json
    - |
      REACHABLE_CRITICAL=$(jq '[.matches[] | select(.vulnerability.severity=="CRITICAL" and .matchDetails[0].maxReachability=="REACHABLE")] | length' grype-result.json)
      if [ "$REACHABLE_CRITICAL" -gt 0 ]; then
        echo "REACHABLE CRITICAL CVEs found — blocking"
        exit 1
      fi
  dependencies: [sbom-generate]

sign:
  stage: sign
  script:
    - cosign sign --yes $REGISTRY:$TAG
    - cosign attest --predicate sbom.json --type cyclonedx $REGISTRY:$TAG
  only: [main]
```

### Сценарий 6: Offline-сканирование (air-gapped)

```bash
# На машине с интернетом: экспорт баз
trivy image --download-db-only
# → Сохраняет базу в ~/.cache/trivy/

# Копирование на air-gapped машину
scp -r ~/.cache/trivy/ user@airgapped:/opt/trivy-db/

# На air-gapped машине: сканирование
trivy image --db-repository /opt/trivy-db/ --skip-db-update my-app:latest
```

## Лучшие практики

1. **Комбинируйте инструменты:** Trivy для быстрого сканирования + Grype для reachability + Syft для SBOM.
2. **EPSS вместо только CVSS:** Используйте EPSS для приоритизации — CVE с EPSS > 0.5 требуют немедленного внимания.
3. **VEX для ложных срабатываний:** Reachability не идеален — подкрепляйте VEX-отчёт для документирования решений.
4. **Offline-режим для air-gapped:** Trivy и osv-scanner работают без интернета при наличии локальной базы.
5. **Интеграция с автоматизацией:** Trivy/Grype/Snyk интегрируются с Renovate для автоматического создания PR при обнаружении CVE.

## Устранение неполадок

| Симптом | Причина | Решение |
|:--- |:--- |:--- |
| Trivy не находит CVE в образе | База устарела | `trivy image --download-db-only` |
| Grype не показывает reachability | Версия < v0.35 | Обновите: `grype --version` |
| osv-scanner не находит lock-файл | Нестандартное имя | Используйте `--lockfile=./my-lockfile` |
| Snyk требует аутентификацию | CLI работает только с аккаунтом | Используйте `snyk auth` или Docker-токен |
| Syft не распознаёт экосистему | Нет плагина | Используйте `cdxgen` как fallback |

## Граничные случаи и ограничения

* **Транзитивные зависимости:** Все SCA-инструменты работают с lock-файлами. Если lock-файл не коммитится, результаты будут неполными.
* **Dynamic dependencies:** Инструменты не отслеживают динамическую загрузку библиотек (dlopen, importlib). Для этого нужен runtime-мониторинг (Falco/Tetragon).
* **Проприетарные библиотеки:** SCA-сканеры не могут проанализировать闭源 библиотеки. Необходимо предоставить SBOM от вендора.
* **Частые обновления баз:** Базы CVE обновляются ежедневно. В air-gapped средах необходимо настроить регулярную синхронизацию.

## Дополнительная информация

### Стандарты и ресурсы

* **Trivy:** <https://github.com/aquasecurity/trivy> — все-в-одном сканер.
* **Grype:** <https://github.com/anchore/grype> — сканер с reachability.
* **Syft:** <https://github.com/anchore/syft> — генератор SBOM.
* **osv-scanner:** <https://github.com/google/osv-scanner> — быстрое сканирование lock-файлов.
* **OSV.dev:** <https://osv.dev/> — агрегатор баз уязвимостей.
* **EPSS:** <https://www.first.org/epss/> — модель предсказания эксплуатации.

### Связанные документы

* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — жизненный цикл SBOM.
* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM, blast radius.
* [Триаж CVE](./cve_triage_workflow.md) — процесс реагирования.
* [Сканирование уязвимостей](../../Docker/Docker_security/vulnerability_scanning.md) — детали Trivy/Grype.
