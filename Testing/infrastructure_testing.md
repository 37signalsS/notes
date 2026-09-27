# Инфраструктурное тестирование (Goss, InSpec, Testinfra)

## Определения

**Infrastructure Testing** — автоматизированная проверка состояния инфраструктуры (серверов, контейнеров, IaC-артефактов) на соответствие ожидаемой конфигурации. Вместо «grep по ssh-выводам» используются декларативные тесты: инструменты проверяют пакеты, сервисы, файлы, порты, процессы, пользователей и т.д.

Методология TDI (Test-Driven Infrastructure) — «тесты до кода/после кода инфраструктуры» — описана в [TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md#test-driven-infrastructure-tdi) вместе с сравнительной таблицей инструментов (Terratest, Molecule, conftest, InSpec, Goss).

**Goss** — быстрый YAML-инструмент валидации сервера/контейнера (Go). Самое заметное применение — health-проверки и smoke после сборки образов (в CI). Актуальная стабильная версия — v0.4.x.

**InSpec** — декларативный фреймворк Chef для compliance- и config-тестирования (Ruby DSL; есть профили compliance-Os).

**Testinfra** — Python-фреймворк для тестирования инфраструктуры (pytest-расширение, библиотека для Ansible/SSH/Docker).

## Основные концепции

### Когда какое средство

| Инструмент | Формат | Цель применения | Экосистема |
| :--- | :--- | :--- | :--- |
| **Goss** | YAML | Быстрые smoke/health после сборки образов, контейнеров | Docker, Kubernetes (init/startup probes), CI |
| **InSpec** | Ruby DSL / profiles | Compliance, до-контроль, большие профили, интеграция с Chef | Chef, Compliance |
| **Testinfra** | Python (pytest) | Тесты под Ansible-роли, SSH/локально, Docker-контейнеры | Ansible, Molecule |
| **ServerSpec** | Ruby (RSpec) | Аналогично Testinfra для Ruby-стека | Puppet/Chef |
| **conftest / OPA / Kyverno** | Rego/YAML | Policy-тесты манифестов (k8s, Terraform) | OPA, Kyverno |

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

### Ресурс YAML — пример

```yaml
package:
  nginx:
    installed: true
  postgresql:
    installed: true
service:
  nginx:
    enabled: true
    running: true
  postgresql:
    enabled: true
    running: true
file:
  /etc/nginx/nginx.conf:
    exists: true
    owner: root
    mode: "0644"
process:
  nginx:
    running: true
addr:
  tcp:80:
    listening: true
http:
  http://localhost/health:
    status: 200
    body:
      - "ok"
```

### Генерация Goss-тестов из текущего состояния

Главная фишка Goss — `goss add` генерирует YAML по результату запроса:

```bash
goss add package nginx
goss add service nginx
goss add file /etc/nginx/nginx.conf
goss add addr tcp:80
goss add process nginx
goss add http http://localhost/health
```

Все собранные ресурсы накапливаются в `goss.yaml` (или через `goss add` по одному). Затем — `goss validate`:

```bash
goss validate
# ✓ nginx: installed
# ✓ tcp:80: listening
```

### Testinfra: модель

Тесты — обычные Python-функции, использующие host-агент:

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

Профиль — папка с `controls/*.rb`:

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

или с обёрткой `dgoss` (docker + goss):

```bash
dgoss run -p 8080:80 app:test goss validate
```

### Сценарий 2: Goss как init-здоровье Kubernetes (startupProbe)

```yaml
startupProbe:
  exec:
    command: ["goss", "validate", "--format", "json"]
```

Идиома: goss в образе + `startupProbe`/`livenessProbe` — быстрое детектирование неготовности. (Подробно про пробы — [Kubernetes liveness/readiness](../Kubernetes/concepts/probes/README.md) при наличии каталога).

### Сценарий 3: Тестирование Ansible-роли через Molecule + Testinfra

Molecule — стандартный цикл для Ansible ролей (см. [Тестирование Ansible-ролей](../Ansible/ansible_testing_with_molecule.md)):

1. `molecule init scenario` — создаёт `verify.yml` с Testinfra.
2. `molecule converge` — применяет роль.
3. `molecule verify` — запускает Testinfra-тесты.

```python
def test_postgres_installed(host):
    assert host.package("postgresql-16").is_installed
    assert host.service("postgresql").is_running
```

### Сценарий 4: Compliance-проверка продакшн-хостов (InSpec)

```bash
inspec exec https://github.com/dev-sec/linux-baseline \
  -t ssh://root@app --sudo -c ~/.inspec/creds.json
```

C профилями обеспечивается соответствие CIS/DISA — они удобны для аудита и до-проверок перед внедрением.

### Сценарий 5: Интеграция в CI/CD pipeline (GitLab)

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

Применение smoke-логики после деплоя — см. [Smoke-тестирование после деплоя](../CI-CD/Testing/smoke_testing.md).

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `cannot connect to the Docker daemon` | dgoss/Testinfra на host без доступа к docker.sock | Настроить `DOCKER_HOST`/права группы docker |
| Goss `timeout waiting for http` | Сервис ещё не поднялся к запуску теста | Добавить ретраи/ожидание: `goss validate --retry=5 --sleep=2` |
| Проверка `service running` падает в контейнере | В контейнере нет systemd | Использовать `process`/`http` вместо `service` в OCI |
| Testinfra не видит SSH-хост | Миск-конфиг анскперта, ключи | `--host='ssh://user@host' -i key`, проверить сетевую доступность |
| Диспропорция прав/owner на разных ОС | Различия базовых образов | Параметризовать тесты по OS (pytest `--pyargs`, метки) |
| InSpec-профиль флакаит semantics | Независимость от порядка/окружения | Использовать `describe file` с `file('modules')` из api, драйвер `sudo` |

## Дополнительная информация

### См. также

- **[TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md#test-driven-infrastructure-tdi)** — методология TDI и сравнительная таблица инструментов (SSoT по подходам).
- **[Тестирование Ansible-ролей](../Ansible/ansible_testing_with_molecule.md)** — Molecule + Testinfra для ролей (SSoT по Ansible-ролам).
- **[Смоук-тестирование после деплоя](../CI-CD/Testing/smoke_testing.md)** — где инфраструктурные проверки используются как smoke.

### Внешние ресурсы

- [Goss на GitHub](https://github.com/goss-org/goss) — исходный код, сборка, releases (v0.4.9).
- [InSpec Documentation](https://docs.chef.io/inspec/) — документация InSpec (profiles, compliance).
- [Testinfra на GitHub](https://github.com/pytest-dev/testinfra) — pytest-фреймворк для инфраструктуры.