# SSH — контроль доступа

## Определения

**SSH Access Control (Контроль доступа SSH)** — комплекс мер и конфигураций, ограничивающих возможность подключения к SSH-серверу на основе идентификации пользователя, его групповой принадлежности, IP-адреса источника или других параметров сессии.

**Whitelist (Белый список)** — стратегия безопасности, при которой доступ по умолчанию запрещен всем (Default Deny), кроме явно указанных субъектов (пользователей, групп или сетей).

**Match Blocks** — механизм условной конфигурации в `sshd_config`, позволяющий применять специфические параметры доступа только при выполнении определенных условий (например, для конкретного пользователя или подсети).

**`ForceCommand`** — директива, принудительно запускающая указанную команду при успешной аутентификации, игнорируя запрошенную клиентом команду или оболочку.

**`ChrootDirectory`** — директория, в которую изолируется сессия SFTP/SSH при использовании `ChrootDirectory`, ограничивая видимость файловой системы.

**`AuthenticationMethods`** — директива, определяющая комбинации методов аутентификации, необходимых для успешного входа (например, `publickey,keyboard-interactive` для MFA).

**`PermitTunnel`** — управляет разрешением на установление туннелей ` tun(4)` устройства (например, для VPN через SSH).

**`X11Forwarding`** — разрешает проброс X11-сессий с удаленного сервера на локальный рабочий стол.

**`TCP Wrappers`** — устаревший, но иногда используемый механизм фильтрации (`/etc/hosts.deny`/`/etc/hosts.allow`), который OpenSSH проверяет до обработки `sshd_config`.

## Основные концепции

### Директивы контроля доступа в sshd_config

Базовое ограничение реализуется через четыре основные директивы. Они обрабатываются в строго определенном порядке:

1.  `DenyUsers`
2.  `AllowUsers`
3.  `DenyGroups`
4.  `AllowGroups`

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| **`AllowUsers`** | Разрешает вход только указанным пользователям. Можно ограничить по хосту: `user@host`. | `AllowUsers admin deploy@10.0.0.5` |
| **`AllowGroups`** | Разрешает вход пользователям, являющимся членами указанных групп. | `AllowGroups ssh-admins` |
| **`DenyUsers`** | Явно запрещает вход указанным пользователям. | `DenyUsers guest root` |
| **`DenyGroups`** | Явно запрещает вход пользователям из указанных групп. | `DenyGroups banned-users` |

**Порядок обработки:**
1. Оценка глобальных директив (`AllowUsers`, `DenyUsers`, `AllowGroups`, `DenyGroups`) выполняется последовательно.
2. Если пользователь совпадает с `DenyUsers` — доступ запрещен, даже если он есть в `AllowUsers`.
3. При наличии `Match`-блока условия проверяются в порядке их объявления в файле. Первый подходящий блок применяется (`First Match Wins`), и его директивы переопределяют глобальные настройки **только для текущей сессии**.
4. Директивы внутри `Match`-блока применяются как **additive** (дополняют глобальные), если не переопределяют ту же самую опцию.
5. `Match` может применяться к нескольким критериям одновременно: `Match User alice Address 10.0.0.0/8`.

**Важные ограничения:**
- `AllowUsers`/`DenyUsers` не понимают паттерны CIDR для пользователей, только для хостов (`user@host`).
- Группы (`AllowGroups`/`DenyGroups`) проверяются через NSS ( `/etc/group`, LDAP, SSSD), поэтому латентность группы зависит от бэкенда.
- `Match` не поддерживает вложенность: нельзя определить `Match` внутри другого `Match`.
- Директивы, влияющие на привилегированное разделение (`ChrootDirectory`), требуют корректных прав доступа (владелец root, права 755 или stricter).

> **Рекомендация:** Используйте только `AllowUsers` или `AllowGroups`. Использование одновременно разрешающих и запрещающих списков усложняет аудит и может привести к логическим ошибкам. Для тонкой настройки предпочитайте `Match`-блоки, так как они не создают глобальных исключений.

### Условная конфигурация (Match Blocks)

Директива `Match` позволяет переопределять глобальные настройки для конкретных критериев. Это наиболее гибкий инструмент контроля доступа.

