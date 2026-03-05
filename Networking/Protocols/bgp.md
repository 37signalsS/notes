# BGP (Border Gateway Protocol)

## Определения

**BGP (Border Gateway Protocol)** — протокол маршрутизации между автономными системами (EGP — Exterior Gateway Protocol), используемый для построения таблиц маршрутизации в сети Интернет. BGP отвечает за обмен информацией о доступности префиксов между автономными системами.

**Автономная система (AS)** — группа IP-сетей под единым административным управлением с общей политикой маршрутизации. Каждая AS имеет уникальный номер **ASN (Autonomous System Number)**.

**Ключевая особенность:** BGP — это **path-vector протокол**, который выбирает маршруты на основе политик, а не только метрик. Это делает его протоколом достижения консенсуса в глобальном масштабе.

## Базовые концепции

### Типы BGP

| Тип | Описание | Особенности |
|-----|----------|-------------|
| **eBGP (external BGP)** | Между различными AS | TTL=1 по умолчанию, требует прямого соединения (обычно) |
| **iBGP (internal BGP)** | Внутри одной AS | Требует full-mesh или route reflector, не меняет AS Path |

### Атрибуты BGP

BGP использует атрибуты для выбора наилучшего пути. Порядок выбора (BGP Best Path Selection Algorithm):

1. **Weight** (Cisco-specific) — локальный приоритет. Чем выше, тем лучше.
2. **Local Preference** — приоритет внутри AS. Чем выше, тем лучше (по умолчанию 100).
3. **Locally Originated** — предпочтительны локально originated маршруты.
4. **AS Path** — список AS, через которые проходит маршрут. Чем короче, тем лучше.
5. **Origin Type** — источник маршрута: IGP (`i`) < EGP (`e`) < Incomplete (`?`).
6. **MED (Multi-Exit Discriminator)** — подсказка для входящего трафика. Чем ниже, тем лучше.
7. **eBGP over iBGP** — eBGP маршруты предпочтительнее iBGP.
8. **IGP Metric** — до BGP next-hop. Чем ниже, тем лучше.
9. **ECMP** — равная стоимость → балансировка.

**Community** — метки для группировки префиксов и применения политик (например, `no-export`, `no-advertise`).

### Безопасность BGP: RPKI и ROA

**Проблема:** BGP доверяет объявлениям маршрутов по умолчанию, что позволяет злоумышленникам объявлять чужие префиксы (**BGP hijacking**).

**Решение: RPKI (Resource Public Key Infrastructure)**

- **ROA (Route Origin Authorization)** — криптографически подписанный объект, который авторизует AS объявлять определенный префикс.
- **ROV (Route Origin Validation)** — процесс проверки маршрутов против ROA.
- **Статусы валидации:**
  - `Valid` — ROA существует и совпадает
  - `Invalid` — ROA существует, но не совпадает (отклонять!)
  - `NotFound` — ROA отсутствует (принимать с осторожностью)

**Актуальность (2025):**

- Более **50%** IPv4 и IPv6 маршрутов покрыты RPKI ROA
- Крупные провайдеры (Cloudflare, Google, Akamai) отклоняют `Invalid` маршруты
- Рекомендуется включать RPKI validation на всех BGP-роутерах

**Пример настройки RPKI в FRRouting:**

```bash
router bgp 65001
  bgp rpki server tcp rpki.example.com 323
  address-family ipv4 unicast
    bgp rpki source cache
  exit-address-family
```

## Практические сценарии

### Платформы для BGP

#### Аппаратные решения

- **Cisco (IOS-XE, IOS-XR, NX-OS)** — enterprise и carrier-grade
- **Juniper (Junos OS)** — дата-центры и ISP
- **Arista (EOS)** — high-performance DC
- **Huawei (VRP)** — Азия и enterprise

#### Программные решения (Soft-router)

- **FRRouting (FRR)** — полноценный routing suite (BGP, OSPF, IS-IS)
- **BIRD** — легковесный, популярен на IXP
- **GoBGP** — Go-implementation с API
- **VyOS** — роутер на базе Linux
- **MikroTik (RouterOS)** — SMB сегмент

### Сценарий: Multi-homed подключение к интернету

**Задача:** Обеспечить отказоустойчивость при подключении к двум провайдерам.

**Конфигурация:**

```
                    AS 64500 (Your Network)
                   /                       \
              eBGP /                         \ eBGP
                  /                           \
         AS 1234 (Provider A)           AS 5678 (Provider B)
```

**Рекомендации:**

1. Получите собственный ASN и префикс у LIR/RIR
2. Настройте BGP с обоими провайдерами
3. Используйте Local Preference для выбора основного провайдера
4. Настройте RPKI validation для защиты от hijacking
5. Используйте BFD (Bidirectional Forwarding Detection) для быстрого обнаружения сбоев

### Сценарий: BGP в дата-центре

**Использование:** BGP для underlay сети в Clos/fat-tree топологиях.

**Преимущества:**

- ECMP (Equal-Cost Multi-Path) для балансировки
- Быстрая конвергенция с BFD
- Масштабируемость для больших DC

**Популярная практика:** eBGP между всеми уровнями (leaf-spine) с уникальным ASN на каждом устройстве.

## Дополнительная информация

### Порты и протоколы

- **Порт:** 179/TCP
- **Протокол:** TCP (гарантирует надежную доставку обновлений)

### Связанные документы

- [Сетевой уровень](../OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md) — основы маршрутизации
- [RPKI Deployment](https://rpki.readthedocs.io/) — документация по развёртыванию

### RFC

- **RFC 4271** — спецификация BGP-4
- **RFC 6811** — BGP Prefix Origin Validation (ROV)
- **RFC 8416** — RPKI-Router Protocol
