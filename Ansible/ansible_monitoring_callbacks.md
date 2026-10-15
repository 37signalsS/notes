# Ansible — callback-плагины для мониторинга и уведомлений

## Определения

**Callback-плагин** — плагин, перехватывающий события Ansible (`v2_playbook_on_start`, `v2_runner_on_ok`, `v2_runner_on_failed`, `v2_playbook_on_stats`) и выполняющий внешние действия: отправку метрик, уведомлений, запись в журнал.

**Callback event** — событие, вызывающее callback. Основные события версии v2:
- `v2_playbook_on_start` — запуск плейбука
- `v2_runner_on_ok` — успешное выполнение задачи
- `v2_runner_on_failed` — ошибка выполнения задачи
- `v2_runner_on_skipped` — задача пропущена
- `v2_runner_on_unreachable` — хост недоступен
- `v2_playbook_on_stats` — завершение плейбука, итоговая статистика

**Callback module** — модуль, реализующий логику callback. Наследуется от `ansible.plugins.callback.CallbackBase`.

**Aggregate callback** — плагин, собирающий данные со всех хостов и выполняющий действие в конце выполнения плейбука (`v2_playbook_on_stats`).

**Notification callback** — плагин, отправляющий уведомления о событиях во внешние системы по мере их возникновения.

**Metrics backend** — система сбора метрик (Prometheus, StatsD, InfluxDB). В on-prem окружении используется Prometheus + Pushgateway или самописный HTTP-экспортер.

**Notification channel** — способ уведомления: email, Slack, Telegram, ntfy, Matrix.

**Structured logging** — запись событий в структурированном формате (JSON, key=value) для последующего поиска и агрегации в системах логирования.

**Audit trail** — последовательность записей о событиях Ansible, обеспечивающая прослеживаемость изменений инфраструктуры.

---

## Основные концепции

### Архитектура callback-плагинов

Callback-плагины выполняются на **контрольном узле** в контексте процесса Ansible. В отличие от модулей, которые выполняются на управляемых хостах, callback-плагины обрабатывают результаты выполнения и метаданные.

```
Playbook Engine
    │
    ├─→ stdout callback (вывод в консоль) — только один активен
    ├─→ notification callback (отправка уведомлений по мере событий)
    └─→ aggregate callback (итоговый отчет по всем хостам)
```

### Типы callback-плагинов

| Тип | Назначение | Примеры |
| :--- | :--- | :--- |
| `stdout` | Форматирование вывода в консоль | `yaml`, `json`, `debug`, `minimal` |
| `notification` | Отправка уведомлений о событиях | `community.general.slack`, кастомные плагины |
| `aggregate` | Сбор итоговой статистики | `ansible.posix.timer`, `ansible.posix.profile_tasks` |

### Встроенные callback-плагины

| Плагин | Тип | Назначение |
| :--- | :--- | :--- |
| `default` | stdout | Стандартный вывод |
| `yaml` | stdout | Красивый YAML-вывод |
| `json` | stdout | JSON-формат вывода |
| `timer` | aggregate | Замер общего времени выполнения |
| `profile_tasks` | aggregate | Замер времени каждой задачи |
| `profile_roles` | aggregate | Замер времени по ролям |
| `mail` | notification | Отправка email при ошибках |
| `log_plays` | aggregate | Запись итогов выполнения в лог-файл |

### Жизненный цикл событий

Ansible вызывает методы плагина при наступлении определенных событий:

**Плейбук:**
- `v2_playbook_on_start(playbook)` — запуск плейбука
- `v2_playbook_on_stats(stats)` — завершение, расчет итоговой статистики

**Задачи:**
- `v2_runner_on_ok(result)` — успешное выполнение
- `v2_runner_on_failed(result)` — ошибка выполнения
- `v2_runner_on_skipped(result)` — задача пропущена
- `v2_runner_on_unreachable(result)` — хост недоступен

**Другие:**
- `v2_playbook_on_task_start(task, is_conditional)` — начало задачи
- `v2_playbook_on_play_start(play)` — начало play

### Структура кастомного callback-плагина

