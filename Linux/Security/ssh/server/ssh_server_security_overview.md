# SSH — обзор безопасности сервера

## Определения

**Безопасность SSH-сервера** — комплекс стратегических и технических мер, направленных на защиту демона `sshd` от несанкционированного доступа, эксплуатации уязвимостей и атак типа «отказ в обслуживании». Поскольку SSH является основным инструментом удаленного администрирования, его защита является критическим приоритетом для обеспечения целостности всей системы.

**Defense in Depth (Эшелонированная защита)** — архитектурный принцип безопасности, предполагающий использование нескольких независимых уровней защиты. В контексте SSH это означает, что даже при компрометации одного механизма (например, краже пароля), другие уровни (например, MFA или ограничение по IP) предотвратят несанкционированный вход.

**Привилегированное разделение (Privilege Separation)** — архитектурный механизм OpenSSH, при котором родительский процесс `sshd` работает от `root` только для привязки порта и аутентификации, после чего дочерний процесс понижает привилегии до непривилегированного пользователя (`nobody` или выделенный `ssh-uid`). Это ограничивает ущерб при компрометации памяти демона (например, CVE-2024-6387).

**SSH CA (Certificate Authority)** — инфраструктура открытых ключей для SSH, где центральный сертификат подписывает сертификаты пользователей, исключая необходимость управления отдельными ключами на каждом сервере.

## Основные концепции

### Уровни защиты SSH-сервера

Комплексная защита строится на четырех функциональных эшелонах:

1.  **Аутентификация (Кто вы?):** Проверка подлинности субъекта. Основной акцент делается на отказе от паролей в пользу [SSH-ключей (pubkey)](./ssh_authentication.md) и использовании аппаратных токенов (FIDO2).
2.  **Контроль доступа (Куда вам можно?):** Ограничение прав авторизованных пользователей и фильтрация сетевых источников. Реализуется через [белые списки](./ssh_access_control.md) и правила файрвола.
3.  **Закалка конфигурации (Hardening):** Минимизация поверхности атаки через отключение небезопасных функций и ограничение криптографических алгоритмов современными стандартами (включая постквантовую защиту). Подробнее: [SSH Hardening Best Practices](./ssh_hardening_best_practices.md).
4.  **Мониторинг и аудит (Что происходит?):** Непрерывный анализ журналов, обнаружение аномалий и автоматическое реагирование на атаки перебором. Подробнее: [SSH Monitoring and Troubleshooting](./ssh_monitoring_and_troubleshooting.md).

### Архитектура демона sshd

Понимание модели процессов критично для диагностики и hardening:

```
systemd
  └── sshd.service (master, root)
        ├── sshd: priv (дочерний, root) — аутентификация, создание сессии
        ├── sshd: user [priv] (down-привилегированный, ssh-uid/nobody) — обслуживание сессии
        └── sshd: user@pts/0 (непривилегированный) — выполнение команды/шелла
```

**Жизненный цикл сессии:**
1.  Master-процесс принимает TCP-соединение на порту.
2.  Рождается дочерний процесс `priv` для выполнения обмена ключами (KEX) и аутентификации.
3.  После успешной аутентификации создается сессионный процесс с пониженными привилегиями.
4.  При отключении клиента все дочерние процессы завершаются.

**Важность для SRE:** При утечках памяти или эксплуатации уязвимостей в протоколе (regreSSHion) компрометации подвергается только сессионный процесс с ограниченными правами, а не master-процесс.

### Модель угроз SSH

| Угроза | Описание | Основной метод защиты |
| :--- | :--- | :--- |
| **Brute-force** | Автоматизированный перебор паролей и имен пользователей. | Отключение паролей, [fail2ban](../../Tools/fail2ban.md) |
| **MITM (Man-in-the-Middle)** | Перехват трафика с попыткой подмены ключа сервера. | Проверка Host Key (Fingerprints), аудит `known_hosts`. |
| **Компрометация ключа** | Кража или потеря приватного ключа пользователя. | Использование Passphrase, аппаратные токены (SK-ключи). |
| **Слабые алгоритмы** | Дешифрация трафика из-за использования устаревшего KEX/Ciphers. | [Hardening алгоритмов](./ssh_hardening_best_practices.md) (отказ от SHA-1, RSA < 3072). |
| **Сканирование портов** | Разведка инфраструктуры ботами. | Смена порта, [Port Knocking](./port_knocking.md). |
| **regreSSHion (CVE-2024-6387)** | Heap-based overflow в сигнальной обработке при аутентификации по паролю. RCE с привилегиями root. | Обновление OpenSSH, отключение паролей, привилегированное разделение. |
| **SSH Agent кража** | Компрометация промежуточного хоста с проброшенным агентом. | Отказ от `ForwardAgent`, использование `ProxyJump`. |
| **Аномалия сессий (Account Takeover)** | Повышение привилегий через уязвимости в оболочке или sudo. | `ForceCommand`, `restrict` в authorized_keys, auditd. |

