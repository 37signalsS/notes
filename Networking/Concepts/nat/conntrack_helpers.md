# Conntrack Helpers (ALG-модули)

## Определения

**Conntrack Helper** — модуль ядра Linux, расширяющий возможности conntrack для обработки протоколов с embedded IP-адресами и портами в payload (FTP, SIP, TFTP, H.323 и др.). Без helper'а conntrack «не видит» вложенные соединения внутри таких протоколов и не может корректно отслеживать их состояние.

**ALG (Application Layer Gateway)** — реализация conntrack helper'а, которая анализирует payload протокола (L7) и выполняет трансляцию адресов внутри него. Например, FTP Active-режим передаёт IP:Port клиента через команду `PORT` — ALG заменяет внутренний IP на публичный IP NAT-шлюза.

**Проблема:** Многие протоколы (FTP, SIP, H.323, LDAP) встраивают IP-адреса в payload. NAT модифицирует только заголовки (L3/L4), но не payload (L7). Без ALG получатель получает невалидный IP-адрес внутри протокольного сообщения.

## Теоретический блок

### Как работают Conntrack Helpers

```
Клиент (192.168.1.5) → FTP-команда: PORT 192,168,1,5,20,1
    │
    ▼
NAT-шлюз (conntrack + nf_conntrack_ftp helper)
    │  Helper распознаёт команду PORT
    │  Заменяет 192.168.1.5 на 203.0.113.1 (публичный IP)
    │  Сохраняет маппинг: внутренний IP:Port → внешний IP:Port
    │
    ▼
FTP-сервер (видит 203.0.113.1 в команде PORT)
    │  Устанавливает data-соединение на 203.0.1131:xxxx
    ▼
NAT-шлюз (DNAT на 192.168.1.5:xxxx)
```

### Поддерживаемые протоколы

| Протокол | Модуль | Порт(ы) | Что делает helper |
| :--- | :--- | :--- | :--- |
| **FTP** | `nf_conntrack_ftp` | 21 (command) | Трансляция IP в командах PORT/PASV |
| **SIP** | `nf_conntrack_sip` | 5060 (UDP/TCP) | Трансляция IP в SDP (RTP/RTCP порты) |
| **TFTP** | `nf_conntrack_tftp` | 69 (UDP) | Отслеживание UDP-сессий TFTP |
| **H.323** | `nf_conntrack_h323` | 1720 (TCP) | Трансляция IP в H.225/RAS |
| **AMANDA** | `nf_conntrack_amanda` | 10080 (TCP) | Трансляция IP в Amanda backup |
| **SANE** | `nf_conntrack_sane` | 6566 (TCP) | Трансляция IP в сканирование |

### Проблема с SIP ALG

SIP ALG — один из самых проблемных компонентов на файрволах. Большинство SIP ALG (включая встроенные в коммерческие файрволы) работают некорректно:

| Проблема | Описание |
| :--- | :--- |
| **Корректный SIP через TLS** | ALG не может расшифровать SIP-over-TLS (port 5061) |
| **Некорректная замена в SDP** | ALG ломает SDP-сессию, заменяя неверные поля |
| **Конфликт с SIP-сервером** | Asterisk/FreeSWITCH уже выполняют NAT-traversal |
| **Двойная трансляция** | ALG + NAT-шлюз = двойная замена адресов |

**Рекомендация SRE:** Отключать SIP ALG на файрволах и использовать STUN/TURN или SBC (Session Border Controller) для NAT-traversal.

### Безопасность Conntrack Helpers

Helpers выполняют deep packet inspection (DPI), что создаёт риски:

| Риск | Описание |
| :--- | :--- |
| **DoS через crafted packets** | Злоумышленник может отправить специфически сформированный пакет, который crash'ит helper |
| **Info leak** | Helper может раскрыть внутреннюю топологию сети |
| **Performance degradation** | DPI увеличивает задержку на каждый пакет |

**Рекомендация:** Загружайте только те helper'ы, которые реально необходимы.

## Практический блок

### Просмотр загруженных helpers

```bash
# Список загруженных модулей conntrack
lsmod | grep nf_conntrack
# → nf_conntrack_ftp       32768  1
# → nf_conntrack_sip       36864  0
# → nf_conntrack          176128  6 nf_conntrack_ftp,nf_nat,nf_conntrack_sip

# Просмотр доступных helpers
cat /proc/net/nf_conntrack_expect
# → Или через sysctl:
sysctl -a | grep nf_conntrack_helper
```

### Загрузка модуля (ручная)

```bash
# Загрузить helper для FTP
sudo modprobe nf_conntrack_ftp

# Загрузить helper для SIP
sudo modprobe nf_conntrack_sip

# Автозагрузка при старте системы
echo "nf_conntrack_ftp" | sudo tee /etc/modules-load.d/conntrack-ftp.conf
echo "nf_conntrack_sip" | sudo tee /etc/modules-load.d/conntrack-sip.conf
```

### Назначение helper'а для конкретного правила (iptables)

```bash
# FTP: helper назначается через -j ACCEPT с --helper
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 21 \
  -j ACCEPT

# Далее: conntrack автоматически применит helper для FTP-соединений

# Явное назначение helper'а (для非标准 портов):
iptables -A INPUT -p tcp --dport 2121 \
  -m conntrack --ctstate ESTABLISHED,RELATED \
  -m helper --helper ftp \
  -j ACCEPT
```

### Назначение helper'а (nftables)

```bash
# FTP helper для стандартного порта
nft add rule ip nat prerouting tcp dport 21 ct helper set "ftp"

# SIP helper для нестандартного порта
nft add rule ip nat prerouting tcp dport 5080 ct helper set "sip"

# Просмотр правил с helper'ами
nft list ruleset | grep "ct helper"
```

### Настройка helper'а для TFTP (PXE-загрузка)

```bash
# TFTP используется для PXE-загрузки серверов
# Без helper'а conntrack не отслеживает UDP-сессии TFTP

# Загрузка модуля
sudo modprobe nf_conntrack_tftp

# Правило для TFTP-сервера
iptables -A INPUT -p udp --dport 69 \
  -m conntrack --ctstate NEW \
  -j ACCEPT
```

### Отключение ненужных helpers (безопасность)

```bash
# Отключить все helpers (если не нужны)
sysctl -w net.netfilter.nf_conntrack_helper=0

# Включить конкретные helper'ы вручную
sysctl -w net.netfilter.nf_conntrack_helper=1
# И загрузить только нужные модули
modprobe nf_conntrack_ftp
```

## Дополнительная информация

- **[Теория NAT](./overview.md)** — взаимодействие NAT с протоколами (FTP, SIP, ICMP).
- **[Conntrack Bypass](./conntrack_bypass.md)** — NOTRACK и обход conntrack.
- **[Session Border Controller](../../../Networking/Concepts/session_border_controller.md)** — SBC для NAT-traversal VoIP.
- **[Netfilter в Linux](../../../Linux/Networking/Settings/tools/iptables_basics.md)** — модули Netfilter.
