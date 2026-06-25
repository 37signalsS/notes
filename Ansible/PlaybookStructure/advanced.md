# Ansible: Продвинутые возможности плейбуков

## Определения

- **Статическое включение (`import_tasks`, `import_role`)**: Содержимое файла или роли вставляется в плейбук на этапе парсинга (до его выполнения). Такие включения не могут использовать циклы (`loop`).
- **Динамическое включение (`include_tasks`, `include_role`)**: Файл или роль подключаются в процессе выполнения плейбука. Этот метод позволяет использовать циклы и условные выражения, применяемые к самому включению.
- **Делегирование (`delegate_to`)**: Выполнение конкретной задачи на другом хосте (чаще всего `localhost`), а не на целевом хосте из инвентаря.

## Основные концепции

### Статическое и динамическое включение

Выбор между `import` и `include` — это выбор между производительностью и гибкостью.

- **Используйте `import_*`**, когда структура плейбука заранее известна и не меняется. Это немного производительнее, так как все файлы считываются один раз в начале.
- **Используйте `include_*`**, когда вам нужно динамически подключать задачи в зависимости от переменных, в цикле, или применять к самому включению условные операторы (`when`). Это основной инструмент для создания адаптивных плейбуков.

### Делегирование задач

`delegate_to` — ключевой механизм для взаимодействия с системами, которые не являются целевыми хостами. Например, при деплое приложения вам может понадобиться:

1. Скачать артефакт на `localhost`.
2. Добавить IP нового сервера в систему мониторинга, обратившись к ее API с `localhost`.
3. Скопировать артефакт с `localhost` на целевой хост.

`delegate_to: localhost` работает с **любым модулем** Ansible. Это не особенность отдельных модулей, а универсальный механизм: выполнение задачи просто переносится с целевого хоста из `hosts` на хост, указанный в `delegate_to`. Например, модуль `community.docker.docker_container`, обычно работающий на managed-node, при `delegate_to: localhost` выполнится на контрольном узле.

## Практические сценарии

### Сценарий 1: Динамическое включение задач под конкретную ОС

```yaml
- name: Включить задачи для Debian-подобных систем
  ansible.builtin.include_tasks: debian_specific.yml
  when: ansible_facts['os_family'] == "Debian"

- name: Включить задачи для RedHat-подобных систем
  ansible.builtin.include_tasks: redhat_specific.yml
  when: ansible_facts['os_family'] == "RedHat"
```

### Сценарий 2: Выполнение задачи на `localhost`

Частый случай — поиск файлов на управляющей машине перед их копированием на целевые хосты.

```yaml
- name: Найти .war артефакты на контрольном узле
  ansible.builtin.find:
    paths: /path/to/local/artifacts
    patterns: "*.war"
  delegate_to: localhost
  register: found_artifacts
  run_once: true # Важно, чтобы задача выполнилась только один раз
```

### Сценарий 3: Отладка плейбуков

- **`--check`**: "Сухой прогон" (dry run) без внесения реальных изменений. Показывает, что *было бы* изменено.
- **`--diff`**: Показывает изменения в файлах (например, в шаблонах). Используется вместе с `--check`.
- **`--step`**: Интерактивное пошаговое выполнение. Ansible будет спрашивать подтверждение перед выполнением каждой задачи.
- **`--limit`**: Ограничение выполнения на конкретном хосте или группе.
- **`--start-at-task`**: Начало выполнения с указанной по имени задачи.
- **Модуль `debug`**: Вывод значений переменных или сообщений.

  ```yaml
  - name: Показать содержимое переменной
    ansible.builtin.debug:
      var: my_variable
  ```

- **Отладчик (`debugger`)**: Позволяет войти в интерактивную сессию отладки при выполнении задачи.

  ```yaml
  - name: Задача с точкой останова
    ansible.builtin.template:
      src: my_template.j2
      dest: /etc/my_app.conf
    debugger: on_failed # Войти в отладчик, если задача провалилась
  ```

### Сценарий 4: Скачивание и распространение файлов

Вместо того чтобы каждый сервер скачивал файл из интернета, control-node скачивает его один раз (`delegate_to: localhost`), а затем модули `copy` или `unarchive` распространяют файл по целевым хостам. Это экономит внешний трафик и ускоряет деплой.

