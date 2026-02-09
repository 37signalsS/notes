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

* `dest`: Путь, по которому нужно создать файл на целевой машине (нашей виртуальной машине).
* `content`: Вместо того чтобы создавать файл локально и копировать его, мы используем этот параметр, чтобы записать указанную строку прямо в файл `dest`. Это очень удобно для создания небольших тестовых или конфигурационных файлов.

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

* `path: /etc/nginx/nginx.conf`: Указывает, какой файл нужно изменить.
* `block: | ...`: Содержит многострочный блок `stream`, который будет вставлен.
* Так как не указаны `insertafter` или `insertbefore`, этот блок будет добавлен в конец файла `/etc/nginx/nginx.conf`.
* Ansible добавит комментарии-маркеры вокруг этого блока, чтобы в будущем при повторном запуске плейбука он мог обновить этот блок (если его содержимое изменится) или удалить (если `state` будет установлен в `absent`). Если маркер не указан, используются маркеры по умолчанию `BEGIN ANSIBLE MANAGED BLOCK` и `END ANSIBLE MANAGED BLOCK`.

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

* **Проверяет, существует ли каталог `/var/www/html`**:
  * Если не существует → создаёт.
  * Если уже есть → ничего не удаляет.
* **Гарантирует правильные атрибуты**:
  * правильного владельца
  * правильную группу
  * правильные права доступа
* **Почему это аккуратнее**:
  * В отличие от `synchronize` с `delete: yes`, каталог не удаляется.
  * Это предотвращает ситуацию, когда веб-сервер (например, nginx) теряет свой `root` и сайт "падает" даже на секунду.

**Шаг 2: Копируем файлы**

После того, как каталог гарантированно существует, можно безопасно копировать файлы с помощью `ansible.builtin.copy` или `ansible.builtin.template`.
