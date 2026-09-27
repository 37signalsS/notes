# TDD, BDD и ATDD: Методологии разработки через тестирование

## Определения

**TDD (Test-Driven Development)** — разработка через тестирование. Методология, при которой тесты пишутся до реализации функционала. Является ключевым элементом концепции **Shift-Left Testing** (сдвиг тестирования на ранние этапы разработки).

**BDD (Behavior-Driven Development)** — разработка через поведение. Расширение TDD, фокусирующееся на поведении системы с точки зрения бизнеса. Использует спецификации на естественном языке (Gherkin), понятные как разработчикам, так и стейкхолдерам.

**ATDD (Acceptance Test-Driven Development)** — разработка через приемочные тесты. Процесс, в котором заказчик, разработчик и тестировщик совместно определяют критерии приемки в виде автоматизированных тестов до начала реализации.

**Consumer-Driven Contracts (CDC)** — контрактное тестирование со стороны потребителя. Эволюция TDD/BDD для микросервисной архитектуры, где тесты определяют ожидания потребителя API, формируя обязательный контракт для поставщика (Producer). Подробный воркфлоу с использованием Pact Broker и can-i-deploy см. в разделе **[Контрактное тестирование](../../Testing/testing_types_unit_integration_e2e.md#полный-воркфлоу-pact-consumer-driven-в-cicd)**.
*Примечание: Не путать с Change Data Capture (CDC) в контексте баз данных.*

**TCR (Test && Commit || Revert)** — экстремальная форма TDD, предложенная Кентом Беком. Если тесты проходят — код фиксируется (commit), если падают — код автоматически откатывается (revert) к последнему успешному состоянию. Это заставляет делать минимальные, гарантированно рабочие шаги.

## Основные концепции и архитектура

### Процесс TDD: Цикл Red-Green-Refactor

Жизненный цикл разработки через тестирование состоит из трех этапов:

1. **RED (Красный)**: Написание минимального падающего теста для новой функции. На этом этапе определяется интерфейс (дизайн) будущего кода. Тест компилируется и запускается, но падает, так как реализация отсутствует.

2. **GREEN (Зеленый)**: Написание ровно такого количества кода, которое необходимо для прохождения теста. Допускается «грязное» решение. Цель — быстро получить зеленый тест, а не идеальную архитектуру.

3. **REFACTOR (Рефакторинг)**: Улучшение структуры кода, удаление дублирования и оптимизация без изменения поведения. Тесты гарантируют отсутствие регрессии.

### Три закона TDD (Роберт Мартин)

1. Нельзя писать production-код, пока не написан падающий unit-тест.
2. Нельзя писать unit-тест больше, чем необходимо для его падения (ошибка компиляции — это тоже падение).
3. Нельзя писать production-код больше, чем необходимо для прохождения текущего падающего теста.

### Концепция Double Loop TDD

Сочетание BDD и TDD для обеспечения качества на всех уровнях:
1. **Внешний цикл (BDD)**: Написание падающего приемочного теста (проверка поведения всей системы с точки зрения пользователя).
2. **Внутренний цикл (TDD)**: Множественные итерации Red-Green-Refactor для реализации конкретных модулей, пока приемочный тест не станет «зеленым».

### Формат сценариев BDD (Gherkin)

Сценарии описывают бизнес-логику в декларативном стиле:
* **Given (Дано)**: Предусловие или начальное состояние системы.
* **When (Когда)**: Действие, событие или триггер.
* **Then (Тогда)**: Ожидаемый проверяемый результат.
* **And/But (И/Но)**: Логические связки для дополнения условий.

### Сравнение методологий

| Аспект | TDD | BDD | ATDD / CDC |
| :--- | :--- | :--- | :--- |
| **Фокус** | Дизайн и корректность кода | Поведение (User Story) | Контракты и приемка (Acceptance) |
| **Участники** | Разработчики | Dev, QA, Аналитики | Заказчик, Dev, QA, DevOps |
| **Уровень** | Unit-тесты | Интеграционные / E2E | API / System Integration |
| **Инструменты** | Vitest, Pytest, Bun Test | Playwright, Behave | Pact, Robot Framework |

### Test-Driven Infrastructure (TDI)

Применение принципов TDD к инфраструктурному коду (Terraform, Ansible, Kubernetes манифесты):
1. **Написание теста:** Определение желаемого состояния ресурса.
2. **Запуск:** Тест падает, так как ресурс еще не создан или не настроен.
3. **Имплементация:** Написание HCL/YAML кода.
4. **Проверка:** Прогон тестов через Terratest, Kitchen-Terraform или Checkov.

#### Инструменты TDI

| Инструмент | Язык | Тип тестов | Область применения |
| :--- | :--- | :--- | :--- |
| **Terratest** | Go | Интеграционные | Terraform, Packer, Kubernetes, Docker, Helm |
| **Kitchen-Terraform** | Ruby | Интеграционные | Terraform-модули с Testinfra/ServerSpec |
| **Molecule** | Python | Интеграционные | Ansible-роли (Docker/Podman/Vagrant) |
| **Testinfra** | Python | Интеграционные | Проверка фактического состояния ОС |
| **conftest** | Rego/OPA | Policy | Валидация Kubernetes-манифестов, Terraform HCL, Dockerfile |
| **InSpec** | Ruby | Compliance | Проверка безопасности и соответствия стандартам (CIS, NIST) |
| **Goss / DGoss** | YAML/Go | Интеграционные | Быстрая проверка состояния системы (пакеты, порты, сервисы) |
| **Checkov** | Python | SAST/Static | Статический анализ IaC (Terraform, Kubernetes) |
| **Ginkgo / Gomega** | Go | Unit/Integration | BDD-тестирование на Go (часто в паре с Terratest) |

### Policy-as-Code как расширение TDD

TDD для инфраструктуры тесно связан с **Policy-Driven Development**. Проверки безопасности и соответствия (Compliance) пишутся в виде политик (Rego/OPA) до деплоя. Это позволяет реализовать Shift-Left для всей платформы.

**Инструменты Policy-as-Code:**
* **OPA / Gatekeeper** — движок политик для Kubernetes (Admission Control). Политики пишутся на Rego и применяются к ресурсам кластера.
* **Kyverno** — альтернатива OPA с политиками на YAML (без изучения Rego). Валидация, мутация и генерация ресурсов.
* **Checkov** — статический анализ Terraform/Kubernetes-манифестов на соответствие best practices и корпоративным стандартам.
* **Sentinel** (HashiCorp) — язык политик для Terraform, блокирующий опасные конфигурации до apply.
* **conftest** — CLI для тестирования YAML/HCL/Dockerfile через Rego-политики. Идеален для GitLab CI / GitHub Actions.

**Workflow Policy-as-Code в CI/CD:**
1. Инженер пишет Rego/YAML-политику (ожидаемое состояние).
2. В CI-пайплайне перед `terraform apply` / `kubectl apply` запускается `conftest test` или `opa eval`.
3. Нарушение политики блокирует деплой (hard gate) или генерирует предупреждение (soft gate).
4. Результаты логируются и отправляются в Policy Reporter UI для визуализации.

### Chaos Engineering как продолжение TDD

Chaos Engineering тестирует устойчивость системы к сбоям, применяя те же принципы: гипотеза → эксперимент → наблюдение → вывод.

**Связь с TDD:**
* **TDD** проверяет, что код работает при **нормальных** условиях.
* **Chaos Engineering** проверяет, что система работает при **ненормальных** условиях (отказ узла, сетевой partition, исчерпание ресурсов).
* Оба подхода начинаются с **гипотезы** (ожидаемого поведения) и завершаются **автоматизированной проверкой**.

**Инструменты:**
* **Chaos Monkey / Litmus Chaos** — инъекция сбоев в Kubernetes (убийство подов, блокировка CPU/памяти).
* **ToxiProxy / tc** — сетевые помехи (задержки, потеря пакетов, разрыв соединений).
* **chaos-mesh** — управление хаосом на уровне Kubernetes с CRD и веб-интерфейсом.

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

### Пример Terratest (Go): интеграционный тест Terraform-модуля

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

	// Проверка HTTP-эндпоинта (если bucket настроен как static website)
	url := terraform.Output(t, terraformOptions, "website_endpoint")
	http_helper.HttpGetWithRetry(t, url, nil, 200, "Hello", 10, 5*time.Second)
}
```

**Ключевые особенности Terratest:**
* `defer terraform.Destroy` — гарантирует очистку ресурсов даже при падении теста.
* `t.Parallel()` — параллельный запуск тестов для разных модулей.
* Retryable errors — автоматический ретраи при временных сбоях API.
* **Стоимость:** каждый запуск создаёт реальные ресурсы. В CI используйте выделенные песочницы и обязательный cleanup.

### Пример Molecule + Testinfra (Python): интеграционный тест Ansible-роли

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

### Пример conftest (OPA/Rego): policy-тестирование Kubernetes-манифестов

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
1. Написать Rego-политику (ожидаемое поведение).
2. Запустить `conftest test` — политика падает (нет манифестов).
3. Написать Kubernetes-манифест/Helm-шаблон.
4. `helm template | conftest test -` — проверка проходит.
5. Запуск `helm test` / `kuttl test` для интеграционной проверки в кластере.

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
1. **Lint** — статический анализ (ruff, ansible-lint, helm lint, tflint).
2. **Unit** — быстрые изолированные тесты (TDD-цикл, < 2 мин).
3. **Integration** — проверка взаимодействия компонентов с Testcontainers (5–15 мин).
4. **Policy** — валидация IaC и K8s-манифестов через OPA/Rego (conftest).
5. **Deploy** — деплой в Staging/Production.
6. **Smoke** — BDD-сценарии проверки критических пользовательских путей (post-deploy).

## Операции и команды

### Инструменты для TDD/BDD в CI/CD

| Инструмент / команда | Назначение | Пример использования |
| :--- | :--- | :--- |
| `pytest` | Unit-тестирование Python | `pytest tests/unit/ --cov=app --cov-fail-under=80` |
| `jest` / `vitest` | Unit-тестирование JavaScript/TypeScript | `vitest run --coverage` |
| `behave` | BDD-фреймворк для Python | `behave tests/bdd/features/ --no-capture` |
| `cucumber` | BDD-фреймворк (Java, JS, Ruby) | `cucumber-js features/ --format progress` |
| `mutation testing` (mutmut, Stryker) | Проверка качества тестов | `mutmut run --paths-to-mutate=src/ --tests-dir=tests/` |
| `conftest` | Policy-тестирование YAML/HCL | `conftest test k8s/ -p policy/` |
| `opa` | Оценка политик Rego | `opa eval -i input.json -d policy.rego "data.main.deny"` |
| `molecule` | Тестирование Ansible-ролей | `molecule test -s default` |
| `terratest` | Интеграционные тесты Terraform | `go test -v -run TestTerraformModule` |
| `goss` | Быстрая валидация состояния системы | `goss serve --port 8080 & goss validate --format tap` |
| `testinfra` | Инфраструктурные тесты (Python) | `pytest tests/infra/ --hosts=ssh://app01` |
| `helm test` | Тестирование Helm-чартов | `helm test my-release --namespace prod` |
| `kuttl` | Kubernetes Test Toolkit | `kuttl test --config kuttl.yaml` |

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Unit-тесты падают после merge | Изменение зависимостей без обновления тестов | `pytest -v` для выявления конкретного теста | Обновить тесты под новый контракт |
| BDD-сценарии не отрабатывают | Несоответствие шагов реализации | `behave --no-capture` для просмотра стека | Проверить матчинг шагов в `steps/*.py` |
| Mutation score < 70% | Тесты не покрывают граничные условия | `mutmut results` для просмотра выживших мутантов | Добавить негативные тест-кейсы |
| Molecule падает на idempotence | Ansible-роль не идемпотентна | `molecule converge` + `molecule idempotence` | Исправить handlers, убрать недетерминированные команды |
| conftest блокирует деплой | Жёсткие политики без исключений | `conftest test --debug` для просмотра violations | Добавить исключения в политику или настроить soft gate |
| Terratest утекает ресурсы | Отсутствие `defer Destroy` или падение теста до cleanup | Проверить облачный консоль/реестр | Использовать `t.Parallel()` и `defer terraform.Destroy` |
| Pact contract устарел | Provider изменил API без обновления контракта | `pact-broker can-i-deploy` | Обновить контракт и перезапустить Pact verification |
| Flaky BDD-тесты | Зависимости от внешних сервисов или таймауты | Логи behave, `--format=rerun` | Изолировать внешние зависимости, увеличить таймауты |

