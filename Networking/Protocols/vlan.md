# VLAN (Virtual Local Area Network)

> **Примечание:** Этот файл был декомпозирован на тематические заметки. Актуальная информация находится в директории **[VLAN/](./VLAN/)**.

## Навигация

- **[VLAN/vlan_overview.md](./VLAN/vlan_overview.md)** — определения, назначение, типы портов, Access VLAN
- **[VLAN/vlan_8021q_frame.md](./VLAN/vlan_8021q_frame.md)** — формат кадра 802.1Q, тегирование
- **[VLAN/vlan_trunk_native.md](./VLAN/vlan_trunk_native.md)** — trunk-порты, Native VLAN
- **[VLAN/vlan_inter_vlan_routing.md](./VLAN/vlan_inter_vlan_routing.md)** — меж-VLAN маршрутизация, ROAS
- **[VLAN/vlan_linux_diagnostics.md](./VLAN/vlan_linux_diagnostics.md)** — настройка в Linux, диагностика

## Краткое описание

**VLAN (виртуальная локальная сеть)** — технология канального уровня (L2), позволяющая логически разделить одну физическую сеть на несколько независимых широковещательных доменов.

**Ключевые особенности:**
- Устройства в разных VLAN не могут взаимодействовать напрямую на L2
- Требуется L3-устройство для меж-VLAN маршрутизации
- Стандарт IEEE 802.1Q определяет формат тегирования

**Типы портов:**
- **Access Port** — принадлежит одному VLAN, трафик нетегированный
- **Trunk Port** — пропускает трафик нескольких VLAN с тегами 802.1Q
- **Hybrid Port** — может передавать тегированный и нетегированный трафик

## Связанные документы

- **[Ethernet](../ethernet.md)** — базовый протокол канального уровня
- **[ARP](../arp.md)** — broadcast-трафик в VLAN
- **[L2 Switching](../../Concepts/vlan_l2_switching/definitions_and_concepts.md)** — принцип работы коммутаторов
- **[Сетевая сегментация](../Concepts/network_segmentation_and_microsegmentation.md)** — стратегии сегментации

## Стандарты

- **IEEE 802.1Q** — стандарт тегирования VLAN
- **IEEE 802.1ad** — Q-in-Q (stacked VLANs)
