# Ansible: Модули управления файлами

## Определения

**Модули управления файлами** — это инструменты Ansible для работы с файловой системой на управляемых хостах. Они позволяют создавать, копировать, изменять атрибуты, редактировать содержимое и удалять файлы и директории. Эти модули являются основой для управления конфигурациями и развертывания приложений.

## Основные концепции

Все файловые модули Ansible стремятся к идемпотентности: они проверяют текущее состояние файла перед выполнением действий.

### Группы модулей

1.  **Управление объектами и атрибутами:**
    *   `file`: Создание директорий, симлинков, управление правами (`owner`, `group`, `mode`).
    *   `stat`: Получение детальной информации о файле (существование, контрольная сумма, права).
    *   `find`: Поиск файлов по заданным критериям (паттерн, возраст, размер).
2.  **Перенос данных:**
    *   `copy`: Копирование файлов с контрольного узла на хосты или создание файлов из текста (`content`).
    *   `template`: Создание файлов на основе [шаблонов Jinja2](../ansible_jinja_templating.md).
    *   `fetch`: Копирование файлов с управляемых хостов на контрольный узел.
3.  **Редактирование содержимого:**
    *   `lineinfile`: Управление конкретными строками (добавление, замена по RegExp, удаление).
    *   `blockinfile`: Вставка или обновление многострочных блоков текста с использованием маркеров.
    *   `replace`: Массовая замена строк во всем файле по регулярному выражению.

## Практические сценарии

### Модуль `ansible.builtin.file`

Используется для создания структуры каталогов и управления правами.

```yaml
- name: Создание структуры каталогов для сайта
  ansible.builtin.file:
    path: "{{ item }}"
    state: directory
    mode: '0755'
    owner: www-data
  loop:
    - /var/www/site/html
    - /var/www/site/images
```

**Ad-hoc команда для создания директории:**
```bash
ansible all -m file -a "path=/tmp/test_dir state=directory mode=0700"
```

### Модуль `ansible.builtin.copy`

Копирование статических файлов или создание файлов "на лету".

```yaml
- name: Создание простого index.html
  ansible.builtin.copy:
    dest: /var/www/site/html/index.html
    content: "<h1>Welcome to Ansible Managed Site</h1>"
    owner: www-data
    mode: '0644'
```

### Модуль `ansible.builtin.template`

Основной инструмент для управления динамическими конфигурациями.

```yaml
- name: Развертывание конфига Nginx из шаблона
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    validate: /usr/sbin/nginx -t # проверка синтаксиса перед сохранением
```
Подробнее см. в [Шаблонизация Jinja2](../ansible_jinja_templating.md).

### Модуль `ansible.builtin.lineinfile`

Идеален для изменения отдельных параметров в существующих конфигах.

```yaml
- name: Отключение входа root по SSH
  ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    regexp: '^#?PermitRootLogin'
    line: 'PermitRootLogin no'
    state: present
    validate: '/usr/sbin/sshd -t -f %s'
```

### Модуль `ansible.builtin.blockinfile`

Управляет блоками текста, выделяя их маркерами.

```yaml
- name: Добавление настроек прокси в .bashrc
  ansible.builtin.blockinfile:
    path: /home/user/.bashrc
    block: |
      export http_proxy=http://proxy.example.com:8080
      export https_proxy=http://proxy.example.com:8080
    marker: "# {mark} ANSIBLE MANAGED PROXY SETTINGS"
```

### Модуль `ansible.builtin.stat`

Используется для проверки условий перед выполнением других задач.

```yaml
- name: Проверка наличия файла бэкапа
  ansible.builtin.stat:
    path: /backup/db.sql
  register: backup_file

- name: Сообщение об отсутствии бэкапа
  ansible.builtin.debug:
    msg: "Файл бэкапа не найден!"
  when: not backup_file.stat.exists
```

### Модуль `ansible.builtin.fetch`

Загрузка файлов с серверов на локальную машину (например, логов или сертификатов).

```yaml
- name: Получение лога ошибок с сервера
  ansible.builtin.fetch:
    src: /var/log/nginx/error.log
    dest: ./logs/
    flat: yes # загрузить файл прямо в директорию, не создавая структуру путей сервера
```

### Безопасное развертывание (Atomic operations)

Для минимизации времени простоя сервисов рекомендуется сначала проверять наличие родительских директорий и использовать `validate` в модулях `template` и `copy`.

```yaml
- name: Гарантия наличия root директории
  ansible.builtin.file:
    path: /var/www/html
    state: directory
    mode: '0755'

- name: Копирование конфига с проверкой
  ansible.builtin.copy:
    src: app.conf
    dest: /etc/app/app.conf
    validate: '/usr/bin/app --check-config %s'
```

## Дополнительная информация

*   [Официальная документация по файловым модулям](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/index.html#plugins-in-ansible-builtin)
*   [Шаблонизация Jinja2](../ansible_jinja_templating.md)
*   [Синхронизация файлов через rsync](ansible_file_synchronization_modules.md)
*   [Переменные в Ansible](../PlaybookStructure/variables.md)
