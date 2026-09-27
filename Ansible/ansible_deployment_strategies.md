# Стратегии деплоя и rolling updates в Ansible

## Определения

- **Rolling Update** — поэтапное обновление группы серверов с контролем здоровья между этапами
- **Canary Deployment** — развёртывание на малой подгруппе хостов для тестирования перед полным обновлением
- **Blue-Green Deployment** — параллельное существование двух идентичных сред (Blue и Green) с переключением трафика
- **Health Check** — проверка доступности сервиса после изменений для подтверждения успеха
- **max_fail_percentage** — максимальный допустимый процент ошибок в батче перед прерыванием
- **Serial** — параметр плейбука, определяющий размер батча хостов
- **Drain** — процесс отключения хоста от балансировщика перед обновлением
- **Strategy plugin** — плагин, определяющий алгоритм распределения задач (linear, free, debug)
- **Blast Radius** — масштаб последствий при сбое деплоя; ограничивается `serial` и `max_fail_percentage`
- **Graceful Shutdown** — корректное завершение процесса при остановке сервиса (перехват SIGTERM, завершение активных соединений)
- **Progressive Delivery** — методология поэтапного развёртывания с автоматическими проверками и гейтингом

## Основные концепции

### Архитектура пакетного деплоя

При Rolling Update Ansible обрабатывает хосты группами (батчами). Размер батча задаётся директивой `serial`. После завершения батча Ansible переходит к следующему только при условии успешного выполнения всех задач предыдущего.

Параметры уровня плейбука, управляющие поведением:

- **`serial`** — ограничивает количество хостов в батче. Принимает целое число, процентную строку или список для прогрессивной стратегии.
- **`max_fail_percentage`** — прерывает выполнение, если доля неудачных хостов превышает указанный порог. Работает только совместно с `serial`.
- **`strategy`** — выбирает алгоритм планирования задач. `linear` (по умолчанию) обрабатывает всех хостов в батче синхронно; `free` позволяет каждому хосту двигаться самостоятельно, без ожидания остальных.
- **`any_errors_fatal`** — при `true` любая ошибка на любом хосте немедленно останавливает весь плейбук.
- **`ignore_unreachable`** — при `true` недоступные хосты не прерывают выполнение.

### Rolling Updates

Параметры управления поэтапным обновлением:

```yaml
---
- name: Rolling Update Example
  hosts: webservers
  serial: "25%"              # 25% хостов за раз
  max_fail_percentage: 10    # Допустимо до 10% ошибок
  strategy: linear
  tasks:
    - name: Обновление пакетов
      ansible.builtin.apt:
        name: "*"
        state: latest
        update_cache: true

    - name: Перезапуск сервиса
      ansible.builtin.service:
        name: nginx
        state: restarted

    - name: Проверка здоровья
      ansible.builtin.uri:
        url: "http://localhost/health"
        status_code: 200
      retries: 5
      delay: 5
```

**Порядок выполнения:** 25% хостов → health check → следующие 25% → ...

### Strategy Plugins: linear и free

**`strategy: linear`** (по умолчанию). Все хосты в текущем батче проходят задачу одновременно, затем синхронизируются перед следующей задачей. Гарантирует предсказуемый порядок и упрощает отладку.

**`strategy: free`**. Каждый хост выполняет задачи максимально быстро, без ожидания остальных хостов батча. Полезен для длительных операций на отдельных хостах, где синхронизация не требуется.

```yaml
---
- name: Free Strategy Example
  hosts: webservers
  strategy: free
  tasks:
    - name: Долгая задача на каждом хосте
      ansible.builtin.command: /opt/scripts/long_task.sh

    - name: Быстрая задача
      ansible.builtin.ping:
```

### Health Checks

```yaml
# Использование uri для проверки HTTP
- name: Проверка HTTP
  ansible.builtin.uri:
    url: "http://{{ ansible_host }}:{{ http_port }}/health"
    status_code: 200
  register: health
  retries: 10
  delay: 5
  until: health.status == 200

# Проверка TCP-порта
- name: Проверка порта
  ansible.builtin.wait_for:
    port: "{{ http_port }}"
    delay: 5
    timeout: 30
```

### Rollback стратегии

