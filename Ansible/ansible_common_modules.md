# Ansible: Обзор часто используемых модулей

## Определения

**Модули Ansible** — это автономные единицы кода, которые выполняют конкретные задачи на управляемых хостах. Они являются основой работы Ansible, предоставляя функциональность для автоматизации широкого спектра операций, от управления пакетами до настройки конфигурационных файлов и служб. Каждый модуль разработан для выполнения определенной операции и стремится быть идемпотентным.

## Основные концепции

Идемпотентность — ключевое свойство большинства модулей Ansible. Более подробно об идемпотентности см. в [Ansible: Основные концепции](../ansible_core_concepts.md#идемпотентность). Модули абстрагируют сложность работы с различными операционными системами и инструментами, предоставляя унифицированный интерфейс.

## Практические сценарии

### 1. Модули для управления пакетами

#### `ansible.builtin.yum_repository`
Управляет YUM-репозиториями в системах на базе Red Hat (CentOS, Fedora).

```yaml
- name: Add EPEL Repository
  ansible.builtin.yum_repository:
    name: epel
    description: EPEL YUM repo
    baseurl: https://download.fedoraproject.org/pub/epel/$releasever/$basearch/
```

#### `ansible.builtin.yum`
Управляет пакетами (установка, обновление, удаление) с помощью менеджера пакетов YUM.

```yaml
- name: Install the latest version of Apache
  ansible.builtin.yum:
    name: httpd
    state: latest
```

#### `ansible.builtin.apt`
Аналог `yum` для систем на базе Debian/Ubuntu.

```yaml
- name: Install the latest version of Nginx
  ansible.builtin.apt:
    name: nginx
    state: latest
    update_cache: yes
```

Дополнительная информация об управлении кэшем пакетов:
*   При `state: present` (или `latest`), модуль `apt` обеспечивает идемпотентность: пакет будет установлен, только если его нет или если он устарел.
*   Опция `update_cache: yes` выполняет аналог `apt update` перед установкой.
*   Для контроля частоты обновления кэша можно использовать `cache_valid_time` в блоке play. Например, `cache_valid_time: 3600` означает, что кэш не будет обновляться, если он свежее 1 часа.

Пример использования `cache_valid_time` в playbook:
```yaml
- name: Update apt cache and install Nginx
  ansible.builtin.apt:
    name: nginx
    state: latest
    update_cache: yes
    cache_valid_time: 3600 # Кэш не будет обновляться, если он свежее 1 часа
```

### 2. Модули для управления файлами

#### `ansible.builtin.file`
Управляет файлами, символическими ссылками и каталогами.

```yaml
- name: Create content directories
  ansible.builtin.file:
    path: "{{ item }}"
    state: directory
    mode: '0755'
  loop:
    - /var/www/site1.local/images
    - /var/www/site1.local/assets
    - /var/www/site1.local/html

  * Это стандартный модуль Ansible для работы с файлами и директориями.
  * `state: directory`: Указывает, что мы хотим создать директорию, если она не существует.
  * `loop`: Эта конструкция позволяет выполнить одну и ту же задачу несколько раз с разными параметрами. В данном случае, задача `ansible.builtin.file` выполнится трижды, для каждого пути из списка.
  * `path: "{{ item }}"`: `item` — это специальная переменная в Ansible, которая в цикле `loop` поочередно принимает каждое значение из списка. Таким образом, Ansible последовательно создает директории `/var/www/site1.local/images`, `/var/www/site1.local/assets` и `/var/www/site1.local/html`.
  * `mode: '0755'`: Устанавливает права доступа к директориям. `0755` — это стандартные права для веб-контента, которые позволяют владельцу делать всё, а остальным — только просматривать содержимое.

- name: Remove a file
  ansible.builtin.file:
    path: /etc/foo.conf
    state: absent # удаление
```

#### `ansible.builtin.copy`
Модуль для копирования файлов. Он может копировать файлы с управляющей машины на целевой хост, но также умеет создавать файлы "на лету" с помощью параметра `content`.

```yaml
- name: Create a test index file
  ansible.builtin.copy:
    dest: /var/www/site1.local/html/index.html
    content: "<h1>Main Page</h1>"
```

*   `dest`: Путь, по которому нужно создать файл на целевой машине (нашей виртуальной машине).
*   `content`: Вместо того чтобы создавать файл локально и копировать его, мы используем этот параметр, чтобы записать указанную строку прямо в файл `dest`. Это очень удобно для создания небольших тестовых или конфигурационных файлов.

#### `ansible.builtin.template`
Создает файл на целевом хосте на основе [шаблона Jinja2](../ansible_jinja2_templating.md). Это основной способ управления конфигурационными файлами. Модуль обрабатывает переменные и логику в `.j2` файле и создает на сервере статический `.conf` файл.

```yaml
- name: Create a configuration file from a template
  ansible.builtin.template:
    src: templates/httpd.conf.j2
    dest: /etc/httpd/conf/httpd.conf
```

#### `ansible.builtin.blockinfile`
Модуль для вставки/обновления/удаления блока текста в файлах. Идеально подходит для управления фрагментами конфигурационных файлов, где нужно гарантировать наличие определенного блока текста между специальными маркерами, не перезаписывая весь файл.

**Пример: Добавление `stream` блока в `nginx.conf`**
```yaml
- name: Add stream block to nginx.conf
  ansible.builtin.blockinfile:
    path: /etc/nginx/nginx.conf
    marker: "# {mark} ANSIBLE MANAGED BLOCK FOR STREAM"
    block: |
      stream {
        log_format basic '$remote_addr [$time_local] '
                         '$protocol $status $bytes_sent $bytes_received '
                         '$session_time "$upstream_addr"';

        access_log /var/log/nginx/stream-access.log basic;
        include /etc/nginx/stream.d/*.conf;
      }
```
*   `path: /etc/nginx/nginx.conf`: Указывает, какой файл нужно изменить.
*   `block: | ...`: Содержит многострочный блок `stream`, который будет вставлен.
*   Так как не указаны `insertafter` или `insertbefore`, этот блок будет добавлен в конец файла `/etc/nginx/nginx.conf`.
*   Ansible добавит комментарии-маркеры вокруг этого блока, чтобы в будущем при повторном запуске плейбука он мог обновить этот блок (если его содержимое изменится) или удалить (если `state` будет установлен в `absent`). Если маркер не указан, используются маркеры по умолчанию `BEGIN ANSIBLE MANAGED BLOCK` и `END ANSIBLE MANAGED BLOCK`.


#### Более аккуратный вариант развертывания (через `file` + `copy`)

В отличие от `ansible.builtin.synchronize` с опцией `delete: yes`, который полностью заменяет содержимое целевого каталога, существует более безопасный способ развертывания, особенно для критически важных веб-серверов.

**Шаг 1: Гарантируем наличие корневого каталога**

```yaml
- name: Ensure web root exists
  ansible.builtin.file:
    path: /var/www/html
    state: directory
    owner: vagrant
    group: vagrant
    mode: '0755'
```

Что делает:
*   **Проверяет, существует ли каталог `/var/www/html`**:
    *   Если не существует → создаёт.
    *   Если уже есть → ничего не удаляет.
*   **Гарантирует правильные атрибуты**:
    *   правильного владельца
    *   правильную группу
    *   правильные права доступа
*   **Почему это аккуратнее**:
    *   В отличие от `synchronize` с `delete: yes`, каталог не удаляется.
    *   Это предотвращает ситуацию, когда веб-сервер (например, nginx) теряет свой `root` и сайт "падает" даже на секунду.

**Шаг 2: Копируем файлы**

После того, как каталог гарантированно существует, можно безопасно копировать файлы с помощью `ansible.builtin.copy` или `ansible.builtin.template`.

### 3. Модули для управления службами (сервисами)

#### `ansible.builtin.service`
Основной модуль для управления службами в системах с `SysV-init` или `systemd`.

```yaml
- name: Start and enable httpd service
  ansible.builtin.service:
    name: httpd
    state: started
    enabled: yes
```

#### `ansible.builtin.systemd`
Более современный и предпочтительный модуль для систем, использующих `systemd`. Предоставляет дополнительные возможности, которых нет в `service`. Ключевое преимущество — опция `daemon_reload: yes`, которая выполняет команду `systemctl daemon-reload`. Это необходимо после создания или изменения `unit`-файлов сервисов, чтобы `systemd` узнал о них. Модуль `service` этого делать не умеет.

```yaml
- name: Reload systemd to apply new unit files
  ansible.builtin.systemd:
    daemon_reload: yes

- name: Restart service httpd, and sleep for 5 seconds
  ansible.builtin.systemd:
    name: httpd
    state: restarted
```

### 4. Модули для синхронизации файлов

#### `ansible.builtin.synchronize`
Использует `rsync` для эффективной синхронизации файлов и каталогов между хостами. Идеально подходит для больших сайтов и проектов, где важна скорость и идемпотентность.

```yaml
- name: Sync site content
  ansible.builtin.synchronize:
    src: files/html/
    dest: /var/www/html/
    delete: yes
```

Что делает:
*   **Использует rsync под капотом**: Обеспечивает высокую производительность.
*   **Быстро синхронизирует файлы**:
    *   копирует новые
    *   обновляет изменённые
    *   удаляет лишние на сервере
*   `delete: yes`:
    *   Если файл удалён локально, он будет удалён и на сервере.
    *   Сервер становится точной копией `files/html/`.

##### Нюансы при использовании с Vagrant

Модуль `synchronize` работает поверх `rsync` и инициирует прямое SSH-соединение с хоста управления на целевую машину. Это может вызывать проблемы в средах Vagrant, поскольку `synchronize` не использует автоматически настроенные Vagrant'ом SSH-ключи.

*   **Симптом**: Ошибка `Permission denied (publickey,password)` при выполнении задачи.
*   **Причина**: Модуль пытается аутентифицироваться по паролю или стандартным ключам, игнорируя SSH-конфигурацию Vagrant.
*   **Решение**: В таких случаях рекомендуется заменять `synchronize` на модуль `ansible.builtin.copy`. Модуль `copy` работает через стандартное соединение Ansible, которое Vagrant настраивает корректно, что позволяет избежать проблем с аутентификацией.

## Дополнительная информация

При использовании модулей Ansible важно обращать внимание на их идемпотентность и специфические параметры. Всегда рекомендуется обращаться к официальной [документации Ansible](https://docs.ansible.com/ansible/latest/collections/all_plugins.html#modules) для получения наиболее актуальной и подробной информации о каждом модуле и его возможностях. Использование `ansible-doc <module_name>` в командной строке также предоставляет быстрый доступ к справке.
