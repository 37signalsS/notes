# Кроссплатформенный доступ к данным и артефактам: uri, get_url, slurp, fetch

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21+ | 2.22.0b1 доступен (сентябрь 2026) |
| **Python** (control node) | 3.12+ | 3.14 | Для ansible-core 2.21 |
| **Python** (managed node, POSIX) | 3.9+ | 3.12+ | Для ansible-core 2.21 |
| **PowerShell** (Windows) | 5.1+ | 7.6 LTS | Для ansible-core 2.21/2.22 |
| **OpenSSH** | 8.0+ | 10.5+ | 10.5 — актуальный релиз (август 2026) |
| **PyWinRM** | 0.4+ | 0.5+ | 0.5.0 — текущий стабильный релиз |
| **rsync** | 3.1+ | 3.2+ | 3.2 добавляет xxHash rolling checksum |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible all -m ping
# → pong: web01
# → pong: db01
```

## Определения

- **`ansible.builtin.uri`** — кроссплатформенный модуль для выполнения HTTP-запросов. На POSIX-системах работает через Python `requests`; на Windows — через PowerShell `Invoke-RestMethod`. Используется для health-check, вызова API, проверки доступности сервисов.
- **`ansible.builtin.get_url`** — модуль для скачивания файлов по HTTP/HTTPS/FTP. На POSIX-системах работает через Python `urllib`; на Windows — через PowerShell `Invoke-WebRequest` или `WebClient`. Поддерживает `checksum`, `validate_certs`, `force`, `headers`.
- **`ansible.builtin.slurp`** — модуль для чтения содержимого файлов на удаленном хосте с возвратом в base64. Доступен только на POSIX-системах (Linux, macOS, BSD), так как relies on Python. Для Windows используйте `ansible.windows.win_shell` + `Get-Content` или делегирование на контрол-ноду.
- **`ansible.builtin.fetch`** — модуль для копирования файлов с удаленного хоста на контрол-ноду. Работает только с отдельными файлами; для директорий используйте `ansible.posix.synchronize` в режиме `pull`. На Windows используйте `ansible.windows.win_copy` с `delegate_to: localhost`.
- **`ansible.windows.win_get_url`** — нативный модуль для скачивания файлов на Windows через PowerShell. Альтернатива `get_url` при подключении по WinRM.
- **`ansible.posix.synchronize`** — модуль-обертка над `rsync` для синхронизации директорий. Поддерживает push/pull, дельта-передачу, исключения. Для больших файлов и директорий предпочтительнее `fetch`/`slurp`. Подробнее см. [Ansible: Модули синхронизации файлов](../Modules/ansible_file_synchronization_modules.md).
- **`ansible.builtin.stat`** — модуль для сбора фактов о файлах и директориях (существование, размер, права, контрольные суммы). Кроссплатформенный, работает на Linux, macOS, Windows, BSD. Подробнее см. [Ansible: Модули управления файлами](../Modules/ansible_file_management_modules.md).
- **`ansible.builtin.copy`** — модуль для копирования файлов с контрол-ноды на удаленный хост. Поддерживает `remote_src: yes` для копирования внутри хоста. На Windows используется `ansible.windows.win_copy`. Подробнее см. [Ansible: Модули управления файлами](../Modules/ansible_file_management_modules.md).
- **Lookup plugin** — механизм доступа к данным на контрол-ноде во время выполнения плейбука. `lookup('file', ...)` читает локальные файлы, `lookup('env', ...)` — переменные окружения, `lookup('pipe', ...)` — вывод команд. Выполняется на контрол-ноде, не на целевом хосте.
- **Query plugin** — аналог lookup, но возвращает список вместо строки. Используется через `query()` вместо `lookup()`. Подходит для работы с API, CMDB, внешними системами.

## Основные концепции

### Как работает кроссплатформенный доступ к данным

Ansible использует разные транспорты и среды выполнения для разных ОС:

- **POSIX (Linux, macOS, BSD)**: модули выполняются через Python на целевом хосте. `uri` использует `requests`, `get_url` — `urllib`, `slurp` — прямой чтение файла в base64, `fetch` — SFTP/SCP через Ansible транспорт.
- **Windows**: модули выполняются через PowerShell Remoting (WinRM) или SSH. `uri` на Windows использует PowerShell `Invoke-RestMethod`, `get_url` — `Invoke-WebRequest`. `slurp` и `fetch` не имеют прямых Win-аналогов в базовых коллекциях — используются делегирование или `win_copy`.
- **Контрол-нода**: lookup/query плагины выполняются на контрол-ноде. `lookup('file', ...)` читает локальные файлы, `lookup('pipe', ...)` запускает локальные команды.

### Транспортные механизмы передачи данных

| Механизм | Направление | Модуль | Кроссплатформенность |
| :--- | :--- | :--- | :--- |
| SFTP/SCP (Ansible transport) | Push/Pull | `copy`, `fetch` | POSIX |
| Python `requests`/`urllib` | Pull | `uri`, `get_url` | POSIX + Windows (через PowerShell) |
| PowerShell `Invoke-RestMethod` | Pull | `uri` | Windows |
| PowerShell `Invoke-WebRequest` | Pull | `get_url`, `win_get_url` | Windows |
| rsync (SSH) | Push/Pull | `ansible.posix.synchronize` | POSIX |
| Делегирование на контрол-ноду | Pull | `win_copy` + `delegate_to: localhost` | Windows workaround |
| Base64 кодирование | Pull | `slurp` | Только POSIX |

### Выбор модуля по сценарию

| Сценарий | POSIX | Windows |
| :--- | :--- | :--- |
| Health-check HTTP endpoint | `ansible.builtin.uri` | `ansible.builtin.uri` (через PowerShell) |
| Скачивание бинарника/архива | `ansible.builtin.get_url` | `ansible.windows.win_get_url` или делегирование на контрол-ноду |
| Чтение содержимого файла | `ansible.builtin.slurp` | `ansible.windows.win_shell` + `Get-Content` или делегирование |
| Выгрузка файла на контрол-ноду | `ansible.builtin.fetch` | `ansible.windows.win_copy` + `delegate_to: localhost` |
| Синхронизация директорий | `ansible.posix.synchronize` (rsync) | Не поддерживается нативно; используйте `delegate_to` + `synchronize` через SSH |
| Проверка атрибутов файла | `ansible.builtin.stat` | `ansible.builtin.stat` (кроссплатформенный) |
| Копирование файла на хост | `ansible.builtin.copy` | `ansible.windows.win_copy` |

### Ограничения кроссплатформенности

- **`slurp` и `fetch` не работают на Windows**: нет встроенных аналогов в `ansible.windows`. Используйте делегирование на контрол-ноду или `win_copy` в обратном направлении. Для директорий используйте `ansible.posix.synchronize`.
- **`get_url` на Windows через WinRM**: при подключении по WinRM `get_url` работает через PowerShell, но требует наличия PowerShell 5.1+ и может игнорировать некоторые параметры Python-версии (например, `checksum=sha256` работает, но `timeout` интерпретируется иначе).
- **`uri` и proxy**: на POSIX proxy задается через переменные окружения `HTTP_PROXY`/`HTTPS_PROXY`; на Windows — через `win_environment` или системные настройки PowerShell.
- **Большие файлы**: `slurp` загружает весь файл в память в base64 (размер увеличивается ~33%). Для файлов >10 MB используйте `synchronize` или разбиение на чанки. `fetch` работает только с отдельными файлами, не с директориями.
- **SSL/TLS**: `validate_certs: false` работает на всех платформах, но на Windows WinRM может иметь собственные требования к сертификатам.
- **Windows и удаленный доступ к контрол-ноду**: контрол-нода должна иметь доступ к целевому хосту по WinRM/SSH при использовании `delegate_to: localhost` для обратного копирования.

## Практические сценарии

### Сценарий 1: Кроссплатформенный health-check через `uri`

Модуль `uri` работает на всех платформах. Для кроссплатформенности достаточно одного вызова:

```yaml
- name: Проверка доступности API
  ansible.builtin.uri:
    url: "http://localhost:{{ app_port }}/health"
    method: GET
    status_code: 200
    timeout: 10
    validate_certs: false
  register: health_check
  retries: 5
  delay: 10
  until: health_check.status == 200
