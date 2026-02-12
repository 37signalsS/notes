# NetFlow

## Версии NetFlow

| Версия | Характеристики | Статус |
|--------|----------------|--------|
| **v1** | Первоначальная версия | Устарела |
| **v5** | Добавлены BGP AS, SNMP ifIndex | Широко используется |
| **v7** | Добавлена поддержка Catalyst | Cisco-specific |
| **v8** | Агрегация flow | Редко используется |
| **v9** | Шаблонная структура, flexible | Стандарт |
| **IPFIX** | IETF стандарт (v10) | Современный стандарт |

## NetFlow v5 Record

```
┌─────────────────────────────────────────────────────────────┐
│                  NETFLOW v5 RECORD                          │
├─────────────────────────────────────────────────────────────┤
│ src_ip          │ IP-адрес источника          │ 4 bytes     │
│ dst_ip          │ IP-адрес назначения         │ 4 bytes     │
│ next_hop        │ IP следующего хопа          │ 4 bytes     │
│ input           │ SNMP index input interface  │ 2 bytes     │
│ output          │ SNMP index output interface │ 2 bytes     │
│ dPkts           │ Количество пакетов          │ 4 bytes     │
│ dOctets         │ Количество байт             │ 4 bytes     │
│ First           │ SysUptime первого пакета    │ 4 bytes     │
│ Last            │ SysUptime последнего пакета │ 4 bytes     │
│ src_port        │ Порт источника              │ 2 bytes     │
│ dst_port        │ Порт назначения             │ 2 bytes     │
│ tcp_flags       │ TCP флаги                   │ 1 byte      │
│ prot            │ Протокол (TCP=6, UDP=17)    │ 1 byte      │
│ tos             │ Type of Service             │ 1 byte      │
│ src_as          │ AS источника                │ 2 bytes     │
│ dst_as          │ AS назначения               │ 2 bytes     │
│ src_mask        │ Маска сети источника        │ 1 byte      │
│ dst_mask        │ Маска сети назначения       │ 1 byte      │
└─────────────────────────────────────────────────────────────┘
```

## Как работает NetFlow

```
1. PACKET SAMPLING (опционально)
   ┌─────────────┐
   │   1:100     │  ← Не все пакеты анализируются
   │  sampling   │
   └──────┬──────┘
          │
2. FLOW CACHE
   ┌──────▼──────┐
   │  Flow 1:    │
   │ 192.168.1.1:443 → 10.0.0.5:12345
   │  Packets: 100, Bytes: 150000
   │  Start: 10:00:00, End: 10:00:15
   └─────────────┘
          │
3. ACTIVE/INACTIVE TIMEOUT
   ┌──────▼──────┐
   │ Flow expired│  (по времени или FIN/RST)
   └──────┬──────┘
          │
4. EXPORT TO COLLECTOR
   ┌──────▼──────┐
   │ NetFlow     │  ──► Collector (nfdump, Flowmon)
   │ Exporter    │      Анализ и визуализация
   └─────────────┘
```

## Настройка NetFlow на Cisco

```cisco
! Включение NetFlow на интерфейсе
interface GigabitEthernet0/0
 ip flow ingress
 ip flow egress

! Настройка экспорта
ip flow-export version 5
ip flow-export destination 192.168.1.100 2055
ip flow-export source Loopback0

! Настройка таймаутов
ip flow-cache timeout active 1
ip flow-cache timeout inactive 15

! Проверка
show ip cache flow
show ip flow export
```

## NetFlow Collector

```bash
# nfdump - популярный open-source collector

# Прослушивание NetFlow
nfcapd -w -D -l /var/log/nfdump -p 2055

# Анализ собранных данных
nfdump -r /var/log/nfdump/nfcapd.202401011200 \
    -s srcip/bytes \
    -o "fmt:%ts %sa %da %sp %dp %pkt %byt"

# Фильтрация
nfdump -r nfcapd.current -s record \
    'proto tcp and dst port 443 and bytes > 1000000'
```
