# Удаленный доступ к серверам

## Определения

- **Удаленный доступ:** Совокупность методов и технологий для управления сервером на расстоянии через сетевые интерфейсы.
- **Внутриполосное управление (In-Band Management):** Доступ через основную операционную систему и её сетевой стек. Примеры: SSH, VNC, RDP, Cockpit. Требует полностью работоспособной ОС и сетевых настроек.
- **Внеполосное управление (Out-of-Band Management, OOB):** Аппаратный доступ к серверу через выделенный порт управления (Management Port), независимый от состояния основной ОС. Работает, даже если сервер выключен или ОС зависла.
- **BMC (Baseboard Management Controller):** Автономный микроконтроллер (например, iDRAC, iLO, BMC Supermicro), обеспечивающий функции мониторинга и управления аппаратным обеспечением.
- **IPMI (Intelligent Platform Management Interface):** Промышленный стандарт для взаимодействия с BMC. В 2026 году считается устаревшим (Legacy), но всё ещё широко используется.
- **Redfish API:** Современный стандарт управления оборудованием на базе RESTful API (HTTPS/JSON). Предоставляет безопасный и масштабируемый интерфейс для автоматизации инфраструктуры.
- **IP-KVM (KVM-over-IP):** Технология передачи видеосигнала и эмуляции клавиатуры/мыши через сеть. Встроена в большинство современных BMC.
- **Serial-over-LAN (SOL):** Перенаправление текстового вывода последовательного порта (COM-порта) через сетевой протокол (IPMI/SSH).
- **Bastion Host (Jump Host):** Сервер с публичным IP, через который осуществляется доступ к внутренним сегментам сети. Работает как точка входа, сокращающая поверхность атаки.
- **ZTNA (Zero Trust Network Access):** Архитектурный подход, при котором доступ предоставляется на основе динамической оценки доверия (identity, device posture, context), а не статического сетевого расположения.

## Теоретические основы

### OSI model и протоколы удаленного доступа

Протоколы удаленного доступа размещаются преимущественно на сессионном (L5) и прикладном (L7) уровнях модели OSI:

- **SSH:** L7 (прикладной), но использует TCP (L4) напрямую.
- **RDP:** L7 с собственным транспортным механизмом поверх TCP.
- **VNC (RFB):** L7, может работать поверх TCP или Unix-сокетов.
- **IPMI/SOL:** L7 над UDP (RMCP) или TCP (SSH для SOL).
- **Redfish:** L7 REST/HTTPS поверх TCP.
- **VPN (WireGuard, IPsec, OpenVPN):** Работают на L3 (IP) или L2 (TAP) с инкапсуляцией.

### Транспортный уровень: TCP vs UDP

Выбор транспортного протокола влияет на надежность и производительность удаленного доступа:

| Протокол | Транспорт | Особенности |
| :--- | :--- | :--- |
| **SSH** | TCP | Гарантированная доставка, порядок пакетов. Чувствителен к задержкам и потерям (поведение при разрыве зависит от TCP-таймаутов). |
| **RDP** | TCP | Адаптивное сжатие, tolerant к потерям. Требует стабильного канала. |
| **VNC** | TCP | Передает полные кадры. Высокий overhead на низкоскоростных каналах. |
| **mosh** | UDP | State Synchronization Protocol. Толерантен к смене IP, потерям пакетов и роумингу. |
| **WireGuard** | UDP | Минимальный overhead, быстрый handshake. Требует поддержки NAT-T или проброса портов. |
| **IPsec (IKEv2)** | UDP 500/4500 | MOBIKE поддерживает смену IP без переподключения. |
| **OpenVPN** | TCP/UDP | TCP маскируется под HTTPS. UDP — выше производительность. |

### Аутентификация: ключи, сертификаты, MFA, FIDO2

