# Trivy + SonarQube: сканирование безопасности в пайплайне GitLab CI

**Актуально для:** GitLab 17.x–19.x, Trivy 0.76.0, SonarQube Server 2026.5 LTA / 2026.1 LTA / Community Build 26.x, SonarScanner CLI 12.x

## Определения

**Trivy** — универсальный сканер безопасности от Aqua Security. Сканирует уязвимости, секреты, ошибки конфигурации IaC и избыточные RBAC-права в контейнерных образах, файловых системах, Git-репозиториях и Kubernetes-кластерах.

**Trivy fs** — режим сканирования файловой системы/репозитория. Используется для проверки IaC-манифестов, Dockerfile и Helm-чартов на этапе CI, до деплоя.

**Trivy k8s** — режим сканирования живого Kubernetes-кластера. Проверяет уже задеплоенные образы, RBAC-права и конфигурацию в рантайме.

**Trivy config** — режим сканирования отдельных IaC-файлов (Terraform, Dockerfile, Kubernetes-манифесты, Helm-чарты) на ошибки конфигурации. Является узконаправленным подмножеством `trivy fs --scanners misconfig`.

**SARIF (Static Analysis Results Interchange Format)** — стандарт OASIS версии 2.1.0 для обмена результатами статического анализа. SonarQube принимает SARIF-отчёты через параметр `sonar.sarifReportPaths`.

**Внешние issue SonarQube (Generic Issue Import Format)** — формат JSON для импорта issue-ов из сторонних сканеров. SonarQube принимает такие отчёты через параметр `sonar.externalIssuesReportPaths`. Начиная с SonarQube 10.3, формат требует массив `rules` наряду с массивом `issues`, а в каждом правиле — массив `impacts` с `softwareQuality` и `severity` (обязательно для MQR Mode).

**IaC (Infrastructure as Code)** — управление и подготовка инфраструктуры с помощью манифестов и конфигурационных файлов.

**RBAC (Role-Based Access Control)** — управление доступом на основе ролей в Kubernetes.

## Архитектура: зачем два сканирования

Инфра-репозиторий запускает два вида Trivy-сканирования: файловой системы (обнаружение ошибок конфигурации IaC в репозитории) и живого Kubernetes-кластера. Результаты попадают в SonarQube как внешние issue.

| Тип сканирования | Что находит | Когда запускается |
|---|---|---|
| `trivy fs` | Секреты в git, уязвимые теги образов в HelmRelease values, ошибки в K8s-манифестах | На этапе CI, до деплоя |
| `trivy k8s` | Уязвимости задеплоенных образов, избыточные RBAC-права, ошибки конфигурации в рантайме | После деплоя в кластер |

Сканирование файловой системы находит проблемы в git. Сканирование кластера проверяет то, что уже работает в production — например, образы, задеплоенные до публикации CVE.

## Предварительные требования

| Компонент | Требования |
|---|---|
| **GitLab** | 17.x–19.x с GitLab Runner (Docker executor) |
| **SonarQube** | Server 2026.x (LTA) либо Community Build 26.x с включённой поддержкой SARIF (`sonar.sarifReportPaths`) и Generic Issue Import (`sonar.externalIssuesReportPaths`) |
| **Trivy** | Образ `aquasec/trivy:0.76.0` в GitLab CI |
| **kubeconfig** | CI/CD-переменная `KUBECONFIG` с доступом к целевому кластеру (`infra-k8s` context) |
| **Python** | 3.12+ в джобе конвертации (для `trivy-k8s-json-to-sonar.py`) |
| **CI/CD Variables** | `SONAR_HOST_URL`, `SONAR_TOKEN`, `KUBECONFIG` — protected + masked |

## Конфигурация пайплайна

Стадия безопасности запускается вручную. Все джобы безопасности имеют `needs: [start:security]` — запускаются только после ручного триггера.

```yaml
start:security:
  stage: validate:security
  when: manual
  allow_failure: true
  script:
    - echo "Security checks started"
```

### Сканирование файловой системы (trivy fs)

Джоб сканирует файловую систему репозитория на наличие уязвимостей, секретов и ошибок конфигурации IaC. Результат в формате SARIF импортируется в SonarQube через `sonar.sarifReportPaths`.

