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
```

* Это стандартный модуль Ansible для работы с файлами и директориями.
* `state: directory`: Указывает, что мы хотим создать директорию, если она не существует.
* `loop`: Эта конструкция позволяет выполнить одну и ту же задачу несколько раз с разными параметрами. В данном случае, задача `ansible.builtin.file` выполнится трижды, для каждого пути из списка.
* `path: "{{ item }}"`: `item` — это специальная переменная в Ansible, которая в цикле `loop` поочередно принимает каждое значение из списка. Таким образом, Ansible последовательно создает директории `/var/www/site1.local/images`, `/var/www/site1.local/assets` и `/var/www/site1.local/html`.
* `mode: '0755'`: Устанавливает права доступа к директориям. `0755` — это стандартные права для веб-контента, которые позволяют владельцу делать всё, а остальным — только просматривать содержимое.

**Ad-hoc команда для создания директории `.ssh`:**
```bash
ansible <hostname> -m file -a "path=/home/ansible_user/.ssh state=directory owner=ansible_user group=ansible_user mode=0700" --become
```

```yaml
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

Также с помощью `content` и функции `lookup` можно прочитать локальный файл на управляющей машине и записать его содержимое на удаленный хост. Это полезно, например, для распространения публичных SSH-ключей.

```yaml
- name: Copy public key to remote host
  ansible.builtin.copy:
    dest: /home/ansible_user/.ssh/authorized_keys
    content: "{{ lookup('file', '/path/to/your/local/id_rsa.pub') }}"
```
**Ad-hoc команда для копирования публичного SSH-ключа:**
```bash
ansible <hostname> -m copy -a 'content="{{ lookup("file", "~/.ssh/id_rsa.pub") }}" dest=/home/ansible_user/.ssh/authorized_keys owner=ansible_user group=ansible_user mode=0600' --become
```

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

### 4. Модули для системной конфигурации

#### `ansible.builtin.timezone`
Управляет системным часовым поясом.

```yaml
- name: Set timezone to Europe/Moscow
  ansible.builtin.timezone:
    name: Europe/Moscow
```

#### `ansible.builtin.hostname`
Управляет именем хоста (hostname) системы.

```yaml
- name: Set hostname to 'webserver01'
  ansible.builtin.hostname:
    name: webserver01

- name: Set hostname based on inventory name
  ansible.builtin.hostname:
    name: "{{ inventory_hostname }}"
```

### 5. Модули для синхронизации файлов

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

### 5. Модули для выполнения команд

#### `ansible.builtin.command`
Этот модуль предназначен для выполнения простых команд на целевых хостах. В отличие от большинства модулей Ansible, **`command` не является идемпотентным по умолчанию**. Это означает, что он будет выполнять команду при каждом запуске плейбука, независимо от состояния системы.

**Когда его использовать?**
`command` следует использовать как крайнюю меру, когда нет более подходящего, специализированного модуля для выполнения задачи. Например, если нужно запустить простой скрипт или утилиту, для которой нет отдельного модуля Ansible.

**Важно:**
*   Модуль `command` **не выполняет** команды через оболочку (shell). Это значит, что переменные окружения (`$HOME`), конвейеры (`|`), и перенаправления (`>`, `<`) работать не будут. Для таких задач используйте модуль `ansible.builtin.shell`.
*   Всегда отдавайте предпочтение специализированным модулям (`apt`, `service`, `copy` и т.д.), так как они обеспечивают идемпотентность и лучшую обработку ошибок.

**Пример: Проверка версии утилиты**
```yaml
- name: Get the version of some utility
  ansible.builtin.command:
    cmd: /usr/bin/some-utility --version
  register: some_utility_version
  changed_when: false # Команда не изменяет состояние системы
```

**Как сделать `command` идемпотентным?**
Использование `creates` в задачах `ansible.builtin.command` делает плейбук идемпотентным. Можно добавить условное выполнение с помощью аргументов `creates` или `removes`.
*   `creates`: команда будет выполнена, только если указанный файл **не существует**.
*   `removes`: работает по обратному принципу: команда выполняется, только если указанный файл **существует**, и ее назначение — удалить этот файл.

**Пример с `creates`**
Предположим, у нас есть скрипт, который создает файл `/opt/app/initialised.flag` после своей отработки.
```yaml
- name: Initialize application only once
  ansible.builtin.command:
    cmd: /opt/app/initialize.sh
    creates: /opt/app/initialised.flag
```
В этом случае `/opt/app/initialize.sh` будет запущен только один раз. При последующих запусках Ansible увидит, что файл `/opt/app/initialised.flag` уже существует, и пропустит эту задачу.

#### `ansible.builtin.shell`
Модуль `ansible.builtin.shell` предназначен для выполнения команд через оболочку (shell) на целевых хостах. Это его ключевое отличие от `ansible.builtin.command`, который не использует оболочку.

**Когда его использовать?**
Используйте `shell` тогда, когда вам нужны функции оболочки, такие как:
*   Использование конвейеров (`|`)
*   Перенаправление ввода/вывода (`>`, `>>`, `<`)
*   Доступ к переменным окружения (`$HOME`, `$PATH`)
*   Использование условных конструкций оболочки (`&&`, `||`)
*   Выполнение сложных команд, включающих подстановку команд (command substitution)