| Метод | Безопасность | Масштабируемость | Применение |
| :--- | :--- | :--- | :--- |
| **Пароль** | Низкая | Высокая | Запрещен в production. |
| **Статические ключи (ed25519)** | Высокая | Средняя | Стандарт для серверов и CI/CD. |
| **SSH-сертификаты (CA)** | Очень высокая | Высокая | Enterprise, >50 серверов. Централизованный отзыв, KRL. |
| **FIDO2 / Ed25519-SK** | Максимальная | Средняя | YubiKey, TPM. Защита от краж ключей. |
| **MFA (PAM)** | Очень высокая | Средняя | OATH-TOTP, Duo, YubiKey OTP. Второй фактор поверх ключа. |
| **Kerberos/GSSAPI** | Высокая | Высокая | Доменные среды (Active Directory, FreeIPA). |

### Шифрование в протоколах удаленного доступа

- **SSH:** End-to-end шифрование на транспортном уровне (AES-GCM, ChaCha20-Poly1305). PFS гарантирована через ephemeral ключи.
- **TLS (Redfish, Cockpit, RDP Gateway):** Шифрование на прикладном уровне. Зависит от корректной настройки CA и версии протокола.
- **IPMI v1.5/v2.0:** Устаревшее шифрование (SHA-1, AES-CBC). Уязвимо к атакам на RAKP. Требует изоляции в dedicated management VLAN.
- **WireGuard:** ChaCha20-Poly1305, Curve25519. Шифрование на L3. Минимальный код, audit-friendly.
- **IPsec:** AES-GCM, IKEv2 с ECDH. Шифрование на L3/L4. Сложность настройки.

### Zero Trust и удаленный доступ

Принципы Zero Trust применительно к удаленному доступу:

1. **Никому не доверять по умолчанию:** Даже пользователи внутри корпоративной сети проходят аутентификацию.
2. **Минимальные привилегии:** Доступ только к конкретным хостам/сервисам через `PermitOpen`, `authorized_keys` command=.
3. **Непрерывная верификация:** Короткоживущие сертификаты (SSH CA), сессионные VPN-ключи.
4. **Изоляция сессий:** Bastion без Agent Forwarding, `tmux`/`mosh` вместо `screen`, ограничение `MaxSessions`.
5. **Полная видимость:** Логирование всех входов, `auditd`, SIEM-интеграция.

### NAT-траверсал

При доступе через NAT (роутер, файрвол) возникают проблемы с установлением прямых соединений:

- **SSH:** Использует TCP. Работает через NAT без проблем при пробросе порта на стороне клиента или сервера.
- **mosh:** Использует UDP. Требует проброса диапазона портов или поддержки UDP на файрволе. Клиент initiates соединение.
- **WireGuard:** UDP. Клинт всегда initiates. `PersistentKeepalive = 25` решает проблему закрытия NAT-таблицы.
- **IPsec IKEv2:** NAT-T (UDP 4500). Может работать через NAT без проблем.
- **OpenVPN:** TCP 443 маскируется под HTTPS. UDP — требует проброса.

### Split tunneling vs full tunnel

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Full Tunnel** | Весь трафик идет через VPN | Корпоративные сети, строгие политики DLP |
| **Split Tunnel** | Только подсети VPN идут через туннель, остальное — напрямую | Разработка, обход ограничений пропускной способности |
| **Reverse Split** | Трафик в корпоративную сеть идет через VPN, интернет — напрямую | Гибридные сценарии, баланс производительности |

## Основные концепции

### Иерархия управления и доступа

Для обеспечения максимальной отказоустойчивости используется многоуровневая модель:

1. **Сервисный уровень (API/Web):** Cockpit, Portainer (для контейнеров), Redfish.
2. **Консольный уровень (SSH):** Основной инструмент администратора.
3. **Графический уровень (VNC/RDP/X2Go):** Для задач, требующих GUI (например, работа с проприетарным ПО).
4. **Аварийный/Аппаратный уровень (OOB/KVM):** Прямой доступ к "железу", BIOS, установке ОС.

### Bastion и Jump Host

Bastion-host — сервер с публичным IP, через который осуществляется доступ к внутренним сегментам сети. Это сокращает поверхность атаки: на внутренних серверах SSH слушает только на management VLAN или localhost.

**ProxyJump (рекомендуемый):**
```bash
# Прозрачный туннель через bastion
ssh -J user@bastion user@internal-host

# Или в ~/.ssh/config
Host internal-host
  HostName 10.0.1.50
  User admin
  ProxyJump bastion
```

