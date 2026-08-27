# Ansible — разработка Callback-плагинов

## Определения

**Callback-плагин (Callback Plugin)** — это расширение Ansible, которое позволяет перехватывать события в процессе выполнения плейбука (например, начало задачи, успешное выполнение, ошибка) и выполнять произвольные действия: логирование, отправку уведомлений или интеграцию с внешними системами.

В отличие от модулей, callback-плагины всегда выполняются на **узле управления (Control Node)** в контексте процесса Ansible и не взаимодействуют напрямую с управляемыми хостами.

**Callback-плагин** является частью системы плагинов Ansible и относится к типу расширений, которые перехватывают события жизненного цикла выполнения плейбука. Существуют и другие типы плагинов: action, inventory, connection, filter, lookup — каждый отвечает за свой уровень взаимодействия.

## Основные концепции

### Архитектура Callback-плагинов

Callback-плагины работают на **узле управления (Control Node)** и перехватывают события из движка Ansible. В отличие от модулей (которые выполняются на управляемых хостах), callback-плагины обрабатывают результаты выполнения и метаданные, а не сами команды.

```
Control Node                    Managed Hosts
┌─────────────────────┐        ┌──────────────────┐
│  Playbook Engine    │        │   Module Exec    │
│  ┌───────────────┐  │        │   (yum, apt,     │
│  │ CallbackMgr  │──┼───────▶│    template...)  │
│  │  ├─ stdout    │  │◀───────┤                  │
│  │  ├─ timer     │  │ Result │                  │
│  │  ├─ notification│  │        └──────────────────┘
│  │  └─ custom    │  │
│  └───────────────┘  │
└─────────────────────┘
```

### Типы Callback-плагинов

1.  **stdout:** Плагины, отвечающие за вывод в консоль. В Ansible может быть активен только **один** stdout-плагин (например, `yaml`, `debug`, `minimal`). Настраивается через `stdout_callback` в `ansible.cfg`.
2.  **aggregate:** Плагины, которые собирают данные со всех хостов и выполняют действие в конце выполнения (например, формирование итогового отчета).
3.  **notification:** Отправка уведомлений о событиях во внешние системы (ELK, Loki, Slack, Telegram) по мере их возникновения.

### Местоположение и FQCN

Начиная с Ansible 2.10, плагины рекомендуется поставлять в составе коллекций.
*   **Локальные плагины:** Размещаются в директории `callback_plugins/` рядом с плейбуком или ролью.
*   **Плагины коллекций:** Используют полное имя (**FQCN**), например `ansible.posix.timer` или `community.general.logstash`.
*   **Пути поиска:** Регулируются параметром `callback_plugins` в `ansible.cfg`.

### Жизненный цикл событий

Ansible вызывает методы плагина (наследуемые от `CallbackBase`) при наступлении определенных событий. Основные методы версии v2:

*   **Плейбук:**
    *   `v2_playbook_on_start`: Запуск выполнения плейбука. Вызывается один раз при старте.
    *   `v2_playbook_on_stats`: Завершение выполнения, расчет итоговой статистики.
    *   `v2_playbook_on_task_start`: Начало выполнения задачи (до проверки `when`).
    *   `v2_playbook_on_play_start`: Начало выполнения play.
    *   `v2_playbook_on_no_hosts_remaining`: Все хосты недоступны или завершились с ошибкой.
*   **Задачи и Хосты:**
    *   `v2_runner_on_ok`: Успешное выполнение задачи на хосте.
    *   `v2_runner_on_failed`: Ошибка выполнения задачи (возврат `failed`).
    *   `v2_runner_on_unreachable`: Узел недоступен по SSH/WinRM.
    *   `v2_runner_on_skipped`: Задача пропущена из-за условий `when`.
    *   `v2_runner_on_async_poll`: Ожидание завершения асинхронной задачи.
    *   `v2_runner_on_async_ok`: Асинхронная задача завершилась успешно.
    *   `v2_runner_on_async_failed`: Асинхронная задача завершилась с ошибкой.
*   **Итерации (Loop):**
    *   `v2_runner_item_on_ok`: Успешная итерация в цикле (`loop`).
    *   `v2_runner_item_on_failed`: Ошибка в итерации цикла.
    *   `v2_runner_item_on_skipped`: Итерация пропущена.
    *   `v2_runner_item_on_retry`: Итерация повторяется (через `until`).

### Метаданные плагина

При разработке необходимо указывать атрибуты класса для корректной регистрации:

*   `CALLBACK_VERSION`: Версия API (текущая — `2.0`).
*   `CALLBACK_TYPE`: Тип плагина (`stdout`, `notification`, `aggregate`).
*   `CALLBACK_NAME`: Имя плагина для использования в конфигурации.
*   `CALLBACK_NEEDS_WHITELIST`: Требуется ли включение в `callbacks_enabled` (по умолчанию `False` для stdout, `True` для notification/aggregate).

### Метаданные DOCUMENTATION и EXAMPLES

Аналогично модулям, callback-плагины должны содержать блоки `DOCUMENTATION`, `EXAMPLES` и `RETURN`:

```python
DOCUMENTATION = r'''
---
module: my_callback
short_description: Custom callback plugin for logging
description:
    - Logs playbook execution events to a JSON file.
    - Supports no_log filtering for sensitive data.
options:
    log_path:
        description: Path to the log file
        type: str
        default: ansible_log.json
        env:
            - name: ANSIBLE_CALLBACK_LOG_PATH
'''

EXAMPLES = r'''
# ansible.cfg
# [defaults]
# callbacks_enabled = my_callback
# callback_plugins = ./callback_plugins
'''
```

## Практические сценарии

### Включение плагинов

Плагины включаются в файле `ansible.cfg`. Для современных версий Ansible рекомендуется использовать полное имя (FQCN):

```ini
[defaults]
# Пути поиска кастомных плагинов
callback_plugins = ./my_plugins/callback

# Включение обычных плагинов (список через запятую)
callbacks_enabled = ansible.posix.timer, ansible.posix.profile_tasks, my_custom_callback

# Изменение формата вывода в консоль (только один)
stdout_callback = community.general.yaml
```

### Разработка кастомного плагина для логирования

Создайте файл `callback_plugins/log_to_json.py`.

#### Пример: Плагин с защитой данных и продвинутым логированием

```python
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import os
from datetime import datetime
from ansible.plugins.callback import CallbackBase

DOCUMENTATION = r'''
---
module: log_to_json
short_description: Logs playbook events to JSON file
description:
    - Records task execution results to a JSON lines file.
    - Automatically filters no_log content for security.
type: notification
options:
    log_path:
        description: Path to the log file
        type: str
        default: ansible_execution_log.json
'''

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'log_to_json'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.log_path = os.environ.get(
            'ANSIBLE_CALLBACK_LOG_PATH',
            'ansible_execution_log.json'
        )
        self._display.vvv(f"Инициализация плагина JSON-логов в {self.log_path}")

    def _log_event(self, host, status, result):
        # Проверка no_log для защиты секретов
        if result._result.get('_ansible_no_log', False):
            clean_result = {"censored": "the output has been hidden due to no_log: True"}
        else:
            clean_result = result._result.copy()
            # Удаляем технические поля для чистоты
            clean_result.pop('invocation', None)
            clean_result.pop('_ansible_no_log', None)

        data = {
            'timestamp': datetime.now().isoformat(),
            'host': host,
            'status': status,
            'task': result._task.get_name(),
            'action': result._task.action,
            'result': clean_result
        }

        with open(self.log_path, 'a') as f:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')

    def v2_runner_on_ok(self, result):
        self._log_event(result._host.get_name(), 'OK', result)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        status = 'FAILED' if not ignore_errors else 'IGNORED'
        self._log_event(result._host.get_name(), status, result)

    def v2_runner_on_unreachable(self, result):
        self._log_event(result._host.get_name(), 'UNREACHABLE', result)

    def v2_runner_on_skipped(self, result):
        self._log_event(result._host.get_name(), 'SKIPPED', result)

    def v2_runner_item_on_ok(self, result):
        self._log_event(result._host.get_name(), 'ITEM_OK', result)

    def v2_runner_item_on_failed(self, result):
        self._log_event(result._host.get_name(), 'ITEM_FAILED', result)
```

### Пример: Плагин-уведомления в Slack