```python
# callback_plugins/my_callback.py
from ansible.plugins.callback import CallbackBase

DOCUMENTATION = r'''
---
module: my_callback
short_description: Custom callback for monitoring
description:
  - Custom callback plugin for metrics and notifications.
type: notification
'''

EXAMPLES = r'''
# ansible.cfg
[defaults]
callbacks_enabled = my_callback
callback_plugins = ./callback_plugins
'''

RETURN = r'''
msg:
  description: Result message
  returned: always
  type: str
'''

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'my_callback'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.start_time = None
        self.events = []

    def v2_playbook_on_start(self, playbook):
        self.start_time = time.time()
        self._log(f"Playbook started: {playbook._file_name}")

    def v2_runner_on_ok(self, result):
        host = result._host.get_name()
        task = result._task.get_name()
        self._log(f"OK: {host} - {task}")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        host = result._host.get_name()
        task = result._task.get_name()
        self._log(f"FAILED: {host} - {task}")

    def v2_playbook_on_stats(self, stats):
        duration = time.time() - self.start_time
        self._log(f"Playbook finished in {duration:.2f}s")

    def _log(self, message):
        # Реализация логирования
        pass
```

### Конфигурация в ansible.cfg

```ini
[defaults]
# Активация callback-плагинов
callbacks_enabled = timer, profile_tasks, mail, my_callback

# Выбор stdout-плагина
stdout_callback = yaml

# Пути поиска callback-плагинов
callback_plugins = ./callback_plugins:/usr/share/ansible/plugins/callback

# Включение всех плагинов без явного указания (не рекомендуется для production)
# callback_whitelist = *

# Логирование Ansible
log_path = /var/log/ansible/playbook.log
```

---

## Предварительные требования

### Версии ПО

- **ansible-core**: 2.20+
- **Python на контрольном узле**: 3.12+
- **Операционная система**: GNU/Linux (RHEL 9+, Debian 12+, Ubuntu 22.04+)

### Зависимости Python на контрольном узле

```bash
# Установка базовых зависимостей
pip install \
  ansible-core>=2.20 \
  requests>=2.32 \
  prometheus-client>=0.20 \
  jmespath>=1.0 \
  netaddr>=1.2

# Для уведомлений в Slack/Telegram
pip install \
  slack-sdk>=3.30 \
  python-telegram-bot>=20.0

# Для работы с email
pip install \
  secure-smtplib
```

### Переменные окружения

```bash
# Slack
export ANSIBLE_CALLBACK_SLACK_WEBHOOK_URL="https://hooks.internal.example.com/services/xxx/yyy/zzz"
export ANSIBLE_CALLBACK_SLACK_CHANNEL="#ansible-notifications"

# Telegram
export ANSIBLE_CALLBACK_TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
export ANSIBLE_CALLBACK_TELEGRAM_CHAT_ID="123456789"

# Email
export ANSIBLE_CALLBACK_MAIL_TO="ops@example.com"
export ANSIBLE_CALLBACK_MAIL_FROM="ansible@example.com"
```

### Структура проекта

```
project/
├── callback_plugins/
│   ├── __init__.py
│   ├── prometheus_metrics.py
│   ├── slack_notify.py
│   ├── telegram_notify.py
│   └── audit_logger.py
├── inventory/
├── group_vars/
└── playbooks/
```

---

## Практические сценарии

### Включение встроенных callback-плагинов

#### profile_tasks для замера времени задач

```ini
# ansible.cfg
[defaults]
callbacks_enabled = profile_tasks
stdout_callback = yaml
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

#### timer для замера общего времени

```ini
# ansible.cfg
[defaults]
callbacks_enabled = timer
```

Выводит общее время выполнения плейбука.

#### mail для email-уведомлений

```ini
# ansible.cfg
[defaults]
callbacks_enabled = mail

[email]
mail_to=ops@example.com
mail_from=ansible@example.com
mail_subject=Ansible: {{ playbook_name }} finished
smtp_host=smtp.example.com
smtp_port=587
smtp_user=ansible@example.com
smtp_pass={{ vault_smtp_password }}
```

### Создание кастомного callback для Prometheus

```python
# callback_plugins/prometheus_metrics.py
from ansible.plugins.callback import CallbackBase
from prometheus_client import Counter, Gauge, start_http_server
import time

