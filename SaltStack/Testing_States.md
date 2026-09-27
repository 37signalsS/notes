# Тестирование Salt States

## Определения

- **`test=True`**: Режим dry-run, при котором Salt показывает какие изменения были бы применены, но не выполняет их实际. Используется для проверки перед деплоем.
- **`state.show_sls`**: Команда для отображения скомпилированного состояния SLS-файла (результат Jinja + YAML рендеринга) без выполнения.
- **`state.show_highstate`**: Команда для отображения полного highstate — всех состояний, назначенных миньону через `top.sls`.
- **`state.show_lowstate`**: Команда для отображения низкоуровневого представления (low state) — плоского списка словарей, которые Salt выполнит.
- **salt-lint**: Линтер для SLS-файлов, проверяющий синтаксис YAML, стиевые ошибки и best practices.
- **pre-commit**: Фреймворк для запуска проверок перед коммитом в Git. В контексте Salt — проверка SLS-файлов на ошибки.
- **serverspec / testinfra**: Фреймворки интеграционного тестирования, проверяющие конечное состояние системы после применения Salt states.
- **InSpec**: Фреймворк compliance-тестирования, проверяющий безопасность и конфигурацию систем.
- **`state.test`**: Execution-модуль для запуска `test=True` через API: `salt '*' state.test <state>`.

---

## Основные концепции

### Уровни тестирования Salt

| Уровень | Инструмент | Что проверяет |
|:---|:---|:---|
| **Linting** | salt-lint, yamllint | Синтаксис YAML, стиевые ошибки, типичные ошибки |
| **Dry-run** | `test=True`, `state.show_sls` | Какие изменения будут применены |
| **Unit-тест** | Python unittest, pytest | Логика кастомных модулей |
| **Integration** | serverspec, testinfra | Конечное состояние системы |
| **Compliance** | InSpec, Hubblestack | Соответствие стандартам безопасности |

### Pipeline тестирования

```
Код → git commit → pre-commit hooks (lint) → CI/CD → dry-run → staging → prod
```

---

## Практические сценарии

### 1. Проверка через test=True

```bash
# Dry-run на всех миньонах
salt '*' state.apply nginx test=True

# Dry-run с подробным выводом
salt '*' state.apply nginx test=True --state-output=full

# Dry-run в формате YAML
salt '*' state.apply nginx test=True --out=yaml

# Dry-run через salt-call (локально, без мастера)
salt-call --local state.apply nginx test=True
```

**Пример вывода:**

```
web-01:
  ----------
  pkg_|-nginx_installed_|-nginx_|-installed:
    ----------
    __run_num__:
        0
    changes:
        ----------
    comment:
        Package nginx is already installed
    name:
        nginx
    result:
        True
  ----------
  service_|-nginx_service_|-nginx_|-running:
    ----------
    __run_num__:
        1
    changes:
        ----------
    comment:
        Service nginx is already running
    name:
        nginx
    result:
        True
```

### 2. Просмотр скомпилированного SLS

```bash
# Просмотр конкретного SLS
salt '*' state.show_sls nginx

# Просмотр с指定 окружением
salt '*' state.show_sls nginx saltenv=production

# Просмотр highstate
salt '*' state.show_highstate

# Просмотр low state (плоский список)
salt '*' state.show_lowstate
```

### 3. Настройка salt-lint

**Установка:**

```bash
pip install salt-lint
```

**Конфигурация `.salt-lint`:**

```yaml
# .salt-lint
exclude:
  - '.git'
  - '.kitchen'
  - '.travis.yml'
  - 'Gemfile'

# Правила
201:
  message: "Trailing whitespace"
  level: "warning"

202:
  message: "Missing newline at end of file"
  level: "warning"

203:
  message: "Missing template: jinja"
  level: "warning"

204:
  message: "Line too long"
  level: "warning"
  max_length: 160
```

**Запуск:**

```bash
# Проверка конкретного файла
salt-lint nginx/init.sls

# Проверка всех SLS-файлов
salt-lint salt://**/*.sls

# Проверка с выходным кодом для CI
salt-lint salt://**/*.sls && echo "Lint passed" || echo "Lint failed"
# → Lint passed
```

### 4. Pre-commit hooks для Salt

**Установка pre-commit:**

```bash
pip install pre-commit
```

**Конфигурация `.pre-commit-config.yaml`:**

```yaml
repos:
  - repo: https://github.com/saltstack/salt-lint
    rev: v0.9.2
    hooks:
      - id: salt-lint
        name: Salt Lint
        entry: salt-lint
        language: system
        files: '\.(sls|jinja|j2)$'

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: check-yaml
        name: Check YAML
        files: '\.(sls|yaml|yml)$'
      - id: end-of-file-fixer
        name: Fix End of File
      - id: trailing-whitespace
        name: Fix Trailing Whitespace
```

**Активация:**

```bash
cd /srv/salt
git init
pre-commit install
# → pre-commit installed at .git/hooks/pre-commit
```

**Результат:**

```bash
git commit -m "Update nginx config"
# Salt Lint..............................................Passed
# Check YAML.............................................Passed
# Fix End of File........................................Passed
# Fix Trailing Whitespace................................Passed
```

### 5. CI/CD pipeline для Salt

**GitLab CI:**

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - dry-run
  - deploy

salt-lint:
  stage: lint
  image: python:3.12
  script:
    - pip install salt-lint
    - salt-lint salt://**/*.sls