```yaml
trivy:scan-repo:
  image: aquasec/trivy:0.76.0
  needs: [start:security]
  variables:
    TRIVY_CACHE_DIR: "${CI_PROJECT_DIR}/.trivy-cache"
  cache:
    key: trivy-db
    paths: [.trivy-cache/]
    policy: pull-push
  script:
    - |
      trivy fs \
        --cache-dir "${TRIVY_CACHE_DIR}" \
        --scanners vuln,secret,misconfig \
        --format sarif \
        --output trivy.sarif \
        --severity HIGH,CRITICAL \
        --exit-code 0 \
        .
  artifacts:
    paths: [trivy.sarif]
```

**Параметры:**

| Параметр | Значение | Описание |
|---|---|---|
| `--scanners vuln,secret,misconfig` | vuln,secret,misconfig | Явный выбор сканеров: уязвимости (vuln), секреты (secret), ошибки конфигурации IaC (misconfig). По умолчанию в `trivy fs` включены только `vuln,secret`; `misconfig` добавляется для проверки Kubernetes-манифестов, Dockerfile и Helm-чартов |
| `--format sarif` | SARIF 2.1.0 | Формат отчёта, нативно поддерживается SonarQube |
| `--exit-code 0` | 0 | Джоб не падает при наличии находок — цель видимость в SonarQube, а не блокировка |
| `--severity HIGH,CRITICAL` | HIGH,CRITICAL | Фильтр по severity |
| `--cache-dir` | `${TRIVY_CACHE_DIR}` | Каталог кэша базы уязвимостей |

### Сканирование Kubernetes-кластера (trivy k8s)

Джоб сканирует живой Kubernetes-кластер на уязвимости образов, RBAC и конфигурацию в рантайме. Поддерживаемые форматы вывода: `table`, `json`, `cyclonedx` — SARIF не поддерживается напрямую. Поэтому результат в JSON конвертируется в формат внешних issue SonarQube.

```yaml
trivy:k8s:
  image: aquasec/trivy:0.76.0
  needs: [start:security]
  variables:
    TRIVY_CACHE_DIR: "${CI_PROJECT_DIR}/.trivy-cache"
  cache:
    key: trivy-db
    paths: [.trivy-cache/]
    policy: pull-push
  script:
    - |
      trivy k8s \
        --cache-dir "${TRIVY_CACHE_DIR}" \
        --format json \
        --output "trivy-k8s-infra.json" \
        --severity HIGH,CRITICAL \
        all \
        infra-k8s
  artifacts:
    paths: ["trivy-k8s-*.json"]
```

**Параметры:**

| Параметр | Значение | Описание |
|---|---|---|
| `--format json` | JSON | Формат отчёта (SARIF не поддерживается для `trivy k8s`) |
| `--severity HIGH,CRITICAL` | HIGH,CRITICAL | Фильтр по severity |
| `infra-k8s` (positional) | kubeconfig context | Контекст кластера, передаётся позиционным аргументом после `all` |
| `all` | — | Сканировать все ресурсы (vuln + misconfig + secret + rbac по умолчанию) |

> **Примечание:** В Trivy 0.76.0 контекст кластера передаётся позиционным аргументом (`trivy k8s all infra-k8s`), а не флагом `--context`. Флаг `--context` был удалён в пользу позиционного аргумента, который является документированным стандартом. Для `trivy k8s all` по умолчанию включены все сканеры: `vuln,misconfig,secret,rbac`.

### Конвертация JSON → внешние issue SonarQube

Так как `trivy k8s` не генерирует SARIF, результаты в JSON конвертируются в формат внешних issue SonarQube с помощью Python-скрипта.

```yaml
trivy:convert-k8s:
  needs: [trivy:k8s]
  script:
    - |
      for source_file in trivy-k8s-*.json; do
        target_env="${source_file#trivy-k8s-}"
        target_env="${target_env%.json}"
        python3 scripts/trivy-k8s-json-to-sonar.py \
          "$source_file" \
          "trivy-k8s-${target_env}-sonar.json"
      done
```