**Синтаксис:**
```ssh
Match [User|Group|Host|LocalAddress|LocalPort|Address] value
    Directive1 Value
    Directive2 Value
```

**Ключевые возможности:**
- Ограничение аутентификации (например, только по ключам для определенных IP).
- Принудительное выполнение команд (`ForceCommand`).
- Ограничение проброса портов (`AllowTcpForwarding no`).

### Ограничения в authorized_keys (Options)

Контроль доступа может быть точечным — на уровне конкретного публичного ключа. Опции указываются в начале строки перед типом ключа.

| Опция | Назначение |
| :--- | :--- |
| `from="pattern"` | Разрешает использование ключа только с указанных IP/хостов. |
| `command="cmd"` | Принудительно запускает указанную команду вместо шелла (ForceCommand). |
| `no-port-forwarding` | Запрещает проброс TCP-портов для этой сессии. |
| `no-pty` | Запрещает выделение терминала (полезно для автоматизации/туннелей). |

### Сетевой контроль (L3-L4)

Фильтрация на уровне файрвола (iptables, nftables, ufw) является первым эшелоном защиты, отсекая нежелательный трафик до того, как он попадет на обработку демону `sshd`.

## Практические сценарии

### Сценарий 1: Групповой контроль доступа (Whitelist)

**Задача:** Разрешить доступ только членам группы `ssh-users`, запретив всем остальным (включая root).

```bash
# 1. Создание группы
sudo groupadd ssh-users

# 2. Добавление легитимных пользователей
sudo usermod -aG ssh-users myuser

# 3. Настройка /etc/ssh/sshd_config
# Убедитесь, что PermitRootLogin установлен в no для максимальной безопасности
sudo sed -i 's/^#PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
echo "AllowGroups ssh-users" | sudo tee -a /etc/ssh/sshd_config

# 4. Проверка конфига и перезапуск
sudo sshd -t && sudo systemctl restart sshd
```

### Сценарий 2: Ограничение по IP через файрвол

**Задача:** Разрешить SSH только из локальной сети администратора.

**С использованием iptables:**
```bash
# Разрешить локальную сеть, дропнуть остальное
sudo iptables -A INPUT -p tcp -s 192.168.1.0/24 --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 22 -j DROP
```

**С использованием nftables (рекомендуется):**
```bash
# Добавление правила в существующую таблицу inet filter
nft add rule inet filter input ip saddr 192.168.1.0/24 tcp dport 22 accept
nft add rule inet filter input tcp dport 22 counter reject
```

### Сценарий 3: Использование Match Blocks для администраторов

**Задача:** Для пользователей группы `admins` разрешить вход только с определенного IP и требовать только SSH-ключи, даже если глобально разрешены пароли.

```ssh
# Глобальные настройки (в конце файла)
Match Group admins
    Address 203.0.113.10
    PasswordAuthentication no
    AuthenticationMethods publickey
```

### Сценарий 4: Ограничение доступа к конкретной команде (Backup)

**Задача:** Создать пользователя для бэкапов, который может выполнять только `rsync` и только с IP бэкап-сервера.

**Запись в `~/.ssh/authorized_keys` пользователя backup:**
```text
from="10.0.5.10",command="rsync --server --daemon .",no-pty,no-port-forwarding ssh-ed25519 AAAAC3Nza... backup-key
```

### Сценарий 5: Смена порта и SELinux

**Задача:** Перенести SSH на порт 2239 в системе с включенным SELinux (RHEL/CentOS/Fedora).

```bash
# 1. Добавление порта в политику SELinux
sudo semanage port -a -t ssh_port_t -p tcp 2239

# 2. Открытие порта в firewalld
sudo firewall-cmd --permanent --add-port=2239/tcp
sudo firewall-cmd --reload

# 3. Изменение Port в /etc/ssh/sshd_config
# 4. Перезапуск sshd
sudo systemctl restart sshd
```

### Сценарий 6: ForceCommand для CI/CD-деплоя

**Задача:** Разрешить пользователю `deploy` выполнять только команду развертывания приложения, но только с IP-адреса CI/CD-раннера.

**Конфигурация в `/etc/ssh/sshd_config`:**
```ssh
Match User deploy Address 192.168.10.0/24
    ForceCommand /usr/local/bin/deploy-wrapper.sh
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
```

