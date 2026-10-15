# Юнит-тестирование Helm-чартов

**Актуально для:** Helm 3.22 (support mode, EOL 2026-07-08), Helm 4.1+ (stable); helm-unittest 1.2.x

## Определения

**Юнит-тестирование Helm-чартов** — это процесс автоматизированной проверки корректности рендеринга шаблонов без необходимости развертывания ресурсов в реальном кластере Kubernetes. В отличие от интеграционных тестов (`helm test`), юнит-тесты проверяют логику шаблонизации: правильность условий (`if/else`), циклов (`range`), формирование меток и соответствие манифестов ожиданиям. Это самый быстрый и дешёвый уровень проверки чарта — типичный прогон 50–200 тестов занимает 1–5 секунд на CI-агенте.

Основным инструментом является плагин **[helm-unittest](https://github.com/helm-unittest/helm-unittest)** (текущая мажорная линейка **1.2.x**, стабильная совместимость с Helm 3.9+ и Helm 4.x). Альтернативы:

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
- **`.Release`**: имитация имени релиза, неймспейса, статуса (`installed|uninstalled|superseded`), `upgrade` (флаг апгрейда).
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

- **OCI-установка** из локального реестра: `helm plugin install oci://harbor.corp.local/helm-plugins/unittest:1.2.1`. Преимущества: версионирование, репликация, RBAC.
- **HTTP-установка** из корпоративного артефакт-стора (Nexus, Artifactory) с заранее подготовленным `.tgz` и проверенной контрольной суммой.
- **Docker-образ** `helmunittest/helm-unittest:<helm-ver>-<plugin-ver>` — внутри уже установлены и Helm, и плагин. Запуск: `docker run --rm -v $(pwd):/apps helmunittest/helm-unittest:3.22.0-1.2.1 .` — наиболее воспроизводимый вариант для CI.
- **Pre-baked CI-раннер** (Packer/AMI) с предустановленным плагином из локального зеркала.

### 10. GPG-верификация (Helm 4)
Начиная с Helm 4, при `helm plugin install` из git проверяется GPG-подпись тега репозитория плагина. При установке helm-unittest v1.2.x из git-URL на Helm 4 требуется флаг `--verify=false`, либо предварительный импорт публичного ключа:

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
# Helm 3
helm plugin install https://github.com/helm-unittest/helm-unittest.git
# или с указанием версии:
helm plugin install https://github.com/helm-unittest/helm-unittest.git --version 1.2.1

# Helm 4 (требуется --verify=false, т.к. GPG-проверка не поддерживается для git-URL)
helm plugin install https://github.com/helm-unittest/helm-unittest.git --verify=false

# Официальный OCI-реестр (только с v1.1.0+)
helm plugin install oci://ghcr.io/helm-unittest/helm-unittest/unittest:latest
```

**Из локального OCI-реестра (air-gapped):**
```bash
helm plugin install oci://harbor.corp.local/helm-plugins/unittest:1.2.1
```

**Через Docker (воспроизводимый CI):**
```bash
docker run --rm -v "$(pwd):/apps" helmunittest/helm-unittest:3.22.0-1.2.1 .
# с JUnit-отчётом:
docker run --rm -v "$(pwd):/apps" helmunittest/helm-unittest:3.22.0-1.2.1 \
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
ci/
```

Чтобы тесты, снапшоты и `ci/`-заглушки не попадали в собранный `.tgz`-артефакт чарта (это полезно и для безопасности, и для уменьшения размера, и чтобы secrets из `ci/` случайно не оказались в релизе).

### 2. Мокирование Capabilities, Release, Values

**Capabilities (адаптивная логика API):**
```yaml
suite: test adaptive api versions
templates:
  - ingress.yaml
tests:
  - it: should use networking.k8s.io/v1 for K8s 1.19+
    capabilities:
      majorVersion: 1
      minorVersion: 19
      apiVersions:
        - networking.k8s.io/v1
    asserts:
      - equal:
          path: apiVersion
          value: networking.k8s.io/v1
  - it: should fall back to extensions/v1beta1 on K8s 1.16
    capabilities:
      majorVersion: 1
      minorVersion: 16
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
        upgrade: false
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
      - greaterOrEqual:           # числовое сравнение
          path: spec.template.spec.containers[0].resources.requests.memory
          value: 64
      - lessOrEqual:
          path: spec.template.spec.containers[0].resources.limits.memory
          value: 512
      - isNotNullOrEmpty:        # строка не пуста
          path: metadata.labels["app.kubernetes.io/version"]
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

# Параллельный запуск тестов (v1.1+, ускоряет большие наборы)
helm unittest --parallel --max-workers 4 ./my-chart

# Покрытие кода шаблонов (v1.2+)
helm unittest --coverage ./my-chart
# с машинночитаемым отчётом:
helm unittest --coverage-format cobertura,lcov --coverage-file ./reports/cov ./my-chart
# → result: ./reports/cov.xml (Cobertura), ./reports/cov.info (LCOV)

# Генерация JUnit-отчёта для GitLab/GitHub
helm unittest -o report.xml -t JUnit ./my-chart
```

Форматы отчётов: `JUnit`, `NUnit`, `XUnit` (по умолчанию **XUnit**), `Sonar`. Для GitLab — `JUnit`, для Jenkins — `JUnit` или `XUnit`, для Azure DevOps — `JUnit`, для SonarQube — `Sonar`.

### 10. Запуск и интеграция в CI/CD

**GitLab CI (offline-friendly):**
```yaml
stages:
  - validate
  - test
  - package

variables:
  HELM_IMAGE: "harbor.corp.local/devops/helm:3.22.0"

helm-lint:
  stage: validate
  image: ${HELM_IMAGE}
  script:
    - helm lint ./charts/*
    - |
      for chart in charts/*/; do
        helm lint "$chart"
        helm lint "$chart" -f "${chart}values-dev.yaml" || true
      done

helm-unittest:
  stage: test
  image: helmunittest/helm-unittest:3.22.0-1.2.1
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
    - ct lint --config ct.yaml --charts charts/my-service
    - ct install --config ct.yaml --charts charts/my-service --debug

helm-package:
  stage: package
  image: ${HELM_IMAGE}
  script:
    - helm package ./charts/* --destination dist/
  artifacts:
    paths:
      - dist/*.tgz
  only:
    - main
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
      image 'helmunittest/helm-unittest:3.22.0-1.2.1'
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
    image: helmunittest/helm-unittest:3.22.0-1.2.1
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
      image: helmunittest/helm-unittest:3.22.0-1.2.1
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
target-branch: main
chart-dirs:
  - charts
chart-repos:
  - bitnami=https://charts.bitnami.com/bitnami
validate-maintainers: false
chart-yaml-schema: https://raw.githubusercontent.com/helm/chart-testing/main/etc/chart_schema.yaml
lint-conf: ct-lint.yaml
check-version-increment: true
```

`check-version-increment: true` (вкл. по умолчанию) заставляет `ct` падать, если шаблоны чарта изменены, а версия в `Chart.yaml` — нет. Это защищает от выпуска артефакта, который не отличается от предыдущего тега.

```bash
# Только линтинг (lint + unittest + values.schema)
ct lint --config ct.yaml

# Полный цикл (lint + install dry-run в kind/eks/...)
ct install --config ct.yaml

# Только helm-unittest через ct
ct lint --config ct.yaml --lint-cmd "helm unittest --strict --failfast {}"

# Явно указать чарты (избегает линта на неизменённых чартах в монорепо)
ct lint --config ct.yaml --charts charts/my-service
```

`ct` запускает helm-unittest автоматически как часть `ct lint`, если в чарте есть директория `tests/`. Кастомный `lint-cmd` позволяет переопределить команду.

**Values-заглушки для `ct install`:**

`ct install` использует values из поддиректории `ci/` внутри чарта. Каждый `.yaml`-файл в `ci/` — отдельная установка с разными значениями:

```text
charts/my-service/
├── Chart.yaml
├── templates/
├── values.yaml
└── ci/
    ├── default-values.yaml      # ← используется для ct install
    ├── dev-values.yaml          # ← вторая установка
    └── staging-values.yaml      # ← третья установка
```

Если `ci/` отсутствует, `ct install` использует значения из `values.yaml` чарта. Однако для production-чартов `values.yaml` часто содержит placeholder-значения, поэтому рекомендуется всегда заводить `ci/default-values.yaml` с безопасными значениями для тестовой установки. Файлы `ci/` должны быть добавлены в `.helmignore` основного чарта (они нужны только для тестов, а не для релиза):

```text
# .helmignore
tests/
__snapshot__/
ci/
```

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

### 14. Миграция с helm-unittest 0.7.x → 1.2.x

Ключевые изменения (breaking changes):

- **`capabilities.major`/`minor` → `capabilities.majorVersion`/`minorVersion`.** Поля переименованы в v1.0.0. Старые имена больше не расп 인яются.
- **`release.isInstall`/`isUpgrade` → `release.upgrade`.** Объединены в одно логическое поле. `isInstall: true` эквивалентно `upgrade: false` (значение по умолчанию, может быть опущено).
- **`greaterThan` → `greaterOrEqual`, `lessThanOrEqual` → `lessOrEqual`.** Имена assertion-ов выровнены с семантикой (ранее назывались смещённо).
- **JsonPath по умолчанию** в `path`. Старые выражения с `\.` для экранирования точек в ключах ломаются: `metadata.labels.app\.kubernetes\.io/name` → `metadata.labels["app.kubernetes.io/name"]`.
- **`--strict`** — теперь выявляет опечатки в assertion-именах и неизвестные поля тестов. Включите в CI как можно раньше.
- **Формат отчёта по умолчанию** — `XUnit`. Если CI использует парсер, ожидающий `JUnit`, укажите `-t JUnit` явно.

Пошаговый план:
1. Обновите плагин: `helm plugin install --version 1.2.1 ...`
2. Запустите `helm unittest --strict ./my-chart` — соберите список упавших тестов.
3. Замените `capabilities.major`/`minor` на `majorVersion`/`minorVersion`.
4. Замените `release.isInstall: true` → `upgrade: false` (или удалите, т.к. это дефолт).
5. Замените `greaterThan` → `greaterOrEqual`, `lessThanOrEqual` → `lessOrEqual`.
6. Замените экранированные точки в `path` на JsonPath-кавычки: `metadata.labels.app\.kubernetes\.io/name` → `metadata.labels["app.kubernetes.io/name"]`.
7. Закоммитьте изменения тестов отдельным PR с меткой `unittest-1.x-migration`.

### 15. Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| `failed to load chart: validation: chart.metadata.apiVersion is required` | Чарт использует `apiVersion: v1` | Переведите чарт на `apiVersion: v2` (Chart.yaml) |
| `test file does not exist` | Тесты вне `tests/` | Переместите в `tests/` или используйте `-f 'pattern/**/*_test.yaml'` |
| `snapshot not found, please use -u to update` | Снапшот ещё не создан | `helm unittest -u ./my-chart` локально, закоммитьте `__snapshots__/` |
| Тест проходит локально, падает в CI | Разные версии Helm | Зафиксируйте версии через Docker-образ или `helm version` в pre-job |
| `failed parsing testsuite` после обновления 0.7→1.x | Старый синтаксис `capabilities.major`/`release.isInstall`/`greaterThan` | Запустите с `--strict`, замените на `majorVersion`/`upgrade`/`greaterOrEqual` |
| `helm plugin install` падает на git-URL в Helm 4 | GPG-проверка | `--verify=false` или импорт публичного ключа плагина |
| Тесты внутри subchart игнорируются | `--with-subchart=false` | Уберите флаг или поставьте `true` |
| `isKind` не находит ресурс | Multi-doc шаблон | Добавьте `documentSelector` или `documentIndex` |
| `values.schema.json` блокирует тест | Schema не пускает тестовые значения | Временно `--skip-schema-validation` или ослабьте schema |
| Snapshot diff после изменения шаблона | Шаблон действительно изменился | Проверьте `git diff` руками, затем `helm unittest -u` |
| `helm plugin install` долго устанавливается в CI | Скачивание из github.com при каждом запуске | Предустановите плагин в Docker-образ на базе `alpine/helm:3.22.0` |
| `ct lint` падает на неизменённых чартах | По умолчанию ct проверяет все чарты в `chart-dirs` | Используйте `--charts charts/my-service`, чтобы явно указать чарты |
| `ct install` не находит values для тестовой установки | Нет файла-заглушки в `ci/` | Создайте `ci/default-values.yaml` в директории чарта |
| `check-version-increment: true` ломает CI | Шаблоны изменены, а версия в `Chart.yaml` нет | Инкрементируйте `version:` в `Chart.yaml`, либо отключите `--target-branch`-поведение |

### 16. Ограничения и границы применимости

- **Юнит-тесты не заменяют dry-run** в реальном кластере. Шаблон может быть синтаксически корректен, но не пройти admission webhook (OPA, Kyverno) или отсутствующий CRD. Обязателен второй уровень валидации через `ct install` или `helm install --dry-run=server`.
- **Не валидируют runtime-логику**: правильность readiness-проб, корректность volume mounts, работоспособность образа — это зона интеграционных тестов ([helm_hooks_and_tests.md](../helm_hooks_and_tests.md)).
- **Helm unit ≠ Helm test**: `helm test` запускает test-pod внутри кластера, требует kubectl-доступа и времени на развёртывание. Юнит-тесты — статика, всегда 1–5 секунд.
- **Snapshot-тесты хрупки при больших рефакторингах**. Любое изменение условной логики «зацепит» десятки снапшотов. Точечные ассерты более устойчивы к рефакторингу, хотя требуют больше кода.
- **Templated Test Suites** — рендерят чарт внутри тестового прогона, что увеличивает время. Для 10+ окружений может стать узким местом. Альтернатива — параметризация через shell-цикл.
- **Тесты не покрывают helm-хуки** в полном объёме: `helm-unittest` рендерит хуки как обычные манифесты, но не запускает их lifecycle (pre-install, post-upgrade). Для E2E хуков — `helm test` или `ct install`.

### 17. helm lint — статическая валидация

`helm lint` — встроенный линтер, который проверяет синтаксис `Chart.yaml`, структуру каталога чарта, корректность шаблонов и соответствие `values.schema.json`. Он работает без кластера и ловит ошибки, которые не видит рендеринг: отсутствующие `required`-поля, несоответствие типов values и нарушения структуры.

```bash
# Базовый линтинг чарта
helm lint charts/my-service

# Линтинг с environment-specific values
helm lint charts/my-service -f charts/my-service/values-dev.yaml
```

**Критически важно:** линтите с `values`-файлами каждого окружения, а не только с `defaults`. Значение, опциональное в `values.yaml`, может стать обязательным в `values-dev.yaml` из-за `{{ required "field is required" .Values.someField }}` в шаблонах.

Для нескольких чартов в монорепо:

```bash
for chart in charts/*/; do
  helm lint "$chart"
  helm lint "$chart" -f "${chart}values-dev.yaml" || true
done
```

> **Примечание для Helm 4:** флаг `--strict` для `helm lint` всё ещё доступен (`--strict  fail on lint warnings`). Комбинируйте его с `values.schema.json` для максимальной строгости валидации в CI.

### 18. Что тестировать и что пропускать

Необходимо покрывать проверками те участки, где ошибка приводит к нерабочему или небезопасному деплою, а не те, что валидирует и так Kubernetes.

**Тестировать (unit-тесты на helm-unittest):**

| Что | Почему | Пример assertion |
|---|---|---|
| Количество реплик по окружениям | Неправильный `replicaCount` приводит к over/under-provisioning | `equal: path: spec.replicas, value: 3` |
| SecurityContext | `allowPrivilegeEscalation: true` или отсутствие `readOnlyRootFilesystem` — нарушение PSA | `equal: path: spec.template.spec.containers[0].securityContext.allowPrivilegeEscalation, value: false` |
| Resource requests/limits | Отсутствие `requests` приводит к плохой scheduling-стратегии и OOM | `isNotNullOrEmpty: path: spec.template.spec.containers[0].resources.requests.cpu` |
| Selector Service совпадает с метками Deployment | Мismatch ломает Service-to-Pod routing | `equal: path: spec.selector.app, value: my-service` |
| Обязательные secrets/configmaps | Отсутствие `required`-вызова приводит к пустым значениям в runtime | `failedTemplate: errorMessage: "field is required"` |
| Image tag и репозиторий | `latest` или неверный репозиторий ломают деплой | `notMatchRegex: path: spec.template.spec.containers[0].image, pattern: ":latest"` |

**Пропустить (не unit-тестами):**

| Что | Почему | Как проверять |
|---|---|---|
| Внутренности Kubernetes (scheduler, controller-manager) | Это функции платформы, а не чарта | `ct install --dry-run` + E2E |
| Runtime-поведение (readiness probe, volume mounts, работоспособность образа) | Требует запущенного кластера | `helm test` (integration test pod) |
| ConfigMap/Secret data содержимое (за исключением presence) | Данные генерируются внешними системами | Интеграционные тесты в кластере |
| Helm hooks lifecycle (pre-install, post-upgrade) | `helm-unittest` рендерит, но не исполняет | `ct install` или `helm test` в кластере |

---

## Дополнительная информация

- **[Плагины Helm](../helm_plugins.md)** — обзор расширений CLI, в том числе helm-unittest.
- **[Хуки и тестирование чартов](../helm_hooks_and_tests.md)** — интеграционное тестирование (`helm test`) в реальном кластере.
- **[Шаблонизация в Helm](../helm_templating.md)** — синтаксис Go Templates, на котором основан рендер под тестами.
- **[Библиотечные чарты](../helm_dependencies_and_library_charts.md)** — обязательный контекст для тестирования через `commonTemplate`.
- **[Проверка версий API и возможностей](./scenarios.md#3-создание-универсальных-адаптивных-чартов)** — когда и зачем нужно мокировать `.Capabilities`.
- **[Безопасность и лучшие практики](./security_best_practices.md)** — соседний уровень валидации: `helm lint`, `values.schema.json`, `kubeconform`.
- **[chart-testing (ct)](https://github.com/helm/chart-testing)** — оркестратор полного цикла валидации чартов.
- **[helm-unittest DOCUMENT.md](https://github.com/helm-unittest/helm-unittest/blob/main/DOCUMENT.md)** — полный справочник по assertion-API (v1.x).