Подробные стратегии отката с примерами `block/rescue`, blue/green, canary и миграций БД описаны в **[Стратегиях отката (rollback) в Ansible](../examples/ansible_rollback_strategies.md)**.

```

### Zero-downtime деплой

```yaml
# Drain перед обновлением
- name: Отключение от балансировщика
  ansible.builtin.uri:
    url: "http://{{ lb_host }}/api/drain/{{ inventory_hostname }}"
    method: POST
  delegate_to: localhost

# Обновление
- name: Обновление сервера
  ansible.builtin.apt:
    name: nginx
    state: latest

# Включение на балансировщике
- name: Включение на балансировщике
  ansible.builtin.uri:
    url: "http://{{ lb_host }}/api/enable/{{ inventory_hostname }}"
    method: POST
  delegate_to: localhost
```

### Blue-Green Deployment

```yaml
---
- name: Blue-Green Deployment
  hosts: localhost
  vars:
    active_env: blue
    target_env: green
  tasks:
    - name: Определение активной среды
      ansible.builtin.set_fact:
        active_group: "{{ 'webservers_blue' if active_env == 'blue' else 'webservers_green' }}"
        target_group: "{{ 'webservers_green' if active_env == 'blue' else 'webservers_blue' }}"

    - name: Развёртывание на target
      ansible.builtin.include_role:
        name: deploy_app
      vars:
        target_hosts: "{{ target_group }}"

    - name: Health check target
      ansible.builtin.uri:
        url: "http://{{ hostvars[groups[target_group][0]]['ansible_host'] }}/health"
        status_code: 200
      register: target_health
      retries: 10
      delay: 5
      until: target_health.status == 200

    - name: Переключение трафика
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/switch/{{ target_env }}"
        method: POST
      when: target_health.status == 200
```

## Предварительные требования

### Системные требования

- **ansible-core** 2.20+ (рекомендуется 2.21+)
- **Python** 3.12+ на control node
- **Python** 3.9+ на managed nodes
- **sshpass** или настроенный SSH-доступ без пароля
- **curl** или **httpie** для отладки health-эндпоинтов

### Проверка окружения

```bash
python3 --version       # → Python 3.12.x
ansible --version       # → ansible-core 2.21.x
ansible-config dump     # → проверка forks, timeout, strategy
```

### Структура инвентаря

```ini
# inventory.ini
[webservers]
web1 ansible_host=192.168.1.10
web2 ansible_host=192.168.1.11
web3 ansible_host=192.168.1.12

[webservers_blue]
web1 ansible_host=192.168.1.10
web2 ansible_host=192.168.1.11

[webservers_green]
web3 ansible_host=192.168.1.12
web4 ansible_host=192.168.1.13

[lb]
localhost ansible_host=127.0.0.1
```

## Практические сценарии

### Rolling Update Nginx с Health Check

```yaml
---
- name: Rolling Update Nginx
  hosts: webservers
  serial: 1
  max_fail_percentage: 0
  pre_tasks:
    - name: Получение предыдущей версии пакета
      ansible.builtin.package_facts:
        manager: auto

  tasks:
    - name: Отключение от балансировщика
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/disable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      ignore_errors: true

    - name: Ожидание завершения активных соединений
      ansible.builtin.command: sleep 30

    - name: Обновление Nginx
      ansible.builtin.apt:
        name: nginx
        state: latest
        update_cache: true

    - name: Перезапуск Nginx
      ansible.builtin.service:
        name: nginx
        state: restarted

    - name: Health check
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}/health"
        status_code: 200
      register: health
      retries: 10
      delay: 5
      until: health.status == 200

    - name: Включение на балансировщике
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/enable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      when: health.status == 200

  post_tasks:
    - name: Очистка кэша apt
      ansible.builtin.command: apt-get clean
      when: ansible_facts['os_family'] == "Debian"
```

### Percentage-based Batches

```yaml
---
- name: Percentage-based Rolling Update
  hosts: all
  serial: "10%"
  max_fail_percentage: 5
  tasks:
    - name: Обновление пакетов
      ansible.builtin.yum:
        name: "*"
        state: latest
      when: ansible_os_family == "RedHat"

    - name: Обновление пакетов (Debian)
      ansible.builtin.apt:
        name: "*"
        state: latest
        update_cache: true
      when: ansible_os_family == "Debian"

    - name: Перезапуск сервиса
      ansible.builtin.service:
        name: "{{ service_name }}"
        state: restarted
