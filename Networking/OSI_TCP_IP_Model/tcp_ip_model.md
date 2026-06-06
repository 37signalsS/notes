# Модель TCP/IP

## Определения

**Модель TCP/IP (Transmission Control Protocol/Internet Protocol)** — практическая многоуровневая модель сетевого взаимодействия, стандарт де-факто для современного Интернета. В отличие от теоретической [модели OSI](./osi_model.md) (Open Systems Interconnection), разработана на основе реально существующих протоколов.

**Стек протоколов TCP/IP** — иерархический набор протоколов, реализующий модель TCP/IP. Название происходит от двух ключевых протоколов: TCP и IP (Internet Protocol).

### История и стандарты

| Параметр | Значение |
| :--- | :--- |
| **Разработчик** | DARPA (Defense Advanced Research Projects Agency) / IETF (Internet Engineering Task Force) |
| **Год появления** | 1970-е (TCP — 1974, разделение на TCP/IP — 1978) |
| **Стандарты** | RFC (Request for Comments) |
| **Ключевые RFC** | RFC 791 (IP, STD 5), RFC 9293 (TCP, **заменяет RFC 793**, август 2022, STD 7), RFC 768 (UDP) |
| **Текущий статус** | Основной стандарт Интернета |

## Базовые концепции

### Уровни модели TCP/IP

В реальности интернет работает по модели TCP/IP, где уровней всего 4, а не 7. Это связано с тем, что разделение на 7 слоев хорошо выглядит на бумаге, но в реальных протоколах границы между уровнями 5, 6 и 7 (сеансовый, представления, прикладной) размыты. HTTP, TLS, DNS — все они работают на прикладном уровне.

| Уровень | Соответствие OSI | Функции | Протоколы |
| :--- | :--- | :--- | :--- |
| **4. Прикладной (Application)** | L7, L6, L5 | Взаимодействие с приложениями, представление данных, сеансы | [HTTP](../Protocols/HTTP/http_basics.md) (HyperText Transfer Protocol), [DNS](../Protocols/DNS/dns.md) (Domain Name System), SMTP (Simple Mail Transfer Protocol), FTP (File Transfer Protocol), [TLS](../Protocols/tls.md) (Transport Layer Security) | [application_layer.md](./application_layer.md) |
| **3. Транспортный (Transport)** | L4 | Доставка между процессами, надёжность, поток | [TCP](../Protocols/TCP/overview.md), [UDP](../Protocols/udp.md) (User Datagram Protocol), SCTP (Stream Control Transmission Protocol) | [transport_layer.md](./transport_layer.md) |
| **2. Сетевой (Internet)** | L3 | Глобальная адресация, маршрутизация, фрагментация | [IP](../Protocols/IP_addressing/ip_overview.md), [ICMP](../Protocols/ICMP/icmp_overview.md) (Internet Control Message Protocol), [ARP](../Protocols/arp.md) (Address Resolution Protocol), OSPF (Open Shortest Path First), [BGP](../Protocols/bgp.md) (Border Gateway Protocol) | [Network_layer/Concepts/network_layer_overview.md](./Network_layer/Concepts/network_layer_overview.md) |
| **1. Канальный (Network Access)** | L2, L1 | Доставка в пределах ЛВС | [Ethernet](../Protocols/ethernet.md), Wi-Fi, PPP (Point-to-Point Protocol) | [data_link_layer.md](./data_link_layer.md), [physical_layer.md](./physical_layer.md) |

#### Краткое описание уровней

**1. Канальный уровень (Network Access Layer)**

- Физическая доставка в пределах локальной сети
- Адресация: [MAC-адреса](../Concepts/mac_address.md) (Media Access Control)
- Оборудование: коммутаторы, мосты, сетевые карты

**2. Межсетевой уровень (Internet Layer)**

- Маршрутизация между сетями (internetworking)
- Адресация: [IP-адреса](../Protocols/IP_addressing/ip_overview.md) (IPv4/IPv6)
- Оборудование: маршрутизаторы, L3-коммутаторы

**3. Транспортный уровень (Transport Layer)**

- Связь между приложениями через **[порты](../Concepts/network_ports.md)**
- Надёжная (TCP) или быстрая (UDP) доставка
- Оборудование: хосты, L4-брандмауэры, L4-балансировщики

**4. Прикладной уровень (Application Layer)**

- Протоколы пользовательских приложений
- Оборудование: хосты, прокси-серверы, L7-балансировщики, WAF (Web Application Firewall)

### Инкапсуляция и стек протоколов

```
Данные приложения (HTTP/DNS/SMTP)
         ↓
[TCP/UDP заголовок] + Данные = Сегмент/Дейтаграмма
         ↓
[IP заголовок] + Сегмент = IP-пакет
         ↓
[Ethernet заголовок] + Пакет + FCS = Кадр
         ↓
Биты (электрические/световые сигналы)
```

**Процесс:**

1. Данные L7 помещаются в транспортный сегмент (TCP/UDP)
2. Сегмент инкапсулируется в межсетевой пакет (IP)
3. Пакет заключается в канальный кадр (Ethernet)
4. Кадр преобразуется в биты для передачи. Включает FCS (Frame Check Sequence) для проверки целостности.

На принимающей стороне — обратный процесс (**декапсуляция**).

## Практические сценарии

### Сценарий 1: Запрос веб-страницы

| Шаг | Уровень | Действие |
| :--- | :--- | :--- |
| 1 | Прикладной | Браузер формирует HTTP GET-запрос |
| 2 | Транспортный | Создание TCP-сегмента (порт клиента → порт 443) |
| 3 | Сетевой | Создание IP-пакета (IP клиента → IP сервера) |
| 4 | Канальный | Инкапсуляция в Ethernet-кадр (MAC шлюза через ARP) |
| 5 | Маршрутизация | Роутеры перенаправляют пакет по IP назначения |
| 6 | Декапсуляция | Сервер распаковывает пакет, HTTP-запрос доставляется веб-серверу |

### Сценарий 2: Получение IP-адреса по DHCP

| Шаг | Уровень | Действие |
| :--- | :--- | :--- |
| 1 | Канальный | Широковещательный DHCPDISCOVER (`FF:FF:FF:FF:FF:FF`) |
| 2 | Канальный | DHCP-сервер отвечает DHCPOFFER с предложением IP |
| 3 | Канальный | Устройство отправляет DHCPREQUEST |
| 4 | Канальный | Сервер финализирует DHCPACK (аренда адреса) |

**Особенность:** Весь обмен происходит по протоколу DHCP (Dynamic Host Configuration Protocol) в пределах одного широковещательного домена (ЛВС).

## Дополнительная информация

### Сравнение с моделью OSI

| Уровни OSI | Уровень TCP/IP | Отличия |
| :--- | :--- | :--- |
| L7 + L6 + L5 | **Прикладной** | TCP/IP объединяет верхние 3 уровня OSI. Шифрование, кодирование — в прикладном уровне (например, [TLS](../Protocols/tls.md)) |
| L4 | **Транспортный** | Функциональность схожа |
| L3 | **Сетевой (Internet)** | Уровень IP — центральный элемент модели |
| L2 + L1 | **Канальный (Network Access)** | TCP/IP не детализирует, полагается на существующие технологии |

### См. также
- [Модель OSI](./osi_model.md) — теоретическая эталонная модель
- [Транспортный уровень](./transport_layer.md) — подробный разбор L4
- [Сетевой уровень](./Network_layer/Concepts/network_layer_overview.md) — подробный разбор L3
