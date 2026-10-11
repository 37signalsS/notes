# Юнит-тестирование Helm-чартов

## Определения

**Юнит-тестирование Helm-чартов** — это процесс автоматизированной проверки корректности рендеринга шаблонов без необходимости развертывания ресурсов в реальном кластере Kubernetes. В отличие от интеграционных тестов (`helm test`), юнит-тесты проверяют логику шаблонизации: правильность условий (`if/else`), циклов (`range`), формирование меток и соответствие манифестов ожиданиям. Это самый быстрый и дешёвый уровень проверки чарта — типичный прогон 50–200 тестов занимает 1–5 секунд на CI-агенте.

Основным инструментом является плагин **[helm-unittest](https://github.com/helm-unittest/helm-unittest)** (текущая мажорная линейка **0.7.x**, стабильная совместимость с Helm 3.8+ и Helm 4.x). Альтернативы:

- **[helm-template](https://github.com/technosophos/helm-template)** — рендеринг без Tiller, но без встроенной assertion-логики.
- **[chart-testing](https://github.com/helm/chart-testing)** (`ct`) — оркестратор комплексной валидации: lint, unittest, install dry-run, kubeconform. Используется как обёртка поверх helm-unittest для полного цикла.
- **[pytest-helm-charts](https://github.com/codiply/pytest-helm-charts)** — Python-фреймворк, удобен для команд, уже инвестировавших в pytest-инфраструктуру.
- **[terratest](https://terratest.gruntwork.io/)** — Go-фреймворк общего назначения, применим и к Helm.

В этом документе рассматривается **helm-unittest** как канонический инструмент, остальные упоминаются там, где они закрывают пробелы (например, `ct lint` для CI-оркестрации).

---

## Основные концепции

### 1. BDD-подход (Behavior-Driven Development)
Тесты описываются в формате YAML и следуют логике «Дано — Когда — Тогда» (`it`, `set`, `asserts`). Это позволяет техническим специалистам легко читать и поддерживать тестовое покрытие, фокусируясь на ожидаемом поведении манифестов. Структура теста:

- **`suite`** — имя набора (отображается в отчёте, должно быть стабильным для diff'а в PR).
- **`templates`** — список путей к шаблонам, к которым применяются все `tests` набора.
- **`tests[]`** — массив кейсов; каждый кейс содержит `it` (человекопонятное название), `set`/`values` (моки) и `asserts[]`.

### 2. Snapshot-тестирование
Механизм фиксации эталонного вывода шаблона. При первом запуске с флагом `-u` (`--update-snapshot`) создаётся снимок (snapshot) отрендеренного YAML. Все последующие запуски сравнивают новый вывод с эталоном. Это лучший способ обнаружения случайных регрессий в сложных шаблонах.

Ключевые практики:
- Снапшоты **обязаны** быть в VCS вместе с тестом — это даёт PR-review видимость любого изменения рендера.
- Перед коммитом обновлённого снапшота проверяйте `git diff tests/__snapshot__/`, чтобы случайно не зафиксировать регрессию.
- Снапшоты не заменяют точечные ассерты, а дополняют их: для критичных полей (`replicas`, `image.tag`, `resources.limits`) используйте явные `equal`, снапшот — для «всё остальное».

### 3. Изоляция и мокирование (Mocking)
Юнит-тесты работают исключительно с локальным рендерингом (`helm template`). Инструментарий позволяет подменять:

- **`.Values`**: через секцию `set` (точечные переопределения) или `values` (полные values-файлы, абсолютные или glob-пути).
- **`.Release`**: имитация имени релиза, неймспейса, статуса (`installed|uninstalled|superseded`), `IsInstall`/`IsUpgrade`/`IsTest`.
- **`.Capabilities`**: имитация версий Kubernetes и доступных API (важно для адаптивных чартов — см. [scenarios.md](./scenarios.md#3-создание-универсальных-адаптивных-чартов)).
- **`.Files`**: имитация содержимого нешаблонных файлов чарта (для `configmap_files` и `secrets_files`).

Это даёт детерминированный прогон: один и тот же коммит всегда даёт один и тот же результат, что важно для воспроизводимости в CI.

### 4. Тестирование хелперов (Helpers)
Возможность тестирования отдельных именованных шаблонов (`define`) без рендеринга всего файла манифеста — поле `commonTemplate`. Это критично для `library`-чартов, которые не содержат собственных ресурсов, а также для проверки общих функций в прикладных чартах (генерация меток, селекторов, аннотаций).

### 5. DocumentSelector и JsonPath
helm-unittest начиная с v0.6.0 поддерживает **JsonPath** в `path` ассертов: `metadata.annotations["kubernetes.io/ingress.class"]`, `spec.containers[?(@.name=="app")].image`. Это позволяет точно адресовать элементы в multi-doc шаблонах без хрупких числовых индексов.

`documentSelector` фильтрует документы, к которым применяется тест, по JsonPath-выражению:

```yaml
documentSelector:
  path: metadata.name
  value: my-service
```

Это незаменимо для чартов, рендерящих несколько ресурсов (например, один Deployment, две Service, три ConfigMap) — селектор изолирует тест от порядка документов.

### 6. Templated Test Suites (параметризация через чарт)
Когда требуется прогнать один и тот же набор тестов против разных `values.yaml` (например, `dev`/`staging`/`prod`), helm-unittest умеет рендерить сами файлы тестов как **мини-чарт** через `--chart-tests-path <dir>`. В директории лежат `Chart.yaml`, `values.yaml` и шаблоны, генерирующие YAML-тесты. Это устраняет копипасту тестовых файлов.

### 7. Dependent subchart testing
helm-unittest автоматически обнаруживает и прогоняет тесты внутри hard-зависимостей (subcharts в `charts/`). Значения тестов subchart **автоматически скоупируются** префиксом зависимости, что позволяет тестировать override-логику из корневого чарта.

### 8. Уровни проверки чарта (пирамида)
Юнит-тесты — это **нижний** уровень пирамиды. Над ними располагаются:

1. **Юнит-тесты** (helm-unittest) — логика шаблонов, детерминированно, без кластера.
2. **Статическая валидация** (`helm lint`, `values.schema.json`, `kubeconform`) — соответствие API-сервера и схеме.
3. **Dry-run apply** (`helm install --dry-run`, `kubectl apply --server-side --dry-run=server`) — реальная валидация API-сервером.
4. **Интеграционные тесты** (`helm test`) — запуск test-pod'ов в живом кластере.

Юнит-тесты ловят **самые частые** регрессии (опечатки в условиях, неверные ссылки на values, ошибки в циклах) на этапе PR за секунды, не дожидаясь дорогого dry-run.

### 9. Изоляция от окружения (offline / air-gapped CI)
В закрытых контурах (финансы, промышленность, госсектор) установка плагина из `github.com` запрещена. Поддерживаются следующие пути:

- **OCI-установка** из локального реестра: `helm plugin install oci://harbor.corp.local/helm-plugins/unittest:0.7.0`. Преимущества: версионирование, репликация, RBAC.
- **HTTP-установка** из корпоративного артефакт-стора (Nexus, Artifactory) с заранее подготовленным `.tgz` и проверенной контрольной суммой.
- **Docker-образ** `helmunittest/helm-unittest:<helm-ver>-<plugin-ver>` — внутри уже установлены и Helm, и плагин. Запуск: `docker run --rm -v $(pwd):/apps helmunittest/helm-unittest:3.16.4-0.7.0 .` — наиболее воспроизводимый вариант для CI.
- **Pre-baked CI-раннер** (Packer/AMI) с предустановленным плагином из локального зеркала.

### 10. GPG-верификация (Helm 4)
Начиная с Helm 4, при `helm plugin install` из git проверяется GPG-подпись тега репозитория плагина. Для helm-unittest v0.7.0+ при установке из git-URL требуется флаг `--verify=false`, либо предварительный импорт публичного ключа:

```bash
curl -SsL https://github.com/helm-unittest/helm-unittest/raw/refs/heads/main/public-key.asc | gpg --import
gpg --export > ~/.gnupg/pubring.gpg
```

При установке из OCI/http-архива GPG-проверка работает штатно при наличии ключа в `pubring.gpg`.

---

## Практические сценарии

### 1. Установка плагина

**Из публичного GitHub (online):**
```bash
helm plugin install https://github.com/helm-unittest/helm-unittest.git
```

**Из локального OCI-реестра (air-gapped):**
```bash
helm plugin install oci://harbor.corp.local/helm-plugins/unittest:0.7.0
```

**Через Docker (воспроизводимый CI):**
```bash
docker run --rm -v "$(pwd):/apps" helmunittest/helm-unittest:3.16.4-0.7.0 .
# с JUnit-отчётом:
docker run --rm -v "$(pwd):/apps" helmunittest/helm-unittest:3.16.4-0.7.0 \
  -o test-output.xml -t JUnit .
```

**Из локального каталога (разработка плагина):**
```bash
git clone https://github.com/helm-unittest/helm-unittest.git
helm plugin install ./helm-unittest
```

Тесты располагаются в директории `tests/` в корне чарта.
```text
my-chart/
├── Chart.yaml
├── templates/
├── tests/
│   ├── deployment_test.yaml
│   ├── helpers_test.yaml
│   ├── _suite_test.yaml
│   └── __snapshots__/              # Автоматически создаваемые снимки
│       └── deployment_test.yaml.snap
├── values.yaml
└── values.schema.json
```

`.helmignore` должен включать:
```text
tests/
__snapshot__/
```

Чтобы тесты и снапшоты не попадали в собранный `.tgz`-артефакт чарта (это полезно и для безопасности, и для уменьшения размера).

### 2. Мокирование Capabilities, Release, Values

**Capabilities (адаптивная логика API):**
```yaml
suite: test adaptive api versions
templates:
  - ingress.yaml
tests:
  - it: should use networking.k8s.io/v1 for K8s 1.19+
    capabilities:
      major: 1
      minor: 19
      apiVersions:
        - networking.k8s.io/v1
    asserts:
      - equal:
          path: apiVersion
          value: networking.k8s.io/v1
  - it: should fall back to extensions/v1beta1 on K8s 1.16
    capabilities:
      major: 1
      minor: 16
      apiVersions:
        - extensions/v1beta1
    asserts:
      - equal:
          path: apiVersion
          value: extensions/v1beta1
```

**Release (имитация имени и неймспейса):**
```yaml
suite: test release metadata
templates:
  - deployment.yaml
tests:
  - it: should use release name and namespace
    release:
      name: my-release
      namespace: payments
      isInstall: true
    asserts:
      - equal:
          path: metadata.name
          value: my-release-payments
      - equal:
          path: metadata.namespace
          value: payments
```

**Values (через `set` — точечно, через `values` — файлом):**
```yaml
suite: test values overrides
templates:
  - deployment.yaml
tests:
  - it: should respect explicit set overrides
    set:
      image.repository: nginx
      image.tag: "1.27"
      replicaCount: 3
    asserts:
      - equal:
          path: spec.template.spec.containers[0].image
          value: nginx:1.27
      - equal:
          path: spec.replicas
          value: 3
  - it: should load values from staging file
    values:
      - ./tests/fixtures/values-staging.yaml
    asserts:
      - equal:
          path: spec.template.spec.containers[0].image
          value: registry.corp.local/payments:2.4.1
```

### 3. Все виды ассертов

```yaml
suite: comprehensive asserts
templates:
  - configmap.yaml
  - deployment.yaml
tests:
  - it: should demonstrate every common assertion
    set:
      replicaCount: 3
      env:
        - name: LOG_LEVEL
          value: info
    template: deployment.yaml
    documentSelector:
      path: kind
      value: Deployment
    asserts:
      - isKind:                  # проверка Kind ресурса
          of: Deployment
      - isAPIVersion:            # проверка apiVersion
          of: apps/v1
      - equal:                   # точное равенство значения
          path: spec.replicas
          value: 3
      - notEqual:                # значение НЕ равно
          path: spec.replicas
          value: 1
      - exists:                  # поле существует
          path: spec.template.spec.containers[0].resources
      - notExists:               # поля быть не должно
          path: spec.template.spec.hostNetwork
      - matchRegex:              # регулярка по значению
          path: metadata.name
          pattern: ^my-chart-
      - notMatchRegex:
          path: metadata.name
          pattern: --$
      - contains:                # массив/строка содержит
          path: spec.template.spec.containers[0].args
          content: "--log-level=info"
      - notContains:
          path: spec.template.spec.containers[0].args
          content: "--debug"
      - lengthEqual:             # длина массива/строки
          path: spec.template.spec.containers
          count: 1
      - greaterThan:             # числовое сравнение
          path: spec.template.spec.containers[0].resources.requests.memory
          value: 64
      - lessThanOrEqual:
          path: spec.template.spec.containers[0].resources.limits.memory
          value: 512
      - isNotNullOrEmpty:        # строка не пуста
          path: metadata.labels.app\.kubernetes\.io/version
      - isNullOrEmpty:           # поле пусто или отсутствует
          path: spec.template.spec.dnsPolicy
```

**Примечание по JsonPath:** точечные ключи с символами `.` и `/` оборачиваются в кавычки: `metadata.annotations["kubernetes.io/ingress.class"]`, `metadata.labels["app.kubernetes.io/name"]`.

### 4. Snapshot-тестирование

**Полный снапшот манифеста:**
```yaml
suite: test full rendering
templates:
  - deployment.yaml
tests:
  - it: should match the recorded snapshot
    asserts:
      - matchSnapshot: {}
```

**Снапшот поддерева + regex-фильтры:**
```yaml
suite: test pod spec with filtered snapshot
templates:
  - deployment.yaml
tests:
  - it: should match pod spec with dynamic fields ignored
    asserts:
      - matchSnapshot:
          path: spec.template.spec
          matchRegex:
            pattern: .*app.*
          notMatchRegex:
            pattern: .*bcde.*
```

**Workflow:**
```bash
# 1. Первый запуск — фиксация эталона
helm unittest -u ./my-chart
# создаёт tests/__snapshots__/*_test.yaml.snap

# 2. Последующие запуски — сравнение
helm unittest ./my-chart

# 3. В CI — failfast, без обновления снапшотов
helm unittest --failfast ./my-chart
```

Файлы `__snapshots__/*.snap` коммитятся в VCS. Любое изменение снапшота в PR требует code review: `git diff tests/__snapshots__/`.

### 5. Тестирование Named Templates (Helpers)

```yaml
suite: test helpers
templates: []                  # пустой список — тестируем только хелперы
tests:
  - it: should render standard labels correctly
    commonTemplate: mychart.labels
    set:
      chart.name: mychart
      chart.version: 1.2.3
    asserts:
      - matchRegex:
          path: app\.kubernetes\.io/name
          pattern: ^mychart$
      - matchRegex:
          path: app\.kubernetes\.io/version
          pattern: ^1\.2\.3$
  - it: should pick the right selector component
    commonTemplate: mychart.selectorLabels
    set:
      chart.name: mychart
    asserts:
      - equal:
          path: app\.kubernetes\.io/name
          value: mychart
      - notExists:
          path: app\.kubernetes\.io/version
```

Особенно полезно для **library-чартов** ([helm_dependencies_and_library_charts.md](../helm_dependencies_and_library_charts.md)): библиотечный чарт не имеет собственных ресурсов, поэтому единственный способ его покрыть тестами — `commonTemplate`.

### 6. Тестирование subchart-ов

```yaml
# В tests/postgresql_subchart_test.yaml корневого чарта
suite: test subchart override
templates:
  - charts/postgresql/templates/deployment.yaml
tests:
  - it: should respect postgresql replicaCount override
    set:
      postgresql.replicaCount: 3
    asserts:
      - equal:
          path: spec.replicas
          value: 3
```

helm-unittest по умолчанию рекурсивно прогоняет тесты **внутри** subcharts (`--with-subchart=true`). Чтобы отключить — `helm unittest --with-subchart=false ./my-chart`.

### 7. Templated Test Suites (параметризация)

Структура:
```text
my-chart/
├── Chart.yaml
├── tests-chart/                       # директория мини-чарта с тестами
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│       └── per_env_snapshots.yaml     # шаблон, генерирующий наборы тестов
├── values.yaml
└── templates/
    └── deployment.yaml
```

`tests-chart/templates/per_env_snapshots.yaml`:
```yaml
{{- range .Values.environments }}
---
suite: snapshot for {{ .name }}
templates:
  - deployment.yaml
values:
  - ../values/{{ .name }}.yaml
tests:
  - it: should render correctly for {{ .name }}
    asserts:
      - matchSnapshot: {}
{{- end }}
```

`tests-chart/values.yaml`:
```yaml
environments:
  - name: dev
  - name: staging
  - name: prod
```

Запуск:
```bash
helm unittest --chart-tests-path tests-chart ./my-chart
```

**Важно:** папка `tests-chart` должна быть в `.helmignore` основного чарта и не должна пересекаться с обычными тестами. Директории `__snapshot__/*` также игнорируются основным чартом (см. NOTE 3 в [документации helm-unittest](https://github.com/helm-unittest/helm-unittest/blob/main/DOCUMENT.md)).

### 8. DocumentSelector в multi-doc шаблонах

```yaml
suite: multi-doc test
templates:
  - service.yaml            # содержит 2 Service + 1 Headless Service
tests:
  - it: should set correct type for headless service
    documentSelector:
      path: metadata.name
      value: my-chart-headless
    asserts:
      - equal:
          path: spec.clusterIP
          value: None
  - it: should keep cluster IP for primary service
    documentSelector:
      path: metadata.name
      value: my-chart
    asserts:
      - notEqual:
          path: spec.clusterIP
          value: None
```

Без `documentSelector` пришлось бы использовать хрупкий `documentIndex: 0/1/2`, ломающийся при изменении порядка.

### 9. Полезные CLI-флаги

```bash
# Строгий парсинг тестов (типизация, неизвестные поля)
helm unittest --strict ./my-chart

# Прервать на первой ошибке (быстрый fail в CI)
helm unittest --failfast ./my-chart

# Включить логи плагина (отладка)
helm unittest --debugPlugin ./my-chart

# Пропустить валидацию values.schema.json (только для юнит-тестов)
helm unittest --skip-schema-validation ./my-chart

# Свой glob-паттерн для тестовых файлов
helm unittest -f 'tests/integration/**/*.yaml' ./my-chart

# Запустить только тесты с конкретным suite
helm unittest -f 'tests/deployment_test.yaml' ./my-chart

# Включить тесты внутри subcharts (по умолчанию true)
helm unittest --with-subchart=true ./my-chart

# Цветной вывод (в CI принудительно выключить)
helm unittest --color=false ./my-chart

# Генерация JUnit-отчёта для GitLab/GitHub
helm unittest -o report.xml -t JUnit ./my-chart
```

Форматы отчётов: `JUnit`, `NUnit`, `XUnit` (по умолчанию). Для GitLab — `JUnit`, для Jenkins — `JUnit` или `XUnit`, для Azure DevOps — `JUnit`.

### 10. Запуск и интеграция в CI/CD

**GitLab CI (offline-friendly):**
```yaml
stages:
  - validate
  - test
  - package

variables:
  HELM_IMAGE: "harbor.corp.local/devops/helm:3.16.4"

helm-lint:
  stage: validate
  image: ${HELM_IMAGE}
  script:
    - helm lint ./charts/*

helm-unittest:
  stage: test
  image: helmunittest/helm-unittest:3.16.4-0.7.0
  script:
    - helm unittest --strict --failfast -o report.xml -t JUnit ./charts/*
  artifacts:
    when: always
    reports:
      junit: report.xml
    paths:
      - report.xml
    expire_in: 7 days

chart-testing:
  stage: test
  image: ${HELM_IMAGE}
  script:
    - ct lint --config ct.yaml
    - ct install --config ct.yaml --debug
```

**GitHub Actions:**
```yaml
name: helm-unittest
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run helm-unittest
        uses: addictedtoctrl/helm-unittest-action@v1
        with:
          chart-path: charts/myservice
          output-type: JUnit
          output-file: report.xml
      - name: Publish Test Results
        if: always()
        uses: mikepenz/action-junit-report@v6
        with:
          report_paths: '**/report.xml'
```

**Jenkins (declarative pipeline):**
```groovy
pipeline {
  agent {
    docker {
      image 'helmunittest/helm-unittest:3.16.4-0.7.0'
      args '-v $WORKSPACE:/apps'
    }
  }
  stages {
    stage('Unittest') {
      steps {
        sh 'helm unittest --strict --failfast -o report.xml -t JUnit .'
        junit 'report.xml'
      }
    }
  }
}
```

**Drone CI:**
```yaml
kind: pipeline
name: helm-unittest
steps:
  - name: unittest
    image: helmunittest/helm-unittest:3.16.4-0.7.0
    commands:
      - helm unittest --strict --failfast -o report.xml -t JUnit ./charts/*
  - name: publish
    image: plugins/junit
    settings:
      report: report.xml
    when:
      always: true
```

**Tekton:**
```yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: helm-unittest
spec:
  steps:
    - name: run
      image: helmunittest/helm-unittest:3.16.4-0.7.0
      script: |
        #!/usr/bin/env bash
        set -e
        helm unittest --strict --failfast -o $(results.report.path) -t JUnit .
    workspaces:
      - name: source
        mountPath: /source
  results:
    - name: report
      description: JUnit report
```

### 11. Pre-commit hooks (ранняя валидация)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gruntwork-io/pre-commit
    rev: v0.1.25
    hooks:
      - id: helmlint
  - repo: local
    hooks:
      - id: helm-unittest
        name: helm-unittest
        description: Run helm-unittest against changed charts
        entry: bash -c 'helm unittest ./charts/$1'
        language: system
        files: '^charts/.+/templates/.+\.yaml$'
        pass_filenames: true
```

Pre-commit ловит ошибки шаблонов **до** push в remote, экономя CI-минуты. Однако помните: pre-commit запускает `helm unittest` локально и требует установленного Helm и плагина у каждого разработчика.

### 12. Интеграция с chart-testing (ct)

`ct` — стандарт де-факто для комплексной валидации чартов в CI. Он объединяет lint, unittest, install dry-run и kubeconform.

`ct.yaml`:
```yaml
chart-dirs:
  - charts
chart-repos:
  - bitnami=https://charts.bitnami.com/bitnami
validate-maintainers: false
chart-yaml-schema: https://raw.githubusercontent.com/helm/chart-testing/main/etc/chart_schema.yaml
lint-conf: ct-lint.yaml
```

```bash
# Только линтинг (lint + unittest + values.schema)
ct lint --config ct.yaml

# Полный цикл (lint + install dry-run в kind/eks/...)
ct install --config ct.yaml

# Только helm-unittest
ct lint --config ct.yaml --lint-cmd "helm unittest --strict --failfast {}"
```

`ct` запускает helm-unittest автоматически как часть `ct lint`, если в чарте есть директория `tests/`. Кастомный `lint-cmd` позволяет переопределить команду.

### 13. Интеграция с helm diff (pre-upgrade safety)

```bash
# Перед upgrade — посмотреть, что изменится
helm diff upgrade my-release ./my-chart -f values-prod.yaml

# Запустить unittest, чтобы убедиться, что новые шаблоны не сломаны
helm unittest --strict ./my-chart

# Только после успешного diff+unittest — реальный upgrade
helm upgrade my-release ./my-chart -f values-prod.yaml
```

В CI это выглядит как job `helm-diff`, который **всегда** падает, если diff не пустой при изменении версии чарта (защита от случайного force-upgrade).

### 14. Миграция с helm-unittest 0.6.x → 0.7.x

Ключевые изменения:

- **JsonPath по умолчанию** в `path`. Старые выражения с `\.` для экранирования точек в ключах ломаются: `metadata.labels.app\.kubernetes\.io/name` → `metadata.labels["app.kubernetes.io/name"]`. Проверьте все тестовые файлы через `helm unittest --strict`.
- **`documentSelector`** — новый способ адресации документов. Рекомендуется для multi-doc чартов вместо `documentIndex`.
- **`--strict`** — теперь выявляет опечатки в assertion-именах и неизвестные поля тестов. Включите в CI как можно раньше.
- **Формат отчёта по умолчанию** изменён на `XUnit` (был `JUnit`). Проверьте парсеры отчётов в CI.

Пошаговый план:
1. Обновите плагин: `helm plugin install --version 0.7.0 ...`
2. Запустите `helm unittest --strict ./my-chart` — соберите список упавших тестов.
3. Замените экранированные точки в `path` на JsonPath-кавычки.
4. Замените `documentIndex` на `documentSelector` где возможно.
5. Закоммитьте изменения тестов отдельным PR с меткой `unittest-0.7-migration`.

### 15. Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| `failed to load chart: validation: chart.metadata.apiVersion is required` | Чарт использует `apiVersion: v1` | Переведите чарт на `apiVersion: v2` (Chart.yaml) |
| `test file does not exist` | Тесты вне `tests/` | Переместите в `tests/` или используйте `-f 'pattern/**/*_test.yaml'` |
| `snapshot not found, please use -u to update` | Снапшот ещё не создан | `helm unittest -u ./my-chart` локально, закоммитьте `__snapshots__/` |
| Тест проходит локально, падает в CI | Разные версии Helm | Зафиксируйте версии через Docker-образ или `helm version` в pre-job |
| `failed parsing testsuite` после обновления 0.6→0.7 | Старый синтаксис `path` | Запустите с `--strict`, замените `\.` на `["..."]` |
| `helm plugin install` падает на git-URL в Helm 4 | GPG-проверка | `--verify=false` или импорт публичного ключа плагина |
| Тесты внутри subchart игнорируются | `--with-subchart=false` | Уберите флаг или поставьте `true` |
| `isKind` не находит ресурс | Multi-doc шаблон | Добавьте `documentSelector` или `documentIndex` |
| `values.schema.json` блокирует тест | Schema не пускает тестовые значения | Временно `--skip-schema-validation` или ослабьте schema |
| Snapshot diff после изменения шаблона | Шаблон действительно изменился | Проверьте `git diff` руками, затем `helm unittest -u` |

### 16. Ограничения и границы применимости

- **Юнит-тесты не заменяют dry-run** в реальном кластере. Шаблон может быть синтаксически корректен, но не пройти admission webhook (OPA, Kyverno) или отсутствующий CRD. Обязателен второй уровень валидации через `ct install` или `helm install --dry-run=server`.
- **Не валидируют runtime-логику**: правильность readiness-проб, корректность volume mounts, работоспособность образа — это зона интеграционных тестов ([helm_hooks_and_tests.md](../helm_hooks_and_tests.md)).
- **Helm unit ≠ Helm test**: `helm test` запускает test-pod внутри кластера, требует kubectl-доступа и времени на развёртывание. Юнит-тесты — статика, всегда 1–5 секунд.
- **Snapshot-тесты хрупки при больших рефакторингах**. Любое изменение условной логики «зацепит» десятки снапшотов. Точечные ассерты более устойчивы к рефакторингу, хотя требуют больше кода.
- **Templated Test Suites** — рендерят чарт внутри тестового прогона, что увеличивает время. Для 10+ окружений может стать узким местом. Альтернатива — параметризация через shell-цикл.
- **Тесты не покрывают helm-хуки** в полном объёме: `helm-unittest` рендерит хуки как обычные манифесты, но не запускает их lifecycle (pre-install, post-upgrade). Для E2E хуков — `helm test` или `ct install`.

---

## Дополнительная информация

- **[Плагины Helm](../helm_plugins.md)** — обзор расширений CLI, в том числе helm-unittest.
- **[Хуки и тестирование чартов](../helm_hooks_and_tests.md)** — интеграционное тестирование (`helm test`) в реальном кластере.
- **[Шаблонизация в Helm](../helm_templating.md)** — синтаксис Go Templates, на котором основан рендер под тестами.
- **[Библиотечные чарты](../helm_dependencies_and_library_charts.md)** — обязательный контекст для тестирования через `commonTemplate`.
- **[Проверка версий API и возможностей](./scenarios.md#3-создание-универсальных-адаптивных-чартов)** — когда и зачем нужно мокировать `.Capabilities`.
- **[Безопасность и лучшие практики](./security_best_practices.md)** — соседний уровень валидации: `helm lint`, `values.schema.json`, `kubeconform`.
- **[chart-testing (ct)](https://github.com/helm/chart-testing)** — оркестратор полного цикла валидации чартов.
- **[helm-unittest DOCUMENT.md](https://github.com/helm-unittest/helm-unittest/blob/main/DOCUMENT.md)** — полный справочник по assertion-API.