```

> `uri` на Windows использует PowerShell `Invoke-RestMethod` под капотом. Параметры `timeout`, `validate_certs`, `headers` работают одинаково на всех платформах. Для production-сред используйте `validate_certs: true` и корректные сертификаты.

### Сценарий 2: Скачивание артефактов с учетом ОС

Для POSIX используется `get_url`, для Windows — `win_get_url` или делегирование на контрол-ноду:

```yaml
- name: Определение URL артефакта по ОС
  ansible.builtin.set_fact:
    artifact_url: "{{ 'https://example.com/linux-amd64.tar.gz' if ansible_facts['system'] != 'Win32NT' else 'https://example.com/windows-amd64.zip' }}"

- name: Скачивание артефакта (POSIX)
  ansible.builtin.get_url:
    url: "{{ artifact_url }}"
    dest: "/tmp/artifact.tar.gz"
    checksum: sha256:abc123...
    mode: '0644'
    timeout: 60
  when: ansible_facts['system'] != 'Win32NT'

- name: Скачивание артефакта (Windows)
  ansible.windows.win_get_url:
    url: "{{ artifact_url }}"
    dest: "C:\\Temp\\artifact.zip"
  when: ansible_facts['system'] == 'Win32NT'
```

### Сценарий 3: Чтение файлов: `slurp` (POSIX) vs `win_shell` (Windows)

`slurp` возвращает содержимое файла в base64. Для Windows используйте PowerShell или делегирование:

```yaml
- name: Чтение конфига (POSIX)
  ansible.builtin.slurp:
    src: "/etc/myapp/config.yml"
  register: config_content
  when: ansible_facts['system'] != 'Win32NT'