## Лучшие практики

### Проектирование тестов

* **Первый принцип:** тесты должны проверять поведение, а не реализацию. Если тест ломается при рефакторинге без изменения поведения — он переусложнён.
* **Изоляция:** unit-тесты не должны зависеть от состояния базы данных, внешних API или тестовых данных. Используйте моки для внешних зависимостей.
* **Детерминированность:** результат не должен зависеть от времени суток, дня недели или нагрузки. Избегайте проверок, чувствительных к concurrency.
* **Именование:** используйте описательные имена тестов, отражающие проверяемое поведение (`test_login_fails_with_invalid_password`).

### Интеграция в pipeline

* **Gate placement:** размещайте unit-тесты сразу после lint, smoke-тесты — после деплоя.
* **Fail-fast:** при провале TDD-цикла инициируйте автоматический откат (revert) без ожидания ручного вмешательства.
* **Parallel execution:** запускайте независимые тесты параллельно (pytest-xdist, matrix strategy в CI), чтобы минимизировать общее время.
* **Artifacts:** сохраняйте coverage-отчёты, JUnit XML, логи behave/pact как артефакты pipeline.
* **Promotion rules:** для стратегий blue-green и canary используйте TDD/BDD-тесты как prerequisite для promotion.

### Observability и метрики

* **Coverage:** определяйте пороги покрытия (например, 80% для unit, 70% для mutation score). Провал — сигнал о недостаточном тестировании.
* **SLO context:** определяйте SLO на pass rate TDD-тестов (например, 99.9% успешных прогонов за 30 дней).
* **Test flakiness:** трекайте flaky-тесты отдельно от стабильных. Используйте quarantine-механизм (как в [Управление нестабильными тестами](./flaky_test_management.md)).