**ProxyCommand (legacy, для старых OpenSSH):**
```bash
ssh -o ProxyCommand="ssh -W %h:%p bastion" user@internal-host
```

**Вариант с socat (если netcat недоступен):**
```bash
ssh -o ProxyCommand="socat - EXEC:'ssh -W %h:%p bastion'" user@db-server
```

### Возможности внеполосного управления (OOB)

Модули BMC (iDRAC, iLO, ALOM) функционируют как независимые компьютеры и предоставляют:
- **vKVM:** Удаленный экран с момента инициализации BIOS.
- **Power Management:** Принудительное питание (ON/OFF), жесткая перезагрузка (Cold Reset).
- **Virtual Media:** Монтирование удаленных ISO-образов (HTTP/Samba) как локальных USB/DVD-приводов.
- **Hardware Health:** Мониторинг температуры, вольтажа, статуса дисков и вентиляторов.
- **SOL (Serial-over-LAN):** Текстовый доступ к консоли загрузки Linux.

### Высокая доступность управления

Для критичных инфраструктур требуется redundancy на всех уровнях:

1. **Несколько BMC интерфейсов:** Если сервер имеет два блока питания, он обычно имеет и два dedicated management порта.
2. **Несколько точек входа:** Разные операторы/провайдера для доступа к bastion.
3. **L3-out-of-band:** Отдельный маршрут к management VLAN через другой роутер.
4. **Console серверы:** Порядка 48 портов (например., OpenGear) для последовательного доступа ко всем серверам стойки.

## Безопасность удаленного доступа

- **Изоляция Management Network:** Порты BMC **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** выставлять в публичные сети. Требуется выделенный VLAN или физически изолированная сеть.
- **SSH-туннелирование:** Протоколы без встроенного шифрования (VNC, старые версии IPMI) должны использоваться **только** внутри SSH-туннеля или VPN.
- **ZTNA и Mesh-VPN:** Современные решения (Tailscale, ZeroTier, WireGuard) позволяют организовать безопасный доступ к серверам без проброса портов, используя топологию "точка-точка" с шифрованием.
- **Defense in Depth:** Файрвол + Port Knocking/SPA + SSH ключи + MFA + мониторинг.
- **Принцип минимальных привилегий:** `AllowUsers` вместо `DenyUsers`, `PermitRootLogin no`, `PasswordAuthentication no`.

## Практические сценарии

### 1. Безопасный консольный доступ (SSH)

SSH — основной метод управления. Детальная настройка (ключи, hardening, туннели) находится в разделе: [**SSH (Secure Shell)**](../Security/ssh/ssh_overview.md).

### 2. Аварийное восстановление через BMC (iDRAC/iLO/IPMI)

Если сервер недоступен по SSH:
1. Зайдите в Web-интерфейс BMC.
2. Откройте **Virtual Console (KVM)**.
3. Если ОС зависла: выполните **Power Action -> Reset**.
4. Если поврежден загрузчик: подключите ISO через **Virtual Media** и загрузитесь в **Rescue Mode**.

**Управление через CLI (ipmitool):**
```bash
# Проверка состояния питания
ipmitool -I lanplus -H <IP> -U <User> -P <Pass> power status

# Включение Serial-over-LAN
ipmitool -I lanplus -H <IP> -U <User> -P <Pass> sol activate
```

### 3. Bastion / Jump Host

Все внутренние серверы должны быть доступны только через bastion:

```bash
# Конфигурация ~/.ssh/config
Host bastion
  HostName bastion.example.com
  User admin
  IdentityFile ~/.ssh/id_ed25519

Host internal-*
  User admin
  IdentityFile ~/.ssh/id_ed25519
  ProxyJump bastion
  StrictHostKeyChecking accept-new
```

### 4. mosh для нестабильных сетей

`mosh` (Mobile Shell) — замена SSH для мобильных пользователей и нестабильных соединений. Использует UDP и протокол синхронизации состояния экрана, а не поток байтов.

```bash
# На сервере
sudo apt install mosh

# На клиенте
mosh user@server -- ssh -p 2222

# Через bastion
mosh user@bastion -- ssh -L 5432:db.internal:5432 user@jump
```

### 5. SSH-сертификаты (CA)

Для инфраструктур >50 серверов используйте SSH CA вместо статических `authorized_keys`:

```bash
# Подпись сертификата
ssh-keygen -s /etc/ssh/ca_user -I user@company.com -n admin -V +52w ~/.ssh/id_ed25519.pub

# Проверка сертификата
ssh-keygen -L -f ~/.ssh/id_ed25519-cert.pub
```

Детали: [SSH-аутентификация по сертификатам](../Security/ssh/server/ssh_certificate_authentication.md).

### 6. FIDO2 / TPM-backed ключи

```bash
# Генерация ключа, привязанного к YubiKey
ssh-keygen -t ed25519-sk -C "admin@workstation" -f ~/.ssh/id_ed25519_sk

# Для TPM 2.0
ssh-keygen -t ecdsa-sk -f ~/.ssh/id_ecdsa_sk
```

### 7. MFA через PAM

```bash
# Установка Google Authenticator PAM
sudo apt install libpam-google-authenticator

# Настройка пользователя
google-authenticator

# В /etc/pam.d/sshd добавьте:
auth required pam_google_authenticator.so

# В /etc/ssh/sshd_config:
ChallengeResponseAuthentication yes
AuthenticationMethods publickey,password publickey,keyboard-interactive
```

### 8. Графический доступ через RDP (xrdp)

RDP эффективнее VNC за счет адаптивного сжатия. Подходит для работы с удаленными рабочими столами.

```bash
# Установка xrdp на Ubuntu/Debian
sudo apt update && sudo apt install xrdp -y

# Настройка прав (добавление в группу для доступа к сертификатам)
sudo adduser xrdp ssl-cert

# Фикс для корректного выхода (Session Management)
echo "exec startxfce4" > ~/.xsession

sudo systemctl restart xrdp
```

### 9. X2Go (альтернатива RDP/VNC)

X2Go использует протокол NX с компрессией, лучше VNC на медленных каналах:

```bash
# На сервере Ubuntu/Debian
sudo apt install xfce4 x2goserver x2goserver-xsession -y

# На клиенте: установите x2goclient и подключитесь
```

### 10. Доступ к серверу за NAT (Reverse SSH Tunnel)

Используется, когда у сервера нет белого IP и он находится за сетевым экраном.

```bash
# Выполняется на сервере ЗА NAT:
# Направляет порт 22 сервера на порт 2222 публичного VPS
ssh -R 2222:localhost:22 user@public_vps_ip -N -f

# Теперь с публичного VPS можно зайти на сервер за NAT:
ssh -p 2222 localhost
```

### 11. Настройка VNC через SSH-туннель (TigerVNC + XFCE)

Безопасный метод графического доступа без открытия портов вовне.

**Установка на сервере:**
```bash
sudo apt update
sudo apt install xfce4 xfce4-goodies tigervnc-standalone-server -y
```

**Настройка:**
1. Выполните `vncserver`, задайте пароль.
2. Остановите: `vncserver -kill :1`.
3. Отредактируйте `~/.vnc/xstartup`:
```bash
#!/bin/bash
xrdb $HOME/.Xresources
startxfce4 &
```
4. Сделайте файл исполняемым: `chmod +x ~/.vnc/xstartup`.

**Запуск с ограничением на localhost:**
```bash
vncserver -localhost :1
```

**Подключение с клиента:**
```bash
# Создание туннеля (порт 5901 сервера -> 59001 локально)
ssh -L 59001:localhost:5901 -N -f user@server_ip

# Подключение VNC-клиентом к адресу localhost:59001
```

### 12. Веб-управление (Cockpit)

Легковесный интерфейс для мониторинга и базового администрирования.

```bash
# Установка
sudo apt install cockpit -y
sudo systemctl enable --now cockpit.socket
```

Доступ: `https://<server_ip>:9090`. Использует системную PAM-аутентификацию.

### 13. Настройка Serial Console (SOL)

Для текстового доступа через BMC необходимо настроить Linux:

1. В `/etc/default/grub` добавьте:
   `GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200"`
2. Обновите GRUB: `sudo update-grub`.
3. Включите сервис: `sudo systemctl enable serial-getty@ttyS0.service`.

### 14. Защита от brute-force (fail2ban / crowdsec)

