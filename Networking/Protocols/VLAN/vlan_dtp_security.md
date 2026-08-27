# Безопасность на канальном уровне: DTP и Port Security

## Определения

**DTP (Dynamic Trunking Protocol)** — проприетарный протокол Cisco, предназначенный для автоматического согласования типа соединения (Access или Trunk) и протокола инкапсуляции (802.1Q) между портами коммутаторов.

**Cisco Port Security** — механизм защиты уровня L2, позволяющий ограничивать количество и конкретный перечень MAC-адресов устройств, которым разрешен доступ к порту коммутатора. Основной инструмент борьбы с атаками типа MAC Flooding.

**VLAN Hopping (перескок между VLAN)** — метод атаки, позволяющий злоумышленнику отправлять трафик в другие VLAN в обход устройств маршрутизации, эксплуатируя настройки Native VLAN или протокол DTP.

## Базовые концепции

### Динамическое согласование транков (DTP)

Протокол DTP включен по умолчанию на большинстве коммутаторов Cisco. Для обмена информацией он использует многоадресный MAC-адрес `01-00-0C-CC-CC-CC`.

#### Режимы работы порта (DTP States)

| Режим | Описание |
| :--- | :--- |
| **Access** | Порт принудительно работает в режиме доступа. DTP-кадры не отправляются. |
| **Trunk** | Порт принудительно работает в режиме магистрали. Отправляет DTP-кадры для согласования с соседом. |
| **Dynamic Auto** | Порт готов стать транком, если сосед инициирует согласование (`Desirable` или `Trunk`). Сам инициатором не является. |
| **Dynamic Desirable** | Порт активно пытается стать транком, отправляя DTP-запросы. Станет транком, если сосед — `Auto`, `Desirable` или `Trunk`. |
| **Nonegotiate** | Порт в режиме Trunk, но отправка DTP-кадров полностью отключена. Используется для связи с оборудованием других вендоров. |

#### Матрица согласования (Negotiation Matrix)

| | Access | Dynamic Auto | Dynamic Desirable | Trunk |
| :--- | :---: | :---: | :---: | :---: |
| **Access** | Access | Access | Access | **Conflict** |
| **Dynamic Auto** | Access | Access | **Trunk** | **Trunk** |
| **Dynamic Desirable** | Access | **Trunk** | **Trunk** | **Trunk** |
| **Trunk** | **Conflict** | **Trunk** | **Trunk** | **Trunk** |

### Механизмы Port Security

Port Security применяется только на портах доступа (Access) или транковых портах с жестко заданным режимом. На динамических портах (DTP) включение Port Security невозможно.

#### Типы MAC-адресов в Port Security
1. **Static:** Настраиваются вручную администратором, сохраняются в конфигурационном файле.
2. **Dynamic:** Изучаются коммутатором при поступлении трафика, хранятся только в CAM-таблице (пропадают после перезагрузки).
3. **Sticky:** Изучаются динамически, но автоматически преобразуются в статические и записываются в `running-config`.

#### Режимы нарушения (Violation Modes)

При превышении лимита MAC-адресов или появлении неразрешенного адреса срабатывает один из режимов:

| Режим | Отбрасывание трафика | Логирование (SNMP/Syslog) | Счетчик нарушений | Статус порта |
| :--- | :---: | :---: | :---: | :---: |
| **Protect** | Да | Нет | Нет | Up |
| **Restrict** | Да | Да | Да | Up |
| **Shutdown** | Да | Да | Да | **Error-Disabled** |

#### Время жизни адресов (Aging)
Позволяет очищать таблицу Port Security от неиспользуемых адресов.
- **Absolute:** Удаление адреса строго через заданное время.
- **Inactivity:** Удаление адреса только в случае отсутствия трафика от него в течение заданного времени.

### VLAN Hopping: механизмы атак

1. **Switch Spoofing:** Злоумышленник эмулирует коммутатор в режиме `Dynamic Desirable`. Если порт жертвы находится в режиме по умолчанию (`Dynamic Auto`), устанавливается Trunk-соединение, открывающее доступ ко всем разрешенным VLAN.
2. **Double Tagging:** Кадр отправляется с двумя тегами 802.1Q. Внешний тег совпадает с Native VLAN транка. Первый коммутатор удаляет внешний тег, второй коммутатор видит внутренний тег и направляет кадр в целевую VLAN. Атака однонаправленная (ответный трафик не вернется).

