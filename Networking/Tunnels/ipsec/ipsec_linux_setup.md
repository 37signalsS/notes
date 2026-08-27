# IPsec: настройка стека KAME/racoon на Linux

> **Основной документ:** [IPsec (основной документ)](./ipsec.md).

Данный файл содержит техническое руководство по эксплуатации устаревшей реализации IPsec через стек KAME и демон управления ключами racoon.

> **ВНИМАНИЕ — УСТАРЕВШАЯ ТЕХНОЛОГИЯ:** Стек KAME/racoon не поддерживается и не обновляется с начала 2010-х годов. Он содержит критические ограничения безопасности (отсутствие поддержки IKEv2, использование дискредитированных алгоритмов шифрования). Для новых инсталляций **ОБЯЗАТЕЛЬНО** используйте **[strongSwan](./ipsec.md)** или **LibreSwan**.

---

## Определения

**KAME** — исторический проект по реализации стека IPv6 и IPsec для BSD, части которого были интегрированы в ядро Linux. Подсистема **XFRM** является его идеологическим преемником в modern Linux.

**racoon** — демонIKEv1-демон) для динамического согласования Security Associations (SA) и управления ключами. Работает в пользовательском пространстве и взаимодействует с ядром через протокол PF_KEY.

**setkey** — низкоуровневая утилита для прямого манипулирования базами данных политик (SPD) и состояний (SAD) в ядре. Используется как для ручной настройки, так и для диагностики.

**ipsec-tools** — пакет, объединяющий `racoon` и `setkey`. В современных дистрибутивах может отсутствовать или находиться в репозиториях legacy-ПО.

**PF_KEY** — протокол управления ключами между пользовательским пространством и ядром Linux. Используется для передачи команд на создание/удаление SA.

---

## Предварительные требования

### Доступные дистрибутивы

| Дистрибутив | Доступность пакета | Репозиторий |
|-------------|-------------------|-------------|
| Debian 11 (Bullseye) | `racoon`, `ipsec-tools` | Основной |
| Debian 12 (Bookworm) | `racoon`, `ipsec-tools` | Основной |
| Ubuntu 20.04/22.04 | `racoon`, `ipsec-tools` | universe |
| CentOS 7 | `racoon`, `ipsec-tools` | Основной |
| CentOS 8/Stream | Удалён | EPEL (может отсутствовать) |
| Rocky/Alma 8+ | Удалён | EPEL (может отсутствовать) |
| Arch Linux | `racoon`, `ipsec-tools` | Основной |

### Установка

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install racoon ipsec-tools

# CentOS/RHEL 7
sudo yum install racoon ipsec-tools

# Arch Linux
sudo pacman -S racoon ipsec-tools
```

### Модули ядра

Убедитесь, что необходимые модули ядра загружены:

```bash
modprobe af_key
modprobe esp4

# Проверка
lsmod | grep -E "af_key|esp4"
# → af_key    24576  0
# → esp4      20480  0
```

### Права доступа

Файл секретов должен иметь строгие права:

```bash
chmod 600 /etc/racoon/psk.txt
chown root:root /etc/racoon/psk.txt
```

### Требования к сетевой среде

| Параметр | Требование |
|----------|------------|
| UDP 500 | Открыт между шлюзами (IKE согласование) |
| UDP 4500 | Открыт для NAT-Traversal (если применимо) |
| IP Protocol 50 (ESP) | Разрешён в файрволе |
| IP Forwarding | Включён на обоих шлюзах |
| Маршрутизация | Рабочая маршрутизация между Public IP шлюзов |

### Включение IP Forwarding

```bash
# Временно
sudo sysctl -w net.ipv4.ip_forward=1

# Постоянно
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-ipsec.conf
sudo sysctl -p /etc/sysctl.d/99-ipsec.conf
```

---

## Основные концепции

### Архитектура KAME в стеке Linux

```
+-------------------+
|   racoon (IKEv1)  |  ← Пользовательское пространство
+--------+----------+
         | PF_KEY
+--------v----------+
|     af_key        |  ← Модуль ядра
+--------+----------+
         |