Скрипт `trivy-k8s-json-to-sonar.py` преобразует находки Trivy в формат внешних issue SonarQube. Для SonarQube 10.3+ (включая 2026.x) формат требует массив `rules` наряду с массивом `issues`, а в каждом правиле — массив `impacts` с `softwareQuality` и `severity` (требуется для MQR Mode):

```json
{
  "rules": [
    {
      "id": "CVE-2024-1234",
      "name": "CVE-2024-1234",
      "description": "Уязвимость в компоненте nginx",
      "engineId": "trivy",
      "cleanCodeAttribute": "FORMATTED",
      "impacts": [
        {
          "softwareQuality": "SECURITY",
          "severity": "HIGH"
        }
      ]
    }
  ],
  "issues": [
    {
      "ruleId": "CVE-2024-1234",
      "effortMinutes": 0,
      "primaryLocation": {
        "message": "nginx:1.25.3 — известная RCE-уязвимость",
        "filePath": "fluxcd/projects/dev/kustomization/hub/patches/nginx.yaml",
        "textRange": {
          "startLine": 3,
          "startColumn": 8,
          "endLine": 3,
          "endColumn": 20
        }
      }
    }
  ]
}
```

| Поле | Где находится | Описание |
|---|---|---|
| `rules` | Верхний уровень | Массив правил (требуется для SonarQube 10.3+) |
| `issues` | Верхний уровень | Массив issue-ов |
| `engineId` | `rules[].engineId` | Идентификатор сканера (trivy) |
| `cleanCodeAttribute` | `rules[].cleanCodeAttribute` | Атрибут качества кода: `FORMATTED`, `CONVENTIONAL`, `IDENTIFIABLE`, `CLEAR`, `LOGICAL`, `COMPLETE`, `EFFICIENT`, `FOCUSED`, `DISTINCT`, `MODULAR`, `TESTED`, `LAWFUL`, `TRUSTWORTHY`, `RESPECTFUL` |
| `impacts` | `rules[].impacts[]` | Массив влияний (обязательно для MQR Mode). Каждый объект: `softwareQuality` — `MAINTAINABILITY`, `RELIABILITY`, `SECURITY`; `severity` — `HIGH`, `MEDIUM`, `LOW` |
| `ruleId` | `issues[].ruleId` | Ссылка на правило из массива `rules` |
| `filePath` | `issues[].primaryLocation.filePath` | Путь к файлу в репозитории |
| `textRange` | `issues[].primaryLocation.textRange` | Диапазон строк (рекомендуется для точной привязки) |

> **Важно:** Для SonarQube 10.8+ (включая 2026.x) массив `rules` обязателен, а внутри каждого правила — массив `impacts` с `softwareQuality` и `severity`. Без `impacts` issue отображаются с `Maintainability: Medium` в MQR Mode.

### Импорт в SonarQube

Джоб запускает SonarScanner, который отправляет SARIF-отчёт (от `trivy fs`) и JSON-отчёты внешних issue (от `trivy k8s`) в SonarQube.

```yaml
sonarqube:trivy:
  image: sonarsource/sonar-scanner-cli:12
  needs: [trivy:scan-repo, trivy:convert-k8s]
  variables:
    GIT_STRATEGY: clone
    GIT_DEPTH: "0"
  script:
    - |
      sonar_k8s_reports=$(ls trivy-k8s-*-sonar.json 2>/dev/null | tr '\n' ',' | sed 's/,$//')
      sonar-scanner \
        -Dsonar.host.url=${SONAR_HOST_URL} \
        -Dsonar.token=${SONAR_TOKEN} \
        -Dsonar.projectKey=trivy_infra \
        -Dsonar.sources=. \
        -Dsonar.python.version=3.12 \
        -Dsonar.sarifReportPaths=trivy.sarif \
        ${sonar_k8s_reports:+-Dsonar.externalIssuesReportPaths=${sonar_k8s_reports}}
```

**Параметры:**

| Параметр | Описание |
|---|---|
| `GIT_DEPTH: "0"` | Полная история git — SonarQube использует git blame для привязки находок к коммитам и авторам |
| `sonar.sarifReportPaths` | Путь к SARIF-файлу от `trivy fs` |
| `sonar.externalIssuesReportPaths` | Путь к JSON-файлу(ам) внешних issue от `trivy k8s` |
| `${sonar_k8s_reports:+...}` | Флаг добавляется только если переменная непустая (bash parameter expansion) |

