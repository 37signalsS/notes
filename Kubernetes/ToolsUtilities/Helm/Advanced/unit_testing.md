# Юнит-тестирование Helm-чартов

## Определения

**Юнит-тестирование Helm-чартов** — это процесс автоматизированной проверки корректности рендеринга шаблонов без необходимости развертывания ресурсов в реальном кластере Kubernetes. В отличие от интеграционных тестов (`helm test`), юнит-тесты проверяют логику шаблонизации: правильность условий (`if/else`), циклов (`range`), формирование меток и соответствие манифестов ожиданиям.

Основным инструментом является плагин **[helm-unittest](https://github.com/helm-unittest/helm-unittest)**.

---

## Основные концепции

### 1. BDD-подход (Behavior-Driven Development)
Тесты описываются в формате YAML и следуют логике «Дано — Когда — Тогда» (`it`, `set`, `asserts`). Это позволяет техническим специалистам легко читать и поддерживать тестовое покрытие, фокусируясь на ожидаемом поведении манифестов.

### 2. Snapshot-тестирование
Механизм фиксации эталонного вывода шаблона. При первом запуске создается снимок (snapshot) отрендеренного YAML. Все последующие запуски сравнивают новый вывод с эталоном. Это лучший способ обнаружения случайных регрессий в сложных шаблонах.

### 3. Изоляция и мокирование (Mocking)
Юнит-тесты работают исключительно с локальным рендерингом (`helm template`). Инструментарий позволяет подменять:
- **`.Values`**: через секцию `set`.
- **`.Release`**: имитация имени релиза, неймспейса и статуса.
- **`.Capabilities`**: имитация версий Kubernetes и доступных API (важно для адаптивных чартов).

### 4. Тестирование хелперов (Helpers)
Возможность тестирования отдельных именованных шаблонов (`define`) без рендеринга всего файла манифеста. Это критично для `library`-чартов, которые не содержат собственных ресурсов.

---

## Практические сценарии

### 1. Подготовка окружения
```bash
# Установка плагина
helm plugin install https://github.com/helm-unittest/helm-unittest
```

Тесты располагаются в директории `tests/` в корне чарта.
```text
my-chart/
├── templates/
├── tests/
│   ├── deployment_test.yaml
│   ├── _suite_test.yaml
│   └── __snapshots__/  # Автоматически создаваемые снимки
└── values.yaml
```

### 2. Тестирование адаптивной логики (Mocking Capabilities)
Если чарт меняет API в зависимости от версии K8s, это можно проверить через `capabilities`.

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
```

### 3. Snapshot-тестирование
Для фиксации сложной структуры без описания десятков ассертов.

```yaml
suite: test full rendering
templates:
  - deployment.yaml
tests:
  - it: should match snapshot
    asserts:
      - matchSnapshot: {}
```
После запуска `helm unittest -u` будет создан файл в `__snapshots__/`.

### 4. Тестирование Named Templates (Helpers)
Для проверки логики генерации меток или селекторов.

```yaml
suite: test helpers
tests:
  - it: should render standard labels correctly
    commonTemplate: mychart.labels
    asserts:
      - matchRegex:
          path: app\.kubernetes\.io/name
          pattern: ^mychart$
```

### 5. Запуск и интеграция в CI/CD
```bash
# Запуск всех тестов
helm unittest ./my-chart

# Обновление снимков (snapshots)
helm unittest -u ./my-chart

# Использование в GitLab CI/CD
test-helm:
  stage: test
  image: helmunittest/helm-unittest
  script:
    - helm unittest --output-type JUnit --output-file report.xml .
  artifacts:
    reports:
      junit: report.xml
```

---

## Дополнительная информация

- **[Плагины Helm](../helm_plugins.md)** — обзор расширений CLI.
- **[Хуки и тестирование чартов](../helm_hooks_and_tests.md)** — интеграционное тестирование (`helm test`) в реальном кластере.
- **[Шаблонизация в Helm](../helm_templating.md)** — синтаксис Go Templates.
- **[Проверка версий API и возможностей](./scenarios.md#3-создание-универсальных-адаптивных-чартов)** — когда и зачем нужно мокировать `.Capabilities`.
- **[Безопасность и лучшие практики](./security_best_practices.md)** — линтинг и статическая валидация через `kubeconform`.