+--------v----------+
|   SPD / SAD       |  ← Базы данных политик и ассоциаций
+--------+----------+
         |
+--------v----------+
|   ESP / AH        |  ← Обработка пакетов
+-------------------+
```

**Важно:** Стек KAME взаимодействует с ядром через протокол **PF_KEY v2** (RFC 2367). Это устаревший интерфейс, который в современных ядрах Linux заменён на **XFRM** (Netlink-based). Однако для legacy-приложений PF_KEY всё ещё доступен через модуль `af_key`.

### Компоненты взаимодействия

| Компонент | Роль в системе | Интерфейс |
|-----------|----------------|-----------|
| **racoon** | Обработка протокола ISAKMP (Фаза 1 и Фаза 2) в пользовательском пространстве. | PF_KEY |
| **setkey** | Синхронизация политик безопасности с ядром через протокол PF_KEY. | PF_KEY |
| **af_key** | Модуль ядра, необходимый для взаимодействия между `racoon` и сетевым стеком. | Ядро |
| **esp4** | Модуль ядра для обработки ESP-пакетов (шифрование/аутентификация). | Ядро |

### Конфигурационные файлы

| Путь | Назначение | Формат |
|------|------------|--------|
| `/etc/racoon.conf` | Основной файл: параметры IKE, предложения алгоритмов, пути к ключам. | racoon-специфичный |
| `/etc/racoon/psk.txt` | База секретов Pre-Shared Keys (формат: `IP-адрес Ключ`). | Текстовый |
| `/etc/ipsec-tools.conf` | Скрипт для `setkey`, содержащий правила перехвата трафика (SPD). | setkey-команды |

### Структура racoon.conf

Конфигурационный файл racoon.conf состоит из следующих основных секций:

```
# 1. Путь к файлу ключей и логирование
path pre_shared_key "/etc/racoon/psk.txt";
log notify;

# 2. Слушающий сокет
listen { ... }

# 3. Параметры удалённого пира (Фаза 1)
remote <IP> { ... }

# 4. Параметры туннеля (Фаза 2)
sainfo address <subnet> ... address <subnet> ... { ... }
```

### Фазы согласования IKEv1

```
Фаза 1 (ISAKMP SA):
    Main Mode (6 сообщений):
        Initiator → Responder: SA, KE, Nonce, ID
        Responder → Initiator: SA, KE, Nonce, ID
        Initiator → Responder: HASH_I
        Responder → Initiator: HASH_R

Фаза 2 (IPsec SA / Quick Mode):
    Initiator → Responder: HASH, SA, [KE,] Nonce, IDci, IDcr
    Responder → Initiator: HASH, SA, [KE,] Nonce, IDci, IDcr
    Initiator → Responder: HASH
```

---

## Практические сценарии настройки

### Site-to-Site (Туннельный режим)

**Параметры стенда:**
- **Локальный шлюз (Public IP):** `10.0.1.1` (защищаемая сеть `192.168.1.0/24`)
- **Удаленный шлюз (Public IP):** `10.0.255.1` (защищаемая сеть `192.168.255.0/24`)

#### 1. Подготовка окружения

```bash
# Загрузка модулей ядра
modprobe af_key
modprobe esp4

# Установка пакетов
sudo apt-get install racoon ipsec-tools  # Debian/Ubuntu
# или
sudo yum install racoon ipsec-tools     # CentOS/RHEL 7

# Включение IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1
```

#### 2. Настройка политик безопасности (`/etc/ipsec-tools.conf`)

Этот файл инициализирует SPD (Security Policy Database). Без этих правил ядро не будет знать, что трафик нужно шифровать.

```bash
#!/usr/sbin/setkey -f
# Очистка текущих записей перед применением
flush;
spdflush;

# Политика для ИСХОДЯЩЕГО трафика
spdadd 192.168.1.0/24 192.168.255.0/24 any -P out ipsec
    esp/tunnel/10.0.1.1-10.0.255.1/require;

# Политика для ВХОДЯЩЕГО трафика
spdadd 192.168.255.0/24 192.168.1.0/24 any -P in ipsec
    esp/tunnel/10.0.255.1-10.0.1.1/require;