**Пример `deploy-wrapper.sh`:**
```bash
#!/bin/bash
# Логируем источник и команду
echo "$(date '+%Y-%m-%d %H:%M:%S') deploy from $SSH_CONNECTION" >> /var/log/ssh-deploy.log

# Разрешаем только конкретную команду
if [[ "$SSH_ORIGINAL_COMMAND" == "deploy --env=prod" ]]; then
    exec /usr/local/bin/app-deploy.sh "$@"
else
    echo "Доступ запрещен. Разрешена только команда: deploy --env=prod"
    exit 1
fi
```

```bash
# Настройка прав
sudo chmod 700 /usr/local/bin/deploy-wrapper.sh
sudo chown root:root /usr/local/bin/deploy-wrapper.sh
sudo systemctl restart sshd
```

### Сценарий 7: SFTP-only chroot jail

**Задача:** Создать изолированную среду для пользователя `uploader`, разрешив только SFTP без оболочки и доступа к остальной файловой системе.

```bash
# 1. Создание группы и пользователя без оболочки
sudo groupadd sftpusers
sudo useradd -m -d /sftp/uploader -s /usr/sbin/nologin -g sftpusers uploader

# 2. Создание структуры chroot (обязательно владелец root, права 755)
sudo mkdir -p /sftp/uploader/{incoming,outgoing}
sudo chown root:root /sftp/uploader
sudo chmod 755 /sftp/uploader
sudo chown uploader:sftpusers /sftp/uploader/{incoming,outgoing}
sudo chmod 700 /sftp/uploader/{incoming,outgoing}

# 3. Настройка sshd_config
sudo tee -a /etc/ssh/sshd_config << 'EOF'

Subsystem sftp internal-sftp

Match Group sftpusers
    ChrootDirectory /sftp/%u
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no
    PasswordAuthentication no
    PubkeyAuthentication yes
EOF

# 4. Перезапуск и валидация
sudo sshd -t && sudo systemctl restart sshd
```

> **Важно:** `ChrootDirectory` требует, чтобы целевая директория и все её родительские компоненты принадлежали root и не были доступны для записи группе/остальным.

### Сценарий 8: Многофакторная аутентификация (2FA) через PAM

**Задача:** Для группы `admins` требовать одновременно SSH-ключ и временный пароль (Google Authenticator / TOTP).

```bash
# 1. Установка libpam-google-authenticator
sudo apt install libpam-google-authenticator  # Debian/Ubuntu
# sudo dnf install google-authenticator        # RHEL/Fedora

# 2. Настройка PAM
sudo tee -a /etc/pam.d/sshd << 'EOF'
# В конец файла
auth required pam_google_authenticator.so nullok
EOF

# 3. Настройка sshd_config
sudo tee -a /etc/ssh/sshd_config << 'EOF'

# Глобально разрешаем оба метода, но требовать оба для admins
KbdInteractiveAuthentication yes
UsePAM yes

Match Group admins
    AuthenticationMethods publickey,keyboard-interactive
EOF

# 4. Генерация секрета для каждого пользователя-администратора
sudo -u alice google-authenticator -t -d -f -r 3 -R 30 -w 3
```

```bash
# Валидация: подключение запросит ключ, затем код из приложения
# Если неверный код или нет ключа — вход отклонен
sudo systemctl restart sshd
```

### Сценарий 9: Бэкап и откат конфигурации

**Задача:** Создать резервную копию `sshd_config` перед изменениями и иметь возможность быстрого отката.

```bash
# 1. Бэкап с датой и метаданными
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%F_%H%M%S)
sudo md5sum /etc/ssh/sshd_config.bak.* > /root/sshd_config_hashes.txt

# 2. Проверка перед применением (обязательно)
sudo sshd -t
# → (нет вывода = успех)

# 3. Откат при ошибке
sudo cp /etc/ssh/sshd_config.bak.2026-09-09_103000 /etc/ssh/sshd_config
sudo systemctl restart sshd

# 4. Если доступ потерян (резервный сеанс через IPMI/iDRAC/console):
# systemctl revert sshd
# или восстановите конфиг через rescue-режим
```