### Безопасность и compliance

* **Secrets management:** не храните токены и пароли для тестов в репозитории. Используйте CI-native secrets (GitLab CI/CD Variables, GitHub Secrets).
* **Read-only access:** тесты в CI должны иметь read-only доступ к production. Не запускайте тесты с кредами, дающими write-доступ.

## Ограничения и особые случаи

### TDD не покрывает всё

TDD проверяет только корректность кода на уровне unit и интеграции. Он не выявляет:
* Баги в бизнес-логике на уровне E2E
* Проблемы с миграцией данных
* Race conditions в production
* Утечки памяти или ресурсов
* Поведение при высокой нагрузке

TDD — это **первая линия защиты**, а не единственное тестирование.

### Флакивость тестов

Частые причины флаков:
* **Race condition:** тест запускается до завершения прогрева кэша или миграций.
* **Timing issues:** проверка запущена во время ротации логов или ротации TLS-сертификатов.
* **External dependencies:** сторонние сервисы недоступны или отвечают с задержкой.
* **Resource starvation:** CI-раннер не имеет достаточно CPU/RAM.

Меры против флаков:
* Фильтруйте flaky-тесты из критериев успешности CI, но трекайте их отдельно.
* Используйте quarantine-механизм для тестов с временными зависимостями.

### Инфраструктурные ограничения