```

**Примечание:** Параметры `esp/tunnel/.../require` указывают, что для данного трафика обязателен ESP в туннельном режиме. Значения IP — это адреса шлюзов (не внутренние подсети).

#### 3. Настройка демона ключей (`/etc/racoon.conf`)

```bash
path pre_shared_key "/etc/racoon/psk.txt";
log notify; 

listen {
    isakmp 10.0.1.1 [500];
    strict_address;
}

# Фаза 1: Установление защищенного канала управления
remote 10.0.255.1 {
    exchange_mode main;
    proposal {
        encryption_algorithm 3des;   # ВНИМАНИЕ: Алгоритм признан слабым
        hash_algorithm sha1;        # ВНИМАНИЕ: Алгоритм признан слабым
        authentication_method pre_shared_key;
        dh_group 2;                 # MODP 1024
    }
}

# Фаза 2: Создание SA для пользовательских данных
sainfo address 192.168.1.0/24 any address 192.168.255.0/24 any {
    pfs_group 2;
    encryption_algorithm 3des;
    authentication_algorithm hmac_sha1;
    compression_algorithm deflate;
}
```

**Разбор параметров:**
- `exchange_mode main` — Main Mode (6 сообщений), скрывает ID сторон. Агрессивный режим (`aggressive`) менее безопасен.
- `encryption_algorithm` — Алгоритм шифрования. **3DES признан слабым** (см. раздел "Безопасность").
- `hash_algorithm` — Алгоритм хеширования для аутентификации. **SHA1 признан слабым**.
- `dh_group 2` — Группа Diffie-Hellman. **MODP 1024 признана слабой**.
- `pfs_group` — Группа Perfect Forward Secrecy для Фазы 2.
- `compression_algorithm deflate` — Сжатие (опционально, может увеличить latency).

#### 4. Настройка секретов (`/etc/racoon/psk.txt`)

```text
10.0.255.1    MySuperSecretKey123
```

**Важно:** Права доступа должны быть строго `600` (`chmod 600 /etc/racoon/psk.txt`), иначе демон откажется работать из соображений безопасности.

#### 5. Применение и запуск

```bash
# Применение политик SPD
sudo setkey -f /etc/ipsec-tools.conf

# Запуск демона racoon
sudo racoon

# Или запуск в отладочном режиме (для диагностики)
sudo racoon -F -d
```

#### 6. Валидация

```bash
# Проверка SPD
sudo setkey -DP

# Проверка SAD (после установки туннеля)
sudo setkey -D

# Проверка статуса racoon
sudo racoonctl show-sa isakmp
sudo racoonctl show-sa esp

# Пинг через туннель
ping -c 4 192.168.255.1
```

### Remote Access (Клиент-Шлюз)

**Сценарий:** Удалённый клиент подключается к шлюзу для доступа к внутренней сети.

**Параметры:**
- **Шлюз (Public IP):** `10.0.1.1` (защищаемая сеть `192.168.1.0/24`)
- **Клиент:** Динамический IP (защищаемая сеть `10.0.0.0/24`)

#### Конфигурация шлюза (`/etc/racoon.conf`)

```bash
path pre_shared_key "/etc/racoon/psk.txt";
log notify;

listen {
    isakmp 10.0.1.1 [500];
}

# Удалённый клиент (динамический IP)
remote anonymous {
    exchange_mode main;
    proposal {
        encryption_algorithm 3des;
        hash_algorithm sha1;
        authentication_method pre_shared_key;
        dh_group 2;
    }
}

# Фаза 2: любой адрес клиента -> внутренняя сеть
sainfo address 192.168.1.0/24 any address 10.0.0.0/24 any {
    pfs_group 2;
    encryption_algorithm 3des;
    authentication_algorithm hmac_sha1;
}
```

#### Конфигурация политики (`/etc/ipsec-tools.conf`)

```bash
#!/usr/sbin/setkey -f
flush;
spdflush;

# Исходящий трафик от шлюза к клиенту
spdadd 192.168.1.0/24 10.0.0.0/24 any -P out ipsec
    esp/tunnel/10.0.1.1-0.0.0.0/require;