```bash
# Установка fail2ban
sudo apt install fail2ban -y

# Локальная конфигурация для SSH
sudo tee /etc/fail2ban/jail.local <<EOF
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 1d
findtime = 10m
EOF

sudo systemctl restart fail2ban

# Проверка
sudo fail2ban-client status sshd
```

### 15. VPN клиенты для удаленного доступа

Для доступа к корпоративной сети используйте mesh-VPN. Детальные сценарии: [Remote Access VPN — сравнение](../../Networking/Tunnels/remote_access_vpn.md), [WireGuard](../../Vpn/wireguard.md), [Tailscale](../../Vpn/tailscale.md), [ZeroTier](../../Vpn/zerotier.md).

**WireGuard Remote Access (краткий пример):**
```ini
# ~/.config/wireguard/wg0.conf (клиент)
[Interface]
PrivateKey = <client_private_key>
Address = 10.0.0.2/32
DNS = 10.0.0.1

[Peer]
PublicKey = <server_public_key>
Endpoint = vpn.example.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
```

### 16. Доступ к Docker API через SSH

```bash
# Проброс Unix-сокета Docker
ssh -L /tmp/docker.sock:/var/run/docker.sock user@host

# Использование локально
export DOCKER_HOST=unix:///tmp/docker.sock
docker ps
```

## Мониторинг и аудит

### Кто вошел и что делает

```bash
# Активные сессии SSH
who
# → user1    pts/0        2026-09-13 10:00 (10.0.0.1)

# История входов
last -f /var/log/wtmp
# → user1    pts/0        10.0.0.1              Mon Sep 13 10:00   still logged in

# Неудачные попытки
sudo grep "Failed password" /var/log/auth.log | tail -20

# Журнал SSH (journalctl)
sudo journalctl -u sshd --since "1 hour ago"
```

### Аудит через auditd

```bash
# Установка
sudo apt install auditd audispd-plugins -y

# Правила для SSH
sudo tee /etc/audit/rules.d/ssh-audit.rules <<EOF
-w /etc/ssh/sshd_config -p wa -k sshd_config
-w /etc/ssh/ssh_host_*_key -p wa -k ssh_host_key
-w /root/.ssh/ -p wa -k root_ssh
-w /home/ -p wa -k user_ssh
-w /var/log/auth.log -p wa -k auth_log
EOF

sudo systemctl restart auditd
sudo ausearch -k sshd_config -i
```

### Мониторинг OOB

```bash
# Redfish (curl)
curl -k -u admin:password https://bmc.local/redfish/v1/Systems/1

# ipmitool сensor
ipmitool -I lanplus -H <bmc> -U <user> sensor
```

## Диагностика и устранение неисправностей

### Типичные проблемы

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Connection timed out** | Файрвол блокирует порт, сервер выключен | `nc -zv host 22`, `ping` | Открыть порт, проверить сеть |
| **Connection refused** | SSH не слушает на порту | `ss -tlnp \| grep 22` | Запустить sshd, проверить ListenAddress |
| **Permission denied (publickey)** | Ключ не добавлен в ssh-agent, неверные права | `ssh-add -l`, `ls -la ~/.ssh` | `chmod 600 ~/.ssh/id_ed25519`, добавить ключ |
| **Host key verification failed** | Изменился хостовый ключ | `ssh-keygen -F host` | Проверить целостность хоста, обновить known_hosts |
| **Broken pipe / Connection reset** | Разрыв TCP-соединения | `dmesg`, `journalctl -u sshd` | Проверить сеть, увеличить TCPKeepAlive |
| **Write failed: Broken pipe** | Клиентский таймаут меньше серверного | `ClientAliveInterval` | Синхронизировать таймауты клиента и сервера |
| **IPMI: RMCP error** | Порты UDP 623/664/443 заблокированы | `tcpdump udp port 623` | Открыть порты в dedicated management VLAN |
| **SOL зависает** | Неправильная скорость COM-порта | Проверить `GRUB_CMDLINE_LINUX` | Установить `console=ttyS0,115200` |
| **RDP: черный экран** | Не настроен DE/WM | Проверить `~/.xsession` | Указать `startxfce4` или `gnome-session` |
| **mosh: не подключается** | UDP заблокирован | `nc -u` | Пробросить UDP или использовать SSH fallback |