### Кэш базы данных Trivy

```yaml
cache:
  key: trivy-db
  paths: [.trivy-cache/]
  policy: pull-push
```

База уязвимостей занимает ~300 МБ. Без кэша каждое сканирование скачивает её с GitHub — несколько минут на медленном соединении.

### Уведомление

```yaml
notify:security:
  when: on_success
  needs: [sonarqube:trivy]
```

Отправляет сообщение в Telegram и Mattermost с прямой ссылкой на дашборд SonarQube.

## Валидация и проверка

**Ожидаемые артефакты после выполнения пайплайна:**

| Артефакт | Источник | Проверка |
|---|---|---|
| `trivy.sarif` | `trivy:scan-repo` | Файл существует и содержит `runs` с `results` |
| `trivy-k8s-{env}-sonar.json` | `trivy:convert-k8s` | JSON с массивами `rules` и `issues` |

**Проверка импорта в SonarQube:**

```bash
# 1. SARIF-отчёт импортирован (проверка через API)
curl -s -u "$SONAR_TOKEN:" \
  "$SONAR_HOST_URL/api/project_analyses/search?project=trivy_infra&ps=1" \
  | jq '.analyses[0].warnings[]? | select(.key == "sarif")'

# 2. Внешние issue импортированы
curl -s -u "$SONAR_TOKEN:" \
  "$SONAR_HOST_URL/api/issues/search?componentKeys=trivy_infra&types=VULNERABILITY" \
  | jq '.total'

# → Ожидаемый результат: total > 0 при наличии уязвимостей HIGH/CRITICAL
```

**Проверка в UI SonarQube:**
1. Проект `trivy_infra` появляется в списке после первого `sonarqube:trivy` run.
2. На вкладке **Measures → Security** видны импортированные issue из Trivy (SARIF) и внешние issue (Generic Import Format).
3. Все issue имеют `ruleId`, соответствующий CVE-ID (например, `CVE-2024-1234`).

**Ожидаемые результаты:**

| Сценарий | Критерий успеха |
|---|---|
| `trivy:scan-repo` | SARIF-файл сгенерирован, job завершается с `exit code 0` |
| `trivy:k8s` | JSON-файлы с результатами сканирования кластера созданы |
| `trivy:convert-k8s` | JSON-файлы в формате Generic Issue Import для каждого окружения |
| `sonarqube:trivy` | SonarQube принимает SARIF + external issues, job завершается успешно |
| `notify:security` | Уведомление с дашбордом отправлено в Telegram/Mattermost |

## Команды

| Команда | Описание | Пример |
|---|---|---|
| `trivy fs` | Сканирование файловой системы/репозитория | `trivy fs --scanners vuln,secret,misconfig --format sarif -o report.sarif --severity HIGH,CRITICAL --exit-code 0 .` |
| `trivy config` | Сканирование отдельных IaC-манифестов (Terraform, Dockerfile, K8s) | `trivy config --severity HIGH,CRITICAL --format sarif -o report.sarif ./helm/` |
| `trivy k8s` | Сканирование Kubernetes-кластера | `trivy k8s all <context> --format json -o report.json --severity HIGH,CRITICAL` |
| `trivy k8s ... --timeout` | Увеличение таймаута для больших кластеров | `trivy k8s all <context> --timeout 30m ...` |
| `trivy db` | Управление базой уязвимостей (скачивание/обновление) | `trivy db download --db-repository public.ecr.aws/aquasecurity/trivy-db:2` |
| `sonar-scanner` | Импорт отчётов в SonarQube | `sonar-scanner -Dsonar.sarifReportPaths=report.sarif -Dsonar.externalIssuesReportPaths=ext-issues.json` |

## Частые проблемы