## Практические сценарии

### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **Оборудование** | Коммутаторы Cisco Catalyst (2960, 3560, 3750, 9200, 9300, 9400, 9500, 9600) |
| **ПО** | Cisco IOS 12.2(25)SE или выше (для Port Security); Cisco IOS 15.0(2)SE или выше (для всех функций) |
| **Права** | Уровень привилегий `enable 15` или `privilege exec` |
| **Начальная настройка** | Интерфейсы в режиме `shutdown` (рекомендуется для новых портов) |
| **VLAN** | Созданные VLAN в VLAN-базе коммутатора (`vlan database` или `vlan <id>`) |

> **Важно:** Port Security не работает на динамических портах (Dynamic Auto/Desirable). Перед включением Port Security убедитесь, что порт находится в статическом режиме (Access или Trunk с `nonegotiate`).

### Сценарий 1: Отключение DTP и настройка безопасного Trunk

Безопасная конфигурация магистрального канала между коммутаторами.

#### Конфигурация

```cisco
interface GigabitEthernet1/0/24
 description *** Uplink to Core-SW ***
 # Фиксация режима и отключение DTP
 switchport mode trunk
 switchport nonegotiate
 
 # Безопасность Native VLAN
 switchport trunk native vlan 999
 # Тегирование Native VLAN (глобальная команда)
 # vlan dot1q tag native
 
 # Принцип минимизации привилегий
 switchport trunk allowed vlan 10,20
```

#### Валидация (ожидаемый результат)

```cisco
# Проверка режима порта и DTP
show interfaces switchport | include Administrative Mode|Negotiation of Trunking
# → Administrative Mode: trunk
# → Negotiation of Trunking: Off

# Проверка Native VLAN
show interfaces trunk | include Native VLAN
# → Native VLAN: 999

# Проверка разрешенных VLAN
show interfaces trunk | include Allowed VLAN
# → VLANs allowed on trunk: 10,20

# Проверка отсутствия DTP-кадров
show dtp interface Gi1/0/24
# → DTP interface state: Off
```

### Сценарий 2: Настройка Port Security с авто-восстановлением

Конфигурация порта доступа для рабочего места сотрудника.

#### Конфигурация

```cisco
interface GigabitEthernet1/0/5
 description *** User-Access-Port ***
 switchport mode access
 switchport access vlan 10
 switchport nonegotiate
 
 # Включение Port Security
 switchport port-security
 # Лимит: 2 адреса (например, ПК + IP-телефон)
 switchport port-security maximum 2
 # Сохранение адресов в конфигурации
 switchport port-security mac-address sticky
 
 # Очистка адресов при неактивности (30 минут)
 switchport port-security aging time 30
 switchport port-security aging type inactivity
 
 # Режим блокировки
 switchport port-security violation shutdown
exit

# Глобальная настройка авто-восстановления порта
# Автоматический вывод из состояния error-disabled через 5 минут
errdisable recovery cause psecure-violation
errdisable recovery interval 300
```

#### Валидация (ожидаемый результат)

```cisco
# Проверка включенного Port Security
show port-security interface Gi1/0/5
# → Port Security: Enabled
# → Port Status: Secure-up
# → Violation Mode: Shutdown
# → Maximum MAC Addresses: 2
# → Total MAC Addresses: 1
# → Sticky MAC Addresses: 1

# Просмотр sticky MAC-адресов
show port-security address interface Gi1/0/5
# → Security Stable-Priority Address(es)
# → -------------------------------------------
# → 001a.2b3c.4d5e    VLAN: 10    Gi1/0/5    STABLE

# Проверка состояния errdisable recovery
show errdisable recovery | include psecure
# → psecure-violation: Enabled
# → Recovery interval: 300 seconds
```

### Сценарий 3: Диагностика и мониторинг

#### Расширенные команды диагностики