Как и `command`, `shell` **не является идемпотентным по умолчанию** и должен использоваться с осторожно.

**Важно:**
*   Всегда отдавайте предпочтение специализированным модулям Ansible. Если существует модуль для вашей задачи (например, `apt` для пакетов, `service` для служб), используйте его вместо `shell`.
*   Будьте осторожны с безопасностью: избегайте использования `shell` с ненадежными переменными, так как это может привести к уязвимостям через инъекции команд.
*   Если вам не нужны функции оболочки, используйте `ansible.builtin.command`. Он более безопасен и эффективен.

**Пример: Запуск команды с использованием конвейера**
```yaml
- name: Check if a process is running using grep
  ansible.builtin.shell:
    cmd: ps aux | grep my_process | grep -v grep
  register: process_status
  changed_when: false
```

**Как сделать `shell` идемпотентным?**
Как и в случае с `command`, вы можете использовать аргументы `creates` или `removes` для достижения идемпотентности.

**Пример с `creates`**
```yaml
- name: Configure a complex service using a shell script only if not configured
  ansible.builtin.shell:
    cmd: /usr/local/bin/configure_service.sh --setup-all
    creates: /etc/service_configured_flag
```
В этом примере скрипт `/usr/local/bin/configure_service.sh` будет выполнен только в том случае, если файл `/etc/service_configured_flag` не существует.

### 7. Модули для работы с паролями и чувствительными данными

#### `ansible.builtin.password`

*   **Назначение**: Генерация паролей для учетных записей пользователей, баз данных, а также для создания ключей.
*   **Идемпотентность**: Модуль идемпотентен. Если пароль уже был сгенерирован и сохранен (например, в файле, указанном в `path`), он не будет генерироваться повторно при следующих запусках, если это не будет принудительно указано.

```yaml
- name: Generate a random password for a database user
  ansible.builtin.password:
    length: 20
    chars: ascii_letters,digits,punctuation
    # path: /path/to/vaulted_password_file # Укажите путь к файлу, который будет зашифрован Vault
    # Чтобы сгенерировать хеш пароля (для хранения в БД, например):
    # algorithm: sha512crypt # Алгоритм хеширования (например, 'sha512crypt', 'bcrypt')
    # Эти параметры (`path`, `algorithm`) являются взаимоисключающими и необязательными,
    # их использование зависит от способа хранения и применения пароля.
  register: db_password_result # Результат генерации пароля будет доступен в этой переменной

- name: Create database user with generated password
  community.mysql.mysql_user:
    name: my_app_user
    password: "{{ db_password_result.password }}"
    host: localhost
    priv: '*.*:ALL'
    state: present
  no_log: true # Важно скрывать пароли в логах!
```

### 8. Модули для управления пользователями и группами

#### `ansible.builtin.user`

*   **Назначение**: Создание, изменение, удаление учетных записей пользователей. Управление группами пользователей.
*   **Идемпотентность**: Модуль идемпотентен. Он создаст пользователя, только если его нет, и изменит параметры, только если они отличаются от заданных.

**Пример 1: Создание нового пользователя**
```yaml
- name: Create a new user 'peter_parker'
  ansible.builtin.user:
    name: peter_parker
    comment: "Peter Parker, Web Developer"
    shell: /bin/bash
    home: /home/peter_parker
    state: present
```
**Ad-hoc команда для создания пользователя:**
```bash
ansible <hostname> -m user -a "name=ansible_user shell=/bin/bash state=present" --become
```

**Пример 2: Добавление пользователя в группу sudo**
Для добавления пользователя в группу `sudo` (или `wheel` в RHEL-подобных системах) используйте параметр `groups` и `append: yes`.
```yaml
- name: Add 'peter_parker' to the sudo group
  ansible.builtin.user:
    name: peter_parker
    groups: sudo
    append: yes
    state: present
```

**Пример 3: Установка пароля для пользователя**
Для установки пароля используется параметр `password`. **Важно**: Пароль должен быть в виде хеша. Ansible не принимает пароли в открытом виде. Вы можете сгенерировать хеш пароля с помощью утилиты `mkpasswd` (в Linux) или Python.

```bash
# Пример генерации хеша пароля (для Linux, нужен пакет `whois` или `passwd`)
# python -c 'import crypt; print(crypt.crypt("MySecretPassword", crypt.METHOD_SHA512))'
```

```yaml
- name: Set password for 'peter_parker'
  ansible.builtin.user:
    name: peter_parker
    password: "$6$rounds=656000$q1w2e3r4t5y6u7i8$aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789./ABCDEFGHIJKLMNOPQRSTUVW" # Замените на сгенерированный хеш
    update_password: always # Всегда обновлять пароль, если хеш изменился
    state: present
  no_log: true # Скрывать пароль в логах
```
> **Лучшая практика**: Всегда используйте [Ansible Vault](../ansible_vault.md) для хранения хешей паролей и других чувствительных данных.

## Дополнительная информация

При использовании модулей Ansible важно обращать внимание на их идемпотентность и специфические параметры. Всегда рекомендуется обращаться к официальной [документации Ansible](https://docs.ansible.com/ansible/latest/collections/all_plugins.html#modules) для получения наиболее актуальной и подробной информации о каждом модуле и его возможностях. Использование `ansible-doc <module_name>` в командной строке также предоставляет быстрый доступ к справке.
