# VPN под DPI и в ограничивающих сетях

## Определения

**DPI (Deep Packet Inspection)** — фильтрация трафика по содержимому пакетов (не только портам): сигнатуры протоколов, TLS-отпечатки, SNI, размеры и частоты пакетов. **SNI (Server Name Indication)** — поле ClientHello, по которому DPI видит «домен назначения» даже в шифрованном TLS. **TLS fingerprint (JA3/JA4)** — отпечаток набора cipher/расширений ClientHello, позволяющий отличить TLS OpenVPN/nginx от браузера. **Обфускация** — преобразование сегментов трафика так, чтобы сигнатура не распознавалась автоматически. **TCP-over-TCP meltdown** — эффект деградации, когда TCP-данные инкапсулируются в TCP: каскад ретранотмитов и потерь, из-за чего пропускную способность проседает.

## Основные концепции

### Что DPI видит и блокирует

| Тип VPN | Признак для DPI | Метод обхода |
|---------|-----------------|--------------|
| WireGuard over UDP | характерный шум сигнатуры Noise_IK: стабильный размер пакетов (~148 байт), строгий интервал | редко эффективен на практике; варианты — UDP поверх TCP-соединений, «маскировка» |
| OpenVPN | сигнатура TLS + статический порт, отпечаток OpenVPN-стека TLS | порт 443 + `tls-crypt`/`-auth-nocache`, вариант «SSL путь» |
| IPsec (ESP/UDP) | UDP 500/4500, IKE-сигнатура, ESP payload | IKEv2 через дублирование или инкапсуляцию в TLS (криптографически спорно) |
| SS/Trojan-подобные обфускаторы | меняющийся паттерн | используются там, где нужна максимальная незаметность |

Важно: **обфускация ≠ гарантия незаметности** и не является защитой от национального блокировщика. Материал — для сценариев «рабочая сеть режет UDP/странные порты» и для понимания, какие приёмы бывают.

### Ключевые ограничения

- **TCP-over-TCP на OpenVPN поверх TCP 443** даёт meltdown (см. [openvpn.md](../Networking/Tunnels/openvpn.md)): работающая конфигурация — UDP+1472 MTU, но при блокировке UDP выбирают TCP 443 и мирятся с overhead или включают вариант «udp over tcp» туннелем.
- **WireGuard нельзя протолкнуть «как TLS»** без посторонней обвязки: чистый WG — UDP с фиксированной сигнатурой.
- Один прокси-хоп (например, nginx `stream`) снимает вопрос «порт 443 занят», но не снимает fingerprint — нужен полноценный TLS-Upon-TLS (OpenVPN внутри nginx stream с TLS-паспортом).

## Практические сценарии

### 1. OpenVPN поверх 443 с `tls-crypt` (классика обхода)

Самый распространённый производственный приём при «не работают странные UDP-порты». На сервере включается порт 443/tcp (или UDP 443), TLS-обфускация `tls-crypt`:

```text
# /etc/openvpn/server.conf — фрагмент
port 443
proto tcp
dev tun
tls-crypt /etc/openvpn/ta.key
tls-version-min 1.2
cipher AES-256-GCM
```

Полная настройка сервера/клиента и флаги — [OpenVPN — практическое руководство](../Networking/Tunnels/openvpn.md).

### 2. Проход WireGuard через «нестандартный» UDP-канал

Категория «не решается штатно». Часто встречаются связки вроде:

- **WireGuard в маскарадирующем порту**: запуск WG на порту 443/udp тоже не делает его «TLS», но снимает вопрос «файрвол режет нестандартные порты» там, где DPI выключен для 443.
- **udp2raw/gost-стиль**: заворачивание UDP-канала WireGuard во внешнее TCP-соединение (fake-флаг, fake-header). Работает, но добавляет overhead и чувствительность к RTT; ценой TCP-over-TCP meltdown при неверной настройке.
- **TUN/TAP поверх SSH/SOCKS**: WireGuard выполняется через туннель SSH (`wg-quick` на узле, доступном через bastion; связка описана в [SSH-туннели](../Linux/Security/ssh/ssh_usage_and_tunnels.md)). Приемлемо для единичных узлов, не для флота.

Для прозрачности: полностью «невидимого» WireGuard не существует без смены трафика на другой протокол, поэтому при жёстком DPI переходят на OpenVPN 443/tls-crypt или на mesh с релейными серверами (DERP/relay у [mesh-vpn-overview](./mesh-vpn-overview.md)).

### 3. TLS-туннель через nginx stream (443 + SNI-sharing)

Если на сервере уже живёт HTTPS (SNI запрошен другим приложением), OpenVPN можно «спрятать» за nginx `stream` с передачей по SNI:

```nginx
# /etc/nginx/nginx.conf — модуль stream
stream {
    map $ssl_server_name $vpndest {
        default                 vpn_backend;
        example.com             web_backend;
    }
    server {
        listen 443;
        ssl_preread on;
        proxy_pass $vpndest;
    }
    upstream vpn_backend  { server 127.0.0.1:1194; }
    upstream web_backend  { server 127.0.0.1:8443; }
}
```

DPI видит TLS-сессию на 443 к `example.com`; приложения без SNI (OpenVPN с включённым `tls-crypt` поверх TCP) попадают на VPN-бэкенд. Приём классический — «одному 443-порту, многим потребителям».

### 4. Диагностика «VPN не работает из конкретной сети»

```bash
# Проверка, жив ли UDP-порт вообще (например, 51820)
bash -c 'timeout 3 bash -c "echo > /dev/udp/vpn.example.com/51820" && echo UDP-ok'

# Сигнатура-проверка: как выглядит трафик WG/OpenVPN
sudo tcpdump -ni eth0 udp port 51820 -XX
# → пакеты одинакового размера, без «текста» — типичная сигнатура WG

# Есть ли блокировка по SNI/fingerprint: сравнить с эталоном из браузера
# Через Shadowsocks/OpenVPN — сервер TLS-фингерпринта совпадает ?
openssl s_client -connect vpn.example.com:443 -servername example.com 2>/dev/null | grep "subject="
```

Если UDP-порт жив, а handshake не устанавливается — проблема DPI/фильтрации; переходите на обфускацию (п. 1-3) или порт 443 с `tls-crypt`.

## Лучшие практики

- Сначала исключите нормальные причины: MTU (см. [MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)), firewall (см. [vpn_firewall_templates.md](../Networking/Tunnels/vpn_firewall_templates.md)), allowlist (см. [wireguard-security.md](./wireguard-security.md)).
- Не комбинируйте обфускацию поверх обфускации — ломается поддержка и усложняется мониторинг.
- Для регламентного контура сверьтесь с политикой безопасности: обход средств мониторинга провайдера может нарушать локальные правила.

## Дополнительная информация

- **[OpenVPN — практическое руководство](../Networking/Tunnels/openvpn.md)** — `tls-crypt`, порт 443, TCP-over-TCP, MTU
- **[SSH-туннели и bastion](../Linux/Security/ssh/ssh_usage_and_tunnels.md)** — сценарии выхода через промежуточные узлы
- **[vpn-monitoring.md](./vpn-monitoring.md)** — проверка «VPN-сервис жив» снаружи, blackbox-проба