- name: Декодирование содержимого (POSIX)
  ansible.builtin.set_fact:
    config_parsed: "{{ config_content.content | b64decode }}"
  when: ansible_facts['system'] != 'Win32NT'

- name: Чтение конфига (Windows)
  ansible.windows.win_shell: |
    Get-Content -Path "C:\ProgramData\MyApp\config.yml" -Raw
  register: config_content
  when: ansible_facts['system'] == 'Win32NT'
```

> **Production note:** `slurp` загружает весь файл в память в base64 (размер увеличивается ~33%). Для файлов >10 MB используйте `ansible.posix.synchronize` или разбивку на чанки. Для Windows без доступа к файлу используйте `delegate_to: localhost` с `win_copy`.

### Сценарий 4: Выгрузка файлов на контрол-ноду: `fetch` (POSIX) vs делегирование (Windows)

`fetch` работает только на POSIX и только с отдельными файлами. Для Windows и директорий используйте альтернативы:

```yaml
- name: Выгрузка лога (POSIX)
  ansible.builtin.fetch:
    src: "/var/log/myapp/app.log"
    dest: "/tmp/fetched-logs/{{ inventory_hostname }}/"
    flat: no
  when: ansible_facts['system'] != 'Win32NT'

- name: Выгрузка лога (Windows) — делегирование на контрол-ноду
  ansible.windows.win_copy:
    src: "C:\\ProgramData\\MyApp\\logs\\app.log"
    dest: "/tmp/fetched-logs/{{ inventory_hostname }}/app.log"
    delegate_to: localhost
  when: ansible_facts['system'] == 'Win32NT'
```

> При использовании `delegate_to: localhost` убедитесь, что контрол-нода имеет доступ к целевому хосту по WinRM и что пути доступны для записи. Для выгрузки директорий на POSIX используйте `ansible.posix.synchronize` в режиме `pull`.

### Сценарий 5: Сбор логов по критериям (`find` + `fetch`)

Сначала ищем файлы по размеру и дате, затем выгружаем их на контрольный узел:

```yaml
- name: Поиск тяжелых логов
  ansible.builtin.find:
    paths: /var/log/myapp
    size: 10M
    age: 7d
    age_stamp: mtime
    file_type: file
    limit: 50
  register: log_files

- name: Выгрузка найденных логов
  ansible.builtin.fetch:
    src: "{{ item.path }}"
    dest: "./backup_logs/{{ inventory_hostname }}/"
    flat: yes
  loop: "{{ log_files.files }}"
  when: log_files.matched > 0
