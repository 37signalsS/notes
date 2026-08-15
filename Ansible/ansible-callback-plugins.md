# Ansible — разработка Callback-плагинов

## Определения

**Callback-плагин (Callback Plugin)** — это расширение Ansible, которое позволяет перехватывать события в процессе выполнения плейбука (например, начало задачи, успешное выполнение, ошибка) и выполнять произвольные действия: логирование, отправку уведомлений или интеграцию с внешними системами. 

В отличие от модулей, callback-плагины всегда выполняются на **узле управления (Control Node)** в контексте процесса Ansible.

## Основные концепции

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
    *   `v2_playbook_on_start`: Запуск выполнения плейбука.
    *   `v2_playbook_on_stats`: Завершение выполнения, расчет итоговой статистики.
*   **Задачи и Хосты:**
    *   `v2_runner_on_ok`: Успешное выполнение задачи на хосте.
    *   `v2_runner_on_failed`: Ошибка выполнения задачи (возврат `failed`).
    *   `v2_runner_on_unreachable`: Узел недоступен по SSH/WinRM.
    *   `v2_runner_on_skipped`: Задача пропущена из-за условий `when`.
    *   `v2_runner_item_on_ok`: Успешная итерация в цикле (`loop`).

### Метаданные плагина

При разработке необходимо указывать атрибуты класса для корректной регистрации:
*   `CALLBACK_VERSION`: Версия API (текущая — `2.0`).
*   `CALLBACK_TYPE`: Тип плагина (`stdout`, `notification`, `aggregate`).
*   `CALLBACK_NAME`: Имя плагина для использования в конфигурации.

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
    name: log_to_json
    type: notification
    short_description: Записывает результаты выполнения в JSON файл с учетом безопасности
'''

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'log_to_json'

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.log_path = 'ansible_execution_log.json'
        # self._display доступен из CallbackBase для вывода в консоль
        self._display.vvv(f"Инициализация плагина JSON-логов в {self.log_path}")

    def _log_event(self, host, status, result):
        # Проверка no_log для защиты секретов
        if result._result.get('_ansible_no_log', False):
            clean_result = {"censored": "the output has been hidden due to no_log: True"}
        else:
            clean_result = result._result.copy()
            # Удаляем технические поля для чистоты
            clean_result.pop('invocation', None)

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
        self._log_event(result._host.get_name(), 'FAILED', result)

    def v2_runner_on_unreachable(self, result):
        self._log_event(result._host.get_name(), 'UNREACHABLE', result)
```

### Интеграция с внешними системами (ELK / Loki / Slack)

Для промышленного использования предпочтительны готовые плагины из коллекций:

1.  **Loki:** `community.general.loki`. Позволяет отправлять логи напрямую в Grafana Loki через HTTP API.
2.  **ELK (Logstash):** `community.general.logstash`. Отправляет JSON-события через TCP/UDP.
3.  **Slack:** `community.general.slack`. Отправляет итоговую статистику или уведомления о сбоях в каналы Slack.

**Преимущества централизованного сбора:**
*   Аналитика времени выполнения через `ansible.posix.profile_tasks`.
*   Хранение истории изменений для комплаенса и аудита.
*   Мгновенные алерты при критических сбоях плейбуков.

## Дополнительная информация

### Популярные встроенные плагины

*   **`ansible.posix.timer`:** Выводит время выполнения каждого плея и суммарное время в конце.
*   **`ansible.posix.profile_tasks`:** Показывает топ-20 самых медленных задач (незаменимо для оптимизации).
*   **`ansible.builtin.junit`:** Генерирует отчет в формате JUnit XML для интеграции с CI/CD (Jenkins, GitLab).
*   **`community.general.say`:** Использует синтез речи для озвучивания прогресса (macOS/Linux).

### Отладка плагинов

Если плагин не работает:
1.  Проверьте наличие плагина в списке: `ansible-doc -t callback -l`.
2.  Запустите плейбук с повышенной вербозностью: `ansible-playbook -vvv`.
3.  Используйте `self._display.warning("message")` внутри плагина для вывода отладочной информации.

### Рекомендации (Best Practices)

*   **Производительность:** Callback-плагины работают синхронно в основном потоке управления. Долгие сетевые вызовы (например, отправка в API) замедляют выполнение плейбука. Для высоконагруженных систем используйте очереди сообщений (Redis, RabbitMQ) или отправляйте данные в фоновых потоках.
*   **Безопасность и `no_log`:** Всегда проверяйте атрибут `_ansible_no_log` в объекте результата. Игнорирование этого правила приведет к утечке паролей и токенов в логи.
*   **Использование `self._display`:** Вместо `print()` используйте встроенный объект `self._display`. Он поддерживает уровни логирования (`display`, `v`, `vv`, `vvv`, `warning`, `error`) и корректно интегрируется с выводом Ansible.
*   **Совместимость:** Наследуйтесь от класса `CallbackBase` и следуйте спецификации API v2 для гарантии работы в будущих версиях `ansible-core`.

### Смотрите также

*   [Оптимизация производительности Ansible](./ansible_performance_tuning.md) — использование `timer` и `profile_tasks`.
*   [Безопасность в Ansible: лучшие практики](./ansible_security_best_practices.md) — аудит и защита конфигурации.
*   [Разработка собственных модулей](./ansible_custom_modules.md) — сравнение модулей и плагинов.
*   [Официальная документация по Callback Plugins](https://docs.ansible.com/ansible/latest/plugins/callback.html) (EN).