# Входящий трафик от клиента к шлюзу
spdadd 10.0.0.0/24 192.168.1.0/24 any -P in ipsec
    esp/tunnel/0.0.0.0-10.0.1.1/require;
```

### Hub-and-Spoke (Звезда)

**Сценарий:** Центральный шлюз (Hub) связывает несколько удалённых сайтов (Spokes).

**Параметры:**
- **Hub (Public IP):** `10.0.1.1` (защищаемая сеть `192.168.1.0/24`)
- **Spoke 1 (Public IP):** `10.0.2.1` (защищаемая сеть `192.168.2.0/24`)
- **Spoke 2 (Public IP):** `10.0.3.1` (защищаемая сеть `192.168.3.0/24`)

#### Конфигурация Hub (`/etc/racoon.conf`)

```bash
path pre_shared_key "/etc/racoon/psk.txt";
log notify;

listen {
    isakmp 10.0.1.1 [500];
}

# Spoke 1
remote 10.0.2.1 {
    exchange_mode main;
    proposal {
        encryption_algorithm 3des;
        hash_algorithm sha1;
        authentication_method pre_shared_key;
        dh_group 2;
    }
}

# Spoke 2
remote 10.0.3.1 {
    exchange_mode main;
    proposal {
        encryption_algorithm 3des;
        hash_algorithm sha1;
        authentication_method pre_shared_key;
        dh_group 2;
    }
}

# Фаза 2 для Spoke 1
sainfo address 192.168.1.0/24 any address 192.168.2.0/24 any {
    pfs_group 2;
    encryption_algorithm 3des;
    authentication_algorithm hmac_sha1;
}

# Фаза 2 для Spoke 2
sainfo address 192.168.1.0/24 any address 192.168.3.0/24 any {
    pfs_group 2;
    encryption_algorithm 3des;
    authentication_algorithm hmac_sha1;
}
```

#### Конфигурация Hub (`/etc/ipsec-tools.conf`)

```bash
#!/usr/sbin/setkey -f
flush;
spdflush;

# Hub -> Spoke 1
spdadd 192.168.1.0/24 192.168.2.0/24 any -P out ipsec
    esp/tunnel/10.0.1.1-10.0.2.1/require;
spdadd 192.168.2.0/24 192.168.1.0/24 any -P in ipsec
    esp/tunnel/10.0.2.1-10.0.1.1/require;

# Hub -> Spoke 2
spdadd 192.168.1.0/24 192.168.3.0/24 any -P out ipsec
    esp/tunnel/10.0.1.1-10.0.3.1/require;
spdadd 192.168.3.0/24 192.168.1.0/24 any -P in ipsec
    esp/tunnel/10.0.3.1-10.0.1.1/require;
```

**Важно:** В конфигурации Hub должны быть прописаны отдельные секции `remote` и `sainfo` для каждого Spoke.

---

## Управление и диагностика

### Основные команды управления

| Задача | Команда |
|--------|---------|
| Применение политик SPD | `setkey -f /etc/ipsec-tools.conf` |
| Просмотр активных политик (SPD) | `setkey -DP` |
| Просмотр активных ассоциаций (SAD) | `setkey -D` |
| Полная очистка состояний и политик | `setkey -F && setkey -FP` |
| Запуск демона в отладочном режиме | `racoon -F -d` |
| Просмотр статуса Фазы 1 | `racoonctl show-sa isakmp` |
| Просмотр активных туннелей Фазы 2 | `racoonctl show-sa esp` |
| Ручной запуск согласования | `racoonctl vpn-connect <IP>` |
| Принудительное удаление SA | `racoonctl delete-sa isakmp` |

### Диагностика в ядре (XFRM)

В современных дистрибутивах для работы с ядром можно использовать как legacy-утилиту `setkey`, так и современные команды `ip xfrm`:

| Задача | Legacy (`setkey`) | Современный (`ip xfrm`) |
|--------|-------------------|-------------------------|
| Просмотр SAD (ключи) | `setkey -D` | `ip xfrm state` |
| Просмотр SPD (политики) | `setkey -DP` | `ip xfrm policy` |
| Очистка SAD | `setkey -F` | `ip xfrm state flush` |
| Очистка SPD | `setkey -FP` | `ip xfrm policy flush` |

### Проверка логов racoon

Логи демона направляются в `syslog` или `messages`:

```bash
# Просмотр логов racoon
sudo tail -f /var/log/syslog | grep racoon
# или
sudo journalctl -u racoon -f

