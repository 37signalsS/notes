# Callback-плагины для мониторинга и уведомлений

## Определения

- **Callback plugin** — плагин, перехватывающий события Ansible (task started, task failed, playbook finished) и выполняющий внешние действия
- **Callback event** — событие, вызывающее callback (`v2_playbook_on_start`, `runner_on_ok`, `runner_on_failed`)
- **Callback module** — модуль, реализующий логику callback (форматирование, отправка)
- **Prometheus metrics** — метрики, отправляемые в Prometheus через HTTP
- **Slack Webhook** — URL для отправки сообщений в канал Slack
- **Notification channel** — способ уведомления (email, slack, pagerduty, webhook)
- **Callback results** — словарь с результатами задачи (event, task, host, res)

## Основные концепции

### Архитектура callbacks

Callback-плагины делятся на три типа:

1. **stdout callbacks** — изменяют формат вывода в консоль (только один активен)
2. **notification callbacks** — отправляют уведомления о событиях во внешние системы
3. **aggregate callbacks** — собирают данные со всех хостов и выполняют действие в конце

```
Playbook Engine
    │
    ├─→ stdout callback (вывод в консоль)
    ├─→ notification callback (отправка уведомлений)
    └─→ aggregate callback (итоговый отчет)
```

### Встроенные callback-плагины

| Плагин | Тип | Назначение |
|---|---|---|
| `default` | stdout | Стандартный вывод |
| `yaml` | stdout | Красивый YAML-вывод |
| `json` | stdout | JSON-формат вывода |
| `timer` | aggregate | Замер общего времени выполнения |
| `profile_tasks` | aggregate | Замер времени каждой задачи |
| `profile_roles` | aggregate | Замер времени по ролям |
| `mail` | notification | Отправка email при ошибках |

### Настройка в ansible.cfg

```ini
[defaults]
# Активация callback-плагинов
callback_enabled = timer, profile_tasks, mail

# Выбор stdout-плагина
stdout_callback = yaml

# Пути поиска callback-плагинов
callback_plugins = ./callback_plugins:/usr/share/ansible/plugins/callback
```

### Custom Callbacks

Структура кастомного callback-плагина:

```python
# callback_plugins/prometheus_callback.py
from ansible.plugins.callback import CallbackBase
import json
import requests

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'prometheus'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.stats = {}

    def v2_playbook_on_stats(self, stats):
        """Сбор метрик в конце выполнения"""
        for host in stats.processed:
            s = stats.summarize(host)
            self.stats[host] = {
                'ok': s['ok'],
                'changed': s['changed'],
                'failures': s['failures'],
                'unreachable': s['unreachable'],
                'skipped': s['skipped']
            }

        # Отправка в Prometheus
        self._send_to_prometheus()

    def _send_to_prometheus(self):
        """Отправка метрик в Prometheus Pushgateway"""
        metrics = []
        for host, data in self.stats.items():
            for key, value in data.items():
                metrics.append(f'ansible_task_{{host="{host}",status="{key}"}} {value}')

        requests.post(
            'http://prometheus:9091/metrics/job/ansible',
            data='\n'.join(metrics)
        )
```

### Интеграция с мониторингом

**Prometheus:**
```python
# Отправка метрик
def v2_runner_on_ok(self, result):
    host = result._host.get_name()
    task = result._task.get_name()
    self.metrics.append(f'ansible_task_ok{{host="{host}",task="{task}"}} 1')

def v2_runner_on_failed(self, result):
    host = result._host.get_name()
    task = result._task.get_name()
    self.metrics.append(f'ansible_task_failed{{host="{host}",task="{task}"}} 1')
```

**StatsD:**
```python
def v2_runner_on_ok(self, result):
    self.statsd.incr('ansible.task.ok')

def v2_runner_on_failed(self, result):
    self.statsd.incr('ansible.task.failed')
```

### Интеграция с уведомлениями

**Slack callback:**
```yaml
# ansible.cfg
[defaults]
callback_enabled = community.general.slack

# environment variable
export ANSIBLE_CALLBACK_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz"
export ANSIBLE_CALLBACK_SLACK_CHANNEL="#ansible-notifications"
```