```cisco
# Общая статистика по всем защищенным портам
show port-security
# → Secure Port AddressCount SecurityViolation SecurityAction
# → ------------- ------------ ------------------ --------------
# → Gi1/0/5             1                 0         Shutdown
# → Gi1/0/6             0                 0         Shutdown

# Детальная проверка параметров интерфейса
show port-security interface Gi1/0/5
# → Interface  : GigabitEthernet1/0/5
# → Port-security             : Enabled
# → Port-security Trap Shutdown: Disabled
# → Port Status               : Secure-up
# → Violation Mode            : Shutdown
# → Maximum MAC Addresses     : 2
# → Total MAC Addresses       : 1
# → Sticky MAC Addresses      : 1
# → Last source address       : 001a.2b3c.4d5e
# → Security Violation Count  : 0

# Просмотр базы MAC-адресов безопасности
show port-security address
# → Vlan    Mac Address       Type        Ports
# → ----    -----------       ----        -----
# → 10      001a.2b3c.4d5e    SecureSticky Gi1/0/5

# Проверка портов, отключенных системой безопасности
show interfaces status err-disabled
# → Port            Name               Status       Vlan
# → Gi1/0/12        *** User ***       err-disabled 10

# Просмотр причин errdisable
show interfaces Gi1/0/12 status
# → Port            Name               Status       Vlan
# → Gi1/0/12        *** User ***       err-disabled 10
# → Err-Disable Reason: psecure-violation

# Мониторинг DTP-событий в реальном времени
debug dtp packets
# → DTP: Sending packet on GigabitEthernet1/0/24 (None)
# → DTP: Received packet on GigabitEthernet1/0/24 from 001a.2b3c.4d5e

# Просмотр VLAN-тегов на интерфейсе
show interfaces switchport | include Trunking Native VLAN|Access VLAN
# → Access VLAN: 10
# → Trunking Native Mode VLAN: 999
```

## Дополнительная информация

### Конфигурация Port Security на Juniper Junos

Juniper не поддерживает DTP (протокол Cisco), но предоставляет аналогичные механизмы Port Security.

```juniper
# Защита Access-порта (MU-series, EX-series)
interfaces ge-0/0/1 {
    unit 0 {
        family ethernet-switching {
            interface-mode access;
            vlan {
                members vlan-users;
            }
            storm-control default;
        }
    }
}

# Ограничение MAC-адресов на порту
ethernet-switching-options {
    secure-access-port {
        interface ge-0/0/1.0;
        mac-limit {
            packet-action drop;
            limit 2;
        }
        mac-learn {
            disable;
        }
    }
    # Глобальная настройка sticky MAC
    secure-access-port {
        interface ge-0/0/1.0;
        mac-limit {
            maximum 2;
        }
    }
}

# Проверка Port Security на Juniper
# show ethernet-switching secure-access-port
# show ethernet-switching table interface ge-0/0/1
```

### Конфигурация Port Security на Arista EOS

```arista
# Включение Port Security на Access-порту
interface Ethernet1
 description *** User-Access-Port ***
 switchport mode access
 switchport access vlan 10
 switchport nonegotiate

# Включение Port Security
 switchport port-security
 switchport port-security maximum 2
 switchport port-security mac-address sticky
 switchport port-security violation shutdown

# Проверка Port Security на Arista
# show port-security
# show port-security interface Ethernet1
# show port-security addresses
```

### Типичные ошибки и их решения (Troubleshooting)

| Проблема | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Port Security не включается** | Команда `switchport port-security` отклоняется | Порт в динамическом режиме (Dynamic Auto/Desirable) | Переключите порт в статический режим: `switchport mode access` или `switchport mode trunk` + `switchport nonegotiate` |
| **Sticky MAC не сохраняется** | После перезагрузки MAC-адреса пропадают | Не включен `switchport port-security mac-address sticky` | Добавьте команду `switchport port-security mac-address sticky` |
| **Порт в err-disabled, не восстанавливается** | Порт в состоянии err-disabled, авто-восстановление не работает | `errdisable recovery` не включен или причина не указана | Включите: `errdisable recovery cause psecure-violation` + `errdisable recovery interval 300` |
| **VLAN Hopping (Double Tagging)** | Трафик появляется в неправильном VLAN | Native VLAN не изменена с VLAN 1 | Измените Native VLAN: `switchport trunk native vlan 999` + включите тегирование: `vlan dot1q tag native` |
| **DTP атака (Switch Spoofing)** | Сторонний коммутатор устанавливает Trunk | DTP включен на Access-порту | Отключите DTP: `switchport nonegotiate` на всех портах |
| **MAC Flooding** | Коммутатор работает как хаб (весь трафик flooding) | CAM-таблица переполнена | Включите Port Security с лимитом MAC-адресов |
| **Native VLAN mismatch** | Широковещательный трафик в неправильном VLAN | Разные Native VLAN на两端 Trunk-порта | Установите одинаковую Native VLAN на обоих концах Trunk |

