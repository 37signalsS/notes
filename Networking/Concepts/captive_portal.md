# Captive Portal (Перехватывающий портал)

## Определения

**Captive Portal** — сетевая технология контроля доступа, предназначенная для принудительного взаимодействия пользователя с веб-интерфейсом до предоставления полного доступа к ресурсам сети.

Процесс функционирования:
1. Клиент подключается к сети (Wi-Fi или Ethernet) и получает сетевые настройки по протоколу **[DHCP](../Protocols/DHCP/dhcp_overview.md)**.
2. Сетевой шлюз (Network Access Server, NAS) блокирует весь трафик клиента, кроме разрешенного (Walled Garden).
3. При попытке обращения к любому веб-ресурсу шлюз перехватывает запрос и перенаправляет клиента на страницу авторизации.
4. После выполнения условий (ввод логина, просмотр рекламы, оплата) шлюз открывает доступ, привязывая авторизацию к MAC- или IP-адресу устройства.

## Основные концепции

### Архитектура и компоненты

Каптивный портал состоит из следующих компонентов:
- **NAS (Network Access Server)** — устройство, на котором работает портал; выполняет функции DHCP, DNS, фаервола и HTTP-редиректора.
- **УАМ-сервер (UAM — User Authentication Manager)** — веб-приложение, обслуживающее страницу авторизации, условия использования и обратные вызовы.
- **RADIUS-сервер** — бэкенд аутентификации, авторизации и аккаунтинга (AAA); хранит учетные данные, политики сессий и квоты.
- **Walled Garden** — набор правил L3/L4, разрешающих определенный трафик до авторизации (DNS, NTP, CDN портала, серверы аутентификации).
- **База данных сессий** — хранилище активных подключений, MAC/IP-привязок, оставшегося времени и объема трафика.

### Механизмы перенаправления и их ограничения

#### 1. DNS-перенаправление (DNS Redirection)
Шлюз перехватывает DNS-запросы и возвращает IP-адрес портала вместо реального IP.
- **Проблема DoH/DoT:** Современные браузеры и ОС используют **DNS-over-HTTPS** или **DNS-over-TLS**, что делает невозможным классический перехват DNS-трафика без разрыва TLS-соединения.
- **Кэширование:** Клиенты могут кэшировать фальшивый IP, что вызывает ошибки доступа после успешной авторизации.

#### 2. HTTP-перенаправление (L7 Hijacking)
Шлюз инспектирует трафик на порту 80 и возвращает HTTP-ответ `302 Found` или `307 Temporary Redirect`.
- **Проблема HTTPS и HSTS:** Попытка перехвата HTTPS-запроса (порт 443) приводит к критической ошибке безопасности (`NET::ERR_CERT_AUTHORITY_INVALID`). Если сайт включен в список **HSTS**, браузер полностью заблокирует соединение, не позволяя пользователю увидеть страницу портала.
- **Реализация на уровне фаервола:** Для перехвата HTTP-трафика используется правило `REDIRECT` в **iptables** или `redirect` в **nftables**, которое отправляет пакеты на порт listening-процесса UAM-сервера (обычно 3990 или 80).

#### 3. Walled Garden (Белый список)
Список разрешенных доменов и IP-адресов, доступных до авторизации.
- **Техническая сложность:** Современные веб-страницы порталов требуют загрузки ресурсов (шрифты, скрипты, аналитика) с внешних CDN. Необходимо разрешать не только основной домен портала, но и все сопутствующие FQDN.
- **Двууровневая конфигурация:** В большинстве решений (CoovaChilli, MikroTik, pfSense) Walled Garden разделяется на IP-based (точные адреса) и DNS-based (домены), так как до авторизации DNS-резолвинг может быть недоступен или ненадежен.

### Современные стандарты и автоматизация

#### RFC 8908 и RFC 8910
Современный подход заменяет "перехват" явным информированием клиента:
- **DHCP Option 114:** Шлюз передает URL портала непосредственно в DHCP-пакете.
- **IPv6 Router Advertisement (RA):** Аналогичный механизм для IPv6-сетей.
- **Captive Portal API (RFC 8908):** JSON-интерфейс, позволяющий устройству программно проверить статус сессии, остаток квоты и получить ссылку на страницу оплаты без открытия браузера.