```

### Сценарий 6: Platform-specific proxy и SSL

Прокси и сертификаты часто различаются между корпоративными Linux и Windows средами:

```yaml
- name: Установка прокси для POSIX
  ansible.builtin.environment:
    HTTP_PROXY: "{{ http_proxy }}"
    HTTPS_PROXY: "{{ https_proxy }}"
    NO_PROXY: "{{ no_proxy }}"
  when: ansible_facts['system'] != 'Win32NT'

- name: Установка прокси для Windows через win_environment
  ansible.windows.win_environment:
    name: HTTP_PROXY
    value: "{{ http_proxy }}"
    state: present
    level: machine
  when: ansible_facts['system'] == 'Win32NT'
```

### Сценарий 7: Использование lookup плагинов для данных на контрол-ноде

Lookup плагины выполняются на контрол-ноде и полезны для получения данных из файлов, окружения, Vault или внешних API:

```yaml
- name: Чтение локального файла на контрол-ноде
  ansible.builtin.set_fact:
    local_config: "{{ lookup('file', 'files/app_config.json') }}"

- name: Получение переменной окружения
  ansible.builtin.set_fact:
    artifact_token: "{{ lookup('env', 'ARTIFACT_TOKEN') }}"

- name: Чтение SSH-ключа через lookup
  ansible.builtin.set_fact:
    ssh_public_key: "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"
```

### Сценарий 8: Скачивание с retries и until

Кроссплатформенный паттерн для массового скачивания с повторными попытками:

```yaml
- name: Скачивание нескольких артефактов
  ansible.builtin.get_url:
    url: "{{ item.url }}"
    dest: "{{ item.dest }}"
    checksum: "{{ item.checksum | default(omit) }}"
    timeout: 60
  loop: "{{ artifacts[ansible_facts['os_family']] }}"
  register: download_result
  retries: 3
  delay: 5
  until: download_result is succeeded
  when: ansible_facts['system'] != 'Win32NT'
```

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible web_servers -m ansible.builtin.uri -a "url=http://localhost:80/health method=GET"` | Health-check на всех платформах | `{"status": 200, "json": {...}}` |
| `ansible web_servers -m ansible.builtin.get_url -a "url=https://... dest=/tmp/artifact.tar.gz"` | Скачивание файла (POSIX) | Файл сохранен, `changed` или `ok` |
| `ansible web_servers -m ansible.builtin.slurp -a "src=/etc/hostname"` | Чтение файла в base64 (POSIX) | `{"content": "base64...", "encoding": "base64"}` |
| `ansible web_servers -m ansible.builtin.fetch -a "src=/var/log/app.log dest=/tmp/logs/"` | Выгрузка логов на контрол-ноду (POSIX) | Файлы в `/tmp/logs/<hostname>/` |
| `ansible windows_servers -m ansible.windows.win_get_url -a "url=https://... dest=C:\\Temp\\file.zip"` | Скачивание файла (Windows) | Файл сохранен на Windows-хосте |
| `ansible web_servers -m ansible.builtin.stat -a "path=/var/log/myapp"` | Проверка атрибутов файла/директории | `stat.exists: true`, `stat.isdir: true`, `stat.size` |
| `ansible web_servers -m ansible.builtin.find -a "paths=/var/log age=7d size=10M"` | Поиск файлов по критериям | `matched: N`, список файлов в `files` |
| `ansible web_servers -m ansible.builtin.copy -a "src=config.yaml dest=/etc/myapp/config.yaml"` | Копирование файла с контрол-ноды | Файл скопирован, `changed` или `ok` |
| `ansible db01 -m ansible.posix.synchronize -a "mode=pull src=/var/backups/ dest=./backups/"` | Синхронизация директорий (pull) | Дельта-передача, `changed` при обновлениях |

## Диагностика и устранение неполадок

### uri и HTTP-запросы

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `status_code: 404` | URL не найден или ресурс перемещен | `curl -I <url>` с контрол-ноды | Проверьте URL, обновите ссылку, проверьте proxy |
| `Connection refused` | Сервис не запущен или порт закрыт firewall | `curl -v http://host:port/` | Запустите сервис, откройте порт в firewall |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Self-signed или невалидный сертификат | `openssl s_client -connect <host>:443` | Для тестов `validate_certs: false`; для production используйте валидный сертификат |
| `Timeout` | Сервис перегружен или сеть недоступна | `curl -w "%{time_total}" -o /dev/null -s http://host/` | Увеличьте `timeout`, проверьте сеть и нагрузку |
| `Proxy authentication required` | Прокси требует аутентификацию | `env | grep -i proxy` | Добавьте `proxy_user`/`proxy_password` в `uri` или настройте `win_environment` |
| `uri возвращает HTML вместо JSON` | Эндпоинт возвращает ошибку или редирект | `curl -v http://host/api` | Проверьте `method`, `status_code`, добавьте `follow_redirects: yes` |