### Порядок диагностики

1. **Проверка режима порта:** `show interfaces switchport` — убедитесь, что порт в статическом режиме.
2. **Проверка Port Security:** `show port-security interface <iface>` — проверьте статус и лимиты.
3. **Проверка MAC-адресов:** `show port-security address` — убедитесь, что нужные MAC-адреса в таблице.
4. **Проверка errdisable:** `show interfaces status err-disabled` — найдите отключенные порты.
5. **Проверка DTP:** `show dtp interface <iface>` — убедитесь, что DTP отключен.
6. **Просмотр логов:** `show logging | include PORT_SECURITY` — проверьте события нарушений.

### Best Practices

1. **Отключайте DTP на всех портах:** Используйте `switchport nonegotiate` на Access и Trunk портах.
2. **Используйте статические режимы:** Никогда не оставляйте порты в Dynamic Auto/Desirable.
3. **Ограничивайте VLAN на Trunk:** `switchport trunk allowed vlan <list>` — только необходимые VLAN.
4. **Изменяйте Native VLAN:** Не используйте VLAN 1. Установите dedicated Native VLAN (например, 999).
5. **Включайте Port Security:** На всех Access-портах с лимитом MAC-адресов.
6. **Используйте Sticky MAC:** Автоматическое обучение + сохранение в конфигурации.
7. **Настройте errdisable recovery:** Автоматическое восстановление портов через заданное время.
8. **Включайте BPDU Guard:** На всех Access-портах для предотвращения подключения коммутаторов.
9. **Мониторьте нарушения:** Настройте SNMP-алерты или Syslog для Port Security violation.
10. **Документируйте VLAN-план:** Ведите таблицу VLAN ID ↔ назначение ↔ диапазоны IP.

### Edge Cases

#### 1. Port Security + 802.1X

Если на порту включен 802.1X, Port Security работает только после успешной аутентификации. Порты в состоянии ` unauthorized` не могут пройти Port Security learning.

#### 2. Port Security + DHCP Snooping

При использовании Port Security + DHCP Snooping убедитесь, что `switchport port-security mac-address sticky` добавляет MAC в таблицу DHCP Snooping. В противном случае IP Source Guard не сможет работать.

#### 3. Trunk Port + Port Security

Port Security работает на Trunk-портах, но лимит MAC-адресов applies ко всем VLAN суммарно. Используйте `switchport port-security maximum <N>` с учетом количества MAC-адресов во всех разрешенных VLAN.

#### 4. Максимальное количество sticky MAC-адресов

Cisco Catalyst поддерживает до 8192 sticky MAC-адресов на модуле. Для крупных сетей используйте `switchport port-security maximum` с осторожностью.

#### 5. errdisable + Spanning Tree

Если порт заблокирован из-за Port Security и BPDU Guard одновременно, причина будет только одна (та, которая сработала первой). Проверяйте обе причины при диагностике.

### Рекомендации по L2 Hardening

- **Storm Control:** Ограничение интенсивности широковещательного (Broadcast) трафика для предотвращения перегрузки CPU коммутатора.
- **BPDU Guard:** Обязательная функция на всех Access-портах (`spanning-tree bpduguard enable`). Отключает порт при попытке подключения стороннего коммутатора.
- **Root Guard:** Защита от появления несанкционированного Root Bridge в топологии STP.
- **DHCP Snooping:** Механизм фильтрации нелегитимных DHCP-ответов и база для работы DAI и IP Source Guard.

### Связанные документы

- **[VLAN — обзор](../vlan.md)** — фундаментальные принципы сегментации.
- **[Trunk и Native VLAN](./vlan_trunk_native.md)** — глубокое погружение в работу магистралей.
- **[Формат кадра 802.1Q](./vlan_8021q_frame.md)** — детализация полей тега.
- **[DHCP Snooping](../DHCP/dhcp_security.md)** — защита от Rogue DHCP и атак на пул адресов.
- **[Spanning Tree Protocol (STP)](../stp.md)** — механизмы предотвращения петель и функции защиты.
- **[Жёсткая защита L2](./vlan_security_hardening.md)** — комплексная защита (DHCP Snooping, DAI, IPSG, BPDU Guard, Storm Control).
- **[Агрегация каналов (LACP)](../../Concepts/link_aggregation.md)** — Port-Channel для отказоустойчивости trunk.
