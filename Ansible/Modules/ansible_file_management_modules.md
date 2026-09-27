# Ansible: Модули управления файлами

## Определения

**Модули управления файлами** — это группа специализированных инструментов Ansible (преимущественно `ansible.builtin`), предназначенных для декларативного манипулирования файловой системой на управляемых хостах. Они позволяют описывать желаемое состояние файлов и директорий, обеспечивая идемпотентность и безопасность операций.

**Атомарная перезапись (Atomic Move)** — стандартный механизм Ansible для обеспечения целостности данных. Вместо прямого редактирования файла Ansible создает временную копию (обычно в той же директории), вносит в неё изменения, устанавливает права и затем заменяет оригинал системным вызовом `rename`. Это гарантирует, что файл не окажется в поврежденном состоянии при сбое в процессе записи или нехватке места на диске.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля (например, `ansible.builtin.template`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен и обеспечения предсказуемости выполнения во всех современных версиях Ansible (с версии 2.10). Для модулей из коллекции `ansible.posix` FQCN обязателен, так как они не входят в состав `ansible-core`.

### Механизм сравнения файлов

Ansible использует алгоритмы контрольных сумм для определения необходимости обновления файлов:
- **Для текстовых файлов**: Сравнение содержимого после рендеринга шаблона с текущим файлом на хосте
- **Для бинарных файлов**: Использование контрольных сумм (MD5, SHA-1, SHA-256 или выше, в зависимости от настроек модуля и требований FIPS). Начиная с ansible-core 2.19, параметр `checksum_algorithm` позволяет явно выбирать алгоритм: `md5`, `sha1`, `sha224`, `sha256`, `sha384`, `sha512`. На FIPS-совместимых системах MD5 может быть недоступен.
- **Для `remote_src`**: Сравнение контрольных сумм локально на управляемом хосте

### Временные файлы и их управление

Ansible создает временные файлы в директории `~/.ansible/tmp/` на управляемых хостах:
- Имена файлов формата: `ansible-tmp-<timestamp>-<random>`
- Автоматическая очистка после успешного выполнения
- При ошибке файлы сохраняются для отладки (можно включить `ANSIBLE_KEEP_REMOTE_FILES=1`)
- Для глубокой отладки можно использовать `ANSIBLE_KEEP_REMOTE_FILES=1` вместе с `-vvv`, чтобы получить путь к распакованному модулю на удаленном хосте

### Требования к окружению

Начиная с **ansible-core 2.19**, для работы модулей управления файлами требуется **Python 3.10+** на управляемых узлах. Поддержка Python 2.7 и 3.6 была прекращена в ansible-core 2.17, поддержка Python 3.7 — в ansible-core 2.18.

## Основные концепции

### Группы модулей по назначению

1.  **Управление структурой и атрибутами:**
    *   `ansible.builtin.file`: Создание директорий (`directory`), симлинков (`link`), хардлинков (`hard`), пустых файлов (`touch`), управление правами, владельцами, временными метками и удаление (`absent`). Поддерживает управление временем доступа и модификации (`access_time`, `modification_time`), а также символьные и восьмеричные права.
    *   `ansible.builtin.stat`: Сбор фактов о файле (существование, контрольные суммы, права, `uid`, `gid`, `mtime`, `ctime`, `atime`, атрибуты `lsattr`, контекст SELinux). Используется для принятия решений в последующих задачах через `register`. Начиная с ansible-core 2.20, возвращает контекст SELinux (`get_selinux_context`), начиная с 2.21 — использование диска в байтах (`disk_usage_bytes`).
    *   `ansible.builtin.find`: Рекурсивный поиск файлов по шаблонам, дате, размеру или содержимому. Начиная с ansible-core 2.16, поддерживает параметры `exact_mode` и `mode` для точного matching прав, `encoding` (2.17) для указания кодировки при поиске по содержимому, `checksum_algorithm` (2.19) и `limit` (2.18) для ограничения количества результатов.
    *   `ansible.builtin.tempfile`: Создание гарантированно уникальных временных файлов или директорий на управляемом хосте.
2.  **Перенос и получение данных:**
    *   `ansible.builtin.copy`: Копирование с контрольного узла или внутри удаленного хоста (`remote_src: yes`). Поддерживает `follow` для следования по симлинкам и `force` для принудительной перезаписи.
    *   `ansible.builtin.template`: Генерация файлов из шаблонов [Jinja2](../ansible_jinja_templating.md). Обработка происходит на контрольном узле. Рендеринг выполняется Action-плагином перед передачей на хост.
    *   `ansible.builtin.fetch`: Копирование файлов с хостов на контрольный узел. **Ограничение**: Работает только с отдельными файлами; для выгрузки директорий используйте `ansible.posix.synchronize` в режиме `pull`.
    *   `ansible.builtin.get_url`: Загрузка файлов по HTTP/HTTPS/FTP напрямую на управляемый хост. Поддерживает заголовки авторизации, таймауты и проверку SSL-сертификатов.
    *   `ansible.builtin.unarchive`: Распаковка архивов. Требует наличия `tar`, `unzip` или `xz` на целевом хосте. Может скачивать архив с контрольного узла или использовать локальный на хосте (`remote_src: yes`). Поддерживает `list_files` для просмотра содержимого без распаковки.
3.  **Редактирование содержимого:**
    *   `ansible.builtin.lineinfile`: Управление отдельными строками (добавление, замена, удаление). Идеально для простых правок системных конфигов. Поддерживает `backup`, `create`, `insertafter`, `insertbefore`.
    *   `ansible.builtin.blockinfile`: Вставка многострочных блоков текста, защищенных маркерами. Позволяет задавать кастомные маркеры через параметр `marker`.
    *   `ansible.builtin.replace`: Массовая замена текста по регулярным выражениям. Поддерживает `backup` и `after`/`before` для ограничения области замены.
    *   `ansible.builtin.patch`: Применение стандартных `patch`-файлов (diff). Поддерживает `remote_src` для применения патчей, уже находящихся на хосте.
    *   `ansible.builtin.assemble`: Сборка (конкатенация) одного файла из нескольких фрагментов, находящихся в директории. Поддерживает `delimiter` и `regexp` для фильтрации фрагментов.
    *   `ansible.builtin.ini_file`: Управление INI-файлами по секциям (`[section]`) без шаблона. Находит нужную секцию, создаёт её при отсутствии и меняет только указанный параметр, сохраняя комментарии и форматирование остальных секций. Единственный файловый модуль, который оперирует на уровне «секция + ключ», а не на уровне строк.
 4.  **Расширенные права и атрибуты (ansible.posix):**
     *   `ansible.posix.acl`: Управление расширенными списками контроля доступа (ACL). Требует установки коллекции `ansible.posix`.
     *   `ansible.posix.xattr`: Управление расширенными атрибутами файловой системы. Требует установки коллекции `ansible.posix`.
 5.  **Архивация и извлечение данных:**
     *   `ansible.builtin.slurp`: Чтение содержимого файлов с управляемого хоста и возврат в base64. Полезно для передачи бинарных данных или конфиденциальной информации из удаленного хоста на контрольный узел без использования `fetch`.
     *   `community.general.archive`: Создание архивов (tar, zip, bz2, xz) на управляемом хосте. Поддерживает `path`, `dest`, `format`, `compression`. Полезно для создания бэкапов перед обновлениями.
     *   `community.general.iso_extract`: Извлечение файлов из ISO-образов. Поддерживает `image`, `dest`, `files` для выборочного извлечения.
     *   `community.general.iso_copy`: Копирование ISO-образов на удаленный хост или с него.

### Выбор стратегии редактирования файла

| Инструмент | Когда использовать | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **template** | Для сложных и динамических конфигов | Единый источник конфигурации, полный контроль через Jinja2 | Требует хранения и поддержки шаблона |
| **lineinfile** | Для одиночных правок в системных файлах | Минимум кода, не нужен шаблон | Трудно поддерживать при большом кол-ве правок |
| **blockinfile** | Для вставки блоков (напр. в `/etc/hosts`) | Четкие границы блока (маркеры) | Добавляет комментарии-маркеры в файл |
| **replace** | Для массового патчинга по Regex | Высокая гибкость поиска | Риск нарушить структуру файла при ошибке в Regex |
| **ini_file** | Для INI-файлов (`.ini`, `.cfg`, `pip.ini`, `grafana.ini`) | Меняет один ключ в одной секции, не трогая остальное | Ограничен форматом INI; не умеет менять порядок секций |

Ключевое различие: `lineinfile`/`replace` работают с **строками** и не понимают структуру файла, поэтому один и тот же параметр может оказаться в нескольких секциях (например, `[server]` и `[server.backup]` в `grafana.ini`) — поиск по строке попадёт не туда. `ini_file` адресует параметр **явной парой `section` + `key`**, что делает его единственным безопасным выбором для INI-конфигураций с одноимёнными ключами в разных секциях.

### Критически важные параметры

-   **`validate`**: Выполнение команды проверки синтаксиса перед финальной заменой файла (например, `validate: '/usr/sbin/visudo -cf %s'`). Символ `%s` заменяется на путь к временному файлу. **Обязательно** для критических конфигураций (`/etc/sudoers`, `/etc/ssh/sshd_config`, `/etc/nginx/nginx.conf`).
-   **`remote_src`**: Определяет местоположение источника. Если `yes`, `src` ищется на управляемом хосте (используется в `copy` и `unarchive`). При `no` (по умолчанию) файл передается с контрольного узла.
-   **`unsafe_writes`**: Позволяет Ansible изменять файлы, когда атомарная перезапись невозможна (например, при монтировании файлов напрямую в Docker-контейнеры через `bind mount` или на сетевых FS без поддержки `rename`). **Внимание**: Использование повышает риск повреждения файла при сбое в момент записи. Применяется только как крайняя мера, когда `rename` недоступен.
-   **`backup`**: Создает резервную копию файла с временной меткой в той же директории перед внесением изменений. Поддерживается большинством файловых модулей (`copy`, `template`, `lineinfile`, `replace`, `blockinfile`, `file`).
-   **`force`**: В модуле `copy` определяет, нужно ли перезаписывать файл, если он уже существует, но имеет другое содержимое. При `force: no` (по умолчанию) файл не перезаписывается, если существует.
-   **`follow`**: В модуле `copy`, `template` и `file` определяет, следовать ли по символическим ссылкам при копировании/управлении (по умолчанию `true` в `file`, `false` в `copy`/`template`). При `follow: false` Ansible работает с самой ссылкой, а не с целевым объектом.
-   **`directories_only`**: В модуле `find` — искать только директории, игнорируя файлы.
-   **`files_only`**: В модуле `find` — искать только файлы, игнорируя директории.
-   **`checksum_algorithm`**: В модулях `find` (начиная с 2.19) и `stat` — выбор алгоритма контрольной суммы (`md5`, `sha1`, `sha224`, `sha256`, `sha384`, `sha512`). На FIPS-системах MD5 недоступен.
-   **`limit`**: В модуле `find` (начиная с 2.18) — максимальное количество возвращаемых результатов. Позволяет ограничить объем данных при поиске на больших файловых системах.
-   **`access_time` / `modification_time`**: В модуле `file` (начиная с Ansible 2.7) — установка времени доступа и модификации файла. Значение `preserve` сохраняет текущее время, `now` устанавливает текущее, или можно задать формат `YYYYMMDDHHMM.SS`.
-   **`exact_mode`**: В модуле `find` (начиная с 2.16) — точное совпадение прав вместо минимального набора.

### Права доступа, атрибуты и SELinux

Файловые модули поддерживают расширенное управление атрибутами:
- **`owner` / `group`**: Установка владельца и группы. При изменении владельца рекурсивно (`recurse: yes`) убедитесь, что пользователь существует на всех целевых хостах.
- **`mode`**: Права доступа. **Всегда** используйте восьмеричный формат в кавычках (`'0644'`, `'0755'`). Без кавычек Ansible может интерпретировать число как десятичное, что приведет к неверным правам. Поддерживается символьный режим (например, `u+rwx,g=rx,o=rx`).
- **`attributes`**: Флаги файловой системы Linux (например, `i` — запрет на изменение (immutable), `a` — только для дозаписи). Требует поддержки файловой системой (ext4, xfs, btrfs). Просмотр текущих атрибутов: `lsattr`, установка: `chattr`.
- **SELinux**: Параметры `setype`, `seuser`, `serole`, `selevel` для управления контекстом безопасности. Если SELinux включен, Ansible пытается сохранить контекст при атомарном перемещении. Начиная с ansible-core 2.20, модуль `stat` может возвращать контекст SELinux через `get_selinux_context: yes`.

### Режим диагностики (Diff & Check Mode)

Файловые модули полноценно поддерживают флаги диагностики:
- **`--check`**: Показывает, будет ли файл изменен, не применяя изменений на практике. Модули, которые не изменяют систему (например, `stat`, `find`), работают в check_mode полностью.
- **`--diff`**: Показывает детальную разницу (unified diff) между текущим состоянием файла и планируемым. Очень полезно для валидации работы `template` и `lineinfile`. Некоторые модули (например, `find`) не поддерживают diff_mode.

### Идемпотентность файловых операций

Идемпотентность — ключевое свойство модулей управления файлами. Повторный запуск плейбука не должен вносить изменения, если система уже находится в желаемом состоянии. Модули достигают этого через:
- Сравнение контрольных сумм перед копированием (`copy`, `template`)
- Проверку существования файла перед созданием (`file` с `state: touch`)
- Сравнение содержимого при редактировании (`lineinfile`, `blockinfile`, `replace`)
- Использование параметра `creates` в `unarchive` и `command`/`shell` для пропуска уже выполненных операций

### Кросс-платформенные особенности

Модули управления файлами работают на разных платформах, но с отличиями:
- **Linux (ext4, xfs, btrfs)**: Полная поддержка атрибутов (`immutable`, `append`), ACL, SELinux
- **macOS**: Ограниченная поддержка расширенных атрибутов, особый синтаксис прав ( `+a` для append-only), отсутствие SELinux
- **FreeBSD**: Отличия в управлении ACL и расширенными атрибутами, используется `getcap`/`setcap`
- **Windows**: Использование модулей `ansible.windows.win_*` вместо `ansible.builtin.*`. Например, `ansible.windows.win_file` вместо `ansible.builtin.file`, `ansible.windows.win_stat` вместо `ansible.builtin.stat`

## Практические сценарии

### Создание директорий и рекурсивное управление правами

Использование `recurse: yes` позволяет применить права ко всем вложенным объектам (только при `state: directory`).

```yaml
- name: "Настройка директории для хранения данных"
  ansible.builtin.file:
    path: /var/lib/myapp
    state: directory
    owner: myuser
    group: mygroup
    mode: '0750'
    recurse: yes
```

### Безопасное обновление конфигурации Sudoers

Модуль `template` с валидацией предотвращает блокировку доступа к системе из-за синтаксических ошибок.

```yaml
- name: "Настройка прав sudo для разработчиков"
  ansible.builtin.template:
    src: sudoers_developers.j2
    dest: /etc/sudoers.d/developers
    owner: root
    group: root
    mode: '0440'
    validate: '/usr/sbin/visudo -cf %s'
```

### Редактирование sysctl параметров

Изменение конкретных параметров ядра без замены всего файла.

```yaml
- name: "Включение пересылки трафика IPv4"
  ansible.builtin.lineinfile:
    path: /etc/sysctl.conf
    regexp: '^net.ipv4.ip_forward'
    line: 'net.ipv4.ip_forward=1'
    state: present
    backup: yes

- name: "Применение параметров sysctl"
  ansible.builtin.command: sysctl -p
```

### Управление конфигурацией systemd-сервисов

Размещение unit-файлов с корректными правами и валидацией.

```yaml
- name: "Размещение unit-файла сервиса"
  ansible.builtin.copy:
    src: myapp.service
    dest: /etc/systemd/system/myapp.service
    owner: root
    group: root
    mode: '0644'
  register: service_unit

- name: "Перезагрузка демона systemd"
  ansible.builtin.systemd:
    name: myapp
    daemon_reload: yes
  when: service_unit.changed
```

### Распаковка артефактов с проверкой существования

Если архив загружается через `get_url`, используйте `remote_src: yes` в `unarchive`. Параметр `creates` обеспечивает идемпотентность.

```yaml
- name: "Развертывание приложения из архива"
  ansible.builtin.unarchive:
    src: /tmp/app_v1.tar.gz
    dest: /opt/app
    remote_src: yes
    creates: /opt/app/bin/start.sh
```

### Редактирование системных конфигураций (`lineinfile`)

Эффективно для изменения конкретных параметров без замены всего файла.

```yaml
- name: "Включение пересылки трафика IPv4"
  ansible.builtin.lineinfile:
    path: /etc/sysctl.conf
    regexp: '^net.ipv4.ip_forward'
    line: 'net.ipv4.ip_forward=1'
    state: present
    backup: yes
```

### Управление INI-конфигурациями (`ini_file`)

`ini_file` меняет конкретный параметр в конкретной секции, не переписывая файл целиком. Секция создаётся автоматически, если её нет. Идемпотентен: повторный запуск не даёт `changed`.

```yaml
- name: "Настройка pip через ini_file"
  ansible.builtin.ini_file:
    path: /etc/pip.conf
    section: global
    key: index-url
    value: "https://pypi.example.com/simple"
    mode: "0644"
    owner: root
    group: root
  # → changed: [target] => {"changed": true, "msg": "Added key/value in section: global"}
  # повторный запуск: ok: [target] => {"changed": false}
```

**Несколько параметров одной секции** — задача с `loop`, а не одна задача на ключ:

```yaml
- name: "Настройка индекса пакетов PyPI"
  ansible.builtin.ini_file:
    path: /etc/pip.conf
    section: global
    key: "{{ item.key }}"
    value: "{{ item.value }}"
    mode: "0644"
  loop:
    - { key: "index-url", value: "https://pypi.example.com/simple" }
    - { key: "trusted-host", value: "pypi.example.com" }
    - { key: "timeout", value: "60" }
  loop_control:
    label: "{{ item.key }}={{ item.value }}"
  # → changed: [target] => (item=global.index-url) => {"changed": true}
  # → changed: [target] => (item=global.trusted-host) => {"changed": true}
  # → changed: [target] => (item=global.timeout) => {"changed": true}
```

**Ключ в нескольких секциях одного файла** — главный сценарий, ради которого `ini_file` и нужен. В `grafana.ini` параметр `http_port` встречается и в `[server]`, и в `[server.http]`, и в `[server.udp]`; `lineinfile` с `regexp` изменил бы их все:

```yaml
- name: "Изменение порта только в основной секции Grafana"
  ansible.builtin.ini_file:
    path: /etc/grafana/grafana.ini
    section: server
    key: http_port
    value: "8080"
  # → changed: [target] => {"changed": true, "msg": "Changed key/value in section: server"}
```

**Удаление параметра и целой секции:**

```yaml
- name: "Удаление устаревшего параметра"
  ansible.builtin.ini_file:
    path: /etc/pip.conf
    section: global
    key: extra-index-url
    state: absent
  # → changed: [target] => {"changed": true, "msg": "Removed key/value in section: global"}

- name: "Удаление всей секции"
  ansible.builtin.ini_file:
    path: /etc/app/config.ini
    section: legacy_settings
    state: absent
  # секция [legacy_settings] целиком удаляется со всеми ключами
```

**Типичные параметры:**

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `path` | путь | Путь к INI-файлу. Относительный путь разрешается относительно каталога с плейбуком |
| `section` | строка | Имя секции **без** квадратных скобок |
| `key` | строка | Имя параметра. **Обязателен** при `state: present`, не нужен при `state: absent` для всей секции |
| `value` | строка | Новое значение. Значения приводятся к строке |
| `state` | `present` / `absent` | Установить/создать или удалить |
| `create` | `yes` / `no` | Создавать ли файл, если его нет (по умолчанию `yes`) |
| `regextype` | `sre` / `posix` | Тип регулярных выражений (влияет на `option` для парсинга) |
| `backup` | `yes` / `no` | Резервная копия перед изменением |
| `mode`, `owner`, `group` | — | Атрибуты файла. `mode` всегда в восьмеричном виде в кавычках |

**Важные особенности и подводные камни:**

- **Комментарии и форматирование сохраняются** в отличие от `template`. Это главная причина не переписывать INI-файл целиком: в `pip.conf`, `grafana.ini`, `netdata.conf` правки вручную накапливаются, и полная перезапись шаблоном их уничтожит.
- **Значения в кавычках.** Модуль сохраняет кавычки в том виде, в каком они переданы. Если в файле значение было `"8080"`, а передано `8080`, Ansible посчитает их разными и будет помечать задачу как `changed` на каждом запуске. Передавайте значение ровно в том формате, в каком оно должно лежать в файле.
- **Секция указывается без скобок:** `section: global`, а не `section: "[global]"`. Со скобками модуль создаст секцию с именем `[global]` внутри скобок — неверная структура.
- **Пустой `value` удаляет ключ.** Чтобы задать пустое значение осознанно, передайте `value: '""'` (две кавычки как символы).
- **Нет вложенности секций.** `ini_file` не поддерживает многоуровневые секции вида `[a.b.c]` из некоторых форматов — вложенные секции обрабатываются как плоские имена. Если формат требует вложенности, используйте `template`.
- **Нет параметров без секции.** Параметры до первой секции (в некоторых форматах глобальные) изменить нельзя — модуль требует `section`.
- **Проверка перед изменением через `--check --diff`** обязательна: модуль корректно показывает, какая секция и какой ключ будут затронуты, что позволяет поймать опечатку в имени секции до применения.

```bash
# Проверка без применения
ansible-playbook -i inventory.ini site.yml --check --diff --tags pip_config
```

**Типичные ошибки:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Section 'X' not found` при `state: absent` | Секции нет в файле — удалять нечего | Ожидаемое поведение, задача вернёт `ok: changed=false` |
| Постоянный `changed` при повторных запусках | Несовпадение кавычек или пробелов вокруг значения | Сверьте точное содержимое: `ansible.builtin.slurp` + `b64decode` |
| Изменились все одноимённые ключи | Использован `lineinfile` с `regexp` вместо `ini_file` | Замените на `ini_file` с явной `section` |
| Файл не создан | `create: no` и файла нет на хосте | Проверьте наличие каталога-родителя через `ansible.builtin.file` |
| Секция создана, но ключ не вставлен | `section` передан в квадратных скобках | Уберите скобки: `section: global` |

### Тонкая настройка прав через ACL

Предоставление доступа конкретному пользователю без изменения владельца/группы директории.

```yaml
- name: "Разрешение чтения логов для пользователя мониторинга"
  ansible.posix.acl:
    path: /var/log/nginx
    entity: prometheus
    etype: user
    permissions: rx
    state: present
    recursive: yes
```

### Сбор логов по критериям (`find` + `fetch`)

Сначала ищем файлы по размеру и дате, затем выгружаем их на контрольный узел. Используйте `limit` для предотвращения перегрузки при большом количестве файлов.

```yaml
- name: "Поиск тяжелых логов"
  ansible.builtin.find:
    paths: /var/log/myapp
    size: 10M
    age: 1d
    age_stamp: mtime
    file_type: file
    limit: 50
  register: log_files

- name: "Выгрузка найденных логов"
  ansible.builtin.fetch:
    src: "{{ item.path }}"
    dest: "./backup_logs/{{ inventory_hostname }}/"
    flat: yes
  loop: "{{ log_files.files }}"
  when: log_files.matched > 0
```

### Использование кастомных маркеров в `blockinfile`

Позволяет избежать конфликтов со стандартными маркерами Ansible, если файл уже содержит аналогичные комментарии.

```yaml
- name: "Добавление настроек в кастомный конфиг"
  ansible.builtin.blockinfile:
    path: /etc/my_app.conf
    marker: "# {mark} MY APP SETTINGS"
    block: |
      setting_a = true
      setting_b = false
```

### Массовая замена текста с помощью `replace`

Использование регулярных выражений для патчинга конфигурационных файлов.

```yaml
- name: "Замена IP-адреса в конфигурации"
  ansible.builtin.replace:
    path: /etc/hosts
    regexp: '(192\.168\.1\.)\d+'
    replace: '\g<1>100'
    backup: yes
```

### Проверка файловых атрибутов через `stat`

Использование фактов из `stat` для условного выполнения задач. Начиная с ansible-core 2.20, `stat` может возвращать контекст SELinux.

```yaml
- name: "Проверка существования файла конфигурации"
  ansible.builtin.stat:
    path: /etc/myapp/config.yml
    get_attributes: yes
    get_selinux_context: yes
  register: config_stat

- name: "Создание файла конфигурации если не существует"
  ansible.builtin.template:
    src: config.yml.j2
    dest: /etc/myapp/config.yml
    owner: root
    group: root
    mode: '0644'
  when: not config_stat.stat.exists
```

### Загрузка файлов с аутентификацией

Использование `get_url` с заголовками авторизации для скачивания артефактов. Используйте `no_log: true` для маскировки токенов в логах.

```yaml
- name: "Загрузка приватного артефакта"
  ansible.builtin.get_url:
    url: "https://artifacts.example.com/v1.0/app.tar.gz"
    dest: /tmp/app.tar.gz
    headers:
      Authorization: "Bearer {{ lookup('env', 'ARTIFACT_TOKEN') }}"
    mode: '0644'
    timeout: 60
  register: download_result
  no_log: true

- name: "Проверка успешности загрузки"
  ansible.builtin.debug:
    msg: "Артефакт загружен успешно: {{ download_result.status_code }}"
  when: download_result.status_code == 200
```

### Распаковка различных форматов архивов

Примеры работы с разными форматами архивов.

```yaml
- name: "Распаковка zip-архива"
  ansible.builtin.unarchive:
    src: /tmp/backup.zip
    dest: /var/backup
    remote_src: yes
    list_files: yes
  register: zip_contents

- name: "Распаковка tar.xz архива"
  ansible.builtin.unarchive:
    src: https://releases.example.com/package.tar.xz
    dest: /opt/packages
    remote_src: yes
    creates: /opt/packages/package/
```

### Сборка файла из фрагментов (`assemble`)

Конкатенация нескольких файлов в один конфигурационный файл.

```yaml
- name: "Сборка конфигурации из фрагментов"
  ansible.builtin.assemble:
    src: /etc/myapp/conf.d/
    dest: /etc/myapp/myapp.conf
    owner: root
    group: root
    mode: '0644'
    delimiter: '# --- fragment boundary ---'
    regexp: '^# FRAGMENT:'
```

### Управление правами через символический формат

Использование символьного формата для более читаемого описания прав.

```yaml
- name: "Установка прав через символьный формат"
  ansible.builtin.file:
    path: /var/www/html
    state: directory
    owner: www-data
    group: www-data
    mode: 'u=rwx,g=rx,o=rx'
```

### Установка временных меток файлов

Явное управление временем доступа и модификации для соответствия политикам backup и аудита.

```yaml
- name: "Установка времени модификации на release-файл"
  ansible.builtin.file:
    path: /opt/app/release-2024.01.15.tar.gz
    state: file
    modification_time: 202401151200.00
    modification_time_format: "%Y%m%d%H%M.%S"
    access_time: preserve
```

### Удаление файлов с созданием резервных копий

Безопасное удаление файлов с предварительным бэкапом.

```yaml
- name: "Удаление старого конфига с бэкапом"
  ansible.builtin.file:
    path: /etc/old_config.yml
    state: absent
    backup: yes
```

### Управление конфигурацией cron через `lineinfile`

Безопасное добавление записей в cron без замены всего файла.

```yaml
- name: "Добавление задачи очистки кеша"
  ansible.builtin.lineinfile:
    path: /etc/cron.d/cleanup
    regexp: '^0 2 \* \* \* root'
    line: '0 2 * * * root /usr/local/bin/cleanup_cache.sh'
    create: yes
    owner: root
    group: root
    mode: '0644'
```

### Поиск устаревших файлов с помощью `find` и `exact_mode`

Использование точного совпадения прав для поиска файлов с проблемными разрешениями.

```yaml
- name: "Поиск файлов с правами 777"
  ansible.builtin.find:
    paths: /var/www
    mode: '0777'
    exact_mode: yes
    file_type: file
  register: insecure_files

- name: "Исправление прав на найденные файлы"
  ansible.builtin.file:
    path: "{{ item.path }}"
    mode: '0644'
  loop: "{{ insecure_files.files }}"
  when: insecure_files.matched > 0
```

### Проверка атрибутов файловой системы через `stat`

Использование `get_attributes` для проверки immutable-флагов.

```yaml
- name: "Проверка атрибутов критичных файлов"
  ansible.builtin.stat:
    path: /etc/passwd
    get_attributes: yes
  register: passwd_stat

- name: "Вывод информации об атрибутах"
  ansible.builtin.debug:
    var: passwd_stat.stat.attributes
```

## Операции и команды

### Работа с документацией модулей (`ansible-doc`)

Утилита `ansible-doc` позволяет получать справку без доступа к интернету.

```bash
# Просмотр документации модуля
ansible-doc ansible.builtin.copy

# Вывод краткого шаблона (snippet) для вставки в плейбук
ansible-doc -s ansible.builtin.file

# Список всех доступных модулей
ansible-doc -l

# Фильтрация модулей по ключевому слову
ansible-doc -l | grep file
```

### Управление коллекциями (`ansible-galaxy`)

Для модулей из коллекции `ansible.posix` (например, `acl`, `xattr`) требуется предварительная установка:

```bash
# Установка коллекции ansible.posix
ansible-galaxy collection install ansible.posix

# Просмотр установленных коллекций
ansible-galaxy collection list

# Проверка доступности модуля в установленных коллекциях
ansible-doc ansible.posix.acl
```

### Ad-hoc команды для файловых операций

Быстрое выполнение файловых операций без плейбуков:

```bash
# Создание директории
ansible all -m file -a "path=/tmp/myapp state=directory mode=0750"

# Проверка фактов о файле
ansible all -m stat -a "path=/etc/hosts"

# Копирование файла с контрольного узла
ansible all -m copy -a "src=/local/file.conf dest=/remote/file.conf owner=root mode=0644"

# Получение файла с удаленного хоста
ansible all -m fetch -a "src=/remote/logs/app.log dest=./logs/ flat=yes"

# Загрузка файла по URL
ansible all -m get_url -a "url=https://example.com/file.tar.gz dest=/tmp/file.tar.gz mode=0644"

# Распаковка архива
ansible all -m unarchive -a "src=/tmp/backup.tar.gz dest=/opt/app remote_src=yes"

# Поиск файлов по критериям
ansible all -m find -a "paths=/var/log size=10M age=1d"

# Редактирование строки в файле
ansible all -m lineinfile -a "path=/etc/sysctl.conf regexp='^net.ipv4.ip_forward' line='net.ipv4.ip_forward=1'"

# Правка ключа в секции INI-файла
ansible all -m ini_file -a "path=/etc/pip.conf section=global key=index-url value=https://pypi.example.com/simple"
```

## Устранение неполадок

### Типичные ошибки модулей

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Permission denied` | Недостаточно прав на управляемом узле | Используйте `become: yes` или проверьте права |
| `No such file or directory` | Несуществующий путь | Проверьте путь или используйте `creates` для идемпотентности |
| `Checksum mismatch` | Изменение файла после рендеринга | Проверьте конфликты параллельного доступа или внешние изменения |
| `Unable to set permissions` | Несуществующий пользователь/группа | Убедитесь что пользователь существует на хосте |
| `Module failed` | Невалидный шаблон Jinja2 | Проверьте синтаксис шаблона и переменные |
| `Atomic move failed` | Файловая система не поддерживает `rename` | Используйте `unsafe_writes: yes` или смонтируйте с поддержкой `rename` |
| `SELinux context error` | Неправильный контекст безопасности | Проверьте параметры `setype`, `seuser` или отключите SELinux для теста |
| `Remote source not found` | Файл отсутствует на управляемом хосте | Проверьте `remote_src: yes` и путь на целевом узле |
| `FIPS-403: md5 unavailable` | MD5 запрещен на FIPS-системе | Используйте `checksum_algorithm: sha256` или выше |
| `find: limit exceeded` | Количество результатов превышает `limit` | Увеличьте `limit` или сузьте критерии поиска |

### Диагностика файловых операций

```bash
# Проверка доступности модуля и его параметров
ansible-doc ansible.builtin.file
ansible-doc ansible.builtin.template

# Проверка подключения к хосту
ansible all -m ping

# Сбор фактов о файловой системе
ansible all -m setup -a "filter=ansible_mounts"

# Проверка фактов о конкретном файле
ansible all -m stat -a "path=/etc/myapp/config.yml"

# Проверка существующих файлов по шаблону
ansible all -m find -a "paths=/etc/nginx conf.d/*.conf"
```

### Режим отладки

```bash
# Максимальная вербальность для диагностики
ansible-playbook site.yml -vvvv

# Сохранение временных файлов на удаленном узле для инспекции
export ANSIBLE_KEEP_REMOTE_FILES=1
ansible-playbook site.yml -vvv

# Проверка без применения изменений
ansible-playbook site.yml --check --diff

# Просмотр различий между текущим и планируемым состоянием
ansible-playbook site.yml --diff
```

### Паттерны обработки ошибок

```yaml
- name: "Загрузка конфигурации с обработкой ошибок"
  ansible.builtin.get_url:
    url: "https://config.example.com/app.yml"
    dest: /etc/app/config.yml
    timeout: 30
    validate_certs: yes
  register: download
  retries: 3
  delay: 5
  until: download.status_code | default(500) | int < 400
  failed_when: download.status_code | default(500) | int >= 500
  changed_when: download.status_code | default(500) | int == 200
```

## Рекомендации

### Выбор правильного модуля

При выборе модуля следуйте принципу «декларативность вместо императивности»:
- Для управления состоянием файла → `ansible.builtin.file`
- Для сложных шаблонов → `ansible.builtin.template`
- Для простых замен строк → `ansible.builtin.lineinfile`
- Для массового поиска/замены по regex → `ansible.builtin.replace` или `ansible.builtin.lineinfile`
- Для INI-файлов и правки одного ключа в конкретной секции → `ansible.builtin.ini_file` (сохраняет комментарии и форматирование, в отличие от `template`)
- Для синхронизации больших объемов → `ansible.posix.synchronize` (rsync)
- Для распаковки архивов → `ansible.builtin.unarchive`
- **Избегайте**: `command`/`shell` для файловых операций (нарушают идемпотентность)

### Валидация и безопасность
- Всегда используйте `validate` для критических файлов (`/etc/sudoers`, `/etc/ssh/sshd_config`, `/etc/nginx/nginx.conf`)
- Используйте `backup: yes` при редактировании конфигурационных файлов
- Применяйте `no_log: true` для задач, работающих с чувствительными данными (токены, ключи)
- Проверяйте контрольные суммы после копирования бинарных файлов через `stat`
- Используйте `checksum_algorithm: sha256` на FIPS-совместимых системах

### Идемпотентность и тестирование
- Всегда тестируйте модули с флагом `--check` перед применением в production
- Используйте `--diff` для визуальной валидации изменений
- Для модулей `template` и `copy` проверяйте, что `changed` возвращается только при реальных изменениях
- Избегайте `force: yes` в `copy` без явной необходимости — это нарушает идемпотентность
- Используйте `creates` в `unarchive` и `command` для пропуска уже выполненных операций

### Производительность
- Для массовых операций используйте `loop` с `batch_size` вместо отдельных задач
- Для длительных операций используйте `async`/`poll` для параллельного выполнения
- Используйте `delegate_to: localhost` для предварительной компиляции шаблонов на контрольном узле
- Избегайте `find` с очень широкими шаблонами на больших файловых системах; используйте `limit` для ограничения объема
- Для синхронизации больших директорий предпочитайте `ansible.posix.synchronize` вместо `copy`/`fetch`

### Пакетная обработка файлов

Для обработки большого количества файлов используйте пакетные операции вместо итераций:

```yaml
- name: "Пакетное обновление прав"
  ansible.builtin.file:
    path: "{{ item }}"
    owner: deploy
    group: deploy
    mode: '0644'
  loop: "{{ list_of_files }}"
  batch_size: 100
```

### Параллельное выполнение

Увеличьте параллелизм для ускорения работы с файлами:

```yaml
- name: "Параллельная загрузка файлов"
  ansible.builtin.get_url:
    url: "{{ item.url }}"
    dest: "{{ item.dest }}"
  loop: "{{ files_to_download }}"
  async: 300
  poll: 0
  register: download_jobs

- name: "Ожидание завершения всех загрузок"
  ansible.builtin.async_status:
    jid: "{{ item.ansible_job_id }}"
  loop: "{{ download_jobs.results }}"
  register: async_results
  until: async_results.finished
  retries: 60
  delay: 5
```

### Управление большими наборами файлов

При работе с тысячами файлов используйте:
- `find` с `limit` для выборки порциями
- `batch_size` в `loop` для контроля потребления памяти
- `async`/`poll` для длительных операций копирования
- `synchronize` вместо `copy` для полных директорий

### Общие принципы
- Всегда используйте FQCN для модулей.
- Проверяйте идемпотентность модулей перед использованием в production.
- Документируйте нестандартные параметры и assumptions в плейбуках.
- Используйте `no_log: true` для задач с чувствительными данными.
- **Стратегии**: Используйте `strategy: free` для независимого выполнения хостов.
- **Сборщики**: Используйте `ansible.builtin.package_facts` и `service_facts` вместо многократного вызова `setup`.

## Дополнительная информация

- **[Шаблонизация Jinja2](../ansible_jinja_templating.md)** — динамическая генерация файлов.
- **[Action-плагины](../ansible-action-plugins.md)** — как работают `template`, `copy`, `fetch` на уровне плагинов.
- **[Обзор модулей Ansible](ansible_modules_overview.md)** — выбор правильного инструмента управления файлами.
- **[Атомарные операции](../../Concepts/atomic_operations.md)** — теоретические основы атомарности и ее реализация в Ansible.
