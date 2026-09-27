# Конфигурация клиента SSH (`~/.ssh/config`)

## Определения

**`~/.ssh/config`** — конфигурационный файл SSH-клиента для определения псевдонимов хостов и индивидуальных параметров подключения (пользователь, порт, ключ, сжатие). Упрощает и автоматизирует подключение к часто используемым серверам.

**Include** — директива для модульной организации конфигурации. Позволяет подключать внешние файлы, например, разделяя настройки для рабочих и личных проектов.

**Match** — механизм условной конфигурации. В отличие от `Host`, позволяет задавать параметры на основе более сложных критериев: текущего пользователя, сетевого окружения (локальная сеть или VPN) или результата выполнения внешней команды.

**Jump Host (ProxyJump)** — промежуточный защищённый сервер (бастион), используемый как единая точка входа во внутреннюю сеть. Клиент подключается к Jump Host, который создаёт прозрачный TCP-туннель до целевого сервера.

**SSH Multiplexing** — повторное использование одного TCP-соединения для нескольких SSH-сессий (включая `scp`, `sftp`, `git`). Позволяет мгновенно открывать новые сессии, пропуская этапы TCP-handshake и SSH-аутентификации.

**IdentityAgent** — директива, указывающая путь к Unix-сокету SSH-агента. Позволяет использовать внешние менеджеры ключей (1Password, GPG-agent, Apple Keychain) вместо стандартного `ssh-agent`.

**CanonicalizeHostname** — автоматическое преобразование коротких имен хостов в полные доменные имена (FQDN) на основе заданных суффиксов.

**ProxyCommand** — альтернатива `ProxyJump` для OpenSSH < 7.3 или сложных сценариев, где трафик должен пройти через произвольную команду (например, `nc`, `socat`, `tor`). В отличие от `ProxyJump`, `ProxyCommand` дает полный контроль над TCP-соединением.

**PreferredAuthentications** — список методов аутентификации, которые клиент попробует по порядку. Позволяет запретить менее безопасные методы (например, пароль) для конкретного хоста.

**IdentitiesOnly** — директива, ограничивающая использование ключей только теми, которые явно указаны через `IdentityFile`. Без нее `ssh-agent` может предложить серверу все загруженные ключи, что приводит к ошибке `Too many authentication failures`.

**ControlPersist** — время (в секундах или формате `10m`, `1h`, `yes`), в течение которого мастер-сокет мультиплексирования остается открытым после закрытия последней сессии.

**UserKnownHostsFile** — путь к файлу известных хостов. Позволяет использовать отдельные файлы для разных сред или временные файлы (например, `/dev/null` для CI/CD).

**HostKeyAlgorithms** — явный список алгоритмов ключей хостов, которые клиент готов принять. Используется для принудительного отключения устаревших алгоритмов (например, `ssh-rsa` с SHA-1) или для совместимости со старыми серверами.

Инструменты передачи файлов (`scp`, `sftp`, `rsync`): [Инструменты командной строки SSH](./ssh_cli_tools.md).

## Базовые концепции

### Структура файла `~/.ssh/config`

Файл состоит из блоков `Host` или `Match`, каждый из которых задает параметры для конкретного псевдонима или группы хостов. Настройки применяются по принципу **первого совпадения**: если директива определена в начале файла, последующие блоки её не переопределят (кроме глобального блока `Host *`).

**Приоритет директивы `Include`:**
Вложенные файлы обрабатываются синхронно в момент чтения директивы. Порядок файлов внутри `Include ~/.ssh/config.d/*` определяется алфавитным порядком (как в glob). Это значит, что настройки из `01-defaults.conf` будут применены раньше, чем из `99-hardening.conf`, даже если оба файла подключены через `Include` в начале основного конфига. При конфликте директив в рамках одного блока `Host` побеждает последнее прочтение.

**Модульность:** Современные конфигурации часто начинаются с директивы `Include`, что позволяет разбить один огромный файл на логические части.