```

### Progressive Serial Strategy

Прогрессивное увеличение размера батча снижает риск каскадного сбоя:

```yaml
---
- name: Progressive Deployment
  hosts: webservers
  serial:
    - 1       # Canary: первый хост
    - 5       # Pilot: небольшая группа
    - "25%"   # Rolling: четверть парка
    - "100%"  # Full: остальные
  max_fail_percentage: 10
```

### Canary Deployment

```yaml
---
- name: Canary Deployment
  hosts: webservers
  serial: 1
  tasks:
    - name: Развёртывание на canary (1 хост)
      ansible.builtin.include_tasks: deploy.yml
      when: inventory_hostname == groups['webservers'][0]

    - name: Мониторинг canary
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}/metrics"
        return_content: true
      register: canary_metrics
      until: "'error_rate' in canary_metrics.content and canary_metrics.content.split('error_rate')[1].split()[0]|float < 0.01"
      retries: 30
      delay: 10
      when: inventory_hostname == groups['webservers'][0]

    - name: Развёртывание на остальные хосты
      ansible.builtin.include_tasks: deploy.yml
      when: inventory_hostname != groups['webservers'][0]
```

### Длинные операции с async/poll

Для обновлений, превышающих таймаут SSH-сессии, используйте асинхронный запуск:

```yaml
---
- name: Async OS Update
  hosts: webservers
  serial: "25%"
  tasks:
    - name: Запуск обновления ОС в фоне
      ansible.builtin.dnf:
        name: "*"
        state: latest
      async: 3600
      poll: 0
      register: update_job

    - name: Ожидание завершения обновления
      ansible.builtin.async_status:
        jid: "{{ update_job.ansible_job_id }}"
      register: job_result
      until: job_result.finished
      retries: 60
      delay: 30

    - name: Проверка здоровья после обновления
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}/health"
        status_code: 200
      when: job_result.finished
```

### Перезапуск после ошибки с clear_host_errors

```yaml
---
- name: Deploy with Retry
  hosts: webservers
  max_fail_percentage: 50
  tasks:
    - name: Попытка деплоя
      block:
        - name: Копирование артефакта
          ansible.builtin.copy:
            src: app.tar.gz
            dest: /opt/app/

        - name: Перезапуск сервиса
          ansible.builtin.service:
            name: myapp
            state: restarted

        - name: Health check
          ansible.builtin.uri:
            url: http://localhost:8080/health
            status_code: 200
          register: health
          retries: 5
          delay: 10
          until: health.status == 200

      rescue:
        - name: Остановка сервиса перед повторной попыткой
          ansible.builtin.service:
            name: myapp
            state: stopped

        - name: Очистка состояния хоста
          ansible.builtin.meta: clear_host_errors
```

### Кастомные Strategy Plugins

```yaml
# Free strategy — каждый хост движется максимально быстро
- name: Free Strategy Example
  hosts: webservers
  strategy: free
  tasks:
    - name: Долгая задача
      ansible.builtin.command: /opt/scripts/long_task.sh
    - name: Быстрая задача
      ansible.builtin.ping:
```

## Операции и команды

### Директивы управления деплоем

| Директива | Уровень | Тип | Описание |
| :--- | :--- | :--- | :--- |
| `serial` | play | int / str / list | Размер батча хостов. `1`, `"25%"`, `[1, 5, "25%"]`. |
| `max_fail_percentage` | play | int | Максимальный процент ошибок в батче перед остановкой. `0` — останов при первой ошибке. |
| `strategy` | play | str | Алгоритм планирования: `linear` (по умолчанию) или `free`. |
| `any_errors_fatal` | play / task | bool | Немедленная остановка всего плейбука при любой ошибке. |
| `ignore_unreachable` | play / task | bool | Продолжать выполнение при недоступных хостах. |
| `throttle` | task | int | Максимальное количество одновременных выполнений задачи. Защищает внешние API от rate limits. |
| `run_once` | task | bool | Выполнить задачу только на первом хосте батча. |
| `delegate_to` | task | str | Выполнить задачу на указанном хосте (например, `localhost` для вызовов API балансировщика). |
| `async` | task | int | Максимальное время выполнения задачи в секундах. |
| `poll` | task | int | `0` — запустить в фоне и продолжить; положительное — ждать завершения с опросом. |
| `retries` | task | int | Количество повторов для `until`. |
| `delay` | task | int | Пауза между повторами в секундах. |
| `check_mode` | play / task | bool | Принудительное выполнение задачи даже при `--check`. |

### Переменные окружения

| Переменная | Значение | Описание |
| :--- | :--- | :--- |
| `ANSIBLE_STRATEGY` | `linear` / `free` | Переопределение strategy plugin по умолчанию. |
| `ANSIBLE_FORCE_COLOR` | `true` / `false` | Цветной вывод для логов деплоя. |
| `ANSIBLE_HOST_KEY_CHECKING` | `false` | Отключение проверки SSH-ключей в автоматизации. |

### Полезные команды

```bash
# Запуск с явным указанием serial
ansible-playbook deploy.yml --serial 5

