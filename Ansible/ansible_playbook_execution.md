# Ansible: Выполнение Playbook

## Определения

**ansible-playbook** — утилита командной строки для запуска и выполнения Playbook Ansible на Managed Node.

**Play** — логически сгруппированный набор задач (Tasks), применяемый к определенной группе хостов из Inventory.

**Task (Задача)** — атомарная операция в Playbook, вызывающая конкретный Ansible Module для достижения желаемого состояния системы.

**PLAY RECAP** — итоговая сводка выполнения Playbook, отображающая статус выполнения Tasks по каждому хосту (`ok`, `changed`, `unreachable`, `failed`).

## Основные концепции

### Запуск Playbook

Playbook запускаются с помощью команды `ansible-playbook`. Целевые серверы определяются в файле [Inventory](ansible_setup_and_config.md).

```bash
ansible-playbook -i inventory.ini --ask-pass playbook.yml
# → Выполнение задач из playbook.yml на серверах из inventory.ini...
```

**Ключевые элементы команды:**

* `ansible-playbook`: основная команда для инициации выполнения Playbook.
* `-i inventory.ini`: указывает путь к файлу Inventory.
* `--ask-pass` (или `-k`): запрашивает пароль для SSH-подключения к Managed Node.
* `playbook.yml`: путь к файлу [Playbook](PlaybookStructure/basics.md), который необходимо выполнить.

### Анализ вывода выполнения

**PLAY**

```text
PLAY [Install and start nginx] ********************************************
```

Обозначает начало выполнения Play — логически сгруппированного набора Tasks, применяемого к определенной группе хостов.

**TASK**

```text
TASK [Gathering Facts] ******************************************************
ok: [ws01]

TASK [install nginx] *******************************************************
changed: [ws01]
```

* `Gathering Facts`: первая Task, выполняемая по умолчанию для сбора системных данных (Facts) на Managed Node.
* `changed`: статус выполнения, означающий, что Task внесла изменения в систему (например, установила пакет или изменила конфигурационный файл).
* `ok`: статус выполнения, означающий, что система уже находилась в желаемом состоянии, и никаких изменений не потребовалось.

**PLAY RECAP**

```text
PLAY RECAP *****************************************************************
ws01                       : ok=5    changed=4    unreachable=0    failed=0
```

Итоговая сводка по всем хостам, участвовавшим в выполнении Playbook.

* `ok`: количество Tasks, успешно выполненных без изменений.
* `changed`: количество Tasks, успешно выполненных с изменениями.
* `unreachable`: количество хостов, к которым Ansible не смог подключиться.
* `failed`: количество хостов, на которых произошел сбой хотя бы одной Task (`failed > 0` означает, что выполнение завершилось с ошибкой).

### Ключевые опции командной строки

Команда `ansible-playbook` поддерживает множество опций для гибкого управления выполнением.

* `--inventory` (`-i`): указывает путь к файлу Inventory. Пример:

    ```bash
    ansible-playbook -i /path/to/inventory.ini playbook.yml
    # → Выполнение Playbook с указанным Inventory...
    ```

* `--limit`: ограничивает выполнение Playbook только указанными хостами или группами. Пример:

    ```bash
    # Выполнить только на хосте web1
    ansible-playbook -i inventory.ini --limit web1 playbook.yml
    # → Выполнение только для хоста web1...
    ```

* `--list-hosts`: выводит список хостов, на которых будет выполнен Playbook, без фактического запуска. Полезно для проверки правильности Inventory и фильтров.

    ```bash
    ansible-playbook -i inventory.ini site.yml --list-hosts
    # →   hosts (2):
    # →     web1
    # →     web2
    ```

* `--list-tasks`: выводит список всех задач, которые будут выполнены, без фактического запуска. Полезно для анализа порядка выполнения и проверки тегов.

    ```bash
    ansible-playbook -i inventory.ini site.yml --list-tasks
    # →   play #1 (webservers): webservers  TAGS: []
    # →     tasks:
    # →       install nginx TAGS: [nginx]
    ```

* `--check` (dry-run): запускает Playbook в режиме тестирования — задачи выполняются, но реальные изменения на хостах не вносятся. Модули сообщают, что *изменилось бы*, но не применяют изменения.

    ```bash
    ansible-playbook -i inventory.ini site.yml --check --diff
    # → Отображение ожидаемых изменений без их фактического применения...
    ```

* `--diff`: показывает изменения, которые будут внесены в файлы, в стиле Git `diff`. Комбинируется с `--check` для контроля перед деплоем.
* `--step`: включает пошаговое выполнение. Перед каждой Task система будет спрашивать подтверждение (`y`/`n`/`c`) на запуск.
* `--skip-tags`: пропускает задачи с указанными тегами. Полезно для исключения опциональных задач.

    ```bash
    ansible-playbook -i inventory.ini site.yml --skip-tags optional
    # → Пропуск задач с тегом 'optional'...
    ```

* `--tags`: выполняет только задачи с указанными тегами.

    ```bash
    ansible-playbook -i inventory.ini site.yml --tags nginx
    # → Выполнение только задач с тегом 'nginx'...
    ```

* `--force-handlers`: заставляет выполнять обработчики (Handlers) даже если выполнение Playbook завершилось с ошибкой. Рекомендуется для CI/CD-пайплайнов, чтобы гарантировать выполнение очистки или перезапуска сервисов.
* `--become`: указывает на необходимость повышения привилегий (`sudo`) для выполнения задач на Managed Node.
* `--ask-pass` (`-k`): запрашивает пароль для SSH-подключения.
* `--ask-become-pass` (`-K`): запрашивает пароль для повышения привилегий (`sudo`).

## Практические сценарии

### Интеграция с Vagrant: указание Inventory

При использовании Ansible в качестве Provisioner для Vagrant могут возникать проблемы с обнаружением хостов, если Inventory определен в отдельном файле.

* **Проблема**: Vagrant по умолчанию создает временный файл Inventory только для создаваемых им машин и не знает о группах, определенных в вашем статическом файле `inventory.ini`. Это приводит к предупреждениям `[WARNING]: Could not match supplied host pattern...` и ошибкам `skipping: no hosts matched`.
* **Решение**: чтобы Vagrant использовал ваш кастомный файл Inventory, необходимо явно указать путь к нему в `Vagrantfile` внутри блока конфигурации Ansible.

    **Пример в `Vagrantfile`:**

    ```ruby
    Vagrant.configure("2") do |config|
      # ...
      config.vm.provision "ansible" do |ansible|
        ansible.playbook = "playbook.yml"
        # Явно указываем путь к файлу инвентаря
        ansible.inventory_path = "path/to/your/inventory.ini"
      end
      # ...
    end
    ```

    Это заставит Ansible использовать правильный Inventory, и он сможет находить хосты и группы, определенные в нем.

## Дополнительная информация

### Смотрите также

* [Оптимизация производительности](ansible_performance_tuning.md) — стратегии ускорения выполнения Playbook.
* [Управление потоком выполнения](PlaybookStructure/flow_control.md) — работа с тегами, условиями и циклами при выполнении.
* [Применение конфигураций с Ansible Pull](ansible_pull.md) — альтернативный pull-режим.