TASK_OK = Counter('ansible_tasks_ok', 'Successful tasks', ['host', 'task'])
TASK_FAILED = Counter('ansible_tasks_failed', 'Failed tasks', ['host', 'task'])
PLAYBOOK_DURATION = Gauge('ansible_playbook_duration_seconds', 'Playbook duration')

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'prometheus_metrics'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()
        start_http_server(8000)
        self.start_time = None

    def v2_playbook_on_start(self, playbook):
        self.start_time = time.time()

    def v2_playbook_on_stats(self, stats):
        if self.start_time:
            PLAYBOOK_DURATION.set(time.time() - self.start_time)

    def v2_runner_on_ok(self, result):
        TASK_OK.labels(
            host=result._host.get_name(),
            task=result._task.get_name()
        ).inc()

    def v2_runner_on_failed(self, result, ignore_errors=False):
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
callbacks_enabled = community.general.slack

# Переменные окружения
# export ANSIBLE_CALLBACK_SLACK_WEBHOOK_URL=https://hooks.internal.example.com/services/xxx
# export ANSIBLE_CALLBACK_SLACK_CHANNEL=#deployments
# export ANSIBLE_CALLBACK_SLACK_USERNAME=Ansible Bot
```

### Интеграция с Telegram

```python
# callback_plugins/telegram_notify.py
from ansible.plugins.callback import CallbackBase
import requests
import os

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'telegram_notify'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()
        self.token = os.environ.get('ANSIBLE_CALLBACK_TELEGRAM_BOT_TOKEN')
        self.chat_id = os.environ.get('ANSIBLE_CALLBACK_TELEGRAM_CHAT_ID')

    def _send(self, text):
        if not self.token or not self.chat_id:
            return
        requests.post(
            f'https://api.telegram.org/bot{self.token}/sendMessage',
            json={'chat_id': self.chat_id, 'text': text, 'parse_mode': 'Markdown'}
        )

    def v2_runner_on_failed(self, result, ignore_errors=False):
        host = result._host.get_name()
        task = result._task.get_name()
        self._send(f"[FAILED] {host} - {task}")

    def v2_playbook_on_stats(self, stats):
        lines = ["[STATS] Playbook finished:"]
        for host in sorted(stats.processed):
            s = stats.summarize(host)
            lines.append(f"{host}: ok={s['ok']} changed={s['changed']} failed={s['failures']}")
        self._send("\n".join(lines))
```

### Структурированное логирование в файл

```python
# callback_plugins/audit_logger.py
from ansible.plugins.callback import CallbackBase
import json
import os
import time

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'audit_logger'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()
        self.log_path = os.environ.get('ANSIBLE_AUDIT_LOG', '/var/log/ansible/audit.jsonl')
        self.start_time = None
        self.playbook = None

    def v2_playbook_on_start(self, playbook):
        self.start_time = time.time()
        self.playbook = os.path.basename(playbook._file_name)

    def v2_runner_on_ok(self, result):
        self._write({
            'event': 'task_ok',
            'playbook': self.playbook,
            'host': result._host.get_name(),
            'task': result._task.get_name(),
            'changed': result._result.get('changed', False),
            'timestamp': time.time()
        })

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._write({
            'event': 'task_failed',
            'playbook': self.playbook,
            'host': result._host.get_name(),
            'task': result._task.get_name(),
            'error': result._result.get('msg', 'unknown'),
            'timestamp': time.time()
        })

    def v2_playbook_on_stats(self, stats):
        duration = time.time() - self.start_time
        self._write({
            'event': 'playbook_end',
            'playbook': self.playbook,
            'duration': duration,
            'summary': {h: stats.summarize(h) for h in stats.processed},
            'timestamp': time.time()
        })

    def _write(self, record):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, 'a') as f:
            f.write(json.dumps(record) + "\n")
```

### Фильтрация событий и rate limiting

```python
# callback_plugins/filtered_notify.py
from ansible.plugins.callback import CallbackBase
import time

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'filtered_notify'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()
        self.last_notification = {}
        self.rate_limit_seconds = 60
        self.ignore_tasks = ['debug', 'wait_for', 'meta']

    def _should_notify(self, host, task_name):
        now = time.time()
        key = f"{host}:{task_name}"
        if key in self.ignore_tasks:
            return False
        if key in self.last_notification:
            if now - self.last_notification[key] < self.rate_limit_seconds:
                return False
        self.last_notification[key] = now
        return True

    def v2_runner_on_failed(self, result, ignore_errors=False):
        host = result._host.get_name()
        task = result._task.get_name()
        if self._should_notify(host, task):
            self._send_alert(f"FAILED: {host} - {task}")