```python
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError
from ansible.plugins.callback import CallbackBase

DOCUMENTATION = r'''
---
module: slack_notify
short_description: Sends playbook notifications to Slack
description:
    - Sends task results and summary to a Slack channel.
type: notification
options:
    webhook_url:
        description: Slack incoming webhook URL
        type: str
        required: true
        env:
            - name: SLACK_WEBHOOK_URL
    channel:
        description: Slack channel name
        type: str
        default: '#ansible-logs'
'''

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'slack_notify'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
        self.channel = os.environ.get('SLACK_CHANNEL', '#ansible-logs')
        if not self.webhook_url:
            self._display.warning("SLACK_WEBHOOK_URL не установлен")

    def _send_slack(self, message):
        if not self.webhook_url:
            return
        payload = json.dumps({
            "channel": self.channel,
            "text": message,
            "username": "Ansible Bot",
            "icon_emoji": ":robot_face:"
        }).encode('utf-8')
        try:
            req = Request(self.webhook_url, data=payload)
            req.add_header('Content-Type', 'application/json')
            urlopen(req, timeout=10)
        except URLError as e:
            self._display.warning(f"Ошибка отправки в Slack: {e}")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        host = result._host.get_name()
        task = result._task.get_name()
        msg = f":x: *FAILED* `{task}` on `{host}`"
        self._send_slack(msg)

    def v2_runner_on_unreachable(self, result):
        host = result._host.get_name()
        msg = f":rotating_light: *UNREACHABLE* `{host}`"
        self._send_slack(msg)

    def v2_playbook_on_stats(self, stats):
        hosts = sorted(stats.processed.keys())
        summary = []
        for h in hosts:
            s = stats.summarize(h)
            summary.append(
                f"`{h}`: ok={s['ok']} changed={s['changed']} "
                f"failures={s['failures']} unreachable={s['unreachable']}"
            )
        msg = ":clipboard: *Playbook Summary*\n" + "\n".join(summary)
        self._send_slack(msg)
```

### Пример: Плагин-анализатор производительности

```python
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = r'''
---
module: task_timer
short_description: Measures and reports task execution times
description:
    - Tracks time spent on each task.
    - Reports slowest tasks at playbook completion.
type: aggregate
'''

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'task_timer'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.task_times = {}
        self.playbook_start = None

    def v2_playbook_on_task_start(self, task, is_conditional):
        import time
        self.current_task_start = time.time()
        self.current_task_name = task.get_name()

    def v2_runner_on_ok(self, result):
        import time
        if hasattr(self, 'current_task_start'):
            elapsed = time.time() - self.current_task_start
            task_name = self.current_task_name
            host = result._host.get_name()
            key = f"{host}:{task_name}"
            self.task_times[key] = elapsed

    def v2_playbook_on_stats(self, stats):
        if not self.task_times:
            return
        self._display.banner("SLOWEST TASKS")
        sorted_tasks = sorted(
            self.task_times.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        for task_key, elapsed in sorted_tasks:
            self._display.display(
                f"  {elapsed:6.2f}s  {task_key}"
            )
```

### Интеграция с внешними системами (ELK / Loki / Slack)

Для промышленного использования предпочтительны готовые плагины из коллекций:

1.  **Loki:** `community.general.loki`. Позволяет отправлять логи напрямую в Grafana Loki через HTTP API.
2.  **ELK (Logstash):** `community.general.logstash`. Отправляет JSON-события через TCP/UDP.
3.  **Slack:** `community.general.slack`. Отправляет итоговую статистику или уведомления о сбоях в каналы Slack.
4.  **Email:** `community.general.mail`. Отправляет отчеты по email при завершении плейбука.
5.  **Syslog:** `community.general.syslog`. Отправляет события в syslog-сервер.

**Преимущества централизованного сбора:**
*   Аналитика времени выполнения через `ansible.posix.profile_tasks`.
*   Хранение истории изменений для комплаенса и аудита.
*   Мгновенные алерты при критических сбоях плейбуков.
*   Корреляция событий Ansible с инцидентами в мониторинге.

## Дополнительная информация

### Популярные встроенные плагины

*   **`ansible.posix.timer`:** Выводит время выполнения каждого play и суммарное время в конце.
*   **`ansible.posix.profile_tasks`:** Показывает топ-20 самых медленных задач (незаменимо для оптимизации).
*   **`ansible.posix.profile_roles`:** Аналог `profile_tasks` для ролей.
*   **`ansible.builtin.junit`:** Генерирует отчет в формате JUnit XML для интеграции с CI/CD (Jenkins, GitLab).
*   **`community.general.say`:** Использует синтез речи для озвучивания прогресса (macOS/Linux).
*   **`ansible.builtin.default`:** Стандартный вывод (stdout по умолчанию).
*   **`ansible.builtin.minimal`:** Компактный вывод для скриптов и CI/CD.
*   **`ansible.builtin.yaml`:** Форматированный вывод в формате YAML (читаемый).
*   **`ansible.builtin.debug`:** Детальный вывод с полной информацией о результатах.

### Тестирование Callback-плагинов

Тестирование callback-плагинов требует проверки вызова правильных методов и корректной обработки данных:

```python
import pytest
from unittest.mock import MagicMock, patch
from callback_plugins.log_to_json import CallbackModule

@pytest.fixture
def callback():
    with patch('builtins.open', create=True):
        return CallbackModule()

def test_v2_runner_on_ok(callback):
    result = MagicMock()
    result._host.get_name.return_value = 'web01'
    result._task.get_name.return_value = 'Install nginx'
    result._task.action = 'apt'
    result._result = {'changed': False, 'msg': 'OK'}

    callback.v2_runner_on_ok(result)

    assert callback.log_path == 'ansible_execution_log.json'

def test_no_log_filtering(callback):
    result = MagicMock()
    result._host.get_name.return_value = 'db01'
    result._task.get_name.return_value = 'Set password'
    result._task.action = 'user'
    result._result = {'changed': True, '_ansible_no_log': True}

    callback._log_event('db01', 'OK', result)
    # Проверяем что файл создан, но пароль не записан
```

### Отладка плагинов

Если плагин не работает:
1.  Проверьте наличие плагина в списке: `ansible-doc -t callback -l`.
2.  Запустите плейбук с повышенной вербозностью: `ansible-playbook -vvv`.
3.  Используйте `self._display.warning("message")` внутри плагина для вывода отладочной информации.
4.  Проверьте, что плагин добавлен в `callbacks_enabled` в `ansible.cfg`.
5.  Убедитесь, что файл плагина находится в одной из директорий `callback_plugins`.

### Диагностические команды

```bash
# Список доступных callback-плагинов
ansible-doc -t callback -l

# Документация по конкретному плагину
ansible-doc -t callback ansible.posix.timer

# Проверка плейбука с отладкой плагинов
ansible-playbook -vvv playbook.yml

# Проверка количества плагинов
ansible-doc -t callback -l | wc -l

# Поиск плагинов по имени
ansible-doc -t callback -l | grep -i slack
```

### Таблица типовых ошибок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Плагин не загружается | Файл не в `callback_plugins/` или не в `callbacks_enabled` | Проверьте путь и `ansible.cfg` |
| `AttributeError: 'NoneType'` | Плагин вызывается до инициализации `__init__` | Всегда вызывайте `super().__init__()` |
| Секреты в логах | Отсутствие проверки `_ansible_no_log` | Проверяйте `result._result.get('_ansible_no_log', False)` |
| `ImportError` при запуске | Отсутствие зависимостей в `ansible-core` | Используйте только стандартную библиотеку Python |
| stdout-плагин не применяется | Использован неправильный `CALLBACK_TYPE` | Убедитесь, что тип — `stdout`, а не `notification` |
| Плагин вызывается дважды | Два плагина одного типа зарегистрированы | Проверьте `callbacks_enabled` — оставьте только нужные |
| `KeyError` в метаданных | Отсутствует обязательный атрибут класса | Добавьте `CALLBACK_VERSION`, `CALLBACK_TYPE`, `CALLBACK_NAME` |
| Плагин не виден в `ansible-doc` | Ошибка синтаксиса Python | Проверьте плагин командой `python -c "import callback_plugins.my_plugin"` |

### Рекомендации (Best Practices)

*   **Производительность:** Callback-плагины работают синхронно в основном потоке управления. Долгие сетевые вызовы (например, отправка в API) замедляют выполнение плейбука. Для высоконагруженных систем используйте очереди сообщений (Redis, RabbitMQ) или отправляйте данные в фоновых потоках.
*   **Безопасность и `no_log`:** Всегда проверяйте атрибут `_ansible_no_log` в объекте результата. Игнорирование этого правила приведет к утечке паролей и токенов в логи.
*   **Использование `self._display`:** Вместо `print()` используйте встроенный объект `self._display`. Он поддерживает уровни логирования (`display`, `v`, `vv`, `vvv`, `warning`, `error`) и корректно интегрируется с выводом Ansible.
*   **Совместимость:** Наследуйтесь от класса `CallbackBase` и следуйте спецификации API v2 для гарантии работы в будущих версиях `ansible-core`.
*   **Блокировка вызовов:** Избегайте блокировки вызовов в `__init__`. Инициализируйте переменные, но не выполняйте сетевые операции до первого вызова метода.
*   **Идемпотентность:** Callback-плагин не должен изменять состояние системы. Он только обрабатывает результаты и отправляет их во внешние системы.
*   **Обработка ошибок:** Всегда оборачивайте сетевые вызовы в блоки `try/except`. Ошибка в callback-плагине не должна прерывать выполнение плейбука.

### Смотрите также

*   [Оптимизация производительности Ansible](./ansible_performance_tuning.md) — использование `timer` и `profile_tasks`.
*   [Безопасность в Ansible: лучшие практики](./ansible_security_best_practices.md) — аудит и защита конфигурации.
*   [Разработка собственных модулей](./ansible_custom_modules.md) — сравнение модулей и плагинов.