* **TDI в air-gapped средах:** используйте локальные кэши модулей (Terraform module cache, Ansible Galaxy offline).
* **Network segmentation:** размещайте CI-раннеры в отдельном VLAN/segment с минимально необходимыми доступом к production.

## Дополнительная информация

### См. также

* **[Контрактное тестирование](../../Testing/testing_types_unit_integration_e2e.md)** — Pact workflow, CDC.
* **[Smoke Testing](./smoke_testing.md)** — post-deploy verification в CI/CD.
* **[Управление нестабильными тестами](./flaky_test_management.md)** — quarantine, retry, detection.

### Внешние ресурсы

* [Test Driven Development: By Example (Kent Beck)](https://www.amazon.com/Test-Driven-Development-Kent-Beck/dp/0321146530) — фундаментальный труд.
* [The Cucumber Book](https://cucumber.io/docs/guides/overview/) — руководство по BDD и Gherkin.
* [Pact Foundation](https://docs.pact.io/) — документация по контрактному тестированию (CDC).
* [Mutation Testing (Stryker Mutator)](https://stryker-mutator.io/) — инструмент для мутационного тестирования.
* [Hypothesis (Python)](https://hypothesis.readthedocs.io/) — property-based testing для Python.
* [Terratest (Gruntwork)](https://terratest.gruntwork.io/docs/) — документация по тестированию инфраструктуры на Go.
* [Molecule (Ansible)](https://ansible.readthedocs.io/projects/molecule/) — официальное руководство по тестированию Ansible-ролей.
* [conftest (OPA)](https://www.conftest.dev/) — CLI для policy-тестирования YAML/HCL/Dockerfile.