#### Протокол WISPr (Wireless Internet Service Provider roaming)
Стандарт (версии 1.0 и 2.0), позволяющий клиентскому ПО (например, агрегаторам хотспотов) автоматически проходить авторизацию через POST-запросы к порталу, избавляя пользователя от ручного ввода данных.

## Механизмы обнаружения портала (CNA)

ОС используют специализированные службы **Captive Network Assistant (CNA)** для автоматического запуска браузера.

1. **Запрос зондирования (Probing):** ОС отправляет легкий HTTP-запрос (например, `http://connectivitycheck.gstatic.com/generate_204`).
2. **Анализ ответа:**
   - Ответ `204 No Content` — сеть свободна.
   - Ответ `200 OK` с измененным телом или редирект — сеть заблокирована порталом.
3. **Изоляция:** CNA запускается в песочнице (sandbox), чтобы предотвратить утечку cookies и данных из основного браузера до установления доверенного соединения.

## Технические нюансы и безопасность

### Влияние рандомизации MAC-адресов
Современные мобильные ОС (Android 10+, iOS 14+) по умолчанию используют случайные MAC-адреса для каждой Wi-Fi сети.
- **Последствие:** Если пользователь переподключится к сети, шлюз увидит "новое" устройство и потребует повторной авторизации.
- **Решение:** Использование Captive Portal API для привязки сессии к более стабильным идентификаторам или увеличение времени аренды DHCP.

### Проблемы безопасности и обхода

- **Изоляция клиентов (Client Isolation):** Настройка L2, запрещающая прямой обмен трафиком между устройствами в одной подсети. Критична для защиты от ARP-spoofing внутри публичной сети.
- **Туннелирование:**
  - **DNS-Tunneling:** Если шлюз разрешает неограниченные DNS-запросы на внешние серверы, данные можно передавать внутри имен хостов.
  - **ICMP-Tunneling:** Передача данных через тело пакетов `ping`.
- **Evil Twin:** Создание поддельной точки доступа с идентичным SSID и визуально похожим порталом для фишинга учетных данных.

## Практическая реализация

### Обзор решений

| Решение | Особенности | Сфера применения |
| :--- | :--- | :--- |
| **CoovaChilli** | Высокая гибкость, поддержка RADIUS/AAA. | Провайдеры (WISP), крупные сети. |
| **pfSense / OPNsense** | Встроенный модуль, управление ваучерами. | Офисы, малый бизнес. |
| **MikroTik Hotspot** | Интеграция с RouterOS, скриптинг. | HoReCa, региональные сети. |
| **Ubiquiti UniFi** | Облачное управление, дизайн портала. | Современные офисы, отели. |

### Предварительные требования

Общие требования для любого развертывания:
- **Сетеовая топология:** Минимум два интерфейса на NAS — внешний (WAN/UPSTREAM) и внутренний (LAN/HOTSPOT). Рекомендуется выделенная VLAN для гостевой сети.
- **Сертификат TLS:** Для HTTPS-портала требуется сертификат, признанный клиентскими ОС (публично доверенный CA или корневой сертификат, предустановленный на устройствах). Иначе браузер отклонит соединение до попытки аутентификации.
- **RADIUS-инфраструктура (опционально, но рекомендуется):** FreeRADIUS 3.x+, сетевой доступ к портам 1812/18120/UDP (auth/acct) и 1813/UDP (accounting).
- **DNS-резолвер:** Внутренний кэширующий резолвер (Unbound, dnsmasq, BIND) для обработки запросов из Walled Garden и перенаправления портала.
- **Брандмауэр:** nftables или iptables с поддержкой connection tracking (conntrack) для отслеживания состояний сессий.

### Сценарий 1: CoovaChilli + FreeRADIUS (Debian/Ubuntu Linux)