```yaml
- name: Скачать дистрибутив на control-node (один раз)
  ansible.builtin.get_url:
    url: https://example.com/package.tar.gz
    dest: /tmp/package.tar.gz
  delegate_to: localhost
  run_once: true

- name: Распространить архив по серверам
  ansible.builtin.unarchive:
    src: /tmp/package.tar.gz
    dest: /opt/application
    remote_src: no
```

### Сценарий 5: Вызов внешнего API

Операции, не имеющие отношения к целевым хостам — создание заявки в Jira, отправка уведомления в Slack, регистрация сервера в системе мониторинга — всегда выполняются с `delegate_to: localhost`.

```yaml
- name: Отправить уведомление о начале деплоя
  ansible.builtin.uri:
    url: https://hooks.slack.com/services/...
    method: POST
    body_format: json
    body:
      text: "Начат деплой на {{ inventory_hostname }}"
  delegate_to: localhost
  run_once: true
```

### Сценарий 6: Копирование с удалением исходника на control-node

Модуль `ansible.posix.synchronize` (обёртка над `rsync`) с параметром `delete_source: yes` копирует файл на managed-node и удаляет оригинал на control-node.

```yaml
- name: Sync and delete source on control-node
  ansible.posix.synchronize:
    src: /tmp/test_delegate.txt
    dest: /tmp/test_delegate.txt
    delete_source: yes
```

Требуется `rsync` на обеих машинах и коллекция `ansible.posix` (обычно предустановлена).

### Сценарий 7: Проверка состояний (facts + assert)

`package_facts` и `service_facts` собирают информацию о системе, а `assert` валидирует её. Это основной паттерн для написания проверок в verify-сценариях (Molecule) и post-condition guard.

```yaml
- name: Собрать факты о пакетах
  ansible.builtin.package_facts:
    manager: auto

- name: Убедиться, что nginx установлен
  ansible.builtin.assert:
    that:
      - "'nginx' in ansible_facts.packages"
    fail_msg: "Nginx не установлен"

- name: Собрать факты о сервисах
  ansible.builtin.service_facts:

- name: Убедиться, что nginx запущен
  ansible.builtin.assert:
    that:
      - ansible_facts.services['nginx.service'].state == 'running'
    fail_msg: "Nginx не запущен"
```

Подробнее о `package_facts` — в [модулях управления пакетами](../Modules/ansible_package_management_modules.md#получение-информации-об-установленных-пакетах), о `service_facts` — в [модулях управления службами](../Modules/ansible_service_and_system_config_modules.md#сбор-информации-о-сервисах).

### Сценарий 8: Обработка ошибок и откат (rollback) через block, rescue, always

Конструкция `block` / `rescue` / `always` — аналог `try` / `catch` / `finally`. `block` содержит основную логику, `rescue` выполняется при ошибке в блоке, `always` — в любом случае. В сочетании с `backup: yes` в модулях `copy` / `template` (см. [файловые модули](../Modules/ansible_file_management_modules.md)) позволяет реализовать автоматический rollback:

```yaml
- name: Deploy config with rollback
  block:
    - name: Deploy new config
      ansible.builtin.copy:
        src: app.conf
        dest: /etc/app.conf
        backup: yes

    - name: Restart service
      ansible.builtin.service:
        name: app
        state: restarted

  rescue:
    - name: Restore old config
      ansible.builtin.copy:
        src: /tmp/app.conf.bak
        dest: /etc/app.conf

    - name: Restart service
      ansible.builtin.service:
        name: app
        state: restarted
```

> `backup: yes` создаёт копию с меткой времени (например, `/tmp/app.conf.bak.2026-01-15.@10:30:00`). Для предсказуемого rollback имя файла нужно знать заранее или находить через `find`.

Подробнее об управлении ходом выполнения — в [flow_control.md](flow_control.md#обработка-ошибок).

Более детальные примеры решения типовых ошибок (синтаксис, SSH, типы данных) приведены в руководстве **[Примеры отладки типовых проблем](../examples/debugging_examples.md)**.

## Дополнительная информация

- [Оптимизация производительности](../ansible_performance_tuning.md) — параллелизм (`forks`, `async`, `throttle`) и стратегии выполнения.
- [Тестирование с Molecule](../ansible_testing_with_molecule.md) — проверка корректности плейбуков и ролей.
- [Антипаттерны Ansible](../ansible_bad_practices.md) — разбор частых ошибок и плохих практик.

