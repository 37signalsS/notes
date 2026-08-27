# TDD, BDD и ATDD: Методологии разработки через тестирование

## Определения

**TDD (Test-Driven Development)** — разработка через тестирование. Методология, при которой тесты пишутся до реализации функционала. Является ключевым элементом концепции **Shift-Left Testing** (сдвиг тестирования на ранние этапы разработки).

**BDD (Behavior-Driven Development)** — разработка через поведение. Расширение TDD, фокусирующееся на поведении системы с точки зрения бизнеса. Использует спецификации на естественном языке (Gherkin), понятные как разработчикам, так и стейкхолдерам.

**ATDD (Acceptance Test-Driven Development)** — разработка через приемочные тесты. Процесс, в котором заказчик, разработчик и тестировщик совместно определяют критерии приемки в виде автоматизированных тестов до начала реализации.

**Consumer-Driven Contracts (CDC)** — контрактное тестирование со стороны потребителя. Эволюция TDD/BDD для микросервисной архитектуры, где тесты определяют ожидания потребителя API, формируя обязательный контракт для поставщика (Producer). Подробный воркфлоу с использованием Pact Broker и can-i-deploy см. в разделе **[Контрактное тестирование](../../Testing/testing_types_unit_integration_e2e.md#полный-воркфлоу-pact-consumer-driven-в-cicd)**.
*Примечание: Не путать с Change Data Capture (CDC) в контексте баз данных.*

**TCR (Test && Commit || Revert)** — экстремальная форма TDD, предложенная Кентом Беком. Если тесты проходят — код фиксируется (commit), если падают — код автоматически откатывается (revert) к последнему успешному состоянию. Это заставляет делать минимальные, гарантированно рабочие шаги.

## Основные концепции

### Процесс TDD: Цикл Red-Green-Refactor

1.  **RED (Красный)**: Написание минимального падающего теста для новой функции. На этом этапе определяется интерфейс (дизайн) будущего кода.
2.  **GREEN (Зеленый)**: Написание ровно такого количества кода, которое необходимо для прохождения теста. Допускается «грязное» решение.
3.  **REFACTOR (Рефакторинг)**: Улучшение структуры кода, удаление дублирования и оптимизация без изменения поведения. Тесты гарантируют отсутствие регрессии.

### TDD с поддержкой ИИ (AI-Assisted TDD)

В 2026 году цикл TDD дополняется использованием LLM и агентных воркфлоу:
*   **Prompt-Driven Test:** Использование ИИ для генерации тестовых сценариев на основе бизнес-требований (Intent Design).
*   **Zero-step Implementation:** ИИ предлагает реализацию, проходящую сгенерированные тесты. Роль инженера смещается к верификации намерений и архитектурному надзору.
*   **Self-Healing Tests:** Агенты автоматически исправляют тесты при изменении UI или API, если логика поведения осталась прежней.

Подробнее об агентном подходе см. в **[Методологии AI-First разработки](../../AI/ai-first-development.md)**.

### Три закона TDD (Роберт Мартин)

1.  Нельзя писать production-код, пока не написан падающий unit-тест.
2.  Нельзя писать unit-тест больше, чем необходимо для его падения (ошибка компиляции — это тоже падение).
3.  Нельзя писать production-код больше, чем необходимо для прохождения текущего падающего теста.

### Концепция Double Loop TDD

Сочетание BDD и TDD для обеспечения качества на всех уровнях:
1.  **Внешний цикл (BDD)**: Написание падающего приемочного теста (проверка поведения всей системы с точки зрения пользователя).
2.  **Внутренний цикл (TDD)**: Множественные итерации Red-Green-Refactor для реализации конкретных модулей, пока приемочный тест не станет «зеленым».

### Формат сценариев BDD (Gherkin)

Сценарии описывают бизнес-логику в декларативном стиле:
*   **Given (Дано)**: Предусловие или начальное состояние системы.
*   **When (Когда)**: Действие, событие или триггер.
*   **Then (Тогда)**: Ожидаемый проверяемый результат.
*   **And/But (И/Но)**: Логические связки для дополнения условий.

### Мутационное тестирование (Mutation Testing)

Метод проверки качества самих тестов. Инструмент вносит небольшие изменения (мутации) в production-код (например, меняет `>` на `<` или `+` на `-`).
*   Если тест **упал** — мутант «убит» (тест качественный).
*   Если тест **прошел** — мутант «выжил» (тест не покрывает данную логику, хотя coverage может быть 100%).

### Property-Based Testing (Тестирование на основе свойств)

Подход, при котором вместо фиксированных входных данных (как в обычном TDD) задаются свойства, которым должен соответствовать результат для любых валидных входных данных. Инструмент генерирует сотни случайных кейсов для поиска граничных условий.

### Test-Driven Infrastructure (TDI)

Применение принципов TDD к инфраструктурному коду (Terraform, Ansible, Kubernetes манифесты):
1.  **Написание теста:** Определение желаемого состояния ресурса (например, "Bucket должен быть приватным").
2.  **Запуск:** Тест падает, так как ресурс еще не создан или не настроен.
3.  **Имплементация:** Написание HCL/YAML кода.
4.  **Проверка:** Прогон тестов через **Terratest**, **Kitchen-Terraform** или **Checkov**.

#### Инструменты TDI

| Инструмент | Язык | Тип тестов | Область применения |
| :--- | :--- | :--- | :--- |
| **Terratest** | Go | Интеграционные | Terraform, Packer, Kubernetes, Docker, Helm |
| **Kitchen-Terraform** | Ruby | Интеграционные | Terraform-модули с Testinfra/ServerSpec |
| **Molecule** | Python | Интеграционные | Ansible-роли (Docker/Podman/Vagrant) |
| **Testinfra** | Python | Интеграционные | Проверка фактического состояния ОС (сделано через Ansible, Chef, Puppet) |
| **conftest** | Rego/OPA | Policy | Валидация Kubernetes-манифестов, Terraform HCL, Dockerfile |
| **InSpec** | Ruby | Compliance | Проверка безопасности и соответствия стандартам (CIS, NIST) |
| **Goss / DGoss** | YAML/Go | Интеграционные | Быстрая проверка состояния системы (пакеты, порты, сервисы) |
| **Checkov** | Python | SAST/Static | Статический анализ IaC (Terraform, CloudFormation, K8s) |
| **Ginkgo / Gomega** | Go | Unit/Integration | BDD-тестирование на Go (часто в паре с Terratest) |

#### Пример Terratest (Go): интеграционный тест Terraform-модуля

Terratest создаёт реальную инфраструктуру в облаке, проверяет её и уничтожает:

```go
package test

import (
	"testing"
	"github.com/gruntwork-io/terratest/modules/terraform"
	"github.com/stretchr/testify/assert"
	"github.com/gruntwork-io/terratest/modules/http-helper"
)

func TestTerraformS3Bucket(t *testing.T) {
	t.Parallel()

	terraformOptions := terraform.WithDefaultRetryableErrors(t, &terraform.Options{
		TerraformDir: "../modules/s3-bucket",
		Vars: map[string]interface{}{
			"bucket_name": "test-bucket-terratest-001",
			"environment": "test",
		},
	})

	// Уничтожение инфраструктуры по завершении (defer)
	defer terraform.Destroy(t, terraformOptions)

	// apply: создание ресурсов
	terraform.InitAndApply(t, terraformOptions)

	// Проверка outputs
	bucketId := terraform.Output(t, terraformOptions, "bucket_id")
	assert.Equal(t, "test-bucket-terratest-001", bucketId)

	// Проверка HTTP-эндпоинта (если.bucket настроен как static website)
	url := terraform.Output(t, terraformOptions, "website_endpoint")
	http_helper.HttpGetWithRetry(t, url, nil, 200, "Hello", 10, 5*time.Second)
}
```

**Ключевые особенности Terratest:**
*   `defer terraform.Destroy` — гарантирует очистку ресурсов даже при падении теста.
*   `t.Parallel()` — параллельный запуск тестов для разных модулей.
*   Retryable errors — автоматический ретраи при временных сбоях API облака.
*   **Стоимость:** каждый запуск создаёт реальные ресурсы (AWS/GCP/Azure). В CI используйте выделенные песочницы и обязательный cleanup.

#### Пример Molecule + Testinfra (Python): интеграционный тест Ansible-роли

Структура директорий роли:

```
roles/nginx/
├── tasks/
│   └── main.yml
├── handlers/
│   └── main.yml
└── molecule/
    └── default/
        ├── molecule.yml
        ├── converge.yml
        └── tests/
            └── test_default.py
```

`molecule.yml` — конфигурация среды тестирования:

```yaml
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: instance
    image: geerlingguy/docker-ubuntu2204-ansible:latest
    privileged: true
    pre_build_image: true
provisioner:
  name: ansible
verifier:
  name: ansible
```

`converge.yml` — плейбук применения роли:

```yaml
---
- name: Converge
  hosts: all
  roles:
    - role: nginx
```

`tests/test_default.py` — Testinfra-тесты (Pytest-стиль):

```python
import testinfra.utils.ansible_runner

testinfra_hosts = testinfra.utils.ansible_runner.AnsibleRunner(
    inventory=".molecule/instance/hosts"
).get_hosts("all")

def test_nginx_installed(host):
    """Пакет nginx должен быть установлен"""
    pkg = host.package("nginx")
    assert pkg.is_installed

def test_nginx_running(host):
    """Сервис nginx должен быть запущен"""
    svc = host.service("nginx")
    assert svc.is_running
    assert svc.is_enabled

def test_nginx_config(host):
    """Конфигурация должна быть валидной"""
    cmd = host.run("nginx -t")
    assert cmd.rc == 0

def test_port_80_open(host):
    """Порт 80 должен слушать"""
    socket = host.socket("tcp://0.0.0.0:80")
    assert socket.is_listening

def test_index_html(host):
    """Главная страница должна отдавать контент"""
    cmd = host.run("curl -s http://localhost/")
    assert "Welcome to nginx" in cmd.stdout
```

Запуск полного цикла TDI:

```bash
molecule test
# → create → prepare → converge → idempotence → verify → destroy
```

#### Пример conftest (OPA/Rego): policy-тестирование Kubernetes-манифестов

Проверка YAML-манифестов на соответствие политикам безопасности до деплоя:

```bash
# Установка conftest
go install github.com/open-policy-agent/conftest@latest

# Валидация одного манифеста
helm template ./charts/my-app | conftest test -

# Валидация директории
conftest test ./k8s-manifests/ -p policy/
```

Пример Rego-политики `policy/deny.rego`:

```rego
package main

deny[msg] {
    input.kind == "Deployment"
    not input.spec.template.spec.securityContext.runAsNonRoot
    msg := "Deployment должен указывать runAsNonRoot: true"
}

deny[msg] {
    input.kind == "Deployment"
    not input.spec.template.spec.containers[_].resources.limits.cpu
    msg := "Каждый контейнер должен иметь CPU limit"
}

deny[msg] {
    input.kind == "Pod"
    input.spec.containers[_].securityContext.privileged == true
    msg := "Запуск привилегированных контейнеров запрещён"
}
```

**Цикл TDI для Kubernetes:**
1.  Написать Rego-политику (ожидаемое поведение).
2.  Запустить `conftest test` — политика падает (нет манифестов).
3.  Написать Kubernetes-манифест/Helm-шаблон.
4.  `helm template | conftest test -` — проверка проходит.
5.  Запуск `helm test` / `kuttl test` для интеграционной проверки в кластере.

### Policy-as-Code как расширение TDD

В 2026 году TDD для инфраструктуры тесно связан с **Policy-Driven Development**. Проверки безопасности и соответствия (Compliance) пишутся в виде политик (Rego/OPA) до деплоя. Это позволяет реализовать Shift-Left для всей платформы.

**Инструменты Policy-as-Code:**
*   **OPA / Gatekeeper** — движок политик для Kubernetes (Admission Control). Политики пишутся на Rego и применяются к ресурсам кластера.
*   **Kyverno** — альтернатива OPA с политиками на YAML (без изучения Rego). Валидация, мутация и генерация ресурсов.
*   **Checkov** — статический анализ Terraform/CloudFormation/Kubernetes-манифестов на соответствие best practices и корпоративным стандартам.
*   **Sentinel** (HashiCorp) — язык политик для Terraform Cloud/Enterprise, блокирующий опасные конфигурации до apply.
*   **conftest** — CLI для тестирования YAML/HCL/Dockerfile через Rego-политики. Идеален для GitLab CI / GitHub Actions.

**Workflow Policy-as-Code в CI/CD:**
1.  Инженер пишет Rego/YAML-политику (ожидаемое состояние).
2.  В CI-пайплайне перед `terraform apply` / `kubectl apply` запускается `conftest test` или `opa eval`.
3.  Нарушение политики блокирует деплой (hard gate) или генерирует предупреждение (soft gate).
4.  Результаты логируются и отправляются в Policy Reporter UI для визуализации.

### Chaos Engineering как продолжение TDD

Chaos Engineering тестирует устойчивость системы к сбоям, применяя те же принципы: гипотеза → эксперимент → наблюдение → вывод.

**Связь с TDD:**
*   **TDD** проверяет, что код работает при **нормальных** условиях.
*   **Chaos Engineering** проверяет, что система работает при **ненормальных** условиях (отказ узла, сетевой partition, исчерпание ресурсов).
*   Оба подхода начинаются с **гипотезы** (ожидаемого поведения) и завершаются **автоматизированной проверкой**.

**Инструменты:**
*   **Chaos Monkey / Litmus Chaos** — инъекция сбоев в Kubernetes (убийство подов, блокировка CPU/памяти).
*   **ToxiProxy / tc** — сетевые помехи (задержки, потеря пакетов, разрыв соединений).
*   **chaos-mesh** — управление хаосом на уровне Kubernetes с CRD и веб-интерфейсом.

## Практические сценарии

### Пример TDD на Python (pytest)

```python
import pytest

# Этап RED: Тест падает (функция не реализована)
# @pytest.mark.parametrize("a, b, expected", [(2, 3, 5), (-1, 1, 0), (0, 0, 0)])
# def test_add_numbers(a, b, expected):
#     assert add(a, b) == expected

# Этап GREEN: Минимальная реализация
def add(a, b):
    return a + b

# Этап REFACTOR: Использование параметризации для расширения покрытия
@pytest.mark.parametrize("a, b, expected", [
    (2, 3, 5),
    (-1, 1, 0),
    (10, 20, 30),
    (0.1, 0.2, 0.3) # Пример, где требуется pytest.approx для float
])
def test_add_numbers_parametrized(a, b, expected):
    assert add(a, b) == pytest.approx(expected)
```

### Пример BDD сценария (Gherkin)

```gherkin
Feature: Авторизация пользователя
  Scenario: Успешный вход в систему
    Given пользователь "admin" существует с паролем "pass123"
    When пользователь вводит логин "admin" и пароль "pass123"
    Then система перенаправляет пользователя на главную страницу
    And отображается сообщение "Добро пожаловать, admin"
```

### Пример реализации BDD шагов (Python + Behave)

Связывание Gherkin-сценария с кодом:

```python
from behave import given, when, then

@given('пользователь "{user}" существует с паролем "{password}"')
def step_impl(context, user, password):
    context.auth_system.create_user(user, password)

@when('пользователь вводит логин "{user}" и пароль "{password}"')
def step_impl(context, user, password):
    context.response = context.auth_system.login(user, password)

@then('система перенаправляет пользователя на главную страницу')
def step_impl(context):
    assert context.response.status_code == 302
    assert context.response.location == "/"
```

### Пример Property-Based тестирования (Hypothesis)

```python
from hypothesis import given, strategies as st

def decode(s):
    # Упрощенная логика
    return s

def encode(s):
    return s

@given(st.text())
def test_encode_decode_identity(s):
    # Свойство: декодирование закодированной строки должно возвращать оригинал
    assert decode(encode(s)) == s
```

### Пример CDC сценария (Pact)

Контракт описывает ожидания потребителя (Frontend) от поставщика (Backend API):

```json
{
  "consumer": { "name": "FrontendApp" },
  "provider": { "name": "UserService" },
  "interactions": [
    {
      "description": "Запрос данных пользователя с ID 1",
      "request": {
        "method": "GET",
        "path": "/users/1"
      },
      "response": {
        "status": 200,
        "body": {
          "id": 1,
          "username": "admin",
          "role": "ADMIN"
        }
      }
    }
  ]
}
```

### Сравнение методологий

| Аспект | TDD | BDD | ATDD / CDC |
| :--- | :--- | :--- | :--- |
| **Фокус** | Дизайн и корректность кода | Поведение (User Story) | Контракты и приемка (Acceptance) |
| **Участники** | Разработчики | Dev, QA, Аналитики | Заказчик, Dev, QA, DevOps |
| **Уровень** | Unit-тесты | Интеграционные / E2E | API / System Integration |
| **Инструменты 2026** | **Vitest**, Pytest, Bun Test | **Playwright**, Behave | **Pact**, Robot Framework |

### Интеграция TDD/BDD в CI/CD pipeline (GitLab CI)

Пример пайплайна, реализующего все уровни тестирования — от unit до policy и smoke:

```yaml
stages:
  - lint
  - unit
  - integration
  - policy
  - deploy
  - smoke

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

# --- Unit-тесты (TDD: быстрая обратная связь) ---
test:unit:
  stage: unit
  image: python:3.12-slim
  script:
    - pip install pytest pytest-cov pytest-mock
    - pytest tests/unit/ --cov=app --cov-branch --cov-report=xml:coverage.xml --cov-fail-under=80
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

# --- Интеграционные тесты (TDD: проверка взаимодействия) ---
test:integration:
  stage: integration
  image: python:3.12-slim
  services:
    - postgres:16
    - redis:7
  variables:
    POSTGRES_DB: testdb
    POSTGRES_USER: test
    POSTGRES_PASSWORD: test
  script:
    - pip install pytest testcontainers
    - pytest tests/integration/ --tb=short

# --- Policy-тестирование (TDI: проверка Kubernetes-манифестов) ---
test:policy:
  stage: policy
  image: openpolicyagent/conftest:latest
  script:
    - conftest test k8s/ -p policy/ --all-namespaces
  allow_failure: false

# --- Molecule: тестирование Ansible-ролей (TDI) ---
test:molecule:
  stage: integration
  image: python:3.12-slim
  script:
    - pip install "molecule>=24.0" "molecule-plugins[docker]" ansible-lint pytest-testinfra
    - molecule test -s default
  variables:
    DOCKER_HOST: unix:///var/run/docker.sock

# --- BDD: smoke-тесты после деплоя ---
test:smoke:
  stage: smoke
  image: python:3.12-slim
  script:
    - pip install requests behave
    - behave tests/bdd/features/smoke.feature --no-capture
  only:
    - main
```

**Порядок выполнения в пайплайне:**
1.  **Lint** — статический анализ (ruff, ansible-lint, helm lint, tflint).
2.  **Unit** — быстрые изолированные тесты (TDD-цикл, < 2 мин).
3.  **Integration** — проверка взаимодействия компонентов с Testcontainers (5–15 мин).
4.  **Policy** — валидация IaC и K8s-манифестов через OPA/Rego (conftest).
5.  **Deploy** — деплой в Staging/Production.
6.  **Smoke** — BDD-сценарии проверки критических пользовательских путей (post-deploy).

## Дополнительная информация

### Антипаттерны и типичные ошибки

*   **The Mockery (Избыточное моканье)**: Чрезмерное использование заглушек, при котором тесты проверяют детали реализации, а не конечное поведение. Это блокирует рефакторинг.
*   **The Liar (Лжец)**: Тест, который всегда «зеленый», но не содержит реальных проверок или проверяет нерелевантные условия.
*   **The Giant (Гигант)**: Тесты, покрывающие слишком много логики. Трудно диагностировать причину падения.
*   **Тестирование приватных методов**: Нарушает инкапсуляцию. Логику приватного метода следует тестировать через публичный интерфейс или выделить в отдельный класс.
*   **Fragile Tests (Хрупкие тесты)**: Тесты, ломающиеся при изменениях, не влияющих на функциональность (например, изменение порядка вызовов логгера).

### Принципы качественных тестов

**FIRST (Характеристики качественных unit-тестов):**
*   **Fast** (Быстрые): Выполнение за миллисекунды.
*   **Independent** (Независимые): Результат не зависит от порядка запуска.
*   **Repeatable** (Повторяемые): Стабильность в любой среде.
*   **Self-validating** (Самодокументированные): Четкий результат Pass/Fail.
*   **Timely** (Своевременные): Написаны перед кодом.

**AAA (Структура теста):**
1.  **Arrange** (Подготовка): Настройка окружения и данных.
2.  **Act** (Действие): Вызов тестируемого метода.
3.  **Assert** (Проверка): Сравнение результата с ожидаемым.

### Test Pyramid в CI/CD

Пирамида тестирования определяет баланс между типами тестов. В 2026 году выделяют три модели:

| Модель | Фокус | Пропорция | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Testing Pyramid** | Unit-тесты (быстрые) | 70% Unit / 20% Integration / 10% E2E | Классические приложения |
| **Testing Trophy** | Integration-тесты | 10% Unit / 60% Integration / 20% E2E / 10% Contract | Frontend, React/Vue |
| **Testing Honeycomb** | API/Contract-тесты | 20% Unit / 40% Integration / 30% Contract / 10% E2E | Микросервисы |

**Practical ratio для CI/CD:**
- Unit-тесты: запуск < 2 мин (каждый коммит)
- Integration-тесты: запуск 5-15 мин (каждый MR)
- E2E-тесты: запуск 10-30 мин (MR или nightly)
- Contract-тесты: запуск 2-5 мин (каждый MR)
- Load-тесты: запуск 3-10 мин (MR, см. [Load Testing](./load_testing_ci_cd.md))

### Property-Based Testing (Тестирование на основе свойств)

Подход, при котором вместо фиксированных входных данных задаются **свойства**, которым должен соответствовать результат для **любых** валидных входных данных.

#### Когда использовать
- Граничные условия (edge cases) невозможно перечислить
- Алгоритмы сортировки, парсинга, кодирования
- Математические функции, cryptography, хеширование

#### Python + Hypothesis

```python
from hypothesis import given, strategies as st, settings

# Простой property-based тест
@given(st.lists(st.integers()))
def test_sort_preserves_length(xs):
    """Сортировка не меняет длину списка."""
    result = sorted(xs)
    assert len(result) == len(xs)

@given(st.lists(st.integers()))
def test_sort_is_idempotent(xs):
    """Двойная сортировка = одинарной."""
    assert sorted(sorted(xs)) == sorted(xs)

@given(st.lists(st.integers()))
def test_sort_preserves_elements(xs):
    """Сортировка сохраняет все элементы (с учётом дубликатов)."""
    assert sorted(xs) == sorted(xs, reverse=True)[::-1]

# Стратегии для специфичных типов
@given(st.from_regex(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"))
def test_email_parsing(email):
    """Парсер email не падает на任何 корректных адресах."""
    result = parse_email(email)
    assert "@" in result
```

#### Go + `testing/quick`

```go
func TestSortProperties(t *testing.T) {
    f := func(nums []int) bool {
        sorted := sort.Ints(nums)
        return len(sorted) == len(nums)
    }
    if err := quick.Check(f, nil); err != nil {
        t.Error(err)
    }
}
```

### Мутационное тестирование (Mutation Testing)

Метод проверки **качества самих тестов**. Инструмент вносит небольшие изменения (мутанты) в production-код и проверяет, убивают ли тесты этих мутантов.

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Mutation Score** | Доля убитых мутантов / общее число мутантов | > 70% |
| **Survived Mutants** | Мутанты, которые тесты НЕ убили | Чем меньше, тем лучше |

#### Python + mutmut

```bash
# Установка
pip install mutmut

# Запуск мутационного тестирования
mutmut run --paths-to-mutate=src/ --tests-dir=tests/

# Результаты
mutmut results
mutmut html  # HTML-отчет
```

#### JavaScript + Stryker

```bash
# Установка
npm install --save-dev @stryker-mutator/core @stryker-mutator/jest-runner

# Конфигурация (stryker.config.json)
{
  "mutate": ["src/**/*.ts"],
  "testRunner": "jest",
  "coverageAnalysis": "perTest",
  "thresholds": { "high": 80, "low": 60, "break": 70 }
}

# Запуск
npx stryker run
```

#### Интеграция с CI

```yaml
mutation_test:
  stage: test
  image: python:3.12
  script:
    - pip install mutmut
    - mutmut run --paths-to-mutate=src/ --tests-dir=tests/
    - |
      SCORE=$(mutmut results | grep "mutation score" | awk '{print $NF}')
      if [ $(echo "$SCORE < 70" | bc -l) -eq 1 ]; then
        echo "FAIL: Mutation score ${SCORE}% < 70% threshold"
        exit 1
      fi
  allow_failure: true  # Опционально: не блокировать, но показывать
```

### См. также

*   **[Виды тестирования: Unit, Integration, E2E](../../Testing/testing_types_unit_integration_e2e.md)**
*   **[Метрики тестового покрытия](../../Testing/testing_coverage_metrics.md)**
*   **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)**
*   **[Нагрузочное тестирование в CI/CD](./load_testing_ci_cd.md)** — k6, performance budget.
*   **[API Тестирование](./api_testing_ci_cd.md)** — REST/gRPC тесты, Newman, Schema Validation.
*   **[Контрактное тестирование](./contract_testing_ci_cd.md)** — Pact, PactFlow, consumer-driven contracts.
*   **[Smoke Testing](./smoke_testing.md)** — post-deploy verification.
*   **[Управление нестабильными тестами](./flaky_test_management.md)** — quarantine, retry, detection.
*   **[Тестирование контейнеров](./container_testing.md)** — Hadolint, Trivy, SBOM.
*   **[Observability-Driven Testing](./observability_driven_testing.md)** — Prometheus как gate.
*   **[Molecule: тестирование Ansible-ролей](../../Ansible/ansible_testing_with_molecule.md)** — интеграционные тесты ролей с Testinfra и Docker.
*   **[Testcontainers: обзор](../../Testing/testcontainers_overview.md)** — стандарт интеграционного тестирования с изолированными контейнерами.
*   **[Юнит-тестирование Helm-чартов](../../Kubernetes/ToolsUtilities/Helm/Advanced/unit_testing.md)** — BDD-тестирование шаблонов черезhelm-unittest.
*   **[IaC: обзор](../../Concepts/iac_overview.md#тестирование-инфраструктурного-кода)** — Terratest, Molecule, Compliance-тесты.
*   **[Политики и Governance (Kyverno/OPA)](../../GitOps/Crossplane/policy_governance.md)** — Policy-as-Code для Kubernetes.
*   **[Методология AI-First разработки](../../AI/ai-first-development.md)**

### Внешние ресурсы

*   [Test Driven Development: By Example (Kent Beck)](https://www.amazon.com/Test-Driven-Development-Kent-Beck/dp/0321146530) — фундаментальный труд.
*   [The Cucumber Book](https://cucumber.io/docs/guides/overview/) — руководство по BDD и Gherkin.
*   [Pact Foundation](https://docs.pact.io/) — документация по контрактному тестированию (CDC).
*   [Mutation Testing (Stryker Mutator)](https://stryker-mutator.io/) — инструмент для мутационного тестирования.
*   [Hypothesis (Python)](https://hypothesis.readthedocs.io/) — property-based testing для Python.
*   [Terratest (Gruntwork)](https://terratest.gruntwork.io/docs/) — документация по тестированию инфраструктуры на Go.
*   [Molecule (Ansible)](https://ansible.readthedocs.io/projects/molecule/) — официальное руководство по тестированию Ansible-ролей.
*   [conftest (OPA)](https://www.conftest.dev/) — CLI для policy-тестирования YAML/HCL/Dockerfile.
*   [Chaos Mesh](https://chaos-mesh.org/) — управление хаосом в Kubernetes.