CoovaChilli — открытый контроллер доступа, работающий как пользовательское пространство (userspace) и взаимодействующий с ядром через TUN/TAP-интерфейс.

#### Шаг 1: Подготовка системы и установка

```bash
# Обновление индексов пакетов
sudo apt-get update

# Установка CoovaChilli и зависимостей
sudo apt-get install -y coova-chilli freeradius freeradius-mysql mysql-server apache2 php libapache2-mod-php

# Проверка версии CoovaChilli
chilli --version
# → CoovaChilli 1.6 (или новее)
```

#### Шаг 2: Настройка сетевых интерфейсов

Файл `/etc/network/interfaces` или Netplan (`/etc/netplan/*.yaml`):

```bash
# eth0 — внешний интерфейс (WAN), получает IP по DHCP от провайдера
auto eth0
iface eth0 inet dhcp

# eth1 — внутренний интерфейс (LAN/HOTSPOT), статический IP подсети гостей
auto eth1
iface eth1 inet static
    address 10.10.10.1/24
    # без gateway — NAS выступает шлюзом для этой подсети
```

Применение:

```bash
sudo netplan apply
# или
sudo systemctl restart networking
```

#### Шаг 3: Настройка DHCP-сервера для гостевой подсети

CoovaChilli может работать в режиме built-in DHCP или с внешним сервером. Для простоты используем `isc-dhcp-server`:

```bash
sudo apt-get install -y isc-dhcp-server
```

Конфигурация `/etc/dhcp/dhcpd.conf`:

```bash
subnet 10.10.10.0 netmask 255.255.255.0 {
    range 10.10.10.10 10.10.10.250;
    option routers 10.10.10.1;
    option domain-name-servers 10.10.10.1;
    option broadcast-address 10.10.10.255;
    default-lease-time 600;
    max-lease-time 3600;

    # Передача URL портала через DHCP Option 114 (RFC 8910)
    option captive-portal-url http://10.10.10.1:3990/cgi-bin/login;
}
```

Указание интерфейса в `/etc/default/isc-dhcp-server`:

```bash
INTERFACESv4="eth1"
```

#### Шаг 4: Настройка FreeRADIUS

Инициализация базы данных:

```bash
sudo mysql -u root -p -e "CREATE DATABASE radius;"
sudo mysql -u root -p radius < /etc/freeradius/3.0/mods-config/sql/main/mysql/schema.sql
```

Добавление тестового пользователя в `/etc/freeradius/3.0/mods-config/sql/main/mysql/insert_queries.sql` или через `radtest`:

```bash
# Тест аутентификации локально
sudo radtest testuser testpass 127.0.0.1 0 radiussecret
# → Received Access-Accept
```

#### Шаг 5: Конфигурация CoovaChilli

Основной конфиг `/etc/chilli/config`:

```bash
HS_NASID=hotspot1
HS_RADIUS=127.0.0.1
HS_RADIUS2=127.0.0.1
HS_RADIUS_SECRET=radiussecret
HS_UAMSERVER=http://10.10.10.1:3990
HS_UAMSECRET=uamsecret
HS_NETWORK=10.10.10.0
HS_NETMASK=255.255.255.0
HS_UAMLISTEN=10.10.10.1
HS_DYNIP=10.10.10.0
HS_STATIP=
HS_MACALLOW=
HS_MACTUNNEL=
HS_TCPTIMEOUT=600
HS_UAMUAA=http://10.10.10.1:3990/uaa
HS_UAMHOMEPAGE=http://10.10.10.1:3990/
```

Walled Garden в `/etc/chilli/hotspot` или через `HS_UAMALLOW`:

```bash
# Разрешение DNS и NTP до авторизации
HS_UAMALLOW="dns,ntp,10.10.10.1,107.178.250.42"
```

#### Шаг 6: Настройка фаервола (nftables)