| Проблема | Причина | Решение |
|---|---|---|
| `TOOMANYREQUESTS` | Trivy превышает лимит GitHub API при скачивании базы уязвимостей | Использовать GitLab CI cache или зеркало Trivy: `--db-repository public.ecr.aws/aquasecurity/trivy-db:2` |
| Нет информации об авторе в SonarQube | `GIT_DEPTH` не равен `0` — shallow clone ломает git blame | Установить `GIT_DEPTH: "0"` для полной истории |
| `trivy k8s` завершается по таймауту | Стандартные 5 минут не хватает на кластеры с 20+ namespaces | Добавить `--timeout 30m` (наследуется от родительской команды Trivy) |
| SARIF-импорт не работает | Версия SonarQube не поддерживает SARIF (требуется v9.9+) | Убедиться, что версия SonarQube Server >= 9.9; в KB — 2026.x |
| External issues не импортируются | JSON не соответствует формату Generic Issue Import Format (SonarQube 10.3+) | Проверить структуру JSON: массивы `rules` и `issues`, обязательные поля `id`, `engineId`, `ruleId`, `cleanCodeAttribute`, `impacts[].softwareQuality`, `impacts[].severity`, `filePath`, `message` |

## Лучшие практики

- **Версии образов:** фиксируйте версии Trivy и SonarScanner (не используйте `latest`). Trivy 0.71.0+ содержит исправление CVE-2026-54448 (DoS при обработке Helm-архивов); версии < 0.71.0 уязвимы.
- **Кэширование:** используйте GitLab cache для базы Trivy (`key: trivy-db`, `policy: pull-push`) — экономит ~300 МБ трафика и минуты загрузки на каждом сканировании.
- **Exit code:** `--exit-code 0` для видимости в SonarQube без блокировки пайплайна. Для жёсткой блокировки используйте `--exit-code 1`.
- **`--scanners`:** явно указывайте сканеры через `--scanners vuln,secret,misconfig` — по умолчанию `trivy fs` включает только `vuln,secret`, пропуская проверку конфигурации IaC.
- **`--ignore-unfixed`:** используйте для `trivy fs` и `trivy k8s`, чтобы скрыть уязвимости без доступных патчей — только те CVE, для которых есть `fixedVersion`, попадают в отчёт.
- **`.trivyignore`:** коммитьте `.trivyignore` рядом с Dockerfile для подавления ложных срабатываний с указанием CVE и причины (см. пример ниже).
- **`--db-repository`:** в air-gapped или rate-limited средах указывайте зеркало Trivy DB: `--db-repository public.ecr.aws/aquasecurity/trivy-db:2`. Флаг принимает несколько значений для fallback.
- **Полная история git:** всегда используйте `GIT_DEPTH: "0"` в джобе SonarQube — иначе находки остаются без автора из-за поломанного git blame.
- **Conditional flags:** используйте bash parameter expansion `${var:+-Dflag=${var}}` для условного добавления флагов SonarScanner.

```text
# .trivyignore — подавление false-positive CVE с объяснением
# CVE-2024-12345: базовый образ alpine:3.19, патч недоступен через apk;
#                 подтверждено архитектором как accepted risk (2026-09-15)
CVE-2024-12345
```

## Дополнительная информация

- [Trivy Documentation](https://trivy.dev/docs/latest/)
- [SonarQube: импорт SARIF-отчётов](https://docs.sonarsource.com/sonarqube-server/analyzing-source-code/importing-external-issues/importing-issues-from-sarif-reports)
- [SonarQube: Generic Issue Import Format](https://docs.sonarsource.com/sonarqube-server/analyzing-source-code/importing-external-issues/generic-issue-import-format)
- [Trivy Operator: непрерывное сканирование в Kubernetes](../../../Kubernetes/Security/trivy_operator.md)
- [Безопасный релиз в GitLab CI/CD: SAST, DAST, SCA, сканирование образов, SBOM и security gates](../../DevSecOps/secure_release_pipeline.md)
- [Policy-as-Code в GitLab CI/CD](../Advanced/policy_as_code.md)
- [GitLab CI/CD + SonarQube интеграция](sonarqube_integration.md)
- [SonarQube (Tools)](../../Tools/sonarqube.md)
- [Trivy fs CLI reference](https://trivy.dev/docs/latest/references/configuration/cli/trivy_filesystem/)
- [Trivy k8s CLI reference](https://trivy.dev/docs/latest/references/configuration/cli/trivy_kubernetes/)
