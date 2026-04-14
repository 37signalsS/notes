# SSH Authentication

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

## Definitions

**SSH-аутентификация** — процесс подтверждения личности пользователя при подключении к SSH-серверу. Основные методы: по ключам (pubkey), по паролю (password), через Kerberos/GSSAPI, challenge-response.

**Пара ключей (Key Pair)** — два криптографических ключа:

- **Приватный ключ (Private Key)** — секретный файл на клиенте, не передаётся по сети.
- **Публичный ключ (Public Key)** — открытый файл, размещается на сервере в `~/.ssh/authorized_keys`.

**Аутентификация по SSH-ключам** — метод, при котором сервер проверяет соответствие приватного ключа клиента публичному ключу на сервере через криптографический handshake.

## Basic Concepts

### Методы аутентификации

| Метод | Описание | Безопасность |
| :--- | :--- | :--- |
| **PubkeyAuthentication** | По паре ключей (ed25519, RSA, ECDSA) | Высокая (рекомендуется) |
| **PasswordAuthentication** | По паролю пользователя | Средняя (уязвимо к brute-force) |
| **Kerberos/GSSAPI** | Через централизованную систему SSO | Зависит от инфраструктуры |
| **ChallengeResponseAuthentication** | Интерактивный метод (TOTP, PAM) | Зависит от backend |

### Типы SSH-ключей

| Тип | Длина | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **ED25519** | Фиксированная (256 бит) | Высокая производительность, компактный размер | OpenSSH 6.5+ |
| **RSA** | 4096 бит (мин. 2048) | Максимальная совместимость | Медленнее, крупные ключи |
| **ECDSA** | 256–521 бит | Компактный, быстрый | Зависимость от NIST-кривых |

**Рекомендация:** Использовать `ed25519` как современный стандарт. `RSA 4096` — для обратной совместимости.

### Файл `~/.ssh/authorized_keys`

Хранит публичные ключи, авторизованные для доступа к учётной записи. Каждый ключ — отдельная строка.

**Формат:**

```
<тип_ключа> <базовый_ключ> <комментарий>
```

**Пример:**

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... user@example.com
```

**Опции перед ключом** (ограничивают доступ):

```
command="backup.sh",from="192.168.1.0/24" ssh-ed25519 AAAA... user@host
```

### Контроль прав доступа

Неправильные права приводят к отказу в аутентификации. `sshd` отклоняет ключи при нарушенных разрешениях.

| Путь | Права | Владелец | Описание |
| :--- | :--- | :--- | :--- |
| `~/.ssh/` | `700` | Пользователь | Каталог ключей и конфигов |
| `~/.ssh/authorized_keys` | `600` | Пользователь | Авторизованные публичные ключи |
| `~/.ssh/id_*` (приватные) | `600` | Пользователь | Секретные ключи клиента |
| `~/.ssh/id_*.pub` | `644` | Пользователь | Публичные ключи клиента |
| `~/.ssh/config` | `600` | Пользователь | Клиентский конфиг |
| `/etc/ssh/ssh_host_*_key` | `600` | `root:root` | Приватные ключи хоста |
| `/etc/ssh/ssh_host_*_key.pub` | `644` | `root:root` | Публичные ключи хоста |

**Ошибка при нарушении прав:**

```
Authentication refused: bad ownership or modes for directory /home/user/.ssh
```

## Practical Scenarios

### Сценарий 1: Генерация и установка SSH-ключа

**Задача:** Создать пару ключей ed25519 и добавить на сервер.

```bash
# 1. Генерация ключа
ssh-keygen -t ed25519 -C "user@workstation" -f ~/.ssh/id_ed25519_work

# 2. Копирование публичного ключа на сервер
ssh-copy-id -i ~/.ssh/id_ed25519_work.pub user@server

# 3. Ручной вариант (если ssh-copy-id недоступен)
cat ~/.ssh/id_ed25519_work.pub | ssh user@server "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

### Сценарий 2: Отключение аутентификации по паролю

**Задача:** Перевести сервер на аутентификацию только по ключам.

```bash
# 1. Убедиться, что ключи установлены
ssh-copy-id user@server

# 2. Проверить подключение по ключу
ssh user@server

# 3. Отключить парольную аутентификацию (/etc/ssh/sshd_config)
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config

# 4. Перезапустить SSH
sudo systemctl restart sshd
```

### Сценарий 3: Генерация ключа с кодовой фразой

**Задача:** Создать ключ с passphrase для повышенной безопасности.

```bash
# Генерация с passphrase
ssh-keygen -t ed25519 -C "secure-key" -f ~/.ssh/id_ed25519_secure

# Добавление ключа в SSH-агент (чтобы не вводить passphrase каждый раз)
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_secure
```

### Сценарий 4: Отзыв доступа (удаление ключа)

**Задача:** Удалить скомпрометированный ключ с сервера.

```bash
# 1. Удалить ключ из authorized_keys
ssh user@server "sed -i '/compromised-key-comment/d' ~/.ssh/authorized_keys"

# 2. Удалить ключ с клиента
rm ~/.ssh/id_ed25519_compromised ~/.ssh/id_ed25519_compromised.pub
```

## Additional Information

### Связь с директивами sshd_config

Ключевые директивы аутентификации в `/etc/ssh/sshd_config`:

| Директива | Значение | Описание |
| :--- | :--- | :--- |
| `PubkeyAuthentication yes` | Включить | Разрешить вход по ключам |
| `PasswordAuthentication no` | Выключить | Запретить вход по паролю |
| `PermitRootLogin no` | Запретить | Запретить вход root (рекомендуется) |
| `MaxAuthTries 3` | Ограничить | Снизить риск brute-force |
| `PermitEmptyPasswords no` | Запретить | Запретить пустые пароли |
| `AuthenticationMethods publickey` | Строгий | Требовать только pubkey |

Подробности — в [SSH Hardening Best Practices](./ssh_hardening_best_practices.md).

### Диагностика проблем аутентификации

1. **Проверить логи сервера:** `journalctl -u sshd --since "5 min ago"`
2. **Проверить права:** `ls -la ~/.ssh/` и `ls -la ~/.ssh/authorized_keys`
3. **Проверить конфиг:** `sudo sshd -T | grep -i auth`
4. **Запустить клиент с отладкой:** `ssh -vvv user@server`
5. **Проверить known_hosts:** `ssh-keygen -F hostname`

### Связанные темы

- [SSH Access Control](./ssh_access_control.md) — управление доступом (AllowUsers, AllowGroups)
- [SSH Hardening Best Practices](./ssh_hardening_best_practices.md) — укрепление безопасности
- [SSH Client Config](../ssh_client_config.md) — настройка клиента и SSH-агент
- [SSH Troubleshooting](../ssh_troubleshooting.md) — диагностика проблем