### get_url

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `checksum mismatch` | Файл поврежден или URL ведет на старую версию | `sha256sum /tmp/artifact.tar.gz` | Удалите файл и повторите, проверьте URL |
| `get_url не работает на Windows через WinRM` | PowerShell параметры интерпретируются иначе | `win_get_url` вместо `get_url` | Используйте `ansible.windows.win_get_url` для Windows |
| `Download very slow` | Ограничение bandwidth или удаленный сервер | `curl -o /dev/null -w "%{speed_download}\n" <url>` | Используйте `delegate_to: localhost` + `copy` для больших файлов |
| `URL requires authentication` | Базовый auth или токен не переданы | `curl -H "Authorization: Bearer <token>" <url>` | Добавьте `headers` или `url_username`/`url_password` |
| `FTP не работает` | FTP заблокирован firewall или сервер не отвечает | `ftp <host>` | Используйте HTTP/HTTPS вместо FTP, проверьте firewall |

### slurp

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `MemoryError` на контрол-ноде | Файл слишком большой для base64 в памяти | `ls -lh /path/to/file` | Для файлов >10 MB используйте `synchronize` или разбивку на чанки |
| `slurp не работает на Windows` | Модуль доступен только на POSIX | `ansible_facts['system']` | Используйте `win_shell` + `Get-Content` или делегирование |
| `base64 decode error` | Файл содержит не UTF-8 символы | `file /path/to/file` | Используйте `b64decode` с параметром `errors='replace'` |
| `Permission denied` | Файл недоступен для пользователя Ansible | `sudo cat /path/to/file` | Используйте `become: yes` или настройте права |

### fetch

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `fetch не выгружает директории` | Модуль работает только с отдельными файлами | `ansible-doc ansible.builtin.fetch` | Используйте `find` + `fetch` с loop или `ansible.posix.synchronize` в режиме `pull` |
| `fetch не работает на Windows` | Модуль доступен только на POSIX | `ansible_facts['system']` | Используйте `win_copy` + `delegate_to: localhost` |
| `Permission denied` | Файл недоступен для пользователя Ansible | `sudo ls -la /path/to/file` | Используйте `become: yes` или настройте права |
| `File not found` после fetch | Путь `dest` неверен или директория не создана | `ls -la /tmp/fetched-logs/` | Убедитесь, что `dest` существует на контрол-ноде |

### Windows data retrieval

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `win_get_url возвращает 403` | Прокси или firewall блокирует запрос | `Invoke-WebRequest -Uri <url> -UseBasicParsing` на целевом хосте | Настройте `win_environment` для proxy, проверьте firewall |
| `WinRM не передает большие данные` | PSRP имеет ограничение на размер ответа | `winrm get winrm/config/winrs` | Увеличьте `MaxEnvelopeSizekb` или перенаправьте вывод в файл + `slurp` |
| `delegate_to: localhost не работает` | Контрол-нода не имеет доступа к хосту по WinRM | `Test-NetConnection -ComputerName <host> -Port 5986` | Настройте WinRM, сертификаты, firewall |
| `Get-Content возвращает пустоту` | Файл заблокирован или кодировка неверна | `Get-Content -Path "C:\path\file" -Raw -Encoding UTF8` | Укажите кодировку явно, проверьте права доступа |

### Граничные случаи и ограничения

