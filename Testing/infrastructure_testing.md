# Инфраструктурное тестирование (Goss, InSpec, Testinfra)

**Актуально для:** Goss v0.4.9 / Chef InSpec 5.21.x / Testinfra (pytest-dev/pytest-testinfra latest) / Molecule v5

## Определения

**Infrastructure Testing** — автоматизированная проверка состояния инфраструктуры (серверов, контейнеров, IaC-артефактов) на соответствие ожидаемой конфигурации. Вместо «grep по ssh-выводам» используются декларативные тесты: инструменты проверяют пакеты, сервисы, файлы, порты, процессы, пользователей и т.д.

Методология TDI (Test-Driven Infrastructure) — «тесты до кода/после кода инфраструктуры» — описана в [TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md#test-driven-infrastructure-tdi) вместе с сравнительной таблицей инструментов (Terratest, Molecule, conftest, InSpec, Goss).

**Goss** — быстрый YAML-инструмент валидации сервера/контейнера (Go). Самое заметное применение — health-проверки и smoke после сборки образов (в CI). Актуальная стабильная версия — v0.4.x.

**InSpec** — декларативный фреймворк Chef для compliance- и config-тестирования (Ruby DSL; есть профили compliance-OS).

**Testinfra** — Python-фреймворк для тестирования инфраструктуры (pytest-расширение, библиотека для Ansible/SSH/Docker).

## Архитектура и принцип работы

### Модель выполнения

Инфраструктурные тесты работают по принципу **desired state verification**:

1. **Определение желаемого состояния** — декларативный spec (YAML для Goss, Ruby DSL для InSpec, Python для Testinfra) описывает, как система *должна* выглядеть.
2. **Сбор фактов** — инструмент опрашивает реальное состояние: пакеты, сервисы, файлы, сетевые порты, процессы, пользователей, конфигурационные файлы.
3. **Сравнение** — факты сравниваются с spec; расхождения выводятся как failures.
4. **Отчёт** — exit code != 0 при любом расхождении (удобно для CI/CD как Quality Gate).

### Инструменты и их классификация

| Инструмент | Язык | Формат | Цель применения | Экосистема |
| :--- | :--- | :--- | :--- | :--- |
| **Goss** | Go | YAML | Быстрые smoke/health после сборки образов, контейнеров | Docker, Kubernetes (init/startup probes), CI |
| **InSpec** | Ruby DSL / profiles | Ruby DSL / profiles | Compliance, до-контроль, большие профили, интеграция с Chef | Chef, Compliance |
| **Testinfra** | Python (pytest) | Python (pytest) | Тесты под Ansible-роли, SSH/локально, Docker-контейнеры | Ansible, Molecule |
| **ServerSpec** | Ruby (RSpec) | Ruby (RSpec) | Аналогично Testinfra для Ruby-стека | Puppet/Chef |
| **conftest / OPA / Kyverno** | Rego/YAML | Rego/YAML | Policy-тесты манифестов (k8s, Terraform) | OPA, Kyverno |

### Goss: модель

Тест — `.yaml`-файл, описывающий ожидаемые ресурсы системы. Ключевые ресурсы:

- `package` — установлен пакет (apt/yum/apk);
- `service` — сервис запущен и/или enabled (systemd);
- `addr` — порт/TCP-адрес слушается;
- `file` — файл существует с правами/контентом/owner;
- `user`, `group` — наличие учётной записи;
- `process` — процесс запущен;
- `command` — результат произвольной команды;
- `dns` — разрешение DNS.

Также доступны:

- `http` — HTTP-запрос (status, headers, body),
- `port`-диапазоны, `mount`, `kernel-param`, `mtime/anbu`-проверки.

### Testinfra: модель

Тесты — обычные Python-функции, использующие host-агент. Testinfra опирается на pytest fixtures для подключения к хосту (local, SSH, Docker):

```python
def test_nginx(host):
    pkg = host.package("nginx")
    assert pkg.is_installed
    service = host.service("nginx")
    assert service.is_running
    assert service.is_enabled

def test_config(host):
    f = host.file("/etc/nginx/nginx.conf")
    assert f.exists and f.mode == 0o644
```

```bash
pytest --host='ssh://root@10.0.0.5' tests/   # против удалённого хоста
pytest --host='docker://my_container_id'      # против контейнера
pytest --host='local'                         # локально
```

### InSpec: профили

Профиль — папка с `controls/*.rb`. InSpec поддерживает два режима:

- **локальный** (local target) — тесты выполняются на том же хосте;
- **удалённый** (`-t ssh://`, `-t docker://`) — через транспортный слой.

```ruby
control 'nginx-01' do
  impact 0.7
  title 'nginx должен быть установлен и запущен'
  describe package('nginx') do
    it { should be_installed }
  end
  describe service('nginx') do
    it { should be_running }
    it { should be_enabled }
  end
  describe file('/etc/nginx/nginx.conf') do
    it { should exist }
    it { should be_mode 644 }
  end
end
```

```bash
inspec exec controls/ --target ssh://root@host -i ~/.ssh/id_rsa
inspec exec https://github.com/dev-sec/linux-baseline -t docker://<id>  # готовые compliance-профили
```

## Практические сценарии

### Сценарий 1: Smoke контейнерного образа в CI (Goss + Docker)

**Предпосылки:**
- Docker 20.10+
- Goss YAML (`goss.yaml`) в корне проекта
- Права на запись в `/tmp` внутри контейнера

`Dockerfile` с встроенным goss на этапе проверки:

```dockerfile
FROM nginx:1.27
# ... копируем конфиги, зависим от этапа сборки
RUN curl -Lo /tmp/goss https://github.com/goss-org/goss/releases/download/v0.4.9/goss-linux-amd64 \
 && chmod +x /tmp/goss
COPY goss.yaml /goss.yaml
CMD ["nginx", "-g", "daemon off;"]
```

проверка в CI:

```bash
docker build -t app:test .
docker run -d --name test-runner app:test
docker exec test-runner /tmp/goss validate
docker rm -f test-runner
```

**Валидация:** `goss validate` возвращает exit code 0 при успехе, 1 при failure.

или с обёрткой `dgoss` (docker + goss):

```bash
dgoss run -p 8080:80 app:test goss validate
```

### Сценарий 2: Goss как init-здоровье Kubernetes (startupProbe)

**Предпосылки:**
- Goss упакован в образ
- `goss.yaml` в корне образа (`/goss.yaml`)

```yaml
startupProbe:
  exec:
    command: ["goss", "validate", "--format", "json"]
```

Идиома: goss в образе + `startupProbe`/`livenessProbe` — быстрое детектирование неготовности. (Подробно про пробы — в документации Kubernetes `liveness/readiness probes`).

### Сценарий 3: Тестирование Ansible-роли через Molecule + Testinfra

**Предпосылки:**
- Ansible 2.17+
- Molecule 5.x
- Python 3.11+ с testinfra

Molecule — стандартный цикл для Ansible ролей (см. [Тестирование Ansible-ролей](../Ansible/ansible_testing_with_molecule.md)):

1. `molecule init scenario` — создаёт `verify.yml` с Testinfra.
2. `molecule converge` — применяет роль.
3. `molecule verify` — запускает Testinfra-тесты.

```python
def test_postgres_installed(host):
    assert host.package("postgresql-16").is_installed
    assert host.service("postgresql").is_running
```

**Валидация:** `molecule verify` возвращает exit code 0 только если все тесты проходят.

### Сценарий 4: Compliance-проверка продакшн-хостов (InSpec)

**Предпосылки:**
- InSpec 5.x
- SSH-доступ с sudo
- JSON-файл с credentials (`~/.inspec/creds.json`)

```bash
inspec exec https://github.com/dev-sec/linux-baseline \
  -t ssh://root@app --sudo -c ~/.inspec/creds.json
```

**Валидация:** InSpec выводит таблицу результатов с процентом прохождения. Exit code 0 при compliance, 100 при non-compliance.

C профилями обеспечивается соответствие CIS/DISA — они удобны для аудита и до-проверок перед внедрением.

### Сценарий 5: Интеграция в CI/CD pipeline (GitLab)

**Предпосылки:**
- CI-runner с Docker-in-Docker или Docker socket
- Goss и Testinfra в образе runner-а

```yaml
infra-tests:
  stage: verify
  script:
    - docker build -t app:test .
    - docker run -d --name test-runner app:test
    - docker exec test-runner goss validate --format json || exit 1
    - docker run --rm --network host -it \
        --entrypoint pytest bhilmann/pytest-testinfra-docker \
        --host='docker://test-runner' tests/
  after_script:
    - docker rm -f test-runner
```

**Валидация:** pipeline падает на `exit 1` при любом infrastructure test failure.

Применение smoke-логики после деплоя — см. [Smoke-тестирование после деплоя](../CI-CD/Testing/smoke_testing.md).

## Операции и команды

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `goss validate` | Запуск всех тестов из `goss.yaml` | `goss validate --format json` |
| `goss add <resource>` | Генерация YAML по текущему состоянию | `goss add package nginx && goss add addr tcp:80` |
| `goss render` | Отображение сформированного YAML | `goss render --lint` |
| `goss serve` | HTTP-интерфейс для удалённой валидации | `goss serve -p 8080` |
| `dgoss run` | Goss в контейнере | `dgoss run -p 8080 app:goss` |
| `inspec exec <path>` | Запуск профиля InSpec | `inspec exec controls/ --target ssh://root@host` |
| `inspec check` | Статическая проверка профиля | `inspec check profiles/` |
| `inspec fmt` | Форматирование Ruby DSL | `inspec fmt controls/` |
| `pytest --host` | Запуск Testinfra-тестов | `pytest --host='ssh://root@10.0.0.5' tests/` |
| `molecule converge` | Применение роли в тестовом окружении | `molecule converge` |
| `molecule verify` | Запуск verifier (Testinfra) | `molecule verify` |
| `molecule destroy` | Удаление тестовых VM/контейнеров | `molecule destroy` |
| `molecule test` | Полный цикл (converge → verify → destroy) | `molecule test` |

### JVM/окружение для InSpec

Для удалённого запуска InSpec:

```bash
# Установка через Chef DK (включает inspec)
curl https://omnitruck.chef.io/install.sh | sudo bash -s -- -P chefdk

# Либо standalone
curl https://omnitruck.chef.io/install.sh | sudo bash -s -- -P inspec
```

### Переменные окружения

| Переменная | Применение | Значение по умолчанию |
| :--- | :--- | :--- |
| `INSPEC_CONFIG` | Путь к `credentials.json` | `~/.inspec/config.json` |
| `PYTEST_HOST` | Алиас для `--host` в Testinfra | — |
| `GOSS_OPTS` | Дополнительные флаги для goss | — |

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `cannot connect to the Docker daemon` | dgoss/Testinfra на host без доступа к docker.sock | `docker ps` вручную | Настроить `DOCKER_HOST`/права группы docker |
| Goss `timeout waiting for http` | Сервис ещё не поднялся к запуску теста | `curl http://localhost/health` до запуска goss | Добавить ретраи/ожидание: `goss validate --retry=5 --sleep=2` |
| Проверка `service running` падает в контейнере | В контейнере нет systemd | `systemctl status nginx` внутри контейнера | Использовать `process`/`http` вместо `service` в OCI |
| Testinfra не видит SSH-хост | Миск-конфиг ансиблера, ключи | `ssh root@host` вручную | `--host='ssh://user@host' -i key`, проверить сетевую доступность |
| Диспропорция прав/owner на разных ОС | Различия базовых образов | `ls -la /etc/nginx/nginx.conf` на разных дистрибутивах | Параметризовать тесты по OS (pytest `--pyargs`, метки) |
| InSpec-профиль флакаит semantics | Независимость от порядка/окружения | `inspec exec --verbose` | Использовать `describe file` с `file('modules')` из api, драйвер `sudo` |
| Goss `addr tcp:80: listening` fails | Порт проверяется до того, как сервис слушает | `ss -tlnp | grep :80` в момент теста | Добавить `goss validate --sleep 2` или `retry` в YAML |
| InSpec `control could not be loaded` | Синтаксическая ошибка в профиле Ruby DSL | `inspec check controls/` | `inspec fmt` для форматирования, исправить синтаксис |
| Testinfra `ModuleNotFoundError: No module named 'testinfra'` | testinfra не установлен в окружении | `pip show testinfra` | Установить: `pip install testinfra[all]` |

## Лучшие практики

### Общие принципы

1. **Декларативность > императивность** — описывайте *что* должно быть, а не *как проверить*. YAML/Rego легче поддерживать, чем bash-скрипты с `grep`/`awk`.
2. **Fail-fast в CI** — infrastructure тесты — Quality Gate. Non-zero exit code на любое расхождение.
3. **Smoke vs Compliance** — Goss/Testinfra для smoke и config-проверок; InSpec для compliance-аудитов (CIS/STIG/PCI). Не смешивайте: compliance-профили тяжёлые, smoke должен быть быстрым.
4. **Избегайте флаки** — не проверяйте `service running` в контейнерах без systemd. Используйте `process`/`http`/`command` с ретраями.
5. **Параметризуйте по ОС** — `host.package("nginx")` работает иначе на EL vs Debian. Делайте метки/условия.

### CI/CD интеграция

6. **Goss в Dockerfile** — добавляйте health-проверку на этапе сборки. Это ловит broken образы до деплоя.
7. **Testinfra в Molecule** — используйте `molecule test` как часть PR-пайплайна для Ansible-ролей. Требуйте `--scenario-name` для параллелизма.
8. **InSpec в pre-deploy gate** — запускайте compliance-профили перед выкатом в production. Используйте `--controls` для выбора категорий.
9. **conftest/OPA для IaC** — policy-тесты на этапе `terraform plan`/`kubectl apply --dry-run` ловят нарушения compliance на этапе CI, прежде чем инфраструктура создастся.
10. **Baseline comparison** — сохраняйте baseline performance (Goss validate time, InSpec scan time) и fail при росте >20% (может означать flapping или увеличение поверхности атаки).

### SRE-практики

11. **SRE diagnostic checklist:**
    - **Utilization** — `goss validate` не должен выполнять тяжёлые `command`-проверки на production. Используйте `http`/`addr`/`file` вместо `command "ps aux | grep ..."`.
    - **Saturation** — InSpec scan с `ssl` и `apache` портами может вызывать spikes. Ограничьте parallelism (`--controls`, `--input-file`).
    - **Errors** — `inspec exec --reporter json:report.json` для CI; `--reporter cli` для локальной разработки.
    - **Processes** — `goss add process <name>` для проверки critical процессов; не злоупотребляйте `process running` — это CPU-intensive.
    - **Network** — `addr` и `http` проверки должны иметь таймауты (`timeout` в YAML для Goss).
12. **Resource limits в CI** — Goss/Testinfra/InSpec в CI требуют ограничения ресурсов (CPU, memory, file descriptors). Убедитесь, что container limits не вызывают false failures.
13. **Secrets в тестах** — никогда не храните credentials в `goss.yaml`. Используйте `inspec attributes` и Ansible Vault для Testinfra.

## Ограничения и крайние случаи

- **Goss** — подходит только для Linux (macOS поддерживается экспериментально). Нет встроенного parallel execution больше 100 проверок — используйте `goss serve` + batch API.
- **InSpec** — тяжёлый runtime (Ruby + Chef). Запуск на 100+ хостах требует InSpec CLI в кластере или InSpec Backend (Chef Automate).
- **Testinfra** — не подходит для Windows-хостов без WSL2. `host.ansible()` требует Ansible на control-ноде.
- **Service checks в контейнерах** — `service running: true` работает только с systemd. В OCI-контейнерах используйте `process` или `command`.
- **Compliance drift** — InSpec профили могут флакать при изменении patch version ОС. Используйте `--input-file` для переопределения значений (например, `kernel_version`).
- **Network partitions в distributed testinfra** — SSH-соединения могут зависать. Используйте `ssh_args` с `ConnectTimeout=10`.
- **Goss `http` body matching** — только поддерживает exact match и substring. Нет regex/ JSONPath. Используйте `command "curl ... | jq ..."` для сложных проверок.
- **InSpec `only_if`** — отключает контроль полностью, включая вывод в отчёте. Используйте `skip` для условных controls.

## Очистка

1. **Goss artifacts** — удаляйте `goss.yaml` и скачанные бинарники после CI-ранна:
   ```bash
   rm -f /tmp/goss /goss.yaml
   ```
2. **Testinfra/pytest cache** — очищайте `.pytest_cache` и `__pycache__` в CI:
   ```bash
   rm -rf .pytest_cache tests/__pycache__
   ```
3. **Molecule scenarios** — всегда `molecule destroy` после `molecule converge` в локальной разработке, чтобы не оставлять контейнеры/VM.
4. **InSpec reports** — удаляйте `report.json`/`report.xml` после CI (особенно если содержат вывод compliance с упоминанием хостов).
5. **Docker images** — в CI удаляйте `app:test` после проверки: `docker rmi app:test || true`.
6. **Credentials** — `~/.inspec/creds.json` и SSH-ключи не должны попадать в артефакты CI.
7. **dgo**ss temporary — `dgoss` создаёт временные контейнеры (`tmp_dgoss_*`). Используйте `DOCKER_LABEL` для их идентификации и `docker ps -aq --filter label=dgoss --format '{{.ID}}' | xargs -r docker rm -f` для cleanup.

## Дополнительная информация

### См. также

- **[TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md#test-driven-infrastructure-tdi)** — методология TDI и сравнительная таблица инструментов (SSoT по подходам).
- **[Тестирование Ansible-ролей](../Ansible/ansible_testing_with_molecule.md)** — Molecule + Testinfra для ролей (SSoT по Ansible-ролам).
- **[Смоук-тестирование после деплоя](../CI-CD/Testing/smoke_testing.md)** — где инфраструктурные проверки используются как smoke.
- **[Compliance и аудит в Linux](../Linux/SystemAdministration/Users/users_compliance.md)** — CIS Benchmarks, DISA STIG, SCAP.
- **[Контейнеры и IaC: policy-инструменты](../Concepts/configuration_management_models.md)** — conftest/OPA/Kyverno для policy-тестов манифестов.

### Внешние ресурсы

- [Goss на GitHub](https://github.com/goss-org/goss) — исходный код, сборка, releases (v0.4.9).
- [InSpec Documentation](https://docs.chef.io/inspec/) — документация InSpec (profiles, compliance).
- [Testinfra на GitHub](https://github.com/pytest-dev/pytest-testinfra) — pytest-фреймворк для инфраструктуры.
- [dev-sec профили](https://github.com/dev-sec) — готовые compliance-профили для InSpec (CIS, SSL, SSH).
- [Molecule Documentation](https://ansible.readthedocs.io/projects/molecule/) — официальная документация по тестированию Ansible-ролей.