### Тренды безопасности 2026 года

- **Zero Trust:** Переход от концепции «доверенной сети» к проверке каждого соединения независимо от источника.
- **Post-Quantum Cryptography (PQC):** Внедрение гибридных алгоритмов обмена ключами (X25519 + ML-KEM) для защиты от будущих квантовых угроз.
- **Passwordless:** Полный отказ от паролей в пользу SSH CA или аппаратных ключей FIDO2.
- **Hardware-Bound Keys:** Стандартизация использования аппаратных токенов (YubiKey, Touch ID) для всех privileged-аккаунтов.
- **Automated Compliance:** Интеграция SSH-аудита в CI/CD пайплайны через OpenSCAP и ssh-audit с автоматическим gate-контролем.

## Предварительные требования

### Аппаратные и программные требования

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **ОС** | Linux с systemd (RHEL 8+, Debian 11+, Ubuntu 22.04+) | Актуальная LTS-версия с исправлениями безопасности |
| **OpenSSH** | 8.8p1 | 9.8p1+ (поддержка ML-KEM, ED25519-SK, privilege separation sandbox) |
| **Ядро** | 5.4+ | 6.1+ (полная поддержка seccomp, Landlock, LSM) |
| **Память** | 512 MB | 2 GB+ (при нагрузке >1000 одновременных сессий) |
| **Хранилище** | 1 GB свободного места | SSD (для журналов auditd и высокой производительности) |

### Инициализация окружения

```bash
# 1. Проверка версии OpenSSH
ssh -V
# → OpenSSH_9.8p1, OpenSSL_3.0.2 ...

# 2. Установка необходимых пакетов
# Debian/Ubuntu:
sudo apt update && sudo apt install -y openssh-server auditd fail2ban ssh-audit

# RHEL/CentOS/Fedora:
sudo dnf install -y openssh-server audit fail2ban ssh-audit

# 3. Создание директории для кастомных конфигураций
sudo mkdir -p /etc/ssh/sshd_config.d
sudo chmod 755 /etc/ssh/sshd_config.d

# 4. Создание резервной копии заводского конфига
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.orig
sudo chmod 600 /etc/ssh/sshd_config.orig
```

### Проверка исходного состояния

```bash
# Проверка, что служба активна
sudo systemctl is-active sshd
# → active

# Проверка прослушиваемых портов
sudo ss -tnlp | grep sshd
# → LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1234,fd=3))

# Проверка эффективной конфигурации (базовая)
sudo sshd -T | grep -E "port|permitrootlogin|passwordauthentication|pubkeyauthentication"
```

## Практические сценарии

### Сценарий 1: Комплексный аудит безопасности (Self-Audit)

Оперативный чеклист для оценки состояния защиты сервера с валидацией результатов:

```bash
# 1. Проверка эффективных настроек аутентификации
# Ищет включенные пароли, вход root и уровень логирования
sudo sshd -T | grep -E "pubkeyauth|passwordauth|permitroot|loglevel"

# Ожидаемый результат:
# pubkeyauthentication yes
# passwordauthentication no
# permitrootlogin no
# loglevel VERBOSE

# 2. Поиск примененных ограничений доступа
# Проверяет AllowUsers, AllowGroups и наличие Match-блоков
sudo sshd -T | grep -E "allowusers|allowgroups|match"

# 3. Проверка используемых алгоритмов (KEX)
# Важно: mlkem768x25519-sha256 должен быть в начале списка для PQC
sudo sshd -T | grep kexalgorithms

# 4. Анализ последних попыток входа
# Список последних 10 неудачных входов из базы btmp
sudo lastb -n 10

# 5. Статистика блокировок fail2ban
sudo fail2ban-client status sshd

# 6. Проверка целостности хостовых ключей
ls -la /etc/ssh/ssh_host_*_key
# → -rw------- 1 root root ... ssh_host_ed25519_key
# → -rw-r--r-- 1 root root ... ssh_host_ed25519_key.pub

# 7. Валидация systemd hardening (если применен)
systemd-analyze security sshd.service
# → Рекомендуется HIGH или MEDIUM
```

### Сценарий 2: Юридическая и информационная защита (Banner)

Настройка баннера, уведомляющего о мониторинге и запрете несанкционированного доступа, с валидацией:

```bash
# 1. Создание файла баннера
sudo tee /etc/ssh/banner << 'EOF'
 ***************************************************************************
 *                          UNAUTHORIZED ACCESS PROHIBITED                 *
 *             All connections are monitored and legally recorded.          *
 *                                                                         *
 *  This is a private computer system. Access is restricted to             *
 *  authorized users only. All activities are logged and monitored.        *
 *  Unauthorized access or use may result in civil or criminal penalties.  *
 ***************************************************************************
EOF

# 2. Настройка прав доступа (banner читается перед аутентификацией)
sudo chmod 644 /etc/ssh/banner

# 3. Подключение баннера в sshd_config
echo "Banner /etc/ssh/banner" | sudo tee -a /etc/ssh/sshd_config

# 4. Проверка синтаксиса (ОБЯЗАТЕЛЬНО перед перезапуском)
sudo sshd -t
# → (пустой вывод = синтаксис корректен)

# 5. Перезапуск службы
sudo systemctl reload sshd

# 6. Валидация: подключение из другого терминала
# При подключении баннер должен отображаться ДО запроса пароля/ключа
ssh -o BatchMode=yes user@server true
# → Баннер должен быть виден в выводе
```

### Сценарий 3: Атомарное применение конфигурации с откатом

Задача: Внести изменения в `sshd_config` без риска потерять доступ при ошибке синтаксиса или неправильном параметре.

```bash
# 1. Создание бэкапа с временной меткой
BACKUP="/etc/ssh/sshd_config.bak.$(date +%F_%H%M%S)"
sudo cp /etc/ssh/sshd_config "$BACKUP"
sudo md5sum "$BACKUP" > /root/sshd_config_hashes.txt

# 2. Проверка синтаксиса перед применением (ОБЯЗАТЕЛЬНО)
sudo sshd -t
# → Если вывод пустой — синтаксис корректен

# 3. Применение через drop-in (рекомендуется) или атомарная замена
# Вариант A: Drop-in (безопаснее, изолирует изменения)
sudo tee /etc/ssh/sshd_config.d/99-hardening.conf << 'EOF'
# ... новые параметры ...
EOF

# Вариант B: Полная замена с валидацией
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.new
# ... редактирование sshd_config.new ...
sudo diff -u "$BACKUP" /etc/ssh/sshd_config.new
sudo sshd -t -f /etc/ssh/sshd_config.new && \
    sudo mv /etc/ssh/sshd_config.new /etc/ssh/sshd_config

# 4. Проверка эффективного конфига
sudo sshd -T | grep -E "passwordauthentication|permitrootlogin|kexalgorithms"

# 5. Откат при ошибке
sudo cp "$BACKUP" /etc/ssh/sshd_config
sudo systemctl restart sshd
```

**Автоматизация через Ansible (идемпотентный apply + rollback):**

```yaml
- name: Бэкап sshd_config
  ansible.builtin.copy:
    src: /etc/ssh/sshd_config
    dest: "/etc/ssh/sshd_config.bak.{{ ansible_date_time.iso8601 }}"
    remote_src: yes
    owner: root
    group: root
    mode: '0600'

- name: Применить SSH hardening
  ansible.builtin.template:
    src: sshd_config.j2
    dest: /etc/ssh/sshd_config
    validate: '/usr/sbin/sshd -t -f %s'
    backup: yes
  notify: restart sshd

- name: Fallback откат при ошибке
  ansible.builtin.copy:
    src: /etc/ssh/sshd_config.bak
    dest: /etc/ssh/sshd_config
    remote_src: yes
  when: sshd_apply_failed | default(false)
```

### Сценарий 4: Аварийный доступ (Break-Glass)

Задача: Обеспечить аварийный доступ при полной потере SSH (неверный конфиг, потеря ключей, блокировка fail2ban).