```

### Интеграция с Grafana через Loki

```python
# callback_plugins/loki_logger.py
from ansible.plugins.callback import CallbackBase
import requests
import json
import time

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'loki_logger'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()
        self.loki_url = os.environ.get('ANSIBLE_LOKI_URL', 'http://loki:3100/loki/api/v1/push')
        self.labels = {'job': 'ansible', 'environment': os.environ.get('ANSIBLE_ENV', 'production')}

    def _send_to_loki(self, event, data):
        payload = {
            'streams': [{
                'stream': {**self.labels, 'event': event},
                'values': [[str(int(time.time() * 1e9)), json.dumps(data)]]
            }]
        }
        try:
            requests.post(self.loki_url, json=payload, timeout=5)
        except Exception:
            pass

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._send_to_loki('task_failed', {
            'host': result._host.get_name(),
            'task': result._task.get_name(),
            'error': result._result.get('msg', 'unknown')
        })
```

### Интеграция с ntfy

```python
# callback_plugins/ntfy_notify.py
from ansible.plugins.callback import CallbackBase
import requests

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'ntfy_notify'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()
        self.ntfy_url = os.environ.get('ANSIBLE_NTFY_URL', 'https://ntfy.internal.example.com/ansible')
        self.ntfy_token = os.environ.get('ANSIBLE_NTFY_TOKEN')

    def _send(self, message, priority='high'):
        headers = {}
        if self.ntfy_token:
            headers['Authorization'] = f'Bearer {self.ntfy_token}'
        requests.post(self.ntfy_url, data=message, headers=headers)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        host = result._host.get_name()
        task = result._task.get_name()
        self._send(f"FAILED: {host} - {task}")
```

---

## Операции и команды

### Параметры конфигурации в ansible.cfg

| Параметр | Описание |
| :--- | :--- |
| `callbacks_enabled` | Список активных callback-плагинов через запятую |
| `stdout_callback` | Единственный активный stdout-плагин |
| `callback_plugins` | Пути поиска callback-плагинов, разделённые `:` |
| `log_path` | Путь к файлу лога Ansible |
| `bin_ansible_callbacks` | `True` — загрузка callback-плагинов при выполнении через `ansible` CLI |

### Полезные команды

```bash
# Запуск с включенными callback-плагинами (env-переменная на один запуск)
ANSIBLE_CALLBACKS_ENABLED=timer,profile_tasks ansible-playbook site.yml

# Запуск с конкретным stdout-плагином
ANSIBLE_STDOUT_CALLBACK=debug ansible-playbook site.yml

# Проверка доступных callback-плагинов
ansible-doc -t callback -l

# Просмотр документации конкретного плагина
ansible-doc -t callback community.general.slack

# Проверка загруженных callback-плагинов
ansible-config dump | grep -i callback

# Тест callback-плагина
ANSIBLE_CALLBACKS_ENABLED=my_callback ansible-playbook playbooks/deploy.yml -vvv

# Проверка путей поиска плагинов
ansible-config dump | grep -i callback_plugins
```

### Валидация callback-плагина

```bash
# Проверка синтаксиса Python
python3 -m py_compile callback_plugins/prometheus_metrics.py

# Проверка доступности метрик Prometheus
curl http://localhost:8000/metrics | grep ansible_

# Проверка доставки сообщений в Slack/Telegram
ansible-playbook playbooks/test.yml -e "test_notify=true"
```

---

## Диагностика

### Типичные ошибки

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `CALLBACK_NEEDS_WHITELIST` и плагин не работает | Плагин не указан в `callbacks_enabled` | Добавьте имя плагина в `callbacks_enabled` |
| `ImportError: No module named 'prometheus_client'` | Библиотека не установлена на контрольном узле | `pip install prometheus-client` |
| `ModuleNotFoundError` для кастомного плагина | Неправильный путь в `callback_plugins` | Проверьте `callback_plugins` в `ansible.cfg` |
| `Permission denied` при записи в лог | Директория лога недоступна | Создайте директорию: `mkdir -p /var/log/ansible && chown $USER /var/log/ansible` |
| Slack webhook не доставляет сообщения | Неверный URL или firewall | Проверьте `curl -X POST <webhook_url>` |
| `callbacks_enabled` игнорируется | Нет `callback_plugins` или плагин не найден | Проверьте пути поиска через `ansible-config dump` |
| Метрики не появляются в Prometheus | Pushgateway недоступен или порт закрыт | Проверьте доступность `http://pushgateway:9091` |
| `UnicodeEncodeError` в callback | Необработанные символы в выводе | Добавьте `ensure_ascii=False` при сериализации JSON |
| Дублирующиеся алерты | Отсутствие rate limiting | Реализуйте `_should_notify()` с порогом времени |

