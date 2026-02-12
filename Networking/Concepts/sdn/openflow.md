# OpenFlow Protocol

## Принцип работы

OpenFlow — это первый стандартный протокол для SDN, разработанный ONF (Open Networking Foundation).

```
┌─────────────────────────────────────────────────────────────┐
│                    OPENFLOW SWITCH                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Flow Table (0)                         │    │
│  │  ┌───────────────────────────────────────────────┐  │    │
│  │  │ Match                    │ Action             │  │    │
│  │  ├──────────────────────────┼────────────────────┤  │    │
│  │  │ src_ip=10.0.0.0/24       │ output:port2       │  │    │
│  │  │ dst_port=80              │ output:controller  │  │    │
│  │  │ vlan=100                 │ set_field:vlan=200 │  │    │
│  │  └──────────────────────────┴────────────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
│                         ↓                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Flow Table (1)                         │    │
│  └─────────────────────────────────────────────────────┘    │
│                         ↓                                   │
│                    ...                                      │
└─────────────────────────────────────────────────────────────┘
```

## Flow Table Entry

```
┌─────────────────────────────────────────────────────────────┐
│                    FLOW ENTRY                               │
├─────────────────────────────────────────────────────────────┤
│ MATCH FIELDS (L2/L3/L4)          │ PRIORITY │ COUNTERS      │
│ - Ingress port                   │          │ - Byte count  │
│ - Packet headers (MAC/IP/TCP)    │          │ - Packet cnt  │
│ - Metadata                       │          │               │
├─────────────────────────────────────────────────────────────┤
│ INSTRUCTIONS                                                │
│ - Apply Actions: (output port, modify header, drop)         │
│ - Goto Table: (переход к следующей таблице)                 │
│ - Write Metadata                                            │
├─────────────────────────────────────────────────────────────┤
│ TIMEOUTS                                                    │
│ - Idle timeout (удалить если неактивен)                     │
│ - Hard timeout (удалить по истечении времени)               │
├─────────────────────────────────────────────────────────────┤
│ COOKIE (идентификатор для фильтрации)                       │
│ FLAGS                                                       │
└─────────────────────────────────────────────────────────────┘
```

## OpenFlow Actions

| Action | Описание |
|--------|----------|
| `output:port` | Отправить пакет на указанный порт |
| `drop` | Отбросить пакет |
| `set_field` | Изменить поле заголовка (MAC, IP, VLAN) |
| `push_vlan` | Добавить VLAN tag |
| `pop_vlan` | Удалить VLAN tag |
| `group` | Отправить в группу (для ECMP, multicast) |
| `meter` | Применить политику QoS |

## OpenFlow Messages

**Controller-to-Switch:**
- `Features` — получение возможностей switch
- `Config` — конфигурация switch
- `Modify-State` — добавление/удаление flow entries
- `Read-State` — чтение статистики
- `Send-Packet` — отправка пакета через switch
- `Barrier` — синхронизация

**Asynchronous (Switch-to-Controller):**
- `Packet-In` — неизвестный пакет (требуется решение)
- `Flow-Removed` — flow entry удален
- `Port-Status` — изменение статуса порта

## Пример работы OpenFlow

```
1. Первый пакет от Host A к Host B:
   
   Host A ──► OpenFlow Switch ──► Controller (Packet-In)
                                       │
                                       ▼
                              Controller изучает топологию
                              Устанавливает flow rules
                                       │
   Host A ◄────────────────────────────┘
         (Flow Mod: если dst=Host B → output port 2)

2. Последующие пакеты:
   
   Host A ──► OpenFlow Switch ──► Host B
              (совпадение flow rule,
               hardware forwarding)
```