**Telegram callback:**
```python
def v2_playbook_on_stats(self, stats):
    message = self._format_stats(stats)
    requests.post(
        f'https://api.telegram.org/bot{self.token}/sendMessage',
        json={'chat_id': self.chat_id, 'text': message}
    )
```

## Практические сценарии

### Включение profile_tasks для замера времени

```ini
# ansible.cfg
[defaults]
callback_enabled = profile_tasks
```

Результат:
```
Tuesday 01 January 2024  12:00:00 +0300 (0:00:02.123)  0:00:02.123 ***
=============================================
Install packages --------------------- 12.34s
Copy configuration -------------------- 2.56s
Restart service ----------------------- 0.12s
=============================================
```

### Настройка timer callback

```ini
# ansible.cfg
[defaults]
callback_enabled = timer
```

Выводит общее время выполнения плейбука.

### Включение yaml.stdout для красивого вывода

```ini
# ansible.cfg
[defaults]
stdout_callback = yaml
```

### Создание кастомного callback для Prometheus

```python
# callback_plugins/prometheus.py
from ansible.plugins.callback import CallbackBase
from prometheus_client import Counter, Gauge, start_http_server

TASK_OK = Counter('ansible_tasks_ok', 'Successful tasks', ['host', 'task'])
TASK_FAILED = Counter('ansible_tasks_failed', 'Failed tasks', ['host', 'task'])
PLAYBOOK_DURATION = Gauge('ansible_playbook_duration_seconds', 'Playbook duration')

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'prometheus'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()
        start_http_server(8000)
        self.start_time = None

    def v2_playbook_on_start(self, playbook):
        import time
        self.start_time = time.time()

    def v2_playbook_on_stats(self, stats):
        import time
        if self.start_time:
            PLAYBOOK_DURATION.set(time.time() - self.start_time)

    def v2_runner_on_ok(self, result):
        TASK_OK.labels(
            host=result._host.get_name(),
            task=result._task.get_name()
        ).inc()

    def v2_runner_on_failed(self, result):
        TASK_FAILED.labels(
            host=result._host.get_name(),
            task=result._task.get_name()
        ).inc()
```

### Интеграция со Slack

```yaml
# requirements.yml
collections:
  - name: community.general
    version: ">=7.0.0"
```

```ini
# ansible.cfg
[defaults]
callback_enabled = community.general.slack

# Переменные окружения
ANSIBLE_CALLBACK_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
ANSIBLE_CALLBACK_SLACK_CHANNEL=#deployments
ANSIBLE_CALLBACK_SLACK_USERNAME=Ansible Bot
ANSIBLE_CALLBACK_SLACK_DISPLAY_OK_HOSTS=true
ANSIBLE_CALLBACK_SLACK_DISPLAY_FAILED_HOSTS=true
```

### Отправка email через mail callback

```ini
# ansible.cfg
[defaults]
callback_enabled = mail

[email]
mail_to=ops@example.com
mail_from=ansible@example.com
mail_subject=Ansible: {{ playbook_name }} finished
smtp_host=smtp.example.com
smtp_port=587
smtp_user=ansible@example.com
smtp_pass={{ vault_smtp_password }}
```

### Настройка callback-плагина в ansible.cfg

```ini
[defaults]
# Включение плагинов
callback_enabled = timer, profile_tasks, mail, custom_callback

# Пути поиска
callback_plugins = ./plugins/callback:/usr/share/ansible/plugins/callback

# Stdout плагин
stdout_callback = yaml
```

```bash
# Запуск с включением callback-плагинов
ansible-playbook site.yml --callback-enabled=timer,profile_tasks

# Запуск с конкретным stdout
ansible-playbook site.yml --stdout=debug
```

## Дополнительная информация

- [Callback-плагины](./ansible-callback-plugins.md) — разработка кастомных callback
- [Безопасность](./ansible_security_best_practices.md) — защита данных и vault
- [Ansible Semaphore](./ansible_semaphore.md) — веб-интерфейс для Ansible