```bash
# Включение IP forwarding
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.d/99-captive-portal.conf
sudo sysctl -p /etc/sysctl.d/99-captive-portal.conf

# Правило MASQUERADE для выхода в интернет
sudo nft add table inet filter
sudo nft add chain inet filter forward { type filter hook forward priority 0 \; policy drop \; }
sudo nft add rule inet filter forward iif "eth1" oif "eth0" ip saddr 10.10.10.0/24 ct state established,related accept
sudo nft add rule inet filter forward iif "eth0" oif "eth1" ip daddr 10.10.10.0/24 ct state established,related accept
sudo nft add rule inet filter forward iif "eth1" oif "eth0" ip saddr 10.10.10.0/24 masquerade
```

#### Шаг 7: Запуск сервисов

```bash
sudo systemctl restart isc-dhcp-server
sudo systemctl restart freeradius
sudo systemctl restart coova-chilli
sudo systemctl restart nftables

# Проверка статуса
sudo systemctl status coova-chilli
# → active (running)
```

### Сценарий 2: pfSense / OPNsense

pfSense и OPNsense имеют встроенный модуль Captive Portal, работающий через PF (Packet Filter) с интеграцией RADIUS.

#### Шаг 1: Подготовка интерфейсов

1. Назначить LAN-интерфейсу статический IP (например, `192.168.100.1/24`).
2. Подключить точку доступа к тому же сегменту (bridged) или настроить AP в режиме bridge.
3. Убедиться, что DHCP-сервер на этом интерфейсе включен и выдает IP из той же подсети.

#### Шаг 2: Создание зоны Captive Portal

1. Перейти в **Services > Captive Portal** (pfSense) или **Services > Captive Portal > Zones** (OPNsense).
2. Нажать **Add** и заполнить:
   - **Zone name:** `GuestNet`
   - **Interface:** `LAN`
   - **Max concurrent connections:** по желанию (например, 100)
   - **Idle timeout:** время бездействия в минунах (например, 30).
   - **Hard timeout:** принудительное отключение по времени (например, 1440 — сутки).
   - **After authentication Redirection URL:** `https://www.example.com` — куда перенаправлять после успешной авторизации.
3. Сохранить и применить изменения.

#### Шаг 3: Настройка аутентификации

Для локальной аутентификации:
1. Перейти в **System > User Manager > Add**.
2. Создать пользователя (например, `guest_user`).
3. Назначить привилегию **User — Services: Captive Portal login**.
4. Сохранить.

Для аутентификации через RADIUS:
1. Перейти в **System > User Manager > Authentication Servers**.
2. Добавить сервер RADIUS, указать IP, shared secret, порты 1812/1813.
3. В настройках зоны Captive Portal выбрать **Use authentication backend** и указать созданный RADIUS-сервер.

Для ваучеров:
1. Перейти во вкладку **Vouchers** зоны.
2. Включить **Enable Vouchers**.
3. Создать rolls (пакеты ваучеров) с указанием validity duration и количества кодов.
4. Экспортировать CSV для печати.

#### Шаг 4: Walled Garden

1. Перейти на вкладку **Allowed Hostnames** или **Walled Garden**.
2. Добавить домены/IP, необходимые для работы портала:
   - `localhost`, `127.0.0.1` — локальный портал.
   - Домены внешних аутентификаторов (Google, Facebook и т.д.), если используются социальный вход.
   - IP серверов аккаунтинга/контроллеров (для UniFi, Aruba и т.п.).

#### Шаг 5: Проверка

```bash
# Подключиться к сети и открыть любой сайт (например, example.com)
# Должен произойти редирект на страницу captive portal
# После ввода учетных данных — интернет должен заработать
```

### Сценарий 3: MikroTik RouterOS

MikroTik RouterOS имеет встроенный сервис Hotspot с поддержкой RADIUS и внешних порталов.

#### Шаг 1: Подготовка интерфейсов

```bash
# Вход через WinBox или Terminal (SSH)
# Предполагается:
# ether1 — WAN (получение IP от провайдера)
# ether2 — LAN/Hotspot (гостевая сеть)
```

#### Шаг 2: Настройка IP-адресации и DHCP