```ssh
# Подключение всех файлов из директории
Include ~/.ssh/config.d/*
```

**Проверка эффективной конфигурации (`ssh -G`):**
Поскольку настройки применяются по принципу первого совпадения, итоговый конфиг может быть неочевидным. Утилита `ssh -G` показывает все параметры, которые будут применены к конкретному хосту.
```bash
ssh -G my-work-server
# → user admin
# → hostname 1.2.3.4
# → port 2222
```

### Основные директивы

| Директива | Описание |
| :--- | :--- |
| `Host <alias>` | Начало блока настроек для псевдонима |
| `Host *` | Глобальные настройки (рекомендуется размещать в конце файла) |
| `HostName` | Реальное имя хоста или IP-адрес |
| `User` | Имя пользователя для входа |
| `Port` | Порт SSH на сервере |
| `IdentityFile` | Путь к приватному ключу (рекомендуется Ed25519) |
| `Compression` | Включает сжатие (`yes`/`no`) |
| `ForwardAgent` | Проброс `ssh-agent` (**опасно**, по умолчанию `no`) |
| `AddKeysToAgent` | Автоматическое добавление ключа в агент при использовании |
| `PreferredAuthentications` | Порядок методов аутентификации (например, `publickey,password`) |
| `IdentitiesOnly` | Использовать только ключи из `IdentityFile`, игнорировать `ssh-agent` |
| `ControlPersist` | Время жизни мастер-сокета после закрытия сессий (`10m`, `1h`, `yes`) |
| `UserKnownHostsFile` | Путь к файлу known_hosts (можно `/dev/null` для CI/CD) |
| `HostKeyAlgorithms` | Явный список алгоритмов ключей хостов (например, `ssh-ed25519`) |

### Принцип работы Jump Host

При использовании `ProxyJump` SSH-клиент устанавливает зашифрованное соединение с Jump Host, затем запрашивает создание TCP-туннеля до целевого сервера. Весь трафик между клиентом и целевым сервером инкапсулируется в этот туннель, при этом Jump Host не имеет доступа к данным сессии.

**Архитектура `ProxyJump` (OpenSSH 7.3+):**
```
Клиент → [SSH + TCP-туннель] → Jump Host → [прозрачный TCP] → Целевой сервер
```
Ключевые преимущества перед `ProxyCommand`:
1. **Автоматизация TCP:** SSH сам управляет туннелем, не требует внешнего `nc`/`socat`.
2. **Цепочка прыжков:** Для нескольких бастионов хосты перечисляются через запятую: `-J bastion1,bastion2`.
3. **Безопасность:** Jump Host не видит шифртекст сессии между клиентом и целевым хоста.

### Принцип работы ProxyCommand

Используется для OpenSSH < 7.3 или сложных сценариев, где требуется кастомная обработка трафика (например, `nc` через `tor`, `socat` с TLS, или Mosh).

```ssh
Host internal-server
  ProxyCommand ssh -W %h:%p bastion
  # Или с nc (OpenSSH < 7.3):
  ProxyCommand nc -X 5 -x proxy.example.com:1080 %h %p
```

**Различия `ProxyJump` vs `ProxyCommand`:**
| Критерий | `ProxyJump` | `ProxyCommand` |
| :--- | :--- | :--- |
| **OpenSSH версия** | ≥ 7.3 | Любая |
| **Требуемые утилиты** | Только SSH | `nc`, `socat`, `telnet` и др. |
| **Цепочка прыжков** | Встроенная (`-J h1,h2`) | Ручная конфигурация |
| **Сложные сценарии** | Ограничена | Полный контроль над трафиком |

