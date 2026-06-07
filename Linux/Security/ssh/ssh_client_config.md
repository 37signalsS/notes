# Конфигурация клиента SSH (`~/.ssh/config`)

## Определения

**`~/.ssh/config`** — конфигурационный файл SSH-клиента для определения псевдонимов хостов и индивидуальных параметров подключения (пользователь, порт, ключ, сжатие). Упрощает и автоматизирует подключение к часто используемым серверам.

**Jump Host (ProxyJump)** — промежуточный защищённый сервер как единая точка входа во внутреннюю сеть. Клиент подключается к Jump Host, который создаёт прозрачный TCP-туннель до целевого сервера.

**SSH Multiplexing** — повторное использование одного TCP-соединения для нескольких SSH-сессий (включая `scp`, `sftp`, `git`). Пропускает этапы TCP-handshake и SSH-аутентификации для последующих подключений.

Инструменты передачи файлов (`scp`, `sftp`, `rsync`): [Инструменты командной строки SSH](./ssh_cli_tools.md).

## Базовые концепции

### Структура файла `~/.ssh/config`

Файл состоит из блоков `Host`, каждый задаёт параметры для конкретного псевдонима или группы хостов.

| Директива | Описание |
| :--- | :--- |
| `Host <alias>` | Начало блока настроек для псевдонима |
| `Host *` | Глобальные настройки для всех хостов |
| `HostName` | Реальное имя хоста или IP-адрес |
| `User` | Имя пользователя для входа |
| `Port` | Порт SSH на сервере |
| `IdentityFile` | Путь к приватному ключу |
| `Compression` | Включает сжатие (`yes`/`no`) |
| `ForwardX11` | Перенаправление X11 (`yes`/`no`) |
| `ServerAliveInterval` | Интервал keep-alive сообщений (секунды) |
| `BatchMode` | Отключение интерактивных запросов (`yes`/`no`) |
| `LogLevel` | Уровень логирования клиента (`INFO`, `DEBUG`, `VERBOSE`) |
| `PreferredAuthentications` | Порядок методов аутентификации |

### Принцип работы Jump Host

При использовании `ProxyJump` SSH-клиент устанавливает соединение с Jump Host, затем запрашивает создание TCP-туннеля до целевого сервера. Весь трафик инкапсулируется в туннель.

### Принцип работы мультиплексирования

Первая сессия создаёт «мастер-канал» и управляющий сокет (unix-файл). Последующие сессии подключаются к сокету, получая доступ к уже установленному соединению без повторной аутентификации.

## Практические сценарии

Права доступа: `~/.ssh/config` — `600`. Подробнее: [SSH Authentication](./server/ssh_authentication.md#контроль-прав-доступа).

### Базовая конфигурация

```ini
# Псевдоним для рабочего сервера
Host work
  HostName spb-mx-i3.extrt.int.company.net
  User ivanov_i
  Port 2222
  IdentityFile ~/.ssh/id_work
  Compression yes

# Домашний сервер
Host home
  HostName myhome.dyndns.org
  User vasya
  PasswordAuthentication no
  IdentityFile ~/.ssh/id_rsa_home

# Настройки по умолчанию для всех хостов
Host *
  User root
  PreferredAuthentications publickey,password
  ForwardX11 no
  ServerAliveInterval 60
  Compression yes
  BatchMode yes
  VisualHostKey yes
  # LogLevel INFO
```

Подключение: `ssh work`.

### Настройка подключения через Jump Host (`ProxyJump`)

**Через командную строку (`-J`):**

```bash
ssh -J ilya@miminet.ru ilya@10.130.0.28
```

**Через `~/.ssh/config` (для частого использования):**

```ini
Host bastion
  HostName 203.0.113.10
  User admin
  IdentityFile ~/.ssh/private_key.txt

Host internal-server
  HostName 192.168.1.100
  User app_user
  ProxyJump bastion
  IdentityFile ~/.ssh/private_key.txt
```

Подключение: `ssh internal-server`.

Конфигурация работает одинаково на Linux, macOS и Windows (OpenSSH для Windows).

### Настройка SSH Multiplexing

1. Создать директорию для сокетов:

```bash
mkdir -p ~/.ssh/sockets
chmod 700 ~/.ssh/sockets
```

1. Добавить в `~/.ssh/config` (блок `Host *`):

```ini
Host *
  ControlMaster auto
  ControlPath ~/.ssh/sockets/%r@%h-%p
  ControlPersist 10m
```

Управление мастер-каналами (флаг `-O`):

```bash
# Проверить статус
ssh -O check my_alias

# Принудительно закрыть
ssh -O exit my_alias
```

### Управление ключами с помощью `ssh-agent`

`ssh-agent` — фоновая программа, кэширующая приватные SSH-ключи в памяти. Избавляет от повторного ввода passphrase.

```bash
# Запуск агента
eval "$(ssh-agent -s)"

# Добавление ключа
ssh-add ~/.ssh/id_ed25519

# Просмотр добавленных ключей
ssh-add -l

# Удаление конкретного ключа
ssh-add -d ~/.ssh/id_myproject

# Удаление всех ключей
ssh-add -D

# Остановка агента
ssh-agent -k
```

В большинстве современных DE (GNOME, KDE) и macOS `ssh-agent` запускается автоматически.

## Дополнительная информация

### `ProxyCommand` (устаревший способ для Jump Host)

Для OpenSSH < 7.3 или сложных сценариев:

```ini
Host internal-server
  HostName 192.168.1.100
  User app_user
  ProxyCommand ssh bastion -W %h:%p
```

`ssh bastion -W %h:%p` создаёт тот же туннель, что и `ProxyJump`.

### Полезные директивы

| Директива | Назначение |
| :--- | :--- |
| `BatchMode yes` | Отключает интерактивные запросы (пароли, подтверждение хостов). Для скриптов и автоматизации — соединение завершится с ошибкой вместо «зависания» |
| `LogLevel INFO` | Уровень логирования клиента для отладки |
| `PreferredAuthentications publickey,password` | Порядок методов аутентификации |
| `VisualHostKey yes` | Отображение ASCII-art отпечатка хоста при подключении (визуальное обнаружение MITM) |
| `ServerAliveInterval 60` | Keep-alive сообщения каждые 60 секунд для предотвращения разрыва |

### Keep-alive: клиент vs сервер

| Директива | Сторона | Расположение |
| :--- | :--- | :--- |
| `ServerAliveInterval` | Клиент | `~/.ssh/config` |
| `ClientAliveInterval` | Сервер | `/etc/ssh/sshd_config` |
| `TCPKeepAlive` | Сервер (TCP-уровень) | `/etc/ssh/sshd_config` |

Подробнее: [SSH Troubleshooting](./ssh_troubleshooting.md#сценарий-5-разрыв-соединения-при-бездействии).