```bash
/ip address add address=10.10.20.1/24 interface=ether2
/ip pool add name=hotspot-pool ranges=10.10.20.10-10.10.20.250
/ip dhcp-server add name=hotspot-dhcp interface=ether2 address-pool=hotspot-pool lease-time=10m disabled=no
/ip dhcp-server network add address=10.10.20.0/24 gateway=10.10.20.1 dns-server=10.10.20.1
```

#### Шаг 3: Конфигурация Hotspot

```bash
/ip hotspot setup
# Мастер предложит выбрать интерфейс, адрес пула, DNS, имя сервера и т.д.
# После завершения мастера:
```

Или вручную:

```bash
/ip hotspot add name=hotspot1 interface=ether2 address-pool=hotspot-pool profile=hsprof1
/ip hotspot profile add name=hsprof1 hotspot-address=10.10.20.1 use-radius=yes
```

#### Шаг 4: Настройка RADIUS (опционально)

```bash
/radius add address=10.10.10.100 secret=radiussecret service=hotspot
/radius incoming set accept=yes
```

#### Шаг 5: Walled Garden

```bash
# Разрешение DNS перед авторизацией
/ip hotspot walled-garden add dst-host=8.8.8.8 comment="Google DNS"
/ip hotspot walled-garden add dst-host=1.1.1.1 comment="Cloudflare DNS"

# Разрешение внешнего портала (если используется UAM-редирект)
/ip hotspot walled-garden ip add dst-address=10.10.10.100 comment="UAM server"
```

Для DNS-имен (требует работающего DNS на MikroTik):

```bash
/ip hotspot walled-garden add dst-host=portal.example.com comment="Captive portal host"
```

#### Шаг 6: NAT для выхода в интернет

```bash
/ip firewall nat add chain=srcnat out-interface=ether1 action=masquerade src-address=10.10.20.0/24
```

### Валидация и проверка работоспособности

#### Проверка доступности портала

```bash
# Эмуляция запроса CNA (аналогично generate_204)
curl -s -o /dev/null -w "%{http_code}\n" http://connectivitycheck.gstatic.com/generate_204
# Ожидается: 204 (если сеть свободна) или 302/200 (если заблокирован порталом)

# Проверка HTTP-редиректа
curl -I http://example.com
# Ожидается: HTTP/1.1 302 Found или 307 Temporary Redirect с Location на портал

# Проверка DHCP Option 114
sudo tcpdump -i eth1 port 67 or port 68 -n -vv | grep -i "captive"
# В выводе DHCP Offer/Ack должен присутствовать Option 114
```

#### Проверка аутентификации

```bash
# Тест RADIUS доступа
echo "User-Name = testuser, User-Password = testpass, NAS-IP-Address = 10.10.10.1" | radclient -x 127.0.0.1 auth radiussecret
# Ожидается: Access-Accept

# Проверка сессии после авторизации
# На клиентском устройстве:
curl -s -o /dev/null -w "%{http_code}\n" http://connectivitycheck.gstatic.com/generate_204
# Ожидается: 204
```

#### Проверка изоляции и безопасности

```bash
# Проверка Client Isolation (L2)
# Попытка ping между двумя клиентами в той же подсети должна быть заблокирована
# На MikroTik/TopGate:
/ip hotspot print detail
# Проверка параметра `client-isolation`

# Проверка открытых портов NAS
sudo nmap -sT -p- 10.10.10.1
# Ожидается: открыты только 67, 68 (DHCP), 53 (DNS), 80/3990 (UAM), 1812, 1813 (RADIUS)
```