# Фильтрация по уровню
sudo grep -i "racoon" /var/log/syslog | grep -i "error\|warn\|fail"
```

### Анализ трафика (tcpdump)

Для отладки процесса согласования и проверки прохождения данных:

```bash
# Просмотр процесса согласования (Фаза 1 и 2)
sudo tcpdump -n -i any port 500 or port 4500

# Просмотр зашифрованного трафика (ESP)
sudo tcpdump -n -i any proto 50

# Детальный захват для конкретного пира
sudo tcpdump -n -i any host 10.0.255.1 -w ipsec_debug.pcap

# Анализ дампа в Wireshark
wireshark ipsec_debug.pcap
```

### Валидация после настройки

После применения конфигурации обязательна проверка корректности:

```bash
# 1. Проверка SPD
sudo setkey -DP
# → Должны отображаться политики для нужных подсетей

# 2. Проверка SAD (после установки туннеля)
sudo setkey -D
# → Должны отображаться SA с SPI, ключами и алгоритмами

# 3. Проверка модулей ядра
lsmod | grep -E "af_key|esp4"
# → af_key    24576  1
# → esp4      20480  0

# 4. Пинг через туннель (с внутреннего хоста)
ping -c 4 192.168.255.1

# 5. Проверка маршрута
ip route get 192.168.255.1
# → 192.168.255.1 via ... dev eth0 src 192.168.1.1

# 6. Проверка статуса racoon
sudo racoonctl show-sa isakmp
sudo racoonctl show-sa esp
```

### Типовые проблемы и решения

| Проблема | Вероятная причина | Решение |
|----------|-------------------|---------|
| **Несоответствие селекторов трафика (TS)** | `sainfo` в `racoon.conf` не совпадает с `spdadd` в `setkey`. | Проверьте секции `sainfo` на обеих сторонах. Убедитесь, что `local_ts` и `remote_ts` симметричны. |
| **NAT-Traversal не работает** | Racoon требует явной поддержки NAT-T в ядре. | Включите `nat_traversal on;` в секции `remote`. Порт UDP 4500 должен быть открыт. |
| **Ошибки фрагментации** | KAME не поддерживает автоматическую подстройку MSS. | Настройте MSS Clamping: `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu` |
| **Слабая криптография** | Современные устройства запрещают 3DES/SHA1. | Используйте AES-256 и SHA-256 (если поддерживаются). В legacy-системах это невозможно. |
| **`failed to get sainfo`** | Несовпадение подсетей или алгоритмов в Фазе 2. | Проверьте секции `sainfo` в `racoon.conf` на обеих сторонах. |
| **`no policy found`** | Трафик не попадает под правила SPD. | Проверьте вызов `spdadd` в `ipsec-tools.conf`. |
| **`invalid secret`** | Ошибка аутентификации (PSK). | Проверьте `/etc/racoon/psk.txt` и права доступа (`chmod 600`). |
| **`phase1 negotiation failed`** | Блокировка UDP 500 или неверный IP адрес партнера. | Проверьте Firewall и маршрутизацию между шлюзами. |
| **`notify: no phase2 found`** | Партнер запрашивает туннель для подсети, которая не описана. | Синхронизируйте селекторы трафика (TS) на обеих сторонах. |
| **`could not get psk`** | Демон не может прочитать файл ключей. | Проверьте владельца файла (должен быть `root`) и права доступа. |

---

## Безопасность и рекомендации

### Критические ограничения KAME/racoon

1. **Только IKEv1:** Отсутствие поддержки IKEv2 делает невозможным использование современных функций (MOBIKE, EAP, Childless IKE_SA).
2. **Слабая криптография:** По умолчанию используются 3DES, SHA1, MODP 1024 — все признаны слабыми.
3. **Нет AEAD:** Отсутствие поддержки AES-GCM и ChaCha20-Poly1305.
4. **Производительность:** Стек KAME работает менее эффективно на многоядерных системах по сравнению с современным XFRM.
5. **Безопасность обновлений:** Пакет не обновляется с начала 2010-х годов, содержит неисправленные уязвимости.

### Рекомендации по использованию

| Сценарий | Рекомендация |
|----------|--------------|
| **Новая инсталляция** | Используйте **strongSwan** или **LibreSwan** (см. [основной документ](./ipsec.md)) |
| **Legacy-система (CentOS 7)** | Временное решение с ограничениями. Планируйте миграцию. |
| **Lab/тестирование** | Допустимо для изучения, но не для production. |
| **Продакшн** | **ЗАПРЕЩЕНО** использовать KAME/racoon. |

### Если необходимо использовать KAME/racoon

1. **Ограничьте доступ:** Только доверенные сети, строгий файрвол.
2. **Минимизируйте поверхность атаки:** Отключите ненужные сервисы.
3. **Регулярно проверяйте логи:** Ищите подозрительную активность.
4. **Планируйте миграцию:** Переходите на strongSwan/LibreSwan как можно скорее.

---

## Очистка и откат

### Остановка демона

```bash
# Остановка racoon
sudo killall racoon
# или
sudo systemctl stop racoon  # если настроен systemd