### Диагностические команды

```bash
# Проверка доступности порта
nc -zv target-host 22

# Трассировка до SSH
traceroute -T -p 22 target-host

# Проверка DNS для SSH
ssh -o BatchMode=yes -o ConnectTimeout=5 user@host "echo OK"

# Проверка ключей на хосте
ssh-keyscan -t ed25519 host >> ~/.ssh/known_hosts

# Проверка прав на ключи
ls -la ~/.ssh/
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
chmod 600 ~/.ssh/known_hosts
```

## Дополнительная информация

### Сравнение методов доступа

| Метод | Протокол | Шифрование | Уровень | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| **SSH** | SSH | Да | CLI | Повседневное управление |
| **RDP** | RDP (TCP 3389) | Да | GUI | Работа с Windows-приложениями |
| **X2Go** | NX (SSH туннель) | Да | GUI | Медленные каналы, лучше VNC |
| **VNC** | RFB (TCP 5900+) | Нет* | GUI | Старые системы, через туннель |
| **Cockpit** | HTTPS (9090) | Да | Web | Мониторинг, новички |
| **BMC/IPMI** | RMCP (UDP 623) | Слабое | HW | Авария, BIOS, установка ОС |
| **mosh** | UDP | Да | CLI | Мобильные пользователи, плохая связь |

### Сравнение VPN технологий для удаленного доступа

| Параметр | WireGuard | OpenVPN | IPsec (IKEv2) | L2TP/IPsec |
|----------|-----------|---------|---------------|------------|
| **Производительность** | Очень высокая | Средняя | Высокая | Средняя |
| **Простота настройки** | Очень простая | Средняя | Сложная | Сложная |
| **NAT Traversal** | Отлично (UDP) | Отлично (TCP 443) | Хорошо (NAT-T) | Хорошо (NAT-T) |
| **Аутентификация** | Статические ключи | PKI, LDAP, RADIUS | PKI, EAP, PSK | PPP (MSCHAPv2, EAP) |
| **Split Tunneling** | Да (AllowedIPs) | Да (route) | Да (traffic selectors) | Да (PPP routes) |
| **Kill Switch** | Да (PostUp/PostDown) | Да (firewall rules) | Да (iptables) | Ограничен |
| **Роуминг** | Нативно (смена IP) | Требует переподключения | MOBIKE | Нет |

### Реализации OOB (BMC) по вендорам

- **Dell:** iDRAC (integrated Dell Remote Access Controller).
- **HPE:** iLO (Integrated Lights-Out).
- **Supermicro:** Generic IPMI / BMC.
- **Lenovo/IBM:** XClarity Controller (XCC) / IMM.
- **Cisco:** CIMC (Cisco Integrated Management Controller).

### Redfish API vs IPMI

| Параметр | IPMI | Redfish |
| :--- | :--- | :--- |
| **Транспорт** | UDP (Binary) | HTTPS (JSON) |
| **Безопасность** | Уязвимости в RAKP | TLS + Современная Auth |
| **Масштабируемость** | Низкая (сложные скрипты) | Высокая (RESTful) |
| **Читаемость** | Требует парсеров | Человекочитаемый JSON |

### См. также

- [SSH — обзор](../Security/ssh/ssh_overview.md)
- [Практическое использование SSH и туннелирование](../Security/ssh/ssh_usage_and_tunnels.md)
- [SSH-аутентификация по сертификатам](../Security/ssh/server/ssh_certificate_authentication.md)
- [SSH hardening](../Security/ssh/server/ssh_hardening_best_practices.md)
- [Port Knocking](../Security/ssh/server/port_knocking.md)
- [Remote Access VPN — сравнение](../../Networking/Tunnels/remote_access_vpn.md)
- [WireGuard](../../Vpn/wireguard.md)
- [Tailscale](../../Vpn/tailscale.md)
- [ZeroTier](../../Vpn/zerotier.md)
- [SSH-сессии и терминальные мультиплексоры](../Security/ssh/ssh_session_management.md) — tmux, screen, mosh для сохранения сессий
- [Управление пользователями](users_management.md) — централизация доступа, PAM, sudo