- **Windows и slurp/fetch**: нет прямых аналогов в `ansible.windows`. Используйте делегирование на контрол-ноду или `win_copy` в обратном направлении.
- **Большие файлы и slurp**: base64-кодирование увеличивает объем на 33%. Для файлов >10 MB используйте `synchronize` или разбивку на чанки.
- **get_url на Windows через WinRM**: некоторые параметры (например, `timeout`) могут интерпретироваться PowerShell-ом иначе, чем Python-ом. Тестируйте edge cases.
- **SSL-сертификаты на Windows**: WinRM имеет собственные требования к сертификатам. `validate_certs: false` в `uri`/`get_url` отключает проверку на уровне модуля, но не на уровне WinRM-транспорта.
- **Прокси на macOS**: Homebrew-installed Python может игнорировать системные proxy-настройки. Указывайте `HTTP_PROXY` явно через `environment`.
- **Авторизация в uri**: Basic Auth (`url_username`/`url_password`) работает на всех платформах, но на Windows пароль может暴露 в логах WinRM. Используйте `no_log: true`.
- **fetch и директории**: `fetch` работает только с отдельными файлами. Для выгрузки директорий используйте `find` + `fetch` с loop или `ansible.posix.synchronize` в режиме `pull`.
- **synchronize и Windows**: `ansible.posix.synchronize` работает только на POSIX. На Windows используйте `win_copy` или `win_robocopy` для синхронизации.
- **rsync и SSH Agent**: при синхронизации между двумя удаленными серверами через `delegate_to` требуется проброс SSH-агента.

## Рекомендации и лучшие практики

1. **`validate_certs: true` в production**: отключайте проверку сертификатов только для тестов. Используйте валидные сертификаты и внутренние CA.
2. **`no_log: true` для секретов**: маскируйте токены, пароли, ключи в логах Ansible. Особенно важно на Windows, где WinRM логирует больше данных.
3. **`slurp` только для небольших файлов**: base64 увеличивает размер на 33%. Для файлов >10 MB используйте `synchronize` или `fetch` с `find`.
4. **`fetch` + `find` для директорий**: комбинируйте `find` для поиска файлов по критериям с `fetch` для выгрузки.
5. **`synchronize` для больших объемов**: rsync с дельта-алгоритмом эффективнее `copy`/`fetch` для больших файлов и директорий.
6. **Прокси через environment**: на POSIX используйте `environment` для прокси; на Windows — `win_environment`.
7. **Lookup для контрол-нода**: используйте `lookup('file', ...)` и `lookup('env', ...)` для доступа к данным на контрол-ноде, а не на целевом хосте.
8. **Делегирование для Windows**: при обратном копировании (Windows → контрол-нода) используйте `delegate_to: localhost` с `win_copy`.
9. **Проверка применения**: после `get_url`/`fetch`/`slurp` проверяйте `register` результаты и используйте `failed_when` для кастомной обработки ошибок.
10. **`timeout` для медленных сетей**: увеличивайте `timeout` в `uri`/`get_url` для WAN-сетей и медленных серверов.
11. **`checksum` для целостности**: всегда используйте `checksum` в `get_url` для критичных артефактов. На FIPS-системах используйте SHA-256+.
12. **Тестируйте на pilot-группе**: при изменении `proxy`, `validate_certs` или параметров скачивания тестируйте на небольшой группе хостов перед массовым применением.
13. **Используйте Molecule**: тестируйте идемпотентность и корректность получения данных на изолированных инстансах.
14. **Кэширование lookup**: для часто используемых lookup плагинов рассмотрите кэширование через `cacheable: true` (если поддерживается плагином).
15. **Документируйте endpoints**: ведите актуальный реестр внутренних API, токенов и endpoints. Используйте `uri` для проверки доступности в CI/CD.

## Дополнительная информация

- [Ansible: Модули управления файлами](../Modules/ansible_file_management_modules.md) — `copy`, `fetch`, `slurp`, `stat`, `get_url`, `unarchive`, `remote_src`.
- [Ansible: Модули синхронизации файлов](../Modules/ansible_file_synchronization_modules.md) — `synchronize` (rsync) для больших объемов и директорий.
- [Windows-автоматизация](../ansible_windows_automation.md) — нативные `win_*` модули для скачивания и работы с файлами.
- [Кроссплатформенные концепции](./concepts.md) — матрица платформ, `ansible_facts`, общие паттерны.
- [Кроссплатформенное выполнение](./ansible_cross_platform_execution_flow.md) — `strategy`, `serial`, `throttle`, `check_mode`, `async`, `tags`, `--limit`.
- [Ansible: Модули управления сетевым оборудованием](../Modules/ansible_network_device_modules.md) — `httpapi`, `netconf`, RESTCONF для сетевых устройств.