### Диагностические команды

```bash
# Проверка конфигурации callback-плагинов
ansible-config dump | grep -i callback

# Проверка доступности модулей Python
python3 -c "import prometheus_client, requests, telegram; print('OK')"

# Проверка доставки Slack webhook
curl -X POST "$ANSIBLE_CALLBACK_SLACK_WEBHOOK_URL" -H 'Content-Type: application/json' -d '{"text":"test"}'

# Проверка Loki endpoint
curl -s -o /dev/null -w "%{http_code}" http://loki:3100/ready

# Проверка метрик Prometheus
curl -s http://localhost:8000/metrics | grep ansible_tasks_ok

# Просмотр логов Ansible
tail -f /var/log/ansible/playbook.log

# Проверка JSON Lines лога
jq '.' /var/log/ansible/audit.jsonl | tail -20
```

---

## Лучшие практики

1. **Централизованное хранение конфигурации** — callback-плагины и их конфигурация хранятся в Git. Никаких ручных изменений на production.
2. **CALLBACK_NEEDS_WHITELIST** — используйте `True` для notification/aggregate плагинов. Это предотвращает случайную активацию в окружении, где плагин не настроен.
3. **Rate limiting** — ограничьте частоту уведомлений для повторяющихся ошибок (например, 1 алерт в 5 минут на один host:task).
4. **Фильтрация событий** — игнорируйте служебные задачи (`debug`, `wait_for`, `meta`) в уведомлениях.
5. **Безопасность** — храните токены Slack/Telegram в переменных окружения или HashiCorp Vault, не коммитьте в Git.
6. **Идемпотентность** — callback-плагины не должны изменять состояние инфраструктуры. Они только наблюдают и уведомляют.
7. **Обработка ошибок в callback** — оборачивайте сетевые вызовы (`requests.post`) в `try/except`. Ошибка в callback не должна прерывать плейбук.
8. **Структурированное логирование** — используйте JSON Lines (JSONL) для аудита. Это позволяет парсить логи `jq` и загружать в Loki/Elasticsearch.
9. **Атомарная запись** — для файловых логов используйте `with open(path, 'a')` внутри метода, чтобы избежать блокировок при параллельных запусках.
10. **Валидация перед деплоем** — проверяйте синтаксис callback-плагинов через `python3 -m py_compile` в CI.
11. **Разделение окружений** — для dev/staging/prod используйте отдельные каналы Slack/Telegram и отдельные метки в Prometheus.
12. **Мониторинг самих callback-плагинов** — добавляйте метрики о работе самого callback-плагина (ошибки отправки, задержки).
13. **Graceful degradation** — если внешний сервис (Slack, Prometheus) недоступен, callback должен записывать ошибку в локальный лог и продолжать работу.
14. **Тестирование** — используйте `ansible-playbook --syntax-check` и Molecule для тестирования callback-плагинов.
15. **Документация** — каждый кастомный плагин должен содержать блоки `DOCUMENTATION`, `EXAMPLES`, `RETURN`.

---

## Дополнительная информация

### Связанные разделы

- [Разработка callback-плагинов](./ansible-callback-plugins.md) — общая разработка callback-плагинов, lifecycle events, примеры.
- [Ansible Semaphore](./ansible_semaphore.md) — веб-интерфейс для Ansible с встроенными уведомлениями.
- [Основные концепции Ansible](./ansible_core_concepts.md) — общие концепции Ansible, события, выполнение плейбуков.

### Стандарты и документация

- [Ansible Callback Plugins](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/callback_plugins.html) — документация по callback-плагинам.
- [Prometheus Python Client](https://prometheus.io/docs/instrumenting/writing_clientlibs/#python) — интеграция Prometheus с Python-приложениями.
- [Grafana Loki](https://grafana.com/docs/loki/latest/) — агрегация логов в on-prem окружении.