> **Рекомендация:** Никогда не закрывайте текущую SSH-сессию до подтверждения работоспособности новой конфигурации в новом сеансе.

## Дополнительная информация

### Сравнение уровней контроля доступа

| Механизм | Уровень | Гибкость | Рекомендуемое применение |
| :--- | :--- | :--- | :--- |
| **Файрвол (nftables)** | Сетевой (L3) | Низкая | Первичная фильтрация по IP/сетям. |
| **AllowUsers/Groups** | Прикладной (L7) | Средняя | Базовое разделение прав пользователей. |
| **Match Blocks** | Прикладной (L7) | Высокая | Сложные условные политики, исключения. |
| **authorized_keys** | Прикладной (L7) | Максимальная | Делегирование прав для автоматизации (CI/CD). |

### Диагностика эффективной конфигурации

Поскольку `sshd_config` может содержать множество директив и блоков `Match`, важно проверять, какие настройки применяются в реальности для конкретного пользователя и сессии.

```bash
# Просмотр итоговой конфигурации для текущего пользователя (все Include и Match уже раскрыты)
sudo sshd -T

# Проверка для конкретного пользователя с определенного IP (симуляция)
sudo sshd -T -C "user=deploy,addr=192.168.1.5" | grep -E "allowusers|denyusers|allowgroups|denygroups|permitroot|passwordauth|authenticationmethods|forcecommand|x11forwarding|allowtcpforwarding|chrootdirectory|permittunnel"

# Поиск активных Match-блоков, влияющих на пользователя
sudo sshd -T | grep -i "^match "

# Проверка логов sshd на предмет причин отклонения подключения
sudo journalctl -u sshd --since "10 minutes ago" | grep -E "Failed|refused|match|denied|invalid user"

# Проверка эффективных параметров аутентификации для текущего пользователя
sudo sshd -T | grep -E "pubkeyauthentication|passwordauthentication|kbdinteractiveauthentication|maxauthtries|loglevel"

# Верификация прав на authorized_keys (частая причина отказа по ключу)
namei -mo ~/.ssh/authorized_keys
# → ожидается: drwx------ . ssh/ authorized_keys (600)
```