```bash
# 1. Подготовка breakglass пользователя (только для аварий)
sudo useradd -m -s /bin/bash breakglass
sudo mkdir -p /home/breakglass/.ssh
sudo chmod 700 /home/breakglass/.ssh

# 2. Генерация выделенного ED25519-SK ключа (FIDO2 токен, touch-required)
ssh-keygen -t ed25519-sk -O resident -O verify-required -C "breakglass-$(date +%F)" -f ~/.ssh/breakglass_sk

# 3. Размещение публичного ключа
cat ~/.ssh/breakglass_sk.pub | sudo tee /home/breakglass/.ssh/authorized_keys
sudo chmod 600 /home/breakglass/.ssh/authorized_keys
sudo chown -R breakglass:breakglass /home/breakglass/.ssh

# 4. Отдельный Match-блок в основном sshd_config (только для breakglass)
sudo tee -a /etc/ssh/sshd_config.d/99-hardening.conf << 'EOF'

# Break-glass доступ: только FIDO2, только с консоли/IPMI подсети
Match User breakglass Address 192.168.100.0/24
    AuthenticationMethods publickey
    PubkeyAcceptedAlgorithms sk-ssh-ed25519@openssh.com
    PermitRootLogin no
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
    ForceCommand /usr/local/bin/breakglass-audit.sh
EOF

# 5. Скрипт аудита использования breakglass
sudo tee /usr/local/bin/breakglass-audit.sh << 'EOF'
#!/bin/bash
# Вызывается при каждом входе breakglass
logger -t ssh-breakglass "BREAKGLASS ACCESS: user=$USER from=$SSH_CONNECTION cmd=$SSH_ORIGINAL_COMMAND"
# Отправка алерта (email, Slack, PagerDuty, webhook)
curl -X POST -H "Content-Type: application/json" \
     -d "{\"text\":\"[ALERT] BREAKGLASS SSH ACCESS: $USER from $SSH_CONNECTION\"}" \
     "$ALERT_WEBHOOK_URL" 2>/dev/null || true
# Передача управления в шелл
exec /bin/bash
EOF
sudo chmod 755 /usr/local/bin/breakglass-audit.sh
sudo chown root:root /usr/local/bin/breakglass-audit.sh

# 6. Документирование процедуры восстановления
sudo tee /root/BREAKGLASS_RECOVERY.md << 'EOF'
# Процедура аварийного доступа (Break-Glass)

## Признаки необходимости:
- Потеря всех SSH-ключей администраторов
- Ошибка в sshd_config, блокирующая доступ
- fail2ban заблокировал все админы
- Сетевой firewall блокирует основной порт

## Действия:
1. Подключиться через Out-of-Band (IPMI/iDRAC/iLO/Console)
2. Проверить статус: `systemctl status sshd sshd-alt`
3. Если основной sshd неисправим: `systemctl start sshd-alt` (порт 2222, только 192.168.100.0/24)
4. Если нужен root: использовать FIDO2 токен breakglass пользователя
5. После входа: исправить конфиг, `sshd -t && systemctl reload sshd`
6. Обязательно: отозвать использованный breakglass ключ, сгенерировать новый
EOF
```

## Диагностика и устранение неполадок

### Типичные ошибки и их решения

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

### Диагностический чеклист

```bash
# 1. Клиентская отладка (подробный вывод)
ssh -vvv user@server
# → Ищите строки с debug1, debug2 для понимания процесса handshake

# 2. Серверные логи
sudo journalctl -u sshd --since "10 minutes ago" | grep -E "Failed|refused|match|denied|invalid user"

# 3. Проверка эффективного конфига
sudo sshd -T | grep -E "pubkeyauthentication|passwordauthentication|permitroot|authenticationmethods|maxauthtries|loglevel"

# 4. Проверка прав доступа (StrictModes)
namei -mo /home/user/.ssh/authorized_keys
# → ожидается: drwx------ . ssh/ authorized_keys (600)

# 5. Проверка отпечатка ключа
ssh-keygen -l -f ~/.ssh/id_ed25519.pub
ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub

# 6. Проверка known_hosts
ssh-keygen -F server.example.com
# Если хост отсутствует — добавьте вручную или через ssh-keyscan

# 7. Проверка статуса службы
sudo systemctl status sshd
sudo systemctl status fail2ban

# 8. Проверка файрвола
sudo iptables -L -n | grep :22
# или
sudo nft list ruleset | grep 22
```

## Рекомендации по безопасности

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

## Крайние случаи и ограничения

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

## Дополнительная информация

### Карта документации по защите SSH

Для глубокого изучения конкретных аспектов защиты используйте специализированные разделы:

| Раздел | Ссылка | Ключевые темы |
| :--- | :--- | :--- |
| **Аутентификация** | [ssh_authentication.md](./ssh_authentication.md) | ED25519, FIDO2, SSH CA, права доступа. |
| **Контроль доступа** | [ssh_access_control.md](./ssh_access_control.md) | AllowGroups, Match Blocks, IP-фильтрация. |
| **Hardening** | [ssh_hardening_best_practices.md](./ssh_hardening_best_practices.md) | ML-KEM, Ciphers, таймауты сессий. |
| **Мониторинг** | [ssh_monitoring_and_troubleshooting.md](./ssh_monitoring_and_troubleshooting.md) | ssh-audit, анализ журналов, отладка. |
| **Скрытие портов** | [port_knocking.md](./port_knocking.md) | Технологии knockd и SPA (fwknop). |

### См. также

- [SSH Overview](../ssh_overview.md) — фундаментальные принципы протокола.
- [SSH Client Config](../ssh_client_config.md) — настройки безопасности на стороне клиента.
- [fail2ban](../../Tools/fail2ban.md) — детальное руководство по автоматизации блокировок.
- [Инструменты сетевого мониторинга](../../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика
- [PAM: обзор и настройка](../../pam_overview.md) — глубокая интеграция MFA через PAM.
- [nftables threat modeling](../../../Networking/Settings/tools/nftables/threat_modeling.md) — сетевая фильтрация как первый эшелон защиты.