### Типичные ошибки и устранение неполадок

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| Портал не открывается | Walled Garden не настроен | Добавить IP/домен портала в Walled Garden. Проверить `HS_UAMALLOW` или `Allowed Hostnames`. |
| Ошибка `NET::ERR_CERT_AUTHORITY_INVALID` | Портал использует самоподписанный сертификат без доверия в ОС | Установить корневой сертификат на клиентские устройства или использовать публичный CA (Let's Encrypt). |
| `generate_204` возвращает 200 вместо 204 | CNA не может достичь сервера проверки из-за блокировки до авторизации | Разрешить `connectivitycheck.gstatic.com` и `*.gstatic.com` в Walled Garden. |
| Нет интернета после авторизации | Отсутствует правило MASQUERADE/NAT на NAS | Проверить `ip nat` или `nftables` правила для `masquerade`. |
| Бесконечный цикл редиректов | Неверный `After authentication Redirection URL` или циклическая зависимость DNS | Указать внешний доверенный URL (например, `https://www.google.com`), а не внутренний IP. |
| RADIUS timeout | Неверный shared secret или недоступность порта 1812/18120 | Проверить связность: `nc -zvu <radius-ip> 1812`; сравнить `radiussecret` в конфигах NAS и RADIUS. |
| DNS-Tunneling утечка | В Walled Garden разрешены внешние DNS-серверы | Запретить исходящие UDP/53 на WAN для гостевой подсети, разрешить только внутренний DNS. |
| Evil Twin / фишинг | Отсутствует 802.1X или WPA3-Enterprise | Перейти на WPA2/WPA3-Enterprise с RADIUS-аутентификацией вместо открытой сети с порталом. |

### Рекомендации и очистка

- **Используйте HTTPS для UAM-сервера:** Даже если портал кажется "внутренним", браузеры могут блокировать отправку credentials на HTTP. Обязательно настройте TLS с валидным сертификатом.
- **Ограничивайте время аренды DHCP:** Для публичных сетей используйте короткий `default-lease-time` (5–10 минут), чтобы быстро освобождать адреса и минимизировать окно атаки при компрометации.
- **Включите логирование RADIUS:** В FreeRADIUS активируйте модуль `linelog` или `rlm_sql` для записи сессий; это необходимо для расследования инцидентов.
- **Регулярно обновляйте пакеты:** CoovaChilli и MikroTik RouterOS имеют исторические уязвимости (например, переполнение буфера в старых версиях). Следите за CVE.
- **Обратный процесс (декомисcионинг):**
  - Отключение зоны: в pfSense/OPNsense — disable zone; в CoovaChilli — `systemctl stop coova-chilli && systemctl disable coova-chilli`; в MikroTik — `/ip hotspot disable`.
  - Удаление правил фаервола: удалить `MASQUERADE` и цепочки hotspot.
  - Очистка аренд DHCP: удалить файл `/var/lib/dhcp/dhcpd.leases` или сбросить leases в веб-интерфейсе.

### Крайние случаи и ограничения

- **DoS через наплыв DHCP-запросов:** Открытый Hotspot без rate-limit на DHCP-сервере уязвим для исчерпания пула адресов. Используйте `dhcp-max-lease-time` и `max-lease-num` в dnsmasq или `max-lease-time` в ISC DHCP.
- **IPv6 и RA:** В средах с IPv6 Router Advertisement клиент может получить глобальный адрес без прохождения через портал. Настройте `dhcpv6` с Option 114 или включите RA-guard на коммутаторе.
- **DoH/DoT на клиенте:** Если клиент использует системный DoH (например, Firefox с Cloudflare), классический DNS-редирект не сработает. Требуется блокировка HTTPS-трафика до авторизации или использование Captive Portal API (RFC 8908).
- **Веб-туннели (SSH over WebSocket, VPN через 443):** Клиенты могут обойти портал, устанавливая туннели через разрешенный HTTPS. Для предотвращения используDPI (Deep Packet Inspection) или анализ SNI на границе сети.

## Дополнительная информация

- **[Протокол TLS (Transport Layer Security)](../Protocols/tls.md)** — причины конфликтов порталов с HTTPS.
- **[DHCP: Обзор и работа протокола](../Protocols/DHCP/dhcp_overview.md)** — механизмы передачи опций (Option 114).
- **[Аутентификация и авторизация (RADIUS)](../../Security/Concepts/authentication_vs_authorization.md)** — серверная часть обработки запросов портала.
- **[Безопасность DNS](../Protocols/DNS/dns_security.md)** — влияние DoH и DoT на сетевой контроль.