yaml-lint:
  stage: lint
  image: python:3.12
  script:
    - pip install yamllint
    - yamllint -c .yamllint salt://**/*.sls salt://**/*.yaml

dry-run:
  stage: dry-run
  image: python:3.12-slim
  script:
    - pip install salt
    - salt-call --local state.apply test=True --out=yaml
  only:
    - merge_requests

deploy-staging:
  stage: deploy
  script:
    - salt 'staging-*' state.apply
  only:
    - develop
  when: manual

deploy-prod:
  stage: deploy
  script:
    - salt 'prod-*' state.apply batch=10%
  only:
    - main
  when: manual
```

### 6. Интеграционное тестирование через serverspec

**Установка и настройка:**

```bash
# На тестовом хосте
gem install serverspec
```

**Спецификация:**

```ruby
# spec/salt_nginx_spec.rb
require 'serverspec'

describe 'Nginx' do
  describe package('nginx') do
    it { should be_installed }
  end

  describe service('nginx') do
    it { should be_enabled }
    it { should be_running }
  end

  describe port(80) do
    it { should be_listening }
  end

  describe port(443) do
    it { should be_listening }
  end

  describe file('/etc/nginx/nginx.conf') do
    it { should exist }
    it { should be_file }
    its(:content) { should match 'worker_processes auto' }
  end
end
```

**Запуск после salt apply:**

```bash
salt 'web-01' state.apply nginx
ssh web-01 'cd /tmp && rspec spec/'
# → Nginx
#     Package "nginx"
#       should be installed
#     Service "nginx"
#       should be enabled
#       should be running
#     Port "80"
#       should be listening
#     Port "443"
#       should be listening
#     File "/etc/nginx/nginx.conf"
#       should exist
#       should be file
```

### 7. Тестирование через testinfra (pytest)

**Спецификация:**

```python
# test/test_nginx.py
import testinfra

def test_nginx_installed(host):
    """Проверка установки nginx."""
    pkg = host.package('nginx')
    assert pkg.is_installed

def test_nginx_running(host):
    """Проверка запуска nginx."""
    svc = host.service('nginx')
    assert svc.is_running
    assert svc.is_enabled

def test_nginx_config(host):
    """Проверка конфигурации nginx."""
    f = host.file('/etc/nginx/nginx.conf')
    assert f.exists
    assert f.user == 'root'
    assert f.group == 'root'
    assert f.mode == 0o644
    assert f.contains('worker_processes auto')

def test_nginx_listening(host):
    """Проверка прослушивания портов."""
    sock = host.socket('tcp://0.0.0.0:80')
    assert sock.is_listening

    sock443 = host.socket('tcp://0.0.0.0:443')
    assert sock443.is_listening
```

**Запуск:**

```bash
# Через testinfra (pytest)
pytest test/test_nginx.py --hosts=ssh://web-01

# Или через Salt
salt 'web-01' state.apply nginx
pytest test/test_nginx.py --hosts=web-01
# → 5 passed
```

### 8. Compliance-тестирование через InSpec

```ruby
# spec/compliance/nginx_spec.rb
require 'inspec'

control 'nginx-compliance-001' do
  title 'Nginx must be installed'
  desc 'Nginx package should be installed for web serving'
  impact 1.0

  describe package('nginx') do
    it { should be_installed }
  end
end

control 'nginx-compliance-002' do
  title 'Nginx config must not have server_tokens on'
  desc 'Hide nginx version in HTTP headers'
  impact 0.8

  describe file('/etc/nginx/nginx.conf') do
    its(:content) { should_not match(/server_tokens\s+on/) }
  end
end

control 'nginx-compliance-003' do
  title 'Nginx must use TLS 1.2+'
  desc 'SSL configuration should use modern TLS'
  impact 1.0

  describe file('/etc/nginx/conf.d/ssl.conf') do
    its(:content) { should match(/ssl_protocols.*TLSv1\.[2-3]/) }
  end
end
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `test=True` показывает изменения, но не применяет | Это dry-run, а не apply | Использовать `state.apply` без `test=True` |
| `state.show_sls` показывает ошибки | Ошибка в Jinja-шаблоне | Исправить шаблон, проверить Pillar |
| salt-lint не находит ошибки | Правила не настроены | Проверить `.salt-lint`, обновить salt-lint |
| pre-commit не запускается | Git hooks не установлены | `pre-commit install` в корне репозитория |
| serverspec/testinfra падает | State не применился | Проверить `state.apply`, логи |
| `state.apply` и `test=True` расходятся | Pillar/Grains изменились между запусками | Запускать в одном окружении, кэшировать Pillar |

### Best practices

1. **Всегда `test=True`**: Перед любым `state.apply` в продакшене — dry-run.
2. **salt-lint в CI**: Обязательная проверка SLS-файлов перед коммитом.
3. **Pre-commit hooks**: Автоматическая проверка при каждом коммите.
4. **Интеграционные тесты**: Проверяйте конечное состояние, а не только процесс.
5. **Compliance-тесты**: Регулярная проверка безопасности через InSpec/Hubblestack.
6. **Dry-run в staging**: Тестируйте в staging перед prod.
7. **Параллельные тесты**: Используйте `batch` для параллельного тестирования на нескольких миньонах.
8. **Версионирование тестов**: Храните тесты рядом с SLS-файлами в Git.

### См. также

- [Формулы SaltStack](Formulas.md) — структура переиспользуемых пакетов
- [Кастомные модули](Custom_Modules.md) — расширение функционала
- [Highstate и порядок выполнения](Highstate_and_Execution_Order.md) — как компилируется SLS
