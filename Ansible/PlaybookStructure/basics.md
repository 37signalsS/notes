# Ansible: структура плейбука

## Определения

**Плейбук (Playbook)** — YAML-файл, содержащий один или несколько «плеев» (`plays`) для описания желаемого состояния системы и оркестрации шагов по его достижению.

**Плей (Play)** — основной строительный блок плейбука. Сопоставляет группу хостов из инвентаря с набором задач, настроек и переменных.

**Задача (Task)** — отдельная атомарная операция, вызывающая конкретный [модуль Ansible](../Modules/ansible_modules_overview.md).

**FQCN (Fully Qualified Collection Name)** — полное имя модуля, включающее пространство имён и имя коллекции (например, `ansible.builtin.apt` вместо `apt`). Использование FQCN обязательно в современных версиях для исключения конфликтов имен.

**Обработчик (Handler)** — специальная задача, которая выполняется только при получении уведомления (`notify`) от другой задачи и только если состояние системы изменилось (`changed`).

## Базовые концепции

### Структура и современный стандарт

Современный плейбук должен быть максимально декларативным, а вся логика — вынесена в [роли](../ansible_roles.md).

```yaml
---
- name: Развертывание веб-приложения
  hosts: web_servers
  become: true
  gather_facts: true
  
  # Ограничение конкурентности
  serial: "25%"
  max_fail_percentage: 10
  
  pre_tasks:
    - name: Проверка доступности API
      ansible.builtin.uri:
        url: https://api.example.com/health
        status_code: 200
      run_once: true

  roles:
    - role: web_server_base
    - role: application_deploy
      vars:
        app_version: "2.1.0"

  tasks:
    - name: Применение специфичной настройки
      ansible.builtin.template:
        src: custom_config.conf.j2
        dest: /etc/app/custom.conf
        owner: root
        group: root
        mode: '0644'
      notify: Перезапуск приложения

  post_tasks:
    - name: Регистрация в мониторинге
      ansible.builtin.uri:
        url: https://mon.example.com/register
        method: POST
        body_format: json
        body:
          host: "{{ ansible_fqdn }}"

  handlers:
    - name: Перезапуск приложения
      ansible.builtin.systemd:
        name: myapp
        state: restarted
```

### Директивы управления выполнением

1.  **Стратегии выполнения (`strategy`)**:
    *   `linear` (по умолчанию): Все хосты завершают одну задачу, прежде чем перейти к следующей.
    *   `free`: Каждый хост проходит через плейбук настолько быстро, насколько может, независимо от других.
    *   `host_pinned`: Похожа на `free`, но удерживает фиксированное количество хостов в работе.
2.  **Пакетная обработка (`serial`)**: Позволяет обновлять хосты частями (число или проценты). Критично для Rolling Updates.
3.  **Контроль ошибок**:
    *   `any_errors_fatal: true`: Прекращает выполнение на всех хостах, если хотя бы один упал.
    *   `max_fail_percentage`: Порог падений, после которого весь плей останавливается.
4.  **Ограничения (`throttle` / `run_once`)**:
    *   `throttle`: Лимит конкурентных задач для конкретного шага (например, чтобы не перегрузить API БД).
    *   `run_once`: Выполняет задачу только на одном хосте из всей группы.

### Иерархия выполнения (Order of Operations)

Ansible строго следует порядку:
1.  **`pre_tasks`**: Проверки и подготовка до ролей.
2.  **`roles`**: Основная логика.
3.  **`tasks`**: Специфичные для конкретного плея действия.
4.  **`post_tasks`**: Финальные штрихи (регистрация, очистка).
5.  **`handlers`**: Выполняются после завершения всех разделов (или при вызове `flush_handlers`).

### Приоритеты и переменные

Внутри плейбука переменные могут определяться на разных уровнях:
*   `vars`: Статические переменные плея.
*   `vars_files`: Подключение внешних YAML-файлов (включая зашифрованные Vault).
*   `vars_prompt`: Интерактивный запрос данных у пользователя.
*   `environment`: Определение переменных окружения (например, `http_proxy`).

## Практические сценарии

### Сценарий 1: Rolling Update с проверкой (Canary-style)

Использование `serial` для постепенного обновления парка серверов.

```yaml
- name: Обновление кластера БД
  hosts: db_nodes
  become: true
  serial: 1  # Сначала один хост, затем остальные
  any_errors_fatal: true

  tasks:
    - name: Установка новой версии
      ansible.builtin.package:
        name: my-db-engine
        state: latest
      notify: Рестарт БД

    - name: Проверка работоспособности после обновления
      ansible.builtin.wait_for:
        port: 5432
        state: started
        timeout: 30

  handlers:
    - name: Рестарт БД
      ansible.builtin.systemd:
        name: postgresql
        state: restarted
```

### Сценарий 2: Bootstrap с установкой Python

Использование `gather_facts: false` и `raw` для первичной подготовки «голых» систем.

```yaml
- name: Первичная подготовка (Bootstrap)
  hosts: new_nodes
  gather_facts: false
  become: true

  tasks:
    - name: Установка Python3 на Ubuntu/Debian
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      changed_when: false
      
    - name: Сбор фактов после установки Python
      ansible.builtin.setup: # Принудительный сбор фактов
```

## Дополнительная информация

* [Управление ходом выполнения](flow_control.md) — условия `when`, циклы и блоки.
* [Переменные и факты](variables.md) — детальная иерархия приоритетов и использование `ansible_facts`.
* [Продвинутые возможности плейбуков](advanced.md) — делегирование (`delegate_to`) и динамические включения.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — как не стоит организовывать структуру проекта.