### Типичные ошибки и решения

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Bad owner or permissions on /home/user/.ssh/authorized_keys` | Права открыты (например, 644) или владелец root | `chown user:user ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys` |
| `Could not chdir to home directory` | SELinux-контекст некорректен или домашняя директория недоступна | `restorecon -Rv /home/user` (SELinux) или проверить права на `/home/user` |
| `Connection closed by authenticating user` | `AuthenticationMethods` не совпадает с доступными методами | Проверить `sshd -T -C` и конфигурацию PAM |
| `Received disconnect from ...: 11: Bye Bye [preauth]` | `ForceCommand` возвращает не-0 или ключ отклонен `authorized_keys` | Проверить журналы и синтаксис `authorized_keys` |
| `Match` не применяется | Ошибка в синтаксисе или блок переопределяется последующим `Match` | `sshd -t` не найдет синтаксис, но логика приоритета проверяется через `sshd -T` |
| `ChrootDirectory` не работает | Директория не принадлежит root или имеет права > 755 | Установить `chown root:root` и `chmod 755` на `ChrootDirectory` |
| `UNREACHABLE! Permission denied (publickey)` в Ansible | `PermitRootLogin no` и подключение идет от root | Указать `ansible_user=deploy` в инвентаре или добавить ключ для root |
| `AuthorizedKeysFile` указывает на неверный путь | Переопределен глобально или в `Match`-блоке | `sshd -T \| grep authorizedkeysfile` |

### Лучшие практики

1.  **Принцип наименьших привилегий:** По умолчанию используйте `PermitRootLogin no`.
2.  **Многофакторная аутентификация (MFA):** Для критических групп (`admins`, `deploy`) примените `AuthenticationMethods publickey,keyboard-interactive`. Используйте аппаратные ключи (FIDO2) где возможно.
3.  **Используйте `sshd -T` как часть CI/CD-пайплайна:** Автоматически проверяйте наличие запрещенных директив (`PermitRootLogin yes`, `PasswordAuthentication yes`) на всех managed-хостах.
4.  **Изоляция через `ChrootDirectory`:** Для SFTP и ограниченных команд всегда применяйте chroot, чтобы предотвратить escape из песочницы.
5.  **Аудит `authorized_keys`:** Ведите инвентаризацию ключей. Для автоматизации используйте `command="..."` с явным путем и `no-pty,no-port-forwarding,no-X11-forwarding`.
6.  **Ротация ключей и сессий:** Устанавливайте `ClientAliveInterval` и `ClientAliveCountMax` для отключения зависших сессий. Используйте `MaxAuthTries 3` для ограничения перебора.
7.  **Логирование:** Установите `LogLevel VERBOSE` для логирования ключей отладки при аутентификации (полезно для расследований инцидентов).
8.  **Не полагайтесь только на смену порта:** Security through obscurity не защищает от сканеров с поддержкой полного sweep портов. Сочетайте с файрволом и Fail2ban.
9.  **Резервное копирование:** Всегда делайте snapshot конфигурации перед изменениями и тестируйте откат.
10. **Приоритет и порядок:** Помните, что `Match` работает по принципу `First Match Wins`. Не размещайте более общие `Match`-блоки перед специфичными.

### Крайние случаи и ограничения

| Случай | Поведение / Риск | Рекомендация |
| :--- | :--- | :--- |
| **Пользователь одновременно в `AllowUsers` и `DenyUsers`** | Срабатывает `DenyUsers` первым (порядок обработки). | Избегайте пересекающихся списков. Используйте `Match` для исключений. |
| **Nested `Match`** | Не поддерживается. OpenSSH игнорирует вложенные блоки или завершает ошибкой. | Используйте один `Match` с несколькими критериями: `Match User alice Address 10.0.0.0/8`. |
| **ChrootDirectory с NFS / CIFS** | Монтирование сети внутрь chroot ненадежно и может приводить к deadlock при подключении. | Используйте только локальные файловые системы для `ChrootDirectory`. |
| **ForceCommand с TTY-зависимыми скриптами** | Если скрипт требует TTY, а `no-pty` установлен — выполнение завершится ошибкой. | Либо уберите `no-pty`, либо модифицируйте скрипт для работы без TTY (expect, non-interactive mode). |
| **SSH CA vs authorized_keys** | При использовании `TrustedUserCAKeys` пользователь не должен быть в `authorized_keys` лично, но контролировать индивидуальный доступ сложнее. | Для корпоративных сред используйте SSH CA с ограничениями на уровне principals. Для тонкого контроля комбинируйте CA с `authorized_keys`. |
| **Изменение конфигурации без потери доступа** | При ошибке синтаксиса `sshd -t` не предотвратит `systemctl restart sshd` если service manager продолжит старый процесс. | Используйте `sshd -t && systemctl reload sshd` (reload мягче restart). Для тестирования `sshd -T` безопаснее, чем reload. |
| **SELinux / AppArmor** | Даже корректный `sshd_config` не сработает, если политика MAC блокирует доступ к файлам или сетевым портам. | Проверяйте `ausearch -m avc -ts recent` (SELinux) или `journalctl -u sshd` (AppArmor) при таинственных отказах. |
| **TCP Wrappers с systemd** | На современных дистрибутивах OpenSSH может быть собран без поддержки libwrap. | Проверьте `ldd $(which sshd) \| grep wrap`. Если нет — используйте файрвол вместо TCP Wrappers. |

### См. также

- [SSH Server Security Overview](./ssh_server_security_overview.md) — общая стратегия защиты.
- [SSH Hardening Best Practices](./ssh_hardening_best_practices.md) — комплексные меры укрепления.
- [SSH Authentication](./ssh_authentication.md) — методы аутентификации, ключи, FIDO2, права доступа.
- [Port Knocking](./port_knocking.md) — технология скрытия порта до прохождения аутентификации.
- [Инструменты сетевого мониторинга](../../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика
- [Fail2Ban](../../Tools/fail2ban.md) — автоматическая блокировка атакующих.
- [PAM: обзор и настройка](../../pam_overview.md) — глубокая интеграция контроля доступа через PAM.
- [nftables threat modeling](../../../Networking/Settings/tools/nftables/threat_modeling.md) — сетевая фильтрация как первый эшелон защиты.