Подробнее: [SSH Authentication](./server/ssh_authentication.md#подключение-через-bastion-proxyjump).

### Принцип работы мультиплексирования

Первая сессия создаёт «мастер-канал» и управляющий сокет (unix-файл). Все последующие сессии подключаются к этому сокету, используя уже установленное TCP-соединение. Это значительно ускоряет работу скриптов автоматизации (Ansible, CI/CD) и массовых операций копирования.

**Жизненный цикл сокета:**
1. Первое подключение: TCP-handshake + SSH-KEX + аутентификация (~200-500 мс).
2. Создание `ControlPath` (например, `~/.ssh/sockets/%r@%h-%p`).
3. Последующие подключения: только обмен внутри уже зашифрованного канала (<5 мс).

**Важность для DevOps/SRE:**
- **Ansible:** При выполнении 100+ задач на 50 хостах мультиплексирование сокращает время выполнения в разы, так как для каждой задачи не нужно повторно аутентифицироваться.
- **CI/CD:** В пайплайнах с множеством шагов (например, `ansible-playbook` → `kubectl` через bastion) мультиплексирование экономит время и снижает нагрузку на jump-хосты.
- **Ротация ключей:** При замене ключа на сервере достаточно переподключить мастер-канал один раз; все дочерние сессии автоматически используют новое соединение.

## Практические сценарии

Права доступа: `~/.ssh/config` — `600`. Подробнее: [SSH Authentication](./server/ssh_authentication.md#контроль-прав-доступа).

### Современная закаленная конфигурация

Рекомендуется размещать глобальные настройки безопасности в блоке `Host *`.

```ssh
# Глобальные настройки (безопасность и удобство)
Host *
  # Автоматически добавлять ключ в ssh-agent при первом использовании
  AddKeysToAgent yes
  # Использовать Keychain на macOS для хранения паролей ключей
  # UseKeychain yes

  # Безопасность
  ForwardAgent no
  HashKnownHosts yes
  VisualHostKey yes
  # Защита от квантовых компьютеров (OpenSSH 10.0+)
  KexAlgorithms mlkem768x25519-sha256,sntrup761x25519-sha512@openssh.com
  # Только надежные шифры и MAC
  Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com
  MACs hmac-sha2-512-etm@openssh.com

  # Стабильность соединения (Keep-alive)
  ServerAliveInterval 60
  ServerAliveCountMax 3

  # Отключение устаревших методов аутентификации
  GSSAPIAuthentication no
  PreferredAuthentications publickey,keyboard-interactive,password

# Псевдоним для рабочего сервера
Host work
  HostName 1.2.3.4
  User admin
  Port 2222
  IdentityFile ~/.ssh/id_ed25519_work
```

### Настройка подключения через Jump Host (`ProxyJump`)

`ProxyJump` (флаг `-J`) — стандарт с OpenSSH 7.3. Для нескольких прыжков хосты перечисляются через запятую.

```ssh
Host bastion
  HostName 203.0.113.10
  User admin

Host internal-server
  HostName 10.0.0.50
  User app_user
  ProxyJump bastion
```

### Использование внешних агентов (IdentityAgent)

Для интеграции с менеджерами паролей или смарт-картами:

```ssh
# Пример для 1Password (macOS)
Host *
  IdentityAgent "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"

# Пример для GPG-agent (поддержка смарт-карт YubiKey/OpenPGP)
Host *
  IdentityAgent "~/.gnupg/S.gpg-agent.ssh"
```

### Динамическое туннелирование (SOCKS Proxy)

Превращает удаленный SSH-сервер в прокси-сервер для локальных приложений.

```ssh
Host proxy-tunnel
  HostName remote-server.com
  DynamicForward 1080
  # Опционально: отключить запуск оболочки, только туннель
  SessionType none
```
*   **Использование:** Настроить в браузере SOCKS5-прокси на `127.0.0.1:1080`.

### Модульная конфигурация (директория .d)

Для разделения личных и рабочих настроек создайте структуру:

```bash
mkdir -p ~/.ssh/config.d
# Создать отдельные файлы для проектов
touch ~/.ssh/config.d/work ~/.ssh/config.d/personal
```

В начале основного `~/.ssh/config`:
```ssh
Include ~/.ssh/config.d/*
```

### Специфика macOS

Для интеграции с системной связкой ключей (Keychain), чтобы не вводить пароль ключа после перезагрузки:

```ssh
Host *
  AddKeysToAgent yes
  UseKeychain yes
  IdentityFile ~/.ssh/id_ed25519
```

### CI/CD: конфигурация для пайплайнов

В конвейерах автоматизации (GitLab CI, Jenkins, GitHub Actions) требуется неинтерактивный режим с предсказуемым поведением.

```ssh
# Глобальные настройки для CI/CD раннеров
Host *
  BatchMode yes
  StrictHostKeyChecking accept-new
  UserKnownHostsFile ~/.ssh/known_hosts_ci
  IdentityFile ~/.ssh/ci_deploy_key
  IdentitiesOnly yes
```

**Практические нюансы:**
- `BatchMode yes` отключает любой интерактивный ввод (пароли, 2FA). Если ключ отсутствует или неверный — соединение завершается ошибкой, а не зависает.
- `StrictHostKeyChecking accept-new` (OpenSSH 7.6+) автоматически добавляет новые хосты, но отклоняет измененные. Это безопаснее, чем `no`, и не требует ручного `ssh-keyscan` при первом запуске раннера.
- `UserKnownHostsFile` изолирует known_hosts раннера от пользовательского файла, предотвращая загрязнение.

**GitLab CI пример (`.gitlab-ci.yml`):**
```yaml
deploy:
  image: alpine:latest
  before_script:
    - apk add --no-cache openssh-client
    - mkdir -p ~/.ssh
    - echo "$SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
    - chmod 600 ~/.ssh/id_ed25519
    - ssh-keyscan -H target-server >> ~/.ssh/known_hosts_ci
  script:
    - ssh -o StrictHostKeyChecking=accept-new deploy@target-server "systemctl restart app"
```

### Git через SSH

Git использует SSH для `git@github.com:user/repo.git`. Конфигурация в `~/.ssh/config` влияет на все операции `git clone/push/pull`.

**Псевдоним для Git:**
```ssh
Host github-work
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_work
  IdentitiesOnly yes
```

**Использование:**
```bash
git clone git@github-work:company/project.git
# или через GIT_SSH_COMMAND:
GIT_SSH_COMMAND='ssh -i ~/.ssh/id_ed25519_work' git clone git@github.com:company/project.git
```

**Множественные аккаунты GitHub/GitLab:**
```ssh
# Рабочий аккаунт
Host github-work
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_work

# Личный аккаунт
Host github-personal
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_personal
```

### Ansible и SSH-конфиг

Ansible по умолчанию использует `ssh` из PATH и читает `~/.ssh/config`. Для управления множеством сред удобно использовать блоки `Host` с явными указаниями.

```ssh
# ~/.ssh/config
Host prod-*
  User deploy
  IdentityFile ~/.ssh/id_ed25519_prod
  ProxyJump bastion-prod
  StrictHostKeyChecking accept-new

Host staging-*
  User deploy
  IdentityFile ~/.ssh/id_ed25519_staging
  ProxyJump bastion-staging
```

**Важно для Ansible:**
- `ansible_ssh_private_key_file` в inventory переопределяет `IdentityFile` из конфига.
- Если в `ssh-agent` загружено много ключей, добавьте в конфиг `IdentitiesOnly yes` для конкретных хостов, иначе Ansible будет получать `Too many authentication failures`.
- Для совместимости с старыми серверами, где PQC не поддерживается, используйте `ansible_ssh_extra_args='-o KexAlgorithms=curve25519-sha256'`.

### Управление несколькими ключами (Multi-Identity)

При работе с десятками окружений (prod, staging, vendor, personal) в одном `ssh-agent` может накопиться 10+ ключей, что вызывает `Too many authentication failures` на сервере (лимит `MaxAuthTries` по умолчанию — 6).

**Решение 1: `IdentitiesOnly yes`**
```ssh
Host vendor-api
  IdentityFile ~/.ssh/id_ed25519_vendor
  IdentitiesOnly yes
```

**Решение 2: Раздельные агенты**
```bash
# Агент для продакшена
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519_prod
# Агент для вендоров
eval "$(ssh-agent -s -a ~/.ssh/agents/vendor)" && ssh-add ~/.ssh/id_ed25519_vendor
```

**Решение 3: `IdentityAgent` для изоляции**
```ssh
Host vendor-*
  IdentityAgent ~/.ssh/agents/vendor
  IdentityFile ~/.ssh/id_ed25519_vendor
  IdentitiesOnly yes
```

### Сложные цепочки бастионов (ProxyCommand)

Когда `ProxyJump` недостаточно (например, требуется SOCKS5-прокси, Mosh, или нестандартный порт на промежуточном узле):

```ssh
# Бастион с нестандартным портом
Host bastion-alt
  HostName 203.0.113.10
  Port 2222
  User jumper

# Целевой сервер через нестандартный бастион
Host internal-app
  HostName 10.0.0.50
  User app_user
  ProxyCommand ssh -p 2222 -W %h:%p jumper@bastion-alt
```

**Цепочка из трех узлов:**
```ssh
Host gate
  HostName 203.0.113.10
  User gateway

Host mid
  HostName 10.0.0.1
  User miduser
  ProxyCommand ssh -W %h:%p gate

Host app
  HostName 10.0.1.20
  User app
  ProxyJump mid
```

### Network-aware конфигурация (Match exec)

Автоматическое переключение настроек в зависимости от местоположения:

```ssh
# Работа из офиса: использование корпоративного прокси и корпоративного ключа
Match exec "curl -s --max-time 2 http://corp-gw.internal/healthz >/dev/null 2>&1"
  IdentityFile ~/.ssh/id_ed25519_corp
  ProxyCommand corkscrew corp-proxy.internal 3128 %h %p

# Домашняя сеть: локальный ключ
Match exec "curl -s --max-time 2 http://192.168.1.1 >/dev/null 2>&1"
  IdentityFile ~/.ssh/id_ed25519_home
  ProxyJump bastion-home

# Всё остальное: универсальный ключ
Match *
  IdentityFile ~/.ssh/id_ed25519_default
```

**Важно:** `Match exec` выполняет команду при каждом подключении. Избегайте долгих скриптов; используйте таймауты (`curl --max-time 2`) и кэширование.

### Чек-лист hardening клиентского конфига

Для SRE/sysadmin рекомендуется следующий минимальный набор глобальных настроек:

```ssh
Host *
  # Аутентификация
  PreferredAuthentications publickey
  IdentitiesOnly yes
  PubkeyAcceptedAlgorithms ssh-ed25519,sk-ed25519@openssh.com,ssh-rsa

  # Безопасность
  StrictHostKeyChecking accept-new
  HashKnownHosts yes
  ForwardAgent no
  ForwardX11 no

  # Стабильность
  ServerAliveInterval 60
  ServerAliveCountMax 3
  TCPKeepAlive yes

  # Производительность
  Compression yes
  ControlMaster auto
  ControlPath ~/.ssh/sockets/%r@%h:%p
  ControlPersist 10m
```

**Обоснование:**
- `PreferredAuthentications publickey` исключает парольную аутентификацию полностью, защищая от brute-force.
- `IdentitiesOnly yes` предотвращает утечку лишних ключей через `ssh-agent`.
- `ForwardX11 no` отключает X11 Forwarding по умолчанию, что исключает целый класс атак на X-сервер.
- `Compression yes` полезно при работе с текстовыми протоколами (SSH, Git) через медленные каналы; для бинарных потоков (видео, образы) может снижать производительность.

### Валидация конфигурации

Перед применением конфига проверяйте его синтаксис и эффективные параметры:

```bash
# 1. Проверить синтаксис
ssh -F ~/.ssh/config -G dummy-host 2>&1 | head -5
# → Если нет вывода — ошибок в синтаксисе нет

# 2. Убедиться, что хост разрешается
ssh -G work | grep -E "hostname|port|user"
# → hostname 1.2.3.4
# → port 2222
# → user admin

# 3. Проверить, какие ключи будут предложены
ssh -v work 2>&1 | grep "Offering public key"
# → debug1: Offering public key: /home/user/.ssh/id_ed25519_work ED25519 SHA256:...

# 4. Проверить алгоритмы
ssh -vv work 2>&1 | grep -E "kex|cipher|mac"
```

### Настройка SSH Multiplexing

Ускоряет повторные подключения (например, в Ansible).

1. Создать директорию для сокетов:

```bash
mkdir -p ~/.ssh/sockets
chmod 700 ~/.ssh/sockets
```

2. Добавить настройки мультиплексирования:

```ssh
Host *
  ControlMaster auto
  ControlPath ~/.ssh/sockets/%r@%h:%p
  ControlPersist 10m
```

**Важно:** Длина пути Unix-сокета ограничена ~108 символами (субъект реализации ядра Linux). При длинных именах хостов или пользователей путь может превысить лимит:
```
ControlPath ~/.ssh/sockets/%r@%h:%p
# user@very-long-hostname.example.com:2222 — может превысить 108 символов
```
Решение: использовать короткий путь с хешем:
```ssh
ControlPath ~/.ssh/S/%C
# %C — локальный путь к хосту (хэш), гарантированно короткий
```

**Интеграция с Ansible:**
Ansible автоматически использует мультиплексирование, если `ControlPath` настроен. Для проверки:
```bash
# Запуск playbook с таймингом
time ansible all -m ping
# При первом запуске — TCP+SSH handshake (~0.5-1s на хост)
# При повторных — только каналы (<0.05s на хост)
```

Управление активными каналами:

```bash
# Проверить наличие мастера
ssh -O check work
# → Master running (pid=1234)

# Принудительно закрыть соединение
ssh -O exit work
# → Exit request sent.

# Отправить запрос на добавление туннеля к живому соединению
ssh -O forward -S ~/.ssh/S/%C work -L 8080:localhost:80
```

### Управление ключами с помощью `ssh-agent`

`ssh-agent` хранит расшифрованные ключи в оперативной памяти.

```bash
# Запуск агента (если не запущен ОС)
eval "$(ssh-agent -s)" # → Agent pid 5678

# Добавление ключа
ssh-add ~/.ssh/id_ed25519

# Просмотр загруженных ключей
ssh-add -l # → 256 SHA256:... user@host (ED25519)

# Удаление всех ключей из памяти
ssh-add -D
```

## Дополнительная информация

### Условная конфигурация (`Match`)

Директива `Match` позволяет применять настройки на основе условий, которые нельзя проверить через `Host`.

**Полный список критериев `Match`:**
| Критерий | Пример | Описание |
| :--- | :--- | :--- |
| `Host` | `Match Host *.internal` | Имя хоста или IP (поддерживает wildcards `*` и `?`) |
| `HostAddress` | `Match HostAddress 10.0.0.*` | IP-адрес хоста (после DNS-разрешения) |
| `LocalAddress` | `Match LocalAddress 192.168.1.*` | Локальный IP-адрес клиента |
| `LocalPort` | `Match LocalPort 22,2222` | Локальный порт клиента |
| `User` | `Match User deploy` | Имя локального пользователя |
| `Exec` | `Match exec "test -f /etc/is-vpn"` | Результат выполнения команды (0 = успех) |

```ssh
# Применять настройки только если я нахожусь в домашней сети
Match exec "nmcli -t -f ACTIVE,SSID dev wifi | grep '^yes:MyHomeWiFi'"
  IdentityFile ~/.ssh/id_ed25519_home

# Настройки для конкретного локального пользователя
Match User manager
  ForwardAgent yes

# Настройки при подключении к определенной подсети
Match Address 192.168.1.*
  StrictHostKeyChecking no
```

### Автоматическое дополнение имен (`CanonicalizeHostname`)

Позволяет обращаться к хостам по коротким именам (например, `ssh srv1` вместо `ssh srv1.prod.company.com`), автоматически подставляя домен.

```ssh
Host *
  CanonicalizeHostname yes
  CanonicalDomains prod.company.com dev.company.com
  CanonicalizeMaxDots 1
```

**Полный список директив канонизации:**
| Директива | Описание |
| :--- | :--- |
| `CanonicalizeHostname` | `yes` — всегда канонизировать, `no` — никогда, `always` — даже для IP-адресов |
| `CanonicalDomains` | Список суффиксов для канонизации (приоритет: первый совпавший) |
| `CanonicalizeMaxDots` | Максимальное количество точек в коротком имени, при котором применяется канонизация |
| `CanonicalizePermittedCNAMEs` | Разрешить канонизацию через CNAME для указанных доменов |

**Пример для сетей с разными доменами:**
```ssh
# В офисе: srv1 → srv1.corp.example.com
# В дата-центре: srv1 → srv1.dc.example.com
# Дома: полное имя не требуется
Match exec "hostname -d | grep -q '^corp\.example\.com$'"
  CanonicalDomains corp.example.com

Match exec "hostname -d | grep -q '^dc\.example\.com$'"
  CanonicalDomains dc.example.com
```

### `ProxyCommand` (legacy/сложные сценарии)

Используется для OpenSSH < 7.3 или когда нужно пропустить трафик через произвольную команду (например, `nc` или `tor`).

```ssh
Host internal-server
  ProxyCommand ssh bastion -W %h:%p
```

### Использование аппаратных ключей (FIDO2)

Для аппаратных токенов (YubiKey) с типом ключа `ed25519-sk`:

```ssh
Host secure-vault
  HostName vault.internal.com
  IdentityFile ~/.ssh/id_ed25519_sk
  # Принудительное требование подтверждения (касания)
  VerifyHostKeyDNS yes
```

### Полезные директивы (расширенный список)

| Директива | Назначение |
| :--- | :--- |
| `BatchMode yes` | Отключает интерактив (пароли, 2FA). При отсутствии ключа — ошибка, не зависание |
| `StrictHostKeyChecking` | `accept-new` (автодобавление новых, проверка старых), `yes` (строго), `no` (небезопасно) |
| `HashKnownHosts yes` | Хеширует IP/имена в `known_hosts` (защита от сканирования списка серверов) |
| `ConnectTimeout` | Таймаут установления соединения (в секундах) |
| `UserKnownHostsFile` | Путь к файлу известных хостов (можно `/dev/null` для CI/CD) |
| `IdentityAgent` | Указывает путь к сокету `ssh-agent` (например, для 1Password или GPG) |
| `TCPKeepAlive yes` | Проверка соединения на уровне TCP стека ОС |
| `LogLevel VERBOSE` | Повышенная детализация логов для диагностики (показывает отпечатки ключей) |
| `CheckHostIP no` | Отключает проверку IP в known_hosts (полезно при смене IP у того же домена) |
| `SessionType none` | Только туннель, без запуска удаленной оболочки (OpenSSH 9.0+) |
| `ExitOnForwardFailure yes` | Завершить SSH, если не удалось пробросить порт (критично для скриптов) |
| `StreamLocalBindUnlink yes` | Автоматически удалять старые Unix-сокеты перед созданием новых |
| `CertificateFile` | Путь к сертификату, подписанному SSH CA |
| `PubkeyAcceptedAlgorithms` | Явный список типов ключей, которые сервер примет (например, `ssh-ed25519,sk-ssh-ed25519@openssh.com`) |

### Keep-alive: клиент vs сервер

| Директива | Сторона | Расположение |
| :--- | :--- | :--- |
| `ServerAliveInterval` | Клиент | `~/.ssh/config` |
| `ClientAliveInterval` | Сервер | `/etc/ssh/sshd_config` |

Подробнее: [SSH Troubleshooting](./ssh_troubleshooting.md#сценарий-5-разрыв-соединения-при-бездействии).

## Troubleshooting и типичные ошибки клиентского конфига

### Ошибка: `Bad owner or permissions on ~/.ssh/config`

```bash
# Проверка
ls -la ~/.ssh/config
# → -rw------- 1 user user 1234 Sep 9 12:00 /home/user/.ssh/config

# Исправление
chmod 600 ~/.ssh/config
```

SSH требует, чтобы конфиг был доступен только владельцу. Любые другие права (`644`, `664`) приводят к отказу от чтения файла.

### Ошибка: `unix_listener: path too long`

Путь `ControlPath` превышает лимит ~108 символов. Решение:
```bash
# Проверить длину
echo -n ~/.ssh/sockets/%r@%h-%p | wc -c

# Исправить: использовать хэш
ControlPath ~/.ssh/S/%C
```

### Ошибка: `Too many authentication failures`

Сервер отклоняет соединение после `MaxAuthTries` попыток. Причины:
1. В `ssh-agent` загружено >6 ключей, и клиент пытается их все.
2. На хосте нет явного `IdentityFile`, поэтому клиент опрашивает все ключи агента.

Решение:
```bash
# Быстрое: указать ключ явно
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_prod user@host

# Постоянное: добавить в конфиг
Host problematic-host
  IdentityFile ~/.ssh/id_ed25519_prod
  IdentitiesOnly yes
```

### Ошибка: `Host key verification failed`

Ключ хоста изменился или отсутствует в `known_hosts`.

```bash
# Проверить fingerprint без подключения
ssh-keyscan -t ed25519 target-host | ssh-keygen -lf -

# Если изменение легитимно (переустановка ОС)
ssh-keygen -R target-host

# Для CI/CD: использовать accept-new
# В конфиге:
Host ci-targets
  StrictHostKeyChecking accept-new
  UserKnownHostsFile ~/.ssh/known_hosts_ci
```

### Ошибка: `Connection timed out` при использовании `ProxyJump`

Проверьте:
1. Доступен ли Jump Host напрямую: `ssh -v jumper@bastion`.
2. Порт на целевом хосте открыт: `ssh -J bastion -o ProxyCommand="nc -zv %h %p" user@target`.
3. На Jump Host запущен `sshd` и разрешен `AllowTcpForwarding yes` в `/etc/ssh/sshd_config`.

### Ошибка: `no matching key exchange method found`

Сервер поддерживает только устаревшие KEX-алгоритмы. Решение:
```bash
# Временно (для диагностики)
ssh -o "KexAlgorithms=diffie-hellman-group14-sha256" user@legacy-host

# Постоянно
Host legacy-host
  KexAlgorithms +diffie-hellman-group14-sha256
```

### Ошибка: `no matching cipher found`

Аналогично KEX: сервер не поддерживает современные шифры. Решение:
```bash
Host legacy-host
  Ciphers +aes256-cbc
```

## См. также

- [SSH Troubleshooting](./ssh_troubleshooting.md) — диагностика проблем с подключением, `ssh -G`, verbose-режим.
- [Практическое использование SSH и туннелирование](./ssh_usage_and_tunnels.md) — Port Forwarding, SOCKS5, systemd-туннели.
- [SSH Authentication](./server/ssh_authentication.md) — ключи, FIDO2, сертификаты CA, права доступа.
- [Инструменты сетевого мониторинга](../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика.