# Очистка состояний в ядре
sudo setkey -F && setkey -FP
```

### Удаление конфигурации

```bash
# Резервное копирование
sudo cp -r /etc/racoon /etc/racoon.bak
sudo cp /etc/ipsec-tools.conf /etc/ipsec-tools.conf.bak

# Удаление
sudo rm -rf /etc/racoon
sudo rm /etc/ipsec-tools.conf
```

### Полная очистка

```bash
# Остановка и очистка
sudo setkey -F && setkey -FP
sudo killall racoon

# Удаление пакетов
sudo apt-get remove --purge racoon ipsec-tools  # Debian/Ubuntu
# или
sudo yum remove racoon ipsec-tools              # CentOS/RHEL 7

# Очистка модулей ядра
sudo rmmod esp4
sudo rmmod af_key
```

---

## Граничные случаи и ограничения

### Совместимость с другими реализациями

| Устройство/ПО | Совместимость | Примечания |
|---------------|---------------|------------|
| Cisco IOS | Ограничённая | Требуется строгое соответствие алгоритмов. Modern Cisco запрещает 3DES/SHA1. |
| Juniper SRX | Ограничённая | Аналогично Cisco. |
| strongSwan | Невозможна | strongSwan не поддерживает IKEv1 по умолчанию (только если собран с `--enable-ikev1`). |
| LibreSwan | Невозможна | LibreSwan не поддерживает KAME/street-swap. |
| Windows Server | Ограничённая | Windows поддерживает IKEv1, но требует точной настройки. |
| MikroTik | Работает | RouterOS поддерживает IKEv1. |

### Максимальные значения

| Параметр | Значение | Примечание |
|----------|----------|------------|
| Количество туннелей | ~256 (ограничение ядра) | Зависит от памяти |
| Максимальный размер SA | 4 ГБ | 32-битный счётчик пакетов |
| Интервал rekeying | 8–24 часа | Рекомендуется для PFS |

### Проблемы производительности

1. **Однопоточность:** Racoon обрабатывает все соединения в одном потоке.
2. **PF_KEY overhead:** Каждое создание/удаление SA требует обмена сообщениями через PF_KEY.
3. **Нет аппаратного ускорения:** KAME не поддерживает AES-NI или QAT.

---

## Дополнительная информация

### Связанные документы

- **[IPsec (основной документ)](./ipsec.md)** — архитектура IKEv2, настройка strongSwan, XFRM.
- **[Диагностика IPsec (legacy)](./ipsec_troubleshooting.md)** — детальный разбор логов racoon и анализ дампов.
- **[Архитектура IPsec](./ipsec.md#ассоциации-безопасности-sa-и-политики-безопасности-sp)** — теоретические основы SAD/SPD.
- **[MTU и VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — детальный разбор накладных расходов.