# Проверка стратегии без применения изменений
ansible-playbook deploy.yml --serial "25%" --check --diff

# Принудительный запуск с strategy=free
ANSIBLE_STRATEGY=free ansible-playbook deploy.yml
```

## Диагностика

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `max_fail_percentage` не останавливает плей | Директива задана без `serial` | Добавьте `serial`. `max_fail_percentage` работает только с батчированием. |
| Хост остаётся в состоянии `failed` после отката | Ошибка не очищена | Используйте `meta: clear_host_errors` в блоке `rescue` перед повторной попыткой. |
| Health check падает из-за кэширования | `uri` кэширует результат | Добавьте `force: true` или уникальный query-параметр (`?t={{ ansible_date_time.epoch }}`). |
| Балансировщик получает трафик до завершения проверки | Отсутствует `until` с `retries` | Всегда используйте `until` + `retries` + `delay` для health check. |
| Деплой зависает на долгих задачах | strategy: linear с большими батчами | Перейдите на `strategy: free` или увеличьте `timeout` в `ansible.cfg`. |
| Недоступные хосты прерывают деплой | `ignore_unreachable` не установлен | Установите `ignore_unreachable: true` или исключите хосты из батча через `when`. |

### Диагностические команды

```bash
# Проверка доступности хостов перед деплоем
ansible webservers -m ping

# Просмотр фактов для проверки готовности
ansible webservers -m setup -a 'filter=ansible_os*'

# Проверка запущенных сервисов
ansible webservers -m service -a 'name=nginx state=started'
```

## Лучшие практики

- Используйте `serial` вместо массового обновления всего парка одновременно. Начинайте с `serial: 1` для критических сервисов.
- Всегда добавляйте health check с `until`, `retries` и `delay` после изменения конфигурации или перезапуска сервиса.
- Для длительных операций используйте `async` + `poll` с последующей проверкой через `async_status`.
- Используйте `strategy: free` только когда задачи на разных хостах действительно независимы. По умолчанию оставляйте `linear`.
- В блоке `rescue` используйте `meta: clear_host_errors` перед повторной попыткой деплоя на том же хосте.
- Для взаимодействия с балансировщиком всегда используйте `delegate_to: localhost` и `ignore_errors: true` с явной проверкой результата.
- Устанавливайте `max_fail_percentage: 0` для критически важных сервисов, где любой сбой должен остановить весь процесс.
- Разделяйте drain, деплой и enable на отдельные `pre_tasks` и `post_tasks` для читаемости.
- Храните предыдущую версию артефакта до подтверждения успешного health check нового деплоя.
- Используйте `run_once` для задач, которые должны выполниться один раз на батч (например, уведомление в Slack о начале деплоя).
- Тестируйте деплой на окружении, максимально приближённом к production, перед раскаткой на боевых хостах.

## Дополнительная информация

- [Производительность](./ansible_performance_tuning.md) — оптимизация выполнения плейбуков
- [Выполнение плейбуков](./ansible_playbook_execution.md) — режимы запуска
- [Продвинутая структура плейбуков](./PlaybookStructure/advanced.md) — сложные сценарии
- [Поток управления и обработка ошибок](./PlaybookStructure/flow_control.md) — `block/rescue`, `ignore_errors`, `any_errors_fatal`
